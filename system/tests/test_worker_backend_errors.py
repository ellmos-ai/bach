"""Provider failures survive native cleanup without exposing provider payloads."""
import asyncio
import importlib
import json
import sqlite3
from datetime import datetime, timezone

import httpx
import pytest

from hub._services.chat import slots_config as slots
from hub._services.chat.chat_runtime import ChatRuntime, FailedAnswer
from hub._services.chat.session_store import SQLiteChatSessionStore
from hub._services.llm.model_backend import OllamaBackend
from gui.api.worker_status_adapter import _project_worker


def _persistent_session_store(tmp_path):
    session_db_path = tmp_path / "worker-session-snapshots.db"
    with sqlite3.connect(session_db_path) as session_conn:
        session_conn.execute("""
            CREATE TABLE session_snapshots (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                snapshot_data TEXT,
                name TEXT,
                created_at TEXT
            )
        """)
    return SQLiteChatSessionStore(session_db_path)


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
    backend = OllamaBackend(default_model="glm-5.3:cloud")
    runtime = ChatRuntime(backend, session_store=_persistent_session_store(tmp_path))
    monkeypatch.setattr(control, "runtime", runtime)
    session = ChatSession()
    session.chat_id = ident
    monkeypatch.setattr(runtime, "get_session", lambda _: session)
    calls, quota_waits = [], []
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
    monkeypatch.setattr(runtime, "process", process)
    def wait_quota(worker, seconds):
        assert core and seconds == 60
        quota_waits.append(seconds)
        assert worker.task_binding is None and worker.lease_supervisor is None
        assert session.worker_task_binding is None
        native = control._native_task_client()
        assert not native.read(42).leased
        assert native.worker_leases(worker.lease_worker_id)["leases"] == []
        current = slots.get_slot(ident, path)
        assert current["backend_error"]["quota_period"] == "month"
        public = _project_worker(control._worker_handoff_snapshot(current))
        assert public["worker_active"] and not public["running"]
        assert public["backend_error"]["quota_period"] == "month"
        _, _, receipt, status = control._request_worker_revocation(
            ident, current, expected_execution={
                "service_instance": control._WORKER_SERVICE_INSTANCE,
                "start_request_id": worker.start_request_id,
                "generation": worker.generation})
        assert status == 409 and receipt["outcome"] == "revocation-pending"
        return False
    monkeypatch.setattr(control, "_wait_worker_backend_retry", wait_quota)
    thread = None
    try:
        response, code = control.start_worker_execution(ident)
        assert code == 200 and response["ok"] is True
        thread = control._WORKER_EXECUTIONS[ident].thread
        thread.join(5)
        assert not thread.is_alive() and len(calls) == 1
        current = slots.get_slot(ident, path)
        if core:
            assert quota_waits == [60] and current["status"] == "paused"
            receipt = control._WORKER_EXECUTIONS[ident].receipt
            assert receipt["confirmed"] and receipt["status_persisted"]
            assert control.worker_execution_receipt(ident)["terminal"]
        else:
            assert quota_waits == []
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
        if core:
            agent = next(a for a in control._system_slots_snapshot()["agents"] if a["id"] == ident)
            assert agent["backend_error"]["quota_period"] == "month"
            assert agent["backend_error"]["status_code"] == 429
            assert agent["status"] == "paused" and agent["worker_active"] is False
            assert "PRIVATE_PROVIDER_BODY" not in json.dumps(agent)
    finally:
        if thread is not None and thread.is_alive():
            control._WORKER_EXECUTIONS[ident].stop_event.set()
            thread.join(5)
        conn.close()


@pytest.mark.parametrize("model, kind, worker_type, retries, waited, header, expected", [
    ("glm-5.3:cloud", "rate_limited", "continuous", 0, 0, None, 60),
    ("glm-5.3:cloud", "rate_limited", "persistent", 1, 60, 0, 120),
    ("glm-5.3:cloud", "rate_limited", "continuous", 0, 0, 180, 180),
    ("glm-5.3:cloud", "rate_limited", "continuous", 2, 660, 240, 240),
    ("glm-5.3:cloud", "rate_limited", "continuous", 0, 0, 901, 901),
    ("glm-5.3:cloud", "rate_limited", "continuous", 2, 661, 240, 240),
    ("glm-5.3:cloud", "rate_limited", "continuous", 3, 420, None, 480),
    ("glm-5.3:cloud", "quota_exceeded", "continuous", 0, 0, 60, 60),
    ("glm-5.3:cloud", "http_error", "continuous", 0, 0, 60, None),
    ("glm-5.3:cloud", "rate_limited", "once", 0, 0, 60, None),
    ("qwen3.5:4b", "rate_limited", "persistent", 0, 0, 60, None),
])
def test_cloud_retry_policy_limits_frequency_and_preserves_observed_header(
        model, kind, worker_type, retries, waited, header, expected):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    detail = {"provider": "ollama", "kind": kind, "status_code": 429 if kind != "http_error" else 401,
              "quota_exceeded": kind == "quota_exceeded"}
    if header is not None:
        detail["retry_after_seconds"] = header
    assert control._worker_backend_retry_delay({"backend": "ollama", "type": worker_type}, detail, model=model,
        retries=retries, waited_seconds=waited) == expected
    assert control._worker_backend_retry_delay({"type": worker_type}, detail, model=model,
        retries=retries, waited_seconds=waited) is None


@pytest.mark.parametrize("interruption", ["stop", "disabled", "paused", "missing", "expired", "replaced"])
def test_retry_wait_observes_stop_policy_ttl_and_generation(monkeypatch, interruption):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    slot = {"id": "retry-fixture", "enabled": True, "status": "running"}
    worker = control._WorkerControl(slot["id"], slot_policy_reader=lambda: slot)
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {slot["id"]: worker})
    writes = []
    monkeypatch.setattr(control, "_update_worker_slot", lambda _, changes: writes.append(changes))
    if interruption == "stop":
        worker.stop_event.set()
    elif interruption == "disabled":
        slot["enabled"] = False
    elif interruption == "paused":
        slot["status"] = "paused"
    elif interruption == "missing":
        worker.slot_policy_reader = lambda: None
    elif interruption == "expired":
        slot["expires_at"] = "2000-01-01T00:00:00+00:00"
    else:
        control._WORKER_CONTROLS[slot["id"]] = control._WorkerControl(slot["id"])
    assert control._wait_worker_backend_retry(worker, 60) is False
    if interruption in {"stop", "paused", "missing", "replaced"}:
        assert not writes
    else:
        assert writes[-1]["status"] == ("idle" if interruption == "disabled" else "expired")


@pytest.mark.parametrize("scenario", ["recover", "connection_recover", "sustained_rate_limit", "stop", "return_denied", "foreign_claim", "quota_after_retry",
    "unknown_none", "unknown_false", "unknown_true", "unknown_negative", "unknown_string", "unknown_float"])
