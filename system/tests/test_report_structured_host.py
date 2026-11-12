"""4119: synthetic native dispatcher/HTTP/lifetime checks; no model calls."""
import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.document.report_provider_adapter import ReportHostPortError
from hub._services.llm.model_backend import OllamaBackend
from system.tests.test_report_provider import _local_report_runtime

DIGEST = "a" * 64
REAL_UNLOAD = OllamaBackend.unload


def request(model, ctx=4096):
    return {"model": model, "prompt": "Synthetische Beobachtung: übt gemeinsam.",
            "stream": False, "format": {"type": "object", "properties": {
                "text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
            "options": {"temperature": 0, "num_ctx": ctx, "num_predict": ctx // 2},
            "truncate": False, "shift": False, "keep_alive": "0s"}


def completion(model):
    return {"model": model, "response": ' {"text":"Übung"} \n', "done": True,
            "done_reason": "stop", "prompt_eval_count": 111, "eval_count": 12,
            "total_duration": 123456}


def fixture(tmp_path, monkeypatch, *, reply=None, release=None, metadata=None):
    from hub._services.chat import local_resource_reserve as reserve
    local, runtime, backend, legacy, probes, states = _local_report_runtime(tmp_path, monkeypatch)
    policy = {"enabled": True, "models": {backend.default_model: {
        "num_ctx": backend.num_ctx, "digest": DIGEST}}}
    monkeypatch.setattr(reserve, "read_policy", lambda: (policy, "c" * 64))
    calls, owned, started = [], [], asyncio.Event()
    original_client = httpx.AsyncClient

    async def handler(req):
        calls.append(req.url.path)
        model = backend.default_model
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": (metadata or {}).get("version", "0.33.3")})
        if req.url.path == "/api/show":
            return httpx.Response(200, json={"details": {"format": "gguf"},
                                           "model_info": {"general.parameter_count": 123}})
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model, "size": 1000,
                "digest": (metadata or {}).get("digest", DIGEST)}]})
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        assert req.url.path == "/api/generate"
        owner = HostInferenceGate().status()
        assert owner["active"] and owner["dispatch_pending"]
        assert runtime._compute_turn_gate.active
        assert owner["chat_id"] == runtime._compute_turn_gate.chat_id
        assert owner["priority"] == runtime._compute_turn_gate.priority == "background"
        owned.append(json.loads(req.content))
        started.set()
        if release is not None:
            await release.wait()
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, bytes):
            return httpx.Response(200, content=reply)
        if type(reply) is int:
            return httpx.Response(reply, json={"error": "synthetic failure"})
        return httpx.Response(200, json=reply if reply is not None else completion(model))

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return SimpleNamespace(local=local, runtime=runtime, backend=backend, legacy=legacy,
        probes=probes, calls=calls, owned=owned, started=started, policy=policy)


async def invoke(f):
    pin = await f.local.pin_route("run-structured", expected_mode="local", request_mode="local",
                                 allow_fallback=False, local_only=True)
    result = await f.local.generate_structured(request(f.backend.default_model), run_id="run-structured",
        request_mode="local", route_id=pin["route_id"], route_ref=pin["route_ref"],
        expected_model_digest=DIGEST, required_server_version="0.33.3")
    return pin, result


