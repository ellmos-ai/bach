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
        "ocean_resources.configuration": SimpleNamespace(read_client=lambda _: (
            SimpleNamespace(authority_id="authority", host_id="host", client_id="bach"), [target])),
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


def test_cached_load_fields_without_live_authority_never_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    spec = SimpleNamespace(model="fixture:1", digest="a" * 64, port=11434, fingerprint=lambda: "f" * 64)
    permit = {"phase": "MAY_LOAD", "workload_sha256": spec.fingerprint(),
              "policy_sha256": loading.REVIEWED_POLICY_SHA256, "deadline": 110.0,
              "baseline": {"process": {"pid": 10, "created_at": 2.0, "boot_time": 1.0}}}
    async def scenario():
        async with HostInferenceGate().turn("fixture", "background", model_target={
                "socket_id": "s", "binding_id": "b", "agent_id": "a", "backend": "ollama", "model": spec.model}):
            with pytest.raises(ModelReturnUnconfirmed, match="live_authority"):
                GuardedModelPort(transport=lambda *args: pytest.fail("unproved authority reached metadata"),
                                 clock=lambda: 100).check_load_under_owner(spec, permit)
    asyncio.run(scenario())


@pytest.mark.parametrize("when", ["metadata", "intent"])
def test_abort_rechecks_process_after_metadata_and_durable_intent(tmp_path, monkeypatch, when):
    from tools.maintenance import memory_pressure_unload_guard as unload
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    spec = SimpleNamespace(model="fixture:1", digest="a" * 64, port=11434)
    expected = {"pid": 10, "created_at": 2.0, "boot_time": 1.0}
    process, posts = [expected], []
    def change():
        process[0] = {**expected, "pid": 11, "created_at": 3.0}
    def transport(_, path, payload):
        if path == "/api/version": return {"version": "0.33.3"}
        if path == "/api/tags": return {"models": [{"name": spec.model, "digest": spec.digest}]}
        if path == "/api/ps":
            if when == "metadata": change()
            return {"models": [{"name": spec.model, "digest": spec.digest, "size": 10}]}
        posts.append(payload)
        return {"done": True, "done_reason": "unload"}
    original = unload.record_intent
    def changed_after_intent(*args):
        result = original(*args)
        if when == "intent": change()
        return result
    monkeypatch.setattr(unload, "record_intent", changed_after_intent)
    monkeypatch.setattr(loading, "native_model_process", lambda _: (process[0], 10))
    with pytest.raises(ModelReturnUnconfirmed, match="process_identity"):
        GuardedModelPort(transport=transport).abort_load(spec, expected, lambda: None)
    assert posts == []


@pytest.mark.parametrize("resident_initially", [False, True])
def test_abort_terminal_commit_remains_inside_the_native_owner(tmp_path, monkeypatch, resident_initially):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    spec = SimpleNamespace(model="fixture:1", digest="a" * 64, port=11434)
    expected = {"pid": 10, "created_at": 2.0, "boot_time": 1.0}
    resident, phases = [resident_initially], []
    def transport(_, path, payload):
        if path == "/api/version": return {"version": "0.33.3"}
        if path == "/api/tags": return {"models": [{"name": spec.model, "digest": spec.digest}]}
        if path == "/api/ps": return {"models": [{"name": spec.model, "digest": spec.digest, "size": 10}] if resident[0] else []}
        resident[0] = False
        return {"done": True, "done_reason": "unload"}
    def accept():
        held = HostInferenceGate.current_owner()._check_owned_record()
        assert held.record["chat_id"] == "resource-model-return"
        phases.append("ABORTED-under-owner")
    monkeypatch.setattr(loading, "native_model_process", lambda _: (expected, 10))
    GuardedModelPort(transport=transport).abort_load(spec, expected, lambda: None, accept=accept)
    assert phases == ["ABORTED-under-owner"]
    assert not HostInferenceGate().status()["active"]


