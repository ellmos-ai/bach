"""System slot configuration and observed execution, without live inference."""
import asyncio
import json
import sqlite3
import threading
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from hub._services.chat import slots_config as slots
from hub._services.chat.chat_runtime import ChatRuntime, ChatSession, FailedAnswer
from hub._services.chat.agent_profile_context import profile_chat_id_agent
from gui.api import core_system_agents as api, worker_status_adapter as adapter


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    return path


def test_system_defaults_include_transparent_personal_assistant(config_file):
    snapshot = slots.core_system_agents_snapshot()
    assert len(snapshot["agents"]) == 6
    assert {"buddha_boss", "buddha_developer", "buddha_research"} <= {a["id"] for a in snapshot["agents"]}
    assert all(agent["include_system_prompt"] for agent in snapshot["agents"])
    assert snapshot["agents"][0]["role_id"] == "personal-assistant"
    assert snapshot["prompt_templates"]["roles"]["personal-assistant"]
    assert all(agent["running"] is None for agent in snapshot["agents"])


def test_custom_boss_slot_crud_is_versioned_and_preserves_existing_slots(config_file):
    before = slots.core_system_agents_snapshot()
    created = slots.create_system_slot({"name": "Mein Boss"}, before["configuration_version"], preset="boss")
    slot_id = created["slot_id"]
    slot = slots.get_system_slot(slot_id)
    assert slot["sub_mode"] == "boss_routing" and slot["execution_kind"] == "worker"
    assert slot["enabled"] is True and slot["status"] == "idle"
    assert slot["require_assigned_slot"] is True
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.create_system_slot({}, before["configuration_version"])
    assert slots.task_matches_slot_binding({"id": 7, "assigned_slot": slot_id}, slot)
    assert not slots.task_matches_slot_binding({"id": 8}, slot)
    assert not slots.task_matches_slot_binding({"id": 9, "assigned_slot": "someone-else"}, slot)
    changed = slots.change_core_system_agent(slot_id, created["configuration_version"], {"custom_role_prompt": "Koordiniere klar."})
    assert "Koordiniere klar." in slots.compose_worker_prompt(slots.get_system_slot(slot_id))
    assert slots.delete_system_slot(slot_id, changed["configuration_version"])
    assert slots.core_system_agents_snapshot()["agents"] == before["agents"]


def test_fixed_system_slot_cannot_be_deleted(config_file):
    version = slots.core_system_agents_snapshot()["configuration_version"]
    with pytest.raises(ValueError):
        slots.delete_system_slot("buddha_chat", version)


def test_custom_system_prompt_toggle_and_role_override(config_file):
    slot = slots.get_system_slot("buddha_chat")
    slot.update(custom_system_prompt="Meine Systemregeln.", custom_role_prompt="Meine Rollenregeln.")
    assert "Meine Systemregeln." in slots.compose_worker_prompt(slot)
    assert "Meine Rollenregeln." in slots.compose_worker_prompt(slot)
    slot["include_system_prompt"] = False
    prompt = slots.compose_worker_prompt(slot)
    assert "Meine Systemregeln." not in prompt
    assert "Meine Rollenregeln." in prompt


@pytest.mark.parametrize("bad", ["data:image/svg+xml;base64,AAAA", "https://example.org/a.png",
    "data:image/png;base64,aGVsbG8=", "data:image/jpeg;base64,AAAA", None, "x" * 240001],
    ids=["svg", "url", "bad-png", "bad-jpeg", "none", "oversize"])
def test_avatar_is_bounded_and_rejects_active_or_invalid_formats(bad):
    with pytest.raises(ValueError):
        slots.validate_agent_avatar(bad)


