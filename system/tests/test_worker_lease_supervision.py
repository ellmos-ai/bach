"""Real isolated leases and owned heartbeat threads; no live models or DBs."""
import asyncio
import sqlite3
import threading
import time

import pytest
from hub._services import task_lease_client as client_module
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease_client import (
    LeaseConnectionError,
    LeaseError,
    TaskLeaseClient,
)

from system.tests.test_task_lease_service import _connect, _create_db, _insert


@pytest.fixture
def binding(tmp_path, monkeypatch, request):
    database = tmp_path / "canonical.db"
    _create_db(database)
    connection = _connect(database)
    tid = _insert(connection)
    connection.close()
    monkeypatch.setattr(client_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    if getattr(request, "param", None) == "max-total":
        monkeypatch.setenv("BACH_TASK_LEASE_PROFILES", '{"M": [90, 90]}')
    client = TaskLeaseClient(db_path=database)
    bound = WorkerLeaseBinding.acquire(client, tid, worker_id="physical-worker@HOST", host="HOST",
                                      generation="current", is_current=lambda: True,
                                      stop_event=threading.Event())
    yield bound
    bound.return_lease()


def test_heartbeat_renews_actual_lease_while_worker_is_busy(binding):
    from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
    supervisor = WorkerLeaseSupervisor(binding, poll_interval=.01, renew_interval=.01)
    with supervisor:
        deadline = time.monotonic() + 2
        count = 0
        while time.monotonic() < deadline:
            with sqlite3.connect(binding._client._db_path) as connection:
                count = connection.execute("SELECT count(*) FROM task_history WHERE action='lease_renew'").fetchone()[0]
            if count: break
            time.sleep(.01)
        assert count >= 1
        binding.assert_active()
    assert supervisor.failure is None
    assert not supervisor.is_alive
    assert not binding.completed_task_ids


def test_lost_renew_ack_revokes_writes_but_waits_for_actual_provider_completion(binding, monkeypatch):
    from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
    original = binding._client.renew
    calls = []
    def lose(*args, **kwargs):
        calls.append(args)
        original(*args, **kwargs)
        raise LeaseConnectionError("Bestätigung fehlt")
    monkeypatch.setattr(binding._client, "renew", lose)
    async def probe():
        supervisor = WorkerLeaseSupervisor(binding, poll_interval=.01, renew_interval=.01)
        started = asyncio.Event()
        release = asyncio.Event()
        async def provider():
            started.set()
            await release.wait()
            return "actual terminal result"
        task = asyncio.create_task(supervisor.run(provider))
        await asyncio.wait_for(started.wait(), 1)
        deadline = time.monotonic() + 2
        while supervisor.failure is None and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert supervisor.failure is not None
        assert not task.done()  # Missing ACK is not a physical provider cancellation.
        with pytest.raises(LeaseError):
            binding.execute_task_manage({"action": "done", "task_id": binding.task_id, "result": "Konkretes Ergebnis unter Lease-Überwachung"})
        assert binding.return_lease() is False
        release.set()
        with pytest.raises(LeaseError): await asyncio.wait_for(task, 1)
        assert not supervisor.is_alive
    asyncio.run(probe())
    assert len(calls) == 1
    assert not binding.completed_task_ids
    assert binding._client.task_snapshot(binding.task_id)["status"] == "in_progress"


def test_manual_stop_waits_for_provider_then_allows_known_lease_return(binding):
    from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
    async def probe():
        supervisor = WorkerLeaseSupervisor(binding, poll_interval=.01)
        started = asyncio.Event()
        release = asyncio.Event()
        async def provider():
            started.set()
            await release.wait()
            return "terminal"
        task = asyncio.create_task(supervisor.run(provider))
        await asyncio.wait_for(started.wait(), 1)
        binding._stop_event.set()
        deadline = time.monotonic() + 1
        while supervisor.is_alive and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert not task.done()
        assert not supervisor.is_alive
        release.set()
        assert await asyncio.wait_for(task, 1) == "terminal"
        assert supervisor.failure is None
    asyncio.run(probe())
    assert binding.return_lease()
    assert binding._client.task_snapshot(binding.task_id)["status"] == "pending"


def test_local_deadline_loss_revokes_binding_without_fabricated_completion(binding):
    from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
    supervisor = WorkerLeaseSupervisor(binding, poll_interval=.01)
    with supervisor:
        binding._clock = lambda: binding._ack.local_deadline
        assert supervisor.wait_for_failure(1)
    with pytest.raises(LeaseError): binding.assert_active()
    assert not binding.completed_task_ids
    assert not supervisor.is_alive


def test_heartbeat_runs_even_when_provider_blocks_its_event_loop(binding):
    from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
    async def provider():
        time.sleep(.08)  # noqa: ASYNC251 -- Deliberately blocked provider event loop.
        return "actual terminal"
    supervisor = WorkerLeaseSupervisor(binding, poll_interval=.005, renew_interval=.005)
    assert asyncio.run(supervisor.run(provider)) == "actual terminal"
    with sqlite3.connect(binding._client._db_path) as connection:
        assert connection.execute("SELECT count(*) FROM task_history WHERE action='lease_renew'").fetchone()[0] >= 1
    assert not supervisor.is_alive


@pytest.mark.parametrize("gate_kind", ["host", "runtime"])
def test_stopping_before_inference_aborts_gate_wait_without_provider_call(binding, monkeypatch, tmp_path, gate_kind):
    from contextlib import AsyncExitStack
    from unittest.mock import AsyncMock

    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.chat.host_inference_gate import HostInferenceGate
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path / "runtime"))
    backend = type("Backend", (), {
        "get_default_model": lambda self: "example:small",
        "chat": AsyncMock(return_value={"content": "unused"}),
    })()
    runtime = ChatRuntime(backend)
    session = runtime.get_session("worker-waiting")
    session.worker_task_binding = binding
    session.require_task_binding = True
    monkeypatch.setattr(runtime, "_uses_local_compute", lambda backend: True)
    async def probe():
        token = runtime._compute_turn_context.set(("worker-waiting", "background"))
        try:
            async with AsyncExitStack() as stack:
                if gate_kind == "host":
                    await stack.enter_async_context(HostInferenceGate().turn("foreground", "foreground"))
                else:
                    runtime._compute_turn_gate.active = True
                task = asyncio.create_task(runtime._chat_with_compute_turn(backend, []))
                await asyncio.sleep(.04)
                binding._stop_event.set()
                with pytest.raises(RuntimeError, match="Taskbindung"):
                    await asyncio.wait_for(task, .5)
                if gate_kind == "host": assert HostInferenceGate().status()["chat_id"] == "foreground"
        finally:
            runtime._compute_turn_context.reset(token)
    asyncio.run(probe())
    backend.chat.assert_not_awaited()


@pytest.mark.parametrize("binding", ["max-total"], indirect=True)
def test_max_total_denial_keeps_known_lease_valid_until_its_deadline(binding, monkeypatch):
    from hub._services.chat.worker_lease_supervisor import WorkerLeaseSupervisor
    original = binding._client.renew
    calls = []
    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(binding._client, "renew", counted)
    async def provider():
        await asyncio.sleep(.03)
        binding.assert_active()
        return binding.execute_task_manage({"action": "done", "task_id": binding.task_id, "result": "Konkretes Ergebnis unter Lease-Überwachung"})
    supervisor = WorkerLeaseSupervisor(binding, poll_interval=.005, renew_interval=.005)
    assert asyncio.run(supervisor.run(provider)) == f"Task #{binding.task_id}: Ergebnis gespeichert, wartet in Review auf getrennte Abnahme."
    assert supervisor.failure is None
    assert len(calls) == 1  # Exhaustion is known; never retry Renew for this lease.
    assert not binding.completed_task_ids and binding.reviewed_task_ids == (binding.task_id,)
    assert not supervisor.is_alive
