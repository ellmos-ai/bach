# SPDX-License-Identifier: MIT
"""Isolated supervised foreground loads; never contact real Ollama or chat data."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.test_local_resource_reserve import resources, MODEL, DIGEST, GIB, policy
from hub._services.chat import buddha_cold_start as cold, local_resource_reserve as reserve
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.host_inference_gate import HostInferenceGate, _OWNED_TURN


@pytest.fixture
def foreground(resources, monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "send",
                        AsyncMock(side_effect=AssertionError("unexpected test network request")))
    monkeypatch.setattr(httpx.Client, "send",
                        lambda *_a, **_kw: pytest.fail("unexpected test network request"))
    monkeypatch.setattr(cold, "unload_exact_model", AsyncMock(return_value=True))
    path, backend = resources
    raw = policy()
    raw["cold_start"] = {
        "enabled": True, "min_available_bytes": GIB,
        "max_load_seconds": 5, "max_pressure_level": 2,
        "max_swap_growth_bytes": GIB,
    }
    path.write_text(json.dumps(raw))
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "isolated-runtime"))
    monkeypatch.setattr(reserve.psutil, "virtual_memory",
                        lambda: SimpleNamespace(total=32 * GIB, available=3 * GIB))
    from hub import compute_lock
    from hub._services.chat import host_resource_observation, model_sockets
    monkeypatch.setattr(compute_lock, "get_fackel_preference", lambda **_kw: "ollama")
    monkeypatch.setattr(model_sockets, "model_binding_for_call", lambda *_a, **_kw: None)
    sample = {"memory_available_bytes": 3 * GIB, "pressure_level": 1,
              "swap_used_bytes": 0, "compressor_physical_bytes": 0}
    monkeypatch.setattr(host_resource_observation, "observe_host_resources", lambda _memory: dict(sample))
    monkeypatch.setattr(cold, "sample_host", AsyncMock(side_effect=lambda: dict(sample)))
    monkeypatch.setattr(cold, "_COOLDOWN", {"until": 0.0})
    monkeypatch.setattr(cold, "record_observation", lambda *_a: {"synthetic": True})
    monkeypatch.setattr(cold, "resident_footprint", AsyncMock(return_value=None))
    runtime = ChatRuntime(backend)
    slot = {"id": "buddha_chat", "backend": "ollama", "model": MODEL, "enabled": True}
    resident = {"value": False}
    async def observed(*_args):
        return {"external": False, "digest": DIGEST, "weight_floor_bytes": 2 * GIB,
                "resident_context": 1024 if resident["value"] else None}
    monkeypatch.setattr(reserve, "observe_ollama", observed)
    calls = []
    async def load(messages, **kwargs):
        # Native dispatch must run in the exact asyncio task owning the host.
        _OWNED_TURN.get().gate._check_owned_record()
        calls.append((messages, kwargs))
        resident["value"] = True
        return {"content": "", "done_reason": "load"}
    monkeypatch.setattr(backend, "chat", load)
    return runtime, backend, slot, resident, calls, path


def test_readonly_cold_eligibility_does_not_create_session_or_load(foreground):
    runtime, backend, slot, resident, calls, _ = foreground
    receipt = asyncio.run(runtime.probe_chat_cold_start(
        backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)))
    assert receipt["admitted"] is True
    assert receipt["capacity_basis"] == "cold_start_monitored"
    assert runtime.sessions == {} and calls == [] and not resident["value"]


@pytest.mark.parametrize("blocked", ["disabled", "cooldown", "binding"])
def test_cold_eligibility_keeps_native_denials(foreground, blocked):
    runtime, backend, slot, resident, calls, path = foreground
    if blocked == "disabled":
        raw = json.loads(path.read_text())
        raw["cold_start"]["enabled"] = False
        path.write_text(json.dumps(raw))
    elif blocked == "cooldown":
        cold._COOLDOWN["until"] = time.monotonic() + 300
    else:
        slot["model"] = "different:model"
    receipt = asyncio.run(runtime.probe_chat_cold_start(
        backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)))
    assert receipt.get("admitted") is not True
    assert calls == [] and runtime.sessions == {}


def test_chat_load_resets_privilege_and_rechecks_normal_admission(foreground):
    runtime, backend, slot, resident, calls, _ = foreground
    result = asyncio.run(runtime.warm_chat_ollama_model(
        backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)))
    assert result["state"] == "loaded"
    assert calls[0][0] == [] and calls[0][1]["think"] is False
    assert runtime.history("gui-web") == []
    assert runtime._model_warmup_context.get() is None
    assert not getattr(runtime.sessions["gui-web"], "_buddha_cold_start", False)
    resident["value"] = False
    receipt, _ = asyncio.run(runtime.prepare_inference_call(backend, MODEL, chat_id="gui-web"))
    assert receipt["admitted"] is False and receipt["state"] == "waiting_memory_reserve"


def test_warmup_revalidates_binding_after_load_without_accepting_prompt(foreground):
    runtime, backend, slot, resident, calls, _ = foreground
    async def changed(messages, **kwargs):
        _OWNED_TURN.get().gate._check_owned_record()
        slot["model"] = "different:model"
        resident["value"] = True
        return {"content": "", "done_reason": "load"}
    backend.chat = changed
    result = asyncio.run(runtime.warm_chat_ollama_model(
        backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)))
    assert result["state"] == "slot_changed"
    assert runtime.history("gui-web") == []


def test_concurrent_warmup_cannot_share_coldstart_capability(foreground):
    runtime, backend, slot, resident, calls, _ = foreground
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def load(messages, **kwargs):
            _OWNED_TURN.get().gate._check_owned_record()
            entered.set()
            await release.wait()
            resident["value"] = True
            return {"content": "", "done_reason": "load"}
        backend.chat = load
        first = asyncio.create_task(runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)))
        await asyncio.wait_for(entered.wait(), 2)
        receipt, _ = await runtime.prepare_inference_call(backend, MODEL, chat_id="another")
        assert receipt["admitted"] is False
        second = await runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="another", slot_reader=lambda: dict(slot))
        assert second["state"] == "warmup_busy"
        release.set()
        assert (await first)["state"] == "loaded"
    asyncio.run(scenario())


def test_monitor_abort_cleanup_finishes_before_competing_host_owner(foreground, monkeypatch):
    runtime, backend, slot, resident, calls, _ = foreground
    async def scenario():
        final_sample, release_sample = asyncio.Event(), asyncio.Event()
        order = []
        async def sample():
            final_sample.set()
            await release_sample.wait()
            return {"memory_available_bytes": 0, "pressure_level": 1, "swap_used_bytes": 0}
        monkeypatch.setattr(cold, "sample_host", sample)
        async def unload(*_args, **_kwargs):
            assert HostInferenceGate().status()["chat_id"] == "gui-web"
            order.append("cleanup")
            resident["value"] = False
            return True
        monkeypatch.setattr(cold, "unload_exact_model", unload)
        first = asyncio.create_task(runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)))
        await asyncio.wait_for(final_sample.wait(), 2)
        async def competitor():
            async with HostInferenceGate().turn("other-channel", "foreground"):
                order.append("other")
        other = asyncio.create_task(competitor())
        await asyncio.sleep(0.05)
        assert order == []
        release_sample.set()
        result = await first
        await other
        assert result["state"] == "cold_start_aborted"
        assert result["cleanup_verified"] is True
        assert order == ["cleanup", "other"]
        assert runtime.history("gui-web") == []
    asyncio.run(scenario())



def test_monitor_interrupts_running_backend_without_leaking_cancellation(foreground, monkeypatch):
    runtime, backend, slot, resident, calls, _ = foreground
    async def scenario():
        cancelled = []
        async def load(*_a, **_kw):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
        backend.chat = load
        monkeypatch.setattr(cold, "sample_host", AsyncMock(return_value={
            "memory_available_bytes": 0, "pressure_level": 1, "swap_used_bytes": 0}))
        result = await asyncio.wait_for(runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)), timeout=3)
        assert result["state"] == "cold_start_aborted"
        assert result["cleanup_verified"] is True and cancelled == [True]
        assert asyncio.current_task().cancelling() == 0
        assert not HostInferenceGate().status()["active"]
    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["dispatch", "cleanup"])
def test_external_cancellation_waits_for_cleanup_and_propagates(foreground, monkeypatch, phase):
    runtime, backend, slot, resident, calls, _ = foreground
    async def scenario():
        entered, cleanup_entered, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
        if phase == "dispatch":
            async def load(*_a, **_kw):
                entered.set()
                await asyncio.Event().wait()
            backend.chat = load
        else:
            monkeypatch.setattr(cold, "sample_host", AsyncMock(return_value={
                "memory_available_bytes": 0, "pressure_level": 1, "swap_used_bytes": 0}))
        async def cleanup(*_a, **_kw):
            assert HostInferenceGate().status()["chat_id"] == "gui-web"
            cleanup_entered.set()
            await release_cleanup.wait()
            return True
        monkeypatch.setattr(cold, "unload_exact_model", cleanup)
        task = asyncio.create_task(runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot)))
        if phase == "dispatch":
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
        await asyncio.wait_for(cleanup_entered.wait(), 2)
        if phase == "cleanup":
            task.cancel()
        await asyncio.sleep(0.03)
        assert not task.done(), "owner must await cleanup despite cancellation"
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not HostInferenceGate().status()["active"]
        assert not (HostInferenceGate().root / "unload-pending.json").exists()
        assert runtime._model_warmup_context.get() is None
    asyncio.run(scenario())


def test_unverified_cleanup_leaves_durable_host_hold(foreground, monkeypatch):
    runtime, backend, slot, resident, calls, _ = foreground
    monkeypatch.setattr(cold, "sample_host", AsyncMock(return_value={
        "memory_available_bytes": 0, "pressure_level": 1, "swap_used_bytes": 0}))
    monkeypatch.setattr(cold, "unload_exact_model", AsyncMock(return_value=False))
    async def scenario():
        result = await runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot))
        assert result["state"] == "cold_start_aborted" and result["cleanup_verified"] is False
        assert (HostInferenceGate().root / "unload-pending.json").exists()
        with pytest.raises(RuntimeError, match="Unload"):
            async with HostInferenceGate().turn("other", "foreground"):
                pytest.fail("unverified cleanup must retain the host barrier")
    asyncio.run(scenario())


def test_child_task_cannot_inherit_warmup_admission(foreground):
    runtime, backend, slot, resident, calls, _ = foreground
    async def scenario():
        async def load(*_a, **_kw):
            async def unrelated():
                receipt, _ = await runtime.prepare_inference_call(
                    backend, MODEL, chat_id="gui-web")
                assert receipt["admitted"] is False
                assert receipt.get("cold_start") is None
            await asyncio.create_task(unrelated())
            resident["value"] = True
            return {"content": "", "done_reason": "load"}
        backend.chat = load
        result = await runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot))
        assert result["state"] == "loaded"
    asyncio.run(scenario())



def test_queue_time_reduces_foreground_load_budget(foreground, monkeypatch):
    runtime, backend, slot, resident, calls, _ = foreground
    async def scenario():
        holding, release = asyncio.Event(), asyncio.Event()
        async def holder():
            async with HostInferenceGate().turn("blocking", "foreground"):
                holding.set()
                await release.wait()
        blocker = asyncio.create_task(holder())
        await holding.wait()
        seen = []
        original_monitor = cold.monitor_load
        async def monitor(load, gate, **kwargs):
            seen.append(gate["max_load_seconds"])
            return await original_monitor(load, gate, **kwargs)
        monkeypatch.setattr(cold, "monitor_load", monitor)
        async def load(*_a, **_kw):
            await asyncio.Event().wait()
        backend.chat = load
        task = asyncio.create_task(runtime.warm_chat_ollama_model(
            backend, MODEL, chat_id="gui-web", slot_reader=lambda: dict(slot),
            deadline=time.monotonic() + 0.25))
        await asyncio.sleep(0.12)
        release.set()
        await blocker
        result = await task
        assert result["state"] == "warmup_timeout"
        assert seen and 0 < seen[0] < 0.16
        assert result["cleanup_verified"] is True
    asyncio.run(scenario())
