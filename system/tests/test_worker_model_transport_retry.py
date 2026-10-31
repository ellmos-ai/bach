"""Typed transport retries keep one native task, history and tool side effect."""
import asyncio
import copy
import json
import math
import sqlite3
import threading

import httpx
import pytest

from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer
from hub._services.llm.backend_errors import (
    BackendRequestFailure, cloud_call_retry_delay, cloud_call_retry_eligible,
)
from hub._services.llm.model_backend import OpenRouterBackend
from system.tests.test_worker_model_call_retry import Binding, _runtime


KINDS = {
    "connect_timeout": "ConnectTimeout", "read_timeout": "ReadTimeout",
    "write_timeout": "WriteTimeout", "pool_timeout": "PoolTimeout",
    "transport_timeout": "TimeoutException", "connection_error": "ConnectError",
    "transport_error": "RequestError",
}


def _transport(kind="transport_error", **changes):
    return {"provider": "openrouter", "kind": kind, "error_type": KINDS[kind],
            "quota_exceeded": False, **changes}


@pytest.mark.parametrize("kind", KINDS)
def test_typed_transport_has_bounded_backoff(kind):
    detail = _transport(kind)
    assert cloud_call_retry_eligible(detail)
    assert [cloud_call_retry_delay(detail, retries=i, waited_seconds=0)
            for i in range(4)] == [5, 10, 20, None]
    assert cloud_call_retry_delay(detail, retries=0, waited_seconds=895) == 5
    assert cloud_call_retry_delay(detail, retries=0, waited_seconds=896) is None
    for value in (True, -1, math.nan, math.inf):
        assert cloud_call_retry_delay(detail, retries=0, waited_seconds=value) is None
    assert not cloud_call_retry_eligible(_transport(kind, provider="hermes"))
    assert not cloud_call_retry_eligible(_transport(kind, quota_exceeded=True))
    assert not cloud_call_retry_eligible(_transport(kind, error_type="untrusted"))


@pytest.mark.parametrize("kind", KINDS)
def test_retry_preserves_exact_request_and_binding(monkeypatch, kind):
    runtime, session, backend, model, _ = _runtime(monkeypatch, provider="openrouter")
    messages = [{"role": "tool", "content": "already committed result"}]
    calls, waits = [], []
    async def call(actual, *args, **kwargs):
        calls.append((actual, copy.deepcopy(args), copy.deepcopy(kwargs),
                      session.worker_task_binding))
        if len(calls) == 1:
            raise BackendRequestFailure(_transport(kind))
        return {"content": "continued"}
    async def wait(seconds, *, check_active):
        check_active(); waits.append(seconds)
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    answer = asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, messages))
    assert answer == {"content": "continued"} and waits == [5]
    assert calls[0] == calls[1]
    assert messages == [{"role": "tool", "content": "already committed result"}]


@pytest.mark.parametrize("change", ["stop", "binding", "profile", "session", "mode", "fallback", "status"])
def test_transport_wait_aborts_on_binding_or_policy_loss(monkeypatch, change):
    runtime, session, backend, model, profile = _runtime(monkeypatch, provider="openrouter")
    calls = []
    async def call(*args, **kwargs):
        calls.append(1)
        raise BackendRequestFailure(_transport())
    async def wait(seconds, *, check_active):
        if change == "stop":
            session.worker_task_binding.active = False
        elif change == "binding":
            session.worker_task_binding = Binding()
        elif change == "profile":
            profile["model"] = "changed/free"
        elif change == "mode":
            profile["mode"] = "open"
        elif change == "fallback":
            profile["model_fallbacks"].append({"backend": "openrouter", "model": "fixture:free"})
        elif change == "status":
            profile["status"] = "completed"
        else:
            monkeypatch.setattr(runtime, "get_session", lambda _: object())
        check_active()
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    with pytest.raises(RuntimeError):
        asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, []))
    assert calls == [1]


@pytest.mark.parametrize("partial", [
    {"content": "partial"}, {"thinking": "partial"}, {"tool_calls": [{}]},
    {"raw_message": {"content": "partial"}}, {"raw_message": {"unknown": "partial"}},
])
def test_transport_with_partial_output_is_never_retried(monkeypatch, partial):
    runtime, session, backend, model, _ = _runtime(monkeypatch, provider="openrouter")
    result = {"error": "failure", "backend_error": _transport(), **partial}
    calls = []
    async def call(*args, **kwargs):
        calls.append(1); return result
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    assert asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, [])) is result
    assert calls == [1]