def test_slot_symbol_and_portrait_roundtrip_use_configuration_cas(config_file):
    before = slots.core_system_agents_snapshot()
    result = slots.change_core_system_agent("buddha_chat", before["configuration_version"],
                                            {"avatar": "preset:companion", "symbol": "topics_ai"})
    item = next(item for item in result["agents"] if item["id"] == "buddha_chat")
    assert (item["avatar"], item["symbol"]) == ("preset:companion", "topics_ai")
    with pytest.raises(RuntimeError, match="conflict"):
        slots.change_core_system_agent("buddha_chat", before["configuration_version"], {"symbol": "wissen"})
    with pytest.raises(ValueError, match="Symbol"):
        slots.change_core_system_agent("buddha_chat", result["configuration_version"], {"symbol": "https://bad"})


def test_slot_chat_identity_keeps_profile_and_slot_separate():
    suffix = "a" * 32
    assert slots.system_slot_chat_id("slot:buddha_chat:" + suffix) == "buddha_chat"
    nested = "agent:4:slot:system-expert:" + suffix
    assert slots.system_slot_chat_id(nested) == "system-expert"
    assert profile_chat_id_agent(nested) == 4
    assert profile_chat_id_agent("agent:4:" + suffix) == 4
    assert slots.system_slot_chat_id("slot:buddha_chat:invalid") is None
    assert profile_chat_id_agent("agent:4:slot:../../x:" + suffix) is None


def test_disabling_or_changing_a_slot_revokes_tools(config_file):
    session = ChatSession()
    session.system_slot_id = "buddha_chat"
    session.system_slot_reader = lambda: slots.get_system_slot("buddha_chat")
    session.system_slot_configuration = {"model": slots.get_system_slot("buddha_chat")["model"]}
    assert ChatRuntime._refresh_worker_tools(session) is None
    slots.update_slot("buddha_chat", {"model": "a-new-model"})
    assert isinstance(ChatRuntime._refresh_worker_tools(session), FailedAnswer)
    assert session.allow_tools is False


def test_stored_running_status_is_not_a_running_receipt(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    slots.update_slot("buddha_chat", {"status": "running", "current_activity": "old activity"})
    monkeypatch.setattr(control.runtime, "sessions", {})
    monkeypatch.setattr(control.runtime, "_chat_turn_gates", {})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    agent = control._system_slots_snapshot()["agents"][0]
    assert agent["runtime_verified"] is True
    assert agent["running"] is False and agent["status"] == "ready"
    assert agent["current_tool"] == ""


@pytest.mark.parametrize("kind", ["fixed", "custom"])
def test_live_continuous_worker_waiting_for_task_is_running(config_file, monkeypatch, kind):
    from hub._services.chat import telegram_chat as control
    ident = "buddha_boss"
    if kind == "custom":
        result = slots.create_system_slot(
            {"name": "Waiting worker"}, slots.core_system_agents_snapshot()["configuration_version"],
            preset="boss")
        ident = result["slot_id"]
    slots.update_slot(ident, {"type": "continuous", "status": "running"})
    ctrl = control._WorkerControl(ident)
    ctrl.thread = SimpleNamespace(is_alive=lambda: True)
    ctrl.worker_thread_started = True
    monkeypatch.setattr(control.runtime, "sessions", {})
    monkeypatch.setattr(control.runtime, "_chat_turn_gates", {})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {ident: ctrl})
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {ident: ctrl})
    monkeypatch.setattr(control, "_ACTIVE_WORKER_THREADS", {ident: ctrl.thread})
    monkeypatch.setattr(control.runtime, "compute_turn_status",
                        lambda: {"active": False, "foreground_waiters": 0})
    agent = next(item for item in control._system_slots_snapshot()["agents"] if item["id"] == ident)
    assert agent["execution"]["state"] == "running"
    assert agent["execution"]["worker_thread_started"] is True
    assert agent["living"] is True and agent["running"] is True and agent["status"] == "running"
    assert agent["task_id"] is None
    assert agent["current_tool"] == "" and agent["tool_round"] == 0
    assert control.runtime.compute_turn_status()["active"] is False


