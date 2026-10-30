# SPDX-License-Identifier: MIT
"""Isolated host coordination checks; fake backends never make model calls."""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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


def test_cross_process_fifo_with_three_to_one_foreground_fairness(tmp_path):
    gate_root = tmp_path / "gate"
    script = tmp_path / "queued_inference.py"
    target = {
        "socket_id": "socket-test",
        "binding_id": "binding-test",
        "agent_id": "worker-test",
        "backend": "ollama",
        "model": "fixture:small",
    }
    script.write_text('''
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hub._services.chat.host_inference_gate import HostInferenceGate
root = Path(sys.argv[2])
name, priority = sys.argv[3], sys.argv[4]
target = {
    "socket_id": "socket-test",
    "binding_id": "binding-test",
    "agent_id": "worker-test",
    "backend": "ollama",
    "model": "fixture:small",
}
async def run():
    async with HostInferenceGate(root).turn(name, priority, model_target=target):
        with (root / "order.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(name) + "\\n")
        (root / (name + ".entered")).touch()
        while not (root / (name + ".continue")).exists():
            await asyncio.sleep(.005)
asyncio.run(run())
''', encoding="utf-8")
    gate_root.mkdir()
    children = []
    waiters = []
    queued = [
        ("fg1", "foreground"),
        ("fg2", "foreground"),
        ("fg3", "foreground"),
        ("fg4", "foreground"),
        ("bg1", "background"),
        ("bg2", "background"),
    ]
    trace = gate_root / "order.jsonl"

    def observed_order():
        if not trace.exists():
            return []
        return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]

    def start(name, priority):
        child = subprocess.Popen(
            [sys.executable, str(script), str(SYSTEM_ROOT), str(gate_root), name, priority],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=str(tmp_path),
        )
        children.append(child)
        if name != "holder":
            waiters.append((name, child))
        return child

    def failed_waiter():
        entered = set(observed_order())
        return next(
            ((name, child) for name, child in waiters
             if child.poll() is not None and name not in entered),
            None,
        )

    try:
        holder = start("holder", "background")
        _until(lambda: (gate_root / "holder.entered").exists() or holder.poll() is not None)
        assert holder.poll() is None

        digest = hashlib.sha256(json.dumps(
            {"bound": True, "model_target": target},
            ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        for index, (name, priority) in enumerate(queued, start=1):
            child = start(name, priority)
            _until(lambda count=index, process=child:
                   len(list(gate_root.glob("ticket-*.json"))) == count
                   or process.poll() is not None)
            assert child.poll() is None
            tickets = list(gate_root.glob("ticket-*.json"))
            assert len(tickets) == index
            records = [
                json.loads(path.read_text(encoding="utf-8")) for path in tickets
            ]
            record = max(records, key=lambda item: item["sequence"])
            assert record["priority"] == priority
            assert record["target_sha256"] == digest
            assert target["model"] not in json.dumps(record)

        (gate_root / "holder.continue").touch()
        expected = ["holder", "fg1", "fg2", "fg3", "bg1", "fg4", "bg2"]
        for index, name in enumerate(expected[1:], start=2):
            _until(lambda expected_count=index:
                   len(observed_order()) >= expected_count or failed_waiter() is not None)
            order = observed_order()
            if len(order) < index:
                failed = failed_waiter()
                details = None
                if failed is not None:
                    failed_name, failed_child = failed
                    out, err = failed_child.communicate()
                    details = (failed_name, failed_child.returncode, out, err)
                raise AssertionError(f"Queued process exited before admission: {details!r}; order={order!r}")
            assert order[index - 1] == name, order
            (gate_root / (name + ".continue")).touch()

        for child in children:
            out, err = child.communicate(timeout=10)
            assert child.returncode == 0, (out, err)
        assert observed_order() == expected
    finally:
        (gate_root / "holder.continue").touch()
        for name, _ in queued:
            (gate_root / (name + ".continue")).touch()
        for child in children:
            if child.poll() is None:
                child.terminate()
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
    stale.write_text(json.dumps({"pid": 2147483647, "created": 1.0}), encoding="utf-8")

    async def run():
        async with gate.turn("worker", "background"):
            assert gate.status()["active"] is True
    asyncio.run(asyncio.wait_for(run(), 1))
    assert not stale.exists()


def test_reused_pid_waiter_is_removed(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate
    gate = HostInferenceGate(tmp_path)
    stale = tmp_path / "foreground-reused.json"
    stale.write_text(json.dumps({"pid": os.getpid(), "created": 1.0}), encoding="utf-8")
    assert gate.status()["foreground_waiters"] == 0
    assert not stale.exists()


@pytest.mark.parametrize("created_json", ["NaN", "Infinity", "-Infinity", "-1", "0"])
def test_invalid_legacy_marker_fails_closed_before_liveness(tmp_path, monkeypatch, created_json):
    import hub._services.chat.host_inference_gate as gate_module
    from hub._services.chat.host_inference_gate import HostInferenceGate

    gate = HostInferenceGate(tmp_path)
    marker = tmp_path / "foreground-invalid.json"
    marker.write_text(
        f'{{"pid":{os.getpid()},"created":{created_json}}}', encoding="utf-8"
    )
    probes = []

    def forbidden_liveness_probe(pid):
        probes.append(pid)
        pytest.fail("invalid process creation time must fail before PID probing")

    monkeypatch.setattr(gate_module.psutil, "Process", forbidden_liveness_probe)
    with pytest.raises(RuntimeError, match="Ungültiger Inferenz-Koordinationsbeleg"):
        gate._legacy_foreground_count_locked(set())

    assert probes == []
    assert marker.is_file()


def test_mixed_live_legacy_foreground_markers_are_preserved(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate

    gate = HostInferenceGate(tmp_path)
    identity = gate._identity()
    ticket_id = "a" * 32
    legacy = tmp_path / "foreground-legacy.json"
    queued = tmp_path / f"foreground-{ticket_id}.json"
    legacy.write_text(json.dumps(identity), encoding="utf-8")
    queued.write_text(json.dumps({**identity, "ticket_id": ticket_id}), encoding="utf-8")

    assert gate._legacy_foreground_count_locked({ticket_id}) == 1
    assert legacy.is_file()
    assert queued.is_file()


def test_live_legacy_foreground_marker_blocks_new_background(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate

    gate = HostInferenceGate(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    marker = tmp_path / "foreground-legacy.json"
    marker.write_text(json.dumps(gate._identity()), encoding="utf-8")
    entered = []

    async def run():
        async def background():
            async with gate.turn("background", "background"):
                entered.append(True)

        pending = asyncio.create_task(background())
        for _ in range(100):
            if list(tmp_path.glob("ticket-*.json")):
                break
            await asyncio.sleep(.01)
        assert list(tmp_path.glob("ticket-*.json"))
        assert gate.status()["foreground_waiters"] == 1
        assert not entered
        marker.unlink()
        await asyncio.wait_for(pending, 1)

    asyncio.run(run())
    assert entered == [True]


def test_reused_pid_queue_ticket_is_removed(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate

    gate = HostInferenceGate(tmp_path)
    ticket = tmp_path / ("ticket-" + "a" * 32 + ".json")
    ticket.write_text(json.dumps({
        "schema": "bach.local-inference-ticket.v1",
        "ticket_id": "a" * 32,
        "pid": os.getpid(),
        "created": 1.0,
        "priority": "foreground",
        "sequence": 1,
        "target_sha256": "b" * 64,
    }), encoding="utf-8")

    assert gate._foreground_waiters() == 0
    assert not ticket.exists()


def test_crashed_foreground_waiter_is_reaped_without_blocking_background(tmp_path):
    from hub._services.chat.host_inference_gate import HostInferenceGate

    gate_root = tmp_path / "gate"
    script = tmp_path / "queued_waiter.py"
    child_entered = tmp_path / "child-entered"
    script.write_text('''
import asyncio, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hub._services.chat.host_inference_gate import HostInferenceGate
root = Path(sys.argv[2])
async def run():
    async with HostInferenceGate(root).turn("crashed-waiter", "foreground"):
        Path(sys.argv[3]).touch()
        await asyncio.sleep(30)
asyncio.run(run())
''', encoding="utf-8")

    async def run():
        async with HostInferenceGate(gate_root).turn("holder", "background"):
            child = await asyncio.create_subprocess_exec(
                sys.executable, str(script), str(SYSTEM_ROOT), str(gate_root),
                str(child_entered),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                for _ in range(500):
                    if list(gate_root.glob("ticket-*.json")) or child.returncode is not None:
                        break
                    await asyncio.sleep(.01)
                assert child.returncode is None
                assert list(gate_root.glob("ticket-*.json"))
                assert not child_entered.exists()
                child.terminate()
                await asyncio.wait_for(child.communicate(), timeout=5)
                assert HostInferenceGate(gate_root).status()["foreground_waiters"] == 0
                assert not list(gate_root.glob("ticket-*.json"))
                assert not list(gate_root.glob("foreground-*.json"))
            finally:
                if child.returncode is None:
                    child.terminate()
                await asyncio.wait_for(child.communicate(), timeout=5)
        async with HostInferenceGate(gate_root).turn("next", "background"):
            assert HostInferenceGate(gate_root).status()["chat_id"] == "next"

    asyncio.run(run())


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


class _FakeLock:
    """Minimaler Ersatz für den exklusiven Lock aus ``user_config_store``."""

    def __init__(self):
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.exited = True
        return False


def test_release_model_now_releases_under_exclusive_lock(tmp_path, monkeypatch):
    """Erfolgsfall: Lock wird genutzt, Adapter meldet Erfolg, Lock wird freigegeben."""
    import hub._services.chat.host_inference_gate as gate_mod
    from hub._services.chat.host_inference_gate import HostInferenceGate

    lock = _FakeLock()
    seen = {}

    def fake_lock(path, timeout_seconds=0):
        seen["path"] = path
        seen["timeout"] = timeout_seconds
        return lock

    def fake_release(model, *, digest=None, timeout_seconds=0, wait=True):
        seen["model"] = model
        seen["digest"] = digest
        seen["timeout_release"] = timeout_seconds
        seen["wait"] = wait
        return True

    monkeypatch.setattr(gate_mod, "_exclusive_lock", fake_lock)
    monkeypatch.setattr(gate_mod, "_release_model_locked", fake_release)

    result = HostInferenceGate(tmp_path).release_model_now({"model": "qwen-test"})

    expected_digest = HostInferenceGate._target_digest({"model": "qwen-test"})
    assert result == {"ok": True, "released": True, "warning": None, "error": None}
    assert seen["model"] == "qwen-test"
    assert seen["digest"] == expected_digest
    assert seen["timeout_release"] == 0
    assert seen["wait"] is True
    assert seen["path"] == (tmp_path / "inference").expanduser().resolve()
    assert lock.exited is True


def test_release_model_now_never_raises_on_bad_target(tmp_path, monkeypatch):
    """Ungültiges ``model_target`` führt zu ``ok=False`` mit Fehlertext, nie zu einer Exception."""
    import hub._services.chat.host_inference_gate as gate_mod
    from hub._services.chat.host_inference_gate import HostInferenceGate

    lock = _FakeLock()
    monkeypatch.setattr(gate_mod, "_exclusive_lock", lambda *a, **kw: lock)
    monkeypatch.setattr(gate_mod, "_release_model_locked", lambda m: True)

    result = HostInferenceGate(tmp_path).release_model_now(None)

    assert result["ok"] is False
    assert result["released"] is False
    assert result["error"]
    assert lock.exited is True


def test_release_model_locked_returns_false_when_guard_missing_or_failing(monkeypatch):
    """Der Adapter meldet nur bei bestätigtem Unload ``True`` und wirft nie."""
    import hub._services.chat.host_inference_gate as gate_mod

    monkeypatch.setattr(gate_mod, "_load_unload_guard", lambda: None)
    assert gate_mod._release_model_locked("qwen-test") is False

    class RaisingGuard:
        def unload(self, model, *, digest=None, timeout_s=0, wait=True):
            raise RuntimeError("Ollama nicht erreichbar")

    monkeypatch.setattr(gate_mod, "_load_unload_guard", lambda: RaisingGuard())
    assert gate_mod._release_model_locked("qwen-test") is False

    class NotUnloadedGuard:
        def unload(self, model, *, digest=None, timeout_s=0, wait=True):
            return {"unloaded": False, "warning": "noch geladen"}

    monkeypatch.setattr(gate_mod, "_load_unload_guard", lambda: NotUnloadedGuard())
    assert gate_mod._release_model_locked("qwen-test") is False

    class OddReportGuard:
        def unload(self, model, *, digest=None, timeout_s=0, wait=True):
            return "unerwartet"

    monkeypatch.setattr(gate_mod, "_load_unload_guard", lambda: OddReportGuard())
    assert gate_mod._release_model_locked("qwen-test") is False

    class OkGuard:
        def unload(self, model, *, digest=None, timeout_s=0, wait=True):
            return {"unloaded": True}

    monkeypatch.setattr(gate_mod, "_load_unload_guard", lambda: OkGuard())
    assert gate_mod._release_model_locked("qwen-test") is True



def test_release_model_now_holds_real_exclusive_lock_during_unload(tmp_path, monkeypatch):
    """Regressionstest: Der echte _exclusive_lock muss waehrend des Unload gehalten werden."""
    import os

    import hub._services.chat.host_inference_gate as gate_mod
    from hub._services.chat.host_inference_gate import HostInferenceGate

    gate = HostInferenceGate(tmp_path)
    lock_path = (tmp_path / "inference").with_name("inference.lock")
    state = {"spy_called": False, "gate_holds_lock": None}

    def spy(model, digest=None, timeout_seconds=None, wait=True):
        state["spy_called"] = True
        if os.name != "nt":
            import fcntl

            with open(lock_path, "a+b") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    state["gate_holds_lock"] = True
                else:
                    state["gate_holds_lock"] = False
                    raise AssertionError(
                        "release_model_now haelt den exklusiven Lock waehrend des Unload nicht"
                    )
        return True

    monkeypatch.setattr(gate_mod, "_release_model_locked", spy)

    result = gate.release_model_now({"model": "qwen-test"})

    assert state["spy_called"] is True
    assert state["gate_holds_lock"] is not False
    assert result == {"ok": True, "released": True, "warning": None, "error": None}


def test_release_model_now_warns_cleanly_when_real_lock_is_busy(tmp_path):
    """Verhaltens-Guard: extern gehaltener Lock fuehrt zu sauberem Warning statt Exception."""
    import os

    from hub._services.chat.host_inference_gate import HostInferenceGate

    if os.name == "nt":
        return

    import fcntl

    gate = HostInferenceGate(tmp_path)
    lock_path = (tmp_path / "inference").with_name("inference.lock")
    with open(lock_path, "a+b") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = gate.release_model_now({"model": "qwen-test"}, timeout_seconds=0)

    assert result["ok"] is False
    assert result["released"] is False
    assert result["warning"] is not None
    assert result["error"] is None
