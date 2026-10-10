"""Native dialog admission and migration; no provider inference or real stores."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from hub._services.chat import model_sockets as models
from hub._services.chat import slots_config as slots
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.llm.model_backend import OllamaBackend


@pytest.fixture
def native_caller(tmp_path, monkeypatch):
    from hub._services import skill_source_service
    from hub._services.chat import telegram_chat as control

    path = tmp_path / "slots.json"
    slots.initialize_slots_config(str(path))
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(models.platform, "node", lambda: "test-host")
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda target: None)
    backend = OllamaBackend()
    backend.chat = AsyncMock(return_value="answer")
    runtime = ChatRuntime(backend=backend)
    runtime.require_model_socket_config = True
    monkeypatch.setattr(control, "runtime", runtime)
    monkeypatch.setattr(control, "_orig_get_session", runtime.get_session)
    monkeypatch.setattr(runtime, "get_session", control._patched_get_session)
    monkeypatch.setattr(control, "_get_or_create_backend", lambda *_: backend)
    monkeypatch.setattr(control, "_global_defaults", {})
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    return control, runtime, backend, path


def migrate():
    return models.migrate_model_sockets(
        slots.core_system_agents_snapshot()["configuration_version"])


async def local_call(runtime, backend, chat_id, model):
    token = runtime._compute_turn_context.set((chat_id, "foreground"))
    try:
        return await runtime._chat_with_compute_turn(backend, [], model=model)
    finally:
        runtime._compute_turn_context.reset(token)


def test_migration_includes_connector_targets_and_preserves_original_profiles(native_caller):
    _, _, _, path = native_caller
    config = slots.load_slots_config()
    config["slots"]["buddha_connector"]["providers"] = {
        "telegram": {"backend": "ollama", "model": "telegram:8b", "max_tool_rounds": 18},
        "whatsapp": {"backend": "ollama-cloud", "model": "remote:cloud"},
        "signal": {"backend": "lmstudio", "model": "signal:8b"},
    }
    config["private_extension"] = {"keep": "äöüß"}
    slots.save_slots_config(config)
    before = copy.deepcopy(config)
    migrate()
    after = slots.load_slots_config()
    assert after["slots"] == before["slots"]
    assert after["private_extension"] == before["private_extension"]
    for backend, model in (("ollama", "telegram:8b"), ("lmstudio", "signal:8b")):
        assert models.require_model_binding("buddha_connector", backend, model)
    assert not any(s["model"] == "remote:cloud"
                   for s in models.model_sockets_snapshot()["sockets"])
    assert path.exists()


@pytest.mark.parametrize("override", [
    {"id": "buddha_chat"}, {"enabled": True}, {"allowed_tools": ["execute_command"]},
    {"max_tool_rounds": True}, {"max_tool_rounds": 1001},
    {"backend": "unknown-provider"}, {"model": None}, [],
])
def test_invalid_connector_overlay_denies_projection_without_write(native_caller, override):
    _, _, _, path = native_caller
    config = slots.load_slots_config()
    config["slots"]["buddha_connector"]["providers"]["telegram"] = override
    slots.save_slots_config(config)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Connector"):
        models.model_sockets_snapshot()
    assert path.read_bytes() == before


@pytest.mark.parametrize("chat_id,provider", [
    ("12345", "telegram"), ("-100123", "telegram"), ("tg:123", "telegram"),
    ("telegram:123", "telegram"), ("telegram", "telegram"),
    ("wa:123", "whatsapp"), ("whatsapp:123", "whatsapp"),
    ("whatsapp", "whatsapp"), ("signal:123", "signal"), ("signal", "signal"),
])
def test_native_connector_routing_uses_effective_provider_and_binding(native_caller, chat_id, provider):
    control, runtime, backend, _ = native_caller
    config = slots.load_slots_config()
    config["slots"]["buddha_connector"]["providers"][provider] = {
        "backend": "ollama", "model": provider + ":8b", "max_tool_rounds": 21}
    slots.save_slots_config(config)
    migrate()
    selected, model = control._snapshot_chat_backend(chat_id)
    session = runtime.get_session(chat_id)
    session.messages = [{"role": "user", "content": "bestehender Auftrag"}]
    assert selected is backend and model == provider + ":8b"
    assert session.system_slot_id == "buddha_connector"
    assert ChatRuntime._worker_backend_gate(session, backend, model) is None
    assert asyncio.run(local_call(runtime, backend, chat_id, model)) == "answer"
    backend.chat.assert_awaited_once()
    assert not HostInferenceGate().status()["active"]


@pytest.mark.parametrize("chat_id", ["telegram-unverified", "whatsapp-unverified", "tg:", "signal:"])
def test_unknown_connector_prefix_does_not_gain_a_profile(native_caller, chat_id):
    control, _, _, _ = native_caller
    with pytest.raises(control.WorkerBindingError, match="nicht eindeutig"):
        control._snapshot_chat_backend(chat_id)


def test_restored_connector_gets_guard_without_losing_messages(native_caller):
    control, runtime, backend, _ = native_caller
    migrate()
    session = control._orig_get_session("12345")
    messages = [{"role": "user", "content": "älterer Dialog"}]
    session.messages = messages
    control._snapshot_chat_backend("12345")
    assert session.messages is messages
    assert session.system_slot_id == "buddha_connector"
    assert asyncio.run(local_call(runtime, backend, "12345", session.model)) == "answer"


def test_generic_api_dialog_keeps_backend_model_and_context_but_gets_model_identity(native_caller):
    control, runtime, backend, _ = native_caller
    migrate()
    session = control._orig_get_session("api-delegate")
    messages = [{"role": "user", "content": "mein Auftrag"}]
    session.messages = messages
    session.model = "qwen3.8:27b-mlx"
    selected, model = control._snapshot_chat_backend("api-delegate")
    assert selected is backend and model == session.model
    assert session.messages is messages and session.system_slot_id == "buddha_chat"
    assert asyncio.run(local_call(runtime, backend, "api-delegate", model)) == "answer"


def test_provider_change_while_waiting_blocks_dispatch_without_resetting_context(native_caller):
    control, runtime, backend, _ = native_caller
    migrate()
    _, model = control._snapshot_chat_backend("12345")
    session = runtime.get_session("12345")
    messages = [{"role": "user", "content": "laufender Auftrag"}]
    session.messages = messages

    async def run():
        async with HostInferenceGate().turn("other", "foreground"):
            pending = asyncio.create_task(local_call(runtime, backend, "12345", model))
            await asyncio.sleep(.05)
            config = slots.load_slots_config()
            config["slots"]["buddha_connector"]["providers"]["telegram"]["model"] = "new:8b"
            slots.save_slots_config(config)
            with pytest.raises(RuntimeError, match="[Kk]onfiguration"):
                await asyncio.wait_for(pending, 2)
        backend.chat.assert_not_awaited()
    asyncio.run(run())
    assert session.messages is messages


def test_telegram_handler_admits_restored_caller_before_processing(native_caller, monkeypatch):
    control, runtime, _, _ = native_caller
    migrate()
    session = control._orig_get_session("-100123")
    session.messages = [{"role": "user", "content": "alter Auftrag"}]
    observed = []
    async def process(*args, **kwargs):
        observed.append(session.system_slot_id)
        return "answer"
    monkeypatch.setattr(runtime, "process", process)
    monkeypatch.setattr(control, "_owner_check", lambda update: True)
    monkeypatch.setattr(control, "_compute_lock_enabled", lambda *args: False)
    monkeypatch.setattr(control, "_keep_typing", AsyncMock())
    monkeypatch.setattr(control, "_pending_actions", {})
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123),
        message=SimpleNamespace(text="Neuer Auftrag", reply_text=AsyncMock()),
    )
    asyncio.run(control.handle_message(update, object()))
    assert observed == ["buddha_connector"]


def test_telegram_owner_check_precedes_caller_binding(native_caller, monkeypatch):
    control, runtime, _, _ = native_caller
    process = AsyncMock()
    admission = AsyncMock()
    monkeypatch.setattr(runtime, "process", process)
    monkeypatch.setattr(control, "_snapshot_chat_backend", admission)
    monkeypatch.setattr(control, "_owner_check", lambda update: False)
    update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
    asyncio.run(control.handle_message(update, object()))
    admission.assert_not_called()
    process.assert_not_awaited()


@pytest.mark.parametrize("denial", ["disabled", "override", "backend"])
def test_connector_admission_errors_do_not_reopen_global_backend(native_caller, monkeypatch, denial):
    control, runtime, _, _ = native_caller
    config = slots.load_slots_config()
    connector = config["slots"]["buddha_connector"]
    if denial == "disabled":
        connector["enabled"] = False
    elif denial == "override":
        connector["providers"]["telegram"] = {"id": "buddha_chat"}
    else:
        def unavailable(*args):
            raise RuntimeError("backend unavailable")
        monkeypatch.setattr(control, "_get_or_create_backend", unavailable)
    slots.save_slots_config(config)
    with pytest.raises((ValueError, RuntimeError, control.WorkerBindingError)):
        control._snapshot_chat_backend("12345")
    session = runtime.get_session("12345")
    assert session.allow_tools is False


@pytest.mark.parametrize("denial", ["disabled", "override", "backend"])
def test_telegram_denial_precedes_compute_pause_and_process(native_caller, monkeypatch, denial):
    control, runtime, _, _ = native_caller
    config = slots.load_slots_config()
    connector = config["slots"]["buddha_connector"]
    if denial == "disabled":
        connector["enabled"] = False
    elif denial == "override":
        connector["providers"]["telegram"] = {"id": "buddha_chat"}
    else:
        def unavailable(*args):
            raise RuntimeError("backend unavailable")
        monkeypatch.setattr(control, "_get_or_create_backend", unavailable)
    slots.save_slots_config(config)
    process = AsyncMock()
    pauses = []
    monkeypatch.setattr(runtime, "process", process)
    monkeypatch.setattr(control, "_owner_check", lambda update: True)
    monkeypatch.setattr(control, "_compute_lock_enabled", lambda *args: True)
    monkeypatch.setattr(control, "check_compute_active", lambda **kwargs: (True, {}))
    monkeypatch.setattr(control, "get_fackel_preference", lambda: "ollama")
    monkeypatch.setattr(control, "pause_compute_jobs", lambda status: pauses.append(status))
    monkeypatch.setattr(control, "_pending_actions", {})
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=12345),
        message=SimpleNamespace(text="Auftrag", reply_text=AsyncMock()),
    )
    asyncio.run(control.handle_message(update, object()))
    process.assert_not_awaited()
    assert not pauses
    assert "Chat-Zuordnung nicht verfügbar" in update.message.reply_text.call_args.args[0]


def test_confirmed_compute_pause_validates_caller_before_pausing_jobs(native_caller, monkeypatch):
    import time
    control, _, _, _ = native_caller
    pauses = []
    monkeypatch.setattr(control, "_pending_actions", {
        "12345": {"status": {}, "text": "mein Auftrag", "timestamp": time.time()}})
    monkeypatch.setattr(control, "pause_compute_jobs", lambda status: pauses.append(status))
    def deny(chat_id):
        raise control.WorkerBindingError("Zuordnung fehlt")
    monkeypatch.setattr(control, "_snapshot_chat_backend", deny)
    update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
    assert asyncio.run(control._handle_pending_action("12345", "JA", update))
    assert not pauses
    assert "12345" in control._pending_actions


def test_disabled_model_binding_denies_confirmed_pause_and_keeps_pending(native_caller, monkeypatch):
    import time

    control, _, backend, _ = native_caller
    view = migrate()
    models.bind_model_agent(view["configuration_version"], "buddha_connector",
                            view["sockets"][0]["id"], {"enabled": False})
    pauses = []
    monkeypatch.setattr(control, "_pending_actions", {
        "12345": {"status": {}, "text": "mein Auftrag", "timestamp": time.time()}})
    monkeypatch.setattr(control, "pause_compute_jobs", lambda status: pauses.append(status))
    update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
    assert asyncio.run(control._handle_pending_action("12345", "JA", update))
    assert not pauses and "12345" in control._pending_actions
    assert "model_socket_binding_unavailable" in update.message.reply_text.call_args.args[0]
    backend.chat.assert_not_awaited()


@pytest.mark.parametrize("state", ["waiting_memory_reserve", "waiting_disk_reserve"])
def test_known_local_reserve_wait_checks_binding_without_taking_torch(native_caller, monkeypatch, state):
    from hub._services.chat import local_resource_reserve as reserve

    control, _, backend, _ = native_caller
    migrate()
    receipt = {"state": state, "admitted": False, "retryable": True}
    monkeypatch.setattr(reserve, "probe", AsyncMock(return_value=receipt))
    assert asyncio.run(control._admit_chat_for_compute("12345")) == (backend, "qwen3.8:27b-mlx", True)
    assert not HostInferenceGate().status()["active"]
    backend.chat.assert_not_awaited()


@pytest.mark.parametrize("state", ["unknown_model_observation", "unknown_resources"])
def test_unknown_target_receipt_denies_compute_pause(native_caller, monkeypatch, state):
    from hub._services.chat import local_resource_reserve as reserve

    control, _, backend, _ = native_caller
    migrate()
    receipt = {"state": state, "admitted": False, "retryable": True}
    monkeypatch.setattr(reserve, "probe", AsyncMock(return_value=receipt))
    with pytest.raises(reserve.LocalReserveError, match=state):
        asyncio.run(control._admit_chat_for_compute("12345"))
    backend.chat.assert_not_awaited()


def test_metadata_cloud_alias_requires_no_local_model_binding_or_torch(native_caller, monkeypatch):
    from hub._services.chat import local_resource_reserve as reserve

    control, _, backend, _ = native_caller
    # No migration: an actual metadata-confirmed external target needs no slot.
    monkeypatch.setattr(reserve, "probe", AsyncMock(return_value={
        "state": "external_target", "admitted": True, "retryable": False}))
    assert asyncio.run(control._admit_chat_for_compute("12345")) == (backend, "qwen3.8:27b-mlx", False)
    assert not HostInferenceGate().status()["active"]
    backend.chat.assert_not_awaited()


def test_empty_dialog_does_not_rebind_profile_during_metadata_probe(native_caller, monkeypatch):
    from hub._services.chat import local_resource_reserve as reserve

    control, runtime, backend, _ = native_caller
    migrate()
    async def change_profile(*args):
        config = slots.load_slots_config()
        config["slots"]["buddha_connector"]["providers"]["telegram"]["model"] = "changed:8b"
        slots.save_slots_config(config)
        return {"state": "ready", "admitted": True, "retryable": False}
    monkeypatch.setattr(reserve, "probe", change_profile)
    with pytest.raises(RuntimeError, match="[Kk]onfiguration"):
        asyncio.run(control._admit_chat_for_compute("12345"))
    assert runtime.sessions["12345"].model == "qwen3.8:27b-mlx"
    backend.chat.assert_not_awaited()


@pytest.mark.parametrize("model", ["remote-alias", "remote:cloud"])
def test_native_cloud_handler_ignores_local_compute_without_pausing_jobs(native_caller, monkeypatch, model):
    from hub._services.chat import local_resource_reserve as reserve

    control, runtime, backend, _ = native_caller
    config = slots.load_slots_config()
    config["slots"]["buddha_connector"]["providers"]["telegram"]["model"] = model
    config["slots"]["buddha_connector"]["allow_tools"] = False
    slots.save_slots_config(config)
    # No local registry; the selected target is genuinely external.
    monkeypatch.setattr(reserve, "probe", AsyncMock(return_value={
        "state": "external_target", "admitted": True, "retryable": False}))
    backend.chat = AsyncMock(return_value={"content": "cloud answer"})
    runtime.compute_gate = control._compute_lock_blocks
    monkeypatch.setattr(runtime, "_memory_hook", lambda: None)
    monkeypatch.setattr(control, "HAS_COMPUTE_LOCK", True)
    monkeypatch.setattr(control, "CONFIG", {**control.CONFIG, "compute_lock": {"enabled": True}})
    monkeypatch.setattr(control, "check_compute_active", lambda **kwargs: (True, {}))
    monkeypatch.setattr(control, "get_fackel_preference", lambda: "compute")
    monkeypatch.setattr(control, "_owner_check", lambda update: True)
    monkeypatch.setattr(control, "_keep_typing", AsyncMock())
    monkeypatch.setattr(control, "_pending_actions", {})
    def forbidden(*args, **kwargs):
        pytest.fail("An external model must not change local compute jobs or inference flags")
    monkeypatch.setattr(control, "pause_compute_jobs", forbidden)
    monkeypatch.setattr(control, "write_session_flag", forbidden)
    monkeypatch.setattr(control, "set_inferenz_active", forbidden)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=12345),
        message=SimpleNamespace(text="Auftrag", reply_text=AsyncMock()),
    )
    asyncio.run(control.handle_message(update, object()))
    backend.chat.assert_awaited_once()
    assert not HostInferenceGate().status()["active"]
    assert not control._pending_actions
    assert "cloud answer" in update.message.reply_text.call_args.args[0]
