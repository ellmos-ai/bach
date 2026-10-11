"""Explicit model fallback chains stay on native profiles and model-call boundaries."""
import asyncio
import builtins
import json
import sys
import types
from pathlib import Path

import pytest
from hub._services.chat import model_sockets, slots_config
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.llm.model_backend import CLIBackend, OllamaBackend, OpenRouterBackend


@pytest.fixture
def slots_file(tmp_path):
    path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(path)
    return path


def _profile(worker_id, *, chain=None, backend="ollama", model="qwen3.8:4b"):
    return {
        "id": worker_id,
        "enabled": True,
        "backend": backend,
        "model": model,
        "model_fallbacks": list(chain or []),
        "memory_hook_opt_in": False,
        "allow_tools": False,
        "allowed_tools": None,
        "skill_refs": [],
    }


def _safe_ollama_error(status=503, *, quota=False, content="", tool_calls=None):
    return {
        "error": "provider error",
        "content": content,
        "tool_calls": tool_calls,
        "raw_message": {"role": "assistant", "content": content,
                        **({"tool_calls": tool_calls} if tool_calls else {})},
        "backend_error": {
            "provider": "ollama",
            "kind": "quota_exceeded" if quota else ("rate_limited" if status == 429 else "http_error"),
            "quota_exceeded": quota,
            "status_code": status,
        },
    }


def _runtime_profile(monkeypatch, chain):
    primary = OllamaBackend(base_url="http://127.0.0.1:11434", default_model="qwen3.8:4b")
    fallback = OpenRouterBackend(base_url="https://openrouter.ai/api/v1",
                                 api_key="fixture-only", default_model="openrouter/free")
    runtime = ChatRuntime(primary)
    session = runtime.get_session("worker-fallback-test")
    profile = _profile("worker-fallback-test", chain=chain)
    session.worker_slot_reader = lambda: profile
    monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda target: fallback)
    return runtime, session, primary, fallback


def test_core_and_worker_cas_store_ordered_fallbacks(slots_file):
    chain = [
        {"backend": "ollama", "model": "qwen3.5:4b"},
        {"backend": "openrouter", "model": "openrouter/free"},
    ]
    before = slots_config.core_system_agents_snapshot(slots_file)
    core = slots_config.change_core_system_agent(
        "buddha_chat", before["configuration_version"],
        {"model_fallbacks": chain}, path=slots_file,
    )
    core_profile = next(agent for agent in core["agents"] if agent["id"] == "buddha_chat")
    assert core_profile["model_fallbacks"] == chain

    worker = slots_config.add_worker({"name": "Fallback fixture", "sub_mode": "hintergrund_worker"},
                                     path=slots_file)
    before_worker = slots_config.worker_configuration_snapshot(worker["id"], path=slots_file)
    updated = slots_config.change_worker_configuration(
        worker["id"], before_worker["configuration_version"],
        {"model_fallbacks": chain}, path=slots_file,
    )
    assert updated["configuration"]["model_fallbacks"] == chain


@pytest.mark.parametrize("bad", [
    None,
    {},
    ( {"backend": "ollama", "model": "qwen3.5:4b"}, ),
    [{"backend": "ollama", "model": "qwen3.5:4b", "api_key": "secret"}],
    [{"backend": "ollama", "model": "qwen3.5:4b"},
     {"backend": "ollama", "model": "qwen3.5:4b"}],
    [{"backend": "ollama", "model": "qwen3.5:4b:cloud"}],
    [{"backend": "ollama-cloud", "model": "qwen3.5:4b"}],
])
def test_fallback_config_rejects_bad_shapes_and_provider_mismatches(bad):
    with pytest.raises(ValueError):
        slots_config._validated_model_fallbacks(bad)


def test_openrouter_free_cannot_silently_switch_to_paid_external_provider():
    profile = _profile("free-worker", backend="openrouter", model="openrouter/free",
                       chain=[{"backend": "openai", "model": "gpt-4o"}])
    with pytest.raises(ValueError, match="OpenRouter-Free"):
        model_sockets.model_fallbacks_for_profile(profile)


