# SPDX-License-Identifier: MIT
"""Actual local-admission join behavior; no provider, model, or task is started."""
import asyncio

import pytest

from hub._services.chat import local_resource_reserve as reserve, model_sockets, slots_config
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.local_model_admission import compose_admission_receipt
from hub._services.llm.model_backend import OllamaBackend

MODEL = "example:small"
BINDING = {
    "socket_id": "model-0123456789abcdef01234567",
    "binding_id": "binding-0123456789abcdef01234567",
    "agent_id": "buddha_always_on",
    "backend": "ollama",
    "model": MODEL,
    "configuration_version": "a" * 64,
}


def receipt(state, *, admitted=False, enforced=True, retryable=False, **extra):
    result = {
        "schema": reserve.SCHEMA,
        "state": state,
        "admitted": admitted,
        "enforced": enforced,
        "retryable": retryable,
        **extra,
    }
    if state == "ready" and "capacity_basis" not in result:
        result["capacity_basis"] = "host_budget"
    return result


def runtime(monkeypatch, *, strict):
    backend = OllamaBackend(default_model=MODEL)
    instance = ChatRuntime(backend)
    instance.require_model_socket_config = strict
    monkeypatch.setattr(instance, "_uses_local_compute", lambda _backend: True)
    return instance, backend


def test_strict_unconfigured_reserve_is_unknown_after_binding_check(monkeypatch):
    instance, backend = runtime(monkeypatch, strict=True)

    async def probe(*_args):
        return receipt("not_configured", admitted=True, enforced=False)

    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(reserve, "read_policy", lambda: (None, None))
    binding_calls = []

    def binding(*args):
        binding_calls.append(args)
        return BINDING

    monkeypatch.setattr(instance, "_model_binding_for_session", binding)

    with pytest.raises(reserve.LocalReserveError, match="unknown_capacity"):
        asyncio.run(instance.prepare_inference_call(backend, MODEL))

    assert len(binding_calls) == 1
    assert binding_calls[0][0] == "runtime"
    assert binding_calls[0][1] is backend
    assert binding_calls[0][2] == MODEL
    evidence = compose_admission_receipt(
        receipt("not_configured", admitted=True, enforced=False),
        require_model_socket=True,
    )
    assert evidence["state"] == "unknown_capacity"
    assert evidence["admitted"] is False
    assert evidence["local_admission"]["reserve"] == {
        "schema": reserve.SCHEMA,
        "state": "not_configured",
        "configured": False,
        "enforced": False,
        "policy_version": None,
    }
    assert evidence["local_admission"]["capacity"] == {
        "status": "unknown",
        "certification": "not_provided",
    }


def test_disabled_reserve_is_configured_but_not_enforced():
    evidence = compose_admission_receipt(
        receipt("disabled", admitted=True, enforced=False, policy_version="b" * 64),
        binding=BINDING,
        require_model_socket=True,
    )
    assert evidence["state"] == "unknown_capacity"
    reserve_evidence = evidence["local_admission"]["reserve"]
    assert reserve_evidence["configured"] is True
    assert reserve_evidence["enforced"] is False
    assert evidence["local_admission"]["capacity"]["status"] == "unknown"


def test_ready_budget_and_socket_binding_do_not_certify_capacity(monkeypatch):
    instance, backend = runtime(monkeypatch, strict=True)

    async def probe(*_args):
        return receipt("ready", admitted=True, enforced=True, policy_version="c" * 64)

    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(reserve, "read_policy", lambda: ({}, "c" * 64))
    monkeypatch.setattr(instance, "_model_binding_for_session", lambda *_args: BINDING)

    result, binding = asyncio.run(instance.prepare_inference_call(backend, MODEL))

    assert binding == BINDING
    assert result["state"] == "ready" and result["admitted"] is True
    evidence = result["local_admission"]
    assert evidence["reserve"]["configured"] is True
    assert evidence["reserve"]["enforced"] is True
    assert evidence["model_socket"]["status"] == "bound"
    assert evidence["capacity"] == {
        "status": "budget_gate_passed",
        "certification": "not_provided",
    }
    assert "capacity_verified" not in evidence["capacity"]


@pytest.mark.parametrize("basis,status", [
    ("resident_model", "resident_model_reused"),
    ("running_server", "running_server_reused"),
])
def test_reused_local_target_is_not_reported_as_a_host_budget_pass(basis, status):
    evidence = compose_admission_receipt(
        receipt("ready", admitted=True, enforced=True, policy_version="f" * 64,
                capacity_basis=basis),
        binding=BINDING,
    )
    assert evidence["local_admission"]["capacity"] == {
        "status": status,
        "certification": "not_provided",
    }


def test_strict_ready_receipt_without_stable_binding_is_unknown():
    evidence = compose_admission_receipt(
        receipt("ready", admitted=True, enforced=True, policy_version="d" * 64),
        require_model_socket=True,
    )
    assert evidence["state"] == "unknown_model_socket_binding"
    assert evidence["admitted"] is False
    assert evidence["local_admission"]["model_socket"]["status"] == "unknown"
    assert evidence["local_admission"]["capacity"]["certification"] == "not_provided"


