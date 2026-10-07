# SPDX-License-Identifier: MIT
"""Task transitions of a continuous worker, without live TaskDB or inference."""
import importlib
import pytest
from system.tests.test_task_lease_client import mem_db
from hub._services.task_lease_client import TaskLeaseClient
from hub._services import task_lease_client as lease_module

from hub._services.chat.chat_runtime import ChatSession
from hub._services.chat.slots_config import (
    add_worker, get_worker_slot, initialize_slots_config, update_slot,
)


@pytest.mark.parametrize(("worker_type", "receipt_kind"), [
    (kind, receipt) for kind in ("continuous", "persistent")
    for receipt in ("matched", "foreign", "next-assignment-denied", "review", "review-text", "blocked", "returned")
] + [("once", "review")])
@pytest.mark.parametrize("entrypoint", ["http", "native"])
def test_continuous_worker_advances_task_binding_and_assignment(tmp_path, monkeypatch, mem_db, worker_type, receipt_kind, entrypoint):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    initialize_slots_config(path)
    worker = add_worker({"name": "Transition", "type": worker_type, "task_id": 42,
                         "sub_mode": "task_worker", "pause_basis": "tasks"}, path=path)
    wid = worker["id"]
    session = ChatSession()
    session.chat_id = wid
    calls, starts, ends, pauses = [], [], [], []
    mem_db.executemany("INSERT INTO tasks (id, title, status, priority) VALUES (?, ?, 'pending', ?)",
                      [(42, "First canonical task", "P1"), (43, "Second canonical task", "P2")])
    mem_db.execute("UPDATE tasks SET assigned_to='BACH'")
    mem_db.commit()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setattr(control, "_native_task_client", lambda: TaskLeaseClient(conn=mem_db), raising=False)
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: get_worker_slot(ident, path=path))
    monkeypatch.setattr(control, "update_slot", lambda ident, change: update_slot(ident, change, path=path))
    monkeypatch.setattr(control, "record_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (object(), "test-model"))
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: session)

    def begin(**kwargs):
        starts.append(kwargs)
        if receipt_kind == "next-assignment-denied" and len(starts) == 2:
            raise ValueError("synthetic assignment denied")
        return kwargs
    monkeypatch.setattr(control, "begin_assignment", begin)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kw: ends.append((assignment, kw)))

    async def process(prompt, *a, **kw):
        calls.append(prompt)
        assert len(calls) <= 2
        binding = session.worker_task_binding
        assert binding is not None
        assert binding.task_id == (42 if len(calls) == 1 or receipt_kind in {"foreign", "review-text"} else 43)
        assert binding.task_snapshot()["title"] in prompt
        assert binding._ack.lease_id not in prompt
        binding.assert_active()
        if receipt_kind in {"blocked", "returned"} and len(calls) == 1:
            binding.execute_task_manage({"action": "update", "task_id": binding.task_id,
                                         "status": "blocked" if receipt_kind == "blocked" else "pending"})
        elif receipt_kind == "review" and len(calls) == 1:
            binding.record_worktree_result(binding.task_id, "PR ready", review=True,
                result_ref="https://github.com/ellmos-ai/bach/pull/123")
            assert binding.completed_task_ids == ()
        elif receipt_kind not in {"foreign", "review-text"}:
            binding.execute_task_manage({"action": "done", "task_id": binding.task_id})
        return "PR bestätigt; review" if receipt_kind == "review-text" else "verified task completion"
    monkeypatch.setattr(control.runtime, "process", process)
    monkeypatch.setattr(control.runtime, "consume_task_completion_receipts",
                        lambda ident: ((99,) if receipt_kind == "foreign" else (42,))
                        if len(calls) == 1 else (43,))

    def pause(ctrl, *, event_type):
        pauses.append(event_type)
        if receipt_kind in {"foreign", "review-text"}:
            assert ctrl.lease_supervisor is not None and ctrl.lease_supervisor.is_alive
        if receipt_kind == "blocked":
            return len(calls) < 2
        return len(pauses) < 2  # Stop this isolated probe after two task receipts.
    monkeypatch.setattr(control, "_wait_worker_cooldown", pause)

    class SynchronousThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            self.active = True
            try:
                control._WORKER_CONTROLS[wid].stop_event.wait = lambda timeout=None: False
                self.target()
            finally:
                self.active = False

        def is_alive(self):
            return getattr(self, "active", False)
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    responses = []
    monkeypatch.setattr(handler, "_json", lambda body, code=200: responses.append((body, code)))
    if entrypoint == "http":
        handler.do_POST()
    else:
        responses.append(control.start_worker_execution(wid))

    assert responses[-1][1] == 200
    if receipt_kind in {"blocked", "returned"}:
        assert get_worker_slot(wid, path=path)["task_id"] is None
        assert len(calls) == len(ends) == 1
        assert ends[0][1]["result"] == "task_returned"
        assert mem_db.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == (
            "blocked" if receipt_kind == "blocked" else "pending")
        if receipt_kind == "blocked":
            if entrypoint == "http":
                handler.do_POST()
            else:
                control.start_worker_execution(wid)
            assert len(calls) == 2 and starts[-1]["task_id"] == 43
        return
    if worker_type == "once" and receipt_kind == "review":
        assert len(calls) == len(starts) == len(ends) == 1
        assert pauses == []
        assert get_worker_slot(wid, path=path)["status"] == "idle"
        assert get_worker_slot(wid, path=path)["task_id"] is None
        assert ends[0][1]["status"] == "released" and ends[0][1]["result"] == "task_review"
        return
    if receipt_kind in {"foreign", "review-text"}:
        assert len(calls) == 2
        assert pauses == ["runs", "runs"]
        assert get_worker_slot(wid, path=path)["task_id"] == 42
        assert len(starts) == len(ends) == 1
        assert ends[0][1]["status"] == "released"
        return
    assert [assignment["task_id"] for assignment in starts] == [42, 43]
    assert starts[0]["agent_instance_id"] == starts[1]["agent_instance_id"]
    if receipt_kind == "next-assignment-denied":
        assert len(calls) == len(ends) == 1
        assert pauses == ["tasks"]
        assert get_worker_slot(wid, path=path)["status"] == "error"
        assert mem_db.execute("SELECT status FROM tasks WHERE id=43").fetchone()[0] == "pending"
        return
    assert get_worker_slot(wid, path=path)["task_id"] is None
    assert len(calls) == 2
    assert pauses == (["runs", "tasks"] if receipt_kind == "review" else ["tasks", "tasks"])
    assert len(ends) == 2
    if receipt_kind == "review":
        assert ends[0][1]["status"] == "released" and ends[0][1]["result"] == "task_review"
        assert ends[1][1]["status"] == "completed"
        assert mem_db.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == "review"
    else:
        assert all(details["status"] == "completed" for assignment, details in ends)


