"""Model/socket identity, canonical CAS, binding admission and device authorization."""
import asyncio
import copy
import hashlib
import json
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


@pytest.fixture
def ready_local_reserve(registry, tmp_path, monkeypatch):
    from hub._services.chat import local_resource_reserve as reserve

    policy = {
        "schema": reserve.SCHEMA,
        "enabled": True,
        "memory_reserve_bytes": 512 * 1024**2,
        "disk_reserve_bytes": 128 * 1024**2,
        "wait_seconds": 1,
        "poll_seconds": 1,
        "models": {
            "qwen3.8:27b-mlx": {
                "digest": "0" * 64,
                "weight_budget_bytes": 1,
                "kv_headroom_bytes": 128 * 1024**2,
                "overhead_bytes": 128 * 1024**2,
                "num_ctx": 512,
            }
        },
    }
    reserve.validate_policy(policy)
    raw = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path = tmp_path / "runtime" / "local-inference" / "resource-reserve.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    version_hash = hashlib.sha256(raw).hexdigest()

    async def probe(_backend, model):
        assert model in policy["models"]
        return {
            "schema": reserve.SCHEMA,
            "state": "ready",
            "admitted": True,
            "enforced": True,
            "retryable": False,
            "policy_version": version_hash,
            "model": model,
        }

    monkeypatch.setattr(reserve, "probe", probe)
    return version_hash


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
def test_runtime_missing_migrated_registry_never_dispatches_locally(
    registry, ready_local_reserve, format_version
):
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


def test_runtime_admits_actual_bound_target_and_publishes_host_owner(
    registry, ready_local_reserve
):
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



def _bindings_for(agent_id):
    config = slots.load_slots_config(strict=True)
    return {
        binding["id"]: dict(binding)
        for binding in config["model_sockets"]["bindings"].values()
        if binding["agent_id"] == agent_id
    }


def test_new_dynamic_worker_uses_existing_local_offer_without_starting(registry):
    migrated()
    before = slots.load_slots_config(strict=True)
    worker = slots.add_worker({"name": "Pilot", "backend": "ollama", "model": "qwen3.8:27b-mlx",
                               "sub_mode": "task_worker", "task_id": 2217}, path=registry)
    after = slots.load_slots_config(strict=True)
    proof = models.require_model_binding(worker["id"], "ollama", "qwen3.8:27b-mlx")
    assert worker["status"] == "idle" and proof["agent_id"] == worker["id"]
    assert proof["priority"] == "background"
    assert len(_bindings_for(worker["id"])) == 1
    assert after["model_sockets"]["sockets"] == before["model_sockets"]["sockets"]
    assert all(after["model_sockets"]["bindings"][key] == value for key, value in
               before["model_sockets"]["bindings"].items())
    assert models.model_sockets_snapshot()["runtime_verified"] is False


@pytest.mark.parametrize("kind", ["system", "blueprint", "sequence"])
def test_new_system_agent_binds_only_offered_local_model(registry, kind):
    migrated()
    if kind == "system":
        result = slots.create_system_slot(
            {"name": "Lokaler Pilot", "backend": "ollama", "model": "qwen3.8:27b-mlx"},
            version(), path=registry,
        )
    elif kind == "blueprint":
        result = slots.materialize_system_blueprint(
            2217, 1, {"worker_type": "once", "backend": "ollama", "model": "qwen3.8:27b-mlx"},
            version(), path=registry,
        )
    else:
        from hub._services.chat.sequence_store import digest
        profile = slots.sequence_profile_snapshot(["buddha_developer"], path=registry)["profiles"]["buddha_developer"]
        result = slots.materialize_sequence_slot(
            "a" * 32, 0, profile, 2217, source_slot="buddha_developer",
            expected_profile_digest=digest(profile), path=registry,
        )
    slot_id = result["slot_id"]
    assert slots.get_system_slot(slot_id, registry)["status"] == "idle"
    assert models.require_model_binding(slot_id, "ollama", "qwen3.8:27b-mlx")["priority"] == "background"


