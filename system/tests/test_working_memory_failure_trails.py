# SPDX-License-Identifier: MIT
"""Tests for Failure Trails – Ocean-style negative working memory."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hub.working_memory import FailureTrailStore


@pytest.fixture
def in_memory_store():
    """Fresh in-memory FailureTrailStore."""
    return FailureTrailStore()


@pytest.fixture
def db_store(tmp_path: Path):
    """FailureTrailStore backed by a temporary SQLite file."""
    db_path = tmp_path / "failure_trails.db"
    return FailureTrailStore(db_path)


def test_record_first_failure_creates_trail(in_memory_store):
    store = in_memory_store
    entry = store.record_failure("tools/some_tool", ValueError("boom"))

    assert entry.tool_path == "tools/some_tool"
    assert entry.failure_signature.startswith("ValueError:")
    assert entry.retry_count == 1
    assert entry.backoff_until > datetime.now()
    assert store.is_blocked("tools/some_tool") is True
    assert store.should_skip("tools/some_tool") is True
    assert len(store.list_trails()) == 1


def test_repeated_failure_blocks_and_increments(in_memory_store):
    store = in_memory_store
    exc = RuntimeError("timeout")

    first = store.record_failure("agent/scheduler", exc)
    second = store.record_failure("agent/scheduler", exc)

    assert first.retry_count == 1
    assert second.retry_count == 2
    assert second.backoff_until >= first.backoff_until
    assert store.is_blocked("agent/scheduler") is True
    assert second.retry_count == store.list_trails("agent/scheduler")[0].retry_count


def test_backoff_expired_allows_retry(in_memory_store):
    store = in_memory_store
    store.record_failure("agent/scheduler", RuntimeError("timeout"))

    far_future = datetime.now() + timedelta(days=1)
    assert store.is_blocked("agent/scheduler", now=far_future) is False
    assert store.should_skip("agent/scheduler", now=far_future) is False


def test_different_context_is_separate_trail(in_memory_store):
    store = in_memory_store
    exc = ConnectionError("refused")

    store.record_failure("api/client", exc, context={"host": "a.example.com"})
    store.record_failure("api/client", exc, context={"host": "b.example.com"})

    trails = store.list_trails("api/client")
    assert len(trails) == 2
    assert {t.context_hash for t in trails} == {
        store._context_hash({"host": "a.example.com"}),
        store._context_hash({"host": "b.example.com"}),
    }

    # Broad block without context still blocks the tool path.
    assert store.is_blocked("api/client") is True
    # Specific context blocks the exact matching trail.
    assert store.is_blocked("api/client", context={"host": "a.example.com"}) is True


def test_age_out_removes_stale_trails(in_memory_store):
    store = in_memory_store
    store.record_failure("tools/stale", OSError("disk full"))
    assert len(store.list_trails()) == 1

    # Use negative age so every entry is considered stale immediately.
    removed = store.age_out(max_age_minutes=-1)

    assert len(removed) == 1
    assert removed[0].tool_path == "tools/stale"
    assert len(store.list_trails()) == 0


def test_persistence_reloads_trails(db_store, tmp_path: Path):
    db_path = tmp_path / "failure_trails.db"
    store = FailureTrailStore(db_path)
    store.record_failure("tools/persistent", TimeoutError("took too long"))

    # Re-open store from the same database file.
    reloaded = FailureTrailStore(db_path)
    trails = reloaded.list_trails("tools/persistent")

    assert len(trails) == 1
    assert trails[0].retry_count == 1
    assert trails[0].failure_signature.startswith("TimeoutError:")
    assert reloaded.is_blocked("tools/persistent") is True


def test_schema_migration_syntax(tmp_path: Path):
    """Ensure the shipped SQL migration creates the expected table and index."""
    migration_path = Path(__file__).parent.parent / "data" / "schema" / "migrations" / "053_working_memory_failure_trails.sql"
    assert migration_path.exists()

    db_path = tmp_path / "migration.db"
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.executescript(migration_path.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO working_memory_failure_trails (tool_path, failure_signature, context_hash, first_seen_at, last_seen_at, retry_count, backoff_until) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("t", "f", "c", datetime.now().isoformat(), datetime.now().isoformat(), 1, (datetime.now() + timedelta(minutes=5)).isoformat()),
    )
    conn.commit()
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_working_memory_failure_trails_tool_path'")
    assert cur.fetchone() is not None
    conn.close()
