"""Task #2580: persistent needs_split marker and divider routing."""
import sqlite3
import subprocess
import threading

import pytest
from hub._services.chat.telegram_chat import (
    _bound_worker_prompt,
    _task_divider_available,
)
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease import LeaseValidationError, update_lease
from hub._services.task_lease_client import TaskLeaseClient

from system.tests.test_task_lease_client import _init_db, _insert_task
from system.tests.test_task_lease_client_review import T0


def _acquire(client, task_id, slot):
    return WorkerLeaseBinding.acquire_next(
        client, slot, worker_id="physical-worker@HOST", host="HOST",
        generation="generation-1", is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0)


@pytest.fixture
def task_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    yield conn
    conn.close()


def _marked_task(conn, count=1):
    task_id = _insert_task(conn, "Zu teilende Aufgabe")
    conn.execute("UPDATE tasks SET assigned_to='BACH', needs_split=? WHERE id=?", (count, task_id))
    conn.commit()
    return task_id


def test_marker_is_native_and_incremented_atomically(task_db):
    task_id = _marked_task(task_db, 0)
    client = TaskLeaseClient(conn=task_db)
    binding = _acquire(client, task_id, {"id": "slot"})
    binding.record_worktree_result(task_id, "[WIP] erster Stand", needs_split=True)
    snapshot = client.task_snapshot(task_id)
    assert snapshot["needs_split"] == 1
    assert snapshot["description"].endswith("[WIP] erster Stand")
    binding.record_worktree_result(task_id, "[WIP] zweiter Stand", needs_split=True)
    assert client.task_snapshot(task_id)["needs_split"] == 2
    with pytest.raises(LeaseValidationError):
        update_lease(task_db, task_id, lease_id=binding._ack.lease_id, fence=binding._ack.fence,
                     task_version=binding.task_snapshot()["task_version"], changes={"needs_split": -1})


def test_candidates_put_marked_work_first(task_db):
    marked = _marked_task(task_db, 2)
    ordinary = _insert_task(task_db, "Gewöhnliche Aufgabe")
    task_db.execute("UPDATE tasks SET priority='P1'")
    task_db.commit()
    tasks = TaskLeaseClient(conn=task_db).task_candidates()["tasks"]
    assert tasks[0]["id"] == marked
    assert tasks[0]["needs_split"] == 2
    assert ordinary != marked


def test_divider_gets_marked_work_before_other_slots(task_db):
    marked = _marked_task(task_db)
    ordinary = _insert_task(task_db, "Andere Arbeit")
    task_db.execute("UPDATE tasks SET assigned_to='BACH'")
    task_db.commit()
    client = TaskLeaseClient(conn=task_db)
    chosen = _acquire(client, marked, {"id": "divider", "role_id": "task-divider", "divider_available": True})
    assert chosen.task_id == marked
    assert ordinary != marked


def test_other_slot_skips_marked_work_while_divider_is_available(task_db):
    marked = _marked_task(task_db)
    ordinary = _insert_task(task_db, "Andere Arbeit")
    task_db.execute("UPDATE tasks SET assigned_to='BACH'")
    task_db.commit()
    client = TaskLeaseClient(conn=task_db)
    chosen = _acquire(client, marked, {"id": "worker", "sub_mode": "task_worker", "divider_available": True})
    assert chosen.task_id == ordinary


def test_next_worker_splits_when_no_divider_is_available(task_db):
    marked = _marked_task(task_db)
    _insert_task(task_db, "Spätere Arbeit")
    task_db.execute("UPDATE tasks SET assigned_to='BACH'")
    task_db.commit()
    client = TaskLeaseClient(conn=task_db)
    chosen = _acquire(client, marked, {"id": "worker", "sub_mode": "task_worker", "divider_available": False})
    assert chosen.task_id == marked
    prompt = _bound_worker_prompt(chosen, "Arbeite am WIP-Stand")
    assert "höchstens zwei Kontextübergaben" in prompt
    assert '"needs_split": 1' in prompt


def test_decompose_clears_marker_without_changing_assignment(task_db):
    task_id = _marked_task(task_db)
    client = TaskLeaseClient(conn=task_db)
    binding = _acquire(client, task_id, {"id": "divider", "role_id": "task-divider", "divider_available": True})
    task_db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    task_db.commit()
    binding.execute_task_manage({"action": "decompose", "task_id": task_id,
                                 "subtasks": [{"title": "Eigenständiger Teil"}], "close_parent": False})
    parent = client.task_snapshot(task_id)
    child = client.task_candidates()["tasks"][0]
    assert parent["needs_split"] == 0
    assert parent["assigned_to"] == "BACH"
    assert child["assigned_to"] == "BACH"


def test_divider_inventory_distinguishes_unavailable_roles(monkeypatch):
    import hub._services.chat.telegram_chat as control
    monkeypatch.setattr(control, "list_workers", lambda: [
        {"role_id": "task-divider", "enabled": True, "status": "running"},
        {"role_id": "other", "enabled": True, "status": "running"},
    ])
    assert _task_divider_available() is True
    monkeypatch.setattr(control, "list_workers", lambda: [
        {"role_id": "task-divider", "enabled": True, "status": "error"},
    ])
    assert _task_divider_available() is False
    monkeypatch.setattr(control, "list_workers", lambda: (_ for _ in ()).throw(RuntimeError("unreadable")))
    assert _task_divider_available() is True


