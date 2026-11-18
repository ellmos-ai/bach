"""Owner liveness must survive long native dispatch without inventing progress."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psutil
import pytest
from hub._services.docs import maintenance_runtime as runtime

NOW = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)
OLD_SUCCESS = "2026-11-17T03:00:00+00:00"


class Clock:
    def __init__(self):
        self.value = NOW
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.value

    def advance(self, seconds):
        with self.lock:
            self.value += timedelta(seconds=seconds)


def wait_until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end:
            return False
        threading.Event().wait(0.01)
    return True


def service_fixture(tmp_path, monkeypatch, *, max_ticks=1):
    clock = Clock()
    area = tmp_path / "maintenance"
    area.mkdir()
    config_path = area / "config.json"
    config_path.write_text(json.dumps({
        "schema": "bach.maintenance-config.v1",
        "enabled": True,
        "interval_seconds": 300,
        "poll_seconds": 60,
        "min_available_mib": 512,
        "max_state_db_bytes": 67108864,
        "lock_tools_root": str(tmp_path / "lock-tools"),
        "protected_roots": [str(tmp_path)],
        "worker_binding": {},
    }), encoding="utf-8")
    callers = set()

    def guard(_path):
        callers.add(threading.current_thread())

    def no_task_io(*_args, **_kwargs):
        raise AssertionError("Liveness touched task authority")

    service = runtime.MaintenanceRuntime(
        tmp_path, tmp_path / "scheduler.db", area, config_path,
        task_api=SimpleNamespace(list=no_task_io, raw=no_task_io),
        result_reader=no_task_io, guard=guard, clock=clock,
    )
    entered, release = threading.Event(), threading.Event()

    def dispatch(*, now, limit, job_ids):
        assert limit == 1
        assert job_ids == ["bach.docs.delta"]
        entered.set()
        if not release.wait(8):
            raise AssertionError("Isolated dispatch was not released")
        return []

    receipt = {
        "job_id": "bach.docs.delta", "run_id": "a" * 64,
        "status": "succeeded", "started_at": OLD_SUCCESS,
        "finished_at": OLD_SUCCESS, "exit_code": 0,
    }
    service.adapter = SimpleNamespace(
        service=SimpleNamespace(tick=dispatch),
        store=SimpleNamespace(recent_runs=lambda **_kwargs: [dict(receipt)]),
        jobs=lambda: [{
            "id": "bach.docs.delta", "is_active": True,
            "next_run": "2026-11-18T03:05:00+00:00",
            "last_success": OLD_SUCCESS,
        }],
    )
    monkeypatch.setattr("psutil.virtual_memory", lambda: SimpleNamespace(available=2**40))
    monkeypatch.setattr("psutil.disk_usage", lambda _path: SimpleNamespace(free=2**40))
    monkeypatch.setattr(runtime, "HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False)
    data = {
        "schema": "bach.maintenance-status.v1", "service": "bach-docs-maintenance",
        "pid": os.getpid(), "create_time": psutil.Process().create_time(),
        "generation": service.generation,
        "root_id": hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest(),
        "config_hash": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "poll_seconds": 60, "observed_at": NOW.isoformat(),
        "provider": "ellmos-scheduler", "state": "running",
        "semantic_review_completed": False, "runs": [receipt],
    }
    (area / "status.json").write_text(json.dumps(data), encoding="utf-8")
    process = SimpleNamespace(
        is_running=lambda: True, create_time=lambda: data["create_time"],
        cmdline=lambda: [
            "python", str(tmp_path / "system/tools/maintenance/scheduler_maintenance.py"),
            "serve", "--config", str(config_path), "--runtime-dir", str(area),
        ],
    )
    errors = []

    def serve():
        try:
            service.serve(max_ticks=max_ticks)
        except BaseException as error:  # noqa: BLE001 - expose every thread failure to the test
            errors.append(error)

    thread = threading.Thread(target=serve, name="isolated-maintenance-owner")
    return SimpleNamespace(
        service=service, area=area, clock=clock, entered=entered, release=release,
        thread=thread, errors=errors, callers=callers, process=process,
        read=lambda: runtime.readonly_status(
            area, root=tmp_path, config_path=config_path, now=clock(),
            process_factory=lambda _pid: process,
        ),
    )


def test_long_dispatch_keeps_owner_live_without_advancing_work_receipts(tmp_path, monkeypatch):
    """Removing the owned heartbeat makes a real long dispatch look dead."""
    ctx = service_fixture(tmp_path, monkeypatch)
    ctx.thread.start()
    try:
        assert ctx.entered.wait(3), "Native dispatch never entered"
        ctx.clock.advance(240)
        assert wait_until(lambda: ctx.read().get("running") is True), (
            "A live owner became stale while its admitted dispatch was still active"
        )
        raw = json.loads((ctx.area / "status.json").read_text(encoding="utf-8"))
        assert raw["observed_at"] == "2026-11-18T03:04:00+00:00"
        assert raw["receipts_observed_at"] == "2026-11-18T03:00:00+00:00"
        assert raw["runs"][0]["finished_at"] == OLD_SUCCESS
        assert raw["jobs"][0]["last_success"] == OLD_SUCCESS
        assert raw["semantic_review_completed"] is False
        assert not ctx.release.is_set()
        assert not (tmp_path / "scheduler.db").exists()
    finally:
        ctx.service.stop_event.set()
        ctx.release.set()
        ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert ctx.errors == []
    background = ctx.callers - {ctx.thread, threading.current_thread()}
    assert background, "No independent status publication occurred"
    assert all(not thread.is_alive() for thread in background)
    assert ctx.read()["state"] == "stopped"


def test_slow_final_status_guard_does_not_publish_an_old_heartbeat(tmp_path, monkeypatch):
    """A scan that finishes late must not make its new receipt stale on arrival."""
    ctx = service_fixture(tmp_path, monkeypatch)
    first_guard, release_first = threading.Event(), threading.Event()
    next_guard, release_next = threading.Event(), threading.Event()
    status_visits = 0

    def guard(path):
        nonlocal status_visits
        ctx.callers.add(threading.current_thread())
        if threading.current_thread() is ctx.thread or path.name != "status.json":
            return
        status_visits += 1
        if status_visits == 2:
            first_guard.set()
            assert release_first.wait(8)
        elif status_visits == 3:
            next_guard.set()
            assert release_next.wait(8)

    ctx.service.runtime_guard = guard
    ctx.thread.start()
    try:
        assert ctx.entered.wait(3)
        assert first_guard.wait(3)
        ctx.clock.advance(240)
        release_first.set()
        assert next_guard.wait(3)
        raw = json.loads((ctx.area / "status.json").read_text(encoding="utf-8"))
        assert raw["observed_at"] == "2026-11-18T03:04:00+00:00"
        assert raw["receipts_observed_at"] == "2026-11-18T03:00:00+00:00"
        assert ctx.read()["running"] is True
    finally:
        ctx.service.stop_event.set()
        release_first.set()
        release_next.set()
        ctx.release.set()
        ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert ctx.errors == []


def test_public_status_separates_liveness_data_time_and_requested_stop(tmp_path, monkeypatch):
    ctx = service_fixture(tmp_path, monkeypatch)
    path = ctx.area / "status.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(receipts_observed_at="2026-11-18T02:59:00+00:00", stop_requested=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    observed = ctx.read()
    assert observed["running"] is True
    assert observed["receipts_observed_at"] == "2026-11-18T02:59:00+00:00"
    assert observed["stop_requested"] is True


def test_stop_request_keeps_owner_until_admitted_work_finishes(tmp_path, monkeypatch):
    ctx = service_fixture(tmp_path, monkeypatch)
    ctx.thread.start()
    try:
        assert ctx.entered.wait(3)
        ctx.service.stop_event.set()
        assert wait_until(lambda: ctx.read().get("stop_requested") is True)
        assert ctx.read()["running"] is True
        assert not ctx.release.is_set()
        with pytest.raises(OSError), runtime.process_owner(
            ctx.service.owner_path, lambda _path: None,
        ):
            pytest.fail("Stop request released an owner with admitted work")
    finally:
        ctx.release.set()
        ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert ctx.errors == []
    assert ctx.read()["state"] == "stopped"
    assert ctx.read()["running"] is False


def test_heartbeat_thread_exits_before_owner_is_released(tmp_path, monkeypatch):
    """Omitting join must expose an owner release before the last writer exits."""
    ctx = service_fixture(tmp_path, monkeypatch)
    exit_pending, allow_exit = threading.Event(), threading.Event()
    run = runtime._OwnerHeartbeat._run

    def delayed_exit(publisher):
        try:
            run(publisher)
        finally:
            exit_pending.set()
            assert allow_exit.wait(8)

    monkeypatch.setattr(runtime._OwnerHeartbeat, "_run", delayed_exit)
    ctx.thread.start()
    try:
        assert ctx.entered.wait(3)
        ctx.service.stop_event.set()
        ctx.release.set()
        assert exit_pending.wait(3)
        assert ctx.thread.is_alive()
        with pytest.raises(OSError), runtime.process_owner(
            ctx.service.owner_path, lambda _path: None,
        ):
            pytest.fail("Owner released while its heartbeat thread still existed")
    finally:
        allow_exit.set()
        ctx.service.stop_event.set()
        ctx.release.set()
        ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert ctx.errors == []
    assert all(not t.is_alive() for t in ctx.callers)


def test_replaced_owner_during_status_scan_cannot_overwrite_successor(tmp_path, monkeypatch):
    ctx = service_fixture(tmp_path, monkeypatch)
    scanning, continue_scan = threading.Event(), threading.Event()

    def guard(path):
        ctx.callers.add(threading.current_thread())
        if threading.current_thread() is not ctx.thread and path.name == "status.json":
            scanning.set()
            assert continue_scan.wait(8)

    ctx.service.runtime_guard = guard
    ctx.thread.start()
    try:
        assert ctx.entered.wait(3)
        assert scanning.wait(3)
        ctx.service.owner_path.rename(ctx.area / "previous-owner")
        with runtime.process_owner(ctx.service.owner_path, lambda _path: None):
            status = ctx.area / "status.json"
            successor = json.loads(status.read_text(encoding="utf-8"))
            successor["generation"] = "b" * 32
            successor["observed_at"] = "2026-11-18T03:01:00+00:00"
            successor_bytes = json.dumps(successor).encode()
            status.write_bytes(successor_bytes)
            continue_scan.set()
            ctx.release.set()
            ctx.thread.join(4)
            assert not ctx.thread.is_alive()
            assert status.read_bytes() == successor_bytes
    finally:
        continue_scan.set()
        ctx.service.stop_event.set()
        ctx.release.set()
        ctx.thread.join(4)
    assert len(ctx.errors) == 1
    assert isinstance(ctx.errors[0], PermissionError)
    assert all(not t.is_alive() for t in ctx.callers)


def test_owner_is_rechecked_after_fsync_before_publish(tmp_path, monkeypatch):
    owner, status = tmp_path / "owner.lock", tmp_path / "status.json"
    status.write_bytes(b"old receipt")
    fsync = os.fsync

    def replace_owner(fd):
        fsync(fd)
        owner.rename(tmp_path / "previous-owner")
        owner.write_bytes(b"")

    with runtime.process_owner(owner, lambda _path: None) as verify:
        monkeypatch.setattr(runtime.os, "fsync", replace_owner)
        with pytest.raises(PermissionError):
            runtime._write_status(
                status, {"state": "running"}, lambda _path: None, verify_owner=verify,
            )
    assert status.read_bytes() == b"old receipt"


def test_released_owner_cannot_authorize_another_publication(tmp_path):
    with runtime.process_owner(tmp_path / "owner.lock", lambda _path: None) as verify:
        verify()
    with pytest.raises(PermissionError):
        verify()


def test_failed_heartbeat_stops_before_another_native_dispatch(tmp_path, monkeypatch):
    ctx = service_fixture(tmp_path, monkeypatch, max_ticks=None)

    def guard(_path):
        ctx.callers.add(threading.current_thread())
        if threading.current_thread() is not ctx.thread:
            raise PermissionError("unknown status authority")

    ctx.service.runtime_guard = guard
    ctx.thread.start()
    try:
        assert ctx.entered.wait(3)
        assert ctx.service.stop_event.wait(3)
        ctx.release.set()
        ctx.thread.join(4)
    finally:
        ctx.service.stop_event.set()
        ctx.release.set()
        ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert len(ctx.errors) == 1
    assert isinstance(ctx.errors[0], PermissionError)
    assert ctx.service.failure_phase == "status_write"
    assert ctx.read()["state"] == "stopped"
    assert all(not t.is_alive() for t in ctx.callers)


def test_dispatch_error_does_not_leave_a_live_heartbeat(tmp_path, monkeypatch):
    ctx = service_fixture(tmp_path, monkeypatch)

    def failed_dispatch(**_kwargs):
        ctx.entered.set()
        raise RuntimeError("isolated dispatch failure")

    ctx.service.adapter.service.tick = failed_dispatch
    ctx.thread.start()
    ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert len(ctx.errors) == 1
    assert str(ctx.errors[0]) == "isolated dispatch failure"
    assert ctx.service.failure_phase == "scheduler_tick"
    assert ctx.read()["state"] == "stopped"
    assert ctx.read()["running"] is False
    assert all(not t.is_alive() for t in ctx.callers)


@pytest.mark.parametrize("state", [
    "busy", "backoff", "storage_budget", "storage_reserve", "waiting_for_lock",
])
def test_heartbeat_preserves_non_work_state_without_starting_jobs(
    tmp_path, monkeypatch, state,
):
    ctx = service_fixture(tmp_path, monkeypatch, max_ticks=None)
    if state == "busy":
        monkeypatch.setattr("psutil.virtual_memory", lambda: SimpleNamespace(available=1))
    elif state == "backoff":
        ctx.service.retry_at = NOW + timedelta(seconds=600)
    elif state == "storage_budget":
        with (tmp_path / "scheduler.db").open("wb") as stream:
            stream.truncate(67108865)
    elif state == "storage_reserve":
        monkeypatch.setattr("psutil.disk_usage", lambda _path: SimpleNamespace(free=1))
    else:
        def project_locked(_path):
            raise runtime.MaintenanceLockHeld("isolated project lock")
        ctx.service.guard = project_locked
    ctx.thread.start()
    try:
        assert wait_until(lambda: ctx.read().get("state") == state)
        ctx.clock.advance(240)
        assert wait_until(lambda: ctx.read().get("running") is True)
        observed = ctx.read()
        assert observed["state"] == state
        assert observed["semantic_review_completed"] is False
        assert not ctx.entered.is_set()
        if state == "waiting_for_lock":
            assert observed["runs"] == []
            assert observed["jobs"] == []
    finally:
        ctx.service.stop_event.set()
        ctx.release.set()
        ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert ctx.errors == []
    assert ctx.read()["state"] == "stopped"


@pytest.mark.parametrize("damage", ["dead_process", "pid_reused", "stale_151_seconds"])
def test_heartbeat_does_not_weaken_crash_identity_or_150_second_limit(
    tmp_path, monkeypatch, damage,
):
    ctx = service_fixture(tmp_path, monkeypatch)
    if damage == "dead_process":
        ctx.process.is_running = lambda: False
    elif damage == "pid_reused":
        ctx.process.create_time = lambda: psutil.Process().create_time() + 1
    else:
        ctx.clock.advance(151)
    observed = ctx.read()
    assert observed["running"] is False
    assert observed["reason"] == "receipt_not_current"


@pytest.mark.parametrize("fields", [
    {"receipts_observed_at": "2026-11-18T03:01:00+00:00"},
    {"receipts_observed_at": "2026-11-18T03:00:00"},
    {"receipts_observed_at": {"secret": "private"}},
    {"stop_requested": "true"},
])
def test_malformed_heartbeat_metadata_is_not_projected(tmp_path, monkeypatch, fields):
    ctx = service_fixture(tmp_path, monkeypatch)
    path = ctx.area / "status.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(fields)
    path.write_text(json.dumps(raw), encoding="utf-8")
    observed = ctx.read()
    assert observed["running"] is False
    assert observed["reason"] == "maintenance_receipt_unverified"
    assert "private" not in json.dumps(observed)


def test_last_heartbeat_failure_is_not_lost_during_shutdown(tmp_path, monkeypatch):
    """A failure after the final loop check must survive the mandatory join."""
    ctx = service_fixture(tmp_path, monkeypatch)
    shutdown_entered, failed = threading.Event(), threading.Event()
    stop = runtime._OwnerHeartbeat.stop

    def guard(_path):
        ctx.callers.add(threading.current_thread())
        if threading.current_thread() is not ctx.thread and shutdown_entered.is_set():
            failed.set()
            raise PermissionError("authority lost during shutdown")

    def let_last_writer_finish(publisher):
        shutdown_entered.set()
        assert failed.wait(3)
        stop(publisher)

    ctx.service.runtime_guard = guard
    monkeypatch.setattr(runtime._OwnerHeartbeat, "stop", let_last_writer_finish)
    ctx.thread.start()
    try:
        assert ctx.entered.wait(3)
        ctx.release.set()
        ctx.thread.join(4)
    finally:
        ctx.service.stop_event.set()
        ctx.release.set()
        ctx.thread.join(4)
    assert not ctx.thread.is_alive()
    assert len(ctx.errors) == 1
    assert str(ctx.errors[0]) == "authority lost during shutdown"
    assert ctx.service.failure_phase == "status_write"
    assert ctx.read()["state"] == "stopped"
    assert all(not thread.is_alive() for thread in ctx.callers)
