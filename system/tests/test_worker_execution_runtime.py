# SPDX-License-Identifier: MIT
"""Runtime integration for private, call-bound worker execution evidence.

All model transports below are deterministic in-process fakes. The CLI cases
exercise the real private bridge over loopback and a real temporary lease.
"""
import asyncio
import json
import threading
import urllib.request
import uuid

import pytest

from hub._services.chat import local_resource_reserve, model_sockets
from hub._services.chat.chat_runtime import ChatRuntime, ComputeLocked, FailedAnswer
from hub._services.llm.model_backend import CLIBackend, OllamaBackend, OpenAIBackend, OpenRouterBackend
from hub._services.task_lease_client import TaskLeaseClient


CHAT_ID = "runtime-evidence-slot"


class FakeOpenAIBackend(OpenAIBackend):
    def __init__(self, model="gpt-4o", response=None, error=None):
        super().__init__(base_url="https://api.openai.com/v1", default_model=model)
        self.response = response
        self.error = error
        self.calls = []

    async def chat(self, messages, tools=None, think=True, model=None):
        self.calls.append((messages, tools, model))
        if self.error is not None:
            raise self.error
        return self.response


class FakeOpenRouterBackend(OpenRouterBackend):
    def __init__(self, model, response):
        # A synthetic key prevents configuration reads; chat is replaced and
        # never opens a provider connection.
        super().__init__(api_key="fixture-only", default_model=model)
        self.response = response
        self.calls = []

    async def chat(self, messages, tools=None, think=True, model=None):
        self.calls.append((messages, tools, model))
        return self.response


def _submit_response(binding, result="Isoliertes Ergebnis für Review"):
    arguments = {"action": "submit_result", "task_id": binding.task_id, "result": result}
    tool_calls = [{"function": {"name": "task_manage", "arguments": arguments}}]
    return {
        "content": "",
        "tool_calls": tool_calls,
        "raw_message": {"role": "assistant", "content": "", "tool_calls": tool_calls},
    }


@pytest.fixture
def task_state(tmp_path, monkeypatch):
    from system.tests.test_task_lease_service import _create_db, _connect, _insert
    from hub._services import task_lease_client
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    database = tmp_path / "canonical.db"
    _create_db(database)
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    client = TaskLeaseClient(db_path=database)
    state = {"database": database, "client": client, "bindings": [], "current": {"value": True}}

    def add_task(title):
        conn = _connect(database)
        try:
            return _insert(conn, title=title, status="pending", assigned_to="BACH")
        finally:
            conn.close()

    def make_binding(*, generation=None, current=None, title="Execution evidence task"):
        task_id = add_task(title)
        current = current if current is not None else {"value": True}
        binding = WorkerLeaseBinding.acquire(
            client, task_id, worker_id="isolated-runtime-worker@HOST", host="HOST",
            generation=generation or f"generation-{len(state['bindings']) + 1}",
            is_current=lambda: current["value"], stop_event=threading.Event(),
        )
        state["bindings"].append(binding)
        return binding, current

    state["make_binding"] = make_binding
    state["binding"], state["current"] = make_binding(generation="generation-1")

    # Keep these tests away from the host's chat context and persisted slots.
    from hub._services.chat import slots_config
    monkeypatch.setattr(slots_config, "update_slot", lambda *_args, **_kwargs: None)

    yield state
    for binding in reversed(state["bindings"]):
        if binding._active:
            binding.return_lease()


def _runtime(backend, monkeypatch, *, chat_id=CHAT_ID):
    runtime = ChatRuntime(backend)
    runtime.max_tool_rounds = 3
    runtime.hook_every = 999
    runtime._get_bach_context = lambda _text: ""
    runtime._get_memory_hook_context = lambda *_args: ""
    runtime.get_session(chat_id)
    return runtime


def _result_snapshot(binding):
    return binding._client.task_result_snapshot(binding.task_id)["result"]


def _assert_available_execution(binding, *, backend_id, model):
    result = _result_snapshot(binding)
    assert result is not None and result["accepted"] is False
    evidence = result["execution"]
    assert evidence["schema"] == "bach.worker-execution-evidence.v1"
    assert evidence["availability"] == "available"
    assert evidence["backend_id"] == backend_id
    assert evidence["requested_model"] == model
    assert evidence["generation"] == binding.generation
    assert evidence["fence"] == binding._ack.fence
    assert evidence["request_sha256"] and len(evidence["request_sha256"]) == 64
    assert result["accepted"] is False
    return evidence


