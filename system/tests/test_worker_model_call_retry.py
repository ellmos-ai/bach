"""A cloud retry keeps its native task/lease and never repeats earlier tools."""
import asyncio
import copy
import json
import math
import sqlite3
import threading

import httpx
import pytest

from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.llm.backend_errors import BackendRequestFailure, cloud_call_retry_delay
from hub._services.llm.model_backend import OllamaBackend, OpenRouterBackend


def _error(provider="ollama", **changes):
    detail = {"provider": provider, "kind": "rate_limited" if provider == "ollama" else "http_error",
              "status_code": 429, "quota_exceeded": False}
    if provider == "openrouter":
        detail["error_type"] = "HTTPStatusError"
    return {**detail, **changes}


@pytest.mark.parametrize("provider", ["ollama", "openrouter"])
def test_backoff_limit_and_retry_after(provider):
    assert [cloud_call_retry_delay(_error(provider), retries=i, waited_seconds=0)
            for i in range(4)] == [60, 120, 240, None]
    assert cloud_call_retry_delay(_error(provider, retry_after_seconds=700), retries=0, waited_seconds=200) == 700
    assert cloud_call_retry_delay(_error(provider, retry_after_seconds=701), retries=0, waited_seconds=200) is None
    for value in (True, -1, math.nan, math.inf):
        assert cloud_call_retry_delay(_error(provider), retries=0, waited_seconds=value) is None
    assert cloud_call_retry_delay(_error(provider, status_code=503), retries=0, waited_seconds=0) is None
    assert cloud_call_retry_delay(_error("ollama", kind="quota_exceeded", quota_exceeded=True), retries=0, waited_seconds=0) is None


def test_openrouter_retry_after_is_whitelisted_and_redacted():
    response = httpx.Response(429, request=httpx.Request("POST", "https://private.invalid/SECRET"),
                              headers={"Retry-After": "123", "Authorization": "SECRET"}, text="SECRET")
    error = BackendRequestFailure.from_httpx(httpx.HTTPStatusError("SECRET", request=response.request, response=response), provider="openrouter")
    assert error.backend_error["retry_after_seconds"] == 123
    assert "SECRET" not in str(error) + json.dumps(error.backend_error)


class Binding:
    def __init__(self):
        self.active = True

    def assert_active(self):
        if not self.active:
            raise RuntimeError("inactive")

    def task_snapshot(self):
        return {"assigned_slot": "", "required_model": ""}


def _runtime(monkeypatch, *, provider="ollama"):
    backend = OllamaBackend(default_model="glm-5.3:cloud") if provider == "ollama" else OpenRouterBackend(default_model="fixture:free")
    model = backend.get_default_model()
    runtime = ChatRuntime(backend)
    session = runtime.get_session("worker-fixture")
    profile = {"id": session.chat_id, "enabled": True, "type": "continuous", "status": "running",
               "backend": "ollama-cloud" if provider == "ollama" else provider, "model": model}
    session.worker_task_binding = Binding()
    session.require_task_binding = True
    session.worker_slot_reader = lambda: dict(profile)
    return runtime, session, backend, model, profile


@pytest.mark.parametrize("provider", ["ollama", "openrouter"])
def test_same_request_succeeds_after_rate_limit(monkeypatch, provider):
    runtime, session, backend, model, profile = _runtime(monkeypatch, provider=provider)
    messages = [{"role": "tool", "content": "already committed tool result"}]
    calls, waits = [], []
    async def call(actual, *args, **kwargs):
        calls.append((actual, copy.deepcopy(args), copy.deepcopy(kwargs), session.worker_task_binding))
        if len(calls) == 1:
            if provider == "openrouter":
                raise BackendRequestFailure(_error(provider, retry_after_seconds=70))
            return {"error": "limit", "backend_error": _error(provider, retry_after_seconds=70)}
        return {"content": "continued"}
    async def wait(seconds, *, check_active):
        check_active()
        waits.append(seconds)
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    result = asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, messages))
    assert result == {"content": "continued"} and waits == [70]
    assert calls[0] == calls[1] and messages == [{"role": "tool", "content": "already committed tool result"}]