def test_native_cloud_retry_releases_before_wait_and_reclaims_fresh_fence(tmp_path, monkeypatch, scenario):
    import sqlite3
    from hub._services import task_lease_client as client_module
    from hub._services.task_lease_client import TaskLeaseClient
    from hub._services.chat.chat_runtime import ChatSession, _managed_backend_answer
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from system.tests.test_task_lease_client import _init_db
    from hub._services.llm.model_backend import OpenRouterBackend
    connection = scenario == "connection_recover"
    model = "openrouter/free" if connection else "glm-5.3:cloud"
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    ident = slots.add_worker({"name": "Cloud retry fixture", "type": "continuous"}, path)["id"]
    slots.update_slot(ident, {"backend": "openrouter" if connection else "ollama", "model": model, "enabled": True,
        "mode": "safe", "task_id": 42, "pause_after": 0}, path)
    for registry in ("_WORKER_CONTROLS", "_WORKER_EXECUTIONS", "_ACTIVE_WORKER_THREADS"):
        monkeypatch.setattr(control, registry, {})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(client_module, "get_lead_config", lambda: {"mode": "isolated"})
    conn = sqlite3.connect(tmp_path / "tasks.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.execute("INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
        "VALUES (42,'Cloud retry fixture','pending','P1','INBOX','BACH',?)", (ident,))
    conn.commit()
    client = TaskLeaseClient(conn=conn)
    monkeypatch.setattr(control, "_native_task_client", lambda: client)
    backend = (OpenRouterBackend(api_key="fixture", default_model=model)
               if connection else OllamaBackend(default_model=model))
    runtime = ChatRuntime(backend, session_store=_persistent_session_store(tmp_path))
    monkeypatch.setattr(control, "runtime", runtime)
    session = ChatSession()
    session.chat_id = ident
    monkeypatch.setattr(runtime, "get_session", lambda _: session)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (backend, model))
    real_client = httpx.AsyncClient
    calls, fences, waits, inner_waits = [], [], [], []
    async def inner_wait(seconds, *, check_active):
        check_active()
        assert client.read(42).leased
        inner_waits.append(seconds)
    if connection:
        monkeypatch.setattr(runtime, "_wait_model_call_retry", inner_wait)
    def reply(request):
        calls.append(request)
        if connection:
            if len(calls) <= 4:
                raise httpx.ConnectError("PRIVATE_PROVIDER_BODY", request=request)
            return httpx.Response(200, json={"choices": [{
                "message": {"role": "assistant", "content": "Healthy fixture"}}]})
        if len(calls) > 1 and scenario == "recover":
            return httpx.Response(200, text=json.dumps({"message": {"content": "Healthy fixture"}, "done": True}) + "\n")
        payload = "monthly usage limit reached" if scenario == "quota_after_retry" and len(calls) > 1 else "rate limit"
        return httpx.Response(429, json={"error": payload + " PRIVATE_PROVIDER_BODY"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(reply), **kw))
    async def process(*a, **kw):
        binding = session.worker_task_binding
        assert binding.task_id == 42 and not binding.closed
        fences.append(binding._ack.fence)
        messages = [{"role": "user", "content": "fixture"}]
        if connection:
            result = await runtime._chat_with_cloud_call_retry(session, backend, model, messages)
            answer = (FailedAnswer(result["error"], backend_error=result["backend_error"],
                                   reason_code=result["reason_code"])
                      if result.get("error") else _managed_backend_answer(result))
        else:
            answer = _managed_backend_answer(await backend.chat(messages))
        if not FailedAnswer.looks_like(answer):
            binding.execute_task_manage({"action": "submit_result", "task_id": 42, "result": str(answer)})
        return answer
    monkeypatch.setattr(runtime, "process", process)
    monkeypatch.setattr(control, "_wait_worker_cooldown", lambda *a, **kw: False)
    foreign = []
    acquire_calls = []
    native_acquire = control._acquire_worker_task
    def acquire(worker, *args):
        binding = native_acquire(worker, *args)
        acquire_calls.append(binding is not None)
        if foreign:
            assert binding is None and client.read(42, lease_id=foreign[0].lease_id).own is True
            worker.stop_event.set()
        return binding
    monkeypatch.setattr(control, "_acquire_worker_task", acquire)
    def wait(worker, seconds):
        waits.append(seconds)
        assert worker.task_binding is None and worker.lease_supervisor is None
        assert session.worker_task_binding is None
        assert client.read(42).leased is False
        snapshot = control._worker_handoff_snapshot(slots.get_slot(ident, path))
        assert snapshot["active_task_id"] is None
        public = _project_worker(snapshot)
        assert public["worker_active"] is True and public["running"] is False
        assert public.get("active_task_id") is None
        if connection:
            assert public["backend_error"]["kind"] == "connection_error"
            assert fences == [1] and inner_waits == [5, 10, 20]
            assert len(calls) == 4
        else:
            assert public["backend_error"]["status_code"] == 429
        if (scenario == "stop" or scenario.startswith("unknown_")
                or (scenario == "sustained_rate_limit" and len(waits) == 5)
                or (scenario == "quota_after_retry" and len(waits) == 2)):
            worker.stop_event.set()
            return False
        if scenario == "foreign_claim":
            foreign.append(client.acquire(42, worker_id="foreign-fixture@fixture", host="fixture",
                                          task_version=client.task_snapshot(42)["task_version"]))
        return True
    monkeypatch.setattr(control, "_wait_worker_backend_retry", wait)
    if scenario == "return_denied":
        monkeypatch.setattr(WorkerLeaseBinding, "return_lease", lambda _: False)
    if scenario.startswith("unknown_"):
        invalid = {"unknown_none": None, "unknown_false": False, "unknown_true": True,
                   "unknown_negative": -1, "unknown_string": "0", "unknown_float": 0.0}[scenario]
        monkeypatch.setattr(WorkerLeaseBinding, "tool_dispatch_count", property(lambda _: invalid))
    thread = None
    try:
        response, code = control.start_worker_execution(ident)
        assert code == 200 and response["ok"] is True
        execution = control._WORKER_EXECUTIONS[ident]
        thread = execution.thread
        thread.join(5)
        assert not thread.is_alive()
        assert all(json.loads(request.content)["model"] == model for request in calls)
        task = dict(conn.execute("SELECT * FROM tasks WHERE id=42").fetchone())
        current = slots.get_slot(ident, path)
        if scenario in {"recover", "connection_recover"}:
            assert len(calls) == (5 if connection else 2)
            assert waits == [60] and fences == [1, 2]
            if connection:
                assert inner_waits == [5, 10, 20]
                events = slots.get_activity_history(path=path)
                assert any(e.get("event") == "assignment_ended"
                           and e.get("reason") == "temporary_connection_error" for e in events)
            assert task["status"] == "review" and task["claim_salt_ref"] is None
            assert current.get("backend_error") is None
            assert execution.task_result_bindings[42].submitted_result["accepted"] is False
        elif scenario == "sustained_rate_limit":
            assert len(calls) == 5 and waits == [60, 120, 240, 480, 900]
            assert fences == [1, 2, 3, 4, 5] and execution.stop_event.is_set()
            assert execution.start_error is None
            assert task["status"] == "pending" and task["claim_salt_ref"] is None
        elif scenario == "quota_after_retry":
            assert len(calls) == 2 and waits == [60, 120]
            assert execution.stop_event.is_set() and execution.start_error is None
            assert current["backend_error"]["quota_period"] == "month"
            assert task["status"] == "pending" and task["claim_salt_ref"] is None
        elif scenario == "return_denied":
            assert len(calls) == 1 and waits == [] and execution.start_error == "cleanup_error"
            assert client.read(42).leased is True
        elif scenario == "foreign_claim":
            assert len(calls) == 1 and waits == [60]
            assert client.read(42, lease_id=foreign[0].lease_id).own is True
            assert acquire_calls == [True, False]
        elif scenario.startswith("unknown_"):
            # Dispatch telemetry does not turn an open return into quarantine.
            # The supervisor/Return ACK still has to settle before this wait.
            assert len(calls) == 1 and waits == [60]
            assert task["status"] == "pending" and task["claim_salt_ref"] is None
            assert execution.stop_event.is_set() and execution.start_error is None
        else:
            assert len(calls) == 1 and waits == [60] and task["status"] == "pending"
            assert task["claim_salt_ref"] is None
            assert execution.stop_event.is_set() and execution.start_error is None
        assert "PRIVATE_PROVIDER_BODY" not in json.dumps(slots.get_activity_history(path=path))
    finally:
        if thread is not None and thread.is_alive():
            control._WORKER_EXECUTIONS[ident].stop_event.set()
            thread.join(5)
        conn.close()