def test_cloud_response_links_actual_call_to_submitted_result(task_state, monkeypatch):
    binding = task_state["binding"]
    backend = FakeOpenAIBackend(response=_submit_response(binding))
    runtime = _runtime(backend, monkeypatch)
    session = runtime.get_session(CHAT_ID)
    session.worker_task_binding = binding
    session.require_task_binding = True

    answer = asyncio.run(runtime.process("Führe die isolierte Aufgabe aus", CHAT_ID))

    assert "wartet in Review" in str(answer)
    assert len(backend.calls) == 1
    messages = json.dumps(backend.calls[0][0], ensure_ascii=False)
    assert binding._ack.lease_id not in messages
    evidence = _assert_available_execution(binding, backend_id="openai", model="gpt-4o")
    assert evidence["slot_id"] == CHAT_ID
    result = _result_snapshot(binding)
    assert result["execution"]["execution_id"] == evidence["execution_id"]
    assert result["accepted"] is False and result["submission"]["availability"] == "available"


def test_permitted_fallback_links_only_fallback_after_primary_preanswer_failure(
    task_state, monkeypatch,
):
    binding = task_state["binding"]
    primary = FakeOpenAIBackend(model="primary-model", error=__import__("httpx").ConnectError("offline"))
    fallback = FakeOpenRouterBackend("fallback-model", _submit_response(binding))
    monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda target: fallback)
    runtime = _runtime(primary, monkeypatch)
    session = runtime.get_session(CHAT_ID)
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.worker_slot_reader = lambda: {
        "id": CHAT_ID, "enabled": True, "backend": "openai", "model": "primary-model",
        "model_fallbacks": [{"backend": "openrouter", "model": "fallback-model"}],
    }

    answer = asyncio.run(runtime.process("Erlaube den belegten Fallback", CHAT_ID))

    assert "wartet in Review" in str(answer)
    assert len(primary.calls) == 1 and len(fallback.calls) == 1
    evidence = _assert_available_execution(binding, backend_id="openrouter", model="fallback-model")
    assert evidence["backend_id"] != "openai"


def test_invalid_fallback_is_rejected_before_any_model_call(task_state, monkeypatch):
    binding = task_state["binding"]
    backend = FakeOpenAIBackend(model="primary-model", response=_submit_response(binding))
    runtime = _runtime(backend, monkeypatch)
    session = runtime.get_session(CHAT_ID)
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.worker_slot_reader = lambda: {
        "id": CHAT_ID, "enabled": True, "backend": "openai", "model": "primary-model",
        "model_fallbacks": [{"backend": "unknown-provider", "model": "forbidden-model"}],
    }

    answer = asyncio.run(runtime.process("Ungültiger Fallback", CHAT_ID))

    assert isinstance(answer, FailedAnswer)
    assert backend.calls == []
    assert _result_snapshot(binding) is None


