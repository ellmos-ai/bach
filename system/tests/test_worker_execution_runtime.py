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
    arguments = {"action": "submit_result", "task_id": binding.task_id, "result": result, "complete": True}
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

    def make_binding(*, generation=None, current=None, title="Execution evidence task",
                     stop_event=None):
        task_id = add_task(title)
        current = current if current is not None else {"value": True}
        binding = WorkerLeaseBinding.acquire(
            client, task_id, worker_id="isolated-runtime-worker@HOST", host="HOST",
            generation=generation or f"generation-{len(state['bindings']) + 1}",
            is_current=lambda: current["value"],
            stop_event=stop_event if stop_event is not None else threading.Event(),
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


def _execution_rows(task_state, task_id):
    from system.tests.test_task_lease_service import _connect

    conn = _connect(task_state["database"])
    try:
        return conn.execute(
            "SELECT phase, result_id FROM worker_model_executions "
            "WHERE task_id=? ORDER BY started_event_id",
            (task_id,),
        ).fetchall()
    finally:
        conn.close()


def _assert_available_execution(binding, *, backend_id, model):
    result = _result_snapshot(binding)
    assert result is not None and result["accepted"] is False
    evidence = result["execution"]
    assert evidence["schema"] == "bach.worker-execution-evidence.v2"
    assert evidence["availability"] == "available"
    assert evidence["backend_id"] == backend_id
    assert evidence["requested_model"] == model
    # These fake/CLI transports report no provider model metadata. An actual
    # execution must stay usable without inferring identity from its request.
    assert evidence["observed_model"] is None
    assert evidence["model_provenance"] == "unknown"
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

    assert "Abschlussstatus wird nach Policy ermittelt" in str(answer)
    assert len(backend.calls) == 1
    messages = json.dumps(backend.calls[0][0], ensure_ascii=False)
    assert binding._ack.lease_id not in messages
    evidence = _assert_available_execution(binding, backend_id="openai", model="gpt-4o")
    assert evidence["slot_id"] == CHAT_ID
    result = _result_snapshot(binding)
    assert result["execution"]["execution_id"] == evidence["execution_id"]
    assert result["accepted"] is False and result["submission"]["availability"] == "available"


@pytest.mark.parametrize("ack_fence_mode", ["available", "missing", "raises", "inactive"])
def test_non_ollama_bound_worker_exposes_generic_lifecycle_without_extra_kwargs(
    task_state, monkeypatch, ack_fence_mode,
):
    from hub._services.chat import telegram_chat

    canonical_binding = task_state["binding"]
    binding = canonical_binding
    if ack_fence_mode != "available":
        class _AckMetadataProxy:
            def __getattr__(self, name):
                if name == "fence":
                    if ack_fence_mode == "raises":
                        raise RuntimeError("synthetic optional fence read failure")
                    raise AttributeError(name)
                return getattr(canonical_binding._ack, name)

        class _BindingMetadataProxy:
            def assert_active(self):
                if ack_fence_mode == "inactive":
                    raise RuntimeError("synthetic active-lease denial")
                return canonical_binding.assert_active()

            def __getattr__(self, name):
                if name == "_ack":
                    return _AckMetadataProxy()
                return getattr(canonical_binding, name)

        binding = _BindingMetadataProxy()
    worker_id = "generic-request-" + uuid.uuid4().hex[:10]
    control = telegram_chat._WorkerControl(worker_id, generation=binding.generation)
    control.task_binding = binding
    control.thread = threading.current_thread()
    control.physical_worker_id = "isolated-runtime-worker@HOST"
    control.lease_worker_id = "isolated-runtime-worker@HOST"
    control.worker_thread_started = True
    monkeypatch.setattr(telegram_chat, "_WORKER_CONTROLS", {worker_id: control})
    monkeypatch.setattr(telegram_chat, "_WORKER_EXECUTIONS", {worker_id: control})

    backend = FakeOpenAIBackend(
        response={"content": "generic result", "tool_calls": None,
                  "raw_message": {"role": "assistant", "content": "generic result"}},
    )
    runtime = _runtime(backend, monkeypatch, chat_id=worker_id)
    session = runtime.get_session(worker_id)
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.worker_model_request_control = control
    session.worker_handoff = control.handoff
    session.worker_task_actions = control.task_actions

    answer = asyncio.run(runtime.process("generic worker request", worker_id))
    receipt = telegram_chat.worker_execution_receipt(
        worker_id, control.start_request_id, verify_results=False,
    )
    if ack_fence_mode == "inactive":
        assert len(backend.calls) == 0
        assert "provider_request" not in receipt
        return
    assert answer == "generic result"
    assert len(backend.calls) == 1
    request = receipt["provider_request"]
    assert request["generation"] == control.generation
    assert request["task_id"] == binding.task_id
    if ack_fence_mode == "available":
        assert request["task_fence"] == canonical_binding._ack.fence
        assert request["task_fence_available"] is True
    else:
        assert request["task_fence"] is None
        assert request["task_fence_available"] is False
    assert request["phase"] == "runtime_call_complete"
    assert request["terminal_reason"] == "backend_returned"
    assert request["transport"] == "unavailable"
    assert request["transport_details_available"] is False
    assert request["cancellation_supported"] is False
    assert request["client_cleanup_complete"] is None
    assert request["runtime_call_complete"] is True


@pytest.mark.parametrize("change", ["stop", "generation", "deadline", "binding_swap"])
def test_dispatch_rechecks_authority_after_real_execution_ledger_start(
    task_state, monkeypatch, change,
):
    binding = task_state["binding"]
    backend = FakeOpenAIBackend(response={"content": "must not dispatch after authority changed"})
    runtime = _runtime(backend, monkeypatch)
    session = runtime.get_session(CHAT_ID)
    session.worker_task_binding = binding
    session.require_task_binding = True
    assert session._worker_model_dispatch_binding is None

    real_begin = binding.begin_model_execution
    replacement = {}

    def begin_then_change_authority(**kwargs):
        handle = real_begin(**kwargs)
        assert handle is not None  # The real isolated ledger start committed.
        if change == "stop":
            binding._stop_event.set()
        elif change == "generation":
            task_state["current"]["value"] = False
        elif change == "deadline":
            binding._clock = lambda: binding._ack.local_deadline
        else:
            other_binding, _ = task_state["make_binding"](title="Replacement binding")
            replacement["binding"] = other_binding
            session.worker_task_binding = other_binding
        return handle

    monkeypatch.setattr(binding, "begin_model_execution", begin_then_change_authority)
    answer = asyncio.run(runtime.process("Dispatch must recheck its authority", CHAT_ID))

    assert isinstance(answer, FailedAnswer)
    assert backend.calls == []
    assert _result_snapshot(binding) is None
    assert session._worker_model_dispatch_binding is None
    rows = _execution_rows(task_state, binding.task_id)
    assert len(rows) == 1
    assert rows[0]["phase"] == "failed"
    assert rows[0]["result_id"] is None


def test_tool_grant_narrowing_after_real_ledger_start_dispatches_without_execution_evidence(
    task_state, monkeypatch,
):
    binding = task_state["binding"]
    backend = FakeOpenAIBackend(response={"content": "ordinary response after tool grant narrowed"})
    runtime = _runtime(backend, monkeypatch)
    session = runtime.get_session(CHAT_ID)
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.allowed_tools = None

    real_begin = binding.begin_model_execution

    def begin_then_narrow_grants(**kwargs):
        handle = real_begin(**kwargs)
        assert handle is not None  # Use the real ledger start, not a synthetic handle.
        session.allowed_tools = []
        return handle

    monkeypatch.setattr(binding, "begin_model_execution", begin_then_narrow_grants)
    answer = asyncio.run(runtime.process("Continue with a narrower tool grant", CHAT_ID))

    assert answer == "ordinary response after tool grant narrowed"
    assert len(backend.calls) == 1
    assert backend.calls[0][1] == []
    assert session._worker_model_dispatch_binding is binding
    assert _result_snapshot(binding) is None
    rows = _execution_rows(task_state, binding.task_id)
    assert len(rows) == 1
    assert rows[0]["phase"] == "failed"
    assert rows[0]["result_id"] is None


def test_stop_after_real_failed_ledger_finish_blocks_dispatch_after_tool_hash_drift(
    task_state, monkeypatch,
):
    binding = task_state["binding"]
    backend = FakeOpenAIBackend(response={"content": "must not dispatch after stop"})
    runtime = _runtime(backend, monkeypatch)
    session = runtime.get_session(CHAT_ID)
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.allowed_tools = None
    assert session._worker_model_dispatch_binding is None

    real_begin = binding.begin_model_execution
    real_finish = binding.finish_model_execution
    finish_calls = []

    def begin_then_narrow_grants(**kwargs):
        handle = real_begin(**kwargs)
        assert handle is not None  # The real isolated ledger start committed.
        session.allowed_tools = []
        return handle

    def finish_then_request_stop(handle, *, result=None, failed=False):
        outcome = real_finish(handle, result=result, failed=failed)
        finish_calls.append((failed, outcome))
        if failed:
            binding._stop_event.set()
        return outcome

    monkeypatch.setattr(binding, "begin_model_execution", begin_then_narrow_grants)
    monkeypatch.setattr(binding, "finish_model_execution", finish_then_request_stop)
    answer = asyncio.run(runtime.process("Stop after failed ledger finish", CHAT_ID))

    assert isinstance(answer, FailedAnswer)
    assert finish_calls == [(True, False)]
    assert backend.calls == []
    assert session._worker_model_dispatch_binding is None
    assert _result_snapshot(binding) is None
    rows = _execution_rows(task_state, binding.task_id)
    assert len(rows) == 1
    assert rows[0]["phase"] == "failed"
    assert rows[0]["result_id"] is None


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

    assert "Abschlussstatus wird nach Policy ermittelt" in str(answer)
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
        "arguments": {"action": "submit_result", "task_id": binding.task_id, "complete": True,
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


@pytest.mark.parametrize("abort_reason", ["worker_stop", "total_deadline"])
def test_worker_abort_discards_buffered_tool_candidates_before_runtime_dispatch(
    task_state, tmp_path, monkeypatch, abort_reason,
):
    import os
    import time

    import httpx

    from hub._services.chat import chat_runtime as runtime_module
    from hub._services.chat import slots_config as slots
    from hub._services.chat import telegram_chat
    from hub._services.llm import model_backend
    from hub._services.llm.model_backend import OllamaBackend

    worker_id = "cancel-runtime-" + uuid.uuid4().hex[:10]
    control = telegram_chat._WorkerControl(worker_id)
    binding, _current = task_state["make_binding"](
        generation=control.generation,
        title="Buffered provider tool cancellation",
        stop_event=control.stop_event,
    )
    control.task_binding = binding
    control.physical_worker_id = "isolated-runtime-worker@HOST"
    control.lease_worker_id = "isolated-runtime-worker@HOST"
    control.launch_attempted = True
    control.worker_thread_started = True

    slots_path = tmp_path / "cancel-runtime-slots.json"
    slots.initialize_slots_config(str(slots_path))
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(slots_path))
    profile = slots.add_worker({
        "id": worker_id,
        "name": "Isolated cancellation integration",
        "backend": "ollama",
        "model": "m",
        "mode": "safe",
        "max_tool_rounds": 3,
        "task_id": binding.task_id,
        "type": "once",
        "allow_tools": True,
        "allowed_tools": ["task_manage"],
        "max_model_requests": 8,
    }, path=str(slots_path))
    profile.update({"status": "running", "enabled": True})
    configuration_version = slots._worker_profile_version(profile)
    budget_record = {
        "schema": "bach.worker-model-requests.v1",
        "worker_id": worker_id,
        "service_instance": telegram_chat._WORKER_SERVICE_INSTANCE,
        "pid": os.getpid(),
        "process_create_time": max(time.time(), 1.0),
        "start_request_id": control.start_request_id,
        "generation": control.generation,
        "task_id": binding.task_id,
        "task_version": None,
        "configuration_version": configuration_version,
        "limit": 8,
        "reserved_count": 0,
        "phase": "admitted",
        "reason": "",
        "sequence": 0,
    }
    with slots.worker_admission_transaction(str(slots_path)) as advance_revision:
        advance_revision(model_request_run=budget_record)
    budget = telegram_chat._ModelRequestBudget(
        worker_id=worker_id,
        service_instance=budget_record["service_instance"],
        start_request_id=control.start_request_id,
        generation=control.generation,
        task_id=binding.task_id,
        configuration_version=configuration_version,
    )
    control.model_request_budget = budget

    from pathlib import Path
    source_root = Path(__file__).resolve().parents[1]
    imported_paths = {
        "chat_runtime": Path(runtime_module.__file__).resolve(),
        "telegram_chat": Path(telegram_chat.__file__).resolve(),
        "model_backend": Path(model_backend.__file__).resolve(),
    }
    assert all(path.is_relative_to(source_root) for path in imported_paths.values())
    print("CANCEL_TEST_IMPORTS", {name: str(path) for name, path in imported_paths.items()})
    runtime = runtime_module.ChatRuntime(OllamaBackend(default_model="m"))
    runtime.max_tool_rounds = 3
    runtime.hook_every = 999
    runtime._get_bach_context = lambda _text: ""
    runtime._get_memory_hook_context = lambda *_args: ""
    # The host inference semaphore is outside this deterministic fake transport;
    # keep the task, budget, handoff and tool authority gates live.
    runtime._uses_local_compute = lambda _backend: False
    session = runtime.get_session(worker_id)
    session.chat_id = worker_id
    session.backend = runtime.backend
    session.model = "m"
    session.mode = profile["mode"]
    session.allow_tools = True
    session.allowed_tools = ["task_manage"]
    session.max_tool_rounds = 3
    session.worker_task_binding = binding
    session.require_task_binding = True
    session.worker_slot_reader = lambda: dict(profile)
    session.worker_model_request_control = control
    session.worker_handoff = control.handoff
    session.worker_task_actions = control.task_actions
    session.model_request_budget = budget

    escaped_actions = []
    monkeypatch.setattr(runtime_module, "exec_tool",
                        lambda *args, **kwargs: escaped_actions.append((args, kwargs)))
    monkeypatch.setattr(telegram_chat, "_execution_worker_slot",
                        lambda _ident: dict(profile))
    monkeypatch.setattr(telegram_chat, "update_slot",
                        lambda _ident, changes: profile.update(changes))
    monkeypatch.setattr(telegram_chat, "record_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(telegram_chat, "_WORKER_STOP_WAIT_SECONDS", 2.0)

    action = {
        "action": "done",
        "task_id": binding.task_id,
        "result": "This must remain inert because the answer never completed.",
    }
    tool_call = {"function": {"name": "task_manage", "arguments": action}}
    text_action = "<tool_call>" + json.dumps(
        {"name": "task_manage", "arguments": action}, separators=(",", ":")
    ) + "</tool_call>"
    first_chunk = json.dumps({
        "model": "m",
        "message": {
            "role": "assistant",
            "content": text_action,
            "tool_calls": [tool_call],
        },
        "done": False,
    })
    read_started = threading.Event()
    read_cancelled = threading.Event()
    response_closed = threading.Event()
    client_closed = threading.Event()
    cleanup_order = []
    loop_holder = {}
    outcomes = {}
    observer_error_phases = set()
    original_observer = control.observe_provider_request

    def fail_one_observer_phase(request, phase, *, reason=None):
        if phase == "response_headers_received" and phase not in observer_error_phases:
            observer_error_phases.add(phase)
            raise RuntimeError("synthetic observer failure")
        return original_observer(request, phase, reason=reason)

    control.observe_provider_request = fail_one_observer_phase

    class FakeResponse:
        status_code = 200
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            response_closed.set()
            cleanup_order.append("response_closed")
            return False

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield first_chunk
            read_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                read_cancelled.set()

    response = FakeResponse()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            client_closed.set()
            cleanup_order.append("client_closed")
            return False

        def stream(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    original_limit = model_backend.limit
    monkeypatch.setattr(
        model_backend,
        "limit",
        lambda name: (
            0.05 if abort_reason == "total_deadline" and name == "BACH_LLM_TOTAL_CAP"
            else 30 if name in {"BACH_LLM_IDLE_TIMEOUT", "BACH_LLM_TOTAL_CAP"}
            else original_limit(name)
        ),
    )

    def run_worker():
        loop = asyncio.new_event_loop()
        loop_holder["loop"] = loop
        asyncio.set_event_loop(loop)
        try:
            outcomes["answer"] = loop.run_until_complete(
                runtime.process("Run the isolated bound worker request.", worker_id,
                                backend=session.backend, model="m")
            )
            outcomes["provider_request"] = telegram_chat.worker_execution_receipt(
                worker_id, control.start_request_id, verify_results=False,
            ).get("provider_request")
            outcomes["pending_task_count"] = len(asyncio.all_tasks(loop))
        except BaseException as exc:
            outcomes["error"] = exc
        finally:
            try:
                if binding._active:
                    outcomes["lease_returned"] = binding.return_lease()
                    cleanup_order.append("lease_returned")
                record = slots.model_request_run_record(worker_id, control.start_request_id)
                if record is not None and record["phase"] != "terminal":
                    slots.terminalize_model_request_run(
                        worker_id,
                        service_instance=telegram_chat._WORKER_SERVICE_INSTANCE,
                        start_request_id=control.start_request_id,
                        generation=control.generation,
                        expected_sequence=record["sequence"],
                        reason="controller_cleanup_confirmed",
                    )
            except BaseException as exc:
                outcomes["cleanup_error"] = exc
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
                with telegram_chat._WORKER_CONTROL_LOCK:
                    control.done_event.set()
                    if telegram_chat._WORKER_CONTROLS.get(worker_id) is control:
                        telegram_chat._WORKER_CONTROLS.pop(worker_id, None)
                    telegram_chat._ACTIVE_WORKER_THREADS.pop(worker_id, None)

    controls = {worker_id: control}
    executions = {worker_id: control}
    active_threads = {}
    monkeypatch.setattr(telegram_chat, "_WORKER_CONTROLS", controls)
    monkeypatch.setattr(telegram_chat, "_WORKER_EXECUTIONS", executions)
    monkeypatch.setattr(telegram_chat, "_ACTIVE_WORKER_THREADS", active_threads)
    thread = threading.Thread(target=run_worker)
    control.thread = thread
    active_threads[worker_id] = thread
    thread.start()

    try:
        if not read_started.wait(5):
            raise AssertionError(
                f"worker never reached provider read; alive={thread.is_alive()}, outcomes={outcomes!r}"
            )
        active_execution = telegram_chat.worker_execution_receipt(
            worker_id, control.start_request_id, verify_results=False,
        )
        active_provider_request = active_execution["provider_request"]
        assert active_provider_request["request_id"]
        assert active_provider_request["generation"] == control.generation
        assert active_provider_request["task_id"] == binding.task_id
        assert active_provider_request["task_fence"] == binding._ack.fence
        assert active_provider_request["phase"] == "first_stream_chunk_received"
        assert active_provider_request["transport"] == "ollama_httpx"
        assert active_provider_request["transport_details_available"] is True
        active_request_id = active_provider_request["request_id"]

        if abort_reason == "worker_stop":
            old_request = control.active_model_request
            old_cancel_event = old_request.cancel_event
            next_control = telegram_chat._WorkerControl(worker_id, generation="replacement-generation")
            next_binding, _ = task_state["make_binding"](
                generation=next_control.generation,
                title="Replacement generation remains isolated",
                stop_event=next_control.stop_event,
            )
            next_control.task_binding = next_binding
            next_control.launch_attempted = True
            next_control.worker_thread_started = True
            next_event = asyncio.Event()
            with telegram_chat._WORKER_CONTROL_LOCK:
                controls[worker_id] = next_control
                executions[worker_id] = next_control
                active_threads[worker_id] = None
            next_handle = next_control.register_provider_request(
                next_binding, loop_holder["loop"], next_event,
            )
            assert next_handle is not None
            assert control.observe_provider_request(old_request, "response_completed") is False
            assert next_control.active_model_request.phase == "registered"

            stale_expected = {
                "service_instance": telegram_chat._WORKER_SERVICE_INSTANCE,
                "start_request_id": control.start_request_id,
                "generation": control.generation,
            }
            confirmed, _slot, stale_receipt, stale_code = telegram_chat._request_worker_revocation(
                worker_id, profile, expected_execution=stale_expected,
            )
            assert stale_code == 409 and not confirmed
            assert stale_receipt["confirmed"] is False
            assert not old_cancel_event.is_set()
            assert not next_event.is_set()
            next_control.finish_provider_request(next_handle)

            with telegram_chat._WORKER_CONTROL_LOCK:
                controls[worker_id] = control
                executions[worker_id] = control
                active_threads[worker_id] = thread
            _status_persisted, _slot, receipt, code = telegram_chat._request_worker_revocation(
                worker_id, profile, expected_execution=stale_expected,
            )
        thread.join(4)
    finally:
        if thread.is_alive():
            control.stop_event.set()
            control.cancel_active_model_request()
            thread.join(4)
    assert not thread.is_alive()
    assert "error" not in outcomes, repr(outcomes.get("error"))
    assert "cleanup_error" not in outcomes, repr(outcomes.get("cleanup_error"))
    if abort_reason == "worker_stop":
        assert code == 200
        assert receipt["confirmed"] is True
        assert receipt["execution"]["terminal"] is True
        assert receipt["execution"]["generation"] == control.generation
    else:
        assert not control.stop_event.is_set()
        assert control.done_event.is_set()
    assert isinstance(outcomes["answer"], FailedAnswer)
    assert text_action in str(outcomes["answer"])
    assert escaped_actions == []
    assert read_cancelled.is_set()
    assert response_closed.is_set()
    assert client_closed.is_set()
    assert cleanup_order == ["response_closed", "client_closed", "lease_returned"]
    assert outcomes["pending_task_count"] == 0
    assert control.active_model_request is None
    assert outcomes["lease_returned"] is True
    request = outcomes["provider_request"]
    assert request is not None
    assert request["request_id"] == active_request_id
    assert request["generation"] == control.generation
    assert request["task_id"] == binding.task_id
    assert request["task_fence"] == binding._ack.fence
    assert request["phase"] == "runtime_call_complete"
    assert request["terminal_reason"] == abort_reason
    assert request["transport"] == "ollama_httpx"
    assert request["transport_details_available"] is True
    assert request["response_cleanup_complete"] is True
    assert request["client_cleanup_complete"] is True
    assert request["runtime_call_complete"] is True
    assert request["cancel_requested"] is (abort_reason == "worker_stop")
    assert request["observer_error"] is True
    task_snapshot = task_state["client"].task_snapshot(binding.task_id)
    assert task_snapshot["status"] == "pending"
    assert task_state["client"].read(binding.task_id).leased is False
    assert task_state["client"].task_result_snapshot(binding.task_id)["result"] is None
    final_budget = slots.model_request_run_record(worker_id, control.start_request_id)
    assert final_budget["phase"] == "terminal"
    assert final_budget["reserved_count"] == 1
