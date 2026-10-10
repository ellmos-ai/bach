"""Model/socket identity, canonical CAS, binding admission and device authorization."""
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from hub._services.chat import model_sockets as models, slots_config as slots
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.llm.model_backend import OllamaBackend
from gui.api import model_sockets as api, unified_api


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(models.platform, "node", lambda: "test-host")
    from hub._services import skill_source_service
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda target: None)
    return path


def version():
    return slots.core_system_agents_snapshot()["configuration_version"]


def migrated():
    return models.migrate_model_sockets(version())


def test_legacy_read_projects_one_model_with_stable_agent_ids_without_write(registry):
    from pathlib import Path
    before = Path(registry).read_bytes()
    view = models.model_sockets_snapshot()
    assert Path(registry).read_bytes() == before
    assert view["migration_required"] and view["source"] == "legacy_projection"
    assert len(view["sockets"]) == 1
    assert {b["agent_id"] for b in view["sockets"][0]["slots"]} == set(slots.CORE_SYSTEM_AGENT_IDS)
    assert view["sockets"][0]["residency"] == "unknown"
    assert view["sockets"][0]["resource_share"] is None
    assert not view["runtime_verified"]


def test_explicit_migration_preserves_profiles_tasks_history_and_foreign_fields(registry):
    config = slots.load_slots_config()
    config["slots"]["buddha_always_on"]["model"] = "qwen3.8:4b"
    config["slots"]["buddha_chat"]["task_id"] = 42
    config["private_extension"] = {"keep": "äöüß"}
    config["activity_history"] = [{"task_id": 42, "status": "running"}]
    slots.save_slots_config(config)
    before = copy.deepcopy(config)
    view = migrated()
    after = slots.load_slots_config()
    for key in ("slots", "dynamic_workers", "activity_history", "private_extension"):
        assert after[key] == before[key]
    assert len(view["sockets"]) == 2 and not view["migration_required"]
    assert after["version"] == 4
    with pytest.raises(ValueError, match="bereits migriert"):
        models.migrate_model_sockets(version())


@pytest.mark.parametrize("backend,model", [("openrouter", "openrouter/free"),
                                          ("ollama-cloud", "glm-5.3:cloud"),
                                          ("ollama", "glm-5.3:cloud"), ("codex", "default")])
def test_external_targets_create_no_socket_and_hold_no_local_resources(registry, backend, model):
    slots.change_core_system_agent("buddha_chat", version(), {"backend": backend, "model": model})
    view = migrated()
    assert "buddha_chat" in view["unbound_agent_ids"]
    assert not any(b["agent_id"] == "buddha_chat" for s in view["sockets"] for b in s["slots"])
    with pytest.raises(ValueError):
        models.socket_id(backend, model, "test-host")


def test_offered_model_is_registered_without_agent_or_residency_claim(registry):
    initial = migrated()
    updated = models.configure_model_socket(initial["configuration_version"],
        {"backend": "ollama", "model": "other:4b", "max_active_slots": 1000, "residency_policy": "shared"})
    target = next(s for s in updated["sockets"] if s["model"] == "other:4b")
    assert target["slots"] == [] and target["max_active_slots"] == 1000
    assert target["effective_max_active_slots"] == 1 and not target["capacity_verified"]
    assert target["weight_bytes"] is None and target["resource_share"] is None
    assert slots.get_system_slot("buddha_chat")["model"] == "qwen3.8:27b-mlx"


def test_external_agent_can_hold_inactive_local_fallback_binding(registry):
    slots.change_core_system_agent("buddha_chat", version(), {"backend": "openrouter", "model": "openrouter/free"})
    view = migrated()
    target_id = view["sockets"][0]["id"]
    bound = models.bind_model_agent(view["configuration_version"], "buddha_chat", target_id,
                                  {"priority": "foreground", "context_tokens": 8192})
    binding = next(b for s in bound["sockets"] for b in s["slots"] if b["agent_id"] == "buddha_chat")
    assert binding["running"] is None and binding["resource_share"] is None
    again = models.bind_model_agent(bound["configuration_version"], "buddha_chat", target_id)
    assert len([b for s in again["sockets"] for b in s["slots"] if b["agent_id"] == "buddha_chat"]) == 1
    assert slots.get_system_slot("buddha_chat")["backend"] == "openrouter"