@pytest.mark.parametrize("change", ["stop", "binding", "profile", "session"])
def test_guard_loss_during_backoff_prevents_dispatch(monkeypatch, change):
    runtime, session, backend, model, profile = _runtime(monkeypatch)
    calls = []
    async def call(*args, **kwargs):
        calls.append(1)
        return {"error": "limit", "backend_error": _error()}
    async def wait(seconds, *, check_active):
        if change == "stop":
            session.worker_task_binding.active = False
        elif change == "binding":
            session.worker_task_binding = Binding()
        elif change == "profile":
            profile["model"] = "other:cloud"
        else:
            monkeypatch.setattr(runtime, "get_session", lambda _: object())
        check_active()
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    with pytest.raises(RuntimeError):
        asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, []))
    assert calls == [1]


@pytest.mark.parametrize("partial", [{"content": "partial"}, {"thinking": "partial"},
                                    {"tool_calls": [{}]}, {"raw_message": {"content": "partial"}}])
def test_partial_output_never_retried(monkeypatch, partial):
    runtime, session, backend, model, _ = _runtime(monkeypatch)
    calls = []
    result = {"error": "limit", "backend_error": _error(), **partial}
    async def call(*args, **kwargs):
        calls.append(1)
        return result
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    assert asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, [])) is result
    assert calls == [1]


def test_exhaustion_does_not_allow_controller_task_restart(monkeypatch):
    runtime, session, backend, model, _ = _runtime(monkeypatch)
    waits, calls = [], []
    async def call(*args, **kwargs):
        calls.append(1)
        return {"error": "limit", "backend_error": _error()}
    async def wait(seconds, *, check_active):
        check_active()
        waits.append(seconds)
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", call)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    result = asyncio.run(runtime._chat_with_cloud_call_retry(session, backend, model, []))
    from hub._services.chat.chat_runtime import FailedAnswer
    from hub._services.chat.telegram_chat import _worker_backend_retry_delay
    answer = FailedAnswer("limit", backend_error=result["backend_error"], reason_code=result["reason_code"])
    assert len(calls) == 4 and waits == [60, 120, 240]
    assert answer.reason_code == "cloud_call_retry_exhausted"
    assert _worker_backend_retry_delay({"type": "continuous"}, answer.backend_error, model=model,
        retries=0, waited_seconds=0, reason_code=answer.reason_code) is None


def test_actual_tool_write_occurs_once_when_model_resumes(tmp_path, monkeypatch):
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
    binding = WorkerLeaseBinding.acquire(client, 42, worker_id="fixture@fixture", host="fixture", generation="a" * 32,
                                        is_current=lambda: True, stop_event=threading.Event())
    backend = OllamaBackend(default_model="glm-5.3:cloud")
    runtime = ChatRuntime(backend, session_store=_persistent_session_store(tmp_path))
    monkeypatch.setattr(runtime, "_get_bach_context", lambda _: "")
    monkeypatch.setattr(runtime, "_get_memory_hook_context", lambda *a: "")
    session = runtime.get_session("worker-fixture")
    session.worker_task_binding, session.require_task_binding = binding, True
    session.worker_slot_reader = lambda: {"id": session.chat_id, "enabled": True, "type": "continuous",
        "status": "running", "backend": "ollama-cloud", "model": "glm-5.3:cloud"}
    calls, waits = [], []
    real_client = httpx.AsyncClient
    def reply(request):
        calls.append(request)
        if len(calls) == 1:
            message = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "task_manage",
                "arguments": {"action": "add", "title": "Only once"}}}]}
        elif len(calls) == 2:
            return httpx.Response(429, json={"error": "rate limit"})
        else:
            message = {"role": "assistant", "content": "Continued after existing tool result"}
        return httpx.Response(200, text=json.dumps({"message": message, "done": True}) + "\n")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    async def wait(seconds, *, check_active):
        check_active()
        assert client.read(42).leased and binding.generation == "a" * 32
        waits.append(seconds)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait)
    try:
        answer = asyncio.run(runtime.process("Create one child then report", session.chat_id,
                                            backend=backend, model="glm-5.3:cloud", work_priority="background"))
        assert answer == "Continued after existing tool result"
        assert waits == [60] and len(calls) == 3 and calls[1].content == calls[2].content
        assert binding.tool_dispatch_count == 1
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE id != 42").fetchone()[0] == 1
        assert client.task_snapshot(42)["claim_fence"] == 1 and client.read(42).leased
        assert session.worker_task_binding is binding
    finally:
        binding.return_lease()
        conn.close()