def _relay_post(environment, path, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        environment["BACH_WORKER_TOOL_URL"] + path,
        data=data,
        headers={
            "Authorization": "Bearer " + environment["BACH_WORKER_TOOL_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def _cli_submit(environment, binding):
    request_id = uuid.uuid4().hex
    result = _relay_post(environment, "/call", {
        "request_id": request_id, "previous_receipt": None, "name": "task_manage",
        "arguments": {"action": "submit_result", "task_id": binding.task_id,
                      "result": "CLI-Ergebnis wartet auf echte Rückkehr"},
    })
    assert result["is_error"] is False
    ack = _relay_post(environment, "/ack", {
        "request_id": result["request_id"], "receipt_id": result["receipt_id"],
    })
    assert ack["acknowledged"] is True


async def _wait_for_cli_entry(call, entered):
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    except asyncio.TimeoutError:
        if call.done():
            try:
                early_answer = call.result()
            except BaseException as exc:
                pytest.fail(f"CLI runtime ended before bridge submit: {type(exc).__name__}: {exc}")
            pytest.fail(f"CLI runtime ended before bridge submit: {early_answer!r}")
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        pytest.fail("CLI runtime stayed pending without reaching the bridge submit")


def _cli_runtime(task_state, monkeypatch, *, chat_id=CHAT_ID):
    binding = task_state["binding"]
    backend = CLIBackend(cli_name="claude", cli_path="isolated-fake-cli", default_model="sonnet")
    runtime = _runtime(backend, monkeypatch, chat_id=chat_id)
    session = runtime.get_session(chat_id)
    session.worker_task_binding = binding
    session.require_task_binding = True
    return runtime, session, backend


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_cli_execution_is_linked_only_after_physical_return_and_not_after_failure(
    task_state, monkeypatch, outcome,
):
    binding = task_state["binding"]
    runtime, _session, backend = _cli_runtime(task_state, monkeypatch)
    entered = asyncio.Event()
    release = asyncio.Event()
    during = {}

    async def fake_run_cli(prompt, *, model=None, worker_environment=None, worker_guard=None):
        worker_guard()
        assert worker_environment["BACH_WORKER_TOOL_TOKEN"] not in prompt
        assert binding._ack.lease_id not in prompt
        _cli_submit(worker_environment, binding)
        during["result"] = _result_snapshot(binding)
        entered.set()
        if outcome == "cancel":
            raise asyncio.CancelledError()
        if outcome == "error":
            raise RuntimeError("synthetic CLI failure")
        await release.wait()
        return "synthetic CLI answer"

    backend._run_cli = fake_run_cli

    async def run_case():
        call = asyncio.create_task(runtime.process("CLI executes a bound task", CHAT_ID))
        await _wait_for_cli_entry(call, entered)
        assert during["result"]["execution"]["availability"] == "unavailable"
        if outcome == "success":
            release.set()
            await call
        elif outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await call
        else:
            await call

    asyncio.run(run_case())
    final = _result_snapshot(binding)
    if outcome == "success":
        assert final["execution"]["availability"] == "available"
        assert final["execution"]["backend_id"] == "claude"
        assert final["execution"]["requested_model"] == "sonnet"
    else:
        assert final["execution"]["availability"] == "unavailable"
        assert final["execution"]["reason"] in {
            "execution_not_recorded", "execution_evidence_invalid", "submission_not_current",
        }


@pytest.mark.parametrize("change", ["binding_swap", "generation_stale", "stop"])
def test_cli_return_cannot_link_after_binding_generation_or_stop_changes(
    task_state, monkeypatch, change,
):
    binding = task_state["binding"]
    runtime, session, backend = _cli_runtime(task_state, monkeypatch)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_cli(prompt, *, model=None, worker_environment=None, worker_guard=None):
        worker_guard()
        _cli_submit(worker_environment, binding)
        entered.set()
        await release.wait()
        return "answer after authority changed"

    backend._run_cli = fake_run_cli

    async def run_case():
        call = asyncio.create_task(runtime.process("Wait for the CLI return", CHAT_ID))
        await _wait_for_cli_entry(call, entered)
        if change == "binding_swap":
            replacement, _ = task_state["make_binding"](title="Replacement task")
            session.worker_task_binding = replacement
        elif change == "generation_stale":
            task_state["current"]["value"] = False
        else:
            binding._stop_event.set()
        release.set()
        await call

    asyncio.run(run_case())
    evidence = _result_snapshot(binding)["execution"]
    assert evidence["availability"] == "unavailable"
    assert evidence["reason"] in {
        "execution_not_recorded", "execution_evidence_invalid", "submission_not_current",
    }


def test_local_compute_authorization_gate_still_blocks_before_dispatch(task_state, monkeypatch):
    binding = task_state["binding"]
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model="isolated-local-model")
    calls = []

    async def fake_chat(*_args, **_kwargs):
        calls.append("model-dispatched")
        return {"content": "must not be reached"}

    backend.chat = fake_chat
    runtime = _runtime(backend, monkeypatch)
    session = runtime.get_session(CHAT_ID)
    session.worker_task_binding = binding
    session.require_task_binding = True
    runtime.compute_gate = lambda selected: selected is backend
    runtime._model_binding_for_session = lambda *_args: None
    probes = []

    async def permitted_local_reserve(_backend, model):
        probes.append(model)
        return {
            "schema": local_resource_reserve.SCHEMA, "state": "ready", "admitted": True,
            "enforced": True, "retryable": False, "policy_version": "isolated-policy-v1",
        }

    monkeypatch.setattr(local_resource_reserve, "probe", permitted_local_reserve)
    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: ({}, "isolated-policy-v1"))

    with pytest.raises(ComputeLocked):
        asyncio.run(runtime.process("Local compute remains locked", CHAT_ID))

    assert probes == ["isolated-local-model"]
    assert calls == []
    assert _result_snapshot(binding) is None


def test_unbound_chat_keeps_ordinary_response_and_legacy_binding_never_fakes_evidence(
    task_state, monkeypatch,
):
    binding = task_state["binding"]

    ordinary = FakeOpenAIBackend(response={"content": "Ordinary unbound answer"})
    unbound_runtime = _runtime(ordinary, monkeypatch, chat_id="unbound-runtime-chat")
    assert asyncio.run(unbound_runtime.process("ordinary", "unbound-runtime-chat")) == "Ordinary unbound answer"
    assert len(ordinary.calls) == 1

    class LegacyBinding:
        def __getattr__(self, name):
            if name in {"begin_model_execution", "finish_model_execution", "_discard_model_execution_candidate"}:
                raise AttributeError(name)
            return getattr(binding, name)

    legacy = FakeOpenAIBackend(response={"content": "Legacy-compatible answer"})
    legacy_runtime = _runtime(legacy, monkeypatch, chat_id="legacy-runtime-chat")
    session = legacy_runtime.get_session("legacy-runtime-chat")
    session.worker_task_binding = LegacyBinding()
    session.require_task_binding = True

    assert asyncio.run(legacy_runtime.process("legacy", "legacy-runtime-chat")) == "Legacy-compatible answer"
    assert len(legacy.calls) == 1
    assert _result_snapshot(binding) is None