@pytest.mark.parametrize("changes", [{"max_active_slots": True}, {"max_active_slots": 0},
    {"max_active_slots": 1001}, {"enabled": 1}, {"residency_policy": "guaranteed"},
    {"host_id": "another-host"}, {"api_key": "never-persist"}])
def test_invalid_socket_edits_do_not_write(registry, changes):
    from pathlib import Path
    view = migrated()
    before = Path(registry).read_bytes()
    with pytest.raises(ValueError):
        models.configure_model_socket(view["configuration_version"],
                                     {"backend": "ollama", "model": "qwen3.8:27b-mlx", **changes})
    assert Path(registry).read_bytes() == before


def test_all_mutations_share_existing_core_cas(registry):
    view = migrated()
    old = view["configuration_version"]
    slots.change_core_system_agent("buddha_chat", old, {"name": "Neue Instanz"})
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        models.bind_model_agent(old, "buddha_chat", view["sockets"][0]["id"])
    fresh = version()
    models.configure_model_socket(fresh, {"backend": "ollama", "model": "other:4b"})
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_core_system_agent("buddha_chat", fresh, {"name": "Veraltet"})


def test_concurrent_cas_has_exactly_one_winner(registry):
    view = migrated()
    def update(model):
        try:
            models.configure_model_socket(view["configuration_version"], {"backend": "ollama", "model": model})
            return "saved"
        except RuntimeError as exc:
            return str(exc)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(update, ["one:4b", "two:4b"]))
    assert sorted(results) == ["configuration_version_conflict", "saved"]


def test_lock_denial_does_not_write(registry, monkeypatch):
    from pathlib import Path
    from hub._services import skill_source_service
    before = Path(registry).read_bytes()
    def deny(target):
        assert str(target) == registry
        raise RuntimeError("locked")
    monkeypatch.setattr(skill_source_service, "check_write_locks", deny)
    with pytest.raises(RuntimeError, match="locked"):
        models.migrate_model_sockets(version())
    assert Path(registry).read_bytes() == before


def test_binding_is_actual_target_and_enabled_state_specific(registry):
    view = migrated()
    proof = models.require_model_binding("buddha_chat", "ollama", "qwen3.8:27b-mlx")
    assert proof["agent_id"] == "buddha_chat" and proof["socket_id"] == view["sockets"][0]["id"]
    with pytest.raises(RuntimeError, match="binding_unavailable"):
        models.require_model_binding("buddha_chat", "ollama", "another:4b")
    models.bind_model_agent(version(), "buddha_chat", proof["socket_id"], {"enabled": False})
    with pytest.raises(RuntimeError, match="binding_unavailable"):
        models.require_model_binding("buddha_chat", "ollama", "qwen3.8:27b-mlx")


def test_binding_removal_preserves_profile_and_denies_local_call(registry):
    migrated()
    proof = models.require_model_binding("buddha_chat", "ollama", "qwen3.8:27b-mlx")
    models.remove_model_binding(version(), proof["binding_id"])
    assert slots.get_system_slot("buddha_chat")["id"] == "buddha_chat"
    with pytest.raises(RuntimeError, match="binding_unavailable"):
        models.require_model_binding("buddha_chat", "ollama", "qwen3.8:27b-mlx")


@pytest.mark.parametrize("corruption", ["schema", "id", "host", "binding", "unknown"])
def test_present_invalid_state_fails_closed_without_repair(registry, corruption):
    from pathlib import Path
    migrated()
    config = slots.load_slots_config()
    state = config["model_sockets"]
    target = next(iter(state["sockets"].values()))
    binding = next(iter(state["bindings"].values()))
    if corruption == "schema": state["schema"] = "future-unverified"
    if corruption == "id": target["id"] = "model-wrong"
    if corruption == "host": target["host_id"] = "another-host"
    if corruption == "binding": binding["socket_id"] = "missing"
    if corruption == "unknown": state["grant"] = "unverified"
    slots.save_slots_config(config)
    before = Path(registry).read_bytes()
    with pytest.raises(ValueError):
        models.model_sockets_snapshot()
    assert Path(registry).read_bytes() == before


