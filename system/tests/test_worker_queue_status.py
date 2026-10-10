"""Selector observations use the isolated real authority, never a second queue."""
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.chat.worker_queue_status import project_queue_status
from hub._services.task_lease_client import (
    LeaseConnectionError,
    LeaseDeniedError,
    TaskLeaseClient,
)

from system.tests.test_task_lease_client import _init_db
from system.tests.test_task_lease_client import _insert_task as _base_insert_task
from system.tests.test_task_lease_client_review import T0


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    yield conn
    conn.close()


def _insert_task(conn):
    tid = _base_insert_task(conn)
    conn.execute("UPDATE tasks SET assigned_to='BACH' WHERE id=?", (tid,))
    conn.commit()
    return tid


def select(client, reports, slot=None, **changes):
    args = {"worker_id": "physical-worker@HOST", "host": "HOST", "generation": "generation-1",
            "is_current": lambda: True, "stop_event": threading.Event(), "clock": lambda: T0}
    args.update(changes)
    return WorkerLeaseBinding.acquire_next(client, slot or {"id": "our-slot"},
                                          observe_queue=reports.append, **args)


def test_empty_queue_is_observed_without_acquisition(mem_db):
    reports = []
    assert select(TaskLeaseClient(conn=mem_db), reports) is None
    report, = reports
    assert report["reason"] == "empty_queue" and report["scan_complete"]
    assert report["candidate_count"] == report["attempted_count"] == 0
    assert report["scanned_pages"] == 1
    assert report["rejected_counts"] == {}


@pytest.mark.parametrize("fields,slot,reason", [
    ({"assigned_slot": "elsewhere"}, {"id": "our-slot"}, "slot_binding"),
    ({"required_model": "paid-model"}, {"id": "our-slot", "model": "openrouter/free"}, "model_binding"),
    ({}, {"id": "our-slot", "require_assigned_slot": True}, "explicit_slot_required"),
    ({"assigned_to": "user"}, {"id": "our-slot"}, "ownership"),
    ({"category": "GUI"}, {"id": "our-slot", "pickup_filter": {"enabled": True, "categories": ["WORKER"]}}, "pickup_filter"),
    ({"assigned_slot": "our-slot", "tags": "waiting"},
     {"id": "our-slot", "pickup_filter": {"enabled": True, "exclude_tags": ["waiting"]}}, "pickup_filter"),
])
def test_selection_reasons_share_actual_constraints(mem_db, fields, slot, reason):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    # Isolated fixture schema; production writes always use the native API.
    for key, value in fields.items():
        columns = {row[1] for row in mem_db.execute("PRAGMA table_info(tasks)")}
        if key not in columns:
            mem_db.execute(f"ALTER TABLE tasks ADD COLUMN {key} TEXT")
        mem_db.execute(f"UPDATE tasks SET {key}=? WHERE id=?", (value, tid))
    mem_db.commit()
    reports = []
    assert select(client, reports, slot) is None
    report, = reports
    assert report["reason"] == "selection_excluded"
    assert report["rejected_counts"] == {reason: 1}
    assert report["attempted_count"] == 0
    assert report["last_candidate_task_id"] == tid
    assert not client.read(tid).leased