@pytest.mark.parametrize("kind", ["worker", "system"])
@pytest.mark.parametrize("offer", ["missing", "disabled"])
def test_new_local_profile_rejects_unavailable_offer_without_partial_save(registry, kind, offer):
    from pathlib import Path

    migrated()
    if offer == "disabled":
        models.configure_model_socket(version(),
                                      {"backend": "ollama", "model": "unavailable:8b", "enabled": False})
    before = Path(registry).read_bytes()
    with pytest.raises(ValueError, match="Modellangebot|Steckplatz"):
        if kind == "worker":
            slots.add_worker({"name": "Nicht startbar", "backend": "ollama", "model": "unavailable:8b"},
                             path=registry)
        else:
            slots.create_system_slot({"name": "Nicht startbar", "backend": "ollama",
                                      "model": "unavailable:8b"}, version(), path=registry)
    assert Path(registry).read_bytes() == before


def test_new_cloud_worker_has_no_local_socket_or_binding(registry):
    migrated()
    before = slots.load_slots_config(strict=True)["model_sockets"]
    worker = slots.add_worker({"name": "Cloud", "backend": "ollama-cloud", "model": "gemma:cloud"},
                              path=registry)
    after = slots.load_slots_config(strict=True)["model_sockets"]
    assert after == before
    assert _bindings_for(worker["id"]) == {}
    assert worker["status"] == "idle"


def test_dynamic_worker_model_edit_reconciles_only_own_bindings(registry):
    migrated()
    models.configure_model_socket(version(), {"backend": "ollama", "model": "next:8b"})
    worker = slots.add_worker({"name": "Edit", "backend": "ollama", "model": "qwen3.8:27b-mlx", "task_id": 2217},
                              path=registry)
    old_target = models.socket_id("ollama", "qwen3.8:27b-mlx", "test-host")
    old_id = models._binding_id(worker["id"], old_target)
    models.bind_model_agent(version(), worker["id"], old_target,
                            {"priority": "foreground", "context_tokens": 4096})
    foreign = {key: value for key, value in slots.load_slots_config(strict=True)["model_sockets"]["bindings"].items()
               if value["agent_id"] != worker["id"]}
    profile_version = slots.worker_configuration_snapshot(worker["id"])["configuration_version"]
    slots.change_worker_configuration(worker["id"], profile_version,
                                      {"model": "next:8b", "model_fallbacks": [
                                          {"backend": "ollama", "model": "qwen3.8:27b-mlx"}]}, path=registry)
    bindings = _bindings_for(worker["id"])
    assert len(bindings) == 2 and bindings[old_id]["priority"] == "foreground"
    assert bindings[old_id]["context_tokens"] == 4096
    assert models.require_model_binding(worker["id"], "ollama", "next:8b")
    profile_version = slots.worker_configuration_snapshot(worker["id"])["configuration_version"]
    slots.change_worker_configuration(worker["id"], profile_version,
                                      {"model_fallbacks": []}, path=registry)
    assert old_id not in _bindings_for(worker["id"])
    assert all(slots.load_slots_config(strict=True)["model_sockets"]["bindings"][key] == value
               for key, value in foreign.items())


@pytest.mark.parametrize("offer", ["missing", "disabled"])
@pytest.mark.parametrize("field", ["model", "model_fallbacks"])
def test_dynamic_model_edit_rejects_unavailable_target_without_partial_save(registry, offer, field):
    from pathlib import Path

    migrated()
    worker = slots.add_worker({"name": "Edit", "backend": "ollama", "model": "qwen3.8:27b-mlx", "task_id": 2217},
                              path=registry)
    if offer == "disabled":
        models.configure_model_socket(version(),
                                      {"backend": "ollama", "model": "unavailable:8b", "enabled": False})
    before = Path(registry).read_bytes()
    profile_version = slots.worker_configuration_snapshot(worker["id"])["configuration_version"]
    changes = ({"model": "unavailable:8b"} if field == "model" else
               {"model_fallbacks": [{"backend": "ollama", "model": "unavailable:8b"}]})
    with pytest.raises(ValueError, match="Modellangebot|Steckplatz"):
        slots.change_worker_configuration(worker["id"], profile_version,
                                          changes, path=registry)
    assert Path(registry).read_bytes() == before
    assert len(_bindings_for(worker["id"])) == 1


