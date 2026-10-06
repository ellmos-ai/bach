import importlib
import socket
from contextlib import contextmanager

import pytest

base = "imported_capabilities.category_2_superior_solutions.action_journal"
a = importlib.import_module(base + ".adapter_bach")
core = importlib.import_module(base + ".action_journal")
smart = importlib.import_module(base + ".smart_inbox")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.mark.parametrize("operation", ["forward-move", "undo-move", "undo-copy"])
def test_lost_guard_during_final_hash_prevents_resource_mutation(
    tmp_path, monkeypatch, operation
):
    owned = [True]

    @contextmanager
    def guard(paths):
        assert all(p.is_relative_to(tmp_path) for p in paths)
        yield lambda: owned[0]

    src = tmp_path / "src"
    target = tmp_path / "target"
    src.write_bytes(b"private fixture")
    j = a.BachActionJournal(
        tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=guard
    )
    if operation.startswith("undo"):
        j.execute_actions(
            [a.FileActionStep(operation.split("-")[1], str(src), str(target))]
        )
    before = {p: p.read_bytes() if p.exists() else None for p in (src, target)}
    # Ownership expires while the final content check is reading an existing file.
    # The real unchanged hash function and actual rename/unlink remain in use.
    module = core if operation == "undo-copy" else smart
    original = module.file_sha256

    def expiring_hash(path):
        result = original(path)
        owned[0] = False
        return result

    monkeypatch.setattr(module, "file_sha256", expiring_hash)
    with pytest.raises(PermissionError):
        if operation == "forward-move":
            j.execute_actions([a.FileActionStep("move", str(src), str(target))])
        else:
            j.rollback()
    after = {p: p.read_bytes() if p.exists() else None for p in (src, target)}
    assert after == before, "resource changed after host lease became invalid"


@pytest.mark.parametrize(
    "kind, method",
    [
        ("GuardedPath", "mkdir"),
        ("Temps", "mkstemp"),
        ("OS", "fdopen"),
        ("Stream", "write"),
        ("Stream", "flush"),
        ("OS", "fsync"),
        ("OS", "replace"),
    ],
)
def test_every_persistence_boundary_denies_before_primitive(tmp_path, kind, method):
    import inspect

    @contextmanager
    def guard(paths):
        def check():
            frame = inspect.currentframe()
            try:
                while frame:
                    instance = frame.f_locals.get("self")
                    if (
                        frame.f_code.co_name == method
                        and type(instance).__name__ == kind
                    ):
                        return False
                    frame = frame.f_back
                return True
            finally:
                del frame

        yield check

    src = tmp_path / "src"
    target = tmp_path / "target"
    src.write_bytes(b"protected")
    j = a.BachActionJournal(
        tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=guard
    )
    with pytest.raises(PermissionError):
        j.execute_actions([a.FileActionStep("copy", str(src), str(target))])
    assert src.read_bytes() == b"protected" and not target.exists()
    assert not j._fds and not j._streams and j._checker is None
    assert not j._entry_lock.locked()
    if j.journal_file.exists():
        import json

        assert all(
            entry["status"] == "planned"
            for entry in json.loads(j.journal_file.read_text())["entries"]
        )


