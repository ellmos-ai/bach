"""The documentation consumer opts in only its idempotent delta check."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from hub import scheduler_provider
from hub._services.docs.maintenance_runtime import MaintenanceRuntime, JOB_ID
from hub._services.docs.maintenance_recurring import ROUTINES
from ellmos_scheduler import SchedulerStore, JobPolicyConflict
from ellmos_scheduler.store import iso

ANCHOR = datetime(2026, 10, 29, 16, 22, 44, 714586, tzinfo=timezone.utc)
NOW = ANCHOR + timedelta(days=19, seconds=172)


@pytest.fixture
def service(tmp_path):
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps({
        "schema": "bach.maintenance-config.v1", "enabled": True,
        "interval_seconds": 300, "poll_seconds": 60,
        "min_available_mib": 512, "max_state_db_bytes": 67108864,
        "lock_tools_root": str(tmp_path), "protected_roots": [str(tmp_path)],
        "worker_binding": {},
    }))
    recurring = tmp_path / "system/hub/_services/recurring"
    recurring.mkdir(parents=True)
    recurring.joinpath("config.json").write_text(json.dumps({"recurring_tasks": {
        name: {"enabled": True, "interval_days": days, "target": "tasks",
               "last_run": ANCHOR.isoformat(), "task_text": "Existing " + name}
        for name, days in zip(ROUTINES, (14, 14, 60, 30))
    }}))
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("Preparation must not call the task authority")
    runtime = MaintenanceRuntime(
        tmp_path, tmp_path / "scheduler.db", tmp_path / "runtime", cp,
        task_api=SimpleNamespace(list=forbidden, raw=forbidden), result_reader=forbidden,
        guard=lambda _: None, clock=lambda: NOW,
    )
    runtime.task_calls = calls
    return runtime


def seed(service, **changes):
    store = SchedulerStore(service.state_db)
    store.init()
    options = {"now": ANCHOR, "next_due_at": ANCHOR, "lease_seconds": 180,
               "timeout_seconds": 60}
    options.update(changes)
    store.add_job(JOB_ID, {"kind": "interval", "seconds": 300}, "bach-docs",
                  {"schema": "bach.docs-delta-job.v1"}, **options)
    return store


def jobs(store):
    return {r["id"]: r for r in store.list_jobs()}


def test_new_runtime_coalesces_only_delta_and_keeps_all_routine_intervals(service):
    service._prepare()
    rows = jobs(service.adapter.store)
    assert rows[JOB_ID]["misfire_policy"] == "coalesce_latest"
    for name, days in zip(ROUTINES, (14, 14, 60, 30)):
        row = rows["bach.docs.routine." + name]
        assert row["misfire_policy"] == "replay"
        assert json.loads(row["schedule_json"]) == {"kind": "interval", "seconds": days * 86400}
        assert row["next_due_at"] == iso(ANCHOR + timedelta(days=days))
    assert service.adapter.store.recent_runs() == []
    assert service.task_calls == []


def test_existing_delta_migrates_with_cas_without_changing_due_or_history(service):
    store = seed(service)
    before = jobs(store)[JOB_ID]
    service._prepare()
    after = jobs(store)[JOB_ID]
    assert after["misfire_policy"] == "coalesce_latest"
    assert after["generation"] == before["generation"] + 1
    assert after["next_due_at"] == before["next_due_at"]
    assert store.recent_runs() == []
    # A second owner preparation neither re-migrates nor shifts the anchor.
    service._prepare()
    assert jobs(store)[JOB_ID] == after
    assert service.task_calls == []


@pytest.mark.parametrize("started", [False, True])
def test_existing_active_delta_blocks_migration_before_any_tick(service, started):
    store = seed(service)
    claim = store.claim_due("existing-owner", now=NOW)[0]
    if started:
        store.start_run(claim["run_id"], now=NOW)
    before = jobs(store)[JOB_ID]
    with pytest.raises(JobPolicyConflict, match="active_claim"):
        service._prepare()
    assert jobs(store)[JOB_ID] == before
    assert service.adapter is None
    assert len(store.recent_runs()) == 1
    assert service.task_calls == []


def test_claim_arriving_after_snapshot_is_rechecked_natively(service):
    store = seed(service)
    checks = []
    def guard(_):
        checks.append(True)
        if len(checks) == 2:  # After the job snapshot, immediately before the policy mutation.
            store.claim_due("racing-owner", now=NOW)
    service.guard = guard
    with pytest.raises(JobPolicyConflict, match="active_claim"):
        service._prepare()
    assert jobs(store)[JOB_ID]["misfire_policy"] == "replay"
    assert service.task_calls == []


def test_expired_delta_claim_retries_original_after_native_migration(service):
    store = seed(service)
    first = store.claim_due("previous-owner", now=ANCHOR)[0]
    service._prepare()
    assert store.recent_runs()[0]["status"] == "claimed"
    retry = service.adapter.store.claim_due("new-owner", now=NOW, limit=1, job_ids=[JOB_ID])[0]
    assert retry["scheduled_for"] == first["scheduled_for"]
    assert retry["attempt"] == 2
    assert retry["coalesced_count"] == 0
    assert service.task_calls == []


@pytest.mark.parametrize("capability", [None, "ellmos.scheduler.misfire-policy.v0"])
def test_missing_module_capability_fails_before_creating_or_migrating_store(tmp_path, monkeypatch, capability):
    db = tmp_path / "scheduler.db"
    factory_calls = []
    old_module = SimpleNamespace(
        MISFIRE_POLICY_SCHEMA=capability,
        create_bach_adapter=lambda *a, **k: factory_calls.append((a, k)),
    )
    monkeypatch.setattr(scheduler_provider, "load_external_scheduler", lambda: old_module)
    monkeypatch.setattr(scheduler_provider, "probe_scheduler_provider", lambda: SimpleNamespace(external=True))
    with pytest.raises(RuntimeError, match="scheduler_misfire_policy_unavailable"):
        scheduler_provider.create_documentation_scheduler(db, lambda *_: None, worker_id="isolated")
    assert factory_calls == [] and not db.exists()


def test_existing_incompatible_delta_cannot_be_silently_adopted(service):
    store = seed(service, timeout_seconds=70)
    before = jobs(store)[JOB_ID]
    with pytest.raises(RuntimeError, match="existing_maintenance_job_conflict"):
        service._prepare()
    assert jobs(store)[JOB_ID] == before and store.recent_runs() == []


def test_consumer_rejects_preexisting_coalescing_routine(service):
    store = seed(service)
    store.add_job("bach.docs.routine.help_forensic",
        {"kind": "interval", "seconds": 14 * 86400}, "bach-docs",
        {"schema": "bach.docs-routine-job.v1", "routine": "help_forensic"},
        now=ANCHOR, next_due_at=ANCHOR, timeout_seconds=60, misfire_policy="coalesce_latest")
    before = jobs(store)["bach.docs.routine.help_forensic"]
    with pytest.raises(RuntimeError, match="existing_maintenance_job_conflict"):
        service._prepare()
    assert jobs(store)["bach.docs.routine.help_forensic"] == before
    assert store.recent_runs() == [] and service.task_calls == []