@pytest.mark.parametrize(
    "state,alive,started,admission_pending,stop,done,expected_running",
    [
        ("starting", True, False, True, False, False, True),
        ("stopping", True, True, False, True, False, True),
        ("finishing", True, True, False, False, True, True),
        ("unconfirmed", True, False, False, False, False, True),
        ("unconfirmed", False, True, False, False, False, None),
        ("unconfirmed", False, False, True, False, False, None),
        ("terminal", False, True, False, False, True, False),
    ],
    ids=["starting", "stopping", "finishing", "unconfirmed-live",
         "unconfirmed-dead", "unconfirmed-admission", "terminal"])
def test_worker_lifecycle_snapshot_never_reports_pending_execution_ready(
        config_file, monkeypatch, state, alive, started, admission_pending, stop, done,
        expected_running):
    from hub._services.chat import telegram_chat as control
    ident = "buddha_boss"
    ctrl = control._WorkerControl(ident)
    ctrl.thread = SimpleNamespace(is_alive=lambda: alive)
    ctrl.worker_thread_started = started
    ctrl.admission_pending = admission_pending
    if stop:
        ctrl.stop_event.set()
    if done:
        ctrl.done_event.set()
    # Retained executions include the cleanup tail after the current control is removed.
    monkeypatch.setattr(control.runtime, "sessions", {})
    monkeypatch.setattr(control.runtime, "_chat_turn_gates", {})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {} if done else {ident: ctrl})
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {ident: ctrl})
    monkeypatch.setattr(control, "_ACTIVE_WORKER_THREADS", {})
    agent = next(item for item in control._system_slots_snapshot()["agents"] if item["id"] == ident)
    assert agent["execution"]["state"] == state
    assert agent["execution"]["terminal"] is (state == "terminal")
    assert agent["running"] is expected_running
    assert agent["status"] == ("ready" if state == "terminal" else state)
    assert agent["task_id"] is None
    assert agent["current_tool"] == "" and agent["tool_round"] == 0


def test_disabled_worker_stays_living_until_physical_cleanup_finishes(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    ident = "buddha_boss"
    slots.update_slot(ident, {"enabled": False})
    alive = {"value": True}
    ctrl = control._WorkerControl(ident)
    ctrl.thread = SimpleNamespace(is_alive=lambda: alive["value"])
    ctrl.worker_thread_started = True
    ctrl.stop_event.set()
    ctrl.done_event.set()
    monkeypatch.setattr(control.runtime, "sessions", {})
    monkeypatch.setattr(control.runtime, "_chat_turn_gates", {})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {ident: ctrl})
    monkeypatch.setattr(control, "_ACTIVE_WORKER_THREADS", {})
    def snapshot():
        return next(item for item in control._system_slots_snapshot()["agents"] if item["id"] == ident)
    agent = snapshot()
    assert agent["enabled"] is False
    assert agent["living"] is True and agent["running"] is True and agent["status"] == "finishing"
    assert agent["execution"]["terminal"] is False
    assert agent["current_tool"] == "" and agent["tool_round"] == 0
    alive["value"] = False
    agent = snapshot()
    assert agent["living"] is False and agent["running"] is False and agent["status"] == "paused"
    assert agent["execution"]["terminal"] is True


def test_untracked_live_worker_is_unconfirmed_instead_of_ready(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    ident = "buddha_boss"
    monkeypatch.setattr(control.runtime, "sessions", {})
    monkeypatch.setattr(control.runtime, "_chat_turn_gates", {})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {})
    monkeypatch.setattr(control, "_ACTIVE_WORKER_THREADS",
                        {ident: SimpleNamespace(is_alive=lambda: True)})
    agent = next(item for item in control._system_slots_snapshot()["agents"] if item["id"] == ident)
    assert agent["execution"]["state"] == "unconfirmed"
    assert agent["living"] is True and agent["running"] is True and agent["status"] == "unconfirmed"
    assert agent["task_id"] is None
    assert agent["current_tool"] == "" and agent["tool_round"] == 0