def test_local_projection_plans_only_local_targets_and_cloud_is_external():
    local = OllamaBackend(base_url="http://localhost:11434", default_model="qwen3.8:4b")
    cloud_proxy = OllamaBackend(base_url="http://127.0.0.1:11434", default_model="kimi-k3:cloud")
    assert model_sockets.profile_backend_matches("ollama", local, "qwen3.8:4b")
    assert not model_sockets.profile_backend_matches("ollama", cloud_proxy, "kimi-k3:cloud")
    assert model_sockets.profile_backend_matches("ollama-cloud", cloud_proxy, "kimi-k3:cloud")

    config = {
        "slots": {
            "worker-fallback-test": _profile("worker-fallback-test", chain=[
                {"backend": "ollama", "model": "qwen3.5:4b"},
                {"backend": "ollama-cloud", "model": "kimi-k3:cloud"},
                {"backend": "openrouter", "model": "openrouter/free"},
            ]),
        },
        "dynamic_workers": [],
    }
    projected = model_sockets._legacy_projection(config, "test-host")
    models = {(item["backend"], item["model"]) for item in projected["sockets"].values()}
    assert ("ollama", "qwen3.8:4b") in models
    assert ("ollama", "qwen3.5:4b") in models
    assert ("ollama-cloud", "kimi-k3:cloud") not in models
    assert ("openrouter", "openrouter/free") not in models