@pytest.mark.parametrize("action", ["add", "detail", "invalid", "list_directory"])
@pytest.mark.parametrize("previous_block", [False, True])
@pytest.mark.parametrize("dispatch_path", ["runtime", "bridge"])
@pytest.mark.parametrize("backend_failure", ["rate_limit", "monthly_quota", "server_error"])
def test_real_tool_loop_returns_open_work_without_replaying_dispatch(tmp_path, monkeypatch, action, previous_block, dispatch_path, backend_failure):
    """Use real process/dispatcher/TaskDB, not a simulated runtime.process."""
    import sqlite3
    from hub._services import task_lease_client as client_module
    from hub._services.task_lease_client import TaskLeaseClient
    from system.tests.test_task_lease_client import _init_db
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    ident = slots.add_worker({"name": "Real retry fixture", "type": "continuous"}, path)["id"]
    slots.update_slot(ident, {"backend": "ollama", "model": "glm-5.3:cloud", "enabled": True,
        "mode": "safe", "task_id": 42, "pause_after": 0, "max_tool_rounds": 5}, path)
    for registry in ("_WORKER_CONTROLS", "_WORKER_EXECUTIONS", "_ACTIVE_WORKER_THREADS"):
        monkeypatch.setattr(control, registry, {})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(client_module, "get_lead_config", lambda: {"mode": "isolated"})
    conn = sqlite3.connect(tmp_path / "tasks.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.execute("INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
        "VALUES (42,'Real retry fixture','pending','P1','INBOX','BACH',?)", (ident,))
    conn.commit()
    client = TaskLeaseClient(conn=conn)
    monkeypatch.setattr(control, "_native_task_client", lambda: client)
    bindings = []
    acquire = control._acquire_worker_task
    def acquire_record(*args, **kwargs):
        binding = acquire(*args, **kwargs)
        if binding is not None:
            bindings.append(binding)
        return binding
    monkeypatch.setattr(control, "_acquire_worker_task", acquire_record)
    backend = OllamaBackend(default_model="glm-5.3:cloud")
    runtime = ChatRuntime(
        backend,
        session_store=_persistent_session_store(tmp_path),
    )
    # The lean lease-client fixture omits creation timestamps, which the real
    # decomposition tool needs when it creates a child task.
    conn.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    # Isolate unrelated context/hook providers; retain actual tool dispatch.
    monkeypatch.setattr(runtime, "_get_bach_context", lambda _: "")
    monkeypatch.setattr(runtime, "_get_memory_hook_context", lambda *a: "")
    monkeypatch.setattr(control, "runtime", runtime)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (backend, "glm-5.3:cloud"))
    monkeypatch.setattr(control, "_wait_worker_cooldown", lambda *a, **kw: True)
    calls, waits = [], []
    arguments = ({"action": "add", "title": "Only one child"} if action == "add"
                 else {"action": action, "task_id": 42})
    tool_name = "task_manage"
    if action == "list_directory":
        tool_name, arguments = "list_directory", {"path": str(tmp_path)}
    real_client = httpx.AsyncClient
    def reply(request):
        calls.append(request)
        if len(calls) == 1:
            if dispatch_path == "runtime":
                payload = {"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": tool_name, "arguments": arguments}}]}, "done": True}
                return httpx.Response(200, text=json.dumps(payload) + "\n")
            # Exercise the real owned HTTP/ACK bridge and provider dispatcher
            # on this same lease. Provider errors are then handled by the real
            # Cloud runtime/controller, without mocking runtime.process.
            from hub._services.chat.worker_tool_bridge import WorkerToolBridge
            from hub._services.chat.worker_tool_client import WorkerToolClient
            with WorkerToolBridge(bindings[-1], mode="safe") as relay:
                bridge_client = WorkerToolClient.from_environment(relay.private_environment())
                bridge_client.call(tool_name, arguments)
        expected_calls = (2 if dispatch_path == "runtime" else 1) + int(previous_block)
        if previous_block and len(calls) == expected_calls - 1:
            return httpx.Response(200, text=json.dumps({"message": {
                "role": "assistant", "content": "Partial work; task remains open"}, "done": True}) + "\n")
        assert len(calls) <= expected_calls + (3 if backend_failure == "rate_limit" else 0), "Unsafe replay reached provider"
        status = 503 if backend_failure == "server_error" else 429
        message = "monthly usage limit reached" if backend_failure == "monthly_quota" else "rate limit"
        return httpx.Response(status, json={"error": message})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(reply), **kw))
    def wait(worker, seconds):
        waits.append(seconds)
        assert seconds == 60 and backend_failure in {"rate_limit", "monthly_quota"}
        assert worker.task_binding is None and worker.lease_supervisor is None
        assert bindings[-1].closed and bindings[-1].tool_dispatch_count == 1
        assert client.worker_leases(worker.lease_worker_id)["leases"] == []
        assert client.task_snapshot(42)["status"] == "pending"
        worker.stop_event.set()
        return False
    monkeypatch.setattr(control, "_wait_worker_backend_retry", wait)
    call_waits = []
    async def wait_call(seconds, *, check_active):
        check_active()
        call_waits.append(seconds)
    monkeypatch.setattr(runtime, "_wait_model_call_retry", wait_call)
    thread = None
    try:
        response, code = control.start_worker_execution(ident)
        assert code == 200 and response["ok"] is True
        execution = control._WORKER_EXECUTIONS[ident]
        thread = execution.thread
        thread.join(8)
        assert not thread.is_alive()
        expected_calls = (2 if dispatch_path == "runtime" else 1) + int(previous_block)
        assert len(calls) == expected_calls + (3 if backend_failure == "rate_limit" else 0)
        assert waits == ([60] if backend_failure != "server_error" else [])
        assert call_waits == ([60, 120, 240] if backend_failure == "rate_limit" else [])
        if backend_failure == "rate_limit":
            # Only the exact rejected model request is repeated. The earlier
            # tool dispatch, including a write, remains a single execution.
            assert len({request.content for request in calls[expected_calls - 1:]}) == 1
        snapshot = client.task_snapshot(42)
        assert snapshot["claim_fence"] == 1 and snapshot["status"] == "pending"
        assert not client.read(42).leased
        children = conn.execute("SELECT COUNT(*) FROM tasks WHERE id != 42").fetchone()[0]
        assert children == (1 if action == "add" else 0)
        current = slots.get_slot(ident, path)
        if backend_failure == "server_error":
            assert current["status"] == "error"
        else:
            assert execution.stop_event.is_set()
        expected_kind = {"server_error": "http_error", "monthly_quota": "quota_exceeded", "rate_limit": "rate_limited"}[backend_failure]
        assert current["backend_error"]["kind"] == expected_kind
        assert bindings[-1].tool_dispatch_count == 1 and bindings[-1].closed
        assert execution.start_error == ("backend_error" if backend_failure == "server_error" else None)
        # A fresh holder may resume the open task. Acquiring it must preserve
        # the earlier child/files and must not execute any provider/tool call.
        import threading
        from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
        second = WorkerLeaseBinding.acquire(client, 42, worker_id="second@fixture", host="fixture",
            generation="b" * 32, is_current=lambda: True, stop_event=threading.Event())
        assert second.task_id == 42 and second._ack.fence == 2
        assert second.task_snapshot()["title"] == snapshot["title"]
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE id != 42").fetchone()[0] == children
        assert len(calls) == expected_calls + (3 if backend_failure == "rate_limit" else 0)
        assert second.return_lease()
        history = conn.execute("SELECT new_value FROM task_history WHERE task_id=42 AND action='lease_release'").fetchall()
        assert len(history) == 2
        assert all(json.loads(row[0])["outcome"] == "return" for row in history)
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


