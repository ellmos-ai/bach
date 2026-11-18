# SPDX-License-Identifier: MIT
"""Only owned fake API responses and a temporary native inference lock."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.chat.resource_model_port import (
    GuardedModelPort,
    ModelReturnUnconfirmed,
)


@pytest.fixture
def port(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    spec = SimpleNamespace(model="reviewed:1", digest="a" * 64, port=11434)
    state = {"version": "0.33.3", "resident": True, "ack": True, "complete": True,
             "digest": spec.digest, "calls": []}
    foreign = {"name": "foreign:1", "digest": "b" * 64, "size": 11}
    def api(target, path, payload):
        assert target is spec
        state["calls"].append(path)
        record = {"name": spec.model, "digest": state["digest"], "size": 21}
        if path == "/api/version":
            return {"version": state["version"]}
        if path == "/api/tags":
            return {"models": [record, foreign]}
        if path == "/api/ps":
            return {"models": [record, foreign] if state["resident"] else [foreign]}
        assert path == "/api/generate"
        assert payload == {"model": spec.model, "keep_alive": 0, "stream": False}
        root = tmp_path / "runtime" / "local-inference"
        assert (root / "owner.json").is_file() and (root / "unload-pending.json").is_file()
        if state["complete"]:
            state["resident"] = False
        return {"done": state["ack"], "done_reason": "unload"}
    return GuardedModelPort(transport=api, timeout_seconds=.15), spec, state, tmp_path / "runtime" / "local-inference"


def test_exact_model_return_holds_native_gate_and_durable_intent(port):
    adapter, spec, state, root = port
    checks = []
    adapter.unload(spec, lambda: checks.append(True))
    assert len(checks) >= 4 and state["calls"].count("/api/generate") == 1
    assert not (root / "unload-pending.json").exists()
    assert not (root / "owner.json").exists()
    assert adapter.resident_bytes(spec) == 0


@pytest.mark.parametrize("key,value", [("version", "0.33.4"), ("digest", "c" * 64)])
def test_version_or_exact_identity_mismatch_never_posts(port, key, value):
    adapter, spec, state, root = port
    state[key] = value
    with pytest.raises(ModelReturnUnconfirmed):
        adapter.unload(spec, lambda: None)
    assert "/api/generate" not in state["calls"]
    assert not (root / "unload-pending.json").exists()


@pytest.mark.parametrize("key", ["ack", "complete"])
def test_unconfirmed_post_retains_intent_and_refuses_automatic_retry(port, key):
    adapter, spec, state, root = port
    state[key] = False
    with pytest.raises(ModelReturnUnconfirmed):
        adapter.unload(spec, lambda: None)
    assert (root / "unload-pending.json").is_file()
    assert state["calls"].count("/api/generate") == 1
    with pytest.raises(ModelReturnUnconfirmed):
        adapter.unload(spec, lambda: None)
    assert state["calls"].count("/api/generate") == 1


def test_active_native_turn_blocks_return_before_any_api_call(port):
    adapter, spec, state, root = port
    async def scenario():
        async with HostInferenceGate().turn("fake-live", "foreground"):
            with pytest.raises(ModelReturnUnconfirmed):
                await asyncio.to_thread(adapter.unload, spec, lambda: None)
    asyncio.run(scenario())
    assert state["calls"] == [] and not (root / "unload-pending.json").exists()


def test_lost_grant_stops_before_post(port):
    adapter, spec, state, _root = port
    def lost():
        raise RuntimeError("lost fixture grant")
    with pytest.raises(ModelReturnUnconfirmed):
        adapter.unload(spec, lost)
    assert state["calls"] == []


def test_unloaded_catalog_alias_is_allowed_but_resident_alias_is_not(port):
    adapter, spec, state, _root = port
    original = adapter.transport
    alias = {"name": "stored-alias:1", "digest": spec.digest, "size": 21}
    def api(spec, path, payload):
        value = original(spec, path, payload)
        if path == "/api/tags":
            value["models"].append(alias)
        return value
    adapter.transport = api
    adapter.verify_available(spec)
    adapter.transport = lambda spec, path, payload: {"models": [alias]} if path == "/api/ps" else api(spec, path, payload)
    with pytest.raises(ModelReturnUnconfirmed):
        adapter.unload(spec, lambda: None)
    assert "/api/generate" not in state["calls"]


@pytest.mark.parametrize("snapshot", [{}, {"models": None}, {"models": [{"name": "x"}]}])
def test_unknown_residency_is_never_zero(port, snapshot):
    adapter, spec, _state, _root = port
    original = adapter.transport
    adapter.transport = lambda spec, path, payload: snapshot if path == "/api/ps" else original(spec, path, payload)
    with pytest.raises(ModelReturnUnconfirmed):
        adapter.resident_bytes(spec)
