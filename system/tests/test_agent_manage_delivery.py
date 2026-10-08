"""Native agent tools use actual blueprint/config state and owned callbacks."""
import importlib
import json
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hub._services import blueprint_service
from hub._services.agent_manage_service import AgentManager
from hub._services.chat import bach_tools, slots_config as slots

GRANTS = {"read_file", "list_directory", "search_text", "task_manage", "agent_manage", "skill_create"}


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    database = tmp_path / "tasks.db"
    with sqlite3.connect(database) as conn:
        blueprint_service.ensure_blueprint_schema(conn)
    receipt = Mock(return_value={"state": "idle", "service_instance": "owned-service"})
    start = Mock(return_value=({"execution": {"worker_thread_started": True, "state": "running"}}, 200))
    provider = Mock(return_value=True)
    guard = Mock()
    manager = AgentManager(db_path=database, slots_path=path, execution_receipt=receipt,
        start_worker=start, local_provider=provider, guard=guard)
    return SimpleNamespace(path=path, database=database, manager=manager, start=start,
        receipt=receipt, provider=provider, guard=guard)


def invoke(state, payload, mode="safe", grants=GRANTS):
    return state.manager(payload, mode=mode, allowed_tools=grants)


def create(state, **changes):
    return invoke(state, {"action": "blueprint_create", "blueprint": {
        "name": "created-expert", "title": "Eigene Expertin", "persona_prompt": "Prüfe den Auftrag.",
        "skills": [], "governance": {"tool_whitelist": ["read_file", "task_manage"]}, **changes}})


def configure(state, **execution):
    bp = create(state)
    result = invoke(state, {"action": "materialize", "blueprint_id": bp["id"], "expected_version": bp["version"],
        "configuration_version": slots.core_system_agents_snapshot()["configuration_version"],
        "execution": {"backend": "ollama", "model": "owned-local", "mode": "safe", **execution}})
    return bp, result


def start(state, slot_id, **changes):
    return invoke(state, {"action": "start_local", "slot_id": slot_id,
        "configuration_version": slots.core_system_agents_snapshot()["configuration_version"], **changes})


def test_create_materialize_list_and_start_use_real_state(state):
    bp, configured = configure(state)
    assert bp["worker_started"] is False and configured["worker_started"] is False
    assert not state.start.called
    slot = slots.get_system_slot(configured["slot_id"])
    assert slot["blueprint_id"] == bp["id"] and slot["blueprint_version"] == bp["version"]
    assert slot["require_assigned_slot"] is True
    catalog = invoke(state, {"action": "list"})
    assert catalog["source"] == "native_controller" and len(catalog["agents"]) == 7
    assert next(a for a in catalog["agents"] if a["id"] == slot["id"])["execution_kind"] == "worker"
    result = start(state, slot["id"])
    assert result["cloud_started"] is False
    args, kwargs = state.start.call_args
    assert args == (slot["id"],) and kwargs["expected_service_instance"] == "owned-service"
    assert kwargs["expected_configuration_version"] == catalog["configuration_version"]
    assert len(kwargs["start_request_id"]) == 32
    assert state.guard.call_count >= 5


def test_agent_cannot_edit_existing_blueprint_or_slot(state):
    bp, configured = configure(state)
    with pytest.raises(RuntimeError, match="version_conflict"):
        create(state)
    with pytest.raises(PermissionError):
        invoke(state, {"action": "materialize", "blueprint_id": bp["id"], "expected_version": bp["version"],
            "configuration_version": configured["configuration_version"], "execution": {"model": "another"}})
    assert slots.get_system_slot(configured["slot_id"])["model"] == "owned-local"
    state.start.assert_not_called()


@pytest.mark.parametrize("extra", [{"is_template": True}, {"expected_version": 1},
    {"governance": {"tool_whitelist": ["execute_command"]}}, {"governance": []}])
def test_creation_cannot_raise_privileges(state, extra):
    with pytest.raises((PermissionError, ValueError)):
        create(state, **extra)
    with sqlite3.connect(state.database) as conn:
        assert conn.execute("SELECT count(*) FROM agent_blueprints").fetchone()[0] == 0


@pytest.mark.parametrize("backend,model", [("openrouter", "openrouter/free"), ("ollama-cloud", "owned-local"),
    ("claude", "subscription"), ("ollama", "qwen:cloud"), ("ollama", "")])
