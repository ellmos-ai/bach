"""T797: real byte/reopen evidence on temporary resources only."""
import inspect
import json
from contextlib import contextmanager
from threading import Lock

import pytest
from imported_capabilities.category_2_superior_solutions.action_journal.adapter_bach import (
    BachActionJournal,
    FileActionStep,
    file_sha256,
)


def journal(tmp_path, run_id="safe", guard=None):
    # The new explicit safety context is supplied when supported. This keeps
    # the original data-loss assertions runnable against the old API too.
    options = {}
    if "allowed_roots" in inspect.signature(BachActionJournal).parameters:
        @contextmanager
        def private_fixture_lease(paths):
            assert all(path.is_relative_to(tmp_path) for path in paths)
            yield lambda: True
        options = {"allowed_roots": (tmp_path,), "mutation_guard": guard or private_fixture_lease}
    return BachActionJournal(tmp_path / "journals", run_id, **options)


def source(tmp_path, name="source.bin", data=b"original\x00bytes\xff"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_success_reopen_undo_and_idempotence(tmp_path, operation):
    src = source(tmp_path)
    original = src.read_bytes()
    target = tmp_path / "out.bin"
    j = journal(tmp_path)
    assert j.execute_actions([FileActionStep(operation, str(src), str(target))])
    assert target.read_bytes() == original
    assert src.exists() == (operation == "copy")
    reopened = journal(tmp_path)
    reopened.rollback()
    assert src.read_bytes() == original
    assert not target.exists()
    reopened.rollback()
    assert src.read_bytes() == original


@pytest.mark.parametrize("operation", ["write", "delete", "unknown"])
def test_unsupported_operation_rejected_before_mutation(tmp_path, operation):
    src = source(tmp_path)
    target = source(tmp_path, "old.bin", b"old resource")
    j = journal(tmp_path)
    with pytest.raises((ValueError, PermissionError)):
        j.execute_actions([FileActionStep(operation, str(src), str(target))])
    assert src.read_bytes() == b"original\x00bytes\xff"
    assert target.read_bytes() == b"old resource"
    assert not j.journal_file.exists()


def test_expected_source_hash_preserved_and_checked(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "target"
    step = FileActionStep("copy", str(src), str(target), source_sha256="0" * 64)
    j = journal(tmp_path)
    with pytest.raises((ValueError, RuntimeError)):
        j.execute_actions([step])
    assert step.source_sha256 == "0" * 64
    assert not target.exists() and not j.journal_file.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_occupied_target_is_never_overwritten(tmp_path, operation):
    src = source(tmp_path)
    target = source(tmp_path, "old.bin", b"protected old bytes")
    j = journal(tmp_path)
    with pytest.raises((ValueError, FileExistsError, PermissionError)):
        j.execute_actions([FileActionStep(operation, str(src), str(target))])
    assert target.read_bytes() == b"protected old bytes"
    assert src.read_bytes() == b"original\x00bytes\xff"
    assert not j.journal_file.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_rollback_refuses_changed_target_without_touching_any_step(tmp_path, operation):
    a = source(tmp_path, "a")
    b = source(tmp_path, "b")
    ta, tb = tmp_path / "ta", tmp_path / "tb"
    j = journal(tmp_path)
    assert j.execute_actions([FileActionStep(operation, str(a), str(ta)), FileActionStep(operation, str(b), str(tb))])
    ta.write_bytes(b"foreign replacement")
    before = {path: path.read_bytes() if path.exists() else None for path in (a, b, ta, tb)}
    with pytest.raises((RuntimeError, PermissionError)):
        journal(tmp_path).rollback()
    assert {path: path.read_bytes() if path.exists() else None for path in before} == before


def test_rollback_refuses_occupied_move_source(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "target"
    j = journal(tmp_path)
    j.execute_actions([FileActionStep("move", str(src), str(target))])
    src.write_bytes(b"new foreign source")
    with pytest.raises((RuntimeError, PermissionError)):
        j.rollback()
    assert src.read_bytes() == b"new foreign source"
    assert target.read_bytes() == b"original\x00bytes\xff"


@pytest.mark.parametrize("run_id", ["../escape", "..", "bad/name", "bad\\name", "", "unsafe:name"])
def test_invalid_run_id_does_not_create_directories(tmp_path, run_id):
    with pytest.raises(ValueError):
        journal(tmp_path, run_id)
    assert not (tmp_path / "journals").exists()


def test_all_sources_validated_before_first_move(tmp_path):
    src = source(tmp_path)
    j = journal(tmp_path)
    with pytest.raises((ValueError, FileNotFoundError)):
        j.execute_actions([FileActionStep("move", str(src), str(tmp_path / "out")), FileActionStep("copy", str(tmp_path / "missing"), str(tmp_path / "out2"))])
    assert src.read_bytes() == b"original\x00bytes\xff"
    assert not (tmp_path / "out").exists()


def test_self_alias_and_cross_step_alias_rejected(tmp_path):
    a, b = source(tmp_path, "a"), source(tmp_path, "b")
    j = journal(tmp_path)
    with pytest.raises((ValueError, PermissionError)):
        j.execute_actions([FileActionStep("move", str(a), str(a.parent / "." / a.name))])
    with pytest.raises((ValueError, PermissionError, FileExistsError)):
        j.execute_actions([FileActionStep("move", str(a), str(b)), FileActionStep("move", str(b), str(tmp_path / "out"))])
    assert a.read_bytes() == b.read_bytes() == b"original\x00bytes\xff"


@pytest.mark.parametrize("result", [False, None, "FREE"])
def test_lock_or_unknown_guard_fail_closed(tmp_path, result):
    src = source(tmp_path)
    j = journal(tmp_path, guard=lambda paths: result)
    with pytest.raises(PermissionError):
        j.execute_actions([FileActionStep("copy", str(src), str(tmp_path / "out"))])
    assert not (tmp_path / "out").exists() and not j.journal_file.exists()


def test_reopen_checks_lock_again_before_undo(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "out"
    j = journal(tmp_path)
    j.execute_actions([FileActionStep("move", str(src), str(target))])
    with pytest.raises(PermissionError):
        journal(tmp_path, guard=lambda paths: False).rollback()
    assert not src.exists() and target.read_bytes() == b"original\x00bytes\xff"


class SimulatedPowerLoss(BaseException):
    pass


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_crash_after_action_before_receipt_reconciles_exact_retry(tmp_path, monkeypatch, operation):
    src = source(tmp_path)
    target = tmp_path / "target"
    j = journal(tmp_path)
    steps = [FileActionStep(operation, str(src), str(target), file_sha256(src))]
    original_write = j._core._write
    calls = 0
    def lose_power(payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SimulatedPowerLoss("resource mutation persisted, receipt did not")
        original_write(payload)
    monkeypatch.setattr(j._core, "_write", lose_power)
    with pytest.raises(SimulatedPowerLoss):
        j.execute_actions(steps)
    assert json.loads(j.journal_file.read_text())["entries"][0]["status"] == "planned"
    assert target.read_bytes() == b"original\x00bytes\xff"
    reopened = journal(tmp_path)
    assert reopened.execute_actions(steps)
    assert reopened.execute_actions(steps)
    reopened.rollback()
    assert src.read_bytes() == b"original\x00bytes\xff" and not target.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_crash_during_undo_reopen_preserves_original(tmp_path, monkeypatch, operation):
    src = source(tmp_path)
    target = tmp_path / "target"
    j = journal(tmp_path)
    j.execute_actions([FileActionStep(operation, str(src), str(target))])
    def lose_power(payload):
        raise SimulatedPowerLoss("undo persisted, receipt did not")
    monkeypatch.setattr(j._core, "_write", lose_power)
    with pytest.raises(SimulatedPowerLoss):
        j.rollback()
    assert src.read_bytes() == b"original\x00bytes\xff" and not target.exists()
    journal(tmp_path).rollback()
    assert src.read_bytes() == b"original\x00bytes\xff" and not target.exists()


@pytest.mark.parametrize("operation", ["copy", "move"])
def test_foreign_target_after_crash_never_adopted(tmp_path, monkeypatch, operation):
    src = source(tmp_path)
    target = tmp_path / "target"
    j = journal(tmp_path)
    original_write = j._core._write
    calls = 0
    def lose_power(payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SimulatedPowerLoss()
        original_write(payload)
    monkeypatch.setattr(j._core, "_write", lose_power)
    steps = [FileActionStep(operation, str(src), str(target))]
    with pytest.raises(SimulatedPowerLoss):
        j.execute_actions(steps)
    target.write_bytes(b"foreign replacement")
    before = j.journal_file.read_bytes()
    with pytest.raises(RuntimeError):
        journal(tmp_path).execute_actions(steps)
    assert target.read_bytes() == b"foreign replacement"
    assert j.journal_file.read_bytes() == before


def test_journal_resource_and_escape_paths_refused(tmp_path):
    src = source(tmp_path)
    j = journal(tmp_path)
    with pytest.raises(PermissionError):
        j.execute_actions([FileActionStep("copy", str(src), str(j.journal_file))])
    with pytest.raises(ValueError):
        j.execute_actions([FileActionStep("copy", str(src), str(tmp_path.parent / "outside"))])
    assert not j.journal_file.exists()


def test_hard_link_alias_refused(tmp_path):
    src = source(tmp_path)
    alias = tmp_path / "alias"
    alias.hardlink_to(src)
    with pytest.raises(PermissionError):
        journal(tmp_path).execute_actions([FileActionStep("move", str(src), str(tmp_path / "out"))])
    assert alias.read_bytes() == src.read_bytes()


def test_missing_guard_or_allowed_scope_fail_closed(tmp_path):
    src = source(tmp_path)
    steps = [FileActionStep("copy", str(src), str(tmp_path / "out"))]
    with pytest.raises(PermissionError):
        BachActionJournal(tmp_path / "journals", "missing").execute_actions(steps)
    with pytest.raises(PermissionError):
        BachActionJournal(tmp_path / "journals", "missing", allowed_roots=(tmp_path,)).execute_actions(steps)
    assert not (tmp_path / "journals").exists()


def test_guard_expiry_before_target_write_fails_closed(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "out"
    calls = 0
    @contextmanager
    def fixture_lease(paths):
        def check():
            nonlocal calls
            calls += 1
            return calls < 4
        yield check
    j = journal(tmp_path, guard=fixture_lease)
    with pytest.raises(PermissionError):
        j.execute_actions([FileActionStep("copy", str(src), str(target))])
    assert src.read_bytes() == b"original\x00bytes\xff" and not target.exists()


def test_journal_record_tampering_refused_before_undo(tmp_path):
    src = source(tmp_path)
    target = tmp_path / "out"
    j = journal(tmp_path)
    j.execute_actions([FileActionStep("copy", str(src), str(target))])
    payload = json.loads(j.journal_file.read_text())
    payload["entries"][0]["undo_receipt"]["undo_plan"]["target"] = str(src)
    j.journal_file.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        j.rollback()
    assert src.read_bytes() == target.read_bytes()


def test_host_exclusive_lease_blocks_second_run(tmp_path):
    src = source(tmp_path)
    owned = Lock()
    nested_results = []
    @contextmanager
    def host_fixture_lease(paths):
        acquired = owned.acquire(blocking=False)
        if not acquired:
            raise PermissionError("another host lease owns resources")
        try:
            def check():
                if not nested_results:
                    second = journal(tmp_path, "second", guard=host_fixture_lease)
                    with pytest.raises(PermissionError):
                        second.execute_actions([FileActionStep("copy", str(src), str(tmp_path / "out2"))])
                    nested_results.append("denied")
                return acquired
            yield check
        finally:
            owned.release()
    j = journal(tmp_path, guard=host_fixture_lease)
    assert j.execute_actions([FileActionStep("copy", str(src), str(tmp_path / "out"))])
    assert nested_results == ["denied"] and not (tmp_path / "out2").exists()