def test_private_bindings_keep_original_globals_and_path_owner(tmp_path):
    source_globals = dict(core.ActionJournal.execute.__globals__)
    smart_globals = dict(smart.undo_move.__globals__)

    @contextmanager
    def lease(paths):
        yield lambda: True

    @contextmanager
    def denied(paths):
        yield lambda: False

    one = a.BachActionJournal(
        tmp_path / "a" / "b" / "journal",
        "one",
        allowed_roots=(tmp_path,),
        mutation_guard=lease,
    )
    two = a.BachActionJournal(
        tmp_path / "journal2", "two", allowed_roots=(tmp_path,), mutation_guard=denied
    )
    assert type(one._core.path) is not type(two._core.path)
    assert type(one._core.path.parent) is type(one._core.path)
    assert type(one._core.path.resolve()) is type(one._core.path)
    assert one._core.execute.__func__.__code__ is core.ActionJournal.execute.__code__
    assert one._core.undo.__func__.__code__ is core.ActionJournal.undo.__code__
    bindings = one._core.undo.__func__.__globals__
    assert bindings["undo_move"].__code__ is smart.undo_move.__code__
    assert bindings["undo_move"].__globals__["replace"] is smart.replace
    assert bindings["ActionJournal"] is type(one._core)
    assert (
        type(one._core).__dict__["_planned_entries"].__func__.__code__
        is core.ActionJournal._planned_entries.__code__
    )
    assert core.ActionJournal.execute.__globals__ == source_globals
    assert smart.undo_move.__globals__ == smart_globals
    src = tmp_path / "src"
    src.write_bytes(b"private")
    out = tmp_path / "out"
    with pytest.raises(PermissionError):
        two.execute_actions([a.FileActionStep("copy", str(src), str(out))])
    assert one.execute_actions([a.FileActionStep("copy", str(src), str(out))])
    one.rollback()
    assert src.read_bytes() == b"private" and not out.exists()
    assert core.ActionJournal.execute.__globals__ == source_globals


def test_same_consumer_thread_reentry_refused(tmp_path):
    from threading import Event, Thread

    entered, exit_allowed = Event(), Event()

    @contextmanager
    def lease(paths):
        entered.set()
        assert exit_allowed.wait(5)
        yield lambda: True

    src = tmp_path / "src"
    src.write_bytes(b"private")
    out = tmp_path / "out"
    j = a.BachActionJournal(
        tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=lease
    )
    results = []

    def run():
        try:
            results.append(
                j.execute_actions([a.FileActionStep("copy", str(src), str(out))])
            )
        except (ValueError, OSError) as error:
            results.append(error)

    t = Thread(target=run)
    t.start()
    try:
        assert entered.wait(5)
        with pytest.raises(PermissionError, match="Concurrent"):
            j.execute_actions([a.FileActionStep("copy", str(src), str(out))])
    finally:
        exit_allowed.set()
        t.join(5)
    assert not t.is_alive() and results == [True]


def test_short_writes_complete_and_check_every_part(tmp_path, monkeypatch):
    real_fdopen = a.os.fdopen
    counts = []

    class Partial:
        def __init__(self, raw):
            self.raw = raw

        def write(self, data):
            counts.append(len(data))
            return self.raw.write(data[:3])

        def flush(self):
            return self.raw.flush()

        def close(self):
            return self.raw.close()

    monkeypatch.setattr(
        a.os, "fdopen", lambda *args, **kwargs: Partial(real_fdopen(*args, **kwargs))
    )
    checks = []

    @contextmanager
    def lease(paths):
        def check():
            checks.append(True)
            return True

        yield check

    src = tmp_path / "src"
    src.write_bytes(b"0123456789")
    out = tmp_path / "out"
    j = a.BachActionJournal(
        tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=lease
    )
    assert j.execute_actions([a.FileActionStep("copy", str(src), str(out))])
    assert out.read_bytes() == b"0123456789"
    assert len(checks) > len(counts) > 10
    j.rollback()


def test_unknown_proxy_mutations_and_foreign_fd_are_refused(tmp_path):
    @contextmanager
    def lease(paths):
        yield lambda: True

    j = a.BachActionJournal(
        tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=lease
    )
    bindings = j._core._write.__func__.__globals__
    for name in ("remove", "rename", "system", "open", "truncate", "chmod"):
        with pytest.raises(AttributeError):
            getattr(bindings["os"], name)
    with pytest.raises(PermissionError):
        bindings["os"].fdopen(1, "wb")
    with pytest.raises(PermissionError):
        j._core.path.touch()