def test_agent_cannot_start_cloud_or_implicit_model(state, backend, model):
    slot_id = slots.create_system_slot({"name": "Bound", "backend": backend, "model": model or "temporary-explicit",
        "allowed_tools": ["read_file"]}, slots.core_system_agents_snapshot()["configuration_version"])["slot_id"]
    if not model: slots.update_slot(slot_id, {"model": ""})
    with pytest.raises(PermissionError):
        start(state, slot_id)
    state.start.assert_not_called()


@pytest.mark.parametrize("kind", ["nonlocal-endpoint", "cloud-alias", "disabled", "mode", "tools", "active", "unknown", "stale"])
def test_local_start_requires_verified_current_authority(state, kind):
    _, result = configure(state)
    slot_id = result["slot_id"]
    if kind == "nonlocal-endpoint": state.provider.return_value = False
    if kind == "cloud-alias": slots.update_slot(slot_id, {"resolved_model": "other:cloud"})
    if kind == "disabled": slots.update_slot(slot_id, {"enabled": False})
    if kind == "mode": slots.update_slot(slot_id, {"mode": "full"})
    if kind == "tools": slots.update_slot(slot_id, {"allowed_tools": ["write_file"]})
    if kind == "active": state.receipt.return_value = {"state": "running", "service_instance": "owned-service"}
    if kind == "unknown": state.receipt.return_value = {"state": "unconfirmed", "service_instance": "owned-service"}
    extra = {"configuration_version": "a" * 64} if kind == "stale" else {}
    with pytest.raises((PermissionError, RuntimeError)):
        start(state, slot_id, **extra)
    state.start.assert_not_called()


def test_materialize_cannot_raise_mode_or_reuse_stale_blueprint(state):
    bp = create(state)
    payload = {"action": "materialize", "blueprint_id": bp["id"], "expected_version": bp["version"],
        "configuration_version": slots.core_system_agents_snapshot()["configuration_version"],
        "execution": {"backend": "ollama", "model": "explicit", "mode": "full"}}
    with pytest.raises(PermissionError): invoke(state, payload)
    payload["execution"]["mode"] = "safe"
    payload["expected_version"] = 90
    with pytest.raises(RuntimeError, match="version_conflict"): invoke(state, payload)
    assert not slots.get_system_slot(f"system-blueprint-{bp['id']}")


def test_inherited_grants_and_dynamic_workers_use_same_controller(state):
    worker = slots.add_worker({"name": "Dynamic", "backend": "ollama", "model": "owned-local",
        "mode": "safe", "allowed_tools": ["read_file"]}, state.path)
    assert worker["id"] in {a["id"] for a in invoke(state, {"action": "list"})["agents"]}
    start(state, worker["id"])
    assert state.start.call_args.args == (worker["id"],)
    slots.update_slot(worker["id"], {"allowed_tools": None})
    state.start.reset_mock()
    with pytest.raises(PermissionError): start(state, worker["id"])
    full_grants = {t["function"]["name"] for t in bach_tools.tools_for_mode("safe", bound_worker=True)}
    invoke(state, {"action": "start_local", "slot_id": worker["id"],
        "configuration_version": slots.core_system_agents_snapshot()["configuration_version"]}, grants=full_grants)
    assert state.start.called


def test_unconfirmed_start_never_returns_success(state):
    _, result = configure(state)
    state.start.return_value = ({"execution": {"worker_thread_started": False}}, 202)
    with pytest.raises(RuntimeError, match="nicht bestätigt"): start(state, result["slot_id"])


def test_missing_database_unknown_locks_and_plan_mode_fail_closed(state, tmp_path):
    state.manager.db_path = tmp_path / "absent.db"
    with pytest.raises(RuntimeError, match="TaskDB fehlt"): create(state)
    assert not state.manager.db_path.exists()
    state.manager.db_path = state.database
    state.guard.side_effect = PermissionError("Ungeprüft")
    with pytest.raises(PermissionError): create(state)
    with pytest.raises(PermissionError): invoke(state, {"action": "start_local"}, mode="plan")
    state.start.assert_not_called()


