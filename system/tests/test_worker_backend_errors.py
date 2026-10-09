"""Provider failures survive native cleanup without exposing provider payloads."""
import asyncio
import importlib
import json
from datetime import datetime, timezone

import httpx
import pytest

from hub._services.chat import slots_config as slots
from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer
from hub._services.llm.model_backend import OllamaBackend
from gui.api.worker_status_adapter import _project_worker


def run_http(monkeypatch, payload, *, status=429, headers=None):
    real_client = httpx.AsyncClient
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(status, json=payload, headers=headers)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(reply), **kw))
    backend = OllamaBackend(default_model="glm-5.3:cloud")
    result = asyncio.run(backend.chat([{"role": "user", "content": "fixture"}]))
    assert len(calls) == 1
    assert json.loads(calls[0].content)["model"] == "glm-5.3:cloud"
    return result


def test_monthly_quota_is_structured_and_secret_free(monkeypatch):
    result = run_http(monkeypatch, {"error": "monthly usage limit reached PRIVATE_BODY"})
    assert result["backend_error"]["kind"] == "quota_exceeded"
    assert result["backend_error"]["status_code"] == 429
    assert result["backend_error"]["quota_exceeded"] is True
    assert result["backend_error"]["quota_period"] == "month"
    assert "retry_after_seconds" not in result["backend_error"]
    assert "Monatskontingent" in result["error"]
    assert "PRIVATE_BODY" not in json.dumps(result)


@pytest.mark.parametrize("value, expected", [("120", 120), ("0", 0),
    ("invalid PRIVATE_HEADER", None), ("-1", None), ("1.5", None)])
def test_only_observed_valid_retry_after_is_projected(monkeypatch, value, expected):
    result = run_http(monkeypatch, {"error": "rate limit"}, headers={"Retry-After": value})
    detail = result["backend_error"]
    assert detail["kind"] == "rate_limited" and detail["quota_exceeded"] is False
    assert detail.get("retry_after_seconds") == expected
    assert "quota_period" not in detail and "PRIVATE_HEADER" not in json.dumps(result)


def test_retry_after_http_date_uses_actual_header_and_reference_time():
    from hub._services.llm.backend_errors import parse_retry_after
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert parse_retry_after("Fri, 09 Oct 2026 12:02:00 GMT", now=now) == 120
    assert parse_retry_after("Fri, 09 Oct 2026 11:59:00 GMT", now=now) == 0
    assert parse_retry_after("Fri, 09 Oct 2026 12:02:00", now=now) is None


def test_arbitrary_http_body_is_not_shown_or_assumed_monthly(monkeypatch):
    result = run_http(monkeypatch, {"error": "SECRET_KEY SECRET_URL"}, status=503)
    assert result["backend_error"]["kind"] == "http_error"
    assert result["backend_error"]["status_code"] == 503
    assert result["backend_error"]["quota_exceeded"] is False
    assert "quota_period" not in result["backend_error"]
    assert "SECRET" not in json.dumps(result)


def test_failed_answer_preserves_allowlisted_error_across_store_and_restore():
    detail = {"provider": "ollama", "kind": "quota_exceeded", "status_code": 429,
        "quota_exceeded": True, "quota_period": "month", "api_key": "PRIVATE"}
    answer = FailedAnswer("Backend-Fehler: Monatskontingent erreicht", backend_error=detail)
    messages = [{"role": "assistant", "content": answer, "answer_status": "failed"}]
    stored = json.loads(json.dumps(ChatRuntime._messages_for_store(messages)))
    assert "PRIVATE" not in json.dumps(stored)
    restored = ChatRuntime._restore_message_status(stored)
    assert restored[0]["content"].backend_error["quota_period"] == "month"
    assert "backend_error" not in ChatRuntime._messages_for_backend(restored)[0]


@pytest.mark.parametrize("core", [True, False])
def test_assignment_cleanup_preserves_error_and_records_end(tmp_path, core):
    heart = importlib.import_module("hub._services.agents_heart")
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    ident = "buddha_always_on" if core else slots.add_worker({"name": "Quota"}, path)["id"]
    assignment = heart.begin_assignment(role_id="task_worker", mode="safe",
        agent_instance_id="worker-fixture", backend_id="ollama-cloud", model_id="glm-5.3:cloud",
        slot_id=ident, task_id=42, session_id=ident, initiated_by="fixture", path=path)
    slots.update_slot(ident, {"status": "error", "current_activity": "Monatskontingent erreicht"}, path)
    heart.finish_assignment(assignment, status="error", result="runtime_error", path=path)
    current = slots.get_slot(ident, path) if core else slots.get_worker_slot(ident, path)
    assert current["current_activity"] == "Monatskontingent erreicht"
    end = slots.get_activity_history(path=path)[0]
    assert end["event"] == "assignment_ended" and end["assignment_id"] == assignment.assignment_id
    assert end["task_id"] == 42 and end["status"] == "error"


def test_worker_projection_regenerates_error_text_and_drops_provider_secrets():
    detail = {"provider": "ollama", "kind": "quota_exceeded", "status_code": 429,
        "quota_exceeded": True, "quota_period": "month", "retry_after_seconds": 60,
        "message": "PRIVATE_PROVIDER_BODY", "authorization": "PRIVATE_TOKEN"}
    result = _project_worker({"id": "worker-1", "status": "error", "backend_error": detail})
    assert result["backend_error"]["retry_after_seconds"] == 60
    assert "Monatskontingent" in result["backend_error"]["message"]
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("detail", [{"kind": "quota_exceeded", "quota_exceeded": "true"},
    {"provider": "ollama", "kind": "unknown", "status_code": 429},
    {"provider": "ollama", "kind": "http_error", "status_code": True},
    {"provider": "ollama", "kind": [], "quota_exceeded": False}])
