"""Direct Running requests use the current private task binding and actual ACK."""
import asyncio

import pytest

from system.tests.test_worker_lease_binding import binding, mem_db
from hub._services.chat.worker_task_actions import WorkerTaskActions


def requested(binding):
    actions = WorkerTaskActions("worker-bound", "generation-1")
    receipt = actions.request("generation-1", binding.task_id,
                              binding.task_snapshot()["task_version"], binding)
    return actions, receipt


def test_request_rejects_foreign_generation_task_or_version(binding):
    actions = WorkerTaskActions("worker-bound", "generation-1")
    version = binding.task_snapshot()["task_version"]
    for generation, task_id, content in [("old", binding.task_id, version),
                                          ("generation-1", binding.task_id + 1, version),
                                          ("generation-1", binding.task_id, "0" * 64)]:
        with pytest.raises(ValueError):
            actions.request(generation, task_id, content, binding)
    assert actions.snapshot() is None


def test_request_consumed_once_and_no_text_completion(binding):
    actions, receipt = requested(binding)
    with pytest.raises(ValueError):
        actions.request("generation-1", binding.task_id, receipt["task_version"], binding)
    assert actions.consume(binding, backend="isolated", model="test-model")
    assert actions.consume(binding, backend="isolated", model="test-model") is None
    assert actions.confirm(binding) is False
    actions.end_block()
    assert actions.snapshot()["state"] == "error"
    assert actions.snapshot()["confirmed_at"] is None


@pytest.mark.parametrize("close", [True, False])
def test_actual_decompose_ack_confirms_created_ids_without_capabilities(binding, close):
    actions, receipt = requested(binding)
    actions.consume(binding, backend="isolated", model="test-model")
    binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
                                 "subtasks": [{"title": "Prüfen"}], "close_parent": close})
    assert actions.confirm(binding)
    observed = actions.snapshot()
    assert observed["state"] == "confirmed"
    assert observed["created_ids"] == list(binding.decomposition_receipt["created_ids"])
    assert observed["parent_closed"] is close
    assert observed["request_id"] == receipt["request_id"]
    assert binding._ack.lease_id not in str(observed)
    assert observed["model"] == "test-model"


@pytest.mark.parametrize("change", ["version", "stop", "cancel"])
def test_change_before_boundary_prevents_requested_action(binding, change):
    actions, _ = requested(binding)
    if change == "version":
        binding.execute_task_manage({"action": "update", "task_id": binding.task_id, "title": "Neu"})
    elif change == "stop":
        binding._stop_event.set()
    else:
        actions.cancel()
    with pytest.raises(ValueError):
        actions.consume(binding, backend="isolated", model="test-model")
    assert actions.snapshot()["state"] in {"error", "cancelled"}


def test_add_ack_cannot_confirm_requested_decomposition(binding):
    actions, _ = requested(binding)
    actions.consume(binding, backend="isolated", model="test-model")
    binding.execute_task_manage({"action": "add", "title": "Anderer Auftrag"})
    assert actions.confirm(binding) is False


def test_replaced_private_binding_cannot_consume_request(binding):
    import copy
    actions, _ = requested(binding)
    replacement = copy.copy(binding)
    with pytest.raises(ValueError):
        actions.consume(replacement, backend="isolated", model="test-model")
    assert actions.snapshot()["state"] == "error"


def test_committed_decomposition_with_lost_ack_never_confirms(binding, monkeypatch):
    from hub._services.task_lease_client import LeaseConnectionError
    actions, _ = requested(binding)
    actions.consume(binding, backend="isolated", model="test-model")
    real_decompose = binding._client.decompose
    def lost_ack(*args, **kwargs):
        real_decompose(*args, **kwargs)
        raise LeaseConnectionError("ACK fehlt")
    monkeypatch.setattr(binding._client, "decompose", lost_ack)
    with pytest.raises(LeaseConnectionError):
        binding.execute_task_manage({"action": "decompose", "task_id": binding.task_id,
                                     "subtasks": [{"title": "Teilauftrag"}]})
    assert binding._client.task_snapshot(binding.task_id)["status"] == "done"
    assert actions.confirm(binding) is False
    assert binding.return_lease() is False
    actions.end_block()
    assert actions.snapshot()["state"] == "error"


@pytest.mark.parametrize("already_running", [False, True])
def test_requested_action_without_tools_refuses_inference(binding, already_running):
    from unittest.mock import AsyncMock
    from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer
    backend = type("Backend", (), {"get_default_model": lambda self: "isolated-model",
                                   "chat": AsyncMock(return_value={"content": "FERTIG"})})()
    actions, _ = requested(binding)
    if already_running: actions.consume(binding, backend="isolated", model="isolated-model")
    runtime = ChatRuntime(backend)
    runtime.max_tool_rounds = 0
    runtime.auto_continue = 0
    session = runtime.get_session("worker-bound")
    session.worker_task_binding = binding
    session.worker_task_actions = actions
    session.require_task_binding = True
    answer = asyncio.run(runtime.process("Auftrag", "worker-bound", work_priority="background"))
    assert isinstance(answer, FailedAnswer)
    backend.chat.assert_not_awaited()
    assert actions.snapshot()["state"] == "error"


