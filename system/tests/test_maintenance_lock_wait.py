"""Maintenance waits only on proven locks and never turns diagnosis into work authority."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub._services.docs import maintenance_runtime as runtime

NOW = datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.elapsed = 0.0

    def monotonic(self):
        return self.elapsed

    def now(self):
        return NOW + timedelta(seconds=self.elapsed)


class Event:
    def __init__(self, clock, callback=None):
        self.clock, self.callback = clock, callback
        self.stopped = False
        self.waits = []

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        assert len(self.waits) <= 12, 'Unexpected unbounded scheduler loop'
        assert 0 < seconds <= 300
        self.clock.elapsed += seconds
        if self.callback:
            self.callback(self)
        return self.stopped


@pytest.fixture
def context(tmp_path, monkeypatch):
    project, twin, local = (tmp_path / name for name in ("project", "twin", "local"))
    area = local / "maintenance"
    tools = tmp_path / "lock-tools"
    for path in (project, twin, area, tools):
        path.mkdir(parents=True)
    for name in ("lock_scan.py", "lock_utils.py"):
        (tools / name).write_text("# isolated scanner boundary\n", encoding="utf-8")
    pair = tuple(hashlib.sha256((tools / name).read_bytes()).hexdigest()
                 for name in ("lock_scan.py", "lock_utils.py"))
    monkeypatch.setattr(runtime, "TRUSTED_LOCK_TOOLS", {pair})
    config = {
        "schema": "bach.maintenance-config.v1",
        "enabled": True,
        "interval_seconds": 300,
        "poll_seconds": 60,
        "min_available_mib": 512,
        "max_state_db_bytes": 67108864,
        "lock_tools_root": str(tools),
        "protected_roots": [str(project), str(local), str(twin)],
        "worker_binding": {},
    }
    cp = area / "config.json"
    cp.write_text(json.dumps(config), encoding="utf-8")
    ctx = SimpleNamespace(project=project, twin=twin, local=local, area=area,
                          tools=tools, config=config, cp=cp, scans=[],
                          project_locked=False, runtime_locked=False, alter=None)
    clock = Clock()
    monkeypatch.setattr(runtime.time, "monotonic", clock.monotonic)
    ctx.clock = clock

    def run(command, **options):
        assert "--check-dir" in command
        target = Path(command[command.index("--check-dir") + 1])
        ctx.scans.append(target)
        fields = {
            "checked": str(target), "locks": [], "hook_guards": [],
            "twin_status": "not-applicable", "descendants_complete": True,
            "twins_checked": [],
        }
        code = 0
        if target == project:
            fields.update(twin_status="ok", twins_checked=[str(twin)])
        elif target == twin:
            fields["twin_status"] = "pointer-unresolved"
            code = 1
        locked = ((ctx.project_locked and target == project)
                  or (ctx.runtime_locked and target in (local, area)))
        if locked:
            fields["locks"] = [{"path": str(target / "LOCK.other.txt"),
                                 "scope": "fixture", "legacy": False,
                                 "from_main_repo_of_worktree": False, "from_twin": False}]
            code = 1
        if ctx.alter:
            code, fields = ctx.alter(target, code, fields)
        return SimpleNamespace(returncode=code, stdout=json.dumps(fields), stderr="")

    monkeypatch.setattr(runtime.subprocess, "run", run)
    ctx.guard = runtime.CanonicalLockGuard(config)
    return ctx


def service_for(ctx, monkeypatch):
    def no_task_io(*_args, **_kwargs):
        pytest.fail("Blocked maintenance touched native task authority")

    service = runtime.MaintenanceRuntime(
        ctx.project, ctx.local / "scheduler.db", ctx.area, ctx.cp,
        guard=ctx.guard, clock=ctx.clock.now, task_db=ctx.local / "bach.db",
        task_api=SimpleNamespace(list=no_task_io, raw=no_task_io),
        result_reader=no_task_io,
    )
    calls = []

    def native_tick(*, now, limit, job_ids):
        calls.append((now, limit, job_ids))
        return []

    # Only the external scheduler is replaced; owner, guards, tick and receipt IO are real.
    service.adapter = SimpleNamespace(
        service=SimpleNamespace(tick=native_tick),
        store=SimpleNamespace(recent_runs=lambda **_options: []),
        jobs=lambda: [],
    )
    monkeypatch.setattr("psutil.virtual_memory", lambda: SimpleNamespace(available=2**40))
    monkeypatch.setattr("psutil.disk_usage", lambda _path: SimpleNamespace(free=2**40))
    service.stop_event = Event(ctx.clock)
    return service, calls


def read_service(ctx):
    data = json.loads((ctx.area / "status.json").read_text(encoding="utf-8"))
    process = SimpleNamespace(
        is_running=lambda: True, create_time=lambda: data["create_time"],
        cmdline=lambda: ["python", str(ctx.project / "system/tools/maintenance/scheduler_maintenance.py"),
                         "serve", "--config", str(ctx.cp), "--runtime-dir", str(ctx.area)],
    )
    return runtime.readonly_status(ctx.area, root=ctx.project, now=ctx.clock.now(),
                                   process_factory=lambda _pid: process)


def test_confirmed_lock_has_distinct_denial(context):
    context.project_locked = True
    with pytest.raises(PermissionError) as caught:
        context.guard(context.area / "status.json")
    assert type(caught.value).__name__ == "MaintenanceLockHeld"


@pytest.mark.parametrize("damage", ["incomplete", "missing_complete", "wrong_target",
                                   "unknown_twin", "wrong_exit", "invalid_locks"])
def test_uncertain_scan_never_becomes_confirmed_lock(context, damage):
    context.project_locked = True

    def alter(target, code, fields):
        if target != context.project:
            return code, fields
        if damage == "incomplete":
            fields["descendants_complete"] = False
        elif damage == "missing_complete":
            fields.pop("descendants_complete")
        elif damage == "wrong_target":
            fields["checked"] = str(context.local)
        elif damage == "unknown_twin":
            fields["twin_status"] = "error"
        elif damage == "wrong_exit":
            code = 2
        elif damage == "invalid_locks":
            fields["locks"] = ["not-a-native-lock-record"]
        return code, fields

    context.alter = alter
    with pytest.raises(PermissionError) as caught:
        context.guard(context.area / "status.json")
    assert type(caught.value).__name__ != "MaintenanceLockHeld"


def test_incomplete_clear_scan_is_not_permission(context):
    context.alter = lambda target, code, fields: (
        code, {**fields, "descendants_complete": False} if target == context.project else fields)
    with pytest.raises(PermissionError):
        context.guard(context.area / "status.json")


def test_unknown_later_root_overrides_earlier_confirmed_lock(context):
    context.project_locked = True
    context.alter = lambda target, code, fields: (
        code, {**fields, "descendants_complete": False} if target == context.local else fields)
    with pytest.raises(PermissionError) as caught:
        context.guard(context.area / "status.json")
    assert type(caught.value).__name__ != "MaintenanceLockHeld"
    assert context.local in context.scans


def test_proven_pointer_does_not_hide_scanner_failure(context):
    context.alter = lambda target, code, fields: (2 if target == context.twin else code, fields)
    with pytest.raises(PermissionError):
        context.guard(context.area / "status.json")


def test_wait_then_release_keeps_local_owner_and_resumes_work(context, monkeypatch):
    context.project_locked = True
    service, calls = service_for(context, monkeypatch)
    observed = []

    def release(event):
        observed.append(read_service(context))
        assert calls == []
        with pytest.raises(OSError):
            with runtime.process_owner(service.owner_path, service.runtime_guard):
                pytest.fail("Second owner acquired during project wait")
        context.project_locked = False

    service.stop_event.callback = release
    service.serve(max_ticks=1)
    assert len(service.stop_event.waits) == 1
    assert observed[0]["state"] == "waiting_for_lock"
    assert observed[0]["running"] is True
    assert observed[0]["semantic_review_completed"] is False
    assert len(calls) == 1
    assert not (context.local / "scheduler.db").exists()
    assert read_service(context)["state"] == "stopped"


def test_stop_during_wait_never_starts_a_job(context, monkeypatch):
    context.project_locked = True
    service, calls = service_for(context, monkeypatch)
    observed = []

    def stop(event):
        observed.append(read_service(context))
        event.set()

    service.stop_event.callback = stop
    service.serve()
    assert observed[0]["state"] == "waiting_for_lock"
    assert len(service.stop_event.waits) == 1
    assert calls == []
    assert read_service(context)["state"] == "stopped"


def test_lock_wait_budget_does_not_run_or_spin_forever(context, monkeypatch):
    context.project_locked = True
    service, calls = service_for(context, monkeypatch)
    monkeypatch.setattr(runtime, "LOCK_WAIT_BUDGET_SECONDS", 25, raising=False)
    with pytest.raises(RuntimeError, match="maintenance_lock_wait_timeout"):
        service.serve()
    assert 0 < sum(service.stop_event.waits) <= 25
    assert calls == []
    assert read_service(context)["state"] == "stopped"


def test_unknown_after_wait_aborts_without_job(context, monkeypatch):
    context.project_locked = True
    service, calls = service_for(context, monkeypatch)

    def unknown(event):
        context.alter = lambda target, code, fields: (
            code, {**fields, "descendants_complete": False}
            if target == context.project else fields)

    service.stop_event.callback = unknown
    with pytest.raises(PermissionError) as caught:
        service.serve()
    assert type(caught.value).__name__ != "MaintenanceLockHeld"
    assert len(service.stop_event.waits) == 1
    assert calls == []


def test_locked_runtime_does_not_write_owner_or_status(context, monkeypatch):
    context.runtime_locked = True
    service, calls = service_for(context, monkeypatch)
    service.stop_event.callback = lambda event: event.set()
    service.serve()
    assert len(service.stop_event.waits) == 1
    assert calls == []
    assert not (context.area / "owner.lock").exists()
    assert not (context.area / "status.json").exists()
    assert not (context.area / "status.tmp").exists()


def test_runtime_diagnostic_authority_cannot_write_scheduler(context, monkeypatch):
    service, _calls = service_for(context, monkeypatch)
    with pytest.raises(PermissionError):
        service.runtime_guard(context.local / "scheduler.db")
    assert not (context.local / "scheduler.db").exists()


def test_unknown_runtime_scan_aborts_before_owner(context, monkeypatch):
    service, calls = service_for(context, monkeypatch)
    context.alter = lambda target, code, fields: (
        code, {**fields, "descendants_complete": False}
        if target == context.area else fields)
    with pytest.raises(PermissionError):
        service.serve()
    assert service.stop_event.waits == []
    assert calls == []
    assert not (context.area / "owner.lock").exists()


def test_archived_native_task_does_not_hide_live_maintenance(context):
    data = {
        "schema": "bach.maintenance-status.v1",
        "service": "bach-docs-maintenance",
        "pid": 123,
        "root_id": hashlib.sha256(str(context.project.resolve()).encode()).hexdigest(),
        "config_hash": hashlib.sha256(context.cp.read_bytes()).hexdigest(),
        "create_time": 10.0, "generation": "a" * 32, "poll_seconds": 60,
        "observed_at": NOW.isoformat(), "provider": "ellmos-scheduler", "state": "running",
        "documentation": {"routines": {"roadmap_review": {
            "task_id": 2225, "task_status": "archived", "result_accepted": False,
            "result_id": None, "last_review_success": None, "last_repair_success": None,
        }}},
    }
    (context.area / "status.json").write_text(json.dumps(data), encoding="utf-8")
    observed = read_service(context)
    assert observed["running"] is True
    item = observed["documentation"]["routines"]["roadmap_review"]
    assert item["task_status"] == "archived"
    assert item["result_accepted"] is False
    assert item["last_review_success"] is None


def test_lock_arriving_after_start_waits_before_next_job(context, monkeypatch):
    service, calls = service_for(context, monkeypatch)
    states = []

    def advance(event):
        observed = read_service(context)
        states.append(observed["state"])
        if observed["state"] == "running":
            assert len(calls) == 1
            context.project_locked = True
        else:
            assert observed["state"] == "waiting_for_lock"
            assert len(calls) == 1
            context.project_locked = False

    service.stop_event.callback = advance
    service.serve(max_ticks=2)
    assert states == ["running", "waiting_for_lock"]
    assert len(calls) == 2


def test_restart_during_project_lock_has_new_owner_and_resumes(context, monkeypatch):
    context.project_locked = True
    first, first_calls = service_for(context, monkeypatch)
    first.stop_event.callback = lambda event: event.set()
    first.serve()
    assert first_calls == []
    second, second_calls = service_for(context, monkeypatch)
    observations = []

    def release(event):
        observations.append(read_service(context))
        context.project_locked = False

    second.stop_event.callback = release
    second.serve(max_ticks=1)
    assert observations[0]["state"] == "waiting_for_lock"
    assert observations[0]["generation"] != first.generation
    assert observations[0]["generation"] == second.generation
    assert len(second_calls) == 1


@pytest.mark.parametrize("name", ["documentation.json", "failure.json", "config.json",
                                  "worker-binding.ack.json", "status.json.other"])
def test_local_diagnostic_guard_never_authorizes_other_runtime_files(
    context, monkeypatch, name
):
    service, _calls = service_for(context, monkeypatch)
    before = sorted(p.name for p in context.area.iterdir())
    with pytest.raises(PermissionError):
        service.runtime_guard(context.area / name)
    assert sorted(p.name for p in context.area.iterdir()) == before


def test_local_status_symlink_is_rejected(context, monkeypatch):
    service, _calls = service_for(context, monkeypatch)
    outside = context.local / "private.txt"
    outside.write_text("unchanged", encoding="utf-8")
    (context.area / "status.json").symlink_to(outside)
    with pytest.raises(PermissionError):
        service.runtime_guard(context.area / "status.json")
    assert outside.read_text(encoding="utf-8") == "unchanged"


def test_unknown_task_status_remains_unverified(context):
    data = {
        "schema": "bach.maintenance-status.v1", "service": "bach-docs-maintenance",
        "pid": 123, "root_id": hashlib.sha256(str(context.project.resolve()).encode()).hexdigest(),
        "config_hash": hashlib.sha256(context.cp.read_bytes()).hexdigest(),
        "create_time": 10.0, "generation": "a" * 32, "poll_seconds": 60,
        "observed_at": NOW.isoformat(), "provider": "ellmos-scheduler", "state": "running",
        "documentation": {"routines": {"roadmap_review": {
            "task_id": 2225, "task_status": "unrecognized-private-value",
            "result_accepted": False,
        }}},
    }
    (context.area / "status.json").write_text(json.dumps(data), encoding="utf-8")
    observed = read_service(context)
    assert observed["running"] is False
    assert observed["reason"] == "maintenance_receipt_unverified"
    assert "unrecognized-private-value" not in json.dumps(observed)


@pytest.mark.parametrize("kind", ["ordinary", "hardlink"])
def test_status_never_overwrites_existing_temporary(context, monkeypatch, kind):
    import os

    service, _calls = service_for(context, monkeypatch)
    status = context.area / "status.json"
    status.write_text("previous status", encoding="utf-8")
    victim = context.local / "protected-data.txt"
    victim.write_text("unmodified external data", encoding="utf-8")
    monkeypatch.setattr(runtime, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    temporary = status.with_name("status." + "a" * 32 + ".tmp")
    if kind == "hardlink":
        os.link(victim, temporary)
    else:
        temporary.write_text("unmodified temporary", encoding="utf-8")
    before = temporary.read_bytes()
    with pytest.raises(OSError):
        runtime._write_status(status, {"state": "waiting_for_lock"}, service.runtime_guard)
    assert temporary.read_bytes() == before
    assert victim.read_text(encoding="utf-8") == "unmodified external data"
    assert status.read_text(encoding="utf-8") == "previous status"


def test_status_replacement_preserves_external_hardlink_target(context, monkeypatch):
    import os

    service, _calls = service_for(context, monkeypatch)
    status = context.area / "status.json"
    victim = context.local / "protected-data.txt"
    victim.write_text("unmodified external data", encoding="utf-8")
    os.link(victim, status)
    runtime._write_status(status, {"state": "waiting_for_lock"}, service.runtime_guard)
    assert json.loads(status.read_text(encoding="utf-8"))["state"] == "waiting_for_lock"
    assert victim.read_text(encoding="utf-8") == "unmodified external data"
    assert status.stat().st_ino != victim.stat().st_ino


def test_status_rejects_temporary_replacement_before_publish(context, monkeypatch):
    import os

    service, _calls = service_for(context, monkeypatch)
    status = context.area / "status.json"
    status.write_text("previous status", encoding="utf-8")
    monkeypatch.setattr(runtime, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    temporary = status.with_name("status." + "a" * 32 + ".tmp")
    victim = context.local / "protected-data.txt"
    victim.write_text("unmodified external data", encoding="utf-8")
    visits = []

    def guard(target):
        service.runtime_guard(target)
        visits.append(target)
        if target == status and visits.count(status) == 2:
            temporary.unlink()
            os.link(victim, temporary)

    with pytest.raises(PermissionError):
        runtime._write_status(status, {"state": "waiting_for_lock"}, guard)
    assert status.read_text(encoding="utf-8") == "previous status"
    assert temporary.read_bytes() == victim.read_bytes() == b"unmodified external data"


def test_owner_rejects_hardlink_without_entering_or_modifying(context, monkeypatch):
    import os

    service, _calls = service_for(context, monkeypatch)
    victim = context.local / "protected-data.txt"
    victim.write_bytes(b"unmodified external data")
    os.link(victim, service.owner_path)
    with pytest.raises(PermissionError):
        with runtime.process_owner(service.owner_path, service.runtime_guard):
            pytest.fail("Hardlinked owner file was accepted")
    assert victim.read_bytes() == service.owner_path.read_bytes() == b"unmodified external data"


def test_owner_reuses_existing_regular_single_link_file(context, monkeypatch):
    service, _calls = service_for(context, monkeypatch)
    service.owner_path.write_bytes(b"0")
    original = service.owner_path.stat()
    for _ in range(2):
        with runtime.process_owner(service.owner_path, service.runtime_guard):
            assert service.owner_path.read_bytes() == b"0"
            assert service.owner_path.stat().st_ino == original.st_ino


def test_lock_release_at_wait_deadline_cannot_dispatch(context, monkeypatch):
    context.project_locked = True
    service, calls = service_for(context, monkeypatch)
    monkeypatch.setattr(runtime, "LOCK_WAIT_BUDGET_SECONDS", 10)
    service.stop_event.callback = lambda _event: setattr(context, "project_locked", False)
    with pytest.raises(runtime.MaintenanceLockWaitTimeout):
        service.serve(max_ticks=1)
    assert calls == []
    assert context.clock.elapsed == 10
    assert service.stop_event.waits == [10]
    assert read_service(context)["state"] == "stopped"


def test_initial_status_write_counts_towards_lock_wait_budget(context, monkeypatch):
    context.project_locked = True
    service, calls = service_for(context, monkeypatch)
    monkeypatch.setattr(runtime, "LOCK_WAIT_BUDGET_SECONDS", 10)
    original_write = runtime._write_status

    def slow_status(path, value, guard):
        if value["state"] == "waiting_for_lock":
            context.clock.elapsed += 9
        original_write(path, value, guard)

    monkeypatch.setattr(runtime, "_write_status", slow_status)
    with pytest.raises(runtime.MaintenanceLockWaitTimeout):
        service.serve()
    assert context.clock.elapsed == 10
    assert service.stop_event.waits == [1]
    assert calls == []


def test_old_crash_temporary_does_not_block_new_status(context, monkeypatch):
    service, _calls = service_for(context, monkeypatch)
    previous = [
        context.area / "status.tmp",
        context.area / ("status." + "b" * 32 + ".tmp"),
    ]
    for path in previous:
        path.write_bytes(b"preserve interrupted prior write")
    runtime._write_status(context.area / "status.json",
                          {"state": "waiting_for_lock"}, service.runtime_guard)
    assert json.loads((context.area / "status.json").read_text())["state"] == "waiting_for_lock"
    assert all(path.read_bytes() == b"preserve interrupted prior write" for path in previous)
    assert sorted(p.name for p in context.area.glob("status.*.tmp")) == [previous[1].name]