def test_dynamic_worker_switch_to_cloud_removes_only_own_local_binding(registry):
    migrated()
    worker = slots.add_worker({"name": "Edit", "backend": "ollama", "model": "qwen3.8:27b-mlx", "task_id": 2217},
                              path=registry)
    before = slots.load_slots_config(strict=True)["model_sockets"]["bindings"]
    foreign = {key: value for key, value in before.items() if value["agent_id"] != worker["id"]}
    profile_version = slots.worker_configuration_snapshot(worker["id"])["configuration_version"]
    slots.change_worker_configuration(worker["id"], profile_version,
                                      {"backend": "ollama-cloud", "model": "gemma:cloud"}, path=registry)
    after = slots.load_slots_config(strict=True)["model_sockets"]["bindings"]
    assert after == foreign
    assert _bindings_for(worker["id"]) == {}


@pytest.mark.parametrize("operation", ["worker_create", "system_create", "worker_edit"])
def test_migrated_missing_registry_rejects_new_local_profile_mutation(registry, operation):
    from pathlib import Path

    migrated()
    worker = None
    if operation == "worker_edit":
        worker = slots.add_worker({"name": "Edit", "backend": "ollama", "model": "qwen3.8:27b-mlx", "task_id": 2217},
                                  path=registry)
    config = slots.load_slots_config(strict=True)
    del config["model_sockets"]
    slots.save_slots_config(config, registry)
    before = Path(registry).read_bytes()
    with pytest.raises(RuntimeError, match="model_socket_registry_unavailable"):
        if operation == "worker_create":
            slots.add_worker({"name": "Blocked", "backend": "ollama", "model": "qwen3.8:27b-mlx"},
                             path=registry)
        elif operation == "system_create":
            slots.create_system_slot({"model": "qwen3.8:27b-mlx"}, version(), path=registry)
        else:
            profile_version = slots.worker_configuration_snapshot(worker["id"])["configuration_version"]
            slots.change_worker_configuration(worker["id"], profile_version,
                                              {"model": "qwen3.8:27b-mlx"}, path=registry)
    assert Path(registry).read_bytes() == before


@pytest.mark.parametrize("bad_version", ["4", True, None, 0])
@pytest.mark.parametrize("operation", ["core", "create", "blueprint", "sequence",
                                      "worker_create", "worker_edit"])
def test_invalid_format_version_never_saves_a_model_binding(registry, bad_version, operation):
    from pathlib import Path
    from hub._services.chat.sequence_store import digest

    migrated()
    worker = None
    worker_version = None
    if operation == "worker_edit":
        worker = slots.add_worker({"name": "Edit", "backend": "ollama", "model": "qwen3.8:27b-mlx", "task_id": 2217},
                                  path=registry)
        worker_version = slots.worker_configuration_snapshot(worker["id"])["configuration_version"]
    profile = slots.sequence_profile_snapshot(["buddha_developer"], path=registry)["profiles"]["buddha_developer"]
    config = slots.load_slots_config(strict=True)
    config["version"] = bad_version
    slots.save_slots_config(config, registry)
    before = Path(registry).read_bytes()
    core_version = slots._core_configuration_version(config)
    with pytest.raises(ValueError, match="Konfigurationsformatversion|nicht lesbar"):
        if operation == "core":
            slots.change_core_system_agent("buddha_developer", core_version,
                                           {"model": "qwen3.8:27b-mlx"}, path=registry)
        elif operation == "create":
            slots.create_system_slot({"model": "qwen3.8:27b-mlx"}, core_version, path=registry)
        elif operation == "blueprint":
            slots.materialize_system_blueprint(2217, 1,
                {"worker_type": "once", "model": "qwen3.8:27b-mlx"}, core_version, path=registry)
        elif operation == "sequence":
            slots.materialize_sequence_slot("a" * 32, 0, profile, 2217,
                source_slot="buddha_developer", expected_profile_digest=digest(profile), path=registry)
        elif operation == "worker_create":
            slots.add_worker({"name": "Blocked", "backend": "ollama", "model": "qwen3.8:27b-mlx"},
                             path=registry)
        else:
            slots.change_worker_configuration(worker["id"], worker_version,
                                              {"model": "qwen3.8:27b-mlx"}, path=registry)
    assert Path(registry).read_bytes() == before


