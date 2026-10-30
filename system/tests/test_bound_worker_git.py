"""Canonical worktree receipts against isolated authority; no Git publication."""
from pathlib import Path
import os
import subprocess
from types import SimpleNamespace

import pytest
from core.sandbox import SandboxResult

from system.tests.test_worker_tool_bridge import bridge
from hub import worker_git
from hub._services.chat import worker_write_guard
from hub._services.chat.bach_tools import exec_tool
from hub._services.task_lease_client import LeaseReleaseAck


PR = "https://github.com/ellmos-ai/bach/pull/123"
_REAL_SUBPROCESS_RUN = subprocess.run


def _add_task_tree(task_id):
    root = Path(os.environ["BACH_WORKTREES_DIR"])
    repo = Path(os.environ["BACH_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"task-{task_id}"
    if not target.exists():
        _REAL_SUBPROCESS_RUN(
            ["git", "worktree", "add", str(target), "-b", f"bach-task/{task_id}", "main"],
            cwd=str(repo), check=True, capture_output=True, text=True,
        )
    return target


@pytest.fixture
def git_run(bridge, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _REAL_SUBPROCESS_RUN(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    _REAL_SUBPROCESS_RUN(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    _REAL_SUBPROCESS_RUN(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("# Test", encoding="utf-8")
    _REAL_SUBPROCESS_RUN(["git", "add", "."], cwd=str(repo), check=True)
    _REAL_SUBPROCESS_RUN(["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True)
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setenv("BACH_ROOT", str(repo))
    monkeypatch.setenv("BACH_WORKTREES_DIR", str(root))
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: repo)
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: root)
    monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
    _add_task_tree(bridge.binding.task_id)
    monkeypatch.setattr(worker_git, "scan_for_secrets", lambda path: [])
    monkeypatch.setattr(worker_git, "check_git_diff", lambda path: [])
    calls = []
    def physical(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:4] == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/ellmos-ai/bach.git", stderr="")
        return SimpleNamespace(returncode=0, stdout=PR if cmd[:3] == ["gh", "pr", "create"] else "", stderr="")
    monkeypatch.setattr(worker_git.subprocess, "run", physical)
    return calls


@pytest.mark.parametrize(
    "test_result, succeeded, reason",
    [
        pytest.param(SandboxResult(returncode=0, stdout="1 passed", stderr=""), True, None, id="pass"),
        pytest.param(SandboxResult(returncode=2, stdout="failed", stderr=""), False, "Exitcode 2", id="nonzero-exit"),
        pytest.param(SandboxResult(returncode=-9, stdout="partial", stderr="", timed_out=True),
                     False, "Timeout nach 60 Sekunden", id="timeout"),
        pytest.param(SandboxResult(returncode=-9, stdout="partial", stderr="", memory_exceeded=True),
                     False, "Speichergrenze", id="memory-exceeded"),
        pytest.param(SimpleNamespace(returncode=0, timed_out=False, memory_exceeded=False),
                     False, "nicht sicher bestätigt", id="unknown-result-shape"),
    ],
)
def test_bound_finish_runs_tests_through_structured_bound_check(
        bridge, git_run, monkeypatch, tmp_path, test_result, succeeded, reason):
    target = Path(os.environ["BACH_WORKTREES_DIR"]) / f"task-{bridge.binding.task_id}"
    (target / "test_generated.py").write_text("def test_generated():\n    assert True\n", encoding="utf-8")
    bounded_calls = []

    def bounded(binding, command, *, cwd, timeout=60, safe=False, return_result=False):
        bounded_calls.append((binding, command, cwd, timeout, safe, return_result))
        return test_result

    def physical(cmd, **kwargs):
        git_run.append(cmd)
        if cmd[:2] == ["git", "diff"] and "--name-only" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["git", "ls-files"]:
            return SimpleNamespace(returncode=0, stdout="test_generated.py\0", stderr="")
        return SimpleNamespace(returncode=0,
                               stdout=PR if cmd[:3] == ["gh", "pr", "create"] else "", stderr="")

    monkeypatch.setattr(worker_git.subprocess, "run", physical)
    monkeypatch.setattr(worker_write_guard, "run_bound_check", bounded)
    result = worker_git.finish_task(
        bridge.binding.task_id, "Bound test finish", worker_task_binding=bridge.binding,
        require_task_binding=True)

    assert len(bounded_calls) == 1
    binding, command, cwd, timeout, safe, return_result = bounded_calls[0]
    assert binding is bridge.binding
    assert command == "python -m pytest -q -- test_generated.py"
    assert cwd == str(target) and timeout == 60 and safe is False and return_result is True
    if succeeded:
        assert result == {"success": True, "pr_url": PR, "status": "review"}
        assert any(cmd[:2] == ["git", "commit"] for cmd in git_run)
        assert any(cmd[:2] == ["git", "push"] for cmd in git_run)
    else:
        assert result["success"] is False and reason in result["error"]
        assert not any(cmd[:2] in (["git", "add"], ["git", "commit"], ["git", "push"])
                       or cmd[:3] == ["gh", "pr", "create"] for cmd in git_run)

def test_bound_finish_uses_real_bound_python_pytest_parser(bridge, git_run, monkeypatch, tmp_path):
    target = Path(os.environ["BACH_WORKTREES_DIR"]) / f"task-{bridge.binding.task_id}"
    (target / "test_generated.py").write_text("def test_generated():\n    assert True\n", encoding="utf-8")
    from core import sandbox
    from hub import safe_exec
    isolated = []
    git_calls = []

    def physical(cmd, **kwargs):
        git_calls.append(cmd)
        if cmd[:2] == ["git", "diff"] and "--name-only" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["git", "ls-files"]:
            return SimpleNamespace(returncode=0, stdout="test_generated.py\0", stderr="")
        return SimpleNamespace(returncode=0,
                               stdout=PR if cmd[:3] == ["gh", "pr", "create"] else "", stderr="")

    monkeypatch.setattr(worker_git.subprocess, "run", physical)

    def capture(argv, *, limits, cwd, shell, env=None):
        isolated.append((list(argv), limits, cwd, shell, dict(env or {})))
        return SandboxResult(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(sandbox, "run_isolated", capture)
    result = worker_git.finish_task(
        bridge.binding.task_id, "Bound parser integration", worker_task_binding=bridge.binding,
        require_task_binding=True)

    assert result == {"success": True, "pr_url": PR, "status": "review"}
    assert any(cmd[:2] == ["git", "ls-files"] for cmd in git_calls)
    assert len(isolated) == 1
    argv, limits, cwd, shell, env = isolated[0]
    assert argv[0] == safe_exec.resolve_executable("python", worker_write_guard._CHECK_BASES)[0]
    assert argv[1:4] == ["-m", "pytest", "-q"]
    state = target / ".cache" / ".worker-check"
    separator = argv.index("--")
    assert argv[4:separator] == [
        "--basetemp", str(state / "pytest-temp"),
        "-o", "cache_dir=" + str(state / "pytest-cache"),
        "-o", "addopts=",
        "-o", "log_file=",
        "-o", "testpaths=" + str(target),
        "-o", "confcutdir=" + str(target),
    ]
    assert argv[separator + 1:] == [str((target / "test_generated.py").resolve())]
    assert cwd == str(target) and shell is False and limits.timeout_sec == 60
    expected_paths = {
        "HOME": state / "home", "TMPDIR": state / "tmp", "TMP": state / "tmp", "TEMP": state / "tmp",
        "XDG_CACHE_HOME": state / "xdg-cache", "XDG_CONFIG_HOME": state / "xdg-config",
        "XDG_STATE_HOME": state / "xdg-state", "PYTHONPYCACHEPREFIX": state / "python-pycache",
        "RUFF_CACHE_DIR": state / "ruff-cache", "MYPY_CACHE_DIR": state / "mypy-cache",
        "PYRIGHT_PYTHON_CACHE_DIR": state / "pyright-cache", "npm_config_cache": state / "npm-cache",
        "PIP_CACHE_DIR": state / "pip-cache", "UV_CACHE_DIR": state / "uv-cache",
        "PRE_COMMIT_HOME": state / "pre-commit-cache", "COVERAGE_FILE": state / ".coverage",
        "PYTEST_DEBUG_TEMPROOT": state / "pytest-debug-temp", "BACH_DB": state / "worker-check.sqlite3",
        "NPM_CONFIG_USERCONFIG": state / "npmrc", "NPM_CONFIG_GLOBALCONFIG": state / "npm-globalrc",
        "LOCALAPPDATA": state / "local-app-data", "APPDATA": state / "app-data",
    }
    for key, value in expected_paths.items():
        assert Path(env[key]).resolve() == value.resolve(), key
    if os.name == "nt":
        assert Path(env["USERPROFILE"]).resolve() == (state / "home").resolve()
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTEST_ADDOPTS"] == "" and env["PYTEST_PLUGINS"] == ""
    assert env["BACH_ALLOW_ONEDRIVE_DB_FALLBACK"] == "0"


def test_bound_finish_records_review_only_at_canonical_authority(bridge, git_run, tmp_path):
    decoy = tmp_path / "projection-must-not-open.db"
    result = worker_git.finish_task(bridge.binding.task_id, "Actual implementation", run_tests=False,
                                   db_path=decoy, worker_task_binding=bridge.binding, require_task_binding=True)
    assert result == {"success": True, "pr_url": PR, "status": "review"}
    canonical = bridge.binding._client.task_snapshot(bridge.binding.task_id)
    assert canonical["status"] == "review" and canonical["description"].startswith("PR: " + PR)
    assert not decoy.exists()
    assert bridge.binding.closed and bridge.binding.completed_task_ids == ()
    assert bridge.binding.return_lease() is False
    assert any(cmd[:2] == ["git", "push"] for cmd in git_run)


def test_bound_wip_updates_content_version_and_keeps_lease(bridge, git_run, tmp_path):
    before = bridge.binding.task_snapshot()["task_version"]
    decoy = tmp_path / "projection-must-not-open.db"
    result = worker_git.finish_task(bridge.binding.task_id, "Actual WIP", is_wip=True, db_path=decoy,
                                   worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is True and result["wip"] is True
    assert not decoy.exists()
    snapshot = bridge.binding.task_snapshot()
    assert snapshot["task_version"] != before
    assert "[WIP] Stand auf bach-task/" in snapshot["description"]
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["status"] == "in_progress"
    assert not bridge.binding.closed
    bridge.binding.assert_active()


@pytest.mark.parametrize("kind", ["missing", "foreign", "stopped"])
def test_bound_finish_rejects_invalid_authority_before_git_or_db(bridge, git_run, tmp_path, kind):
    binding = bridge.binding
    task_id = binding.task_id
    if kind == "missing": binding = None
    elif kind == "foreign": task_id += 1
    else: binding._stop_event.set()
    decoy = tmp_path / "projection-must-not-open.db"
    result = worker_git.finish_task(task_id, "Denied", db_path=decoy, worker_task_binding=binding,
                                   require_task_binding=True)
    assert result["success"] is False
    assert not git_run and not decoy.exists()


def test_finish_tool_forwards_private_binding(bridge, monkeypatch):
    calls = []
    def finish(*args, **kwargs):
        calls.append((args, kwargs))
        return {"success": True, "status": "review"}
    monkeypatch.setattr(worker_git, "finish_task", finish)
    result = exec_tool("finish_task", {"task_id": bridge.binding.task_id, "message": "Configured work"}, "safe",
                       worker_task_binding=bridge.binding, require_task_binding=True,
                       allowed_tools={"finish_task"})
    assert '"success": true' in result
    assert calls[0][1]["worker_task_binding"] is bridge.binding
    assert calls[0][1]["require_task_binding"] is True


def test_wip_failed_push_does_not_claim_canonical_receipt(bridge, git_run, monkeypatch):
    before = bridge.binding.task_snapshot()["task_version"]
    original = worker_git.subprocess.run
    def failed_push(cmd, **kwargs):
        result = original(cmd, **kwargs)
        if cmd[:2] == ["git", "push"]: result.returncode = 1
        return result
    monkeypatch.setattr(worker_git.subprocess, "run", failed_push)
    result = worker_git.finish_task(bridge.binding.task_id, "WIP", is_wip=True,
                                   worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is False
    assert bridge.binding.task_snapshot()["task_version"] == before


def test_stop_during_commit_blocks_next_git_mutation_and_task_write(bridge, git_run, monkeypatch):
    original = worker_git.subprocess.run
    def stop_after_commit(cmd, **kwargs):
        result = original(cmd, **kwargs)
        if cmd[:2] == ["git", "commit"]: bridge.binding._stop_event.set()
        return result
    monkeypatch.setattr(worker_git.subprocess, "run", stop_after_commit)
    result = worker_git.finish_task(bridge.binding.task_id, "Stop", run_tests=False,
                                   worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is False
    assert not any(cmd[:2] == ["git", "push"] for cmd in git_run)
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["status"] == "in_progress"


def test_missing_review_ack_never_records_task_completion_or_returns_lease(bridge, git_run, monkeypatch):
    original = bridge.binding._client.release
    def lost(*args, **kwargs):
        original(*args, **kwargs)  # Commit occurred, acknowledgement did not reach worker.
        raise OSError("unknown release")
    monkeypatch.setattr(bridge.binding._client, "release", lost)
    result = worker_git.finish_task(bridge.binding.task_id, "Review", run_tests=False,
                                   worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is False
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["status"] == "review"
    assert bridge.binding.completed_task_ids == ()
    assert bridge.binding.return_lease() is False


def test_unknown_content_ack_blocks_review_release_without_retry(bridge, git_run, monkeypatch):
    original = bridge.binding._client.update
    release_calls = []
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("unknown update")
    monkeypatch.setattr(bridge.binding._client, "update", lost)
    monkeypatch.setattr(bridge.binding._client, "release", lambda *a, **k: release_calls.append(k))
    result = worker_git.finish_task(bridge.binding.task_id, "Review", run_tests=False,
                                   worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is False and not release_calls
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["description"].startswith("PR: " + PR)
    assert bridge.binding.return_lease() is False


@pytest.mark.parametrize("url", ["", "not-a-pr", "https://github.com/org/repo/pull/0",
                                  "https://external.invalid/org/repo/pull/123"])
def test_invalid_pr_response_cannot_record_review(bridge, git_run, monkeypatch, url):
    original = worker_git.subprocess.run
    def invalid_pr(cmd, **kwargs):
        result = original(cmd, **kwargs)
        if cmd[:3] == ["gh", "pr", "create"]: result.stdout = url
        return result
    monkeypatch.setattr(worker_git.subprocess, "run", invalid_pr)
    result = worker_git.finish_task(bridge.binding.task_id, "Review", run_tests=False,
                                   worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is False
    canonical = bridge.binding._client.task_snapshot(bridge.binding.task_id)
    assert canonical["status"] == "in_progress" and not canonical["description"]


def test_legacy_finish_cannot_overwrite_an_existing_canonical_holder(bridge, git_run, monkeypatch):
    from hub._services import task_lease
    # The holder was created with the fixture's injected clock. The manual
    # caller must observe that same authority clock, not today's wall time.
    monkeypatch.setattr(task_lease, "_utcnow", bridge.binding._clock)
    result = worker_git.finish_task(bridge.binding.task_id, "Foreign owner", run_tests=False,
                                   db_path=bridge.binding._client._db_path)
    assert result["success"] is False
    assert not git_run
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["status"] == "in_progress"
    bridge.binding.assert_active()


@pytest.fixture(params=[None, "runner-" + "x" * 56 + ".local"], ids=["native-host", "long-fqdn"])
def legacy_acquire_diagnostics(bridge, monkeypatch, request):
    """Keep the original acquire behavior and expose failures in isolated tests."""
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    original = WorkerLeaseBinding.acquire
    diagnostics = []
    if request.param is not None:
        monkeypatch.setattr(worker_git.socket, "gethostname", lambda: request.param)

    def acquire(cls, *args, **kwargs):
        diagnostics.append({"stage": "acquire", "host": kwargs.get("host"),
                            "host_length": len(kwargs.get("host", ""))})
        try:
            binding = original(*args, **kwargs)
        except Exception as exc:
            diagnostics.append({"exception": type(exc).__name__, "message": str(exc)})
            if exc.__context__ is not None:
                diagnostics.append({"cause": type(exc.__context__).__name__,
                                    "message": str(exc.__context__)})
            raise
        diagnostics.append({"stage": "acquired"})
        return binding

    monkeypatch.setattr(WorkerLeaseBinding, "acquire", classmethod(acquire))
    return diagnostics


def test_legacy_finish_acquires_canonical_ownership_before_publication(
        bridge, git_run, legacy_acquire_diagnostics):
    from system.tests.test_task_lease_service import _connect, _insert
    with _connect(bridge.binding._client._db_path) as conn:
        task_id = _insert(conn, title="Unleased work", assigned_to="BACH")
    _add_task_tree(task_id)
    result = worker_git.finish_task(task_id, "Explicit finish", run_tests=False,
                                   db_path=bridge.binding._client._db_path)
    assert result["success"] is True and result["status"] == "review", (result, legacy_acquire_diagnostics)
    with _connect(bridge.binding._client._db_path) as conn:
        row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert row["status"] == "review" and row["claim_fence"] == 1 and row["claim_id"] is None
    assert not row["completed_at"]


def test_legacy_wip_unknown_return_ack_has_no_success_or_retry(
        bridge, git_run, monkeypatch, legacy_acquire_diagnostics):
    from system.tests.test_task_lease_service import _connect, _insert
    from hub._services.task_lease_client import TaskLeaseClient
    with _connect(bridge.binding._client._db_path) as conn:
        task_id = _insert(conn, title="Unleased WIP", assigned_to="BACH")
    _add_task_tree(task_id)
    original = TaskLeaseClient.release
    calls = []
    def lost(client, *args, **kwargs):
        calls.append(kwargs["outcome"])
        original(client, *args, **kwargs)
        raise OSError("unknown cleanup acknowledgement")
    monkeypatch.setattr(TaskLeaseClient, "release", lost)
    result = worker_git.finish_task(task_id, "WIP", is_wip=True, db_path=bridge.binding._client._db_path)
    assert result["success"] is False
    assert calls == ["return"], (result, legacy_acquire_diagnostics)
    snapshot = bridge.binding._client.task_snapshot(task_id)
    assert snapshot["status"] == "pending" and "[WIP]" in snapshot["description"]


@pytest.mark.parametrize("bad", [None, {"released": True, "status": "review"}, "PR ready",
    LeaseReleaseAck(True, 2, "review", "review", 1, "2026-10-05T12:00:00+00:00"),
    LeaseReleaseAck(True, 1, "review", "review", 0, "2026-10-05T12:00:00+00:00"),
    LeaseReleaseAck(False, 1, "review", "review", 1, "2026-10-05T12:00:00+00:00"),
    LeaseReleaseAck(True, True, "review", "review", 1, "2026-10-05T12:00:00+00:00"),
    LeaseReleaseAck(True, 1, "review", "review", True, "2026-10-05T12:00:00+00:00"),
    LeaseReleaseAck(True, 1, "done", "review", 1, "2026-10-05T12:00:00+00:00"),
    LeaseReleaseAck(True, 1, "review", "done", 1, "2026-10-05T12:00:00+00:00"),
])
def test_untyped_review_ack_cannot_prove_review_or_success(bridge, git_run, monkeypatch, bad):
    monkeypatch.setattr(bridge.binding._client, "release", lambda *a, **k: bad)
    result = worker_git.finish_task(bridge.binding.task_id, "Review", run_tests=False,
                                   worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is False
    assert bridge.binding.reviewed_task_ids == () and bridge.binding.completed_task_ids == ()
    assert bridge.binding.return_lease() is False



def test_bound_file_write_requires_grant_and_exact_task_tree(bridge, git_run, tmp_path):
    tree = Path(os.environ["BACH_WORKTREES_DIR"]) / f"task-{bridge.binding.task_id}"
    outside = tmp_path / "outside.txt"
    denied = exec_tool(
        "write_file", {"path": str(outside), "content": "outside"}, "full",
        worker_task_binding=bridge.binding, require_task_binding=True,
        allowed_tools={"write_file"},
    )
    assert "BLOCKIERT" in denied and not outside.exists()

    private_path = tree / "allowed.txt"
    no_grant = exec_tool(
        "write_file", {"path": str(private_path), "content": "no grant"}, "full",
        worker_task_binding=bridge.binding, require_task_binding=True,
    )
    assert "Schreibfreigabe" in no_grant and not private_path.exists()

    written = exec_tool(
        "write_file", {"path": str(private_path), "content": "bound"}, "full",
        worker_task_binding=bridge.binding, require_task_binding=True,
        allowed_tools={"write_file"},
    )
    assert "Geschrieben" in written
    assert private_path.read_text(encoding="utf-8") == "bound"


def test_bound_command_requires_checked_cwd_and_rejects_python_code(bridge, git_run):
    result = exec_tool(
        "execute_command", {"command": "python -m pytest -q"}, "full",
        worker_task_binding=bridge.binding, require_task_binding=True,
        allowed_tools={"execute_command"},
    )
    # Public failures are neutral since the typed tool error contract (#379).
    assert "BLOCKIERT" in result or "nicht bestätigt" in result
    tree = Path(os.environ["BACH_WORKTREES_DIR"]) / f"task-{bridge.binding.task_id}"
    result = exec_tool(
        "execute_command", {"command": "python -c print(1)", "cwd": str(tree)}, "full",
        worker_task_binding=bridge.binding, require_task_binding=True,
        allowed_tools={"execute_command"},
    )
    assert "BLOCKIERT" in result or "nicht bestätigt" in result

@pytest.mark.parametrize("case", ["id-string", "id-bool", "id-missing", "result-empty", "result-too-long"])
def test_bound_task_manage_rejects_public_arguments_before_private_operation(bridge, monkeypatch, case):
    binding = bridge.binding
    calls = []

    def should_not_run(self, args, *, _dispatch_marked=False):
        calls.append((args, _dispatch_marked))
        return "unexpected private call"

    monkeypatch.setattr(type(binding), "execute_task_manage", should_not_run)
    args = {"action": "submit_result", "task_id": binding.task_id,
            "result": "Konkretes Ergebnis mit Quellbeleg."}
    expected = "numerische Ganzzahl"
    if case == "id-string":
        args["task_id"] = str(binding.task_id)
    elif case == "id-bool":
        args["task_id"] = True
    elif case == "id-missing":
        args.pop("task_id")
    elif case == "result-empty":
        args["result"] = "  "
        expected = "Taskergebnis ist ungültig"
    else:
        args["result"] = "x" * 3001
        expected = "Taskergebnis ist ungültig"

    result = exec_tool(
        "task_manage", args, "safe", worker_task_binding=binding,
        require_task_binding=True, allowed_tools={"task_manage"},
    )

    assert expected in result
    assert calls == []
    assert bridge.binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"


def test_bound_task_manage_accepts_valid_own_result_as_review_submission(bridge):
    binding = bridge.binding
    result = exec_tool(
        "task_manage", {"action": "submit_result", "task_id": binding.task_id, "complete": True,
                       "result": "Unabhängig belegtes Ergebnis mit konkreter Prüfgrenze."},
        "safe", worker_task_binding=binding, require_task_binding=True,
        allowed_tools={"task_manage"},
    )

    assert result == f"Task #{binding.task_id}: Ergebnis gespeichert; Abschlussstatus wird nach Policy ermittelt."
    assert binding.completed_task_ids == ()
    assert binding.reviewed_task_ids == (binding.task_id,)


def test_bound_task_manage_hides_native_task_authority_failure(bridge):
    binding = bridge.binding
    result = exec_tool(
        "task_manage", {"action": "submit_result", "task_id": binding.task_id + 1, "complete": True,
                       "result": "Ein synthetisches Ergebnis für den falschen Task."},
        "safe", worker_task_binding=binding, require_task_binding=True,
        allowed_tools={"task_manage"},
    )

    assert result == "Taskoperation nicht bestätigt; Taskbindung prüfen."
    assert "Mutation gehört" not in result
    assert bridge.binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"


def test_bound_task_manage_hides_unknown_native_submission_ack(bridge, monkeypatch):
    binding = bridge.binding

    def unknown_ack(*args, **kwargs):
        raise OSError("PRIVATE synthetic lease/capability details")

    monkeypatch.setattr(binding._client, "submit_result", unknown_ack)
    result = exec_tool(
        "task_manage", {"action": "submit_result", "task_id": binding.task_id, "complete": True,
                       "result": "Ein synthetisches Ergebnis ohne bestätigten ACK."},
        "safe", worker_task_binding=binding, require_task_binding=True,
        allowed_tools={"task_manage"},
    )

    assert result == "Taskoperation nicht bestätigt; Taskbindung prüfen."
    assert "PRIVATE" not in result and "capability" not in result.lower()
    assert binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"
@pytest.mark.parametrize("origin", [
    "https://github.com/ellmos-ai/bach.git",
    "https://github.com/ellmos-ai/bach",
    "git@github.com:ellmos-ai/bach.git",
    "ssh://git@github.com/ellmos-ai/bach.git",
])
def test_canonical_public_bach_origin_accepts_only_supported_forms(origin):
    assert worker_git._canonical_origin("ellmos-ai/bach", origin) == "https://github.com/ellmos-ai/bach"


@pytest.mark.parametrize("origin", [
    "https://github.com/ellmos-ai/other.git",
    "https://user:token@github.com/ellmos-ai/bach.git",
    "https://github.com.evil.invalid/ellmos-ai/bach.git",
    "http://github.com/ellmos-ai/bach.git",
    "https://github.com:bad/ellmos-ai/bach.git",
    "https://github.com/ellmos-ai/bach.git?mirror=other",
])
def test_canonical_public_bach_origin_rejects_untrusted_identity(origin):
    with pytest.raises(RuntimeError):
        worker_git._canonical_origin("ellmos-ai/bach", origin)


def test_public_source_proof_requires_anonymous_public_metadata_and_exact_local_main(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _REAL_SUBPROCESS_RUN(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    _REAL_SUBPROCESS_RUN(["git", "config", "user.name", "Reader Test"], cwd=repo, check=True)
    _REAL_SUBPROCESS_RUN(["git", "config", "user.email", "reader@example.invalid"], cwd=repo, check=True)
    (repo / "README.md").write_text("public source", encoding="utf-8")
    _REAL_SUBPROCESS_RUN(["git", "add", "README.md"], cwd=repo, check=True)
    _REAL_SUBPROCESS_RUN(["git", "commit", "-m", "public base"], cwd=repo, check=True, capture_output=True)
    _REAL_SUBPROCESS_RUN(["git", "remote", "add", "origin", "git@github.com:ellmos-ai/bach.git"], cwd=repo, check=True)
    sha = _REAL_SUBPROCESS_RUN(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                               capture_output=True, text=True).stdout.strip()
    payloads = {
        "https://api.github.com/repos/ellmos-ai/bach": {
            "full_name": "ellmos-ai/bach", "private": False,
            "visibility": "public", "default_branch": "main",
        },
        "https://api.github.com/repos/ellmos-ai/bach/branches/main": {
            "name": "main", "commit": {"sha": sha},
        },
    }
    monkeypatch.setattr(worker_git, "_github_json", lambda url: payloads[url])
    proof = worker_git._public_main_source(repo)
    assert proof["source_sha"] == sha
    assert proof["source_ref"] == "refs/heads/main"
    assert proof["private"] is False and proof["visibility"] == "public"
    assert proof["origin"] == "https://github.com/ellmos-ai/bach"

    payloads["https://api.github.com/repos/ellmos-ai/bach"]["private"] = True
    with pytest.raises(RuntimeError, match="Öffentliche Quellbindung"):
        worker_git._public_main_source(repo)
    payloads["https://api.github.com/repos/ellmos-ai/bach"]["private"] = False
    payloads["https://api.github.com/repos/ellmos-ai/bach/branches/main"]["commit"]["sha"] = "f" * 40
    with pytest.raises(RuntimeError, match="Lokale BACH-Basis"):
        worker_git._public_main_source(repo)


def _public_bound_repo(tmp_path, monkeypatch):
    repo = tmp_path / "public-repo"
    worktrees = tmp_path / "worktrees"
    repo.mkdir()
    worktrees.mkdir()
    _REAL_SUBPROCESS_RUN(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    _REAL_SUBPROCESS_RUN(["git", "config", "user.name", "Reader Test"], cwd=repo, check=True)
    _REAL_SUBPROCESS_RUN(["git", "config", "user.email", "reader@example.invalid"], cwd=repo, check=True)
    (repo / "README.md").write_text("base source", encoding="utf-8")
    _REAL_SUBPROCESS_RUN(["git", "add", "README.md"], cwd=repo, check=True)
    _REAL_SUBPROCESS_RUN(["git", "commit", "-m", "public base"], cwd=repo, check=True, capture_output=True)
    _REAL_SUBPROCESS_RUN(["git", "remote", "add", "origin", "https://github.com/ellmos-ai/bach.git"], cwd=repo, check=True)
    sha = _REAL_SUBPROCESS_RUN(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                               capture_output=True, text=True).stdout.strip()
    proof = {
        "schema": worker_git._PUBLIC_SOURCE_SCHEMA, "task_id": "",
        "repository": "ellmos-ai/bach", "origin": "https://github.com/ellmos-ai/bach",
        "source_ref": "refs/heads/main", "source_sha": sha, "visibility": "public",
        "private": False, "metadata_verified": True, "ref_verified": True,
        "verified_at": worker_git._utc_now(),
    }
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: repo)
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: worktrees)
    monkeypatch.setattr(worker_write_guard, "_fresh_locks", lambda *a, **k: None)
    monkeypatch.setattr(worker_git, "_public_main_source", lambda _repo, _slug=None: dict(proof))
    return repo, worktrees, proof


def test_bound_public_worktree_pins_exact_ref_and_rejects_unregistered_existing_tree(
        tmp_path, request, monkeypatch):
    task_bridge = request.getfixturevalue("bridge")
    repo, _worktrees, proof = _public_bound_repo(tmp_path, monkeypatch)
    commands = []
    run = subprocess.run
    def capture(argv, **kwargs):
        commands.append(list(argv))
        return run(argv, **kwargs)
    monkeypatch.setattr(worker_git.subprocess, "run", capture)

    target = worker_git.start_task_worktree(
        task_bridge.binding.task_id, base_branch="main", worker_task_binding=task_bridge.binding,
        require_task_binding=True, task_code_capability=True,
    )
    head = _REAL_SUBPROCESS_RUN(["git", "rev-parse", "HEAD"], cwd=target, check=True,
                                capture_output=True, text=True).stdout.strip()
    assert head == proof["source_sha"]
    record = worker_git.read_task_public_source_registration(repo, target, task_bridge.binding.task_id)
    assert record["source_sha"] == proof["source_sha"]
    assert record["task_id"] == str(task_bridge.binding.task_id)
    assert not any(command[:2] == ["git", "fetch"] for command in commands)

    with pytest.raises(RuntimeError, match="Quellregistrierung"):
        worker_git._store_public_source_registration(
            repo, target, task_bridge.binding.task_id,
            {**record, "source_sha": "not-a-valid-registration-sha"},
        )


def test_bound_public_worktree_does_not_create_when_public_proof_is_unavailable(
        tmp_path, request, monkeypatch):
    task_bridge = request.getfixturevalue("bridge")
    _repo, worktrees, _proof = _public_bound_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(worker_git, "_public_main_source",
                        lambda _repo, _slug=None: (_ for _ in ()).throw(RuntimeError("unavailable")))
    target = worktrees / f"task-{task_bridge.binding.task_id}"
    with pytest.raises(RuntimeError, match="unavailable"):
        worker_git.start_task_worktree(
            task_bridge.binding.task_id, base_branch="main", worker_task_binding=task_bridge.binding,
            require_task_binding=True, task_code_capability=True,
        )
    assert not target.exists()


def test_bound_existing_worktree_without_public_registration_is_not_upgraded(
        tmp_path, request, monkeypatch):
    task_bridge = request.getfixturevalue("bridge")
    _public_bound_repo(tmp_path, monkeypatch)
    target = worker_git.start_task_worktree(
        task_bridge.binding.task_id, base_branch="main", worker_task_binding=task_bridge.binding,
        require_task_binding=True,
    )
    with pytest.raises(RuntimeError, match="Quellregistrierung"):
        worker_git.start_task_worktree(
            task_bridge.binding.task_id, base_branch="main", worker_task_binding=task_bridge.binding,
            require_task_binding=True, task_code_capability=True,
        )
    assert target.is_dir()

def test_github_public_metadata_reader_requires_https_api_host_and_sends_no_auth(monkeypatch):
    import json
    import urllib.request

    seen = {}
    class Response:
        status = 200
        def geturl(self): return "https://api.github.com/repos/ellmos-ai/bach"
        def read(self, limit): return json.dumps({"private": False}).encode()
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    def fake_open(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    result = worker_git._github_json("https://api.github.com/repos/ellmos-ai/bach")
    assert result == {"private": False}
    assert seen["timeout"] == 8
    assert "Authorization" not in dict(seen["request"].header_items())

    class Redirected(Response):
        def geturl(self): return "https://api.evil.invalid/repo"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: Redirected())
    with pytest.raises(RuntimeError, match="Öffentliche Quellbindung"):
        worker_git._github_json("https://api.github.com/repos/ellmos-ai/bach")

@pytest.mark.parametrize("task_id", [True, False, 0, -1, 1.5, "", "01", "+1", "-1", "1\n-c", "--help", "x", 2**63])
def test_public_source_config_key_rejects_noncanonical_task_ids(task_id):
    with pytest.raises(RuntimeError, match="Taskkennung"):
        worker_git._public_source_config_key(task_id)


@pytest.mark.parametrize("task_id", [1, "1", 2124, "2124", 2**63 - 1, str(2**63 - 1)])
def test_public_source_config_key_uses_only_positive_numeric_identity(task_id):
    assert worker_git._public_source_config_key(task_id) == f"branch.bach-task/{int(task_id)}.bach-public-source"


@pytest.mark.parametrize("operation", ["", "status", "git", "--help", "origin\n-c"])
def test_public_git_reader_rejects_unknown_operations_before_execution(tmp_path, monkeypatch, operation):
    calls = []
    monkeypatch.setattr(worker_git.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError, match="Git-Leseoperation"):
        worker_git._git_text(tmp_path, operation)
    assert calls == []


def test_public_git_reader_constructs_fixed_git_commands(tmp_path, monkeypatch):
    calls = []
    def capture(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="verified\n", stderr="")
    monkeypatch.setattr(worker_git.subprocess, "run", capture)
    for operation in ["origin", "main", "head"]:
        assert worker_git._git_text(tmp_path, operation) == "verified"
    assert worker_git._git_text(tmp_path, "registration", task_id="2124") == "verified"
    assert [entry[0] for entry in calls] == [
        ["git", "remote", "get-url", "origin"],
        ["git", "rev-parse", "--verify", "refs/heads/main^{commit}"],
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        ["git", "config", "--local", "--get", "branch.bach-task/2124.bach-public-source"],
    ]
    assert all(kwargs["shell"] is False and kwargs["stdin"] == subprocess.DEVNULL for _, kwargs in calls)


def test_public_git_registration_reader_validates_id_before_execution(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(worker_git.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError, match="Taskkennung"):
        worker_git._git_text(tmp_path, "registration", task_id="1\n-c")
    assert calls == []

def test_bound_public_start_rejects_noncanonical_id_before_git_or_directory_creation(
        tmp_path, request, monkeypatch):
    task_bridge = request.getfixturevalue("bridge")
    repo, worktrees, _proof = _public_bound_repo(tmp_path, monkeypatch)
    calls = []
    run = subprocess.run
    def capture(argv, **kwargs):
        calls.append(list(argv))
        return run(argv, **kwargs)
    monkeypatch.setattr(worker_git.subprocess, "run", capture)
    invalid_id = f"0{task_bridge.binding.task_id}"
    with pytest.raises(RuntimeError, match="Taskkennung"):
        worker_git.start_task_worktree(
            invalid_id, repo_root=repo, base_branch="main",
            worker_task_binding=task_bridge.binding, require_task_binding=True,
            task_code_capability=True,
        )
    assert calls == []
    assert list(worktrees.iterdir()) == []
    branch = _REAL_SUBPROCESS_RUN(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/bach-task/{invalid_id}"],
        cwd=repo, capture_output=True,
    )
    assert branch.returncode == 1


def test_resolve_task_repo_maps_categories_to_positive_list(monkeypatch):
    monkeypatch.delenv("BACH_OCEAN_REPOS", raising=False)
    assert worker_git._resolve_task_repo(None) == "ellmos-ai/bach"
    assert worker_git._resolve_task_repo("") == "ellmos-ai/bach"
    assert worker_git._resolve_task_repo("general") == "ellmos-ai/bach"
    assert worker_git._resolve_task_repo("coding") == "ellmos-ai/bach"
    assert worker_git._resolve_task_repo("open-ocean") == "ellmos-ai/open-ocean"
    assert worker_git._resolve_task_repo("ellmos-system-gui") == "ellmos-ai/ellmos-system-gui"
    assert worker_git._resolve_task_repo("ellmos-ai/bach") == "ellmos-ai/bach"
    with pytest.raises(ValueError, match="Positivliste"):
        worker_git._resolve_task_repo("ellmes-ai/fremd")


def test_ocean_repos_rejects_entries_without_org(monkeypatch):
    monkeypatch.setenv("BACH_OCEAN_REPOS", "ellmos-ai/bach, open-ocean")
    with pytest.raises(ValueError):
        worker_git._ocean_repos()
    monkeypatch.setenv("BACH_OCEAN_REPOS", "ellmos-ai/open-ocean")
    assert worker_git._ocean_repos() == frozenset({"ellmos-ai/open-ocean"})


def test_ocean_clone_root_and_repo_clone_dir_follow_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_OCEAN_CLONE_DIR", str(tmp_path))
    assert worker_git._ocean_clone_root() == tmp_path.resolve()
    assert worker_git._repo_clone_dir("ellmos-ai/open-ocean") == tmp_path.resolve() / "open-ocean"


def test_is_live_path_blocked_blocks_ocean_roots_and_clones(tmp_path, monkeypatch):
    live_root = tmp_path / "live-repo"
    worktrees_root = tmp_path / "worktrees"
    ocean_root = tmp_path / "ocean"
    software_root = tmp_path / "software"
    clone_root = tmp_path / "klone"
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: live_root.resolve())
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: worktrees_root.resolve())
    monkeypatch.delenv("BACH_ALLOW_LIVE_WRITE", raising=False)
    monkeypatch.setenv("BACH_OCEAN_ROOTS", str(ocean_root))
    monkeypatch.setenv("BACH_SOFTWARE_ROOTS", str(software_root))
    monkeypatch.setenv("BACH_OCEAN_CLONE_DIR", str(clone_root))

    blocked = "Nutze start_task_worktree()"
    assert worker_git.is_live_path_blocked(live_root / "system" / "hub" / "x.py") == blocked
    assert worker_git.is_live_path_blocked(ocean_root / "open-ocean" / "README.md") == blocked
    assert worker_git.is_live_path_blocked(software_root / "ellmos-system-gui" / "app.py") == blocked
    assert worker_git.is_live_path_blocked(clone_root / "open-ocean" / "x.py") == blocked
    assert worker_git.is_live_path_blocked(worktrees_root / "task-1234") is None
    assert worker_git.is_live_path_blocked(tmp_path / "fremder-ordner") is None


def _bound_db_context(monkeypatch, db_path):
    import contextlib
    import sqlite3

    @contextlib.contextmanager
    def fake_context():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(worker_git, "_db_context", fake_context)


def _user_config_file(tmp_path, monkeypatch):
    config_path = tmp_path / "bach-user-config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BACH_USER_CONFIG", str(config_path))
    monkeypatch.delenv("BACH_ACCESS_LEVEL", raising=False)
    return config_path


def test_ensure_task_build_site_is_idempotent(tmp_path):
    import sqlite3
    from hub._services.task_schema import ensure_task_build_site

    db = tmp_path / "tasks.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, category TEXT)")
    conn.commit()
    ensure_task_build_site(conn)
    ensure_task_build_site(conn)
    conn.commit()
    assert "build_site" in [row[1] for row in conn.execute("PRAGMA table_info(tasks)")]
    conn.close()

    empty = sqlite3.connect(tmp_path / "empty.db")
    empty.execute("CREATE TABLE other (id INTEGER)")
    empty.commit()
    with pytest.raises(RuntimeError, match="Task-Migration"):
        ensure_task_build_site(empty)
    empty.close()


def test_task_build_site_fallback_chain(bridge, tmp_path, monkeypatch):
    from system.tests.test_task_lease_service import _connect, _insert

    _user_config_file(tmp_path, monkeypatch)
    _bound_db_context(monkeypatch, bridge.binding._client._db_path)
    with _connect(bridge.binding._client._db_path) as conn:
        task_id = _insert(conn, title="Build site fallback", assigned_to="BACH")
    worker_git._task_build_site(task_id)
    with _connect(bridge.binding._client._db_path) as conn:
        conn.execute("UPDATE tasks SET build_site='open-ocean', category='coding' WHERE id=?", (task_id,))
        conn.commit()
    assert worker_git._task_build_site(task_id) == "open-ocean"
    with _connect(bridge.binding._client._db_path) as conn:
        conn.execute("UPDATE tasks SET build_site=NULL, category='coding' WHERE id=?", (task_id,))
        conn.commit()
    assert worker_git._task_build_site(task_id) == "coding"
    with _connect(bridge.binding._client._db_path) as conn:
        conn.execute("UPDATE tasks SET build_site=NULL, category=NULL WHERE id=?", (task_id,))
        conn.commit()
    assert worker_git._task_build_site(task_id) == "general"
    assert worker_git._task_build_site(task_id + 12345) == "general"
    assert worker_git._task_build_site("x") == "general"


def test_build_site_routes_to_ocean_repo(bridge, tmp_path, monkeypatch):
    from system.tests.test_task_lease_service import _connect, _insert

    _user_config_file(tmp_path, monkeypatch)
    _bound_db_context(monkeypatch, bridge.binding._client._db_path)
    with _connect(bridge.binding._client._db_path) as conn:
        task_id = _insert(conn, title="Ocean routing", assigned_to="BACH")
    worker_git._task_build_site(task_id)
    with _connect(bridge.binding._client._db_path) as conn:
        conn.execute("UPDATE tasks SET build_site='open-ocean' WHERE id=?", (task_id,))
        conn.commit()
    assert worker_git._resolve_task_repo(worker_git._task_build_site(task_id)) == "ellmos-ai/open-ocean"


def test_sandbox_level_blocks_non_default_repo(bridge, git_run, tmp_path, monkeypatch):
    from system.tests.test_task_lease_service import _connect

    _user_config_file(tmp_path, monkeypatch)
    _bound_db_context(monkeypatch, bridge.binding._client._db_path)
    worker_git._task_build_site(bridge.binding.task_id)
    with _connect(bridge.binding._client._db_path) as conn:
        conn.execute("UPDATE tasks SET build_site='open-ocean' WHERE id=?", (bridge.binding.task_id,))
        conn.commit()
    monkeypatch.setenv("BACH_ACCESS_LEVEL", "sandbox")
    with pytest.raises(RuntimeError, match="sandbox"):
        worker_git.start_task_worktree(bridge.binding.task_id, base_branch="main",
                                       worker_task_binding=bridge.binding, require_task_binding=True)


def test_free_level_lifts_live_path_block(tmp_path, monkeypatch):
    live_root = tmp_path / "live-repo"
    worktrees_root = tmp_path / "worktrees"
    _user_config_file(tmp_path, monkeypatch)
    monkeypatch.setattr(worker_git, "get_live_repo_root", lambda: live_root.resolve())
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: worktrees_root.resolve())
    monkeypatch.delenv("BACH_ALLOW_LIVE_WRITE", raising=False)
    monkeypatch.setenv("BACH_OCEAN_ROOTS", str(tmp_path / "ocean"))
    monkeypatch.setenv("BACH_SOFTWARE_ROOTS", str(tmp_path / "software"))
    monkeypatch.setenv("BACH_OCEAN_CLONE_DIR", str(tmp_path / "klone"))
    assert worker_git.is_live_path_blocked(live_root / "x.py") == "Nutze start_task_worktree()"
    monkeypatch.setenv("BACH_ACCESS_LEVEL", "free")
    assert worker_git.is_live_path_blocked(live_root / "x.py") is None


def test_access_level_resolution_and_persistence(tmp_path, monkeypatch):
    config_path = _user_config_file(tmp_path, monkeypatch)
    monkeypatch.setenv("BACH_ACCESS_LEVEL", "nope")
    assert worker_git._user_access_level() == "ocean"
    monkeypatch.setenv("BACH_ACCESS_LEVEL", "free")
    assert worker_git._user_access_level() == "free"
    monkeypatch.delenv("BACH_ACCESS_LEVEL", raising=False)
    from hub._services.user_config_store import update_user_config

    update_user_config(config_path, lambda current: {**current, "access_level": "sandbox"})
    assert worker_git._user_access_level() == "sandbox"
    assert worker_git.set_user_access_level("free") == "free"
    assert worker_git._user_access_level() == "free"
    with pytest.raises(ValueError, match="Unbekannte Zugriffsstufe"):
        worker_git.set_user_access_level("bogus")


def test_receipts_and_pr_body_carry_access_level(bridge, git_run, tmp_path, monkeypatch):
    _user_config_file(tmp_path, monkeypatch)
    decoy = tmp_path / "projection-must-not-open.db"
    result = worker_git.finish_task(bridge.binding.task_id, "WIP mit Stufe", is_wip=True, db_path=decoy,
                                    worker_task_binding=bridge.binding, require_task_binding=True)
    assert result["success"] is True and result["wip"] is True
    assert "(Zugriffsstufe ocean" in bridge.binding.task_snapshot()["description"]
    result = worker_git.finish_task(bridge.binding.task_id, "Fertig", run_tests=False, db_path=decoy,
                                    worker_task_binding=bridge.binding, require_task_binding=True)
    assert result == {"success": True, "pr_url": PR, "status": "review"}
    description = bridge.binding._client.task_snapshot(bridge.binding.task_id)["description"]
    assert description.startswith("PR: " + PR) and "(Zugriffsstufe ocean" in description
    assert not decoy.exists()
    pr_cmd = next(cmd for cmd in git_run if cmd[:3] == ["gh", "pr", "create"])
    body = pr_cmd[pr_cmd.index("--body") + 1]
    assert "Zugriffsstufe dieses Worker-Laufs: ocean" in body
    assert "Nutzstufe" in body