def test_migrated_registry_derives_local_fallback_binding_only_when_selected(slots_file, monkeypatch):
    monkeypatch.setattr(model_sockets.platform, "node", lambda: "test-host")
    # Materialize the real pure migration projection before adding a new fallback.
    # Disk migration itself is guarded separately; this regression exercises the
    # already-migrated registry's call-time ephemeral binding.
    legacy = slots_config.load_slots_config(slots_file)
    migrated = dict(legacy)
    migrated["model_sockets"] = model_sockets._legacy_projection(legacy, "test-host")
    migrated["version"] = max(legacy.get("version", 3), 4)
    Path(slots_file).write_text(
        json.dumps(migrated, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    current = slots_config.core_system_agents_snapshot(slots_file)
    slots_config.change_core_system_agent(
        "buddha_chat", current["configuration_version"],
        {"model_fallbacks": [{"backend": "ollama", "model": "qwen3.5:4b"}]},
        path=slots_file,
    )
    config = slots_config.load_slots_config(slots_file)
    target_id = model_sockets.socket_id("ollama", "qwen3.5:4b", "test-host")
    assert target_id not in config["model_sockets"]["sockets"]

    binding = model_sockets.model_binding_for_call(
        "agent:buddha_chat", "ollama", "qwen3.5:4b", agent_id="buddha_chat",
        path=slots_file, require_config=True,
    )
    assert binding["socket_id"] == target_id
    assert binding["agent_id"] == "buddha_chat"
    assert binding["priority"] == "foreground"
    assert target_id not in slots_config.load_slots_config(slots_file)["model_sockets"]["sockets"]
    with pytest.raises(RuntimeError, match="model_socket_binding_unavailable"):
        model_sockets.model_binding_for_call(
            "agent:buddha_chat", "ollama", "not-configured", agent_id="buddha_chat",
            path=slots_file, require_config=True,
        )


def test_explicitly_disabled_socket_binding_is_not_overridden_by_profile_fallback(monkeypatch):
    monkeypatch.setattr(model_sockets.platform, "node", lambda: "test-host")
    profile = _profile("worker-fallback-test", chain=[{"backend": "ollama", "model": "qwen3.5:4b"}])
    target_id = model_sockets.socket_id("ollama", "qwen3.5:4b", "test-host")
    binding_id = model_sockets._binding_id("worker-fallback-test", target_id)
    state = {
        "schema": model_sockets.SCHEMA,
        "host_id": "test-host",
        "sockets": {target_id: model_sockets._new_socket("ollama", "qwen3.5:4b", "test-host")},
        "bindings": {binding_id: {**model_sockets._new_binding("worker-fallback-test", target_id),
                                  "enabled": False}},
    }
    config = {"slots": {"worker-fallback-test": profile}, "dynamic_workers": [],
              "model_sockets": state}
    with pytest.raises(RuntimeError, match="model_socket_binding_unavailable"):
        model_sockets._binding_from_config(config, "v1", "worker-fallback-test", "ollama", "qwen3.5:4b")


def test_main_tool_loop_uses_only_explicit_chain_after_typed_preanswer_failure(monkeypatch):
    chain = [{"backend": "openrouter", "model": "openrouter/free"}]
    runtime, session, primary, fallback = _runtime_profile(monkeypatch, chain)
    calls = []

    async def fake_call(backend, *args, **kwargs):
        calls.append((backend, kwargs["model"]))
        if backend is primary:
            return _safe_ollama_error(503)
        return {"content": "Antwort aus dem Fallback", "tool_calls": None,
                "raw_message": {"role": "assistant", "content": "Antwort aus dem Fallback"}}

    runtime._chat_with_compute_turn = fake_call
    answer = asyncio.run(runtime._tool_loop_impl([], session, [], backend=primary,
                                                model="qwen3.8:4b", context_limit=8192))
    assert answer == "Antwort aus dem Fallback"
    assert calls == [(primary, "qwen3.8:4b"), (fallback, "openrouter/free")]


def test_partial_answer_tool_call_and_quota_never_trigger_fallback(monkeypatch):
    chain = [{"backend": "openrouter", "model": "openrouter/free"}]
    runtime, session, primary, fallback = _runtime_profile(monkeypatch, chain)
    calls = []
    responses = [
        _safe_ollama_error(503, content="Teilantwort"),
        _safe_ollama_error(503, tool_calls=[{"id": "tool-1"}]),
        _safe_ollama_error(429, quota=True),
    ]

    async def fake_call(backend, *args, **kwargs):
        calls.append((backend, kwargs["model"]))
        return responses.pop(0)

    runtime._chat_with_compute_turn = fake_call
    for _ in range(3):
        result, used_backend, used_model = asyncio.run(runtime._chat_with_configured_fallbacks(
            session, primary, "qwen3.8:4b", [], tools=[], think=False,
        ))
        assert result.get("error") == "provider error"
        assert used_backend is primary and used_model == "qwen3.8:4b"
    assert calls == [(primary, "qwen3.8:4b")] * 3
    assert fallback not in [backend for backend, _ in calls]


def test_bare_http_status_error_429_is_not_fallback_safe():
    import httpx

    request = httpx.Request("POST", "https://provider.invalid/chat")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError("HTTP 429", request=request, response=response)
    assert not ChatRuntime._safe_preanswer_fallback_failure(error=error)


def test_normalized_ollama_quota_response_stays_blocked():
    from hub._services.llm.backend_errors import classify_ollama_error

    detail = classify_ollama_error(
        {"error": "Monthly usage limit reached"}, status_code=429,
    )
    assert detail["quota_exceeded"] is True
    result = {
        "error": "provider error",
        "content": "",
        "thinking": "",
        "tool_calls": None,
        "raw_message": {"role": "assistant", "content": ""},
        "backend_error": detail,
    }
    assert not ChatRuntime._safe_preanswer_fallback_failure(result=result)


def test_task_required_model_blocks_fallback_before_second_inference(monkeypatch):
    runtime, session, primary, fallback = _runtime_profile(
        monkeypatch, [{"backend": "openrouter", "model": "openrouter/free"}]
    )
    class Binding:
        def assert_active(self):
            return None
        def task_snapshot(self):
            return {"required_model": "qwen3.8:4b"}
    session.worker_task_binding = Binding()
    calls = []

    async def fake_call(backend, *args, **kwargs):
        calls.append((backend, kwargs["model"]))
        return _safe_ollama_error(503)

    runtime._chat_with_compute_turn = fake_call
    with pytest.raises(RuntimeError, match="Task passt nicht"):
        asyncio.run(runtime._chat_with_configured_fallbacks(
            session, primary, "qwen3.8:4b", [], tools=[], think=False,
        ))
    assert calls == [(primary, "qwen3.8:4b")]
    assert fallback not in [backend for backend, _ in calls]


def test_missing_native_reader_cannot_activate_a_prompt_supplied_chain(monkeypatch):
    primary = OllamaBackend(base_url="http://127.0.0.1:11434", default_model="qwen3.8:4b")
    fallback = OpenRouterBackend(base_url="https://openrouter.ai/api/v1",
                                 api_key="fixture-only", default_model="openrouter/free")
    runtime = ChatRuntime(primary)
    session = runtime.get_session("unbound-session")
    monkeypatch.setattr(model_sockets, "resolve_fallback_backend", lambda target: fallback)
    calls = []

    async def fake_call(backend, *args, **kwargs):
        calls.append(backend)
        return {"content": "primary", "tool_calls": None}

    runtime._chat_with_compute_turn = fake_call
    result, used_backend, _ = asyncio.run(runtime._chat_with_configured_fallbacks(
        session, primary, "qwen3.8:4b", [], tools=[], think=False,
    ))
    assert result["content"] == "primary"
    assert used_backend is primary
    assert calls == [primary]

_RESOLVER_MODULE = "hub._services.chat.telegram_chat"


def _install_loaded_resolver_factory(monkeypatch, factory):
    """Represent the already-loaded BACH factory without importing its connector module."""
    module = types.ModuleType(_RESOLVER_MODULE)
    module._get_or_create_backend = factory
    monkeypatch.setitem(sys.modules, _RESOLVER_MODULE, module)
    return module


def test_real_fallback_resolver_requires_loaded_factory_without_import_or_start(monkeypatch):
    monkeypatch.delitem(sys.modules, _RESOLVER_MODULE, raising=False)
    real_import = builtins.__import__

    def deny_connector_import(name, *args, **kwargs):
        if name == _RESOLVER_MODULE:
            raise AssertionError("Resolver darf den Connector nicht importieren")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_connector_import)
    with pytest.raises(RuntimeError, match="fallback_backend_resolver_unavailable"):
        model_sockets.resolve_fallback_backend({"backend": "ollama", "model": "qwen3.5:4b"})
    assert _RESOLVER_MODULE not in sys.modules


def test_real_fallback_resolver_accepts_loaded_cloud_and_external_targets(monkeypatch):
    cloud = OllamaBackend(base_url="http://127.0.0.1:11434", default_model="kimi-k3:cloud")
    external = OpenRouterBackend(base_url="https://openrouter.ai/api/v1",
                                api_key="fixture-only", default_model="openrouter/free")
    calls = []
    selected = {("ollama-cloud", "kimi-k3:cloud"): cloud,
                ("openrouter", "openrouter/free"): external}

    def factory(backend, model):
        calls.append((backend, model))
        return selected[(backend, model)]

    _install_loaded_resolver_factory(monkeypatch, factory)
    assert model_sockets.resolve_fallback_backend(
        {"backend": "ollama-cloud", "model": "kimi-k3:cloud"}
    ) is cloud
    assert model_sockets.resolve_fallback_backend(
        {"backend": "openrouter", "model": "openrouter/free"}
    ) is external
    assert calls == [("ollama-cloud", "kimi-k3:cloud"), ("openrouter", "openrouter/free")]


@pytest.mark.parametrize("case", ["wrong_provider_class", "wrong_default_model", "external_at_localhost"])
def test_real_fallback_resolver_rejects_class_model_and_endpoint_mismatch(monkeypatch, case):
    target = {"backend": "ollama", "model": "qwen3.5:4b"}
    if case == "wrong_provider_class":
        backend = OpenRouterBackend(base_url="https://openrouter.ai/api/v1",
                                    api_key="fixture-only", default_model="qwen3.5:4b")
    elif case == "wrong_default_model":
        backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model="qwen3.6:4b")
    else:
        target = {"backend": "openrouter", "model": "openrouter/free"}
        backend = OpenRouterBackend(base_url="http://127.0.0.1:11434",
                                    api_key="fixture-only", default_model="openrouter/free")

    _install_loaded_resolver_factory(monkeypatch, lambda _provider, _model: backend)
    with pytest.raises(RuntimeError, match="fallback_backend_identity_mismatch"):
        model_sockets.resolve_fallback_backend(target)


