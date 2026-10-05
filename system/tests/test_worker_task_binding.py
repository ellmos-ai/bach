# SPDX-License-Identifier: MIT
"""Task transitions of a continuous worker, without live TaskDB or inference."""
import importlib
import pytest

from hub._services.chat.chat_runtime import ChatSession
from hub._services.chat.slots_config import (
    add_worker, get_worker_slot, initialize_slots_config, update_slot,
)


@pytest.mark.parametrize("worker_type", ["continuous", "persistent"])
@pytest.mark.parametrize("receipt_kind", ["matched", "foreign", "next-assignment-denied"])
def test_continuous_worker_advances_task_binding_and_assignment(tmp_path, monkeypatch, worker_type, receipt_kind):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    initialize_slots_config(path)
    worker = add_worker({"name": "Transition", "type": worker_type, "task_id": 42,
                         "sub_mode": "task_worker", "pause_basis": "tasks"}, path=path)
    wid = worker["id"]
    session = ChatSession()
    session.chat_id = wid
    calls, starts, ends, pauses = [], [], [], []
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
        return "verified task completion"
    monkeypatch.setattr(control.runtime, "process", process)
    monkeypatch.setattr(control.runtime, "consume_task_completion_receipts",
                        lambda ident: ((99,) if receipt_kind == "foreign" else (42,))
                        if len(calls) == 1 else (43,))

    def pause(ctrl, *, event_type):
        pauses.append(event_type)
        return len(pauses) < 2  # Stop this isolated probe after two task receipts.
    monkeypatch.setattr(control, "_wait_worker_cooldown", pause)

    class SynchronousThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            control._WORKER_CONTROLS[wid].stop_event.wait = lambda timeout=None: False
            self.target()
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/run"
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": wid})
    responses = []
    monkeypatch.setattr(handler, "_json", lambda body, code=200: responses.append((body, code)))
    handler.do_POST()

    assert responses[-1][1] == 200
    if receipt_kind == "foreign":
        assert len(calls) == 2
        assert pauses == ["runs", "runs"]
        assert get_worker_slot(wid, path=path)["task_id"] == 42
        assert len(starts) == len(ends) == 1
        assert ends[0][1]["status"] == "released"
        return
    assert get_worker_slot(wid, path=path)["task_id"] is None
    assert [assignment["task_id"] for assignment in starts] == [42, 0]
    assert starts[0]["agent_instance_id"] == starts[1]["agent_instance_id"]
    if receipt_kind == "next-assignment-denied":
        assert len(calls) == len(ends) == 1
        assert pauses == ["tasks"]
        assert get_worker_slot(wid, path=path)["status"] == "error"
        return
    assert len(calls) == 2
    assert pauses == ["tasks", "tasks"]
    assert len(ends) == 2
    assert all(details["status"] == "completed" for assignment, details in ends)