def test_cleanup_after_revocation_preserves_own_temp_and_closes_handles(
    tmp_path, monkeypatch
):
    import inspect

    @contextmanager
    def lease(paths):
        def check():
            frame = inspect.currentframe()
            try:
                while frame:
                    if (
                        frame.f_code.co_name == "unlink"
                        and type(frame.f_locals.get("self")).__name__ == "OS"
                    ):
                        return False
                    frame = frame.f_back
                return True
            finally:
                del frame

        yield check

    def disk_failure(*args, **kwargs):
        raise OSError("injected final replace failure")

    monkeypatch.setattr(a.os, "replace", disk_failure)
    src = tmp_path / "src"
    src.write_bytes(b"protected")
    out = tmp_path / "out"
    j = a.BachActionJournal(
        tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=lease
    )
    with pytest.raises(PermissionError):
        j.execute_actions([a.FileActionStep("copy", str(src), str(out))])
    assert not j.journal_file.exists() and not out.exists()
    assert src.read_bytes() == b"protected"
    assert len(j.retained_temporary_paths) == 1
    assert not j._fds and not j._streams and j._checker is None


def test_partial_write_revocation_stops_next_part(tmp_path, monkeypatch):
    real_fdopen = a.os.fdopen
    owned = [True]
    counts = []

    class Partial:
        def __init__(self, raw):
            self.raw = raw

        def write(self, data):
            counts.append(len(data))
            n = self.raw.write(data[:3])
            owned[0] = False
            return n

        def flush(self):
            return self.raw.flush()

        def close(self):
            return self.raw.close()

    monkeypatch.setattr(
        a.os, "fdopen", lambda *args, **kwargs: Partial(real_fdopen(*args, **kwargs))
    )

    @contextmanager
    def lease(paths):
        yield lambda: owned[0]

    src = tmp_path / "src"
    src.write_bytes(b"protected")
    out = tmp_path / "out"
    j = a.BachActionJournal(
        tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=lease
    )
    with pytest.raises(PermissionError):
        j.execute_actions([a.FileActionStep("copy", str(src), str(out))])
    assert len(counts) == 1 and not j.journal_file.exists() and not out.exists()
    assert src.read_bytes() == b"protected"
    assert len(j.retained_temporary_paths) == 1
    assert j.retained_temporary_paths[0].stat().st_size == 3
    assert not j._fds and not j._streams


def test_independent_consumers_concurrent_opposite_guards(tmp_path):
    from threading import Barrier, Thread

    barrier = Barrier(2)
    results = {}

    def run(name, allowed):
        @contextmanager
        def lease(paths):
            barrier.wait(timeout=5)
            yield lambda: allowed

        src = tmp_path / f"src-{name}"
        target = tmp_path / f"out-{name}"
        src.write_bytes(name.encode())
        j = a.BachActionJournal(tmp_path / f"journal-{name}", name, allowed_roots=(tmp_path,), mutation_guard=lease)
        try:
            results[name] = j.execute_actions([a.FileActionStep("copy", str(src), str(target))])
        except PermissionError:
            results[name] = "denied"
        assert not j._fds and not j._streams

    yes = Thread(target=run, args=("yes", True))
    no = Thread(target=run, args=("no", False))
    yes.start()
    no.start()
    yes.join(5)
    no.join(5)
    assert not yes.is_alive() and not no.is_alive()
    assert results == {"yes": True, "no": "denied"}
    assert (tmp_path / "out-yes").read_bytes() == b"yes"
    assert not (tmp_path / "out-no").exists()


def test_zero_progress_write_fails_and_closes_private_handles(tmp_path, monkeypatch):
    real_fdopen = a.os.fdopen

    class NoProgress:
        def __init__(self, raw): self.raw = raw
        def write(self, data): return 0
        def close(self): self.raw.close()

    monkeypatch.setattr(a.os, "fdopen", lambda *args, **kwargs: NoProgress(real_fdopen(*args, **kwargs)))

    @contextmanager
    def lease(paths): yield lambda: True

    src, out = tmp_path / "src", tmp_path / "out"
    src.write_bytes(b"protected")
    j = a.BachActionJournal(tmp_path / "journal", "run", allowed_roots=(tmp_path,), mutation_guard=lease)
    with pytest.raises(OSError, match="valid progress"):
        j.execute_actions([a.FileActionStep("copy", str(src), str(out))])
    assert src.read_bytes() == b"protected" and not out.exists() and not j.journal_file.exists()
    assert not j._fds and not j._streams and not j.retained_temporary_paths