@pytest.mark.parametrize(("primary_backend", "primary_model", "chain", "message"), [
    ("openrouter", "openrouter/free", [{"backend": "openai", "model": "gpt-4o"}], "OpenRouter-Free"),
    ("ollama", "qwen3.8:4b", [{"backend": "ollama", "model": "qwen3.8:4b"}], "Primärziel"),
])
def test_core_and_worker_cas_reject_chain_against_effective_primary(
        slots_file, primary_backend, primary_model, chain, message):
    core_before = slots_config.core_system_agents_snapshot(slots_file)
    core_bytes = Path(slots_file).read_bytes()
    with pytest.raises(ValueError, match=message):
        slots_config.change_core_system_agent(
            "buddha_chat", core_before["configuration_version"],
            {"backend": primary_backend, "model": primary_model, "model_fallbacks": chain},
            path=slots_file,
        )
    assert Path(slots_file).read_bytes() == core_bytes

    worker = slots_config.add_worker({"name": "CAS fallback check", "sub_mode": "hintergrund_worker"},
                                    path=slots_file)
    worker_before = slots_config.worker_configuration_snapshot(worker["id"], path=slots_file)
    worker_bytes = Path(slots_file).read_bytes()
    with pytest.raises(ValueError, match=message):
        slots_config.change_worker_configuration(
            worker["id"], worker_before["configuration_version"],
            {"backend": primary_backend, "model": primary_model, "model_fallbacks": chain},
            path=slots_file,
        )
    assert Path(slots_file).read_bytes() == worker_bytes