def test_existing_disabled_binding_stays_disabled_on_worker_model_edit(registry):
    migrated()
    worker = slots.add_worker({"name": "Edit", "backend": "ollama", "model": "qwen3.8:27b-mlx", "task_id": 2217},
                              path=registry)
    target = models.socket_id("ollama", "qwen3.8:27b-mlx", "test-host")
    models.bind_model_agent(version(), worker["id"], target,
                            {"enabled": False, "context_tokens": 2048})
    profile_version = slots.worker_configuration_snapshot(worker["id"])["configuration_version"]
    slots.change_worker_configuration(worker["id"], profile_version,
                                      {"model": "qwen3.8:27b-mlx"}, path=registry)
    binding = next(iter(_bindings_for(worker["id"]).values()))
    assert binding["enabled"] is False and binding["context_tokens"] == 2048
    with pytest.raises(RuntimeError, match="model_socket_binding_unavailable"):
        models.require_model_binding(worker["id"], "ollama", "qwen3.8:27b-mlx")


def test_atomic_profile_rebind_updates_primary_and_fallback_once(registry, monkeypatch):
    from pathlib import Path

    migrated()
    config = slots.load_slots_config(strict=True)
    old_profile = dict(config["slots"]["buddha_chat"])
    config["private_extension"] = {"kept": "äöüß"}
    config["activity_history"] = [{"task_id": 77, "status": "running"}]
    slots.save_slots_config(config)
    configured = models.model_sockets_snapshot()
    configured = models.configure_model_socket(
        configured["configuration_version"],
        {"backend": "ollama", "model": "rebind-target:8b"},
    )
    old_target = models.socket_id(old_profile["backend"], old_profile["model"], "test-host")
    configured = models.bind_model_agent(
        configured["configuration_version"], "buddha_chat", old_target,
        {"priority": "foreground", "context_tokens": 8192},
    )
    before_config = slots.load_slots_config(strict=True)
    other_bindings = {
        key: value for key, value in before_config["model_sockets"]["bindings"].items()
        if value["agent_id"] != "buddha_chat"
    }
    socket_ids = set(before_config["model_sockets"]["sockets"])
    before_bytes = Path(registry).read_bytes()
    save_calls = 0
    original_save = slots.save_slots_config

    def counted_save(updated, path=None):
        nonlocal save_calls
        save_calls += 1
        return original_save(updated, path)

    monkeypatch.setattr(slots, "save_slots_config", counted_save)
    result = models.rebind_model_profile(
        configured["configuration_version"], "buddha_chat",
        {"backend": "ollama", "model": "rebind-target:8b",
         "model_fallbacks": [{"backend": old_profile["backend"], "model": old_profile["model"]}]},
    )

    after = slots.load_slots_config(strict=True)
    bindings = _bindings_for("buddha_chat")
    expected_ids = {
        models._binding_id("buddha_chat", models.socket_id("ollama", "rebind-target:8b", "test-host")),
        models._binding_id("buddha_chat", old_target),
    }
    assert save_calls == 1
    assert set(bindings) == expected_ids
    assert bindings[models._binding_id("buddha_chat", old_target)]["context_tokens"] == 8192
    assert set(after["model_sockets"]["sockets"]) == socket_ids
    assert all(after["model_sockets"]["bindings"][key] == value for key, value in other_bindings.items())
    assert after["slots"]["buddha_chat"]["model"] == "rebind-target:8b"
    assert after["slots"]["buddha_chat"]["model_fallbacks"] == [
        {"backend": old_profile["backend"], "model": old_profile["model"]}
    ]
    assert after["private_extension"] == {"kept": "äöüß"}
    assert after["activity_history"] == [{"task_id": 77, "status": "running"}]
    assert result["configuration_version"] == slots.core_system_agents_snapshot()["configuration_version"]
    assert result["runtime_verified"] is False
    assert Path(registry).read_bytes() != before_bytes


