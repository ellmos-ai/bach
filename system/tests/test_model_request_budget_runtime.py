"""Observed runtime dispatch contracts for durable model-request budgets.

Every backend below is a real local backend object with only its ``chat``
transport replaced by a deterministic in-process coroutine. Budget admission
and reservations use the real slots configuration code and a temporary file.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

_SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))

from hub._services.chat import chat_runtime as runtime_module
from hub._services.chat import slots_config as slots
from hub._services.chat import telegram_chat
from hub._services.chat import model_sockets
from hub._services.llm.model_backend import CLIBackend, OllamaBackend
from hub._services.chat.worker_tool_trace import TraceIdentity


TASK_ID = 2217
TASK_VERSION = "a" * 64
MODEL = "qwen3.5:4b"
FALLBACK_MODEL = "llama3.2:3b"


class _Binding:
    """Small runtime binding; budget persistence remains the real slot store."""

    def __init__(self, task_id: int = TASK_ID, generation: str | None = None):
        self.task_id = task_id
        self.generation = generation or uuid.uuid4().hex
        self.closed = False
        self._review_grant = None
        self.completed_task_ids = ()
        self.model_starts = []
        self.model_finishes = []
        self.tool_phases = []
        self.invalidated = False

    def task_snapshot(self):
        return {"id": self.task_id, "task_version": TASK_VERSION}

    def budget_task_version_evidence(self):
        self.assert_active()
        return self.task_id, TASK_VERSION, ()

    def assert_active(self):
        if self.closed:
            raise RuntimeError("binding closed")

    def _discard_model_execution_candidate(self):
        return None

    def begin_model_execution(self, **fields):
        handle = uuid.uuid4().hex
        self.model_starts.append({"handle": handle, **fields})
        return handle

    def finish_model_execution(self, handle, *, result=None, failed=False, **fields):
        self.model_finishes.append({"handle": handle, "result": result,
                                    "failed": failed, **fields})
        return True

    def trace_tool_started(self, *, source, request_id, tool_name, arguments_sha256):
        return TraceIdentity(
            task_id=self.task_id,
            fence=1,
            worker_id="isolated-budget-worker",
            generation=self.generation,
            task_version=TASK_VERSION,
            request_id=request_id,
            source=source,
            tool_name=tool_name,
        )

    def trace_tool_phase(self, identity, phase, **fields):
        self.tool_phases.append((identity, phase, fields))
        return {"accepted": True}

    def invalidate(self):
        self.invalidated = True
        self.closed = True


def _new_budget(tmp_path, monkeypatch, *, limit=8, worker_id=None):
    worker_id = worker_id or f"budget-runtime-{uuid.uuid4().hex[:12]}"
    path = tmp_path / f"{worker_id}.json"
    slots.initialize_slots_config(str(path))
    worker = slots.add_worker(
        {
            "id": worker_id,
            "name": "Isolated runtime budget test",
            "backend": "ollama",
            "model": MODEL,
            "mode": "safe",
            "max_tool_rounds": 20,
            "task_id": TASK_ID,
            "type": "once",
            "allow_tools": True,
            "allowed_tools": ["read_file", "task_manage"],
            "max_model_requests": limit,
        },
        path=str(path),
    )
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    record = {
        "schema": "bach.worker-model-requests.v1",
        "worker_id": worker_id,
        "service_instance": telegram_chat._WORKER_SERVICE_INSTANCE,
        "pid": os.getpid(),
        "process_create_time": max(time.time(), 1.0),
        "start_request_id": uuid.uuid4().hex,
        "generation": uuid.uuid4().hex,
        "task_id": TASK_ID,
        "task_version": None,
        "configuration_version": slots._worker_profile_version(worker),
        "limit": limit,
        "reserved_count": 0,
        "phase": "admitted",
        "reason": "",
        "sequence": 0,
    }
    with slots.worker_admission_transaction(str(path)) as advance_revision:
        advance_revision(model_request_run=record)
    budget = telegram_chat._ModelRequestBudget(
        worker_id=worker_id,
        service_instance=record["service_instance"],
        start_request_id=record["start_request_id"],
        generation=record["generation"],
        task_id=TASK_ID,
        configuration_version=record["configuration_version"],
    )
    return path, worker, budget


def _runtime_session(backend, budget, monkeypatch, *, binding=None):
    runtime = runtime_module.ChatRuntime(backend)
    runtime.max_tool_rounds = 20
    runtime.hook_every = 999
    runtime._get_bach_context = lambda _text: ""
    runtime._get_memory_hook_context = lambda *_args: ""
    runtime._uses_local_compute = lambda _selected: False
    runtime._worker_backend_gate = lambda *_args, **_kwargs: None
    session = runtime.get_session(budget.worker_id if budget is not None else "unbudgeted-chat")
    session.chat_id = budget.worker_id if budget is not None else "unbudgeted-chat"
    session.backend = backend
    session.model = MODEL
    session.allow_tools = True
    session.allowed_tools = ["read_file", "task_manage"]
    session.max_tool_rounds = 20
    session.worker_task_binding = binding
    session.require_task_binding = binding is not None
    session.model_request_budget = budget
    monkeypatch.setattr(slots, "update_slot", lambda *_args, **_kwargs: None)
    return runtime, session


def _wire_digest(messages, *, tools, think, model):
    encoded = json.dumps(
        {"args": (messages,),
         "kwargs": {"tools": tools, "think": think, "model": model}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_dispatch(runtime, session, *, messages=None, tools=None,
                  completion_reserve=False, tool_rounds_enabled=None):
    async def call():
        token = runtime._compute_turn_context.set((session.chat_id, "background"))
        try:
            kwargs = {"tools": tools, "think": False, "model": MODEL,
                      "_completion_reserve": completion_reserve}
            if tool_rounds_enabled is not None:
                kwargs["_tool_rounds_enabled"] = tool_rounds_enabled
            return await runtime._chat_with_compute_turn(
                session.backend,
                messages or [{"role": "user", "content": "isolated request"}],
                **kwargs,
            )
        finally:
            runtime._compute_turn_context.reset(token)
    return asyncio.run(call())


def _task_manage_tool():
    return {
        "type": "function",
        "function": {
            "name": "task_manage",
            "description": "Use only the bound task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": [
                        "list", "update", "submit_result", "decompose", "done"]},
                    "task_id": {"type": "integer"},
                    "status": {"type": "string"},
                    "result": {"type": "string"},
                },
                "required": ["action", "task_id"],
            },
        },
    }


def _read_file_tool():
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one file.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }


def _tool_response(action, **arguments):
    args = {"action": action, "task_id": TASK_ID, **arguments}
    call = {"function": {"name": "task_manage", "arguments": args}}
    return {"content": "", "tool_calls": [call],
            "raw_message": {"role": "assistant", "content": "", "tool_calls": [call]}}


def _reserve_plain_calls(runtime, session, backend, count):
    calls = []

    async def fake_chat(messages, tools=None, think=True, model=None):
        calls.append((copy.deepcopy(messages), copy.deepcopy(tools), think, model))
        record = slots.model_request_run_record(
            session.chat_id, session.model_request_budget.start_request_id)
        assert record["reserved_count"] == len(calls)
        return {"content": f"ordinary response {len(calls)}"}

    backend.chat = fake_chat
    for _ in range(count):
        _run_dispatch(runtime, session, tools=None)
    return calls


def test_real_ollama_dispatch_reserves_before_call_and_timeout_consumes_request(
    tmp_path, monkeypatch,
):
    path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    binding = _Binding()
    runtime, session = _runtime_session(backend, budget, monkeypatch, binding=binding)
    calls = []

    async def fake_chat(messages, tools=None, think=True, model=None):
        calls.append((copy.deepcopy(messages), copy.deepcopy(tools), think, model))
        record = slots.model_request_run_record(budget.worker_id, budget.start_request_id)
        assert record["reserved_count"] == len(calls)
        if len(calls) == 1:
            raise asyncio.TimeoutError("synthetic transport timeout")
        return {"content": "second request returned"}

    backend.chat = fake_chat
    with pytest.raises(asyncio.TimeoutError):
        _run_dispatch(runtime, session, tools=None)

    first = slots.model_request_run_record(budget.worker_id, budget.start_request_id)
    assert first["reserved_count"] == 1
    assert binding.model_finishes[-1]["failed"] is True
    assert len(calls) == 1  # the failed attempt is not retried

    assert _run_dispatch(runtime, session, tools=None) == {"content": "second request returned"}
    final = slots.model_request_run_record(budget.worker_id, budget.start_request_id)
    assert final["reserved_count"] == 2
    assert len(calls) == 2
    assert binding.model_finishes[-1]["failed"] is False
    assert path.exists()


def test_local_tool_parser_error_gets_one_new_counted_request(tmp_path, monkeypatch):
    from hub._services.llm.backend_errors import classify_ollama_error

    _path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    binding = _Binding()
    runtime, session = _runtime_session(backend, budget, monkeypatch, binding=binding)
    calls = []
    private_error = "XML syntax error on line 3: element <function> closed by </parameter>"
    detail = classify_ollama_error({"error": private_error})
    assert detail["kind"] == "tool_parse_error"
    assert private_error not in repr(detail)
    assert classify_ollama_error({"error": private_error}, status_code=500)["kind"] == "tool_parse_error"
    assert classify_ollama_error({"message": private_error})["kind"] == "provider_error"

    async def fake_chat(messages, tools=None, think=True, model=None):
        calls.append(copy.deepcopy(messages))
        assert slots.model_request_run_record(
            budget.worker_id, budget.start_request_id)["reserved_count"] == len(calls)
        if len(calls) == 1:
            return {"content": "", "tool_calls": None, "error": detail["message"],
                    "backend_error": detail}
        return {"content": "gültige Antwort", "tool_calls": None}

    backend.chat = fake_chat
    result = _run_dispatch(runtime, session, tools=[_read_file_tool()])
    assert result["content"] == "gültige Antwort"
    assert len(calls) == 2
    assert "Anfrage 1/8" in calls[0][-1]["content"]
    assert "Anfrage 2/8" in calls[1][-1]["content"]
    assert "ungültiges Werkzeugformat" in calls[1][-2]["content"]
    assert private_error not in repr(calls)
    assert binding.model_finishes[0]["failed"] is True
    assert binding.model_finishes[1]["failed"] is False
    assert binding.model_starts[0]["request_sha256"] != binding.model_starts[1]["request_sha256"]

    # A second malformed answer is returned to the controller; it cannot
    # recursively buy a third attempt from the same tool-parser incident.
    async def still_invalid(messages, tools=None, think=True, model=None):
        calls.append(copy.deepcopy(messages))
        assert slots.model_request_run_record(
            budget.worker_id, budget.start_request_id)["reserved_count"] == len(calls)
        return {"content": "", "tool_calls": None, "error": detail["message"],
                "backend_error": detail}

    backend.chat = still_invalid
    failed = _run_dispatch(runtime, session, tools=[_read_file_tool()])
    assert failed["backend_error"]["kind"] == "tool_parse_error"
    assert len(calls) == 4


@pytest.mark.parametrize("remaining,tools,kind", [
    (3, [_read_file_tool()], "tool_parse_error"),
    (8, None, "tool_parse_error"),
    (8, [_read_file_tool()], "provider_error"),
])
def test_parser_retry_refuses_unreserved_or_unrelated_attempt(
    tmp_path, monkeypatch, remaining, tools, kind,
):
    _path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    runtime, session = _runtime_session(backend, budget, monkeypatch, binding=_Binding())
    if remaining < 8:
        _reserve_plain_calls(runtime, session, backend, 8 - remaining)
    observed = []

    async def fake_chat(messages, tools=None, think=True, model=None):
        observed.append(copy.deepcopy(messages))
        return {"content": "", "tool_calls": None, "error": "fester Fehler",
                "backend_error": {"provider": "ollama", "kind": kind,
                                  "quota_exceeded": False}}

    backend.chat = fake_chat
    _run_dispatch(runtime, session, tools=tools)
    assert len(observed) == 1
    assert slots.model_request_run_record(
        budget.worker_id, budget.start_request_id)["reserved_count"] == 9 - remaining


def test_two_request_completion_reserve_narrows_real_tool_requests_and_blocks_ninth(
    tmp_path, monkeypatch,
):
    _path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    binding = _Binding()
    runtime, session = _runtime_session(backend, budget, monkeypatch, binding=binding)
    calls = []
    base_tools = [_read_file_tool(), _task_manage_tool()]

    async def fake_chat(messages, tools=None, think=True, model=None):
        calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools),
                      "think": think, "model": model})
        record = slots.model_request_run_record(budget.worker_id, budget.start_request_id)
        assert record["reserved_count"] == len(calls)
        if len(calls) <= 6:
            return {"content": f"work step {len(calls)}"}
        if len(calls) == 7:
            # A task tool is offered, but ordinary lookup is outside the
            # completion-reserve action set and must have no effect.
            return _tool_response("list")
        if len(calls) == 8:
            return _tool_response("submit_result", result="reported, not accepted", complete=True)
        raise AssertionError("a ninth Ollama dispatch must not occur")

    backend.chat = fake_chat
    for request_number in range(1, 7):
        assert _run_dispatch(runtime, session, tools=None) == {
            "content": f"work step {request_number}"
        }

    # The loop rebuilds offered schemas through the actual runtime boundary;
    # the seam returns only the two already-granted test schemas.
    def offered_tools(_session, _backend, *, enabled, completion_reserve=False):
        assert enabled is True
        return (runtime_module._completion_reserve_tools(base_tools, binding)
                if completion_reserve else copy.deepcopy(base_tools))

    runtime._bound_worker_tools_for_request = offered_tools
    tool_effects = []
    monkeypatch.setattr(
        runtime_module, "exec_tool",
        lambda name, arguments, _mode, **_kwargs:
            (tool_effects.append((name, copy.deepcopy(arguments))) or "isolated no-op result"),
    )

    async def run_loop():
        token = runtime._compute_turn_context.set((session.chat_id, "background"))
        try:
            return await runtime._tool_loop_impl(
                [{"role": "user", "content": "continue isolated task"}],
                session,
                base_tools,
                backend=backend,
                model=MODEL,
            )
        finally:
            runtime._compute_turn_context.reset(token)

    answer = asyncio.run(run_loop())
    assert isinstance(answer, runtime_module.FailedAnswer)
    assert len(calls) == 8
    assert [item["action"] for _name, item in tool_effects] == ["submit_result"]
    assert all(item["task_id"] == TASK_ID for _name, item in tool_effects)
    assert [phase for _identity, phase, _fields in binding.tool_phases].count("acknowledged") == 2
    assert binding.completed_task_ids == ()  # text and fake tools do not prove completion

    for request_number, call_index in ((7, 6), (8, 7)):
        call = calls[call_index]
        schemas = call["tools"]
        assert [tool["function"]["name"] for tool in schemas] == ["task_manage"]
        action_enum = schemas[0]["function"]["parameters"]["properties"]["action"]["enum"]
        assert action_enum == ["submit_result", "update", "decompose"]
        hint = next(message["content"] for message in call["messages"]
                    if isinstance(message.get("content"), str)
                    and "[MODELLANFRAGEN:" in message["content"])
        assert f"Anfrage {request_number}/8; danach {8 - request_number} übrig." in hint
        assert binding.model_starts[call_index]["request_sha256"] == _wire_digest(
            call["messages"], tools=call["tools"], think=call["think"], model=call["model"])

    stored = slots.model_request_run_record(budget.worker_id, budget.start_request_id)
    assert stored["reserved_count"] == 8
    with pytest.raises(slots.ModelRequestBudgetError):
        _run_dispatch(runtime, session, tools=None)
    assert len(calls) == 8
    assert slots.model_request_run_record(budget.worker_id, budget.start_request_id)[
        "reserved_count"] == 8


def test_auto_continue_handoff_and_summarize_cannot_consume_completion_reserve(
    tmp_path, monkeypatch,
):
    _path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    binding = _Binding()
    runtime, session = _runtime_session(backend, budget, monkeypatch, binding=binding)
    calls = _reserve_plain_calls(runtime, session, backend, 6)
    runtime.auto_continue = 3
    before = len(calls)

    async def fake_chat(messages, tools=None, think=True, model=None):
        calls.append((copy.deepcopy(messages), copy.deepcopy(tools), think, model))
        record = slots.model_request_run_record(budget.worker_id, budget.start_request_id)
        assert record["reserved_count"] == 7
        return {"content": "final status only"}

    backend.chat = fake_chat

    async def run_text_loop():
        token = runtime._compute_turn_context.set((session.chat_id, "background"))
        try:
            return await runtime._tool_loop_impl(
                [{"role": "user", "content": "finish"}], session, [],
                backend=backend, model=MODEL,
            )
        finally:
            runtime._compute_turn_context.reset(token)

    answer = asyncio.run(run_text_loop())
    assert answer == "final status only"
    assert len(calls) == before + 1
    assert slots.model_request_run_record(budget.worker_id, budget.start_request_id)[
        "reserved_count"] == 7

    session.messages = [{"role": "user", "content": f"history {index}"}
                        for index in range(6)]
    with pytest.raises(slots.ModelRequestBudgetError):
        asyncio.run(runtime._handoff(session.messages, session, backend=backend, model=MODEL))
    with pytest.raises(slots.ModelRequestBudgetError):
        asyncio.run(runtime._summarize(session, backend=backend, model=MODEL))
    assert len(calls) == before + 1


def test_local_fallback_spends_once_per_actual_call_and_typed_store_errors_do_not_retry(
    tmp_path, monkeypatch,
):
    _path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    primary = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    fallback = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=FALLBACK_MODEL)
    binding = _Binding()
    runtime, session = _runtime_session(primary, budget, monkeypatch, binding=binding)
    runtime._native_model_fallback_route = lambda *_args: {
        "targets": [{"backend": "ollama", "model": MODEL},
                    {"backend": "ollama", "model": FALLBACK_MODEL}],
        "index": 0,
    }
    monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda _target: fallback)
    calls = []

    async def primary_chat(*_args, **_kwargs):
        calls.append("primary")
        raise httpx.ConnectTimeout("synthetic pre-answer connection failure")

    async def fallback_chat(*_args, **_kwargs):
        calls.append("fallback")
        record = slots.model_request_run_record(budget.worker_id, budget.start_request_id)
        assert record["reserved_count"] == 2
        return {"content": "fallback answer"}

    primary.chat = primary_chat
    fallback.chat = fallback_chat

    async def run_fallback():
        token = runtime._compute_turn_context.set((session.chat_id, "background"))
        try:
            return await runtime._chat_with_configured_fallbacks(
                session, primary, MODEL,
                [{"role": "user", "content": "fallback test"}],
                tools=None, think=False,
            )
        finally:
            runtime._compute_turn_context.reset(token)

    result, selected_backend, selected_model = asyncio.run(run_fallback())
    assert result["content"] == "fallback answer"
    assert selected_backend is fallback and selected_model == FALLBACK_MODEL
    assert calls == ["primary", "fallback"]
    assert slots.model_request_run_record(budget.worker_id, budget.start_request_id)[
        "reserved_count"] == 2

    # A typed CAS/store failure is not evidence of a safe retryable backend
    # failure; the fallback transport must never be reached.
    _path2, _worker2, budget2 = _new_budget(tmp_path, monkeypatch)
    primary2 = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    binding2 = _Binding()
    runtime2, session2 = _runtime_session(primary2, budget2, monkeypatch, binding=binding2)
    runtime2._native_model_fallback_route = lambda *_args: {
        "targets": [{"backend": "ollama", "model": MODEL},
                    {"backend": "ollama", "model": FALLBACK_MODEL}],
        "index": 0,
    }
    never_fallback = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=FALLBACK_MODEL)
    monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda _target: never_fallback)
    no_calls = []
    primary2.chat = lambda *_args, **_kwargs: no_calls.append("primary")
    never_fallback.chat = lambda *_args, **_kwargs: no_calls.append("fallback")
    def raise_reservation_conflict(*_args, **_kwargs):
        raise slots.ModelRequestBudgetError("synthetic reservation conflict")

    monkeypatch.setattr(slots, "reserve_model_request", raise_reservation_conflict)

    async def run_store_failure():
        token = runtime2._compute_turn_context.set((session2.chat_id, "background"))
        try:
            return await runtime2._chat_with_configured_fallbacks(
                session2, primary2, MODEL,
                [{"role": "user", "content": "must not retry"}],
                tools=None, think=False,
            )
        finally:
            runtime2._compute_turn_context.reset(token)

    with pytest.raises(slots.ModelRequestBudgetError, match="reservation conflict"):
        asyncio.run(run_store_failure())
    assert no_calls == []
    assert slots.model_request_run_record(budget2.worker_id, budget2.start_request_id)[
        "reserved_count"] == 0


def test_unknown_cli_route_fails_before_dispatch_but_unbudgeted_ollama_is_unchanged(
    tmp_path, monkeypatch,
):
    _path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    cli = CLIBackend(cli_name="claude", cli_path="never-run", default_model="sonnet")
    binding = _Binding()
    runtime, session = _runtime_session(cli, budget, monkeypatch, binding=binding)
    cli_calls = []
    cli.chat = lambda *_args, **_kwargs: cli_calls.append(True)

    with pytest.raises(slots.ModelRequestBudgetError, match="Backendroute"):
        _run_dispatch(runtime, session, tools=None)
    assert cli_calls == []
    assert slots.model_request_run_record(budget.worker_id, budget.start_request_id)[
        "reserved_count"] == 0

    ordinary_backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    ordinary_runtime = runtime_module.ChatRuntime(ordinary_backend)
    ordinary_runtime._uses_local_compute = lambda _selected: False
    ordinary_calls = []

    async def ordinary_chat(messages, tools=None, think=True, model=None):
        ordinary_calls.append((messages, tools, think, model))
        return {"content": "legacy unbudgeted chat"}

    ordinary_backend.chat = ordinary_chat
    ordinary_session = ordinary_runtime.get_session("unbudgeted-chat")
    ordinary_session.chat_id = "unbudgeted-chat"
    ordinary_session.backend = ordinary_backend
    ordinary_session.model = MODEL
    assert ordinary_session.model_request_budget is None
    assert _run_dispatch(ordinary_runtime, ordinary_session, tools=None) == {
        "content": "legacy unbudgeted chat"
    }
    assert len(ordinary_calls) == 1


def test_running_projection_requires_current_budget_control_not_retained_receipt(
    tmp_path, monkeypatch,
):
    _path, worker, budget = _new_budget(tmp_path, monkeypatch)
    binding = _Binding(task_id=TASK_ID, generation=budget.generation)
    import threading

    release = threading.Event()
    thread = threading.Thread(target=release.wait, daemon=True)
    thread.start()
    try:
        control = telegram_chat._WorkerControl(
            worker_id=budget.worker_id,
            generation=budget.generation,
            start_request_id=budget.start_request_id,
            task_binding=binding,
            model_request_budget=budget,
            thread=thread,
            worker_thread_started=True,
            physical_worker_id="isolated-runtime-worker",
        )
        monkeypatch.setitem(telegram_chat._WORKER_CONTROLS, budget.worker_id, control)
        monkeypatch.setitem(telegram_chat._WORKER_EXECUTIONS, budget.worker_id, control)

        worker["status"] = "starting"
        worker["task_prompt"] = "isolated prompt"
        live = telegram_chat._worker_handoff_snapshot(worker)
        assert live["runtime_verified"] is True
        assert live["running"] is True
        assert live["worker_active"] is True
        assert live["status"] == "running"
        assert live["model_requests"]["used"] == 0

        # A retained execution receipt is historical evidence only. Removing
        # the current control pointer must make the public projection fail closed.
        monkeypatch.delitem(telegram_chat._WORKER_CONTROLS, budget.worker_id)
        lost = telegram_chat._worker_handoff_snapshot(worker)
        assert lost["running"] is False
        assert lost["worker_active"] is False
        assert lost["status"] == "unconfirmed"
        assert lost["execution"]["start_request_id"] == budget.start_request_id
    finally:
        release.set()
        thread.join(timeout=1)