@pytest.mark.asyncio
async def test_native_structured_exact_request_raw_completion_receipt(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    pin, result = await invoke(f)
    payload = request(f.backend.default_model)
    assert f.owned == [payload] and not f.legacy and len(f.probes) == 3
    assert result == {"contract": "bach.report-structured-local.v1", "run_id": "run-structured",
        "request_mode": "local", "mode": "local", "route_id": pin["route_id"],
        "route_ref": pin["route_ref"], "request_sha256": hashlib.sha256(json.dumps(payload,
            sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
        "server_version": "0.33.3", "target": pin["target"],
        "completion": completion(f.backend.default_model)}
    assert result["completion"]["response"].endswith(" \n")
    assert not HostInferenceGate().status()["active"] and not f.runtime.sessions
    assert not f.runtime._compute_turn_gate.active
    with pytest.raises(ReportHostPortError):
        await f.local.generate_structured(payload, run_id="run-structured", request_mode="local",
            route_id=pin["route_id"], route_ref=pin["route_ref"], expected_model_digest=DIGEST,
            required_server_version="0.33.3")
    assert len(f.owned) == 1


@pytest.mark.parametrize("change", [
    {"stream": True}, {"truncate": True}, {"shift": True}, {"keep_alive": "5m"},
    {"url": "http://foreign.invalid"}, {"model": "wrong:model"},
    {"options": {"temperature": 0, "num_ctx": 8192, "num_predict": 100}},
    {"options": {"temperature": False, "num_ctx": 4096, "num_predict": 100}},
    {"options": {"temperature": 0, "num_ctx": 4096, "num_predict": True}},
])
def test_closed_structured_request(change):
    with pytest.raises(ValueError):
        OllamaBackend.structured_request({**request("fixture:model"), **change}, model="fixture:model", num_ctx=4096)


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{"version": "0.33.2"}, {"digest": "b" * 64}])
async def test_changed_version_or_digest_never_dispatches(tmp_path, monkeypatch, metadata):
    f = fixture(tmp_path, monkeypatch, metadata=metadata)
    with pytest.raises(ReportHostPortError):
        await invoke(f)
    assert not f.owned and not f.legacy and not HostInferenceGate().status()["active"]


@pytest.mark.asyncio
async def test_cancel_repeatedly_drains_real_http_with_both_owners(tmp_path, monkeypatch):
    release = asyncio.Event()
    f = fixture(tmp_path, monkeypatch, release=release)
    task = asyncio.create_task(invoke(f))
    await asyncio.wait_for(f.started.wait(), 5)
    task.cancel()
    await asyncio.sleep(.02)
    task.cancel()
    await asyncio.sleep(.02)
    assert not task.done() and f.runtime._compute_turn_gate.active
    assert HostInferenceGate().status()["dispatch_pending"]
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(f.owned) == 1 and not HostInferenceGate().status()["active"]
    assert not f.runtime._compute_turn_gate.active and not f.runtime.sessions


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    httpx.ReadTimeout("synthetic timeout"), 500, b'{"done":true,"done":false}',
    b'{"done":NaN}', b'{} {}', {"done": False},
    {"done": True, "done_reason": "stop", "response": "{}", "model": "report-local-fixture:small",
     "prompt_eval_count": True, "eval_count": 1},
])
async def test_unknown_backend_end_persists_and_blocks_all_admission(tmp_path, monkeypatch, reply):
    f = fixture(tmp_path, monkeypatch, reply=reply)
    with pytest.raises(ReportHostPortError):
        await invoke(f)
    gate = HostInferenceGate()
    before = (gate.root / "owner.json").read_bytes()
    assert gate.status()["active"] and gate.status()["dispatch_pending"]
    assert b"Synthetische" not in before and b"response" not in before
    for priority in ("foreground", "background"):
        with pytest.raises(RuntimeError, match="ungeklärt"):
            async with HostInferenceGate().turn("next", priority):
                pytest.fail("admission despite unresolved dispatch")
        assert (gate.root / "owner.json").read_bytes() == before


def test_process_loss_owner_persists_across_fresh_processes(tmp_path):
    root = tmp_path / "gate"
    system = str(Path(__file__).resolve().parents[1])
    script = '''import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hub._services.chat.host_inference_gate import HostInferenceGate
async def main():
 async with HostInferenceGate(Path(sys.argv[2])).turn('crash', 'background', model_target={
  'socket_id':'s','binding_id':'b','agent_id':'a','backend':'ollama','model':'fake:model'}):
  HostInferenceGate.current_owner().begin_dispatch('a'*64, {
   'socket_id':'s','binding_id':'b','agent_id':'a','backend':'ollama','model':'fake:model'})
  os._exit(0)
asyncio.run(main())
'''
    child = subprocess.run([sys.executable, "-B", "-c", script, system, str(root)], timeout=10)
    assert child.returncode == 0
    gate = HostInferenceGate(root)
    before = (root / "owner.json").read_bytes()
    assert not gate._alive(json.loads(before)) and gate.status()["active"]
    async def retry():
        with pytest.raises(RuntimeError, match="ungeklärt"):
            async with HostInferenceGate(root).turn("restart", "foreground"):
                pytest.fail("crashed dispatch was cleared")
    asyncio.run(retry())
    assert (root / "owner.json").read_bytes() == before