def test_slow_http_error_body_cannot_bypass_total_cap(monkeypatch):
    import time
    from hub._services.llm import model_backend as module
    original_limit = module.limit
    monkeypatch.setattr(module, "limit", lambda key: 0.03 if key == "BACH_LLM_TOTAL_CAP" else original_limit(key))
    class SlowErrorBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error":"'
            # Each chunk is well below read_timeout, but the whole response
            # has no end. The finite total budget must release the worker.
            while True:
                await asyncio.sleep(.01)
                yield b'PRIVATE'
    real_client = httpx.AsyncClient
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(429, stream=SlowErrorBody())
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(reply), **kw))
    started = time.monotonic()
    result = asyncio.run(OllamaBackend(default_model="glm-5.3:cloud").chat(
        [{"role": "user", "content": "fixture"}]))
    assert time.monotonic() - started < 2
    assert len(calls) == 1 and result["backend_error"]["status_code"] == 429
    assert result["backend_error"]["kind"] == "rate_limited"
    assert "PRIVATE" not in json.dumps(result)


def test_bounded_reader_works_without_python311_timeout_api(monkeypatch):
    from hub._services.llm.backend_errors import read_error_payload
    monkeypatch.delattr(asyncio, "timeout", raising=False)
    class Response:
        async def aiter_bytes(self, **kw):
            yield b'{"error":"monthly usage limit reached"}'
    result = asyncio.run(read_error_payload(Response(), timeout_seconds=1))
    assert result == {"error": "monthly usage limit reached"}

@pytest.mark.parametrize(("retries", "waited", "expected"), [
    (0, 0, 60), (1, 60, 120), (2, 180, 240), (3, 420, None), (2, 661, None),
])
def test_always_on_local_reserve_retry_is_consent_and_profile_bound(
        retries, waited, expected):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    slot = {
        **slots.DEFAULT_CORE_SLOTS["buddha_always_on"],
        "type": "continuous", "status": "running", "enabled": True,
        "persistent_opt_in": True, "persistent_opt_in_id": "a" * 32,
    }
    slot["persistent_opt_in_profile_version"] = slots._persistent_core_profile_version(slot)
    code = "local_reserve_reserve_wait_expired"
    assert control._worker_backend_retry_delay(
        slot, None, model=slot["model"], retries=retries, waited_seconds=waited,
        reason_code=code,
    ) == expected

    stale = {**slot, "persistent_opt_in_profile_version": "b" * 64}
    assert control._worker_backend_retry_delay(
        stale, None, model=slot["model"], retries=0, waited_seconds=0, reason_code=code,
    ) is None
    changed = {**slot, "model": "qwen3.5:4b"}
    assert control._worker_backend_retry_delay(
        changed, None, model=slot["model"], retries=0, waited_seconds=0, reason_code=code,
    ) is None
    assert control._worker_backend_retry_delay(
        slot, None, model=slot["model"], retries=0, waited_seconds=0,
        reason_code="local_reserve_budget_exceeds_host",
    ) is None
    new_code = "local_reserve_reserve_wait_lease_return_required"
    assert control._worker_backend_retry_delay(
        slot, None, model=slot["model"], retries=0, waited_seconds=0,
        reason_code=new_code,
    ) is None
    assert control._worker_backend_retry_delay(
        slot, None, model=slot["model"], retries=0, waited_seconds=0,
        reason_code=new_code, pre_effect_verified=True,
    ) == 60
    assert control._worker_backend_retry_delay(
        slot, None, model=slot["model"], retries=3, waited_seconds=420,
        reason_code=new_code, pre_effect_verified=True,
    ) is None


def test_local_reserve_failure_reason_is_redacted_structured_and_persisted():
    from hub._services.chat.local_resource_reserve import LocalReserveError

    answer = FailedAnswer.from_exception(LocalReserveError(
        "Lokale Ressourcenfreigabe: reserve_wait_expired SECRET_PATH"
    ))
    assert answer.reason_code is None
    assert "SECRET_PATH" not in str(answer)
    assert "SECRET_PATH" not in json.dumps(ChatRuntime._messages_for_store([
        {"role": "assistant", "content": answer, "answer_status": "failed"},
    ]))

    answer = FailedAnswer.from_exception(LocalReserveError(
        "Lokale Ressourcenfreigabe: reserve_wait_expired"
    ))
    assert answer.reason_code == "local_reserve_reserve_wait_expired"
    stored = json.loads(json.dumps(ChatRuntime._messages_for_store([
        {"role": "assistant", "content": answer, "answer_status": "failed"},
    ])))
    assert stored[0]["reason_code"] == "local_reserve_reserve_wait_expired"
    restored = ChatRuntime._restore_message_status(stored)
    assert restored[0]["content"].reason_code == "local_reserve_reserve_wait_expired"
    assert "reason_code" not in ChatRuntime._messages_for_backend(restored)[0]
    new_code = "local_reserve_reserve_wait_lease_return_required"
    answer = FailedAnswer.from_exception(LocalReserveError(
        "Lokale Ressourcenfreigabe: reserve_wait_lease_return_required"
    ))
    assert answer.reason_code == new_code
    new_stored = json.loads(json.dumps(ChatRuntime._messages_for_store([
        {"role": "assistant", "content": answer, "answer_status": "failed"},
    ])))
    assert new_stored[0]["reason_code"] == new_code
    assert ChatRuntime._restore_message_status(new_stored)[0]["content"].reason_code == new_code
    assert "reason_code" not in ChatRuntime._messages_for_backend(
        ChatRuntime._restore_message_status(new_stored))[0]
    assert FailedAnswer("safe", reason_code={"unknown": True}).reason_code is None


def test_local_core_reserve_wait_does_not_enter_configured_model_fallback(monkeypatch):
    from hub._services.chat.local_resource_reserve import LocalReserveError

    class Backend:
        name = "ollama"
        manages_own_tools = False
        def get_default_model(self):
            return "qwen3.8:27b-mlx"

    runtime = ChatRuntime(Backend())
    session = type("Session", (), {"chat_id": "buddha_always_on"})()
    monkeypatch.setattr(runtime, "_native_model_fallback_route", lambda *a, **kw: {
        "targets": [
            {"backend": "ollama", "model": "qwen3.8:27b-mlx"},
            {"backend": "ollama", "model": "qwen3.5:4b"},
        ], "index": 0,
    })
    calls = []
    async def reserve_wait(*args, **kwargs):
        calls.append(kwargs.get("model"))
        raise LocalReserveError("Lokale Ressourcenfreigabe: resource_policy_changed")
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", reserve_wait)
    from hub._services.chat import model_sockets
    monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda _target: pytest.fail(
        "Core-Reservefehler darf keinen Fallback aufrufen"
    ))
    with pytest.raises(LocalReserveError):
        asyncio.run(runtime._chat_with_configured_fallbacks(
            session, runtime.backend, "qwen3.8:27b-mlx", [], tools=[], think=False,
        ))
    assert calls == ["qwen3.8:27b-mlx"]