@pytest.mark.parametrize("kind", KINDS)
def test_transport_exhaustion_keeps_policy_bound_queue_continuation(monkeypatch, kind):
    from hub._services.chat.telegram_chat import _worker_backend_retry_delay
    runtime, session, backend, model, _ = _runtime(monkeypatch, provider="openrouter")
    calls, waits = [], []
    async def call(*args, **kwargs):
        calls.append(1); raise BackendRequestFailure(_transport(kind))
    async def wait(seconds, *, check_active):
        check_active(); waits.append(seconds)
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    result = asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, []))
    answer = FailedAnswer(result["error"], backend_error=result["backend_error"],
                          reason_code=result["reason_code"])
    assert len(calls) == 4 and waits == [5, 10, 20]
    assert answer.reason_code == "cloud_call_retry_exhausted"
    profile = {"backend": "openrouter", "type": "continuous"}
    for retries, expected in [(0, 60), (1, 120), (4, 900), (40, 900)]:
        assert _worker_backend_retry_delay(
            profile, answer.backend_error, model=model, retries=retries,
            waited_seconds=1200, reason_code=answer.reason_code) == (
                expected if kind == "connection_error" else None)
    for changes in ({"type": "once"}, {"max_model_requests": 3},
                    {"backend": "ollama-cloud"}):
        assert _worker_backend_retry_delay(
            {**profile, **changes}, answer.backend_error, model=model, retries=0,
            waited_seconds=0, reason_code=answer.reason_code) is None
    assert _worker_backend_retry_delay(
        profile, answer.backend_error, model=model, retries=0,
        waited_seconds=0, reason_code="model_request_budget_exhausted") is None


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout, httpx.RequestError])
def test_real_native_tool_effect_occurs_once_after_transport_failure(tmp_path, monkeypatch, failure):
    from hub._services import task_lease_client as clients
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from system.tests.test_task_lease_client import _init_db
    from system.tests.test_worker_backend_errors import _persistent_session_store
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(clients, "get_lead_config", lambda: {"mode": "isolated"})
    conn = sqlite3.connect(tmp_path / "tasks.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    conn.execute("INSERT INTO tasks(id,title,status,priority,category,assigned_to) VALUES(42,'Fixture','pending','P1','INBOX','BACH')")
    conn.commit()
    client = clients.TaskLeaseClient(conn=conn)
    binding = WorkerLeaseBinding.acquire(
        client, 42, worker_id="fixture@fixture", host="fixture", generation="a" * 32,
        is_current=lambda: True, stop_event=threading.Event())
    backend = OpenRouterBackend(api_key="fixture-key", default_model="openrouter/free")
    model = backend.get_default_model()
    runtime = ChatRuntime(backend, session_store=_persistent_session_store(tmp_path))
    monkeypatch.setattr(runtime, "_get_bach_context", lambda _: "")
    monkeypatch.setattr(runtime, "_get_memory_hook_context", lambda *a: "")
    session = runtime.get_session("worker-fixture")
    session.worker_task_binding, session.require_task_binding = binding, True
    session.worker_slot_reader = lambda: {
        "id": session.chat_id, "enabled": True, "type": "continuous", "status": "running",
        "backend": "openrouter", "model": model}
    calls, waits = [], []
    real_client = httpx.AsyncClient
    def reply(request):
        calls.append(request)
        if len(calls) == 1:
            message = {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_fixture", "type": "function", "function": {
                    "name": "task_manage",
                    "arguments": json.dumps({"action": "add", "title": "Only once"})}}]}
        elif len(calls) == 2:
            raise failure("PRIVATE request details must not escape", request=request)
        else:
            message = {"role": "assistant", "content": "Continued after existing tool result"}
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": {}})
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    async def wait(seconds, *, check_active):
        check_active()
        assert client.read(42).leased and binding.generation == "a" * 32
        waits.append(seconds)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    try:
        answer = asyncio.run(runtime.process(
            "Create one child then report", session.chat_id,
            backend=backend, model=model, work_priority="background"))
        assert answer == "Continued after existing tool result"
        assert waits == [5] and len(calls) == 3 and calls[1].content == calls[2].content
        assert binding.tool_dispatch_count == 1
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE id != 42").fetchone()[0] == 1
        assert client.task_snapshot(42)["claim_fence"] == 1 and client.read(42).leased
        assert session.worker_task_binding is binding
    finally:
        binding.return_lease(); conn.close()