def test_aliases_require_exact_unambiguous_persisted_mapping(registry):
    assert models.configured_agent_for_chat("gui-web") == "buddha_chat"
    assert models.configured_agent_for_chat("telegram:unverified") is None
    config = slots.load_slots_config()
    config["slots"]["buddha_connector"]["chat_id"] = "gui-web"
    slots.save_slots_config(config)
    with pytest.raises(RuntimeError, match="ambiguous"):
        models.configured_agent_for_chat("gui-web")


def test_native_missing_registry_denies_but_standalone_legacy_remains_explicit(tmp_path):
    absent = str(tmp_path / "absent.json")
    assert models.model_binding_for_call("gui-web", "ollama", "m", path=absent) is None
    with pytest.raises(RuntimeError, match="config_unavailable"):
        models.model_binding_for_call("gui-web", "ollama", "m", path=absent, require_config=True)


@pytest.mark.parametrize("format_version", [4, 5])
def test_missing_registry_after_migration_denies_all_reads_and_remigration(registry, format_version):
    from pathlib import Path
    migrated()
    config = slots.load_slots_config()
    del config["model_sockets"]
    config["version"] = format_version
    slots.save_slots_config(config)
    before = Path(registry).read_bytes()
    readers = [models.model_sockets_snapshot,
        lambda: models.require_model_binding("buddha_chat", "ollama", "qwen3.8:27b-mlx"),
        lambda: models.model_binding_for_call("gui-web", "ollama", "qwen3.8:27b-mlx"),
        lambda: models.model_binding_for_call("gui-web", "ollama", "qwen3.8:27b-mlx", require_config=True),
        lambda: models.migrate_model_sockets(version())]
    for read in readers:
        with pytest.raises(ValueError, match="Registry|registry"):
            read()
    assert Path(registry).read_bytes() == before


@pytest.mark.parametrize("format_version", [True, "4", 0, None])
def test_invalid_format_version_cannot_enable_legacy_admission(registry, format_version):
    config = slots.load_slots_config()
    config["version"] = format_version
    slots.save_slots_config(config)
    with pytest.raises(ValueError, match="Formatversion|formatversion"):
        models.model_binding_for_call("gui-web", "ollama", "qwen3.8:27b-mlx", require_config=True)


@pytest.mark.parametrize("format_version", [3, 4])
def test_runtime_missing_migrated_registry_never_dispatches_locally(registry, format_version):
    migrated()
    config = slots.load_slots_config()
    del config["model_sockets"]
    config["version"] = format_version
    slots.save_slots_config(config)
    backend = OllamaBackend()
    backend.chat = AsyncMock()
    runtime = ChatRuntime(backend=backend)
    runtime.require_model_socket_config = True
    async def run():
        token = runtime._compute_turn_context.set(("gui-web", "foreground"))
        try:
            with pytest.raises((ValueError, RuntimeError), match="Registry|registry"):
                await runtime._chat_with_compute_turn(backend, [], model="qwen3.8:27b-mlx")
        finally:
            runtime._compute_turn_context.reset(token)
    asyncio.run(run())
    backend.chat.assert_not_awaited()
    assert not HostInferenceGate().status()["active"]


@pytest.mark.parametrize("format_version", [1, 2, 3])
def test_native_legacy_registry_requires_explicit_migration(registry, format_version):
    config = slots.load_slots_config()
    config["version"] = format_version
    slots.save_slots_config(config)
    assert models.model_sockets_snapshot()["migration_required"]
    assert models.model_binding_for_call("gui-web", "ollama", "qwen3.8:27b-mlx") is None
    with pytest.raises(RuntimeError, match="registry_unavailable"):
        models.model_binding_for_call("gui-web", "ollama", "qwen3.8:27b-mlx", require_config=True)
    view = migrated()
    proof = models.model_binding_for_call("gui-web", "ollama", "qwen3.8:27b-mlx", require_config=True)
    assert proof["socket_id"] == view["sockets"][0]["id"]


