# SPDX-License-Identifier: MIT
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub._services.chat import resource_host_client as bridge


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("BACH_RESOURCE_BROKER_CONFIG", "/fixture/client.json")
    events = []
    target = {"socket_id": "model", "model": "fixture:1", "digest": "a" * 64,
              "port": 11434, "context_tokens": 4096}
    @asynccontextmanager
    async def turn(client, socket, slot, priority, *, check_ready):
        assert socket == "model" and slot == "bach-model"
        check_ready()
        events.append("grant")
        try:
            yield
        finally:
            events.append("end_turn")
    modules = {
        "ocean_resources.configuration": SimpleNamespace(read_client=lambda p: ("fixture", [target])),
        "ocean_resources.model_client": SimpleNamespace(model_turn=turn),
        "ocean_resources.model_executor": SimpleNamespace(ModelSpec=lambda **kw: SimpleNamespace(**kw)),
    }
    monkeypatch.setattr(bridge, "load_verified", lambda names: modules)
    from hub._services.chat.resource_model_port import GuardedModelPort
    monkeypatch.setattr(GuardedModelPort, "verify_available", lambda self, spec: events.append("verify_model"))
    backend = SimpleNamespace(base_url="http://127.0.0.1:11434", num_ctx=4096)
    return backend, events


def test_configured_model_preserves_task_check_and_scope(configured):
    backend, events = configured
    async def scenario():
        async with bridge.resource_model_turn(backend, "fixture:1", "private-chat", "background",
                                              check_ready=lambda: events.append("native_check")) as check:
            check()
            events.append("inference")
    asyncio.run(scenario())
    assert events.index("grant") < events.index("verify_model") < events.index("inference") < events.index("end_turn")
    assert events.count("native_check") >= 3


def test_enabled_but_unavailable_provider_fails_before_any_model(configured, monkeypatch):
    backend, events = configured
    def unavailable(names):
        raise RuntimeError("fixture provider unavailable")
    monkeypatch.setattr(bridge, "load_verified", unavailable)
    async def scenario():
        async with bridge.resource_model_turn(backend, "fixture:1", "chat", "foreground"):
            pytest.fail("unbrokered fallback")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(scenario())
    assert events == []


@pytest.mark.parametrize("change", ["model", "context", "port"])
def test_unprofiled_model_endpoint_or_context_never_acquires(configured, change):
    backend, events = configured
    model = "fixture:1"
    if change == "model":
        model = "different:1"
    elif change == "context":
        backend.num_ctx = 8192
    else:
        backend.base_url = "http://127.0.0.1:11435"
    async def scenario():
        async with bridge.resource_model_turn(backend, model, "chat", "foreground"):
            pytest.fail("unprofiled inference")
    with pytest.raises(bridge.ResourceHostUnavailable):
        asyncio.run(scenario())
    assert events == []


def test_endpoint_change_after_admission_is_caught_before_inference(configured):
    backend, events = configured
    async def scenario():
        async with bridge.resource_model_turn(backend, "fixture:1", "chat", "foreground") as check:
            backend.base_url = "http://127.0.0.1:11435"
            with pytest.raises(bridge.ResourceHostUnavailable):
                check()
    asyncio.run(scenario())
    assert events[-1] == "end_turn"


def test_unconfigured_and_external_calls_need_no_local_authority(monkeypatch):
    monkeypatch.delenv("BACH_RESOURCE_BROKER_CONFIG", raising=False)
    monkeypatch.setattr(bridge, "load_verified", lambda _: pytest.fail("unexpected provider lookup"))
    async def scenario():
        async with bridge.resource_model_turn(SimpleNamespace(base_url="http://127.0.0.1:11434"), "x", "c", "foreground"):
            pass
        monkeypatch.setenv("BACH_RESOURCE_BROKER_CONFIG", "/fixture/client.json")
        async with bridge.resource_model_turn(SimpleNamespace(base_url="https://remote.invalid"), "x", "c", "foreground"):
            pass
    asyncio.run(scenario())


def test_external_endpoint_cannot_become_local_inside_unbrokered_turn(monkeypatch):
    monkeypatch.setenv("BACH_RESOURCE_BROKER_CONFIG", "/fixture/client.json")
    backend = SimpleNamespace(base_url="https://remote.invalid")
    async def scenario():
        async with bridge.resource_model_turn(backend, "x", "c", "foreground") as ready:
            backend.base_url = "http://127.0.0.1:11434"
            with pytest.raises(bridge.ResourceHostUnavailable):
                ready()
    asyncio.run(scenario())


