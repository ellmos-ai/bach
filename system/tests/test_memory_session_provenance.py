# -*- coding: utf-8 -*-
"""Regression tests for task 1174 memory author provenance."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest


MIGRATION_PATH = (
    Path(__file__).parent.parent
    / "data"
    / "schema"
    / "migrations"
    / "039_memory_session_provenance.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("memory_session_provenance", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE memory_sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT UNIQUE NOT NULL,
            partner_id TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT
        );
        CREATE TABLE memory_working (id INTEGER PRIMARY KEY, content TEXT NOT NULL);
        CREATE TABLE memory_facts (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            UNIQUE(category, key)
        );
        CREATE TABLE memory_lessons (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            solution TEXT NOT NULL
        );
        """
    )
    _migration().run_migration(conn)
    yield conn
    conn.close()


@pytest.mark.parametrize(
    ("table", "sql", "params"),
    [
        ("memory_working", "INSERT INTO memory_working (content) VALUES (?)", ("note",)),
        (
            "memory_facts",
            "INSERT INTO memory_facts (category, key, value) VALUES (?, ?, ?)",
            ("project", "provenance", "enabled"),
        ),
        (
            "memory_lessons",
            "INSERT INTO memory_lessons (category, title, solution) VALUES (?, ?, ?)",
            ("system", "Memory provenance", "Keep the session reference."),
        ),
    ],
)
def test_new_entries_inherit_the_active_session(db, table, sql, params):
    db.execute(
        "INSERT INTO memory_sessions (session_id, partner_id, started_at) VALUES (?, ?, ?)",
        ("sess-codex", "codex", "2026-08-07T19:00:00"),
    )
    db.execute(sql, params)
    row = db.execute(
        f"SELECT created_by_session_id, updated_by_session_id FROM {table}"
    ).fetchone()
    assert row == ("sess-codex", "sess-codex")


def test_update_records_the_current_editor_without_overwriting_creator(db):
    db.execute(
        "INSERT INTO memory_sessions (session_id, partner_id, started_at, ended_at) VALUES (?, ?, ?, ?)",
        ("sess-claude", "claude", "2026-08-07T18:00:00", "2026-08-07T18:30:00"),
    )
    db.execute(
        "INSERT INTO memory_working (content, created_by_session_id, updated_by_session_id) VALUES (?, ?, ?)",
        ("original", "sess-claude", "sess-claude"),
    )
    db.execute(
        "INSERT INTO memory_sessions (session_id, partner_id, started_at) VALUES (?, ?, ?)",
        ("sess-codex", "codex", "2026-08-07T19:00:00"),
    )
    db.execute("UPDATE memory_working SET content = ? WHERE id = 1", ("edited",))
    row = db.execute(
        "SELECT created_by_session_id, updated_by_session_id FROM memory_working WHERE id = 1"
    ).fetchone()
    assert row == ("sess-claude", "sess-codex")


def test_legacy_entries_remain_explicitly_unknown_without_an_active_session(db):
    db.execute("INSERT INTO memory_working (content) VALUES (?)", ("legacy",))
    row = db.execute(
        "SELECT created_by_session_id, updated_by_session_id FROM memory_working"
    ).fetchone()
    assert row == (None, None)


def test_migration_is_idempotent(db):
    _migration().run_migration(db)
    columns = {row[1] for row in db.execute("PRAGMA table_info(memory_facts)")}
    assert {"created_by_session_id", "updated_by_session_id"} <= columns