def test_skill_and_agent_tools_are_granted_bound_and_excluded_from_plan(monkeypatch):
    callbacks = Mock(return_value={"success": True})
    assert "nicht freigegeben" in bach_tools.exec_tool("agent_manage", {"action": "list"}, "safe",
        agent_operations=callbacks, allowed_tools={"read_file"})
    assert "Taskbindung fehlt" in bach_tools.exec_tool("agent_manage", {"action": "list"}, "safe",
        agent_operations=callbacks, require_task_binding=True)
    for name in ("agent_manage", "skill_create"):
        assert name not in {t["function"]["name"] for t in bach_tools.tools_for_mode("plan")}
        assert "BLOCKIERT" in bach_tools.exec_tool(name, {}, "plan", agent_operations=callbacks)
    callbacks.assert_not_called()
    binding = SimpleNamespace(assert_active=Mock(side_effect=RuntimeError("revoked")))
    assert "BLOCKIERT" in bach_tools.exec_tool("agent_manage", {}, "safe", worker_task_binding=binding, agent_operations=callbacks)
    callbacks.assert_not_called()
    provider = bach_tools.BachToolProvider(agent_operations=callbacks, allowed_tools=GRANTS)
    assert json.loads(provider.execute("agent_manage", {"action": "list"}, "safe"))["success"] is True
    assert callbacks.call_args.kwargs["allowed_tools"] == GRANTS


def test_startup_adds_fixed_slots_once_without_changing_user_configuration(state):
    original = json.loads(open(state.path, encoding="utf-8").read())
    for key in ("buddha_boss", "buddha_developer", "buddha_research"): original["slots"].pop(key)
    original["slots"]["buddha_chat"].update(model="user-selected", backend="lmstudio", custom_role_prompt="Meine Rolle")
    original["private_field"] = {"preserve": True}
    original["prompts"] = {"system": "Nutzerregeln"}
    with open(state.path, "w", encoding="utf-8") as stream: json.dump(original, stream, ensure_ascii=False)
    assert len(slots.core_system_agents_snapshot()["agents"]) == 3
    assert slots.initialize_system_slots(state.path) is True
    actual = json.loads(open(state.path, encoding="utf-8").read())
    assert actual["slots"]["buddha_chat"] == original["slots"]["buddha_chat"]
    assert actual["private_field"] == original["private_field"] and actual["prompts"] == original["prompts"]
    for key in ("buddha_boss", "buddha_developer", "buddha_research"):
        assert actual["slots"][key]["model"] == "user-selected" and actual["slots"][key]["backend"] == "lmstudio"
        assert actual["slots"][key]["status"] == "idle" and actual["slots"][key]["require_assigned_slot"] is True
    before = open(state.path, "rb").read()
    assert slots.initialize_system_slots(state.path) is False
    assert open(state.path, "rb").read() == before


def test_continuous_worker_keeps_actual_task_release_receipts_when_waiting(monkeypatch):
    control_module = importlib.import_module("hub._services.chat.telegram_chat")
    control = control_module._WorkerControl("slot", start_request_id="a" * 32)
    control.task_binding = SimpleNamespace(completed_task_ids=(1834,), reviewed_task_ids=(90,))
    control_module._retain_worker_task_receipts(control)
    control.task_binding = None
    monkeypatch.setattr(control_module, "_execution_worker_slot", lambda ident: {"status": "idle"})
    receipt = control_module._control_execution_receipt(control)
    assert receipt["completed_task_ids"] == [1834] and receipt["reviewed_task_ids"] == [90]
    control.task_binding = SimpleNamespace(completed_task_ids=(1835,), reviewed_task_ids=())
    control_module._retain_worker_task_receipts(control)
    control.task_binding = None
    assert control_module._control_execution_receipt(control)["completed_task_ids"] == [1834, 1835]


def test_chat_task_creation_update_and_decomposition_persist_slot_binding(tmp_path, monkeypatch):
    database = tmp_path / "tasks.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, description TEXT, category TEXT, "
            "depends_on TEXT, priority TEXT, status TEXT, assigned_to TEXT, created_at TEXT, updated_at TEXT, "
            "completed_at TEXT, assigned_slot TEXT, required_model TEXT)")
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: database)
    monkeypatch.setattr(bach_tools, "_current_apply_task_field_changes", lambda: None)
    result = bach_tools.exec_tool("task_manage", {"action": "add", "title": "Überprüfen",
        "assigned_slot": "buddha_developer", "required_model": "explicit-model"}, "safe")
    assert "Task #1 erstellt" in result
    result = bach_tools.exec_tool("task_manage", {"action": "update", "task_id": 1,
        "assigned_slot": "buddha_research"}, "safe")
    assert "aktualisiert" in result
    result = bach_tools.exec_tool("task_manage", {"action": "decompose", "task_id": 1, "close_parent": False,
        "sequential": True, "subtasks": [{"title": "Erster Schritt", "assigned_slot": "buddha_research"},
        {"title": "Zweiter Schritt", "assigned_slot": "buddha_developer", "required_model": "another-model"}]}, "safe")
    assert "2 Teilaufgaben" in result
    with sqlite3.connect(database) as conn:
        rows = conn.execute("SELECT assigned_slot, required_model, depends_on FROM tasks ORDER BY id").fetchall()
    assert rows == [("buddha_research", "explicit-model", ""), ("buddha_research", None, ""),
        ("buddha_developer", "another-model", "2")]