def test_malformed_error_metadata_is_not_projected(detail):
    result = _project_worker({"id": "worker-1", "backend_error": detail})
    assert "backend_error" not in result


@pytest.mark.parametrize("managed", [True, False])
def test_both_runtime_paths_preserve_safe_failure_metadata(managed):
    from hub._services.llm.backend_errors import classify_ollama_error
    class Backend:
        manages_own_tools = managed
        def get_default_model(self):
            return "fixture-model"
        async def chat(self, messages, **kw):
            detail = classify_ollama_error({"error": "monthly usage limit reached"}, status_code=429)
            return {"content": "", "error": detail["message"], "backend_error": detail}
    runtime = ChatRuntime(Backend())
    answer = asyncio.run(runtime.process("fixture", "fixture-quota-chat"))
    assert isinstance(answer, FailedAnswer) and answer.backend_error["quota_period"] == "month"
    stored = ChatRuntime._messages_for_store(runtime.get_session("fixture-quota-chat").messages)
    assert stored[-1]["backend_error"]["status_code"] == 429


@pytest.mark.parametrize("core", [True, False])
def test_native_thread_returns_real_lease_and_preserves_quota_after_cleanup(tmp_path, monkeypatch, core):
    import sqlite3
    from hub._services import task_lease_client as client_module
    from hub._services.task_lease_client import TaskLeaseClient
    from hub._services.chat.chat_runtime import ChatSession, _managed_backend_answer
    from system.tests.test_task_lease_client import _init_db
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    ident = "buddha_always_on" if core else slots.add_worker({"name": "Quota", "type": "once"}, path)["id"]
    slots.update_slot(ident, {"backend": "ollama", "model": "glm-5.3:cloud", "think": True,
        "enabled": True, "mode": "safe", "task_id": 42, "backend_error": {"old": "stale"}}, path)
    for registry in ("_WORKER_CONTROLS", "_WORKER_EXECUTIONS", "_ACTIVE_WORKER_THREADS"):
        monkeypatch.setattr(control, registry, {})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(client_module, "get_lead_config", lambda: {"mode": "isolated"})
    database = tmp_path / "tasks.db"
    conn = sqlite3.connect(database, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.execute("INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
        "VALUES (42,'Native quota fixture','pending','P1','INBOX','BACH',?)", (ident,))
    conn.commit()
    monkeypatch.setattr(control, "_native_task_client", lambda: TaskLeaseClient(conn=conn))
    session = ChatSession()
    session.chat_id = ident
    monkeypatch.setattr(control.runtime, "get_session", lambda _: session)
    calls = []
    backend = OllamaBackend(default_model="glm-5.3:cloud")
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (backend, "glm-5.3:cloud"))
    real_client = httpx.AsyncClient
    def reply(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "monthly usage limit reached PRIVATE_PROVIDER_BODY"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(reply), **kw))
    async def process(*a, **kw):
        binding = session.worker_task_binding
        assert binding.task_id == 42 and not binding.closed
        assert slots.get_slot(ident, path).get("backend_error") is None
        return _managed_backend_answer(await backend.chat([{"role": "user", "content": "fixture"}]))
    monkeypatch.setattr(control.runtime, "process", process)
    thread = None
    try:
        response, code = control.start_worker_execution(ident)
        assert code == 200 and response["ok"] is True
        thread = control._WORKER_EXECUTIONS[ident].thread
        thread.join(5)
        assert not thread.is_alive() and len(calls) == 1
        current = slots.get_slot(ident, path)
        assert current["status"] == "error" and "Monatskontingent" in current["current_activity"]
        assert current["backend_error"]["status_code"] == 429
        task = dict(conn.execute("SELECT * FROM tasks WHERE id=42").fetchone())
        assert task["status"] == "pending" and task["claim_salt_ref"] is None
        events = slots.get_activity_history(path=path)
        assert any(e.get("event") == "assignment_ended" and e.get("task_id") == 42
            and e.get("status") == "error" for e in events)
        public = _project_worker(control._worker_handoff_snapshot(current))
        assert public["worker_active"] is False and public["running"] is False
        assert public["backend_error"]["quota_period"] == "month"
        assert "PRIVATE_PROVIDER_BODY" not in json.dumps(events + [public])
    finally:
        if thread is not None and thread.is_alive():
            control._WORKER_EXECUTIONS[ident].stop_event.set()
            thread.join(5)
        conn.close()


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_other_statuses_do_not_invent_monthly_quota(monkeypatch, status):
    result = run_http(monkeypatch, {"error": "monthly usage limit reached PRIVATE"}, status=status)
    assert result["backend_error"]["kind"] == "http_error"
    assert result["backend_error"]["status_code"] == status
    assert "quota_period" not in result["backend_error"] and "PRIVATE" not in json.dumps(result)


def test_oversized_error_body_is_unknown_and_not_copied(monkeypatch):
    result = run_http(monkeypatch, {"error": "monthly usage limit reached " + "PRIVATE" * 5000})
    assert result["backend_error"]["kind"] == "rate_limited"
    assert "quota_period" not in result["backend_error"] and "PRIVATE" not in json.dumps(result)