def test_external_only_profile_rebind_removes_its_local_bindings(registry):
    migrated()
    current = models.model_sockets_snapshot()
    result = models.rebind_model_profile(
        current["configuration_version"], "buddha_chat",
        {"backend": "openrouter", "model": "openrouter/free", "model_fallbacks": []},
    )
    config = slots.load_slots_config(strict=True)
    assert config["slots"]["buddha_chat"]["backend"] == "openrouter"
    assert config["slots"]["buddha_chat"]["model"] == "openrouter/free"
    assert _bindings_for("buddha_chat") == {}
    assert "buddha_chat" in result["unbound_agent_ids"]
    assert result["runtime_verified"] is False


@pytest.mark.parametrize("target_state", ["missing", "disabled"])
def test_profile_rebind_requires_existing_enabled_local_offer(registry, target_state):
    from pathlib import Path

    current = migrated()
    if target_state == "disabled":
        current = models.configure_model_socket(
            current["configuration_version"],
            {"backend": "ollama", "model": "rebind-target:8b", "enabled": False},
        )
    before = Path(registry).read_bytes()
    with pytest.raises(ValueError, match="Angebot|Steckplatz|Modellangebot"):
        models.rebind_model_profile(
            current["configuration_version"], "buddha_chat",
            {"backend": "ollama", "model": "rebind-target:8b", "model_fallbacks": []},
        )
    assert Path(registry).read_bytes() == before


def test_profile_rebind_rejects_stale_cas_invalid_profile_and_lock_without_write(
    registry, monkeypatch
):
    from pathlib import Path

    from hub._services import skill_source_service

    current = migrated()
    before = Path(registry).read_bytes()
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        models.rebind_model_profile("0" * 64, "buddha_chat", {"model": "unused:8b"})
    assert Path(registry).read_bytes() == before
    with pytest.raises(ValueError, match="Primär|Änderung"):
        models.rebind_model_profile(
            current["configuration_version"], "buddha_chat", {"backend": "ollama", "grant": "x"}
        )
    assert Path(registry).read_bytes() == before
    with pytest.raises(KeyError):
        models.rebind_model_profile(
            current["configuration_version"], "missing-agent", {"model": "unused:8b"}
        )
    assert Path(registry).read_bytes() == before

    def deny(target):
        assert str(target) == registry
        raise RuntimeError("locked")

    monkeypatch.setattr(skill_source_service, "check_write_locks", deny)
    with pytest.raises(RuntimeError, match="locked"):
        models.rebind_model_profile(
            current["configuration_version"], "buddha_chat", {"model": "unused:8b"}
        )
    assert Path(registry).read_bytes() == before


def test_profile_rebind_save_failure_leaves_original_bytes(registry, monkeypatch):
    from pathlib import Path

    current = migrated()
    current = models.configure_model_socket(
        current["configuration_version"], {"backend": "ollama", "model": "unused:8b"}
    )
    before = Path(registry).read_bytes()

    def fail_save(*_args, **_kwargs):
        raise OSError("simulated atomic save failure")

    monkeypatch.setattr(slots, "save_slots_config", fail_save)
    with pytest.raises(OSError, match="simulated atomic save failure"):
        models.rebind_model_profile(
            current["configuration_version"], "buddha_chat", {"model": "unused:8b"}
        )
    assert Path(registry).read_bytes() == before