def test_real_chat_turn_supplies_tool_round_and_running_state(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    chat_id = "slot:buddha_chat:" + "a" * 32
    monkeypatch.setattr(control.runtime, "sessions", {chat_id: SimpleNamespace(current_tool="read_file", tool_round=3)})
    monkeypatch.setattr(control.runtime, "_chat_turn_gates", {chat_id: SimpleNamespace(condition=threading.Condition(), active_turns=1)})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    agent = control._system_slots_snapshot()["agents"][0]
    assert agent["running"] is True and agent["current_tool"] == "read_file" and agent["tool_round"] == 3


def test_core_api_keeps_runtime_unknown_when_control_is_unavailable(config_file, monkeypatch):
    def unavailable(*args, **kwargs):
        raise adapter.WorkerStatusUnavailable("offline")
    monkeypatch.setattr(adapter, "_request_control_api", unavailable)
    result = asyncio.run(api.list_core_system_agents())
    assert all(agent["running"] is None for agent in result["agents"])
    assert all(item["runtime_state"] == "unknown" for item in result["blueprints"])


def test_timeline_uses_actual_events_and_never_task_creation_dates(monkeypatch):
    calls = []
    def request(method, endpoint, **kwargs):
        calls.append((method, endpoint))
        return {"ok": True, "history": [{"timestamp": "2026-10-07T22:00:00Z", "source": "worker-a",
            "task_id": 12, "event": "finished", "status": "review", "details": {"private": "omitted"}}]}
    monkeypatch.setattr(adapter, "_request_control_api", request)
    result = asyncio.run(api.system_agent_timeline())
    assert calls == [("GET", "activity")]
    assert result["events"][0]["task_id"] == 12
    assert "details" not in result["events"][0]


def test_new_profile_chat_reads_its_slot_backend_without_creating_unbound_ram(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    selected = object()
    monkeypatch.setattr(control.runtime, "session_store", SimpleNamespace(load_state=lambda ident: {"binding": None}))
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: pytest.fail("Unbound profile RAM must not be created"))
    calls = []
    monkeypatch.setattr(control, "_get_or_create_backend", lambda provider, model: calls.append((provider, model)) or selected)
    backend, model = control._snapshot_chat_backend("agent:4:slot:buddha_chat:" + "a" * 32)
    assert backend is selected
    assert calls == [("ollama", slots.get_system_slot("buddha_chat")["model"])]


@pytest.mark.parametrize("gate_kind", ["host", "runtime"])
@pytest.mark.parametrize("change", [{"enabled": False}, {"model": "replacement"}], ids=["off", "model"])
def test_slot_change_revokes_queued_inference(config_file, monkeypatch, tmp_path, gate_kind, change):
    from hub._services.chat.host_inference_gate import HostInferenceGate
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = SimpleNamespace(chat=AsyncMock(return_value={"content": "unused"}))
    runtime = ChatRuntime(backend)
    chat_id = "slot:buddha_chat:" + "a" * 32
    session = runtime.get_session(chat_id)
    session.backend, session.model = backend, slots.get_system_slot("buddha_chat")["model"]
    session.system_slot_id = "buddha_chat"
    session.system_slot_reader = lambda: slots.get_system_slot("buddha_chat")
    session.system_slot_configuration = {"model": slots.get_system_slot("buddha_chat")["model"]}
    runtime._chat_turn_gates[chat_id] = SimpleNamespace(condition=threading.Condition(), active_turns=1)
    monkeypatch.setattr(runtime, "_uses_local_compute", lambda selected: True)

    async def probe():
        token = runtime._compute_turn_context.set((chat_id, "foreground"))
        try:
            async with AsyncExitStack() as stack:
                if gate_kind == "host":
                    await stack.enter_async_context(HostInferenceGate().turn("holder", "foreground"))
                else:
                    runtime._compute_turn_gate.active = True
                task = asyncio.create_task(runtime._chat_with_compute_turn(backend, []))
                await asyncio.sleep(.04)
                slots.update_slot("buddha_chat", change)
                from hub._services.chat import telegram_chat as control
                monkeypatch.setattr(control, "runtime", runtime)
                monkeypatch.setattr(control, "_get_or_create_backend", lambda *args: object())
                expected = dict(session.system_slot_configuration)
                try:
                    control._snapshot_chat_backend(chat_id, read_only=True)
                except control.WorkerBindingError:
                    assert change.get("enabled") is False
                assert session.system_slot_configuration == expected
                # A second request must not rebind the first admitted turn either.
                with pytest.raises(control.WorkerBindingError):
                    control._snapshot_chat_backend(chat_id)
                assert session.system_slot_configuration == expected
                with pytest.raises(RuntimeError, match="ausgeschaltet|[Kk]onfiguration"):
                    await asyncio.wait_for(task, 2)
        finally:
            runtime._compute_turn_context.reset(token)
            runtime._leave_compute_turn(runtime._compute_turn_gate)
    asyncio.run(probe())
    backend.chat.assert_not_awaited()


def test_local_waiting_generation_cannot_adopt_cloud_config_without_new_start(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    ident = "buddha_always_on"
    slots.update_slot(ident, {"backend": "ollama", "model": "local-model"})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {})
    monkeypatch.setattr(control, "_ACTIVE_WORKER_THREADS", {})
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *args, **kw: None)
    monkeypatch.setattr(control, "record_activity", lambda *args, **kw: None)
    providers = []
    def snapshot(worker_id, *, worker_slot=None):
        providers.append(worker_slot["backend"])
        return object(), worker_slot["model"]
    monkeypatch.setattr(control, "_snapshot_chat_backend", snapshot)
    monkeypatch.setattr(control, "_acquire_worker_task", lambda *args: None)
    async def forbidden(*args, **kw):
        pytest.fail("No task was acquired; inference must not run")
    monkeypatch.setattr(control.runtime, "process", forbidden)

    class SynchronousThread:
        def __init__(self, target, **kw): self.target, self.active = target, False
        def start(self):
            self.active = True
            def wait(timeout=None):
                slots.update_slot(ident, {"backend": "openrouter", "model": "paid-model"})
                return False
            control._WORKER_CONTROLS[ident].stop_event.wait = wait
            try: self.target()
            finally: self.active = False
        def is_alive(self): return self.active
    monkeypatch.setattr(control.threading, "Thread", SynchronousThread)
    result, code = control.start_worker_execution(ident)
    assert code == 200
    assert providers and set(providers) == {"ollama"}
    assert slots.get_system_slot(ident)["status"] == "error"
    assert "neuer Start erforderlich" in slots.get_system_slot(ident)["current_activity"]