@pytest.mark.parametrize("failure", [None, "authority", "process", "deadline", "policy"])
def test_load_rechecks_native_permission_after_slow_metadata(tmp_path, monkeypatch, failure):
    from hub._services import ocean_resources_provider
    from hub._services.chat import local_resource_reserve
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    spec = SimpleNamespace(model="fixture:1", digest="a" * 64, port=11434, fingerprint=lambda: "f" * 64)
    expected = {"pid": 10, "created_at": 2.0, "boot_time": 1.0}
    state = {"metadata_done": False, "time": 100}
    permit = {"phase": "MAY_LOAD", "workload_sha256": spec.fingerprint(),
              "policy_sha256": loading.REVIEWED_POLICY_SHA256, "deadline": 110.0,
              "baseline": {"process": expected}, "writer_readback": {"fixture": True}}
    authority = {"host_id": "fixture-host", "authority_id": "fixture-writer", "client_id": "fixture-client"}
    checks, posts = [], []
    def verify(actual, **kwargs):
        assert actual is permit and {k: kwargs[k] for k in authority} == authority
        checks.append(state["metadata_done"])
        if failure == "authority" and state["metadata_done"]:
            raise RuntimeError("fixture native authority became terminal")
    monkeypatch.setattr(ocean_resources_provider, "load_verified", lambda _: {
        "ocean_resources.model_dispatch": SimpleNamespace(require_dispatch_permission=verify)})
    monkeypatch.setattr(loading, "native_model_process", lambda _: (
        {**expected, "created_at": 3.0} if failure == "process" and state["metadata_done"] else expected, 10))
    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: ({},
        "f" * 64 if failure == "policy" and state["metadata_done"] else loading.REVIEWED_POLICY_SHA256))
    def transport(_, path, payload):
        assert payload is None
        if path == "/api/version": return {"version": "0.33.3"}
        if path == "/api/tags": return {"models": [{"name": spec.model, "digest": spec.digest}]}
        state["metadata_done"] = True
        if failure == "deadline": state["time"] = 110
        return {"models": []}
    async def scenario():
        async with HostInferenceGate().turn("fixture", "background", model_target={
                "socket_id": "s", "binding_id": "b", "agent_id": "a", "backend": "ollama", "model": spec.model}):
            port = GuardedModelPort(transport=transport, clock=lambda: state["time"])
            if failure:
                with pytest.raises(ModelReturnUnconfirmed):
                    port.check_load_under_owner(spec, permit, authority=authority)
            else:
                port.check_load_under_owner(spec, permit, authority=authority)
                posts.append("fixture-only dispatch permitted")
    asyncio.run(scenario())
    assert checks == ([False] if failure in {"process", "deadline", "policy"} else [False, True])
    assert bool(posts) is (failure is None)


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


def test_ocean_resources_pin_contract_is_exact_29_files_at_0_2_0():
    from hub._services import ocean_resources_provider as provider

    pinned = provider.pin()
    assert pinned["schema"] == "bach.ocean-resources-pin.v1"
    assert pinned["version"] == "0.2.0"
    assert pinned["commit"] == "a27591b8f00d25994cfc3405d5a89308f0a23555"
    assert len(pinned["files"]) == 29
    assert all(path.startswith("ocean_resources/") for path in pinned["files"])


def test_verified_wired_resident_credit_delegates_strictly_through_load_verified(monkeypatch):
    seen = {}

    def fake_build(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(source="darwin-wired-metal-nocopy-vmstat.v2", bytes=16_842_752)

    monkeypatch.setattr(
        loading,
        "load_verified",
        lambda names: (
            {"ocean_resources.model_loading": SimpleNamespace(build_wired_resident_credit=fake_build)}
            if names == ("ocean_resources.model_loading",)
            else pytest.fail(f"unexpected provider load: {names}")
        ),
    )
    args = dict(
        scope="scope-sentinel",
        before_sample_epoch="epoch-1",
        after_sample_epoch="epoch-1",
        pre_commit_epoch="epoch-1",
        platform_sample="vmstat-1",
        observed_at=123.5,
    )
    credit = loading.verified_wired_resident_credit(**args)
    assert credit.source == "darwin-wired-metal-nocopy-vmstat.v2"
    assert credit.bytes == 16_842_752
    assert seen == args
    assert loading.native_resident_credit(api_size=19 * GIB, process_rss=20 * GIB) is None
    assert GuardedModelPort.supports_load_pending is False