def test_materialize_race_cannot_validate_one_revision_and_use_another(state, monkeypatch):
    bp = create(state)
    original_connect = sqlite3.connect
    class Connection:
        def __init__(self, *args, **kwargs): self.conn = original_connect(*args, **kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): return self.conn.__exit__(*args)
        def __getattr__(self, name): return getattr(self.conn, name)
        def execute(self, query, *args):
            cursor = self.conn.execute(query, *args)
            if query.startswith("SELECT governance_json"):
                previous = cursor.fetchone()
                with original_connect(state.database) as other:
                    blueprint_service.save_blueprint(other, {"name": "created-expert", "title": "Eigene Expertin",
                        "persona_prompt": "Prüfe den Auftrag.", "expected_version": 1,
                        "governance": {"tool_whitelist": ["read_file", "write_file"]}})
                return SimpleNamespace(fetchone=lambda: previous)
            return cursor
    monkeypatch.setattr(sqlite3, "connect", Connection)
    with pytest.raises(RuntimeError, match="blueprint_version_conflict"):
        invoke(state, {"action": "materialize", "blueprint_id": bp["id"], "expected_version": 2,
            "configuration_version": slots.core_system_agents_snapshot()["configuration_version"],
            "execution": {"backend": "ollama", "model": "local", "mode": "safe"}})
    assert not slots.get_system_slot(f"system-blueprint-{bp['id']}")


@pytest.mark.parametrize("payload,expected", [
    ({"details": {"format": "safetensors"}, "model_info": {"general.parameter_count": 27800000000}}, True),
    ({"details": {"format": "gguf"}, "model_info": {"general.parameter_count": 4}, "remote_host": "https://ollama.com"}, False),
    ({"details": {"format": "gguf"}, "model_info": {"general.parameter_count": 4}, "remote_model": "paid-upstream"}, False),
    ({}, False), ({"details": {"format": "gguf"}, "model_info": {}}, False),
    ({"details": {"format": "unknown"}, "model_info": {"general.parameter_count": 4}}, False),
    ([], False), (None, False)])
def test_local_ollama_model_verification_uses_remote_metadata_even_for_renamed_alias(monkeypatch, payload, expected):
    import httpx
    from hub._services.agent_manage_service import verified_local_agent_model
    from hub._services.llm.model_backend import OllamaBackend
    request = Mock(return_value=SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload))
    monkeypatch.setattr(httpx, "post", request)
    assert verified_local_agent_model(OllamaBackend(base_url="http://localhost:11434"), "friendly-alias") is expected
    assert request.call_args.kwargs["json"] == {"model": "friendly-alias"}
    assert request.call_args.kwargs["follow_redirects"] is False


def test_unknown_or_remote_provider_never_gets_an_agent_model_request(monkeypatch):
    import httpx
    from hub._services.agent_manage_service import verified_local_agent_model
    from hub._services.llm.model_backend import OllamaBackend, OpenRouterBackend
    request = Mock()
    monkeypatch.setattr(httpx, "post", request)
    assert not verified_local_agent_model(OllamaBackend(base_url="https://ollama.com"), "renamed")
    assert not verified_local_agent_model(OllamaBackend(), "auto")
    assert not verified_local_agent_model(OpenRouterBackend(api_key="fixture-only"), "openrouter/free")
    request.assert_not_called()


@pytest.mark.parametrize("payload,expected", [
    ({"models": [{"key": "local", "type": "llm", "size_bytes": 1000000}]}, True),
    ({"models": [{"key": "local", "type": "llm", "size_bytes": 0}]}, False),
    ({"models": [{"key": "local", "type": "llm", "size_bytes": 1000000, "remote_model": "paid"}]}, False),
    ({"models": []}, False)])
def test_lmstudio_native_model_inventory_confirms_local_downloads(monkeypatch, payload, expected):
    import httpx
    from hub._services.agent_manage_service import verified_local_agent_model
    from hub._services.llm.model_backend import LMStudioBackend
    request = Mock(return_value=SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: payload))
    monkeypatch.setattr(httpx, "get", request)
    assert verified_local_agent_model(LMStudioBackend(), "local") is expected
    assert request.call_args.args == ("http://localhost:1234/api/v1/models",)
