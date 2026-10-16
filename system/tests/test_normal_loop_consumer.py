"""Root acceptance of the real normal-loop consumer, isolated authority only."""
import asyncio
import json
import uuid

import pytest

from hub._services.chat import chat_runtime as runtime_module
from hub._services.chat.chat_runtime import ChatRuntime, ChatSession, FailedAnswer
from hub._services.task_lease_client import LeaseDeniedError, LeaseError
from system.tests.test_worker_tool_trace import binding  # noqa: F401


class Backend:
    name = "fixture-backend"
    _last_tool_call_ids = ["call-1"]

    def get_default_model(self):
        return "fixture-model"

    def tool_response_message(self, content, call_id):
        return {"role": "tool", "content": content, "tool_call_id": call_id}


def _events(binding):
    return binding._client.tool_trace_events(binding.task_id)["events"]



def _assert_blocked_and_foreign_claim_denied(binding):
    assert binding._client.read(binding.task_id).status == "blocked"
    snapshot = binding._client.task_snapshot(binding.task_id)
    with pytest.raises(LeaseDeniedError) as error:
        binding._client.acquire(
            binding.task_id,
            worker_id="foreign-worker@OTHER-HOST",
            host="OTHER-HOST",
            request_id=uuid.uuid4().hex,
            task_version=snapshot["task_version"],
            result_generation=uuid.uuid4().hex,
            intent="isolated consumer quarantine regression",
        )
    assert error.value.reason == "not_claimable"


def _consumer(monkeypatch, binding, *, action="detail", arguments=None, backend=None):
    backend = backend or Backend()
    runtime = ChatRuntime(backend)
    runtime.auto_continue = 0
    runtime.goal = ""
    runtime.hook_every = 1000
    session = ChatSession()
    session.model = "fixture-model"
    session.allow_tools = True
    session.allowed_tools = ["task_manage"]
    session.worker_task_binding = binding
    session.chat_id = ""
    messages = []
    calls = []
    payload = arguments or {"action": action, "task_id": binding.task_id}

    # This suite checks the consumer/receipt boundary. Capability policy and
    # provider classification have their own suites; no provider is invoked.
    monkeypatch.setattr(runtime, "_refresh_worker_tools", lambda _session: None)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_args: None)
    monkeypatch.setattr(runtime, "_context_voll", lambda *_args, **_kwargs: False)

    async def chat(_session, selected_backend, selected_model, msgs, **_kwargs):
        calls.append("model")
        if len(calls) == 1:
            value = {"content": "", "tool_calls": [
                {"function": {"name": "task_manage", "arguments": payload}}
            ], "raw_message": {"role": "assistant", "content": ""}}
        else:
            value = {"content": "isolated answer", "tool_calls": []}
        return value, selected_backend, selected_model

    monkeypatch.setattr(runtime, "_chat_with_configured_fallbacks", chat)

    def dispatch(name, args, *_args, **_kwargs):
        assert name == "task_manage"
        assert [event["phase"] for event in _events(binding)][-1] == "started"
        return binding.execute_task_manage(args)

    monkeypatch.setattr(runtime_module, "exec_tool", dispatch)
    return runtime, session, messages, calls


def _run(runtime, session, messages):
    return asyncio.run(runtime._tool_loop_impl(messages, session, [{"name": "task_manage"}]))


def test_actual_consumer_acks_only_after_response_append(binding, monkeypatch):
    runtime, session, messages, calls = _consumer(monkeypatch, binding)
    original = binding.trace_tool_phase
    observations = []

    def phase(identity, phase, **kwargs):
        if phase == "acknowledged":
            observations.append([dict(item) for item in messages])
            assert any(item.get("role") == "tool" for item in messages)
        return original(identity, phase, **kwargs)

    monkeypatch.setattr(binding, "trace_tool_phase", phase)
    answer = _run(runtime, session, messages)
    assert answer == "isolated answer"
    assert len(calls) == 2
    assert len(observations) == 1
    assert [event["phase"] for event in _events(binding)] == [
        "started", "returned", "acknowledged"
    ]
    assert binding.tool_dispatch_count == 1


def test_actual_terminal_review_release_is_consumed_and_acked(binding, monkeypatch):
    args = {"action": "done", "task_id": binding.task_id,
            "result": "isolated substantive result"}
    runtime, session, messages, calls = _consumer(monkeypatch, binding, arguments=args)
    original = binding.trace_tool_phase

    def phase(identity, phase, **kwargs):
        if phase == "acknowledged":
            assert binding.closed is True
            assert any(item.get("role") == "tool" for item in messages)
        return original(identity, phase, **kwargs)

    monkeypatch.setattr(binding, "trace_tool_phase", phase)
    answer = _run(runtime, session, messages)
    assert "Abschlussstatus wird nach Policy ermittelt" in answer
    assert len(calls) == 1
    assert binding.closed
    assert binding.completed_task_ids == ()
    assert binding._client.task_snapshot(binding.task_id)["status"] == "review"
    assert [event["phase"] for event in _events(binding)] == [
        "started", "returned", "acknowledged"
    ]


