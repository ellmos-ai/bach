# SPDX-License-Identifier: MIT
"""Tests für TaskLeaseClient (BACH #1722, T793 LEASE 3/4)."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from hub._services.task_lease import ensure_task_lease_schema, LeaseConfig
from hub._services.task_lease_client import (
    TaskLeaseClient,
    LeaseAck,
    LeaseHolderView,
    LeaseReleaseAck,
    LeaseDeniedError,
    LeaseStaleFenceError,
    LeaseExpiredError,
    LeaseOfflineDeadlineExceeded,
)


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'M',
            category TEXT,
            assigned_to TEXT,
            created_by TEXT,
            depends_on TEXT,
            estimated_minutes INTEGER,
            actual_minutes INTEGER,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT,
            due_date TEXT,
            source TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT,
            changed_at TEXT NOT NULL
        )"""
    )
    ensure_task_lease_schema(conn)


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    yield conn
    conn.close()


def _insert_task(conn: sqlite3.Connection, title: str = "T1", status: str = "open") -> int:
    cur = conn.execute("INSERT INTO tasks (title, status) VALUES (?, ?)", (title, status))
    conn.commit()
    return cur.lastrowid


def test_client_acquire_and_read(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)

    ack = client.acquire(
        tid,
        worker_id="gemini@ASUS-GEI",
        host="ASUS-GEI",
        ttl_profile="M",
        intent="Client-Test",
    )

    assert isinstance(ack, LeaseAck)
    assert ack.task_id == tid
    assert ack.worker_id == "gemini@ASUS-GEI"
    assert ack.host == "ASUS-GEI"
    assert ack.fence == 1
    assert ack.ttl_profile == "M"
    assert ack.is_locally_valid
    ack.assert_locally_valid()

    # Read ohne lease_id
    view = client.read(tid)
    assert isinstance(view, LeaseHolderView)
    assert view.leased is True
    assert view.fence == 1
    assert view.holder["worker_id"] == "gemini@ASUS-GEI"
    assert view.own is False

    # Read mit passender lease_id
    own_view = client.read(tid, lease_id=ack.lease_id)
    assert own_view.own is True


def test_client_conflict_denied(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)

    ack = client.acquire(tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI")
    assert ack.fence == 1

    # Zweiter Worker -> LeaseDeniedError (held)
    with pytest.raises(LeaseDeniedError) as exc_info:
        client.acquire(tid, worker_id="codex@WORKSTATION-LG", host="WORKSTATION-LG")
    assert exc_info.value.reason == "held"


def test_client_renew_success(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)

    ack = client.acquire(tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI")
    renewed = client.renew(tid, lease_id=ack.lease_id, fence=ack.fence)

    assert renewed.fence == ack.fence
    assert renewed.lease_id == ack.lease_id


def test_client_release_success(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)

    ack = client.acquire(tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI")
    rel = client.release(tid, lease_id=ack.lease_id, fence=ack.fence, outcome="done", note="erledigt")

    assert isinstance(rel, LeaseReleaseAck)
    assert rel.released is True
    assert rel.status == "done"
    assert rel.fence == 1

    # Task ist nun fertig
    view = client.read(tid)
    assert view.status == "done"
    assert view.leased is False


def test_client_stale_fence_fails(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)

    ack = client.acquire(tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI")

    with pytest.raises(LeaseStaleFenceError):
        client.release(tid, lease_id=ack.lease_id, fence=ack.fence + 99, outcome="done")


def test_client_expired_fails(mem_db):
    tid = _insert_task(mem_db)
    client = TaskLeaseClient(conn=mem_db)

    # Acquire zu t0
    t0 = datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc)
    ack = client.acquire(tid, worker_id="gemini@ASUS-GEI", host="ASUS-GEI", now=t0)

    # Release zu t0 + 2h (nach M-TTL von 30m)
    t_late = t0 + timedelta(hours=2)
    with pytest.raises(LeaseExpiredError):
        client.release(tid, lease_id=ack.lease_id, fence=ack.fence, outcome="done", now=t_late)


def test_client_local_deadline_guard():
    # Ablauf liegt 120 Sekunden nach server_now. Mit 60s Sicherheitsmarge ist
    # local_deadline 60 Sekunden nach local_receive_time.
    t_recv = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
    ack = LeaseAck(
        task_id=1,
        lease_id="00000000-0000-4000-8000-000000000001",
        fence=1,
        worker_id="gemini@ASUS-GEI",
        host="ASUS-GEI",
        issued_at="2026-10-05T12:00:00.000000Z",
        expires_at="2026-10-05T12:02:00.000000Z",
        ttl_profile="S",
        server_now="2026-10-05T12:00:00.000000Z",
        local_receive_time=t_recv,
    )
    assert ack.local_deadline == t_recv + timedelta(seconds=60)