def test_real_runtime_resource_grant_wraps_existing_inference_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    from hub._services.chat import host_inference_gate, local_resource_reserve
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.llm.model_backend import OllamaBackend
    events = []
    @asynccontextmanager
    async def resource(*args, check_ready=None, **kwargs):
        assert events == ["reserve"]  # Read-only target classification precedes ownership.
        events.append("resource_grant")
        check_ready()
        try:
            yield check_ready
        finally:
            events.append("resource_end")
    @asynccontextmanager
    async def inference(self, *args, **kwargs):
        assert events == ["reserve", "resource_grant"]
        events.append("inference_lock")
        try:
            yield
        finally:
            events.append("inference_unlock")
    monkeypatch.setattr(bridge, "resource_model_turn", resource)
    monkeypatch.setattr(host_inference_gate.HostInferenceGate, "turn", inference)
    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: ({}, "fixture"))
    backend = OllamaBackend(base_url="http://127.0.0.1:11434")
    runtime = ChatRuntime(backend)
    async def prepare(*args, **kwargs):
        events.append("reserve")
        return {"admitted": True, "state": "admitted", "policy_version": "fixture"}, None
    async def chat(*args, **kwargs):
        events.append("model")
        return {"content": "fixture"}
    monkeypatch.setattr(runtime, "prepare_inference_call", prepare)
    monkeypatch.setattr(backend, "chat", chat)
    asyncio.run(runtime._chat_with_compute_turn(backend, []))
    assert events == ["reserve", "resource_grant", "inference_lock", "reserve", "model", "inference_unlock", "resource_end"]


def test_local_binding_revocation_during_broker_admission_prevents_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("BACH_RESOURCE_BROKER_CONFIG", "/fixture/client.json")
    from hub._services.chat import host_inference_gate, local_resource_reserve
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.llm.model_backend import OllamaBackend
    backend = OllamaBackend(base_url="http://127.0.0.1:11434")
    runtime = ChatRuntime(backend)
    valid = [True]
    events = []
    def binding(*args):
        if not valid[0]:
            raise RuntimeError("model_socket_binding_unavailable")
    async def prepare(*args, **kwargs):
        events.append("probe")
        return {"admitted": True, "state": "admitted", "policy_version": "fixture"}, None
    @asynccontextmanager
    async def resource(*args, check_ready=None, **kwargs):
        check_ready()
        events.append("resource_wait")
        valid[0] = False
        yield check_ready
    def forbidden(*args, **kwargs):
        pytest.fail("revoked local model reached ownership or dispatch")
    monkeypatch.setattr(runtime, "_model_binding_for_session", binding)
    monkeypatch.setattr(runtime, "prepare_inference_call", prepare)
    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: ({}, "fixture"))
    monkeypatch.setattr(bridge, "resource_model_turn", resource)
    monkeypatch.setattr(host_inference_gate.HostInferenceGate, "turn", forbidden)
    monkeypatch.setattr(backend, "chat", forbidden)
    with pytest.raises(RuntimeError, match="model_socket_binding_unavailable"):
        asyncio.run(runtime._chat_with_compute_turn(backend, []))
    assert events == ["probe", "resource_wait"]

@pytest.mark.parametrize("endpoint", ["http://0.0.0.0:11434", "", None])
def test_native_local_unreviewed_endpoint_never_bypasses_enabled_broker(
        tmp_path, monkeypatch, endpoint):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("BACH_RESOURCE_BROKER_CONFIG", "/fixture/unavailable-client.json")
    from hub._services.chat import host_inference_gate, local_resource_reserve
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.llm.model_backend import OllamaBackend

    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: (None, None))
    events = []

    def provider(*args, **kwargs):
        events.append("provider")
        pytest.fail("unreviewed endpoint must fail before authority lookup")

    @asynccontextmanager
    async def inference(self, *args, **kwargs):
        events.append("inference")
        yield

    async def model(*args, **kwargs):
        events.append("model")
        return {"content": "synthetic"}

    monkeypatch.setattr(bridge, "load_verified", provider)
    monkeypatch.setattr(host_inference_gate.HostInferenceGate, "turn", inference)
    backend = OllamaBackend(base_url="http://127.0.0.1:11434")
    backend.base_url = endpoint
    monkeypatch.setattr(backend, "chat", model)
    runtime = ChatRuntime(backend)
    assert runtime._uses_local_compute(backend)
    with pytest.raises(bridge.ResourceHostUnavailable, match="resource_model_endpoint_not_reviewed"):
        asyncio.run(runtime._chat_with_compute_turn(backend, []))
    assert events == []