def test_legacy_core_model_setter_reconciles_under_write_lock(registry, monkeypatch):
    current = migrated()
    current = models.configure_model_socket(
        current["configuration_version"], {"backend": "ollama", "model": "rebind-target:8b"}
    )
    from hub._services import skill_source_service
    checked = []
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda target: checked.append(str(target)))

    slots.change_core_system_agent(
        "buddha_chat", current["configuration_version"],
        {"backend": "ollama", "model": "rebind-target:8b", "model_fallbacks": []},
    )

    assert checked == [registry]
    assert slots.get_system_slot("buddha_chat")["model"] == "rebind-target:8b"
    assert len(_bindings_for("buddha_chat")) == 1
    assert models.require_model_binding("buddha_chat", "ollama", "rebind-target:8b")


def test_api_rebind_auth_precedes_write_and_success_ack_is_config_only(registry, monkeypatch):
    from pathlib import Path

    migrated()
    before = Path(registry).read_bytes()

    def deny(_request):
        raise HTTPException(403, "device required")

    monkeypatch.setattr(unified_api, "_require_memory_device_token", deny)
    payload = {"configuration_version": version(),
               "changes": {"backend": "openrouter", "model": "openrouter/free", "model_fallbacks": []}}
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.rebind_model_profile("buddha_chat", object(), payload))
    assert error.value.status_code == 403
    assert Path(registry).read_bytes() == before

    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda _request: "verified-test-device")
    result = asyncio.run(api.rebind_model_profile("buddha_chat", object(), payload))
    assert result["ack"] == {"configuration_saved": True, "worker_started": False, "runtime_verified": False}
    assert result["configuration_version"] == slots.core_system_agents_snapshot()["configuration_version"]
    assert _bindings_for("buddha_chat") == {}



def test_concurrent_profile_rebind_cas_has_exactly_one_winner(registry):
    current = migrated()
    for model in ("race-one:8b", "race-two:8b"):
        current = models.configure_model_socket(
            current["configuration_version"], {"backend": "ollama", "model": model}
        )
    expected_version = current["configuration_version"]

    def update(model):
        try:
            models.rebind_model_profile(
                expected_version, "buddha_chat",
                {"backend": "ollama", "model": model, "model_fallbacks": []},
            )
            return "saved"
        except RuntimeError as exc:
            return str(exc)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(update, ("race-one:8b", "race-two:8b")))
    assert sorted(results) == ["configuration_version_conflict", "saved"]
    final = slots.get_system_slot("buddha_chat")
    assert final["model"] in {"race-one:8b", "race-two:8b"}
    final_binding = models.require_model_binding("buddha_chat", "ollama", final["model"])
    assert final_binding["model"] == final["model"]
    assert len(_bindings_for("buddha_chat")) == 1


def test_legacy_core_model_setter_lock_denial_leaves_config_unchanged(registry, monkeypatch):
    from pathlib import Path

    from hub._services import skill_source_service

    current = migrated()
    current = models.configure_model_socket(
        current["configuration_version"], {"backend": "ollama", "model": "denied:8b"}
    )
    before = Path(registry).read_bytes()

    def deny(target):
        assert str(target) == registry
        raise RuntimeError("locked")

    monkeypatch.setattr(skill_source_service, "check_write_locks", deny)
    with pytest.raises(RuntimeError, match="locked"):
        slots.change_core_system_agent(
            "buddha_chat", current["configuration_version"],
            {"backend": "ollama", "model": "denied:8b", "model_fallbacks": []},
        )
    assert Path(registry).read_bytes() == before


def test_legacy_core_text_edit_lock_denial_leaves_config_unchanged(registry, monkeypatch):
    from pathlib import Path

    from hub._services import skill_source_service

    current = migrated()
    before = Path(registry).read_bytes()

    def deny(target):
        assert str(target) == registry
        raise RuntimeError("locked")

    monkeypatch.setattr(skill_source_service, "check_write_locks", deny)
    with pytest.raises(RuntimeError, match="locked"):
        slots.change_core_system_agent(
            "buddha_chat", current["configuration_version"], {"icon": "🔒"}
        )
    assert Path(registry).read_bytes() == before
