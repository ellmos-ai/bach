# SPDX-License-Identifier: MIT
"""Queue hints never grant a lease or authorize a model call."""
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from hub._services import task_lease_client
from system.tests.test_task_lease_client import mem_db, _insert_task
from system.tests.test_worker_execution_evidence import worker_context
from system.tests.test_worker_result_review import review_world


@pytest.fixture
def private_authority(tmp_path, monkeypatch):
    home = tmp_path / "home"
    local = home / ".bach"
    local.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "lead"})
    path = local / "bach.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE changes (value TEXT)")
    factory = lambda: task_lease_client.TaskLeaseClient(db_path=path)
    return path, factory


def change_in_process(path):
    result = subprocess.run([sys.executable, "-c",
        "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
        "c.execute('INSERT INTO changes VALUES (?)', ('new',)); c.commit(); c.close()",
        str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_other_process_commit_is_seen_even_when_it_races_preflight(private_authority):
    from hub._services.chat.worker_queue_preflight import QueueChangeObserver
    path, factory = private_authority
    with QueueChangeObserver(factory) as observer:
        before_preflight = observer.revision()
        change_in_process(path)  # Commit while the independent preflight is reading.
        after = observer.revision()
        assert before_preflight != after
        assert observer.wait(threading.Event(), before_preflight, timeout=.2) is False
        assert observer.last_reason == "change_hint"
        assert observer._connection.in_transaction is False
        with pytest.raises(sqlite3.OperationalError):
            observer._connection.execute("INSERT INTO changes VALUES ('forbidden')")


def test_observer_reopens_replaced_database_and_authority(private_authority, tmp_path):
    from hub._services.chat.worker_queue_preflight import QueueChangeObserver
    path, factory = private_authority
    holder = [factory()]
    with QueueChangeObserver(lambda: holder[0]) as observer:
        first = observer.revision()
        connection = observer._connection
        replacement = path.with_suffix(".replacement")
        with sqlite3.connect(replacement) as conn:
            conn.execute("CREATE TABLE changes (value TEXT)")
        replacement.replace(path)
        second = observer.revision()
        assert first != second
        assert observer._connection is not connection
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        holder[0] = task_lease_client.TaskLeaseClient(lead_url="http://example.invalid")
        assert observer.revision() != second
        assert observer._connection is None
        holder[0] = factory()
        assert observer.revision() != second
        assert observer._connection is not None


def test_registry_change_and_connection_loss_are_hints_not_permissions(private_authority):
    from hub._services.chat.worker_queue_preflight import QueueChangeObserver
    path, factory = private_authority
    with QueueChangeObserver(factory) as observer:
        initial = observer.revision()
        (path.parent / "worker_repo_registry.v1.json").write_text("{}")
        assert observer.revision() != initial
        observer._connection.close()
        assert observer.revision() != initial
        assert observer._connection is None
        assert observer.revision() is not None
    assert observer._connection is None


def test_hint_bursts_are_coalesced_and_periodic_fallback_remains(private_authority):
    from hub._services.chat.worker_queue_preflight import QueueChangeObserver
    path, factory = private_authority
    now = [0.]
    class Stop:
        def is_set(self): return False
        def wait(self, delay):
            now[0] += delay
            return False
    with QueueChangeObserver(factory, clock=lambda: now[0],
                             probe_seconds=.1, minimum_recheck_seconds=1.) as observer:
        first = observer.revision()
        change_in_process(path)
        assert observer.wait(Stop(), first, timeout=10) is False
        assert observer.last_reason == "change_hint"
        second = observer.revision()
        change_in_process(path)
        assert observer.wait(Stop(), second, timeout=10) is False
        assert now[0] >= 1.
        same = observer.revision()
        start = now[0]
        assert observer.wait(Stop(), same, timeout=10) is False
        assert now[0] - start >= 10.
        assert observer.last_reason == "periodic"
    assert observer._connection is None


def test_observer_failure_uses_periodic_wait_and_stop_interrupts(tmp_path):
    from hub._services.chat.worker_queue_preflight import QueueChangeObserver
    now = [0.]
    def unavailable(): raise RuntimeError("authority unavailable")
    class Stop:
        def is_set(self): return False
        def wait(self, delay):
            now[0] += delay
            return False
    with QueueChangeObserver(unavailable, clock=lambda: now[0]) as observer:
        before = observer.revision()
        observer.wait(Stop(), before, timeout=10)
        assert now[0] >= 10 and observer.last_reason == "periodic"
        stopped = threading.Event()
        stopped.set()
        assert observer.wait(stopped, before, timeout=10) is True


@pytest.fixture
def candidates(private_authority, monkeypatch):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.worker_policy_settings import CONTRACT, TASK_SCHEMA
    class Client:
        mode = "local"
        def __init__(self):
            self.tasks = []
            self.reviews = []
            self.reasons = {}
            self.route_allowed = False
            self.require_assigned = False
            self.policy_reads = []
        def task_candidates(self, *, limit, offset, _read_only=False):
            assert _read_only is True
            return {"tasks": self.tasks[offset:offset+limit], "has_more": offset+limit < len(self.tasks),
                    "offset": offset, "total": len(self.tasks)}
        def _review_candidates(self, *, limit, offset):
            return {"tasks": self.reviews[offset:offset+limit], "has_more": offset+limit < len(self.reviews),
                    "offset": offset}
        def _task_policy_snapshot(self, tid):
            self.policy_reads.append(tid)
            task = next(t for t in self.tasks+self.reviews if t["id"] == tid)
            return {"schema": TASK_SCHEMA, "availability": "available", "task_id": tid,
                    "task_version": task["task_version"], "configuration_version": "c"*64,
                    "effective": {"contract_version": CONTRACT,
                                  "require_assigned_slot": self.require_assigned, "enforce_model_binding": False}}
        def _preflight_task_readiness(self, tid, *, task_version, worker_id, review=False):
            return self.reasons.get(tid)
        def _review_eligible(self, tid, **kwargs): return self.route_allowed
        def acquire(self, *args, **kwargs): raise AssertionError("preflight acquired")
        def _issue_review_grant(self, *args, **kwargs): raise AssertionError("preflight issued a grant")
    return Client()


def task(tid, **extra):
    return {"id": tid, "task_version": f"{tid:064x}", "status": "pending",
            "title": "test", "assigned_to": "OLLAMA", "assigned_slot": None,
            "required_model": None, "category": "code", **extra}


def preflight(client, **extra):
    from hub._services.chat.worker_queue_preflight import preflight_worker_queue
    slot = {"id": "buddha_always_on", "backend": "ollama", "model": "test-model",
            "allowed_repositories": [], "pickup_filter": {"enabled": False}}
    return preflight_worker_queue(client, slot, worker_id="worker@test", host="test",
        generation="test-generation", is_current=lambda: True, stop_event=threading.Event(),
        review_route={"backend_id": "ollama"}, review_requested_model="test-model", **extra)


def test_preflight_empty_queue_and_all_pages_preserve_deferrals(candidates):
    assert preflight(candidates).eligible is False
    assert preflight(candidates).scan_complete is True
    candidates.tasks = [task(i) for i in range(1, 102)]
    skipped = {t["id"]: t["task_version"] for t in candidates.tasks[:-1]}
    result = preflight(candidates, deferred_versions=skipped)
    assert result.eligible is True and result.task_id == 101
    assert 101 in candidates.policy_reads
    assert result.scan_complete is False


def test_preflight_reads_per_task_policy_and_never_uses_unknown_policy(candidates):
    candidates.tasks = [task(1)]
    assert preflight(candidates).eligible is True
    candidates.require_assigned = True
    result = preflight(candidates)
    assert result.eligible is False
    assert result.rejected_counts == {"explicit_slot_required": 1}
    candidates._task_policy_snapshot = lambda tid: None
    assert preflight(candidates).rejected_counts == {"selection_policy_unavailable": 1}


@pytest.mark.parametrize("reason", ["held", "dependencies_unfinished", "unresolved_tool_trace",
                                    "creator_priority", "stale_task_version"])
def test_preflight_rechecks_native_readiness_without_claiming(candidates, reason):
    candidates.tasks = [task(1)]
    candidates.reasons[1] = reason
    result = preflight(candidates)
    assert result.eligible is False and result.rejected_counts == {reason: 1}


def test_review_only_queue_requires_native_grant_free_eligibility(candidates):
    candidates.reviews = [task(2)]
    assert preflight(candidates).eligible is False
    candidates.route_allowed = True
    result = preflight(candidates)
    assert result.eligible is True and result.task_id == 2


def test_exhausted_preflight_releases_only_expired_preparation_skips(candidates):
    from hub._services.chat.worker_scope_deferrals import ScopePreparationDeferrals
    now = [0.]
    deferrals = ScopePreparationDeferrals(clock=lambda: now[0], retry_seconds=2)
    candidates.tasks = [task(1)]
    assert deferrals.defer(1, task(1)["task_version"], tool_dispatch_count=0)
    ordinary = {9: "a"*64}
    result = preflight(candidates, deferred_versions=deferrals.combined(ordinary))
    assert deferrals.after_exhausted_preflight(result) == ()
    now[0] = 3.
    assert deferrals.after_exhausted_preflight(result) == (1,)
    assert deferrals.combined(ordinary) == ordinary
    assert deferrals.after_exhausted_preflight(preflight(candidates)) == ()


def test_native_readiness_is_read_only_and_checks_lease_dependencies(mem_db, monkeypatch):
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    client = task_lease_client.TaskLeaseClient(conn=mem_db)
    dep = _insert_task(mem_db, "dependency")
    tid = _insert_task(mem_db, "work")
    mem_db.execute("UPDATE tasks SET depends_on=? WHERE id=?", (str(dep), tid))
    mem_db.commit()
    version = client.task_snapshot(tid)["task_version"]
    before = mem_db.total_changes
    assert client._preflight_task_readiness(tid, task_version=version, worker_id="worker@test") == "dependencies_unfinished"
    assert mem_db.total_changes == before and mem_db.in_transaction is False
    mem_db.execute("UPDATE tasks SET status='done' WHERE id=?", (dep,))
    mem_db.commit()
    assert client._preflight_task_readiness(tid, task_version=version, worker_id="worker@test") is None
    client.acquire(tid, worker_id="other@test", host="test")
    assert client._preflight_task_readiness(tid, task_version=version, worker_id="worker@test") == "held"


def test_preflight_missing_repository_binding_is_visible(candidates, private_authority):
    path, _factory = private_authority
    (path.parent / "worker_repo_registry.v1.json").write_text("{}")
    candidates.tasks = [task(1)]
    result = preflight(candidates)
    assert result.eligible is False
    assert result.rejected_counts == {"repository_unverified": 1}


def test_remote_preflight_reads_its_http_authority_not_a_local_projection(monkeypatch):
    from types import SimpleNamespace
    client = task_lease_client.TaskLeaseClient(lead_url="http://example.invalid")
    snapshots = {1: task(1, depends_on="2"), 2: task(2, status="done")}
    monkeypatch.setattr(client, "task_snapshot", lambda tid: snapshots[tid])
    monkeypatch.setattr(client, "read",
                        lambda tid: SimpleNamespace(task_version=snapshots[tid]["task_version"], leased=False))
    assert client._local_observation_path() is None
    assert client._preflight_task_readiness(1, task_version=task(1)["task_version"], worker_id="worker@test") is None
    snapshots[2]["status"] = "pending"
    assert client._preflight_task_readiness(1, task_version=task(1)["task_version"], worker_id="worker@test") == "dependencies_unfinished"


def test_real_private_review_eligibility_does_not_construct_or_publish_grant(review_world, monkeypatch):
    from hub._services import worker_result_review as review
    from system.tests.test_worker_result_review import (
        _prepare, _paths, REVIEW_SLOT, REVIEW_GENERATION, REVIEW_ROUTE, REVIEW_MODEL, T0)
    world = review_world
    prepared = _prepare(world)
    before = world["conn"].total_changes
    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only eligibility must not construct a ReviewGrant")
    monkeypatch.setattr(review, "ReviewGrant", forbidden)
    arguments = dict(worker_id="review-worker@HOST", host="HOST", generation=REVIEW_GENERATION,
        slot_id=REVIEW_SLOT, route={"backend_id": "ollama", "route_sha256": REVIEW_ROUTE},
        requested_model=REVIEW_MODEL, is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0, **_paths(world))
    assert review.review_eligible(world["conn"], prepared["review_task_id"], **arguments) is True
    assert world["conn"].total_changes == before and world["conn"].in_transaction is False
    world["conn"].execute("UPDATE tasks SET status='done' WHERE id=?", (world["task_id"],))
    world["conn"].commit()
    assert review.review_eligible(world["conn"], prepared["review_task_id"], **arguments) is False


def test_repeated_database_open_failure_does_not_become_an_event_storm(private_authority, monkeypatch):
    from hub._services.chat.worker_queue_preflight import QueueChangeObserver
    _path, factory = private_authority
    now = [0.]
    class Stop:
        def is_set(self): return False
        def wait(self, delay):
            now[0] += delay
            return False
    with QueueChangeObserver(factory, clock=lambda: now[0]) as observer:
        observer.revision()
        observer.close()
        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("database unavailable")
        monkeypatch.setattr(sqlite3, "connect", fail)
        unavailable = observer.revision()
        assert observer.revision() == unavailable
        observer.wait(Stop(), unavailable, timeout=10)
        assert now[0] >= 10 and observer.last_reason == "periodic"


def test_one_unverifiable_review_does_not_hide_a_later_eligible_review(candidates):
    candidates.reviews = [task(1), task(2)]
    def eligibility(tid, **kwargs):
        if tid == 1:
            raise RuntimeError("private target unavailable")
        return True
    candidates._review_eligible = eligibility
    result = preflight(candidates)
    assert result.eligible is True and result.task_id == 2
    assert result.rejected_counts == {"ownership": 1}