def test_unknown_resource_receipt_stays_retryable_and_capacity_unknown():
    evidence = compose_admission_receipt(
        receipt("unknown_resources", enforced=True, retryable=True, policy_version="e" * 64),
        require_model_socket=True,
    )
    assert evidence["state"] == "unknown_resources"
    assert evidence["retryable"] is True
    assert evidence["local_admission"]["reserve"]["configured"] is True
    assert evidence["local_admission"]["reserve"]["enforced"] is True
    assert evidence["local_admission"]["capacity"]["status"] == "unknown"


def test_unconfigured_legacy_runtime_stays_explicitly_unenforced(monkeypatch):
    instance, backend = runtime(monkeypatch, strict=False)

    async def probe(*_args):
        return receipt("not_configured", admitted=True, enforced=False)

    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(reserve, "read_policy", lambda: (None, None))
    monkeypatch.setattr(instance, "_model_binding_for_session", lambda *_args: None)

    result, binding = asyncio.run(instance.prepare_inference_call(backend, MODEL))

    assert binding is None
    assert result["state"] == "not_configured" and result["admitted"] is True
    assert result["local_admission"]["reserve"]["configured"] is False
    assert result["local_admission"]["reserve"]["enforced"] is False
    assert result["local_admission"]["capacity"]["status"] == "unknown"


@pytest.mark.parametrize(
    ("model", "uses_local"),
    [
        ("glm-5", False),
        ("glm-5:cloud", True),
    ],
)
def test_external_targets_bypass_local_reserve(monkeypatch, model, uses_local):
    backend = OllamaBackend(default_model=MODEL)
    instance = ChatRuntime(backend)
    instance.require_model_socket_config = True
    monkeypatch.setattr(instance, "_uses_local_compute", lambda _backend: uses_local)

    async def forbidden_probe(*_args):
        pytest.fail("External targets must not enter the local reserve gate")

    monkeypatch.setattr(reserve, "probe", forbidden_probe)

    result, binding = asyncio.run(instance.prepare_inference_call(backend, model))
    assert result is None and binding is None


@pytest.mark.parametrize("state", ["waiting_memory_reserve", "waiting_disk_reserve"])
def test_waiting_reserve_stays_retryable_with_stable_binding(state):
    result = compose_admission_receipt(
        receipt(state, admitted=False, enforced=True, retryable=True, policy_version="f" * 64),
        binding=BINDING,
        require_model_socket=True,
    )
    assert result["state"] == state
    assert result["admitted"] is False and result["retryable"] is True
    assert result["local_admission"]["model_socket"]["status"] == "bound"
    assert result["local_admission"]["capacity"]["status"] == "unknown"


@pytest.mark.parametrize("state", ["waiting_memory_reserve", "waiting_disk_reserve"])
def test_waiting_reserve_without_stable_binding_is_blocked(state):
    result = compose_admission_receipt(
        receipt(state, admitted=False, enforced=True, retryable=True, policy_version="1" * 64),
        require_model_socket=True,
    )
    assert result["state"] == "unknown_model_socket_binding"
    assert result["admitted"] is False and result["retryable"] is False


def test_strict_ready_with_configured_but_not_enforced_reserve_is_unknown():
    result = compose_admission_receipt(
        receipt("ready", admitted=True, enforced=False, policy_version="2" * 64),
        binding=BINDING,
        require_model_socket=True,
    )
    assert result["state"] == "unknown_capacity"
    assert result["admitted"] is False
    assert result["local_admission"]["reserve"]["configured"] is True
    assert result["local_admission"]["reserve"]["enforced"] is False
    assert result["local_admission"]["capacity"]["status"] == "unknown"


@pytest.mark.parametrize("binding", [{}, {"socket_id": "present-but-incomplete"}])
def test_incomplete_stable_binding_cannot_admit_ready_local_call(binding):
    result = compose_admission_receipt(
        receipt("ready", admitted=True, enforced=True, policy_version="3" * 64),
        binding=binding,
        require_model_socket=True,
    )
    assert result["state"] == "unknown_model_socket_binding"
    assert result["admitted"] is False and result["retryable"] is False
    assert result["local_admission"]["model_socket"]["status"] == "unknown"


@pytest.fixture
def socket_registry(tmp_path, monkeypatch):
    path = str(tmp_path / "slots.json")
    slots_config.initialize_slots_config(path)
    monkeypatch.setattr(slots_config, "DEFAULT_SLOTS_FILE", path)
    monkeypatch.setattr(model_sockets.platform, "node", lambda: "test-host")
    from hub._services import skill_source_service
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda _target: None)
    return path


def test_model_binding_for_call_shape_is_the_composed_socket_evidence(socket_registry):
    version = slots_config.core_system_agents_snapshot()["configuration_version"]
    model_sockets.migrate_model_sockets(version, path=socket_registry)
    profile = slots_config.get_system_slot("buddha_chat")
    binding = model_sockets.model_binding_for_call(
        "gui-web", profile["backend"], profile["model"],
        agent_id="buddha_chat", path=socket_registry, require_config=True,
    )
    assert set(binding) == {
        "socket_id", "binding_id", "agent_id", "backend", "model",
        "configuration_version", "priority", "context_tokens",
    }
    assert binding["agent_id"] == "buddha_chat"
    result = compose_admission_receipt(
        receipt("ready", admitted=True, enforced=True, policy_version="4" * 64),
        binding=binding,
        require_model_socket=True,
    )
    assert result["local_admission"]["model_socket"]["status"] == "bound"
    assert result["local_admission"]["model_socket"]["configuration_version"] == binding["configuration_version"]