def test_background_process_clears_previous_resolved_model(monkeypatch):
    class Backend:
        name = "fixture-cloud"
        def get_default_model(self):
            return "fixture-cloud-model"

    runtime = ChatRuntime(Backend())
    session = runtime.get_session("buddha_always_on")
    session.resolved_model = "stale-previous-model"
    async def inspect_turn(*args, **kwargs):
        assert session.resolved_model is None
        return "ok"
    monkeypatch.setattr(runtime, "_process_turn", inspect_turn)
    result = asyncio.run(runtime.process(
        "fixture", "buddha_always_on", work_priority="background",
    ))
    assert result == "ok"
    assert session.resolved_model is None


def test_native_always_on_reserve_wait_returns_lease_before_fresh_claim(
        tmp_path, monkeypatch):
    import sqlite3
    import threading
    from datetime import timedelta

    from hub._services.chat.chat_runtime import ChatSession
    from hub._services.chat.local_resource_reserve import LocalReserveError
    from hub._services.task_lease_client import TaskLeaseClient

    from system.tests.test_task_lease_client import _init_db

    control = importlib.import_module("hub._services.chat.telegram_chat")
    real_datetime = datetime
    simulated_clock = {"offset_seconds": 0}
    class SimulatedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz) + timedelta(seconds=simulated_clock["offset_seconds"])
    monkeypatch.setattr(slots, "datetime", SimulatedDateTime)
    monkeypatch.setattr(control, "datetime", SimulatedDateTime)
    worker_id = "buddha_always_on"
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    slots.update_slot(worker_id, {"resolved_model": "stale-controller-model"}, path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    controller_cas_readbacks = []
    original_controller_update = slots.update_persistent_core_controller_state
    def tracked_controller_update(
            expected_profile_version, expected_intent_id, expected_checkpoint,
            checkpoint, expected_recovery_state, recovery_state, **kwargs):
        previous_phase = (expected_recovery_state.get("phase")
                          if isinstance(expected_recovery_state, dict) else None)
        new_phase = recovery_state.get("phase") if isinstance(recovery_state, dict) else None
        if previous_phase == "active" and new_phase == "reserve_wait":
            ack = original_controller_update(
                expected_profile_version, expected_intent_id, expected_checkpoint,
                checkpoint, expected_recovery_state, recovery_state, **kwargs)
            after_ack = slots.load_slots_config(path, strict=True)["slots"][worker_id]
            assert after_ack[slots.PERSISTENT_WORKER_CONTROLLER_CHECKPOINT_FIELD] == checkpoint
            assert after_ack[slots.PERSISTENT_CORE_RECOVERY_FIELD] == recovery_state
            assert ack["checkpoint"] == checkpoint and ack["recovery_state"] == recovery_state
            assert slots._persistent_core_profile_version(after_ack) == expected_profile_version
            controller_cas_readbacks.append("reserve_wait_ack_readback")
            return ack
        if previous_phase == "reserve_wait" and new_phase == "active":
            before_second_cas = slots.load_slots_config(path, strict=True)["slots"][worker_id]
            assert before_second_cas[slots.PERSISTENT_WORKER_CONTROLLER_CHECKPOINT_FIELD] == expected_checkpoint
            assert before_second_cas[slots.PERSISTENT_CORE_RECOVERY_FIELD] == expected_recovery_state
            assert slots._persistent_core_profile_version(before_second_cas) == expected_profile_version
            ack = original_controller_update(
                expected_profile_version, expected_intent_id, expected_checkpoint,
                checkpoint, expected_recovery_state, recovery_state, **kwargs)
            after_second_cas = slots.load_slots_config(path, strict=True)["slots"][worker_id]
            assert after_second_cas[slots.PERSISTENT_WORKER_CONTROLLER_CHECKPOINT_FIELD] == checkpoint
            assert after_second_cas[slots.PERSISTENT_CORE_RECOVERY_FIELD] == recovery_state
            assert ack["checkpoint"] == checkpoint and ack["recovery_state"] == recovery_state
            assert slots._persistent_core_profile_version(after_second_cas) == expected_profile_version
            controller_cas_readbacks.append("active_cas_ack_readback")
            return ack
        return original_controller_update(
            expected_profile_version, expected_intent_id, expected_checkpoint,
            checkpoint, expected_recovery_state, recovery_state, **kwargs)
    monkeypatch.setattr(slots, "update_persistent_core_controller_state", tracked_controller_update)
    def projected_resolved_model():
        agents = slots.core_system_agents_snapshot(path)["agents"]
        return next(agent["resolved_model"] for agent in agents if agent["id"] == worker_id)
    assert projected_resolved_model() == "stale-controller-model"
    before = slots.worker_configuration_snapshot(worker_id, path=path)
    slots.change_worker_configuration(
        worker_id, before["configuration_version"], {"persistent_opt_in": True}, path=path,
    )
    for registry in ("_WORKER_CONTROLS", "_WORKER_EXECUTIONS", "_ACTIVE_WORKER_THREADS"):
        monkeypatch.setattr(control, registry, {})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")

    conn = sqlite3.connect(tmp_path / "tasks.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.execute(
        "INSERT INTO tasks (id,title,status,priority,category,assigned_to,assigned_slot) "
        "VALUES (42,'Always-On reserve fixture','pending','P1','INBOX','BACH',?)",
        (worker_id,),
    )
    conn.commit()
    client = TaskLeaseClient(conn=conn)
    monkeypatch.setattr(control, "_native_task_client", lambda: client)
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    settlement_events = []
    original_return_lease = WorkerLeaseBinding.return_lease
    def tracked_return_lease(binding, *args, **kwargs):
        result = original_return_lease(binding, *args, **kwargs)
        if binding.task_id == 42 and result:
            settlement_events.append("lease_returned")
        return result
    monkeypatch.setattr(WorkerLeaseBinding, "return_lease", tracked_return_lease)
    original_finish_assignment = control.finish_assignment
    def tracked_finish_assignment(*args, **kwargs):
        result = original_finish_assignment(*args, **kwargs)
        if (kwargs.get("status") == "error"
                and kwargs.get("result") == "backend_error"
                and kwargs.get("reason") == "temporary_rate_limit"):
            settlement_events.append("assignment_finished")
        return result
    monkeypatch.setattr(control, "finish_assignment", tracked_finish_assignment)

    backend = OllamaBackend(default_model="qwen3.8:27b-mlx")
    backend_calls = []
    session = ChatSession()
    session.chat_id = worker_id
    runtime = ChatRuntime(backend, session_store=_persistent_session_store(tmp_path))
    monkeypatch.setattr(control, "runtime", runtime)
    async def resident_buddha_warmup(*_args, **_kwargs):
        return {"state": "resident"}
    monkeypatch.setattr(runtime, "warm_buddha_ollama_model", resident_buddha_warmup)
    monkeypatch.setattr(runtime, "get_session", lambda _id: session)
    monkeypatch.setattr(runtime, "_get_bach_context", lambda _text: "")
    monkeypatch.setattr(runtime, "_get_memory_hook_context", lambda *_args: "")

    # Keep the real ChatRuntime.process and reserve boundary. Only the model and
    # capacity ports are synthetic; the first probe blocks before dispatch.
    from hub._services.chat import local_resource_reserve
    current_slot = slots.get_always_on_execution_slot(path)
    model = current_slot["model"]
    gib = local_resource_reserve.GIB
    policy_version = "a" * 64
    policy = {
        "schema": local_resource_reserve.SCHEMA,
        "enabled": True,
        "memory_reserve_bytes": gib,
        "disk_reserve_bytes": gib,
        "wait_seconds": 60,
        "poll_seconds": 1,
        "models": {
            model: {
                "digest": "d" * 64,
                "weight_budget_bytes": gib,
                "kv_headroom_bytes": gib,
                "overhead_bytes": gib,
                "num_ctx": 16384,
            }
        },
    }
    monkeypatch.setattr(
        local_resource_reserve, "read_policy", lambda: (policy, policy_version),
    )

    def capacity_receipt(state, memory_available):
        return {
            "schema": local_resource_reserve.SCHEMA,
            "state": state,
            "admitted": state == "ready",
            "enforced": True,
            "retryable": state != "ready",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "policy_version": policy_version,
            "model": model,
            "wait_seconds": 60,
            "poll_seconds": 1,
            "memory_total_bytes": 8 * gib,
            "memory_available_bytes": memory_available,
            "memory_required_bytes": 4 * gib,
            "disk_free_bytes": {"taskdb": 8 * gib, "runtime": 8 * gib, "slots": 8 * gib},
            "disk_reserve_bytes": gib,
            "weight_request_bytes": gib,
            "resident_weight_credit": False,
            "capacity_basis": "host_budget",
            "host_resources": {"schema": "bach.host-resource-observation.v1", "errors": ["host_observation_failed"]},
        }

    blocked_receipt = capacity_receipt("waiting_memory_reserve", 3 * gib)
    ready_receipt = capacity_receipt("ready", 5 * gib)
    capacity_wait_completed = False
    probe_observations = []
    probe_calls = []

    async def synthetic_capacity_probe(_backend, _model, *, reuse_running_server=False):
        assert reuse_running_server is True
        probe_calls.append("ready" if capacity_wait_completed else "blocked")
        return ready_receipt if capacity_wait_completed else blocked_receipt

    monkeypatch.setattr(local_resource_reserve, "probe", synthetic_capacity_probe)

    def ready_capacity_probe(slot):
        assert capacity_wait_completed
        worker_control = control._WORKER_CONTROLS[worker_id]
        assert worker_control.task_binding is None and worker_control.lease_supervisor is None
        assert client.read(42).leased is False
        observed = slots._persistent_core_capacity_observation(
            ready_receipt, worker=slot, expected_state="ready",
        )
        probe_observations.append(observed)
        return ready_receipt, observed

    monkeypatch.setattr(control, "_persistent_core_capacity_probe", ready_capacity_probe)
    monkeypatch.setattr(
        control, "_snapshot_chat_backend",
        lambda *args, **kwargs: (backend, "qwen3.8:27b-mlx"),
    )
    attempts, fences, waits = [], [], []

    async def backend_chat(*args, **kwargs):
        backend_calls.append(kwargs)
        current = control._WORKER_CONTROLS[worker_id]
        binding = session.worker_task_binding
        assert binding is current.task_binding
        assert binding is not None and binding.task_id == 42 and not binding.closed
        assert session._worker_model_dispatch_binding is binding
        assert binding.tool_dispatch_count == 0
        if binding not in attempts:
            attempts.append(binding)
            fences.append(binding._ack.fence)
        assert len(backend_calls) == 1
        persisted = slots.load_slots_config(path, strict=True)["slots"][worker_id]
        persisted_checkpoint = persisted[slots.PERSISTENT_WORKER_CONTROLLER_CHECKPOINT_FIELD]
        persisted_recovery = persisted[slots.PERSISTENT_CORE_RECOVERY_FIELD]
        assert persisted_checkpoint == current.persistent_core_checkpoint
        assert persisted_recovery["phase"] == "active"
        assert persisted_recovery["retry_count"] == 1
        assert slots._persistent_core_profile_version(persisted) == (
            current.persistent_core_profile_version
        )
        assert controller_cas_readbacks == [
            "reserve_wait_ack_readback", "active_cas_ack_readback",
        ]
        raise LocalReserveError("Lokale Ressourcenfreigabe: reserve_wait_expired")

    monkeypatch.setattr(backend, "chat", backend_chat)
    monkeypatch.setattr(control, "_wait_worker_cooldown", lambda *args, **kwargs: False)
    def wait_without_lease(worker, seconds, *, expected_persistent_binding=None):
        waits.append(seconds)
        assert expected_persistent_binding is not None
        first_binding = session._local_reserve_failure_binding
        assert first_binding is not None
        if first_binding not in attempts:
            attempts.append(first_binding)
            fences.append(first_binding._ack.fence)
        assert len(attempts) == 1
        assert first_binding is attempts[0]
        assert session._local_reserve_failure_control is not None
        assert session._local_reserve_failure_reason_code == (
            "local_reserve_reserve_wait_lease_return_required"
        )
        assert attempts[0].tool_dispatch_count == 0
        assert session.worker_task_binding is None
        assert worker.task_binding is None and worker.lease_supervisor is None
        assert client.read(42).leased is False
        assert settlement_events[:2] == ["lease_returned", "assignment_finished"]
        stored_wait = slots.load_slots_config(path, strict=True)["slots"][worker_id][
            slots.PERSISTENT_CORE_RECOVERY_FIELD
        ]
        assert stored_wait["phase"] == "reserve_wait"
        assert stored_wait["reason_code"] == (
            "local_reserve_reserve_wait_lease_return_required"
        )
        nonlocal capacity_wait_completed
        capacity_wait_completed = True
        simulated_clock["offset_seconds"] = 61
        current = slots.get_always_on_execution_slot(path)
        assert control._persistent_local_retry_binding(current) == expected_persistent_binding
        slots.update_slot(worker_id, {"resolved_model": "stale-between-task-generations"}, path)
        assert projected_resolved_model() == "stale-between-task-generations"
        return True

    monkeypatch.setattr(control, "_wait_worker_backend_retry", wait_without_lease)
    thread = None
    try:
        startup_snapshot = slots.persistent_core_startup_snapshot()
        admission = control._persistent_core_begin_admission(
            startup_snapshot, threading.Event(), ready_receipt,
        )
        assert admission["state"] == "admitted", admission
        stored_core = slots.load_slots_config(path, strict=True)["slots"][worker_id]
        checkpoint = stored_core.get(slots.PERSISTENT_WORKER_CONTROLLER_CHECKPOINT_FIELD)
        recovery_state = stored_core.get(slots.PERSISTENT_CORE_RECOVERY_FIELD)
        assert checkpoint["phase"] == "admitted"
        assert recovery_state["phase"] == "active"
        thread = control._WORKER_EXECUTIONS[worker_id].thread
        thread.join(8)
        assert not thread.is_alive()
        assert len(attempts) == 2 and len(waits) == 1
        assert fences[0] != fences[1]
        assert attempts[0] is not attempts[1]
        assert attempts[0].tool_dispatch_count == attempts[1].tool_dispatch_count == 0
        assert len(backend_calls) == 1
        assert probe_calls[0] == "blocked" and "ready" in probe_calls[1:]
        assert waits == [60]
        assert len(probe_observations) == 1
        assert probe_observations[0]["state"] == "ready"
        assert len(backend_calls) == 1
        assert session._worker_model_dispatch_binding is attempts[1]
        assert client.read(42).leased is False
        assert projected_resolved_model() == ""
        assert session._local_reserve_failure_reason_code is None
        task = client.task_snapshot(42)
        assert task["status"] == "pending"
        history = slots.get_activity_history(path=path)
        encoded_history = json.dumps(history)
        assert "local_reserve_reserve_wait_lease_return_required" in encoded_history
        assert "local_reserve_reserve_wait_expired" in encoded_history
        assert "resolved_model" not in json.dumps(history[0])
    finally:
        if thread is not None and thread.is_alive():
            control._WORKER_CONTROLS[worker_id].stop_event.set()
            thread.join(8)
        conn.close()


def test_always_on_retry_wait_stops_when_bound_consent_changes(monkeypatch):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    slot = {
        **slots.DEFAULT_CORE_SLOTS["buddha_always_on"],
        "type": "continuous", "status": "running", "enabled": True,
        "persistent_opt_in": True, "persistent_opt_in_id": "c" * 32,
    }
    slot["persistent_opt_in_profile_version"] = slots._persistent_core_profile_version(slot)
    expected = control._persistent_local_retry_binding(slot)
    assert expected is not None
    worker = control._WorkerControl("buddha_always_on", slot_policy_reader=lambda: slot)
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {worker.worker_id: worker})
    assert control._wait_worker_backend_retry(
        worker, 0, expected_persistent_binding=expected,
    ) is True

    slot["persistent_opt_in"] = False
    assert control._wait_worker_backend_retry(
        worker, 0, expected_persistent_binding=expected,
    ) is False


