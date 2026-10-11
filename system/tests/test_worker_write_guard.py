from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub._services.chat import chat_runtime, worker_write_guard as guard
from hub._services.chat.bach_tools import exec_tool
from system.tests.test_worker_tool_bridge import bridge

_REAL_FRESH_LOCKS = guard._fresh_locks


class FakeClient:
    def __init__(self, view=None):
        self.view = view or {
            "own": True,
            "leased": True,
            "fence": 4,
            "status": "in_progress",
            "task_version": "v" * 64,
        }
        self.calls = []

    def read(self, task_id, *, lease_id=None, now=None):
        self.calls.append((task_id, lease_id, now))
        return self.view


class FakeBinding:
    task_id = 41

    def __init__(self, client=None):
        self._client = client or FakeClient()
        self._now = object()

    def assert_active(self):
        return None

    def _ref(self):
        return {"lease_id": "lease-41", "fence": 4, "task_version": "v" * 64, "now": self._now}


def _authorization_fixture(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    root = tmp_path / "worktrees"
    target = root / "task-41"
    repo.mkdir()
    target.mkdir(parents=True)
    monkeypatch.setattr(guard, "_paths", lambda *a, **k: (repo, root))
    monkeypatch.setattr(guard, "_registered_tree", lambda *a, **k: target)
    monkeypatch.setattr(guard, "_fresh_locks", lambda *a, **k: None)
    return repo, root, target


def test_authorization_binds_current_native_lease_and_task_path(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    binding = FakeBinding()
    worktree, paths = guard.authorize_mutation(binding, paths=("system/file.py",))
    assert worktree == target
    assert paths == (target / "system/file.py",)
    assert binding._client.calls == [(41, "lease-41", binding._now)] * 2


@pytest.mark.parametrize("field,value", [
    ("own", False),
    ("leased", False),
    ("fence", 3),
    ("status", "review"),
    ("task_version", "stale"),
])
def test_authorization_rejects_stale_or_foreign_lease(tmp_path, monkeypatch, field, value):
    _authorization_fixture(tmp_path, monkeypatch)
    view = {
        "own": True,
        "leased": True,
        "fence": 4,
        "status": "in_progress",
        "task_version": "v" * 64,
    }
    view[field] = value
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.authorize_mutation(FakeBinding(FakeClient(view)), paths=("file.py",))


def test_authorization_rejects_foreign_task_and_escaped_path(tmp_path, monkeypatch):
    _authorization_fixture(tmp_path, monkeypatch)
    binding = FakeBinding()
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.authorize_mutation(binding, task_id=42, paths=("file.py",))
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.authorize_mutation(binding, paths=("../outside.txt",))


def test_authorization_rejects_symlinked_write_path(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = target / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.authorize_mutation(FakeBinding(), paths=(link / "file.txt",))


@pytest.mark.parametrize("mode", ["safe", "full"])
def test_unbound_copy_and_move_stay_inside_code_derived_bach_root(tmp_path, monkeypatch, mode, caplog):
    from hub import bach_paths

    trusted_root = tmp_path / "bach"
    user_dir = trusted_root / "user"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(bach_paths, "BACH_ROOT", trusted_root)
    caplog.set_level("INFO", logger="bach.chat")

    copy_source = user_dir / "copy-source.txt"
    copy_source.write_text("copy", encoding="utf-8")
    copy_destination = user_dir / "copy-destination.txt"
    copied = exec_tool("copy_file", {
        "source": str(copy_source), "destination": str(copy_destination)
    }, mode=mode)
    assert "Kopiert:" in copied
    assert copy_destination.read_text(encoding="utf-8") == "copy"
    assert str(copy_source) not in caplog.text
    assert str(copy_destination) not in caplog.text

    copy_tree_source = user_dir / "copy-tree-source"
    copy_tree_source.mkdir()
    (copy_tree_source / "nested.txt").write_text("tree", encoding="utf-8")
    copy_tree_destination = user_dir / "copy-tree-destination"
    tree_result = exec_tool("copy_file", {
        "source": str(copy_tree_source), "destination": str(copy_tree_destination)
    }, mode=mode)
    assert "Kopiert:" in tree_result
    assert (copy_tree_destination / "nested.txt").read_text(encoding="utf-8") == "tree"

    external = tmp_path / "outside"
    external.mkdir()
    external_source = external / "source.txt"
    external_source.write_text("outside", encoding="utf-8")
    denied_source = exec_tool("copy_file", {
        "source": str(external_source), "destination": str(user_dir / "denied-source.txt")
    }, mode=mode)
    assert "BACH-Root" in denied_source
    assert not (user_dir / "denied-source.txt").exists()

    external_tree = external / "tree"
    external_tree.mkdir()
    (external_tree / "outside.txt").write_text("outside tree", encoding="utf-8")
    denied_tree = exec_tool("copy_file", {
        "source": str(external_tree), "destination": str(user_dir / "denied-tree")
    }, mode=mode)
    assert "BACH-Root" in denied_tree
    assert not (user_dir / "denied-tree").exists()

    denied_destination = exec_tool("copy_file", {
        "source": str(copy_source), "destination": str(external / "denied-destination.txt")
    }, mode=mode)
    assert "BACH-Root" in denied_destination
    assert not (external / "denied-destination.txt").exists()

    move_source = user_dir / "move-source.txt"
    move_source.write_text("move", encoding="utf-8")
    move_destination = user_dir / "move-destination.txt"
    moved = exec_tool("move_file", {
        "source": str(move_source), "destination": str(move_destination)
    }, mode=mode)
    assert "Verschoben:" in moved
    assert move_destination.read_text(encoding="utf-8") == "move"
    assert str(move_source) not in caplog.text
    assert str(move_destination) not in caplog.text
    assert not move_source.exists()

    external_move_source = external / "move-source.txt"
    external_move_source.write_text("external move", encoding="utf-8")
    denied_move_source = exec_tool("move_file", {
        "source": str(external_move_source), "destination": str(user_dir / "denied-move.txt")
    }, mode=mode)
    assert "BACH-Root" in denied_move_source
    assert external_move_source.read_text(encoding="utf-8") == "external move"

    outside_move_destination = external / "move-destination.txt"
    last_move_source = user_dir / "last-move-source.txt"
    last_move_source.write_text("retained", encoding="utf-8")
    denied_move_destination = exec_tool("move_file", {
        "source": str(last_move_source), "destination": str(outside_move_destination)
    }, mode=mode)
    assert "BACH-Root" in denied_move_destination
    assert last_move_source.read_text(encoding="utf-8") == "retained"
    assert not outside_move_destination.exists()


def test_unbound_path_result_is_exact_checked_normcase_expression(tmp_path, monkeypatch):
    import os
    from hub import bach_paths
    from hub._services.chat import bach_tools

    trusted_root = tmp_path / "BachRoot"
    user_dir = trusted_root / "user"
    user_dir.mkdir(parents=True)
    source = user_dir / "MixedCase-Existing.txt"
    source.write_text("existing", encoding="utf-8")
    destination = user_dir / "MixedCase-New.txt"
    monkeypatch.setattr(bach_paths, "BACH_ROOT", trusted_root)

    checked_source, checked_destination = bach_tools._authorized_file_mutation_paths(
        str(source), str(destination)
    )
    expected_source = Path(os.path.normcase(os.path.realpath(source)))
    expected_destination = Path(os.path.normcase(os.path.realpath(destination)))
    assert checked_source == expected_source
    assert checked_destination == expected_destination
    assert checked_source.read_text(encoding="utf-8") == "existing"
    assert not checked_destination.exists()

    if os.name == "nt":
        differently_cased_source = Path(str(source).swapcase())
        assert differently_cased_source.exists()
        case_checked_source, _ = bach_tools._authorized_file_mutation_paths(
            str(differently_cased_source), str(destination)
        )
        assert case_checked_source == checked_source
        assert case_checked_source.read_text(encoding="utf-8") == "existing"


def test_unbound_path_result_still_rejects_symlink_alias(tmp_path, monkeypatch):
    from hub import bach_paths
    from hub._services.chat import bach_tools

    trusted_root = tmp_path / "BachRoot"
    user_dir = trusted_root / "user"
    user_dir.mkdir(parents=True)
    source = user_dir / "Existing.txt"
    source.write_text("existing", encoding="utf-8")
    alias = user_dir / "SourceAlias.txt"
    try:
        alias.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    monkeypatch.setattr(bach_paths, "BACH_ROOT", trusted_root)

    with pytest.raises(ValueError, match="Ungebundene Dateioperation blockiert"):
        bach_tools._authorized_file_mutation_paths(str(alias), str(user_dir / "destination.txt"))


def test_unbound_copy_rejects_symlinked_source_and_destination_ancestors(tmp_path, monkeypatch):
    from hub import bach_paths

    trusted_root = tmp_path / "bach"
    user_dir = trusted_root / "user"
    user_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    external_file = outside / "secret.txt"
    external_file.write_text("not copied", encoding="utf-8")
    monkeypatch.setattr(bach_paths, "BACH_ROOT", trusted_root)

    inside_file = user_dir / "inside.txt"
    inside_file.write_text("inside", encoding="utf-8")
    source_link = user_dir / "source-link.txt"
    try:
        source_link.symlink_to(external_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    result = exec_tool("copy_file", {
        "source": str(source_link), "destination": str(user_dir / "source-copy.txt")
    }, mode="full")
    assert "BACH-Root" in result
    assert not (user_dir / "source-copy.txt").exists()

    destination_link = user_dir / "destination-link"
    try:
        destination_link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    result = exec_tool("copy_file", {
        "source": str(inside_file), "destination": str(destination_link / "copied.txt")
    }, mode="full")
    assert "BACH-Root" in result
    assert not (outside / "copied.txt").exists()


def test_unbound_move_rejects_symlinked_source_and_destination_ancestors(tmp_path, monkeypatch):
    from hub import bach_paths

    trusted_root = tmp_path / "bach"
    user_dir = trusted_root / "user"
    user_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_source = outside / "source.txt"
    outside_source.write_text("outside", encoding="utf-8")
    monkeypatch.setattr(bach_paths, "BACH_ROOT", trusted_root)

    source_link = user_dir / "source-link.txt"
    try:
        source_link.symlink_to(outside_source)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    result = exec_tool("move_file", {
        "source": str(source_link), "destination": str(user_dir / "moved-source.txt")
    }, mode="full")
    assert "BACH-Root" in result
    assert source_link.is_symlink()
    assert outside_source.read_text(encoding="utf-8") == "outside"

    destination_link = user_dir / "destination-link"
    try:
        destination_link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable")
    inside_source = user_dir / "inside.txt"
    inside_source.write_text("inside", encoding="utf-8")
    result = exec_tool("move_file", {
        "source": str(inside_source),
        "destination": str(destination_link / "moved.txt"),
    }, mode="full")
    assert "BACH-Root" in result
    assert inside_source.read_text(encoding="utf-8") == "inside"
    assert not (outside / "moved.txt").exists()


def test_unbound_copy_rechecks_ancestor_before_copy_sink(tmp_path, monkeypatch):
    from hub import bach_paths
    from hub._services.chat import bach_tools
    import shutil

    trusted_root = tmp_path / "bach"
    user_dir = trusted_root / "user"
    destination_parent = user_dir / "destination-parent"
    destination_parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    source = user_dir / "source.txt"
    source.write_text("inside", encoding="utf-8")
    monkeypatch.setattr(bach_paths, "BACH_ROOT", trusted_root)

    original_authorize = bach_tools._authorized_file_mutation_paths
    calls = 0

    def swap_ancestor_after_first_check(raw_source, raw_destination, binding=None):
        nonlocal calls
        calls += 1
        checked = original_authorize(raw_source, raw_destination, binding)
        if calls == 1:
            destination_parent.rmdir()
            destination_parent.symlink_to(outside, target_is_directory=True)
        return checked

    monkeypatch.setattr(
        bach_tools, "_authorized_file_mutation_paths", swap_ancestor_after_first_check)
    monkeypatch.setattr(shutil, "copy2", lambda *a, **k: pytest.fail("copy sink must not run"))
    result = exec_tool("copy_file", {
        "source": str(source),
        "destination": str(destination_parent / "escape.txt"),
    }, mode="full")
    assert calls == 2
    assert "BACH-Root" in result
    assert not (outside / "escape.txt").exists()


def test_unbound_move_rechecks_ancestor_before_move_sink(tmp_path, monkeypatch):
    from hub import bach_paths
    from hub._services.chat import bach_tools
    import shutil

    trusted_root = tmp_path / "bach"
    user_dir = trusted_root / "user"
    destination_parent = user_dir / "destination-parent"
    destination_parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    source = user_dir / "source.txt"
    source.write_text("inside", encoding="utf-8")
    monkeypatch.setattr(bach_paths, "BACH_ROOT", trusted_root)

    original_authorize = bach_tools._authorized_file_mutation_paths
    calls = 0

    def swap_ancestor_after_first_check(raw_source, raw_destination, binding=None):
        nonlocal calls
        calls += 1
        checked = original_authorize(raw_source, raw_destination, binding)
        if calls == 1:
            destination_parent.rmdir()
            destination_parent.symlink_to(outside, target_is_directory=True)
        return checked

    monkeypatch.setattr(
        bach_tools, "_authorized_file_mutation_paths", swap_ancestor_after_first_check)
    monkeypatch.setattr(shutil, "move", lambda *a, **k: pytest.fail("move sink must not run"))
    result = exec_tool("move_file", {
        "source": str(source),
        "destination": str(destination_parent / "escape.txt"),
    }, mode="full")
    assert calls == 2
    assert "BACH-Root" in result
    assert source.read_text(encoding="utf-8") == "inside"
    assert not (outside / "escape.txt").exists()


def test_bound_copy_stays_in_registered_task_worktree(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    source = target / "source.txt"
    destination = target / "copy.txt"
    source.write_text("task-bound", encoding="utf-8")

    result = exec_tool("copy_file", {
        "source": str(source), "destination": str(destination)
    }, mode="safe", worker_task_binding=FakeBinding(), allowed_tools={"copy_file"})

    assert "Kopiert:" in result
    assert destination.read_text(encoding="utf-8") == "task-bound"


def test_unknown_lock_status_blocks_mutation(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    def unknown(*args, **kwargs):
        raise guard.WorkerWriteGuardError("unknown lock")
    monkeypatch.setattr(guard, "_fresh_locks", unknown)
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.authorize_mutation(FakeBinding(), paths=(target / "file.txt",))


def test_git_registration_requires_exact_task_branch(tmp_path):
    repo = tmp_path / "repo"
    root = tmp_path / "worktrees"
    target = root / "task-41"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "README.md").write_text("test", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    root.mkdir()
    subprocess.run(["git", "worktree", "add", str(target), "-b", "bach-task/41", "main"],
                   cwd=repo, check=True, capture_output=True)
    assert guard._registered_tree(repo, root, 41) == target
    subprocess.run(["git", "checkout", "--detach"], cwd=target, check=True, capture_output=True)
    with pytest.raises(guard.WorkerWriteGuardError):
        guard._registered_tree(repo, root, 41)


def test_bound_check_uses_checked_cwd_and_rejects_mutating_commands(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    calls = []
    results = iter([
        SimpleNamespace(returncode=0, stdout="ok", stderr="", timed_out=False, memory_exceeded=False),
        SimpleNamespace(returncode=7, stdout="", stderr="check failed", timed_out=False, memory_exceeded=False),
        SimpleNamespace(returncode=-9, stdout="partial", stderr="", timed_out=True, memory_exceeded=False),
    ])
    def isolated(argv, *, limits, cwd, shell, env=None):
        calls.append((argv, limits, cwd, shell))
        return next(results)
    monkeypatch.setattr(sandbox, "run_isolated", isolated)
    success = guard.run_bound_check(FakeBinding(), "python -m pytest -q", target)
    assert "Prüfung erfolgreich" in success and "Exitcode 0" in success and "ok" in success
    assert calls[0][2] == str(target) and calls[0][3] is False
    assert calls[0][1].timeout_sec == 60 and calls[0][1].memory_mb is None
    failure = guard.run_bound_check(FakeBinding(), "python -m pytest -q", target)
    assert "Prüfung fehlgeschlagen" in failure and "Exitcode 7" in failure and "check failed" in failure
    timeout = guard.run_bound_check(FakeBinding(), "python -m pytest -q", target)
    assert "Timeout nach 60s" in timeout and "Exitcode -9" in timeout
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.run_bound_check(FakeBinding(), "python -c print(1)", target)
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.run_bound_check(FakeBinding(), "git push origin main", target)
    assert len(calls) == 3


def test_bound_check_returns_typed_result_and_preserves_timeout_memory(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    expected = [
        sandbox.SandboxResult(returncode=0, stdout="ok", stderr=""),
        sandbox.SandboxResult(returncode=-9, stdout="partial", stderr="", timed_out=True),
        sandbox.SandboxResult(returncode=-9, stdout="partial", stderr="", memory_exceeded=True),
    ]
    results = iter(expected)
    monkeypatch.setattr(sandbox, "run_isolated", lambda *a, **k: next(results))
    actual = [guard.run_bound_check(FakeBinding(), "python -m pytest -q", target, return_result=True)
              for _ in expected]
    assert all(type(item) is sandbox.SandboxResult for item in actual)
    assert [item.returncode for item in actual] == [0, -9, -9]
    assert [item.timed_out for item in actual] == [False, True, False]
    assert [item.memory_exceeded for item in actual] == [False, False, True]


def test_bound_check_fails_closed_on_unknown_return_result_shape(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    monkeypatch.setattr(sandbox, "run_isolated", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="looks successful", stderr="", timed_out=False, memory_exceeded=False))
    with pytest.raises(guard.WorkerWriteGuardError, match="nicht typisiert"):
        guard.run_bound_check(FakeBinding(), "python -m pytest -q", target, return_result=True)


def test_bound_check_rejects_external_compileall_ruff_pytest_and_cache_targets_before_spawn(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    from hub import safe_exec
    external = tmp_path.parent / "outside-task-tree"
    commands = [
        f"python -m compileall {external}",
        f"ruff check --fix {external}",
        f"ruff check --output-file={external / 'report.txt'} .",
        f"ruff check --cache-dir={external / 'ruff-cache'} .",
        f"python -m pytest --basetemp={external} .",
        f"python -m pytest {external / 'test_outside.py'}",
        f"python -m pytest -o cache_dir={external / 'pytest-cache'} .",
        f"python -m pytest --junitxml={external / 'results.xml'} .",
        f"python -m pytest --cov-report=html:{external / 'coverage-html'} .",
    ]
    monkeypatch.setattr(safe_exec, "resolve_executable", lambda command, allowed: ["resolved-check"])
    monkeypatch.setattr(sandbox, "run_isolated", lambda *a, **k: pytest.fail("must reject before process start"))
    for command in commands:
        with pytest.raises(guard.WorkerWriteGuardError):
            guard.run_bound_check(FakeBinding(), command, target)


def test_bound_check_keeps_compileall_bytecode_inside_task_tree(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    calls = []
    def isolated(argv, *, limits, cwd, shell, env=None):
        calls.append((argv, cwd, shell, env))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="", timed_out=False, memory_exceeded=False)
    monkeypatch.setattr(sandbox, "run_isolated", isolated)
    result = guard.run_bound_check(FakeBinding(), "python -m compileall -q .", target)
    assert "Prüfung erfolgreich" in result and len(calls) == 1
    assert calls[0][1] == str(target) and calls[0][2] is False
    assert calls[0][3]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert calls[0][3]["PYTHONPYCACHEPREFIX"] == str(target / ".worker-check" / "python-pycache")
    assert calls[0][3]["BACH_DB"] == str(target / ".worker-check" / "worker-check.sqlite3")


def test_bound_check_runs_pytest_with_task_local_inputs_outputs_and_environment(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    from hub import safe_exec
    external_db = tmp_path / "external-bach.db"
    monkeypatch.setenv("BACH_DB", str(external_db))
    (target / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    calls = []
    authorized_paths = []
    original_authorize = guard.authorize_mutation
    def recording_authorize(*args, **kwargs):
        result = original_authorize(*args, **kwargs)
        authorized_paths.extend(result[1])
        return result
    def isolated(argv, *, limits, cwd, shell, env=None):
        calls.append((argv, cwd, shell, env))
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="", timed_out=False, memory_exceeded=False)
    monkeypatch.setattr(safe_exec, "resolve_executable", lambda command, allowed: ["resolved-python", *safe_exec.tokenize(command)[1:]])
    monkeypatch.setattr(sandbox, "run_isolated", isolated)
    monkeypatch.setattr(guard, "authorize_mutation", recording_authorize)
    result = guard.run_bound_check(FakeBinding(), "python -m pytest -q -- test_smoke.py", target)
    assert "Prüfung erfolgreich" in result and len(calls) == 1
    argv, cwd, shell, env = calls[0]
    assert argv[0] == "resolved-python" and argv[1:3] == ["-m", "pytest"]
    assert str(target / "test_smoke.py") in argv
    assert "--basetemp" in argv and str(target / ".worker-check" / "pytest-temp") in argv
    assert "cache_dir=" + str(target / ".worker-check" / "pytest-cache") in argv
    assert "addopts=" in argv
    assert "testpaths=" + str(target) in argv and "confcutdir=" + str(target) in argv
    assert argv.index("--") > argv.index("cache_dir=" + str(target / ".worker-check" / "pytest-cache"))
    assert cwd == str(target) and shell is False
    assert env["BACH_DB"] == str(target / ".worker-check" / "worker-check.sqlite3")
    assert env["PYTHONPYCACHEPREFIX"] == str(target / ".worker-check" / "python-pycache")
    assert env["PYTEST_ADDOPTS"] == "" and env["PYTEST_PLUGINS"] == ""
    assert env["RUFF_CACHE_DIR"] == str(target / ".worker-check" / "ruff-cache")
    authorized = set(authorized_paths)
    for relative in ("home", "tmp", "xdg-cache", "python-pycache", "ruff-cache", "mypy-cache",
                     "pyright-cache", "npm-cache", "pip-cache", "uv-cache", "pre-commit-cache",
                     ".coverage", "pytest-debug-temp", "worker-check.sqlite3", "npmrc", "npm-globalrc",
                     "local-app-data", "app-data", "pytest-temp", "pytest-cache"):
        assert target / ".worker-check" / relative in authorized
    assert external_db not in authorized


def test_bound_check_returns_structured_timeout_result(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    from hub import safe_exec
    response = sandbox.SandboxResult(returncode=-9, stdout="partial", stderr="", timed_out=True,
                                     memory_exceeded=False)
    monkeypatch.setattr(safe_exec, "resolve_executable", lambda command, allowed: ["resolved-python"])
    monkeypatch.setattr(sandbox, "run_isolated", lambda *a, **k: response)
    result = guard.run_bound_check(
        FakeBinding(), "python -m pytest -q -- test_generated.py", target, timeout=60, return_result=True)
    assert type(result) is sandbox.SandboxResult and result is response
    assert result.returncode == -9 and result.timed_out is True and result.memory_exceeded is False

def test_windows_check_fails_closed_without_process_tree_cleanup(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    from core import sandbox
    monkeypatch.setattr(guard.os, "name", "nt")
    monkeypatch.setattr(sandbox, "HAS_PSUTIL", False)
    monkeypatch.setattr(sandbox, "run_isolated", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(guard.WorkerWriteGuardError, match="Prozessbaum"):
        guard.run_bound_check(FakeBinding(), "python -m pytest -q", target)



def test_write_grants_are_explicit_and_recycle_is_never_task_scoped():
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.require_write_grant("write_file", None)
    guard.require_write_grant("write_file", {"write_file"})
    with pytest.raises(guard.WorkerWriteGuardError):
        guard.block_bound_recycle(FakeBinding())


def test_lock_scanner_malformed_output_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_scanner_path", lambda: tmp_path / "scanner.py")
    monkeypatch.setattr(guard, "_RUN", lambda *a, **k: SimpleNamespace(returncode=0, stdout="not-json"))
    with pytest.raises(guard.WorkerWriteGuardError):
        guard._scan_locks(tmp_path)



def test_start_authorization_reads_lease_and_checks_locks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    root = tmp_path / "worktrees"
    repo.mkdir()
    root.mkdir()
    binding = FakeBinding()
    calls = []
    monkeypatch.setattr(guard, "_paths", lambda *a, **k: (repo, root))
    monkeypatch.setattr(guard, "_fresh_locks", lambda *a, **k: calls.append("scan"))
    target = guard.authorize_start(binding, 41)
    assert target == root / "task-41"
    assert calls == ["scan"]
    assert binding._client.calls


def test_lock_scanner_rejects_foreign_locks_and_unknown_twin(tmp_path, monkeypatch):
    scanner = tmp_path / "scanner.py"
    monkeypatch.setattr(guard, "_scanner_path", lambda: scanner)
    payload = {"checked": str(tmp_path.resolve()), "twin_status": "ok",
               "locks": [{"path": str(tmp_path / "LOCK.foreign.txt"), "scope": "foreign"}]}
    monkeypatch.setattr(
        guard, "_RUN",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=json.dumps(payload)),
    )
    with pytest.raises(guard.WorkerWriteGuardError):
        guard._scan_locks(tmp_path)
    payload["locks"] = []
    payload["twin_status"] = "unknown"
    monkeypatch.setattr(
        guard, "_RUN",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(payload)),
    )
    with pytest.raises(guard.WorkerWriteGuardError):
        guard._scan_locks(tmp_path, main_repo=True)


def test_bound_runtime_forwards_explicit_grant_without_agent_controller():
    grants = {"write_file"}
    binding = FakeBinding()
    session = SimpleNamespace(
        worker_task_binding=binding,
        require_task_binding=True,
        allowed_tools=grants,
    )

    kwargs = chat_runtime._tool_dispatch_kwargs(session, agent_operations=None)

    assert kwargs == {
        "worker_task_binding": binding,
        "require_task_binding": True,
        "allowed_tools": grants,
    }
    assert kwargs["allowed_tools"] is grants
    assert "agent_operations" not in kwargs


def test_bound_runtime_missing_grant_stays_fail_closed(tmp_path):
    binding = FakeBinding()
    session = SimpleNamespace(worker_task_binding=binding, require_task_binding=True)
    kwargs = chat_runtime._tool_dispatch_kwargs(session, agent_operations=None)
    target = tmp_path / "must-not-exist.txt"

    result = exec_tool(
        "write_file", {"path": str(target), "content": "blocked"}, "full", **kwargs
    )

    assert "BLOCKIERT" in result
    assert not target.exists()


def test_bound_runtime_revoked_binding_stays_blocked(tmp_path):
    class RevokedBinding(FakeBinding):
        def assert_active(self):
            raise RuntimeError("revoked")

    binding = RevokedBinding()
    grants = {"write_file"}
    session = SimpleNamespace(
        worker_task_binding=binding,
        require_task_binding=True,
        allowed_tools=grants,
    )
    kwargs = chat_runtime._tool_dispatch_kwargs(session, agent_operations=None)
    target = tmp_path / "revoked-must-not-exist.txt"

    result = exec_tool(
        "write_file", {"path": str(target), "content": "blocked"}, "full", **kwargs
    )

    assert "BLOCKIERT" in result
    assert not target.exists()


def test_unbound_required_session_does_not_forward_session_grants():
    grants = {"write_file"}
    session = SimpleNamespace(
        worker_task_binding=None,
        require_task_binding=True,
        allowed_tools=grants,
    )

    kwargs = chat_runtime._tool_dispatch_kwargs(session, agent_operations=None)

    assert kwargs == {
        "worker_task_binding": None,
        "require_task_binding": True,
    }



def test_nested_lock_blocks_write_when_destination_parent_is_missing(tmp_path, monkeypatch):
    _, _, target = _authorization_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(guard, "_fresh_locks", _REAL_FRESH_LOCKS)
    nested_parent = target / "docs" / "sub"
    nested_parent.mkdir(parents=True)
    lock_file = nested_parent / "LOCK.foreign.txt"
    lock_file.write_text("foreign owner", encoding="utf-8")
    scanned = []
    def scan(path, *, main_repo=False):
        path = Path(path)
        scanned.append(path)
        if path == nested_parent and lock_file.exists():
            raise guard.WorkerWriteGuardError("nested lock")
        return {}
    monkeypatch.setattr(guard, "_scan_locks", scan)
    with pytest.raises(guard.WorkerWriteGuardError, match="nested lock"):
        guard.authorize_mutation(FakeBinding(), paths=(nested_parent / "not-created" / "new.py",))
    assert nested_parent in scanned
    assert not (nested_parent / "not-created").exists()


def test_start_scans_nearest_existing_ancestor_when_worktrees_root_is_missing(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    ancestor = tmp_path / "worktree-parent"
    ancestor.mkdir()
    root = ancestor / "not-created" / "worktrees"
    lock_file = ancestor / "LOCK.foreign.txt"
    lock_file.write_text("foreign owner", encoding="utf-8")
    monkeypatch.setattr(guard, "_paths", lambda *a, **k: (repo, root))
    monkeypatch.setattr(guard, "_fresh_locks", _REAL_FRESH_LOCKS)
    scanned = []
    def scan(path, *, main_repo=False):
        path = Path(path)
        scanned.append(path)
        if path == ancestor and lock_file.exists():
            raise guard.WorkerWriteGuardError("ancestor lock")
        return {}
    monkeypatch.setattr(guard, "_scan_locks", scan)
    with pytest.raises(guard.WorkerWriteGuardError, match="ancestor lock"):
        guard.authorize_start(FakeBinding(), 41)
    assert ancestor in scanned
    assert not root.exists()


def test_chat_runtime_caller_forwards_session_grant_without_agent_operations(bridge, monkeypatch):
    from hub._services.chat import chat_runtime as runtime_module
    calls = []
    class Backend:
        def __init__(self):
            self.round = 0
        def get_default_model(self):
            return "isolated-model"
        async def chat(self, messages, **kwargs):
            self.round += 1
            if self.round == 1:
                tool_calls = [{"function": {"name": "get_datetime", "arguments": {}}}]
                return {"content": "", "tool_calls": tool_calls,
                        "raw_message": {"role": "assistant", "content": "", "tool_calls": tool_calls}}
            return {"content": "finished", "tool_calls": [],
                    "raw_message": {"role": "assistant", "content": "finished"}}
        def tool_response_message(self, content, tool_call_id=""):
            return {"role": "tool", "content": content}
    runtime = runtime_module.ChatRuntime(Backend())
    runtime.max_tool_rounds = 3
    runtime.hook_every = 999
    session = runtime.get_session("bound-grant-dispatch")
    session.worker_task_binding = bridge.binding
    session.require_task_binding = True
    session.allowed_tools = {"get_datetime"}
    assert runtime.agent_operations is None
    monkeypatch.setattr(runtime_module, "exec_tool",
                        lambda *a, **kw: calls.append((a, kw)) or "tool result")
    answer = asyncio.run(runtime.process("Prüfe den gebundenen Toolaufruf", "bound-grant-dispatch",
                                         work_priority="background"))
    assert str(answer) == "finished"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "get_datetime"
    assert kwargs["allowed_tools"] is session.allowed_tools
    assert kwargs["worker_task_binding"] is bridge.binding
    assert kwargs["require_task_binding"] is True
    assert "agent_operations" not in kwargs

def test_bound_safe_shell_without_worktree_or_cwd_uses_restricted_runner(monkeypatch):
    from hub._services.chat import bach_tools

    binding = FakeBinding()
    calls = []
    def restricted(command, *, allowed):
        calls.append((command, allowed))
        return "read-only result"
    monkeypatch.setattr(bach_tools, "run_shell_restricted", restricted)

    result = exec_tool(
        "safe_shell", {"command": "uname -a"}, "safe",
        worker_task_binding=binding, require_task_binding=True,
        allowed_tools={"safe_shell"},
    )

    assert result == "read-only result"
    assert calls == [("uname -a", bach_tools.SAFE_BASES)]
    assert binding._client.calls == [(41, "lease-41", binding._now)]


@pytest.mark.parametrize("command", [
    "echo synthetic > /tmp/synthetic-output",
    "find . -exec echo synthetic",
    "sysctl -w synthetic=1",
    "git push origin main",
    "cat ~/.ssh/synthetic-credential",
])
def test_bound_safe_shell_still_blocks_writes_and_secret_paths(monkeypatch, command):
    from hub._services.chat import bach_tools

    binding = FakeBinding()
    monkeypatch.setattr(
        bach_tools, "run_shell_restricted",
        lambda *args, **kwargs: pytest.fail("blocked command reached runner"),
    )
    result = exec_tool(
        "safe_shell", {"command": command}, "safe",
        worker_task_binding=binding, require_task_binding=True,
        allowed_tools={"safe_shell"},
    )
    assert "blockiert" in result.lower() or "nicht erlaubt" in result.lower()
    assert "synthetic-credential" not in result