@pytest.mark.parametrize("tool_action", ["decompose", "done", "text", "update-then-decompose"])
@pytest.mark.parametrize("serialized", [False, True])
@pytest.mark.parametrize("handoff", [False, True])
def test_real_runtime_boundary_and_tool_ack(binding, monkeypatch, tool_action, serialized, handoff):
    import json
    from hub._services.chat import bach_tools
    from hub._services.chat.chat_runtime import ChatRuntime
    calls = []
    class Backend:
        name = "isolated"
        def get_default_model(self): return "isolated-model"
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            assert any("ZERLEGUNG ANGEFORDERT" in m["content"] for m in messages)
            assert binding._ack.lease_id not in str(messages)
            if tool_action == "text":
                return {"content": "FERTIG"}
            args = {"action": "decompose" if tool_action == "update-then-decompose" else tool_action,
                    "task_id": binding.task_id}
            if tool_action in {"decompose", "update-then-decompose"}:
                args["subtasks"] = [{"title": "Teilauftrag"}]
            tools = [{"function": {"name": "task_manage", "arguments": json.dumps(args) if serialized else args}}]
            if tool_action == "update-then-decompose":
                update = {"action": "update", "task_id": binding.task_id, "title": "Inhalt geändert"}
                tools.insert(0, {"function": {"name": "task_manage",
                                             "arguments": json.dumps(update) if serialized else update}})
            return {"content": "", "tool_calls": tools,
                    "raw_message": {"role": "assistant", "content": "", "tool_calls": tools}}
        def tool_response_message(self, content, tool_call_id=""):
            return {"role": "tool", "content": content}
    runtime = ChatRuntime(Backend())
    runtime.auto_continue = 0
    runtime.hook_every = 999
    actions, _ = requested(binding)
    session = runtime.get_session("worker-bound")
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.worker_task_actions = actions
    if handoff:
        from unittest.mock import AsyncMock
        from hub._services.chat.worker_handoff import WorkerHandoff
        session.worker_handoff = WorkerHandoff("worker-bound", "generation-1")
        session.worker_handoff.request("generation-1")
        runtime._handoff = AsyncMock(return_value=[{"role": "user", "content": "Zusammenfassung ohne Aktionsauftrag"}])
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: pytest.fail("projection accessed"))
    asyncio.run(runtime.process("Auftrag", "worker-bound", work_priority="background"))
    assert len(calls) == 1
    assert actions.snapshot()["state"] == ("confirmed" if tool_action == "decompose" else "error")
    if tool_action == "done":
        assert binding.completed_task_ids == (binding.task_id,)
    elif tool_action == "text":
        assert not binding.closed
    if tool_action == "update-then-decompose":
        assert binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"
        assert binding.task_snapshot()["title"] == "Inhalt geändert"
        assert binding.decomposition_receipt is None


@pytest.mark.parametrize("condition", ["current", "stale", "stopped", "no-tools", "unbound"])
def test_controller_request_and_private_binding_projection(binding, monkeypatch, condition):
    from hub._services.chat import telegram_chat as controller
    control = controller._WorkerControl("worker-bound")
    control.supports_step_actions = True
    control.thread = type("Thread", (), {"is_alive": lambda self: True})()
    binding._generation = control.generation
    control.task_binding = None if condition == "unbound" else binding
    slot = {"id": "worker-bound", "status": "running", "allow_tools": condition != "no-tools",
            "max_tool_rounds": 12}
    if condition == "stopped": control.stop_event.set()
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {"worker-bound": control})
    monkeypatch.setattr(controller, "get_worker_slot", lambda worker_id: slot)
    generation = "old" if condition == "stale" else control.generation
    args = ("worker-bound", generation, binding.task_id, binding.task_snapshot()["task_version"])
    if condition != "current":
        with pytest.raises(ValueError): controller._request_worker_decomposition(*args)
        assert control.task_actions.snapshot() is None
    else:
        receipt = controller._request_worker_decomposition(*args)
        projected = controller._worker_handoff_snapshot(slot)
        assert projected["task_action_receipt"] == receipt
        assert projected["task_action_binding"] == {"task_id": binding.task_id,
                                                       "task_version": binding.task_snapshot()["task_version"]}
        assert binding._ack.lease_id not in str(projected)


@pytest.mark.parametrize("invalid", [None, "version", "bool", "extra", "auth"])
def test_control_decomposition_route_validates_before_queueing(monkeypatch, invalid):
    from hub._services.chat import telegram_chat as controller
    handler = controller.ControlHandler.__new__(controller.ControlHandler)
    handler.path = "/api/workers/decompose"
    handler.headers = {"X-Delegation-Depth": "0"}
    body = {"id": "worker-1", "generation": "a" * 32, "task_id": 42, "task_version": "b" * 64}
    if invalid == "version": body["task_version"] = "old"
    elif invalid == "bool": body["task_id"] = True
    elif invalid == "extra": body["subtasks"] = [{"title": "Ungeprüft"}]
    replies, calls = [], []
    monkeypatch.setattr(handler, "_allow_json_post", lambda: invalid != "auth")
    monkeypatch.setattr(handler, "_read_body", lambda: body)
    monkeypatch.setattr(handler, "_json", lambda data, code=200: replies.append((data, code)))
    monkeypatch.setattr(controller, "_request_worker_decomposition",
                        lambda *args: calls.append(args) or {"state": "pending"})
    handler.do_POST()
    if invalid is None:
        assert replies[0][1] == 202
        assert calls == [("worker-1", "a" * 32, 42, "b" * 64)]
    elif invalid == "auth":
        assert not calls and not replies
    else:
        assert replies[0][1] == 400 and not calls