@pytest.mark.parametrize("fault", ["response", "append"])
def test_response_or_append_failure_never_acks_or_replays(binding, monkeypatch, fault):
    class ResponseFailure(Backend):
        def tool_response_message(self, *_args):
            raise RuntimeError("synthetic-private-provider-error")

    class AppendFailure(list):
        def append(self, value):
            if value.get("role") == "tool":
                raise RuntimeError("synthetic-private-append-error")
            return super().append(value)

    runtime, session, messages, calls = _consumer(
        monkeypatch, binding, backend=ResponseFailure() if fault == "response" else None
    )
    if fault == "append":
        messages = AppendFailure()
    with pytest.raises(RuntimeError, match="Werkzeugantwort konnte nicht konsumiert werden") as exc:
        _run(runtime, session, messages)
    assert "synthetic-private" not in str(exc.value)
    assert len(calls) == 1
    assert [event["phase"] for event in _events(binding)] == ["started", "returned"]
    _assert_blocked_and_foreign_claim_denied(binding)
    assert binding.tool_dispatch_count == 1
    with pytest.raises(LeaseError):
        binding.assert_active()


@pytest.mark.parametrize("phase_to_fail", ["started", "returned", "acknowledged"])
def test_sink_failure_stops_actual_consumer(binding, monkeypatch, phase_to_fail):
    runtime, session, messages, calls = _consumer(monkeypatch, binding)
    if phase_to_fail == "started":
        def fail_start(**_kwargs):
            raise RuntimeError("private trace sink")
        monkeypatch.setattr(binding, "trace_tool_started", fail_start)
    else:
        original = binding.trace_tool_phase

        def phase(identity, phase, **kwargs):
            if phase == phase_to_fail:
                raise RuntimeError("private trace sink")
            return original(identity, phase, **kwargs)

        monkeypatch.setattr(binding, "trace_tool_phase", phase)
    answer = _run(runtime, session, messages)
    assert isinstance(answer, FailedAnswer)
    assert "private trace sink" not in answer
    assert len(calls) == 1
    assert not any(event["phase"] == "acknowledged" for event in _events(binding))
    if phase_to_fail != "started":
        _assert_blocked_and_foreign_claim_denied(binding)
    with pytest.raises(LeaseError):
        binding.assert_active()


def test_task_version_mutation_consumes_original_started_identity(binding, monkeypatch):
    previous = binding.task_snapshot()["task_version"]
    args = {"action": "update", "task_id": binding.task_id,
            "description": "actual isolated update"}
    runtime, session, messages, calls = _consumer(monkeypatch, binding, arguments=args)
    answer = _run(runtime, session, messages)
    assert answer == "isolated answer"
    assert binding.task_snapshot()["task_version"] != previous
    events = _events(binding)
    assert [event["phase"] for event in events] == ["started", "returned", "acknowledged"]
    assert all(event["task_version"] == previous for event in events)


def test_effect_then_exception_does_not_repeat_in_actual_consumer(binding, monkeypatch):
    runtime, session, messages, calls = _consumer(monkeypatch, binding)
    effects = []

    def dispatch(*_args, **_kwargs):
        effects.append(True)
        raise RuntimeError("secret callback error after effect")

    monkeypatch.setattr(runtime_module, "exec_tool", dispatch)
    answer = _run(runtime, session, messages)
    assert isinstance(answer, FailedAnswer)
    assert len(effects) == len(calls) == 1
    assert [event["phase"] for event in _events(binding)] == ["started", "failed"]
    assert "secret callback" not in json.dumps(_events(binding))
    _assert_blocked_and_foreign_claim_denied(binding)
    with pytest.raises(LeaseError):
        binding.assert_active()


def test_unbound_chat_preserves_dispatch_without_trace(monkeypatch):
    backend = Backend()
    runtime = ChatRuntime(backend)
    runtime.auto_continue = 0
    runtime.goal = ""
    runtime.hook_every = 1000
    session = ChatSession()
    session.model = "fixture-model"
    session.allow_tools = True
    session.allowed_tools = ["task_manage"]
    messages = []
    models = []
    effects = []

    async def chat(_session, selected_backend, selected_model, msgs, **_kwargs):
        models.append(True)
        result = ({"tool_calls": [{"function": {"name": "task_manage", "arguments": {}}}]}
                  if len(models) == 1 else {"content": "compat answer"})
        return result, selected_backend, selected_model

    monkeypatch.setattr(runtime, "_chat_with_configured_fallbacks", chat)
    monkeypatch.setattr(runtime, "_refresh_worker_tools", lambda _session: None)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_args: None)
    monkeypatch.setattr(runtime, "_context_voll", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(runtime_module, "exec_tool", lambda *_args, **_kwargs:
                        effects.append(True) or "compat receipt")
    assert _run(runtime, session, messages) == "compat answer"
    assert len(effects) == 1
    assert any(item.get("role") == "tool" and item["content"] == "compat receipt"
               for item in messages)


@pytest.mark.parametrize("fault", ["response", "append"])
def test_terminal_unconsumed_response_preserves_review(binding, monkeypatch, fault):
    class ResponseFailure(Backend):
        def tool_response_message(self, *_args):
            raise RuntimeError("synthetic terminal response error")

    class AppendFailure(list):
        def append(self, value):
            if value.get("role") == "tool":
                raise RuntimeError("synthetic terminal append error")
            return super().append(value)

    runtime, session, messages, calls = _consumer(
        monkeypatch, binding,
        arguments={"action": "done", "task_id": binding.task_id,
                   "result": "isolated substantive result"},
        backend=ResponseFailure() if fault == "response" else None,
    )
    if fault == "append":
        messages = AppendFailure()
    with pytest.raises(RuntimeError, match="Werkzeugantwort konnte nicht konsumiert werden"):
        _run(runtime, session, messages)
    assert len(calls) == 1
    assert binding.closed
    assert binding._client.read(binding.task_id).status == "review"
    assert [event["phase"] for event in _events(binding)] == ["started", "returned"]