def test_custom_system_worker_keeps_admitted_reader_when_session_is_reloaded(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    snapshot = slots.core_system_agents_snapshot()
    result = slots.create_system_slot({"name": "Forschung"}, snapshot["configuration_version"], preset="research")
    ident = result["slot_id"]
    slot = control._execution_worker_slot(ident)
    reader = control._execution_slot_reader(slot)
    session = ChatSession()
    session.chat_id, session.worker_slot_reader, session.require_task_binding = ident, reader, True
    monkeypatch.setattr(control, "_orig_get_session", lambda ignored: session)
    monkeypatch.setitem(control._WORKER_CONTROLS, ident, control._WorkerControl(ident))
    slots.update_slot(ident, {"backend": "openrouter", "model": "changed"})
    assert control._patched_get_session(ident) is session
    assert session.worker_slot_reader is reader
    assert isinstance(ChatRuntime._refresh_worker_tools(session), FailedAnswer)


def test_custom_system_worker_lease_uses_admitted_policy_guard(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    result = slots.create_system_slot({"name": "Entwicklung"}, slots.core_system_agents_snapshot()["configuration_version"], preset="developer")
    ident = result["slot_id"]
    captured = {}
    def acquire(client, slot, **kwargs):
        captured.update(kwargs)
    monkeypatch.setattr(WorkerLeaseBinding, "acquire_next", staticmethod(acquire))
    monkeypatch.setattr(control, "_native_task_client", lambda: object())
    ctrl = control._WorkerControl(ident)
    monkeypatch.setitem(control._WORKER_CONTROLS, ident, ctrl)
    control._acquire_worker_task(ctrl, control._execution_worker_slot(ident), "test-worker")
    assert captured["policy_guard"]()["id"] == ident
    slots.update_slot(ident, {"allow_tools": False})
    with pytest.raises(RuntimeError, match="neuer Start"):
        captured["policy_guard"]()


def test_off_switch_saves_desired_state_and_requests_actual_controller_pause(config_file, monkeypatch):
    from gui.api import unified_api
    calls = []
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda request: "test-device")
    monkeypatch.setattr(adapter, "worker_action", lambda action, body, **kw: calls.append((action, body)) or {"ok":True,"state":"stopping"})
    monkeypatch.setattr(api, "_snapshot", lambda: slots.core_system_agents_snapshot())
    version = slots.core_system_agents_snapshot()["configuration_version"]
    result = asyncio.run(api.toggle_core_system_agent("buddha_always_on", object(), {"enabled":False,"configuration_version":version}))
    assert calls == [("pause", {"id":"buddha_always_on"})]
    assert slots.get_system_slot("buddha_always_on")["enabled"] is False
    assert result["ack"]["controller_action"]["state"] == "stopping"
    assert next(item for item in result["agents"] if item["id"] == "buddha_always_on")["running"] is None


def test_profile_readiness_does_not_replace_active_profile_prompt(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    chat_id = "agent:4:slot:buddha_chat:" + "a" * 32
    session = ChatSession()
    session.custom_system_prompt = "Bound and verified profile context"
    session.system_slot_configuration = {"model": "admitted-model"}
    monkeypatch.setattr(control.runtime, "session_store", SimpleNamespace(load_state=lambda ident: {"binding":{"agent_id":4}}))
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: pytest.fail("Readiness must not create or rebind RAM"))
    monkeypatch.setattr(control, "_get_or_create_backend", lambda *args: object())
    control._snapshot_chat_backend(chat_id, read_only=True)
    assert session.custom_system_prompt == "Bound and verified profile context"
    assert session.system_slot_configuration == {"model":"admitted-model"}


def test_active_slot_snapshot_keeps_profile_prompt_and_admitted_backend(config_file, monkeypatch):
    from hub._services.chat import telegram_chat as control
    chat_id = "agent:4:slot:buddha_chat:" + "a" * 32
    session = ChatSession()
    session.backend, session.model = object(), "admitted-model"
    session.custom_system_prompt = "Bound profile context"
    monkeypatch.setattr(control.runtime, "session_store", SimpleNamespace(load_state=lambda ident: {"binding":{"agent_id":4}}))
    monkeypatch.setattr(control.runtime, "sessions", {chat_id:session})
    monkeypatch.setattr(control.runtime, "_chat_turn_gates", {chat_id:SimpleNamespace(condition=threading.Condition(),active_turns=1)})
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: pytest.fail("Active snapshots must not rebind RAM"))
    backend, model = control._snapshot_chat_backend(chat_id)
    assert backend is session.backend and model == "admitted-model"
    assert session.custom_system_prompt == "Bound profile context"