def test_worker_activity_does_not_copy_cached_resolved_model(monkeypatch):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    worker = control._WorkerControl("activity-fixture", slot_policy_reader=lambda: {
        "id": "activity-fixture", "model": "qwen3.8:27b-mlx",
        "resolved_model": "stale-cache-model",
    })
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {worker.worker_id: worker})
    monkeypatch.setattr(control, "_worker_metadata_available", lambda _worker_id: True)
    monkeypatch.setattr(control, "_execution_worker_slot", lambda _worker_id: {
        "model": "qwen3.8:27b-mlx", "resolved_model": "stale-cache-model",
    })
    recorded = []
    monkeypatch.setattr(control, "record_activity", lambda *args, **kwargs: recorded.append((args, kwargs)))
    assert control._record_worker_activity(worker, "synthetic", "ok", {"reason_code": "safe_code"})
    details = recorded[0][0][3]
    assert details == {"reason_code": "safe_code", "model": "qwen3.8:27b-mlx"}
    assert "resolved_model" not in details


@pytest.mark.parametrize(("result", "expected_model"), [
    ({"error": "synthetic failure", "model": "stale-error-model"}, ""),
    ({"content": "ok"}, ""),
    ({"content": "ok", "model": "explicit-current-model"}, "explicit-current-model"),
])
def test_runtime_reports_only_current_successful_response_model(
        monkeypatch, result, expected_model):
    class Backend:
        name = "fixture-cloud"
        manages_own_tools = True
        last_resolved_model = "stale-backend-cache"
        def get_default_model(self):
            return "fixture-model"
        async def chat(self, *args, **kwargs):
            return result

    backend = Backend()
    runtime = ChatRuntime(backend)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_context_limit_for_backend", lambda *args, **kwargs: 4096)
    async def dispatch(*args, **kwargs):
        return await backend.chat(*args, **kwargs)
    monkeypatch.setattr(runtime, "_chat_with_compute_turn", dispatch)
    answer = asyncio.run(runtime.process(
        "fixture", "buddha_always_on", work_priority="background",
    ))
    session = runtime.get_session("buddha_always_on")
    if result.get("error"):
        assert FailedAnswer.looks_like(answer)
    assert session.resolved_model == expected_model


