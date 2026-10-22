"""Direct Running requests use the current private task binding and actual ACK."""
import asyncio

import pytest
from hub._services.chat.worker_task_actions import WorkerTaskActions
from hub._services.task_lease_client import LeaseProtocolError

from system.tests.test_worker_lease_binding import (
    mem_db as lease_mem_db,  # noqa: PLC0414 - explicit pytest fixture export
)


@pytest.fixture
def mem_db(lease_mem_db):
    """Provide the native policy store on this isolated authority."""
    lease_mem_db.execute(
        "CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT, type TEXT)"
    )
    lease_mem_db.commit()
    return lease_mem_db


@pytest.fixture
def binding(mem_db):
    """Pin the selection contract for the actual Runtime boundary."""
    import threading

    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.task_lease_client import TaskLeaseClient
    from system.tests.test_task_lease_client import _insert_task
    from system.tests.test_task_lease_client_review import T0

    mem_db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    mem_db.commit()
    instance = WorkerLeaseBinding.acquire(
        TaskLeaseClient(conn=mem_db), _insert_task(mem_db),
        worker_id="physical-worker@HOST", host="HOST",
        generation="generation-1", is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0,
        slot={"id": "worker-bound", "model": "isolated-model"},
    )
    yield instance
    if instance._active:
        instance.return_lease()


@pytest.fixture
def runtime_binding(mem_db):
    """Real Runtime/Trace uses the authority clock, unlike frozen lease unit tests."""
    import threading

    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.task_lease_client import TaskLeaseClient

    from system.tests.test_task_lease_client import _insert_task

    mem_db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    mem_db.commit()
    task_id = _insert_task(mem_db)
    instance = WorkerLeaseBinding.acquire(
        TaskLeaseClient(conn=mem_db), task_id,
        worker_id="physical-worker@HOST", host="HOST",
        generation="generation-1", is_current=lambda: True,
        stop_event=threading.Event(),
        slot={"id": "worker-bound", "model": "isolated-model"},
    )
    yield instance
    if instance._active:
        instance.return_lease()


def test_expired_authority_lease_blocks_trace_without_task_or_tool_effect(
    runtime_binding, monkeypatch,
):
    import uuid
    from datetime import datetime, timedelta, timezone

    from hub._services import task_lease
    from hub._services.chat.worker_tool_trace import digest_json

    instance = runtime_binding
    before = instance._client.task_snapshot(instance.task_id)
    expiry = datetime.fromisoformat(instance._ack.expires_at.replace("Z", "+00:00"))
    assert expiry.tzinfo is not None
    expired_now = expiry + timedelta(seconds=1)
    assert expired_now > datetime.now(timezone.utc)
    # The local caller can still be live while the canonical trace authority
    # observes expiry. Dispatch must require both proofs, never caller time alone.
    instance.assert_active()
    assert not instance._client.read(instance.task_id, now=expired_now).leased
    monkeypatch.setattr(task_lease, "_utcnow", lambda: expired_now)
    arguments = {"action": "update", "task_id": instance.task_id, "title": "Must not change"}
    with pytest.raises(LeaseProtocolError, match="Trace-Start"):
        instance.trace_tool_started(
            source="normal-loop", request_id=uuid.uuid4().hex,
            tool_name="task_manage", arguments_sha256=digest_json(arguments),
        )
    assert instance._client.tool_trace_events(instance.task_id)["events"] == []
    assert instance._client.task_snapshot(instance.task_id) == before
    assert instance.tool_dispatch_count == 0
    assert not instance.completed_task_ids and not instance.reviewed_task_ids


def _runtime_tool_reply(tool_calls, *, serialized):
    """Keep Wire-format history separate from normalized Runtime dispatch data."""
    import json

    raw_calls = [
        {"function": {
            **call["function"],
            "arguments": json.dumps(call["function"]["arguments"])
            if serialized else call["function"]["arguments"],
        }}
        for call in tool_calls
    ]
    return {
        "content": "", "tool_calls": tool_calls,
        "raw_message": {"role": "assistant", "content": "", "tool_calls": raw_calls},
    }


