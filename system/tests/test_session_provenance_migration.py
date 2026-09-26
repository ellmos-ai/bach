# -*- coding: utf-8 -*-
"""Tests for migration 048 session provenance hardening and stale cleanup."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest


SCHEMA_DIR = Path(__file__).parent.parent / "data" / "schema"
MIGRATION = SCHEMA_DIR / "migrations" / "048_harden_session_provenance.py"


def _migration():
    spec = importlib.util.spec_from_file_location("migration_048", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migration():
    return _migration()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript((SCHEMA_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.executescript(
        """
        INSERT INTO memory_sessions
            (id, session_id, started_at, ended_at, summary, agent_id)
        VALUES
            (1, 's-stale', datetime('now', '-48 hours'), NULL, 'legacy', 'target'),
            (2, 's-fresh-target', datetime('now', '-10 minutes'), NULL, NULL, 'target'),
            (3, 's-fresh-other', datetime('now', '-1 minute'), NULL, NULL, 'other');
        """
    )
    conn.commit()
    yield conn
    conn.close()


def test_migration_closes_stale_sessions_once_and_keeps_fresh_open(db, migration):
    migration.run_migration(db)
    db.commit()

    stale_after_first = db.execute(
        "SELECT ended_at, summary FROM memory_sessions WHERE session_id = 's-stale'"
    ).fetchone()
    assert stale_after_first[0] is not None
    assert stale_after_first[1] == "legacy [AUTO-CLOSED: stale]"
    assert db.execute(
        "SELECT ended_at FROM memory_sessions WHERE session_id = 's-fresh-target'"
    ).fetchone() == (None,)
    assert db.execute(
        "SELECT ended_at FROM memory_sessions WHERE session_id = 's-fresh-other'"
    ).fetchone() == (None,)

    migration.run_migration(db)
    db.commit()

    stale_after_second = db.execute(
        "SELECT ended_at, summary FROM memory_sessions WHERE session_id = 's-stale'"
    ).fetchone()
    assert stale_after_second == stale_after_first
    assert stale_after_second[1].count("[AUTO-CLOSED: stale]") == 1
    assert db.execute(
        "SELECT ended_at FROM memory_sessions WHERE session_id = 's-fresh-target'"
    ).fetchone() == (None,)
    assert db.execute(
        "SELECT ended_at FROM memory_sessions WHERE session_id = 's-fresh-other'"
    ).fetchone() == (None,)


def test_migration_reinstalls_hardened_triggers(db, migration):
    old_sql = db.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'trigger' AND name = 'trg_memory_working_session_provenance_insert'"
    ).fetchone()[0]
    assert "datetime('now', '-24 hours')" not in old_sql

    migration.run_migration(db)
    db.commit()

    new_sql = db.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'trigger' AND name = 'trg_memory_working_session_provenance_insert'"
    ).fetchone()[0]
    assert "datetime('now', '-24 hours')" in new_sql
    assert "NEW.agent_id" in new_sql

    db.execute(
        "INSERT INTO memory_working (type, content, agent_id) "
        "VALUES ('note', 'new', 'target')"
    )
    assert db.execute(
        "SELECT created_by_session_id, updated_by_session_id "
        "FROM memory_working WHERE content = 'new'"
    ).fetchone() == ("s-fresh-target", "s-fresh-target")
