# SPDX-License-Identifier: MIT
"""Fixture-only adapter checks; never contacts an installed model server."""
import asyncio
from types import SimpleNamespace

import pytest
from hub._services.chat import resource_load_pending as loading
from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.chat.resource_model_port import (
    GuardedModelPort,
    ModelReturnUnconfirmed,
)

GIB = 1024**3


def test_api_or_metal_size_is_never_a_native_memory_credit():
    # RSS and API size deliberately differ by two orders of magnitude.
    assert loading.native_resident_credit(api_size=23 * GIB, process_rss=128 * 1024**2) is None
    assert loading.native_resident_credit(api_size=19 * GIB, process_rss=21 * GIB) is None


def test_abort_requires_existing_gate_and_exact_process_before_post(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    spec = SimpleNamespace(model="fixture:1", digest="a" * 64, port=11434)
    identity = {"pid": 10, "created_at": 2.0, "boot_time": 1.0}
    calls = []
    resident = [True]
    def transport(spec, path, payload):
        calls.append((path, payload))
        if path == "/api/version": return {"version": "0.33.3"}
        if path == "/api/tags": return {"models": [{"name": spec.model, "digest": spec.digest}]}
        if path == "/api/ps": return {"models": [{"name": spec.model, "digest": spec.digest, "size": 10}] if resident[0] else []}
        assert path == "/api/generate"
        resident[0] = False
        return {"done": True, "done_reason": "unload"}
    monkeypatch.setattr(loading, "native_model_process", lambda _spec: (identity, 10))
    port = GuardedModelPort(transport=transport)
    port.abort_load(spec, identity, lambda: None)
    assert sum(payload is not None for _, payload in calls) == 1
    assert not (HostInferenceGate().root / "unload-pending.json").exists()
    resident[0] = True
    before = len(calls)
    with pytest.raises(ModelReturnUnconfirmed):
        port.abort_load(spec, {**identity, "created_at": 3.0}, lambda: None)
    assert not any(payload is not None for _, payload in calls[before:])


def test_unsettled_inference_dispatch_cannot_be_unloaded_by_load_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    gate = HostInferenceGate()
    async def leave_uncertain():
        async with gate.turn("fixture", "background", model_target={
                "socket_id": "s", "binding_id": "b", "agent_id": "a", "backend": "ollama", "model": "m"}):
            gate.begin_dispatch("a" * 64, {"socket_id": "s", "binding_id": "b", "agent_id": "a", "backend": "ollama", "model": "m"})
    asyncio.run(leave_uncertain())
    posts = []
    port = GuardedModelPort(transport=lambda *_: posts.append(1), timeout_seconds=.1)
    with pytest.raises(ModelReturnUnconfirmed):
        port.abort_load(SimpleNamespace(model="m", digest="a" * 64, port=11434),
                        {"pid": 10, "created_at": 2.0, "boot_time": 1.0}, lambda: None)
    assert posts == [] and gate.status()["dispatch_pending"]


@pytest.mark.parametrize("terminal", [True, False])
def test_staged_bridge_binds_warmup_and_confirms_only_after_owner_exit(monkeypatch, terminal):
    import time
    from contextlib import asynccontextmanager

    from hub._services.chat import local_resource_reserve
    from hub._services.chat import resource_host_client as bridge
    monkeypatch.setenv("BACH_RESOURCE_BROKER_CONFIG", "/fixture/client.json")
    target = {"socket_id": "model", "model": "fixture:1", "digest": "a" * 64,
              "port": 11434, "context_tokens": 4096, "load_policy_sha256": "e" * 64}
    events = []
    @asynccontextmanager
    async def staged(*args, check_ready):
        check_ready()
        ticket = {"successful": False, "renewal": None, "permit": {
            "spec": {k: target[k] for k in ("model", "digest", "port", "context_tokens")},
            "policy_sha256": "e" * 64, "deadline": time.monotonic() + 300}}
        events.append("load-permission")
        yield ticket
        assert events[-1] == "inference-owner-exited"
        events.append("native-proof" if ticket["successful"] else "guarded-abort")
        ticket["completion"] = {"state": "RUNNING" if ticket["successful"] else "RETURN_REQUESTED"}
    modules = {
        "ocean_resources.configuration": SimpleNamespace(read_client=lambda _: ("fixture", [target])),
        "ocean_resources.model_client": SimpleNamespace(model_turn=lambda *a, **kw: pytest.fail("full grant used for staged load")),
        "ocean_resources.model_executor": SimpleNamespace(ModelSpec=lambda **kw: SimpleNamespace(**kw)),
        "ocean_resources.model_load_client": SimpleNamespace(model_load_turn=staged),
    }
    monkeypatch.setattr(bridge, "load_verified", lambda _: modules)
    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: ({}, "e" * 64))
    monkeypatch.setattr(GuardedModelPort, "verify_available", lambda *args: None)
    backend = SimpleNamespace(base_url="http://127.0.0.1:11434", num_ctx=4096)
    async def scenario():
        warmup = {"task": asyncio.current_task(), "backend": backend, "model": "fixture:1",
                  "chat_id": "warm", "allow_cold": True, "check": lambda: None, "result": None}
        async with bridge.resource_model_turn(backend, "fixture:1", "warm", "background", warmup=warmup) as ready:
            ready()
            events.append("inference-owner-entered")
            warmup["resource_load_ticket"]["transport_terminal"] = terminal
            warmup["result"] = {"state": "loaded"}
            events.append("inference-owner-exited")
        assert warmup["result"]["state"] == ("loaded" if terminal else "resource_load_aborted")
    asyncio.run(scenario())
    assert events[-1] == ("native-proof" if terminal else "guarded-abort")