def test_openai_adapter_normalizes_wire_arguments_before_runtime(monkeypatch):
    import json
    from unittest.mock import AsyncMock, MagicMock

    import httpx
    from hub._services.llm.model_backend import OpenAIBackend

    arguments = {"action": "decompose", "task_id": 1, "subtasks": [{"title": "Teilauftrag"}]}
    wire_call = {
        "id": "fixture-call", "type": "function",
        "function": {"name": "task_manage", "arguments": json.dumps(arguments)},
    }
    message = {"role": "assistant", "content": "", "tool_calls": [wire_call]}
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": message}], "model": "isolated-model"}
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda: client)

    result = asyncio.run(OpenAIBackend(
        base_url="http://fixture.invalid/api", api_key="test-fixture",
        default_model="isolated-model",
    ).chat([{"role": "user", "content": "Auftrag"}]))
    assert result["tool_calls"][0]["function"]["arguments"] == arguments
    assert isinstance(result["tool_calls"][0]["function"]["arguments"], dict)
    assert result["raw_message"]["tool_calls"][0]["function"]["arguments"] == json.dumps(arguments)
    client.post.assert_awaited_once()



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
    args = {"action": "decompose", "task_id": binding.task_id,
            "subtasks": [{"title": "Prüfen"}], "close_parent": close}
    if close:
        with pytest.raises(LeaseProtocolError):
            binding.execute_task_manage(args)
        assert not binding.closed and binding.decomposition_receipt is None
        assert binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"
        assert actions.confirm(binding) is False
        actions.end_block()
        assert actions.snapshot()["state"] == "error"
        return
    binding.execute_task_manage(args)
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
    assert binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"
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
def test_real_runtime_boundary_and_tool_ack(runtime_binding, monkeypatch, tool_action, serialized, handoff):
    binding = runtime_binding
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
            if tool_action == "decompose" and len(calls) == 2:
                description = binding.task_snapshot()["description"] + "\n[Stand: Teilaufgaben angelegt; Umsetzung offen.]"
                tools = [{"function": {"name": "task_manage", "arguments": {
                    "action": "update", "task_id": binding.task_id, "description": description}}},
                    {"function": {"name": "task_manage", "arguments": {
                    "action": "update", "task_id": binding.task_id, "status": "pending"}}}]
                return _runtime_tool_reply(tools, serialized=serialized)
            args = {"action": "decompose" if tool_action == "update-then-decompose" else tool_action,
                    "task_id": binding.task_id}
            if tool_action == "done":
                args["result"] = "Konkretes Ergebnis statt angeforderter Zerlegung"
                args["complete"] = True  # #425: bound submissions state completion explicitly
            if tool_action in {"decompose", "update-then-decompose"}:
                args["subtasks"] = [{"title": "Teilauftrag"}]
            tools = [{"function": {"name": "task_manage", "arguments": args}}]
            if tool_action == "update-then-decompose":
                update = {"action": "update", "task_id": binding.task_id, "title": "Inhalt geändert"}
                tools.insert(0, {"function": {"name": "task_manage",
                                             "arguments": update}})
            return _runtime_tool_reply(tools, serialized=serialized)
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
    assert len(calls) == (2 if tool_action == "decompose" else 1)
    assert actions.snapshot()["state"] == ("confirmed" if tool_action == "decompose" else "error")
    if tool_action == "done":
        assert not binding.completed_task_ids and binding.reviewed_task_ids == (binding.task_id,)
    elif tool_action == "decompose":
        assert not binding.completed_task_ids and not binding.reviewed_task_ids
        current = binding._client.task_snapshot(binding.task_id)
        assert current["status"] == "pending"
        assert "Teilaufgaben angelegt; Umsetzung offen" in current["description"]
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