def test_persistent_core_pre_effect_reserve_returns_typed_failure_without_model_call(
        tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from hub._services.chat import local_model_admission, local_resource_reserve
    from hub._services.chat.local_resource_reserve import LocalReserveError

    worker = {
        **slots.DEFAULT_CORE_SLOTS["buddha_always_on"],
        "id": "buddha_always_on", "type": "continuous", "status": "running",
        "enabled": True, "persistent_opt_in": True, "persistent_opt_in_id": "a" * 32,
    }
    profile_version = slots._persistent_core_profile_version(worker)
    worker["persistent_opt_in_profile_version"] = profile_version
    physical = "worker-" + "4" * 32
    checkpoint = {
        "schema": "bach.persistent-worker-controller.v2",
        "phase": "admitted", "worker_id": worker["id"],
        "service_instance": "1" * 32, "start_request_id": "2" * 32,
        "intent_id": worker["persistent_opt_in_id"], "profile_version": profile_version,
        "trace_contract_sha256": "b" * 64, "generation": "3" * 32,
        "physical_worker_id": physical, "lease_worker_id": physical + "@HOST",
    }
    recovery = {
        "schema": "bach.persistent-core-recovery.v1", "phase": "active",
        "worker_id": worker["id"], "intent_id": worker["persistent_opt_in_id"],
        "profile_version": profile_version, "retry_count": 0, "waited_seconds": 0,
        "capacity_state": "waiting_memory_reserve", "capacity_policy_version": "c" * 64,
        "capacity_fingerprint": "d" * 64,
        "checkpoint_sha256": slots._persistent_checkpoint_sha256(checkpoint),
    }
    assert slots._valid_persistent_worker_controller_checkpoint(checkpoint)
    assert slots._valid_persistent_core_recovery_state(
        recovery, worker=worker, checkpoint=checkpoint)

    snapshot = {
        "state": "prior_generation_unsettled", "worker_id": worker["id"],
        "intent_id": worker["persistent_opt_in_id"], "profile_version": profile_version,
        "checkpoint": checkpoint, "recovery_state": recovery, "slot": worker,
    }
    monkeypatch.setattr(slots, "persistent_core_startup_snapshot", lambda: snapshot)

    gib = local_resource_reserve.GIB
    model = worker["model"]
    policy_version = "c" * 64
    policy = {
        "schema": local_resource_reserve.SCHEMA, "enabled": True,
        "memory_reserve_bytes": gib, "disk_reserve_bytes": gib,
        "wait_seconds": 60, "poll_seconds": 1,
        "models": {model: {
            "digest": "e" * 64, "weight_budget_bytes": gib,
            "kv_headroom_bytes": gib, "overhead_bytes": gib, "num_ctx": 16384,
        }},
    }
    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: (policy, policy_version))
    blocked = {
        "schema": local_resource_reserve.SCHEMA,
        "state": "waiting_memory_reserve", "admitted": False, "enforced": True,
        "retryable": True, "checked_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": policy_version, "model": model, "wait_seconds": 60,
        "poll_seconds": 1, "memory_total_bytes": 8 * gib,
        "memory_available_bytes": 3 * gib, "memory_required_bytes": 4 * gib,
        "disk_free_bytes": {"taskdb": 8 * gib, "runtime": 8 * gib, "slots": 8 * gib},
        "disk_reserve_bytes": gib, "weight_request_bytes": gib,
        "resident_weight_credit": False,
        "capacity_basis": "host_budget",
        "host_resources": {"schema": "bach.host-resource-observation.v1", "errors": ["host_observation_failed"]},
    }
    composed = local_model_admission.compose_admission_receipt(
        blocked, binding=None, require_model_socket=False,
    )

    class Binding:
        tool_dispatch_count = 0
        closed = False
        stop_requested = False
        def assert_active(self):
            return None

    binding = Binding()
    startup = threading.Event()
    startup.set()
    stop = threading.Event()
    control = SimpleNamespace(
        worker_id="buddha_always_on", task_binding=binding, stop_event=stop,
        persistent_core_startup_confirmed=startup, persistent_core_startup_cancelled=False,
        persistent_core_intent_id=worker["persistent_opt_in_id"],
        persistent_core_profile_version=profile_version,
        persistent_core_checkpoint=checkpoint, persistent_core_recovery_state=recovery,
    )
    runtime = ChatRuntime(object())
    session = runtime.get_session("buddha_always_on")
    session.worker_task_binding = binding
    session.require_task_binding = True
    session._persistent_core_model_call_control = control
    monkeypatch.setattr(runtime, "get_session", lambda _chat_id: session)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *args: None)
    monkeypatch.setattr(runtime, "_uses_local_compute", lambda _backend: True)

    async def prepared(_backend, _model, *, chat_id=None):
        return composed, None
    monkeypatch.setattr(runtime, "prepare_inference_call", prepared)

    class Backend:
        name = "ollama"
        manages_own_tools = False
        def __init__(self):
            self.calls = 0
        def get_default_model(self):
            return model
        async def chat(self, *args, **kwargs):
            self.calls += 1
            return "must not be called"

    backend = Backend()
    token = runtime._compute_turn_context.set(("buddha_always_on", "background"))
    try:
        with pytest.raises(LocalReserveError, match="reserve_wait_lease_return_required"):
            asyncio.run(runtime._chat_with_compute_turn(
                backend, [{"role": "user", "content": "synthetic"}], model=model,
            ))
    finally:
        runtime._compute_turn_context.reset(token)
    assert backend.calls == 0
    assert session._local_reserve_failure_reason_code == (
        "local_reserve_reserve_wait_lease_return_required"
    )
    assert session._local_reserve_failure_binding is binding
    assert session._local_reserve_failure_control is control
    assert session._local_reserve_failure_receipt == blocked

    # Every uncertainty gate must turn the special path off.
    assert runtime._persistent_core_pre_effect_reserve_receipt(
        session=session, binding=binding, backend=backend, model=model,
        priority="background", receipt=composed,
    ) == blocked
    binding.tool_dispatch_count = 1
    assert runtime._persistent_core_pre_effect_reserve_receipt(
        session=session, binding=binding, backend=backend, model=model,
        priority="background", receipt=composed,
    ) is None
    binding.tool_dispatch_count = 0
    session._worker_model_dispatch_binding = binding
    assert runtime._persistent_core_pre_effect_reserve_receipt(
        session=session, binding=binding, backend=backend, model=model,
        priority="background", receipt=composed,
    ) is None
    session._worker_model_dispatch_binding = None
    assert runtime._persistent_core_pre_effect_reserve_receipt(
        session=session, binding=binding, backend=backend, model=model,
        priority="foreground", receipt=composed,
    ) is None
    snapshot["profile_version"] = "f" * 64
    assert runtime._persistent_core_pre_effect_reserve_receipt(
        session=session, binding=binding, backend=backend, model=model,
        priority="background", receipt=composed,
    ) is None