def test_persisted_profile_slot_chat_resumes_after_runtime_restart(config_file, monkeypatch, tmp_path):
    from hub._services.chat import telegram_chat as control, agent_profile_context as profiles
    from hub._services.chat.session_store import SQLiteChatSessionStore
    from hub._services.llm import model_backend
    db = tmp_path / "profile.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE bach_agents (id INTEGER PRIMARY KEY,name TEXT,version TEXT,is_active INTEGER,priority INTEGER,display_name TEXT,dashboard TEXT)")
        conn.execute("INSERT INTO bach_agents VALUES (1,'persoenlicher-assistent','1.2.0',1,1,'Persönlicher Assistent',NULL)")
        conn.execute("CREATE TABLE bach_experts (id INTEGER PRIMARY KEY,name TEXT,agent_id INTEGER,is_active INTEGER)")
        conn.execute("CREATE TABLE session_snapshots (id INTEGER PRIMARY KEY,session_id TEXT,snapshot_type TEXT,name TEXT,snapshot_data TEXT,created_at TEXT)")
    monkeypatch.setattr(profiles, "BACH_DB", db)
    monkeypatch.setattr(model_backend, "backend_identifier", lambda backend: "ollama")
    slots.update_slot("buddha_chat", {"model":"fixture-model"})
    context = profiles.resolve_profile(1)
    chat_id = "agent:1:slot:buddha_chat:" + "a" * 32
    class Backend:
        manages_own_tools = True
        def __init__(self): self.calls = []
        def get_default_model(self): return "fixture-model"
        def get_context_limit(self): return 32768
        async def chat(self, messages, **kwargs):
            self.calls.append(messages)
            return {"content":"Fixture-Antwort"}
    first = ChatRuntime(Backend(), session_store=SQLiteChatSessionStore(db))
    assert asyncio.run(first.process("Hallo", chat_id, agent_context=context)) == "Fixture-Antwort"
    backend = Backend()
    restored = ChatRuntime(backend, session_store=SQLiteChatSessionStore(db))
    monkeypatch.setattr(control, "runtime", restored)
    monkeypatch.setattr(control, "_get_or_create_backend", lambda *args: backend)
    selected, model = control._snapshot_chat_backend(chat_id)
    assert chat_id not in restored.sessions
    answer = asyncio.run(restored.process("Weiter", chat_id, agent_context=context, backend=selected, model=model))
    assert answer == "Fixture-Antwort"
    assert len(backend.calls) == 1
    assert context[1].strip() in backend.calls[0][0]["content"]
    assert restored.get_session(chat_id).profile_binding == context[0]
    assert len(restored.session_store.load_state(chat_id)["messages"]) == 4


