"""Task 4199 Diagnose: Ursache fuer abgelehnte Kandidaten in acquire_next."""
import sqlite3
import threading

import pytest

from hub._services import worker_policy_settings as settings
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease_client import TaskLeaseClient
from hub._services.worker_policy_settings import CONTRACT, TASK_SCHEMA
from system.tests.test_task_lease_client import _init_db, _insert_task
from system.tests.test_task_lease_client_review import T0


@pytest.fixture
def task_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    yield conn
    conn.close()


def _prepared(conn):
    task_id = _insert_task(conn, "Diagnoseaufgabe")
    conn.execute(
        "UPDATE tasks SET assigned_to='BACH', needs_split=1 WHERE id=?", (task_id,))
    conn.commit()
    return task_id


def test_4199_policy_chain_diagnosis(task_db):
    task_id = _prepared(task_db)
    print("TASK_ID:", task_id)
    print("TASK_SCHEMA:", TASK_SCHEMA, "| CONTRACT:", CONTRACT)
    try:
        stored_direct = settings.read_task_policy(task_id, conn=task_db)
        print("READ_TASK_POLICY:", stored_direct)
    except Exception as exc:
        pytest.fail(f"read_task_policy: {type(exc).__name__}: {exc}")
    client = TaskLeaseClient(conn=task_db)
    print("CLIENT MODE:", getattr(client, "mode", None))
    reader = getattr(client, "_task_policy_snapshot", None)
    print("READER CALLABLE:", callable(reader))
    try:
        snap = reader(task_id) if callable(reader) else None
        print("CLIENT _task_policy_snapshot:", snap)
    except Exception as exc:
        pytest.fail(f"_task_policy_snapshot: {type(exc).__name__}: {exc}")
    if isinstance(snap, dict):
        print("CHECK schema:", snap.get("schema"), "==", TASK_SCHEMA,
              "->", snap.get("schema") == TASK_SCHEMA)
        print("CHECK availability:", snap.get("availability"), "== available ->",
              snap.get("availability") == "available")
        print("CHECK task_id:", snap.get("task_id"), type(snap.get("task_id")).__name__)
        print("CHECK task_version:", repr(snap.get("task_version")))
        print("CHECK configuration_version:", repr(snap.get("configuration_version")))
        print("CHECK effective:", snap.get("effective"))
    task_version = snap.get("task_version") if isinstance(snap, dict) else None
    effective = WorkerLeaseBinding._effective_selection_policy_snapshot(
        client, {"id": task_id, "task_version": task_version},
        {"id": "slot", "model": "test-model"})
    print("EFFECTIVE_SELECTION_POLICY:", effective)

    # --- acquire_next-Diagnoselauf (4199): konkreten Ablehnungsgrund sichtbar machen.
    def _observe(record):
        print("OBSERVE:", record)

    diag_slot = {"id": "divider", "role_id": "task-divider",
                 "model": "test-model", "divider_available": True}
    try:
        acquired = WorkerLeaseBinding.acquire_next(
            client, diag_slot,
            observe_queue=_observe,
            worker_id="diag-worker@HOST", host="HOST",
            generation="generation-1", is_current=lambda: True,
            stop_event=threading.Event(), clock=lambda: T0)
        print("ACQUIRE_NEXT RESULT:", acquired)
        assert acquired is not None, "acquire_next lieferte None"
    except Exception as exc:
        print("ACQUIRE_NEXT EXCEPTION:", type(exc).__name__, exc,
              "| reason:", getattr(exc, "reason", None))
        pytest.fail(
            f"acquire_next abgelehnt: {type(exc).__name__}: {exc} "
            f"reason={getattr(exc, 'reason', None)}")