def test_explicit_assignment_and_real_ack_are_separate_from_generic_filters(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    mem_db.execute("UPDATE tasks SET assigned_slot=?,required_model=? WHERE id=?",
                   ("our-slot", "openrouter/free", tid))
    mem_db.commit()
    reports = []
    binding = select(client, reports, {"id": "our-slot", "model": "openrouter/free",
        "pickup_filter": {"enabled": True, "categories": ["WORKER"], "priorities": ["P1"]}})
    assert binding.task_id == tid
    report, = reports
    assert report["state"] == "acquired" and report["selected_task_id"] == tid
    assert report["attempted_count"] == report["matched_count"] == report["candidate_count"] == 1
    assert not report["scan_complete"]  # Selection stops at the confirmed acquisition.
    assert binding._ack.lease_id not in str(report)
    assert "task_version" not in report and "title" not in report


def test_held_task_is_reported_from_authoritative_acquire(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    holder = client.acquire(tid, worker_id="foreign@HOST", host="HOST", now=T0)
    reports = []
    assert select(client, reports) is None
    report, = reports
    assert report["reason"] == "acquire_denied"
    assert report["rejected_counts"] == {"held": 1}
    assert holder.lease_id not in str(report) and "foreign" not in str(report)
    assert client.read(tid, lease_id=holder.lease_id, now=T0).own


def test_deferred_version_is_not_reacquired(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    before = client.task_snapshot(tid)
    reports = []
    assert select(client, reports, deferred_versions={tid: before["task_version"]}) is None
    assert reports[0]["rejected_counts"] == {"deferred_version": 1}
    assert reports[0]["attempted_count"] == 0


def test_explicit_foreign_lease_is_diagnosed_without_changing_exception_or_holder(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    holder = client.acquire(tid, worker_id="foreign@HOST", host="HOST", now=T0)
    reports = []
    with pytest.raises(LeaseDeniedError) as error:
        select(client, reports, {"id": "our-slot", "task_id": tid})
    assert error.value.reason == "held"
    report, = reports
    assert report["reason"] == "acquire_denied" and report["rejected_counts"] == {"held": 1}
    assert not report["scan_complete"]
    assert client.read(tid, lease_id=holder.lease_id, now=T0).own
    assert holder.lease_id not in str(report)


@pytest.mark.parametrize("explicit", [True, False])
def test_native_no_grant_conflict_is_diagnosed_but_still_stops_selection(mem_db, monkeypatch, explicit):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    def deny(*args, **kwargs):
        raise LeaseDeniedError(tid, "conflict", {"task_id": tid, "reason": "conflict"})
    monkeypatch.setattr(client, "acquire", deny)
    slot = {"id": "our-slot", **({"task_id": tid} if explicit else {})}
    reports = []
    with pytest.raises(LeaseDeniedError) as error:
        select(client, reports, slot)
    assert error.value.reason == "conflict"
    assert reports[0]["reason"] == "acquire_denied"
    assert reports[0]["rejected_counts"] == {"conflict": 1}
    assert not reports[0]["scan_complete"] and not client.read(tid).leased


def test_all_candidate_pages_are_counted_without_claiming_foreign_scope(mem_db):
    mem_db.executemany("INSERT INTO tasks(title,status,assigned_to) VALUES (?,'pending','user')",
                      [(f"Private task {i}",) for i in range(205)])
    mem_db.commit()
    reports = []
    assert select(TaskLeaseClient(conn=mem_db), reports) is None
    report, = reports
    assert report["candidate_count"] == 205 and report["scanned_pages"] == 3
    assert report["rejected_counts"] == {"ownership": 205}
    assert report["scan_complete"] and report["attempted_count"] == 0
    assert "Private task" not in str(report)


def test_open_dependency_is_not_reported_as_a_successful_claim(mem_db):
    dependency, child = _insert_task(mem_db), _insert_task(mem_db)
    mem_db.execute("UPDATE tasks SET assigned_to='user' WHERE id=?", (dependency,))
    mem_db.execute("UPDATE tasks SET depends_on=? WHERE id=?", (str(dependency), child))
    mem_db.commit()
    reports = []
    assert select(TaskLeaseClient(conn=mem_db), reports) is None
    assert reports[0]["rejected_counts"] == {"not_claimable": 1, "ownership": 1}
    assert reports[0]["matched_count"] == reports[0]["attempted_count"] == 1
    assert reports[0]["reason"] == "acquire_denied"


def test_fresh_content_change_is_rechecked_before_acquire(mem_db, monkeypatch):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    original_snapshot = client.task_snapshot
    def fresh_snapshot(task_id):
        mem_db.execute("UPDATE tasks SET assigned_to='user' WHERE id=?", (task_id,))
        mem_db.commit()
        return original_snapshot(task_id)
    monkeypatch.setattr(client, "task_snapshot", fresh_snapshot)
    reports = []
    assert select(client, reports) is None
    assert reports[0]["rejected_counts"] == {"changed_selection": 1}
    assert not client.read(tid).leased


def test_observation_failure_cannot_lose_acquired_lease(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)
    def bad_observer(_):
        raise RuntimeError("observer failure")
    binding = WorkerLeaseBinding.acquire_next(client, {"id": "our-slot"}, observe_queue=bad_observer,
        worker_id="worker@HOST", host="HOST", generation="generation-1", is_current=lambda: True,
        stop_event=threading.Event(), clock=lambda: T0)
    assert binding.task_id == tid and client.read(tid, lease_id=binding._ack.lease_id, now=T0).own


def test_read_failure_is_error_not_empty_queue(mem_db, monkeypatch):
    client = TaskLeaseClient(conn=mem_db)
    monkeypatch.setattr(client, "task_candidates", lambda **_: (_ for _ in ()).throw(LeaseConnectionError("secret")))
    reports = []
    with pytest.raises(LeaseConnectionError):
        select(client, reports)
    assert reports[0]["state"] == "error" and reports[0]["reason"] == "selection_error"
    assert not reports[0]["scan_complete"] and "secret" not in str(reports)


@pytest.fixture
def waiting_report(mem_db):
    reports = []
    select(TaskLeaseClient(conn=mem_db), reports)
    return reports[0]


@pytest.mark.parametrize("key,value", [
    ("schema", "fake"), ("reason", []), ("state", {}), ("authority_mode", []),
    ("candidate_count", True), ("attempted_count", -1), ("matched_count", 1),
    ("observed_at", "not-time"), ("observed_at", "2026-10-10T03:00:00"),
    ("scan_complete", "true"), ("rejected_counts", {"unknown": 1}),
    ("rejected_counts", {"held": True}), ("rejected_counts", {"held": 1}),
    ("selected_task_id", 1), ("last_candidate_task_id", False),
    ("reason", "task_acquired"), ("reason", "selection_error"),
    ("reason", "acquire_denied"), ("state", "acquired"), ("state", "error"),
    ("scanned_pages", 0), ("scanned_pages", 2),
])
def test_malformed_reports_are_not_projected(waiting_report, key, value):
    assert project_queue_status({**waiting_report, key: value}) is None


def test_acquired_with_empty_queue_reason_is_not_projected(waiting_report):
    impossible = {**waiting_report, "state": "acquired", "reason": "empty_queue",
                  "selected_task_id": 42, "candidate_count": 1, "matched_count": 1,
                  "attempted_count": 1, "scan_complete": False}
    assert project_queue_status(impossible) is None


@pytest.mark.parametrize("state,reason,candidates,matched,attempted,rejected", [
    ("waiting", "selection_excluded", 1, 0, 0, {}),
    ("waiting", "acquire_denied", 1, 1, 1, {}),
    ("waiting", "acquire_denied", 1, 1, 1, {"ownership": 1}),
    ("waiting", "selection_excluded", 1, 0, 0, {"held": 1}),
    ("waiting", "acquire_denied", 2, 2, 1, {"held": 2}),
    ("acquired", "task_acquired", 2, 1, 1, {}),
    ("acquired", "task_acquired", 2, 1, 1, {"held": 1}),
])
def test_impossible_rejection_totals_are_not_projected(
        waiting_report, state, reason, candidates, matched, attempted, rejected):
    report = {**waiting_report, "state": state, "reason": reason,
              "candidate_count": candidates, "matched_count": matched,
              "attempted_count": attempted, "rejected_counts": rejected,
              "scan_complete": state == "waiting"}
    if state == "acquired":
        report["selected_task_id"] = 42
    assert project_queue_status(report) is None


def test_public_adapter_drops_unrecognized_and_private_fields(waiting_report):
    from gui.api.worker_status_adapter import _project_worker
    raw = {**waiting_report, "lease_id": "private", "task_prompt": "private"}
    worker = _project_worker({"id": "our-slot", "queue_status": raw})
    assert worker["queue_status"] == waiting_report
    assert "private" not in str(worker)
    assert "queue_status" not in _project_worker({"id": "our-slot", "queue_status": {"reason": []}})


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_control_read_rejection_becomes_safe_gui_unavailability(monkeypatch, status):
    import asyncio

    from fastapi import HTTPException
    from gui.api import unified_api, worker_status_adapter
    monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda _: "fixture-token")
    def reject(*args, **kwargs):
        raise worker_status_adapter.WorkerActionRejected("PRIVATE_CONTROL_DETAIL", status)
    monkeypatch.setattr(worker_status_adapter, "_request_control_api", reject)
    with pytest.raises(HTTPException) as error:
        asyncio.run(unified_api.get_system_workers(object()))
    assert error.value.status_code == 503 and error.value.detail == "Workerstatus nicht verfügbar"
    assert "PRIVATE" not in error.value.detail


def test_controller_uses_current_generation_observation(mem_db, monkeypatch):
    from hub._services.chat import telegram_chat as controller
    client = TaskLeaseClient(conn=mem_db)
    control = controller._WorkerControl("our-slot")
    control.thread = SimpleNamespace(is_alive=lambda: True)
    control.worker_thread_started = True
    monkeypatch.setattr(controller, "_native_task_client", lambda: client)
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {"our-slot": control})
    monkeypatch.setattr(controller, "_WORKER_EXECUTIONS", {"our-slot": control})
    assert controller._acquire_worker_task(control, {"id": "our-slot"}, "physical") is None
    assert control.queue_status["reason"] == "empty_queue"
    receipt = controller.worker_execution_receipt("our-slot", control.start_request_id, verify_results=False)
    assert receipt["queue_status"] == control.queue_status and receipt["generation"] == control.generation
    raw = controller._worker_handoff_snapshot({"id": "our-slot", "queue_status": {"reason": "fake"}})
    assert raw["queue_status"] == control.queue_status
    newer = controller._WorkerControl("our-slot")
    newer.thread = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(controller, "_WORKER_CONTROLS", {"our-slot": newer})
    raw = controller._worker_handoff_snapshot({"id": "our-slot", "queue_status": control.queue_status})
    assert "queue_status" not in raw  # No stale configuration/generation fallback.