def test_dynamic_worker_uses_its_authority_without_an_unrelated_system_slot_read(tmp_path, monkeypatch):
    from hub._services.chat import telegram_chat as control
    absent = tmp_path / "absent-default-slots.json"
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(absent))
    worker = {"id":"arbitrary-worker", "backend":"ollama", "model":"fixture-model"}
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: worker)
    assert control._execution_worker_slot("arbitrary-worker") is worker
    assert not absent.exists()


def test_unknown_ordinary_chat_does_not_require_a_second_worker_authority(tmp_path, monkeypatch):
    from hub._services.chat import telegram_chat as control
    absent = tmp_path / "absent-default-slots.json"
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(absent))
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: {})
    assert control._execution_worker_slot("api-delegate") == {}
    assert not absent.exists()


@pytest.mark.parametrize("preset", ["companion", "guardian", "connector", "coordinator", "engineer", "researcher"])
def test_portrait_preset_is_valid_but_arbitrary_asset_paths_are_not(preset):
    assert slots.validate_agent_avatar("preset:" + preset) == "preset:" + preset
    for value in ("preset:unknown", "/_astro/foreign.png", "https://example.org/image.png"):
        with pytest.raises(ValueError): slots.validate_agent_avatar(value)


def _legacy_always_on_config(config_file):
    """Persist the older valid core-worker shape, without injected UI defaults."""
    from pathlib import Path
    path = Path(config_file)
    config = json.loads(path.read_text(encoding="utf-8"))
    config["slots"]["buddha_always_on"] = {
        "id": "buddha_always_on", "name": "Buddha Always-On", "enabled": True,
        "backend": "ollama", "model": "fixture-model", "mode": "full",
        "think": True, "max_tool_rounds": 25, "category": "all",
        "status": "idle", "current_activity": "", "pause_after": 5,
        "pause_minutes": 1, "pause_basis": "runs", "pause_counter": 0,
        "pause_started_at": "",
        "pickup_filter": {"enabled": True, "categories": ["INBOX", "WORKER"],
                          "priorities": ["P1", "P2"], "tags": [],
                          "exclude_tags": ["delegated", "waiting"]},
    }
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path, config