def test_runtime_admits_actual_bound_target_and_publishes_host_owner(registry):
    migrated()
    seen = []
    async def answer(*args, **kwargs):
        status = HostInferenceGate().status()
        seen.append(status)
        return "answer"
    backend = OllamaBackend()
    backend.chat = AsyncMock(side_effect=answer)
    runtime = ChatRuntime(backend=backend)
    runtime.require_model_socket_config = True
    async def run():
        token = runtime._compute_turn_context.set(("gui-web", "foreground"))
        try:
            return await runtime._chat_with_compute_turn(backend, [], model="qwen3.8:27b-mlx")
        finally:
            runtime._compute_turn_context.reset(token)
    assert asyncio.run(run()) == "answer"
    assert seen[0]["active"] and seen[0]["model_target"]["agent_id"] == "buddha_chat"
    assert seen[0]["model_target"]["model"] == "qwen3.8:27b-mlx"
    assert not HostInferenceGate().status()["active"]


def test_runtime_revocation_while_waiting_prevents_backend_dispatch(registry):
    view = migrated()
    backend = OllamaBackend()
    backend.chat = AsyncMock()
    runtime = ChatRuntime(backend=backend)
    async def run():
        async with HostInferenceGate().turn("other", "foreground"):
            token = runtime._compute_turn_context.set(("gui-web", "foreground"))
            try:
                pending = asyncio.create_task(runtime._chat_with_compute_turn(backend, [], model="qwen3.8:27b-mlx"))
            finally:
                runtime._compute_turn_context.reset(token)
            await asyncio.sleep(.05)
            models.configure_model_socket(version(), {"backend": "ollama", "model": "qwen3.8:27b-mlx", "enabled": False})
            with pytest.raises(RuntimeError, match="binding_unavailable"):
                await asyncio.wait_for(pending, 2)
        backend.chat.assert_not_awaited()
    asyncio.run(run())
    assert view["sockets"][0]["enabled"]


def test_cloud_proxy_bypasses_local_binding_and_torch(registry):
    migrated()
    backend = OllamaBackend()
    backend.chat = AsyncMock(return_value="cloud")
    runtime = ChatRuntime(backend=backend)
    assert asyncio.run(runtime._chat_with_compute_turn(backend, [], model="glm-5.3:cloud")) == "cloud"
    assert not HostInferenceGate().status()["active"]


def test_api_requires_device_before_any_migration_write(registry, monkeypatch):
    from pathlib import Path
    before = Path(registry).read_bytes()
    def deny(request):
        raise HTTPException(403, "device required")
    monkeypatch.setattr(unified_api, "_require_memory_device_token", deny)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.migrate_model_sockets(object(), {"configuration_version": version()}))
    assert error.value.status_code == 403 and Path(registry).read_bytes() == before


def test_api_migration_and_conflict_ack_never_claim_worker_start(registry, monkeypatch):
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda request: "verified-test-device")
    old = version()
    result = asyncio.run(api.migrate_model_sockets(object(), {"configuration_version": old}))
    assert result["ack"] == {"configuration_saved": True, "worker_started": False, "runtime_verified": False}
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.configure_model_socket(object(), {"configuration_version": old, "changes": {"backend": "ollama", "model": "other"}}))
    assert error.value.status_code == 409


def test_alias_target_and_binding_use_one_file_image(registry, monkeypatch):
    migrated()
    original = models._read
    calls = []
    def once(path=None):
        calls.append(path)
        assert len(calls) == 1
        return original(path)
    monkeypatch.setattr(models, "_read", once)
    proof = models.model_binding_for_call("gui-web", "ollama", "qwen3.8:27b-mlx")
    assert proof["agent_id"] == "buddha_chat" and len(calls) == 1
