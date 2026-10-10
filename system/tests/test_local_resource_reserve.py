# SPDX-License-Identifier: MIT
"""Fake model metadata and isolated files; no real inference or task writes."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from hub._services.chat import local_resource_reserve as reserve
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.llm.model_backend import OllamaBackend

GIB = reserve.GIB
MODEL = "example:small"
DIGEST = "a" * 64


def policy():
    return {"schema": reserve.SCHEMA, "enabled": True,
            "memory_reserve_bytes": GIB, "disk_reserve_bytes": GIB,
            "wait_seconds": 2, "poll_seconds": 1,
            "models": {MODEL: {"digest": DIGEST, "weight_budget_bytes": 2 * GIB,
                               "kv_headroom_bytes": GIB // 2, "overhead_bytes": GIB // 4,
                               "num_ctx": 1024}}}


@pytest.fixture
def resources(tmp_path, monkeypatch):
    path = tmp_path / "resource-reserve.json"
    path.write_text(json.dumps(policy()), encoding="utf-8")
    monkeypatch.setattr(reserve, "policy_path", lambda: path)
    monkeypatch.setattr(reserve, "_data_roots", lambda: {
        "taskdb": tmp_path / "db", "slots": tmp_path / "slots", "runtime": tmp_path / "runtime"})
    monkeypatch.setattr(reserve.psutil, "virtual_memory", lambda: SimpleNamespace(total=32 * GIB, available=8 * GIB))
    monkeypatch.setattr(reserve.shutil, "disk_usage", lambda p: SimpleNamespace(free=4 * GIB))
    async def observed(*_):
        return {"external": False, "digest": DIGEST, "weight_floor_bytes": 2 * GIB,
                "resident_context": None}
    monkeypatch.setattr(reserve, "observe_ollama", observed)
    return path, OllamaBackend(default_model=MODEL, num_ctx=1024)


def test_absent_policy_preserves_legacy_without_creating_runtime(tmp_path, monkeypatch):
    path = tmp_path / "absent" / "policy.json"
    monkeypatch.setattr(reserve, "policy_path", lambda: path)
    async def forbidden(*_): pytest.fail("No metadata request without configured reserve policy")
    monkeypatch.setattr(reserve, "observe_ollama", forbidden)
    result = asyncio.run(reserve.probe(object(), MODEL))
    assert result["state"] == "not_configured" and result["enforced"] is False
    assert result["admitted"] is True and not path.parent.exists()


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(extra="unknown"),
    lambda p: p.update(enabled=1),
    lambda p: p.update(wait_seconds=True),
    lambda p: p.update(poll_seconds=0),
    lambda p: p.update(memory_reserve_bytes=1),
    lambda p: p["models"][MODEL].update(digest="abc"),
    lambda p: p["models"][MODEL].update(kv_headroom_bytes=0),
    lambda p: p["models"][MODEL].update(num_ctx=262145),
    lambda p: p["models"].update({"glm:cloud": p["models"][MODEL]}),
])
def test_invalid_policy_fails_closed(resources, mutate):
    path, backend = resources
    raw = policy(); mutate(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")
    original = path.read_bytes()
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "invalid_policy" and result["retryable"] is False
    assert not result["admitted"] and path.read_bytes() == original


def test_oversized_policy_is_unknown_and_never_rewritten(resources):
    path, backend = resources
    path.write_bytes(b" " * (reserve._MAX_POLICY + 1))
    assert asyncio.run(reserve.probe(backend, MODEL))["state"] == "invalid_policy"
    assert path.stat().st_size == reserve._MAX_POLICY + 1


def test_duplicate_policy_keys_fail_closed(resources):
    path, backend = resources
    path.write_text(json.dumps(policy()).replace('"enabled": true', '"enabled": false, "enabled": true'), encoding="utf-8")
    assert asyncio.run(reserve.probe(backend, MODEL))["state"] == "invalid_policy"


def test_explicit_disable_does_not_probe_provider(resources, monkeypatch):
    path, backend = resources
    raw = policy(); raw["enabled"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    async def forbidden(*_): pytest.fail("No model request for explicitly disabled reserve barrier")
    monkeypatch.setattr(reserve, "observe_ollama", forbidden)
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "disabled" and result["enforced"] is False


def test_ready_receipt_distinguishes_configured_budget_from_observation(resources):
    path, backend = resources
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "ready" and result["admitted"]
    assert result["memory_required_bytes"] == int(3.75 * GIB)
    assert result["weight_request_bytes"] == 2 * GIB
    assert result["resident_weight_credit"] is False
    assert len(result["policy_version"]) == 64 and result["checked_at"]
    assert str(path) not in json.dumps(result)


def test_each_persistence_filesystem_requires_disk_reserve(resources, monkeypatch):
    _, backend = resources
    monkeypatch.setattr(reserve.shutil, "disk_usage", lambda p: SimpleNamespace(free=GIB // 2 if p.name == "slots" else 4 * GIB))
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "waiting_disk_reserve" and result["retryable"]
    assert result["disk_free_bytes"]["slots"] == GIB // 2


def test_available_ram_includes_foreign_compute_and_reserve(resources, monkeypatch):
    _, backend = resources
    monkeypatch.setattr(reserve.psutil, "virtual_memory", lambda: SimpleNamespace(total=32 * GIB, available=3 * GIB))
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "waiting_memory_reserve" and result["retryable"]


@pytest.mark.parametrize("context,credit", [(None, False), (512, False), (1024, True), (2048, True)])
def test_resident_weight_credit_requires_actual_context(resources, monkeypatch, context, credit):
    _, backend = resources
    async def observed(*_):
        return {"external": False, "digest": DIGEST, "weight_floor_bytes": 2 * GIB,
                "resident_context": context}
    monkeypatch.setattr(reserve, "observe_ollama", observed)
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["resident_weight_credit"] is credit
    assert result["weight_request_bytes"] == (0 if credit else 2 * GIB)
    assert result["memory_required_bytes"] == int((1.75 if credit else 3.75) * GIB)


@pytest.mark.parametrize("field,value", [("digest", "b" * 64), ("weight_budget_bytes", GIB), ("num_ctx", 2048)])
def test_catalog_or_context_conflict_cannot_retry(resources, field, value):
    path, backend = resources
    raw = policy(); raw["models"][MODEL][field] = value
    path.write_text(json.dumps(raw), encoding="utf-8")
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "model_budget_conflict" and not result["retryable"]


def test_unknown_provider_observation_is_not_empty_or_ready(resources, monkeypatch):
    _, backend = resources
    async def unavailable(*_): raise ValueError("private provider error")
    monkeypatch.setattr(reserve, "observe_ollama", unavailable)
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "unknown_model_observation" and result["retryable"]
    assert "private" not in json.dumps(result)


def test_impossible_budget_is_terminal_not_endless_polling(resources, monkeypatch):
    _, backend = resources
    monkeypatch.setattr(reserve.psutil, "virtual_memory", lambda: SimpleNamespace(total=2 * GIB, available=GIB))
    result = asyncio.run(reserve.probe(backend, MODEL))
    assert result["state"] == "budget_exceeds_host" and not result["retryable"]
    with pytest.raises(reserve.LocalReserveError, match="budget_exceeds_host"):
        reserve.require_retryable(result)


def test_actual_remote_alias_is_external_without_model_budget(resources, monkeypatch):
    _, backend = resources
    async def remote(*_): return {"external": True}
    monkeypatch.setattr(reserve, "observe_ollama", remote)
    result = asyncio.run(reserve.probe(backend, "remote-alias"))
    assert result["state"] == "external_target" and result["admitted"] and not result["enforced"]


@pytest.fixture
def native_http(monkeypatch):
    calls = []
    loaded = []
    tags = [{"name": MODEL, "digest": DIGEST, "size": 2 * GIB}]
    shown = {"details": {"format": "mlx"}, "model_info": {"general.parameter_count": 2_000_000}}
    def reply(request):
        calls.append((request.method, request.url.path))
        payload = {"/api/show": shown, "/api/tags": {"models": tags}, "/api/ps": {"models": loaded}}[request.url.path]
        return httpx.Response(200, json=payload)
    real = httpx.AsyncClient
    monkeypatch.setattr(reserve.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(reply), **kw))
    return calls, shown, tags, loaded


def test_native_probe_reads_only_show_tags_ps_and_exact_identity(native_http):
    calls, _, _, loaded = native_http
    # A different tag of the same family gives no residency credit.
    loaded.append({"name": "example:large", "digest": DIGEST, "context_length": 1024})
    observed = asyncio.run(reserve.observe_ollama(OllamaBackend(num_ctx=1024), MODEL))
    assert observed["resident_context"] is None
    assert calls == [("POST", "/api/show"), ("GET", "/api/tags"), ("GET", "/api/ps")]


def test_metadata_confirmed_remote_does_not_read_local_capacity(native_http):
    calls, shown, _, _ = native_http
    shown["remote_host"] = "https://provider.invalid"
    assert asyncio.run(reserve.observe_ollama(OllamaBackend(), MODEL)) == {"external": True}
    assert calls == [("POST", "/api/show")]


def test_malformed_remote_flag_is_unknown_not_external(native_http):
    _, shown, _, _ = native_http
    shown["remote_host"] = True
    with pytest.raises(TypeError, match="invalid remote"):
        asyncio.run(reserve.observe_ollama(OllamaBackend(), MODEL))


def test_catalog_ambiguity_is_rejected(native_http):
    _, _, tags, _ = native_http
    tags.append(deepcopy(tags[0]))
    with pytest.raises(ValueError, match="ambiguous catalog"):
        asyncio.run(reserve.observe_ollama(OllamaBackend(), MODEL))


def _receipt(state="ready", *, admitted=True, **fields):
    return {"state": state, "admitted": admitted, "retryable": not admitted,
            "wait_seconds": 2, "poll_seconds": 1, **fields}


def test_runtime_wait_retains_input_and_returns_torch_without_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend)
    context = [{"role": "tool", "content": "existing completed tool result"}]
    calls, probes = [], []
    async def fake_probe(*_):
        probes.append(True)
        return _receipt("waiting_disk_reserve", admitted=False) if len(probes) == 1 else _receipt()
    async def chat(messages, **_):
        calls.append(messages)
        assert not runtime.compute_turn_status().get("resource_waiters")
        return {"content": "result"}
    monkeypatch.setattr(reserve, "probe", fake_probe)
    monkeypatch.setattr(backend, "chat", chat)
    async def run():
        token = runtime._compute_turn_context.set(("worker", "background"))
        try:
            task = asyncio.create_task(runtime._chat_with_compute_turn(backend, context))
            for _ in range(100):
                if runtime.compute_turn_status().get("resource_waiters"): break
                await asyncio.sleep(.01)
            status = runtime.compute_turn_status()
            assert status["active"] is False and not calls
            assert status["resource_waiters"][0]["chat_id"] == "worker"
            assert await task == {"content": "result"}
        finally:
            runtime._compute_turn_context.reset(token)
    asyncio.run(run())
    assert len(calls) == 1 and calls[0] is context and len(probes) == 3
    assert not runtime.compute_turn_status().get("resource_waiters")


def test_cloud_target_bypasses_host_gate_even_on_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = OllamaBackend(default_model="glm:cloud")
    runtime = ChatRuntime(backend)
    async def forbidden(*_): pytest.fail("Cloud has no local reserve gate")
    async def chat(*_, **__):
        assert HostInferenceGate().status()["active"] is False
        return {"content": "external"}
    monkeypatch.setattr(reserve, "probe", forbidden)
    monkeypatch.setattr(backend, "chat", chat)
    assert asyncio.run(runtime._chat_with_compute_turn(backend, []))["content"] == "external"


def test_metadata_target_change_returns_owner_before_external_call(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend)
    states = iter([_receipt(), _receipt("external_target")])
    async def probe(*_): return next(states)
    async def chat(*_, **__):
        assert HostInferenceGate().status()["active"] is False
        return {"content": "external"}
    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(backend, "chat", chat)
    assert asyncio.run(runtime._chat_with_compute_turn(backend, []))["content"] == "external"


def test_cancellation_clears_waiter_without_backend_or_foreign_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend)
    async def probe(*_): return _receipt("waiting_memory_reserve", admitted=False)
    async def forbidden(*_, **__): pytest.fail("No inference while memory reserve is missing")
    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(backend, "chat", forbidden)
    async def run():
        pending = asyncio.create_task(runtime._chat_with_compute_turn(backend, []))
        for _ in range(100):
            if runtime.compute_turn_status().get("resource_waiters"): break
            await asyncio.sleep(.01)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        assert runtime.compute_turn_status()["active"] is False
        assert not runtime.compute_turn_status().get("resource_waiters")
    asyncio.run(run())


def test_timeout_does_not_replay_prior_tool_result(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend)
    async def probe(*_): return _receipt("waiting_memory_reserve", admitted=False, wait_seconds=1)
    async def forbidden(*_, **__): pytest.fail("No inference or tool replay on reserve timeout")
    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(backend, "chat", forbidden)
    with pytest.raises(reserve.LocalReserveError, match="reserve_wait_expired"):
        asyncio.run(runtime._chat_with_compute_turn(backend, [{"role": "tool", "content": "already done"}]))
    assert not runtime.compute_turn_status().get("resource_waiters")


def test_recheck_after_host_wait_can_deny_without_holding_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend)
    states = iter([_receipt(), _receipt("waiting_disk_reserve", admitted=False), _receipt(), _receipt()])
    async def probe(*_): return next(states)
    async def chat(*_, **__): return {"content": "done"}
    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(backend, "chat", chat)
    async def run():
        pending = asyncio.create_task(runtime._chat_with_compute_turn(backend, []))
        for _ in range(100):
            if runtime.compute_turn_status().get("resource_waiters"): break
            await asyncio.sleep(.01)
        assert runtime.compute_turn_status()["active"] is False
        assert (await pending)["content"] == "done"
    asyncio.run(run())


@pytest.mark.parametrize("recover", [True, False])
def test_process_wait_after_dispatched_tool_never_replays_it(tmp_path, monkeypatch, recover):
    from hub._services.chat import chat_runtime as runtime_module
    from hub._services.chat.chat_runtime import FailedAnswer
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    # Native verification puts TMPDIR below the isolated source checkout.
    # Authorize only this owned test directory as a worker write root; keep
    # the production live-tree guard active everywhere else.
    monkeypatch.setenv("BACH_WORKTREES_DIR", str(tmp_path))
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend)
    session = runtime.get_session("reserve-process")
    session.mode = "full"
    session.allow_tools = True
    session.max_tool_rounds = 4
    model_calls, tool_calls, probes = [], [], []
    target = tmp_path / "owned-tool-output.txt"
    async def probe(*_):
        probes.append(True)
        waiting = len(probes) == 3 or (not recover and len(probes) > 3)
        return _receipt("waiting_disk_reserve", admitted=False, wait_seconds=1) if waiting else _receipt()
    async def chat(messages, **_):
        model_calls.append(deepcopy(messages))
        if len(model_calls) == 1:
            call = {"id": "owned-call", "type": "function", "function": {
                "name": "write_file", "arguments": {"path": str(target), "content": "Ergebnis mit Umlauten: öäüß"}}}
            return {"content": "", "tool_calls": [call], "raw_message": {"role": "assistant", "tool_calls": [call]}}
        return {"content": "result", "raw_message": {"role": "assistant", "content": "result"}}
    real_execute = runtime_module.exec_tool
    def execute(name, arguments, *args, **kwargs):
        assert name == "write_file"
        tool_calls.append(deepcopy(arguments))
        return real_execute(name, arguments, *args, **kwargs)
    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(backend, "chat", chat)
    monkeypatch.setattr(runtime_module, "exec_tool", execute)
    result = asyncio.run(runtime.process("Arbeite mit dem Werkzeug.", "reserve-process", backend=backend, model=MODEL))
    assert len(tool_calls) == 1, (result, model_calls, len(probes), session.mode)
    assert target.read_text(encoding="utf-8") == "Ergebnis mit Umlauten: öäüß"
    assert len(model_calls) == (2 if recover else 1)
    assert FailedAnswer.looks_like(result) is (not recover)
    assert not runtime.compute_turn_status().get("resource_waiters")


@pytest.mark.parametrize("reason", ["manual_pause", "lease_lost", "policy_downgrade"])
def test_waiting_obeys_existing_binding_guard_promptly(tmp_path, monkeypatch, reason):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = OllamaBackend(default_model=MODEL)
    runtime = ChatRuntime(backend)
    session = runtime.get_session("bound-worker")
    session.worker_slot_reader = dict
    revoked = []
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_: reason if revoked else None)
    async def probe(*_): return _receipt("waiting_memory_reserve", admitted=False)
    async def forbidden(*_, **__): pytest.fail("No inference after native binding revocation")
    monkeypatch.setattr(reserve, "probe", probe)
    monkeypatch.setattr(backend, "chat", forbidden)
    async def run():
        token = runtime._compute_turn_context.set(("bound-worker", "background"))
        try:
            pending = asyncio.create_task(runtime._chat_with_compute_turn(backend, []))
            for _ in range(100):
                if runtime.compute_turn_status().get("resource_waiters"): break
                await asyncio.sleep(.01)
            revoked.append(True)
            with pytest.raises(RuntimeError, match=reason):
                await asyncio.wait_for(pending, .5)
            assert not runtime.compute_turn_status().get("resource_waiters")
            assert runtime.compute_turn_status()["active"] is False
        finally:
            runtime._compute_turn_context.reset(token)
    asyncio.run(run())


@pytest.mark.parametrize("change", ["remove", "disable", "budget"])
def test_actual_reserve_policy_change_aborts_waiting_call(resources, tmp_path, monkeypatch, change):
    path, backend = resources
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    runtime = ChatRuntime(backend)
    monkeypatch.setattr(reserve.psutil, "virtual_memory", lambda: SimpleNamespace(total=32 * GIB, available=3 * GIB))
    async def forbidden(*_, **__): pytest.fail("No inference under a changed reserve policy")
    monkeypatch.setattr(backend, "chat", forbidden)
    async def run():
        pending = asyncio.create_task(runtime._chat_with_compute_turn(backend, []))
        for _ in range(100):
            if runtime.compute_turn_status().get("resource_waiters"): break
            await asyncio.sleep(.01)
        assert runtime.compute_turn_status()["resource_waiters"]
        if change == "remove":
            path.unlink()
        else:
            raw = policy()
            if change == "disable": raw["enabled"] = False
            else: raw["models"][MODEL]["weight_budget_bytes"] += GIB
            path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(reserve.LocalReserveError, match="resource_policy_changed"):
            await pending
        assert runtime.compute_turn_status()["active"] is False
        assert not runtime.compute_turn_status().get("resource_waiters")
    asyncio.run(run())


def test_policy_change_between_preflight_and_host_recheck_aborts(resources, tmp_path, monkeypatch):
    path, backend = resources
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    runtime = ChatRuntime(backend)
    real_probe = reserve.probe
    probes = []
    async def change_after_first(*args):
        result = await real_probe(*args)
        probes.append(True)
        if len(probes) == 1:
            raw = policy(); raw["enabled"] = False
            path.write_text(json.dumps(raw), encoding="utf-8")
        return result
    async def forbidden(*_, **__): pytest.fail("No inference under the new policy in an old turn")
    monkeypatch.setattr(reserve, "probe", change_after_first)
    monkeypatch.setattr(backend, "chat", forbidden)
    with pytest.raises(reserve.LocalReserveError, match="resource_policy_changed"):
        asyncio.run(runtime._chat_with_compute_turn(backend, []))
    assert runtime.compute_turn_status()["active"] is False and len(probes) == 1


@pytest.mark.parametrize("change", ["remove", "disable", "budget"])
def test_policy_change_during_metadata_recheck_aborts(resources, tmp_path, monkeypatch, change):
    path, backend = resources
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    runtime = ChatRuntime(backend)
    observations = []
    async def observed(*_):
        observations.append(True)
        if len(observations) == 2:
            if change == "remove":
                path.unlink()
            else:
                raw = policy()
                if change == "disable": raw["enabled"] = False
                else: raw["models"][MODEL]["kv_headroom_bytes"] += GIB
                path.write_text(json.dumps(raw), encoding="utf-8")
        return {"external": False, "digest": DIGEST, "weight_floor_bytes": 2 * GIB,
                "resident_context": None}
    async def forbidden(*_, **__): pytest.fail("Metadata receipt cannot authorize a changed policy")
    monkeypatch.setattr(reserve, "observe_ollama", observed)
    monkeypatch.setattr(backend, "chat", forbidden)
    with pytest.raises(reserve.LocalReserveError, match="resource_policy_changed"):
        asyncio.run(runtime._chat_with_compute_turn(backend, []))
    assert len(observations) == 2 and runtime.compute_turn_status()["active"] is False


def test_policy_change_during_internal_gate_wait_aborts(resources, tmp_path, monkeypatch):
    path, backend = resources
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    runtime = ChatRuntime(backend)
    original_enter = runtime._enter_compute_turn
    async def change_while_entering(*args, **kwargs):
        await original_enter(*args, **kwargs)
        raw = policy(); raw["enabled"] = False
        path.write_text(json.dumps(raw), encoding="utf-8")
    async def forbidden(*_, **__): pytest.fail("An internal gate wait cannot authorize a changed policy")
    monkeypatch.setattr(runtime, "_enter_compute_turn", change_while_entering)
    monkeypatch.setattr(backend, "chat", forbidden)
    with pytest.raises(reserve.LocalReserveError, match="resource_policy_changed"):
        asyncio.run(runtime._chat_with_compute_turn(backend, []))
    assert runtime._compute_turn_gate.active is False
    assert runtime.compute_turn_status()["active"] is False