@pytest.mark.parametrize("state", ["no-task", "foreign-holder"])
def test_controller_does_not_infer_without_confirmed_task_lease(tmp_path, monkeypatch, mem_db, state):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    initialize_slots_config(path)
    worker = add_worker({"name": "Denied", "type": "once", "task_id": 42 if state == "foreign-holder" else None}, path=path)
    wid = worker["id"]
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    client = TaskLeaseClient(conn=mem_db)
    if state == "foreign-holder":
        mem_db.execute("INSERT INTO tasks (id, title, status) VALUES (42, 'Foreign', 'pending')")
        mem_db.commit()
        client.acquire(42, worker_id="foreign@HOST", host="HOST")
    monkeypatch.setattr(control, "_native_task_client", lambda: client, raising=False)
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: get_worker_slot(ident, path=path))
    monkeypatch.setattr(control, "update_slot", lambda ident, change: update_slot(ident, change, path=path))
    monkeypatch.setattr(control, "record_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *a, **kw: None)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (object(), "test-model"))
    async def forbidden(*a, **kw): pytest.fail("Inference without lease")
    monkeypatch.setattr(control.runtime, "process", forbidden)
    class SynchronousThread:
        def __init__(self, target, **kw): self.target = target
        def start(self):
            self.active = True
            try:
                self.target()
            finally:
                self.active = False

        def is_alive(self):
            return getattr(self, "active", False)
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    monkeypatch.setattr(handler, "_json", lambda *a, **kw: None)
    handler.do_POST()
    assert get_worker_slot(wid, path=path)["status"] == ("idle" if state == "no-task" else "error")


def test_native_factory_rejects_undeclared_authority_before_projection_path(monkeypatch):
    from hub import rheingold
    from hub._services.chat import bach_tools
    from hub._services.task_lease_client import LeaseError
    control = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.delenv("BACH_MODE", raising=False)
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "isolated", "lead_url": None})
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection path requested"))
    with pytest.raises(LeaseError): control._native_task_client()


def test_native_factory_rejects_authority_change_without_opening_projection(monkeypatch):
    from hub import rheingold
    from hub._services.chat import bach_tools
    from hub._services.task_lease_client import LeaseError
    control = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "worker", "lead_url": "http://lead.invalid"})
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: "unused-projection.db")
    monkeypatch.setattr(TaskLeaseClient, "_get_local_connection", lambda self: pytest.fail("projection opened"))
    with pytest.raises(LeaseError): control._native_task_client()


@pytest.mark.parametrize("case", ["actual-ack", "no-task"])
def test_assignment_completion_uses_authority_ack_not_stale_slot_projection(monkeypatch, mem_db, case):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    wid = "worker-stale-projection"
    worker = {"id": wid, "name": "Stale view", "type": "once", "sub_mode": "task_worker",
              "status": "running" if case == "actual-ack" else "completed",
              "task_id": 42 if case == "actual-ack" else None}
    if case == "actual-ack":
        mem_db.execute("INSERT INTO tasks (id, title, status) VALUES (42, 'Actual', 'pending')")
        mem_db.commit()
    session = ChatSession()
    session.chat_id = wid
    ends = []
    monkeypatch.setattr(lease_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(control, "_native_task_client", lambda: TaskLeaseClient(conn=mem_db))
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: worker)
    monkeypatch.setattr(control, "update_slot", lambda *a: worker)  # Deliberately stale projection.
    monkeypatch.setattr(control, "record_activity", lambda *a, **kw: None)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kw: ends.append(kw))
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (object(), "test-model"))
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: session)
    async def process(*a, **kw):
        assert case == "actual-ack"
        return session.worker_task_binding.execute_task_manage({"action": "done", "task_id": 42})
    monkeypatch.setattr(control.runtime, "process", process)
    class SynchronousThread:
        def __init__(self, target, **kw): self.target = target
        def start(self):
            self.active = True
            try:
                self.target()
            finally:
                self.active = False

        def is_alive(self):
            return getattr(self, "active", False)
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    monkeypatch.setattr(handler, "_json", lambda *a, **kw: None)
    handler.do_POST()
    assert len(ends) == 1
    assert ends[0]["status"] == ("completed" if case == "actual-ack" else "released")
    assert ends[0]["result"] == ("task_done" if case == "actual-ack" else "not_finished")