def test_handoff_state_is_kept_for_context_wip():
    from types import SimpleNamespace

    from hub._services.chat.chat_runtime import _resume_with_handoff_state
    session = SimpleNamespace()
    original = [{"role": "system", "content": "System"}]
    summary = [{"role": "user", "content": "RESUME mit Befund"}]
    trail = "[LESESPUR dieses Laufs]\n- gelesen a.py: Zeilen 1–20"
    _, history = _resume_with_handoff_state(
        session, original, summary, background_task=False, has_tools=False,
        round_num=1, max_rounds=5, read_trail=trail)
    assert session.last_handoff_summary is summary
    assert session.last_handoff_read_trail == trail
    assert any(message.get("content") == trail for message in history)


def test_context_wip_without_worktree_records_note_and_split(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from hub import worker_git
    from hub._services.chat.telegram_chat import _secure_context_wip
    calls = []
    class Binding:
        task_id = 42
        closed = False
        def assert_active(self):
            return None
        def record_worktree_result(self, task_id, annotation, *, needs_split=False):
            calls.append((task_id, annotation, needs_split))
    binding = Binding()
    control = SimpleNamespace(task_binding=binding)
    session = SimpleNamespace(
        last_handoff_summary=[{"role": "user", "content": "RESUME mit token=abc123"}],
        last_handoff_read_trail="[LESESPUR]\n- gelesen a.py: Zeilen 1–20")
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: tmp_path / "missing")
    result = _secure_context_wip(control, session, "completion_reserve_context_exhausted")
    assert result["success"] is True and result["needs_split"] is True
    task_id, annotation, needs_split = calls[0]
    assert task_id == 42 and needs_split is True
    assert "completion_reserve_context_exhausted" in annotation
    assert "token=[redacted]" in annotation and "abc123" not in annotation
    assert "Lesespur" in annotation and "a.py" in annotation


def test_context_wip_uses_wip_commit_path(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from hub import worker_git
    from hub._services.chat.telegram_chat import _secure_context_wip
    target = tmp_path / "task-42"
    target.mkdir()
    calls = []
    class Binding:
        task_id = 42
        closed = False
        def assert_active(self):
            return None
    control = SimpleNamespace(task_binding=Binding())
    session = SimpleNamespace(last_handoff_summary=[], last_handoff_read_trail="")
    monkeypatch.setattr(worker_git, "get_worktrees_dir", lambda: tmp_path)
    monkeypatch.setattr(worker_git, "changed_worktree_files", lambda path: ["system/a.py"])
    def finish(*args, **kwargs):
        calls.append(kwargs)
        return {"success": True}
    monkeypatch.setattr(worker_git, "finish_task", finish)
    result = _secure_context_wip(control, session, "handoff_context_too_large")
    assert result["success"] is True
    kwargs = calls[0]
    assert kwargs["is_wip"] is True and kwargs["run_tests"] is False
    assert kwargs["needs_split"] is True
    assert "system/a.py" in kwargs["result_annotation"]
    assert "Keine abgeschlossene Übergabe" in kwargs["result_annotation"]


def test_finish_task_preserves_wip_commit_push_and_receipt(monkeypatch, tmp_path):
    from hub import worker_git
    from hub._services.chat import worker_write_guard
    remote = tmp_path / "origin.git"
    source = tmp_path / "source"
    target = tmp_path / "worktrees" / "task-42"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
    (source / "README.md").write_text("# Synthetic\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=source, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=source, check=True, capture_output=True)
    target.parent.mkdir()
    subprocess.run(["git", "worktree", "add", str(target), "-b", "bach-task/42"],
                   cwd=source, check=True, capture_output=True)
    (target / "new.txt").write_text("synthetic WIP\n", encoding="utf-8")
    monkeypatch.setenv("BACH_WORKTREES_DIR", str(target.parent))
    monkeypatch.setattr(worker_write_guard, "authorize_mutation", lambda *args, **kwargs: (target, ()))
    calls = []
    class Binding:
        task_id = 42
        def assert_active(self):
            return None
        def record_worktree_result(self, task_id, annotation, *, needs_split=False):
            calls.append((task_id, annotation, needs_split))
    assert worker_git.changed_worktree_files(target) == ["new.txt"]
    result = worker_git.finish_task(
        42, "Kontextgrenze", is_wip=True, run_tests=False,
        worker_task_binding=Binding(), result_annotation="[WIP] synthetischer Kontext",
        needs_split=True)
    assert result["success"] is True and result["needs_split"] is True
    subject = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=target,
                             check=True, capture_output=True, text=True).stdout.strip()
    assert subject.startswith("[WIP] [task 42] Kontextgrenze")
    local_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target,
                               check=True, capture_output=True, text=True).stdout.strip()
    remote_line = subprocess.run(["git", "ls-remote", str(remote), "refs/heads/bach-task/42"],
                                 check=True, capture_output=True, text=True).stdout
    assert remote_line.startswith(local_sha)
    assert calls == [(42, "[WIP] synthetischer Kontext", True)]