def test_fixed_always_on_cas_admission_accepts_unchanged_persisted_policy(config_file):
    from hub._services.chat import telegram_chat as control
    path, _ = _legacy_always_on_config(config_file)
    version = slots.core_system_agents_snapshot()["configuration_version"]
    admitted = slots.system_worker_at_version("buddha_always_on", version)
    reader = control._execution_slot_reader(admitted)
    current = reader()  # The real first gate before assignment or thread launch.
    assert current["id"] == "buddha_always_on"
    assert current["model"] == "fixture-model"
    assert current["type"] == "continuous" and current["sub_mode"] == "task_worker"
    assert "custom_system_prompt" not in admitted and "skill_refs" not in admitted
    assert json.loads(path.read_text(encoding="utf-8"))["slots"]["buddha_always_on"]["status"] == "idle"


@pytest.mark.parametrize("field,value", [
    ("backend", "openrouter"), ("enabled", False),
    ("custom_system_prompt", ""), ("custom_role_prompt", ""),
    ("role_id", "hintergrund_worker"), ("skill_refs", []),
], ids=["provider", "disabled", "system-prompt", "role-prompt", "role", "skills"])
def test_fixed_always_on_cas_reader_rejects_later_authority_change(config_file, field, value):
    from hub._services.chat import telegram_chat as control
    path, config = _legacy_always_on_config(config_file)
    version = slots.core_system_agents_snapshot()["configuration_version"]
    admitted = slots.system_worker_at_version("buddha_always_on", version)
    reader = control._execution_slot_reader(admitted)
    assert reader()["model"] == "fixture-model"
    config["slots"]["buddha_always_on"][field] = value
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="neuer Start erforderlich"):
        reader()
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.system_worker_at_version("buddha_always_on", version)


def test_fixed_always_on_cas_uses_only_its_one_verified_file_image(config_file, monkeypatch):
    from pathlib import Path
    path, _ = _legacy_always_on_config(config_file)
    version = slots.core_system_agents_snapshot()["configuration_version"]
    original_read = Path.read_bytes
    reads = []
    def read_once(target):
        assert target == path
        reads.append(target)
        assert len(reads) == 1
        return original_read(target)
    def no_second_read(*args, **kwargs):
        pytest.fail("CAS admission must not reread the persisted configuration")
    monkeypatch.setattr(Path, "read_bytes", read_once)
    monkeypatch.setattr(Path, "read_text", no_second_read)
    admitted = slots.system_worker_at_version("buddha_always_on", version)
    assert admitted["model"] == "fixture-model"
    assert admitted["sub_mode"] == "task_worker"
    assert "role_id" not in admitted
    assert len(reads) == 1


@pytest.mark.parametrize("invalid", ["enabled", "shadow", "type"])
def test_fixed_always_on_cas_preserves_strict_admission_checks(config_file, invalid):
    path, config = _legacy_always_on_config(config_file)
    if invalid == "enabled":
        config["slots"]["buddha_always_on"]["enabled"] = 1
    elif invalid == "shadow":
        config["dynamic_workers"].append({"id": "buddha_always_on", "type": "continuous"})
    else:
        config["slots"]["buddha_always_on"]["type"] = "persistent"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    version = slots.core_system_agents_snapshot()["configuration_version"]
    with pytest.raises(ValueError):
        slots.system_worker_at_version("buddha_always_on", version)
