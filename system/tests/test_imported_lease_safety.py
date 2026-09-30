"""T797: UUID-fenced SQLite leases, exclusively on disposable databases."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from imported_capabilities.category_1_solved_wanted.leases.adapter_bach import (
    ensure_task_lease_schema,
    release_task_lease,
    renew_task_lease,
    try_claim_task_atomic,
)


@pytest.fixture
def lease_db(tmp_path):
    path = tmp_path / "leases.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, status TEXT)")
        conn.execute("INSERT INTO tasks VALUES (1, 'pending')")
    return path


def snapshot(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT * FROM tasks").fetchall()


@pytest.mark.parametrize("status", ["done", "completed", "cancelled", "blocked", "unknown", None])
@pytest.mark.parametrize("expiry", [None, "2000-01-01 00:00:00"])
def test_terminal_or_unknown_status_never_reopened(lease_db, status, expiry):
    with sqlite3.connect(lease_db) as conn:
        ensure_task_lease_schema(conn)
        conn.execute("UPDATE tasks SET status=?, claim_expires_at=?", (status, expiry))
        conn.commit()
        before = snapshot(lease_db)
        assert not try_claim_task_atomic(conn, 1, "new").success
        assert snapshot(lease_db) == before


@pytest.mark.parametrize("status", ["pending", "open", "in_progress"])
@pytest.mark.parametrize("expiry", [None, "invalid", "2999-01-01 00:00:00"])
def test_existing_claim_requires_valid_expired_lease(lease_db, status, expiry):
    with sqlite3.connect(lease_db) as conn:
        ensure_task_lease_schema(conn)
        conn.execute("UPDATE tasks SET status=?, claim_id='old', claimed_by='same', claim_expires_at=?", (status, expiry))
        conn.commit()
        before = snapshot(lease_db)
        assert not try_claim_task_atomic(conn, 1, "same").success
        assert not try_claim_task_atomic(conn, 1, "other").success
        assert snapshot(lease_db) == before


@pytest.mark.parametrize("ttl", [0, -1, True, 1.5, "30", None])
@pytest.mark.parametrize("operation", ["claim", "renew"])
def test_invalid_ttl_does_not_write(lease_db, ttl, operation):
    with sqlite3.connect(lease_db) as conn:
        ensure_task_lease_schema(conn)
        before = lease_db.read_bytes()
        with pytest.raises(ValueError):
            if operation == "claim":
                try_claim_task_atomic(conn, 1, "agent", ttl_seconds=ttl)
            else:
                renew_task_lease(conn, 1, "old", ttl_seconds=ttl)
        assert lease_db.read_bytes() == before


@pytest.mark.parametrize("agent", ["", "  ", None])
def test_empty_owner_does_not_write(lease_db, agent):
    with sqlite3.connect(lease_db) as conn:
        before = lease_db.read_bytes()
        with pytest.raises(ValueError):
            try_claim_task_atomic(conn, 1, agent)
        assert lease_db.read_bytes() == before


@pytest.mark.parametrize("same_agent", [False, True])
def test_concurrent_initial_schema_and_claim_one_winner(lease_db, same_agent):
    barrier = Barrier(4)
    def claim(index):
        with sqlite3.connect(lease_db, timeout=10) as conn:
            barrier.wait(timeout=5)
            return try_claim_task_atomic(conn, 1, "same" if same_agent else f"agent{index}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    winners = [result for result in results if result.success]
    assert len(winners) == 1
    with sqlite3.connect(lease_db) as conn:
        assert conn.execute("SELECT claim_id FROM tasks").fetchone()[0] == winners[0].claim_id


def test_reopen_reclaim_fences_old_id_and_clears_host(lease_db):
    with sqlite3.connect(lease_db) as conn:
        old = try_claim_task_atomic(conn, 1, "agent", host="old-host")
        assert old.success
        assert not try_claim_task_atomic(conn, 1, "agent").success
        conn.execute("UPDATE tasks SET claim_expires_at='2000-01-01 00:00:00'")
        conn.commit()
    with sqlite3.connect(lease_db) as conn:
        new = try_claim_task_atomic(conn, 1, "agent", host="new-host")
        assert new.success and new.claim_id != old.claim_id
        before = snapshot(lease_db)
        assert not renew_task_lease(conn, 1, old.claim_id)
        assert not release_task_lease(conn, 1, old.claim_id, "done")
        assert snapshot(lease_db) == before
        assert renew_task_lease(conn, 1, new.claim_id)
        assert release_task_lease(conn, 1, new.claim_id)
        assert conn.execute("SELECT status, claim_id, claimed_by, claim_host FROM tasks").fetchone() == ("pending", None, None, None)
        assert try_claim_task_atomic(conn, 1, "other").success


@pytest.mark.parametrize("operation", ["renew", "release"])
@pytest.mark.parametrize("state", ["done", "blocked", "expired"])
def test_inactive_lease_cannot_renew_or_complete(lease_db, operation, state):
    with sqlite3.connect(lease_db) as conn:
        result = try_claim_task_atomic(conn, 1, "agent")
        if state == "expired":
            conn.execute("UPDATE tasks SET claim_expires_at='2000-01-01 00:00:00'")
        else:
            conn.execute("UPDATE tasks SET status=?", (state,))
        conn.commit()
        before = snapshot(lease_db)
        assert not (renew_task_lease(conn, 1, result.claim_id) if operation == "renew" else release_task_lease(conn, 1, result.claim_id, "done"))
        assert snapshot(lease_db) == before


def test_caller_transaction_is_not_committed(lease_db):
    with sqlite3.connect(lease_db) as conn:
        conn.execute("UPDATE tasks SET status='blocked'")
        with pytest.raises(ValueError, match="transaction"):
            try_claim_task_atomic(conn, 1, "agent")
        assert conn.in_transaction
        conn.rollback()
    assert snapshot(lease_db) == [(1, "pending")]


def test_release_rejects_unknown_status(lease_db):
    with sqlite3.connect(lease_db) as conn:
        result = try_claim_task_atomic(conn, 1, "agent")
        before = snapshot(lease_db)
        with pytest.raises(ValueError):
            release_task_lease(conn, 1, result.claim_id, "arbitrary")
        assert snapshot(lease_db) == before