@pytest.mark.parametrize("exception_type", [httpx.ConnectTimeout, httpx.ReadTimeout])
@pytest.mark.parametrize("core", [True, False])
def test_request_failure_survives_assignment_end_store_and_gui(tmp_path, exception_type, core):
    from hub._services.llm.backend_errors import BackendRequestFailure
    heart = importlib.import_module("hub._services.agents_heart")
    path = str(tmp_path / "transport-slots.json")
    slots.initialize_slots_config(path)
    ident = "buddha_always_on" if core else slots.add_worker({"name": "Synthetic transport"}, path)["id"]
    carrier = BackendRequestFailure.from_httpx(exception_type(""), provider="openrouter")
    carrier.backend_error.update({"message": "PRIVATE_BODY", "authorization": "PRIVATE_TOKEN"})
    answer = FailedAnswer.from_exception(carrier)
    assignment = heart.begin_assignment(
        role_id="task_worker", mode="safe", agent_instance_id="synthetic-worker",
        backend_id="openrouter", model_id="openrouter/free", slot_id=ident,
        task_id=42, session_id=ident, initiated_by="synthetic", path=path)
    slots.update_slot(ident, {"status": "error", "current_activity": str(answer),
                              "backend_error": answer.backend_error}, path)
    heart.finish_assignment(assignment, status="error", result="backend_error", path=path)
    current = slots.get_slot(ident, path)
    events = slots.get_activity_history(path=path)
    assert any(event.get("event") == "assignment_ended" for event in events)
    assert current["backend_error"]["error_type"] == exception_type.__name__
    public = _project_worker({"id": ident, "status": current["status"],
                              "backend_error": current["backend_error"]})
    messages = [{"role": "assistant", "content": answer, "answer_status": "failed"}]
    stored = json.loads(json.dumps(ChatRuntime._messages_for_store(messages)))
    restored = ChatRuntime._restore_message_status(stored)
    assert restored[0]["content"].backend_error == public["backend_error"]
    assert "backend_error" not in ChatRuntime._messages_for_backend(restored)[0]
    assert "PRIVATE" not in json.dumps(events + [public] + stored)


@pytest.mark.parametrize("changes", [
    {"kind": "quota_exceeded"}, {"kind": "rate_limited"},
    {"kind": []}, {"error_type": "PRIVATE_TYPE"}, {"quota_exceeded": True},
    {"quota_exceeded": 0}, {"status_code": 503}, {"provider": "PRIVATE_PROVIDER"},
])
def test_request_error_metadata_is_closed_and_never_implies_quota(changes):
    detail = {"provider": "openrouter", "kind": "connect_timeout",
              "error_type": "ConnectTimeout", "quota_exceeded": False, **changes}
    assert "backend_error" not in _project_worker({"id": "worker-1", "backend_error": detail})


@pytest.mark.parametrize("bad_status", [True, 0, 600, "429"])
def test_request_http_status_has_strict_observed_type_and_range(bad_status):
    from hub._services.llm.backend_errors import normalize_backend_error
    assert normalize_backend_error({"provider": "openrouter", "kind": "http_error",
        "error_type": "HTTPStatusError", "quota_exceeded": False,
        "status_code": bad_status}) is None


@pytest.mark.parametrize("metadata_case", ["malformed", "missing"])
def test_malformed_carrier_does_not_fall_back_to_raw_exception_text(metadata_case):
    from hub._services.llm.backend_errors import BackendRequestFailure
    carrier = BackendRequestFailure.from_httpx(httpx.ReadTimeout(""), provider="openrouter")
    if metadata_case == "malformed":
        carrier.backend_error = {"provider": "openrouter", "kind": "PRIVATE"}
    else:
        del carrier.backend_error
    carrier.args = ("PRIVATE_EXCEPTION_URL_TOKEN",)
    answer = FailedAnswer.from_exception(carrier)
    assert answer.backend_error is None and "PRIVATE" not in str(answer)
    assert "nicht verifiziert" in str(answer)