def test_self_managed_cli_connect_error_does_not_retry_after_tool_effect(monkeypatch):
    import httpx

    primary = CLIBackend(cli_name="claude", cli_path="fixture-claude",
                         default_model="claude-sonnet-4-6")
    runtime = ChatRuntime(primary)
    session = runtime.get_session("cli-worker-fallback")
    model = "claude-sonnet-4-6"
    profile = _profile(
        session.chat_id, backend="claude", model=model,
        chain=[{"backend": "openrouter", "model": "openrouter/free"}],
    )
    profile["allow_tools"] = True
    profile["allowed_tools"] = ["task_manage"]
    session.worker_slot_reader = lambda: profile

    class Binding:
        def assert_active(self):
            return None

        def task_snapshot(self):
            return {"required_model": model, "assigned_slot": session.chat_id}

    session.worker_task_binding = Binding()
    session.mode = "safe"
    session.allow_tools = True
    session.allowed_tools = ["task_manage"]
    assert model_sockets.profile_backend_matches("claude", primary, model)
    assert runtime._native_model_fallback_route(session, primary, model) is not None

    side_effects = []
    resolver_calls = []
    request = httpx.Request("POST", "https://cli.invalid/chat")

    async def fail_after_tool_dispatch(*args, **kwargs):
        side_effects.append("tool-effect")
        raise httpx.ConnectError("connection failed after tool dispatch", request=request)

    fallback = OpenRouterBackend(base_url="https://openrouter.ai/api/v1",
                                 api_key="fixture-only", default_model="openrouter/free")
    monkeypatch.setattr(primary, "chat_bound", fail_after_tool_dispatch)
    monkeypatch.setattr(
        model_sockets, "resolve_fallback_backend",
        lambda target: resolver_calls.append(target) or fallback,
    )
    context_token = runtime._compute_turn_context.set((session.chat_id, "foreground"))
    try:
        with pytest.raises(httpx.ConnectError):
            asyncio.run(runtime._chat_with_configured_fallbacks(
                session, primary, model, [], tools=[{"type": "function"}], think=False,
            ))
    finally:
        runtime._compute_turn_context.reset(context_token)
    assert side_effects == ["tool-effect"]
    assert resolver_calls == []
