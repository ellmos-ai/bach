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
        if core:
            agent = next(a for a in control._system_slots_snapshot()["agents"] if a["id"] == ident)
            assert agent["backend_error"]["quota_period"] == "month"
            assert agent["backend_error"]["status_code"] == 429
            assert agent["status"] == "error" and agent["worker_active"] is False
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
    ("glm-5.3:cloud", "rate_limited", "continuous", 0, 0, 901, None),
    ("glm-5.3:cloud", "rate_limited", "continuous", 2, 661, 240, None),
    ("glm-5.3:cloud", "rate_limited", "continuous", 3, 420, None, None),
    ("glm-5.3:cloud", "quota_exceeded", "continuous", 0, 0, 60, None),
    ("glm-5.3:cloud", "http_error", "continuous", 0, 0, 60, None),
    ("glm-5.3:cloud", "rate_limited", "once", 0, 0, 60, None),
    ("qwen3.5:4b", "rate_limited", "persistent", 0, 0, 60, None),
])
def test_cloud_retry_policy_is_bounded_and_preserves_observed_header(
        model, kind, worker_type, retries, waited, header, expected):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    detail = {"provider": "ollama", "kind": kind, "status_code": 429 if kind != "http_error" else 401,
              "quota_exceeded": kind == "quota_exceeded"}
    if header is not None:
        detail["retry_after_seconds"] = header
    assert control._worker_backend_retry_delay({"type": worker_type}, detail, model=model,
        retries=retries, waited_seconds=waited) == expected


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


@pytest.mark.parametrize("scenario", ["recover", "exhausted", "stop", "return_denied", "foreign_claim", "quota_after_retry",
    "unknown_none", "unknown_false", "unknown_true", "unknown_negative", "unknown_string", "unknown_float"])
def test_native_cloud_retry_releases_before_wait_and_reclaims_fresh_fence(tmp_path, monkeypatch, scenario):
    import sqlite3
    from hub._services import task_lease_client as client_module
    from hub._services.task_lease_client import TaskLeaseClient
    from hub._services.chat.chat_runtime import ChatSession, _managed_backend_answer
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from system.tests.test_task_lease_client import _init_db
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    ident = slots.add_worker({"name": "Cloud retry fixture", "type": "continuous"}, path)["id"]
    slots.update_slot(ident, {"backend": "ollama", "model": "glm-5.3:cloud", "enabled": True,
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
    session = ChatSession()
    session.chat_id = ident
    monkeypatch.setattr(control.runtime, "get_session", lambda _: session)
    backend = OllamaBackend(default_model="glm-5.3:cloud")
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *a, **kw: (backend, "glm-5.3:cloud"))
    real_client = httpx.AsyncClient
    calls, fences, waits = [], [], []
    def reply(request):
        calls.append(request)
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
        answer = _managed_backend_answer(await backend.chat([{"role": "user", "content": "fixture"}]))
        if not FailedAnswer.looks_like(answer):
            binding.execute_task_manage({"action": "submit_result", "task_id": 42, "result": str(answer)})
        return answer
    monkeypatch.setattr(control.runtime, "process", process)
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
        assert public.get("active_task_id") is None and public["backend_error"]["status_code"] == 429
        if scenario == "stop":
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
        assert all(json.loads(request.content)["model"] == "glm-5.3:cloud" for request in calls)
        task = dict(conn.execute("SELECT * FROM tasks WHERE id=42").fetchone())
        current = slots.get_slot(ident, path)
        if scenario == "recover":
            assert len(calls) == 2 and waits == [60] and fences == [1, 2]
            assert task["status"] == "review" and task["claim_salt_ref"] is None
            assert current.get("backend_error") is None
            assert execution.task_result_bindings[42].submitted_result["accepted"] is False
        elif scenario == "exhausted":
            assert len(calls) == 4 and waits == [60, 120, 240] and fences == [1, 2, 3, 4]
            assert current["status"] == "error" and "begrenzt beendet" in current["current_activity"]
            assert task["status"] == "pending" and task["claim_salt_ref"] is None
        elif scenario == "quota_after_retry":
            assert len(calls) == 2 and waits == [60]
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
            assert len(calls) == 1 and waits == []
            assert task["status"] == "blocked" and task["claim_salt_ref"] is None
            assert "nicht verifizierbar" in current["current_activity"]
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
def test_real_tool_loop_prevents_cloud_retry_after_dispatch(tmp_path, monkeypatch, action, previous_block, dispatch_path, backend_failure):
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
    runtime = ChatRuntime(backend)
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
        assert len(calls) <= expected_calls, "Unsafe replay reached provider"
        status = 503 if backend_failure == "server_error" else 429
        message = "monthly usage limit reached" if backend_failure == "monthly_quota" else "rate limit"
        return httpx.Response(status, json={"error": message})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw:
        real_client(transport=httpx.MockTransport(reply), **kw))
    def wait(worker, seconds):
        waits.append(seconds)
        pytest.fail("Tools have run; automatic retry must be suppressed")
    monkeypatch.setattr(control, "_wait_worker_backend_retry", wait)
    thread = None
    try:
        response, code = control.start_worker_execution(ident)
        assert code == 200 and response["ok"] is True
        execution = control._WORKER_EXECUTIONS[ident]
        thread = execution.thread
        thread.join(8)
        assert not thread.is_alive()
        expected_calls = (2 if dispatch_path == "runtime" else 1) + int(previous_block)
        assert len(calls) == expected_calls and waits == []
        snapshot = client.task_snapshot(42)
        assert snapshot["claim_fence"] == 1 and snapshot["status"] == "blocked"
        assert not client.read(42).leased
        children = conn.execute("SELECT COUNT(*) FROM tasks WHERE id != 42").fetchone()[0]
        assert children == (1 if action == "add" else 0)
        current = slots.get_slot(ident, path)
        assert current["status"] == "error"
        assert "Toolwirkung" in current["current_activity"]
        expected_kind = {"server_error": "http_error", "monthly_quota": "quota_exceeded", "rate_limit": "rate_limited"}[backend_failure]
        assert current["backend_error"]["kind"] == expected_kind
        assert execution.task_binding.tool_dispatch_count == 1
        assert execution.start_error == "backend_error"
        # A compatible second worker must not silently replay the initial
        # prompt with a fresh zero counter after the first worker exits.
        import threading
        from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
        from hub._services.task_lease_client import LeaseDeniedError
        second = WorkerLeaseBinding.acquire_next(client, {"id": ident, "model": "glm-5.3:cloud"},
            worker_id="second@fixture", host="fixture", generation="b" * 32,
            is_current=lambda: True, stop_event=threading.Event())
        if second is not None:
            assert second.task_id != 42
            assert second.return_lease()
        with pytest.raises(LeaseDeniedError, match="not_claimable"):
            WorkerLeaseBinding.acquire(client, 42, worker_id="second@fixture", host="fixture",
                generation="b" * 32, is_current=lambda: True, stop_event=threading.Event())
        history = conn.execute("SELECT new_value FROM task_history WHERE task_id=42 AND action='lease_release'").fetchall()
        assert any("backend_error_after_tool_dispatch" in row[0] for row in history)
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