def test_unload_guard_rejects_unknown_owner_before_http(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "tools/maintenance/memory_pressure_unload_guard.py"
    spec = importlib.util.spec_from_file_location("synthetic_unload_guard", path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    root = tmp_path / "local-inference"
    root.mkdir()
    (root / "inference.lock").write_bytes(b"")
    monkeypatch.setattr(guard, "canonical_inference_root", lambda: root)
    calls = []
    monkeypatch.setattr(guard, "check_conditions", lambda args: calls.append("conditions"))
    monkeypatch.setattr(guard, "api_request", lambda *a, **k: pytest.fail("HTTP after unresolved owner"))
    for data in [b'{"pid":99999999,"created":1,"dispatch_pending":{"id":"known"}}',
                 b'{"pid":99999999,"created":1,"dispatch_pending":null}',
                 b'{"pid":1,"pid":2}', b'{}', b'not json']:
        (root / "owner.json").write_bytes(data)
        with pytest.raises(guard.Denied):
            guard.unload(SimpleNamespace(inference_root=root))
    assert not calls


@pytest.mark.asyncio
async def test_route_pin_and_context_policy_fail_before_network(tmp_path, monkeypatch):
    f = fixture(tmp_path, monkeypatch)
    pin = await f.local.pin_route("run-policy", expected_mode="local", request_mode="local",
                                 allow_fallback=False, local_only=True)
    arguments = dict(run_id="run-policy", request_mode="local", route_id=pin["route_id"],
                     route_ref="wrong-ref", expected_model_digest=DIGEST, required_server_version="0.33.3")
    with pytest.raises(ReportHostPortError):
        await f.local.generate_structured(request(f.backend.default_model), **arguments)
    arguments["route_ref"] = pin["route_ref"]
    f.policy["models"][f.backend.default_model]["num_ctx"] = 8192
    with pytest.raises(ReportHostPortError):
        await f.local.generate_structured(request(f.backend.default_model), **arguments)
    assert not f.calls and not f.owned and not f.legacy


@pytest.mark.asyncio
async def test_policy_change_during_metadata_rejects_dispatch(tmp_path, monkeypatch):
    from hub._services.chat import local_resource_reserve as reserve
    f = fixture(tmp_path, monkeypatch)
    original = f.backend.structured_metadata
    async def changed(model):
        result = await original(model)
        monkeypatch.setattr(reserve, "read_policy", lambda: (f.policy, "d" * 64))
        return result
    monkeypatch.setattr(f.backend, "structured_metadata", changed)
    with pytest.raises(ReportHostPortError):
        await invoke(f)
    assert not f.owned and not HostInferenceGate().status()["active"]


@pytest.mark.asyncio
async def test_backend_cannot_infer_without_native_owner(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("HTTP without native authority"))
    backend = OllamaBackend(default_model="fixture:model")
    with pytest.raises(RuntimeError, match="autorität"):
        await backend.generate_structured(request("fixture:model"), target={"model": "fixture:model"})


@pytest.mark.asyncio
async def test_dispatch_terminal_handle_belongs_to_held_owner(tmp_path):
    gate = HostInferenceGate(tmp_path / "gate")
    target = dict(socket_id="s", binding_id="b", agent_id="a", backend="ollama", model="fake:model")
    async with gate.turn("owned", "background", model_target=target):
        handle = gate.begin_dispatch("a" * 64, target)
        before = (gate.root / "owner.json").read_bytes()
        with pytest.raises(RuntimeError, match="anderem Dispatch"):
            gate.finish_dispatch(object())
        assert (gate.root / "owner.json").read_bytes() == before
        gate.finish_dispatch(handle)
        assert not gate.status()["dispatch_pending"]
    assert not gate.status()["active"]


def test_direct_unload_retains_dead_owner_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    gate = HostInferenceGate();gate.root.mkdir()
    pending = {"pid": 99999999, "created": 1, "chat_id": "lost", "priority": "background",
               "started_at": 1, "dispatch_pending": {"id": "known"}}
    gate._write(gate.root / "owner.json", pending)
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("unload after unresolved dispatch"))
    assert REAL_UNLOAD(OllamaBackend(default_model="fixture:model")) is False
    assert gate._read(gate.root / "owner.json") == pending


@pytest.mark.asyncio
async def test_reused_gate_waiter_cannot_mutate_or_inherit_dispatch_owner(tmp_path):
    gate = HostInferenceGate(tmp_path / "gate")
    target = dict(socket_id="s", binding_id="b", agent_id="a", backend="ollama", model="fake:model")
    async with gate.turn("owner", "background", model_target=target):
        handle = gate.begin_dispatch("a" * 64, target)
        original = (gate.root / "owner.json").read_bytes()
        async def waiter():
            with pytest.raises(RuntimeError, match="Ownerbindung"):
                HostInferenceGate.current_owner()
            async with gate.turn("waiter", "foreground"):
                pytest.fail("waiter acquired active dispatch")
        pending = asyncio.create_task(waiter())
        for _ in range(100):
            if gate.status()["foreground_waiters"] == 1:
                break
            await asyncio.sleep(.01)
        assert gate.status()["foreground_waiters"] == 1
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert (gate.root / "owner.json").read_bytes() == original
        gate.finish_dispatch(handle)
    assert not gate.status()["active"]