def test_model_loading_capability_is_unavailable_for_current_native_accounting():
    assert GuardedModelPort.supports_load_pending is False


@pytest.mark.parametrize("failure", [None, "second_model", "context", "process", "policy", "unknown"])
def test_independent_native_proof_keeps_owner_until_accept(tmp_path, monkeypatch, failure):
    import shutil

    import psutil
    from hub._services.chat import host_resource_observation, local_resource_reserve
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    spec = SimpleNamespace(model="fixture:27b", digest="a" * 64, port=11434,
                           context_tokens=16384, fingerprint=lambda: "w" * 64)
    identity = {"pid": 10, "created_at": 2.0, "boot_time": 1.0}
    policy = {"enabled": True, "memory_reserve_bytes": 2 * GIB, "disk_reserve_bytes": GIB,
        "cold_start": {"enabled": True, "min_available_bytes": 6 * GIB, "max_load_seconds": 300,
                       "max_pressure_level": 2, "max_swap_growth_bytes": 8 * GIB},
        "models": {spec.model: {"digest": spec.digest, "num_ctx": 16384,
                               "kv_headroom_bytes": GIB, "overhead_bytes": GIB // 2}}}
    policy_reads, process_reads = [0], [0]
    def read_policy():
        policy_reads[0] += 1
        return policy, ("f" * 64 if failure == "policy" and policy_reads[0] > 1 else loading.REVIEWED_POLICY_SHA256)
    def process(_):
        process_reads[0] += 1
        value = {**identity, "created_at": 3.0} if failure == "process" and process_reads[0] > 1 else identity
        return value, 128 * 1024**2
    native = SimpleNamespace(ProcessIdentity=lambda **kw: SimpleNamespace(**kw),
                             LoadObservation=lambda *args: SimpleNamespace(args=args))
    monkeypatch.setattr(loading, "load_verified", lambda _: {"ocean_resources.model_loading": native})
    monkeypatch.setattr(loading, "native_model_process", process)
    monkeypatch.setattr(local_resource_reserve, "read_policy", read_policy)
    monkeypatch.setattr(local_resource_reserve, "_data_roots", lambda: {"runtime": tmp_path})
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * GIB))
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=4 * GIB))
    monkeypatch.setattr(host_resource_observation, "observe_host_resources", lambda _: (
        {} if failure == "unknown" else {"pressure_level": 1, "swap_used_bytes": 0}))
    target = {"name": spec.model, "digest": spec.digest, "size": 23 * GIB,
              "context_length": 8192 if failure == "context" else 16384}
    def transport(spec, path, payload):
        assert payload is None
        if path == "/api/version": return {"version": "0.33.3"}
        if path == "/api/tags": return {"models": [target]}
        models = [target]
        if failure == "second_model": models.append({"name": "other", "digest": "b" * 64, "size": 1})
        return {"models": models}
    observed_owners = []
    def capacity():
        observed_owners.append(HostInferenceGate.current_owner())
        return "fixture-capacity"
    accepted = []
    def accept(proof):
        assert HostInferenceGate.current_owner() is observed_owners[-1]
        assert proof.args[-1] is None  # API/Metal/RSS never invent private memory credit.
        accepted.append(proof)
    call = lambda: GuardedModelPort(transport=transport).load_observation(
        spec, loading.REVIEWED_POLICY_SHA256, loaded=True, expected_process=identity,
        capacity_reader=capacity, accept=accept)
    if failure:
        with pytest.raises(ModelReturnUnconfirmed): call()
        assert accepted == []
    else:
        assert call() is accepted[0]
    assert HostInferenceGate().status()["active"] is False
