"""Canonical worktree receipts against isolated authority; no Git publication."""
from types import SimpleNamespace

import pytest

from system.tests.test_worker_tool_bridge import bridge
from hub import worker_git
from hub._services.chat.bach_tools import exec_tool
from hub._services.task_lease_client import LeaseReleaseAck


PR = "https://github.com/ellmos-ai/bach/pull/123"


@pytest.fixture
def git_run(bridge, tmp_path, monkeypatch):
    root = tmp_path / "worktrees"
    (root / f"task-{bridge.binding.task_id}").mkdir(parents=True)
    monkeypatch.setenv("BACH_WORKTREES_DIR", str(root))
    monkeypatch.setattr(worker_git, "scan_for_secrets", lambda path: [])
    monkeypatch.setattr(worker_git, "check_git_diff", lambda path: [])
    calls = []
    def physical(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=PR if cmd[:3] == ["gh", "pr", "create"] else "", stderr="")
    monkeypatch.setattr(worker_git.subprocess, "run", physical)
    return calls


def test_bound_finish_records_review_only_at_canonical_authority(bridge, git_run, tmp_path):
    decoy = tmp_path / "projection-must-not-open.db"
    result = worker_git.finish_task(bridge.binding.task_id, "Actual implementation", run_tests=False,
                                   db_path=decoy, worker_task_binding=bridge.binding, require_task_binding=True)
    assert result == {"success": True, "pr_url": PR, "status": "review"}
    canonical = bridge.binding._client.task_snapshot(bridge.binding.task_id)
    assert canonical["status"] == "review" and canonical["description"] == "PR: " + PR
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
                       worker_task_binding=bridge.binding, require_task_binding=True)
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
    assert bridge.binding._client.task_snapshot(bridge.binding.task_id)["description"] == "PR: " + PR
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


def test_legacy_finish_acquires_canonical_ownership_before_publication(bridge, git_run):
    from system.tests.test_task_lease_service import _connect, _insert
    with _connect(bridge.binding._client._db_path) as conn:
        task_id = _insert(conn, title="Unleased work", assigned_to="BACH")
    (worker_git.get_worktrees_dir() / f"task-{task_id}").mkdir()
    result = worker_git.finish_task(task_id, "Explicit finish", run_tests=False,
                                   db_path=bridge.binding._client._db_path)
    assert result["success"] is True and result["status"] == "review"
    with _connect(bridge.binding._client._db_path) as conn:
        row = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    assert row["status"] == "review" and row["claim_fence"] == 1 and row["claim_id"] is None
    assert not row["completed_at"]


def test_legacy_wip_unknown_return_ack_has_no_success_or_retry(bridge, git_run, monkeypatch):
    from system.tests.test_task_lease_service import _connect, _insert
    from hub._services.task_lease_client import TaskLeaseClient
    with _connect(bridge.binding._client._db_path) as conn:
        task_id = _insert(conn, title="Unleased WIP", assigned_to="BACH")
    (worker_git.get_worktrees_dir() / f"task-{task_id}").mkdir()
    original = TaskLeaseClient.release
    calls = []
    def lost(client, *args, **kwargs):
        calls.append(kwargs["outcome"])
        original(client, *args, **kwargs)
        raise OSError("unknown cleanup acknowledgement")
    monkeypatch.setattr(TaskLeaseClient, "release", lost)
    result = worker_git.finish_task(task_id, "WIP", is_wip=True, db_path=bridge.binding._client._db_path)
    assert result["success"] is False
    assert calls == ["return"]
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
