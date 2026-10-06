# SPDX-License-Identifier: MIT
"""Isolated host coordination checks; fake backends never make model calls."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parents[1]


def _until(predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Owned fake worker did not reach checkpoint")


def test_cross_process_runtime_yields_to_foreground_between_model_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    script = tmp_path / "fake_inference.py"
    script.write_text('''
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.llm.model_backend import OllamaBackend
root=Path(sys.argv[2]); role=sys.argv[3]
runtime=ChatRuntime(OllamaBackend(base_url="http://127.0.0.1:11434"))
count=0
async def fake_chat(*a, **kw):
 global count
 count+=1
 with (root/"trace.jsonl").open("a",encoding="utf-8") as f:
  f.write(json.dumps([role,count])+"\\n")
 if role=="background" and count==1:
  (root/"started").touch()
  while not (root/"release").exists(): await asyncio.sleep(.01)
 return {"content":"fake response"}
runtime.backend.chat=fake_chat
async def run():
 token=runtime._compute_turn_context.set((role,role))
 try:
  (root/(role+"-requested")).touch()
  for i in range(2 if role=="background" else 1):
   await runtime._chat_with_compute_turn(runtime.backend, [])
 finally: runtime._compute_turn_context.reset(token)
asyncio.run(run())
''', encoding="utf-8")
    children = []
    try:
        def start(role):
            child = subprocess.Popen(
                [sys.executable, str(script), str(SYSTEM_ROOT), str(tmp_path), role],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                cwd=str(tmp_path) if role == "foreground" else None,
            )
            children.append(child)
            return child

        background = start("background")
        _until(lambda: (tmp_path / "started").exists())
        foreground = start("foreground")
        _until(lambda: (tmp_path / "foreground-requested").exists())
        from hub._services.chat.host_inference_gate import HostInferenceGate
        _until(lambda: HostInferenceGate().status()["foreground_waiters"] == 1 or foreground.poll() is not None)
        trace = tmp_path / "trace.jsonl"
        assert [json.loads(line) for line in trace.read_text().splitlines()] == [["background", 1]]
        (tmp_path / "release").touch()
        for child in (background, foreground):
            out, err = child.communicate(timeout=10)
            assert child.returncode == 0, (out, err)
        assert [json.loads(line) for line in trace.read_text().splitlines()] == [
            ["background", 1], ["foreground", 1], ["background", 2],
        ]
    finally:
        (tmp_path / "release").touch()
        for child in children:
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()  # Only processes created by this test.
                child.communicate(timeout=5)


def test_waiter_cancellation_removes_only_own_request(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate

    async def run():
        gate = HostInferenceGate(tmp_path)
        async with gate.turn("worker", "background"):
            async def wait():
                async with gate.turn("chat", "foreground"):
                    raise AssertionError("May not enter while worker owns inference")
            pending = asyncio.create_task(wait())
            for _ in range(100):
                if gate.status()["foreground_waiters"] == 1:
                    break
                await asyncio.sleep(.01)
            assert gate.status()["foreground_waiters"] == 1
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert gate.status()["foreground_waiters"] == 0
            assert gate.status()["chat_id"] == "worker"
        assert gate.status()["active"] is False
    asyncio.run(run())


def test_dead_foreground_waiter_does_not_block_background(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate
    gate = HostInferenceGate(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    stale = tmp_path / "foreground-stale.json"
    stale.write_text(json.dumps({"pid": 2147483647, "created": 0}), encoding="utf-8")

    async def run():
        async with gate.turn("worker", "background"):
            assert gate.status()["active"] is True
    asyncio.run(asyncio.wait_for(run(), 1))
    assert not stale.exists()


def test_reused_pid_waiter_is_removed(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate
    gate = HostInferenceGate(tmp_path)
    stale = tmp_path / "foreground-reused.json"
    stale.write_text(json.dumps({"pid": os.getpid(), "created": 0}), encoding="utf-8")
    assert gate.status()["foreground_waiters"] == 0
    assert not stale.exists()


def test_owned_process_death_releases_inference_lock(tmp_path, monkeypatch):
    from hub._services.chat.host_inference_gate import HostInferenceGate
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    script = tmp_path / "crash_probe.py"
    script.write_text('''
import asyncio,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from hub._services.chat.host_inference_gate import HostInferenceGate
async def run():
 async with HostInferenceGate(Path(sys.argv[2])).turn("owned-child","background"):
  Path(sys.argv[3]).touch()
  await asyncio.sleep(30)
asyncio.run(run())
''', encoding="utf-8")
    root = tmp_path / "gate"
    started = tmp_path / "child-started"
    child = subprocess.Popen(
        [sys.executable, str(script), str(SYSTEM_ROOT), str(root), str(started)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        _until(started.exists)
        assert HostInferenceGate(root).status()["active"]
        child.terminate()  # This test owns this child; no foreign processes.
        child.communicate(timeout=5)
        assert not HostInferenceGate(root).status()["active"]

        async def next_turn():
            async with HostInferenceGate(root).turn("next-chat", "foreground"):
                assert HostInferenceGate(root).status()["chat_id"] == "next-chat"
        asyncio.run(asyncio.wait_for(next_turn(), 2))
    finally:
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=5)


def test_gate_rejects_onedrive_runtime(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate
    with pytest.raises(RuntimeError, match="OneDrive"):
        HostInferenceGate(tmp_path / "OneDrive" / "runtime")


def test_unbound_local_calls_from_two_runtimes_share_host_gate(tmp_path, monkeypatch):
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.llm.model_backend import OllamaBackend
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    runtimes = [ChatRuntime(OllamaBackend(base_url="http://127.0.0.1:11434")) for _ in range(2)]
    active = 0
    maximum = 0

    async def fake_chat(*a, **kw):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(.03)
        active -= 1
        return {"content": "fake"}
    for runtime in runtimes:
        runtime.backend.chat = fake_chat

    async def run():
        await asyncio.gather(*(runtime._chat_with_compute_turn(runtime.backend, []) for runtime in runtimes))
    asyncio.run(run())
    assert maximum == 1
    assert not runtimes[0].compute_turn_status()["active"]
