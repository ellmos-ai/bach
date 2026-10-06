# SPDX-License-Identifier: MIT
"""Unit and contract tests for MemoryGUIBridge (Task #1447, OCEAN S9)."""

import sqlite3
from contextlib import contextmanager
import pytest
from gui.memory_bridge import MemoryGUIBridge


@pytest.fixture
def test_dbs(tmp_path):
    """Fixture providing isolated sqlite databases for bach and user."""
    bach_db_path = tmp_path / "bach_test.db"
    user_db_path = tmp_path / "user_test.db"

    # Schema setup for bach.db
    with sqlite3.connect(bach_db_path) as conn:
        conn.execute("""
            CREATE TABLE memory_working (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT DEFAULT 'note',
                content TEXT,
                created_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                key TEXT,
                value TEXT,
                value_type TEXT DEFAULT 'text',
                confidence REAL DEFAULT 1.0,
                source TEXT DEFAULT 'gui',
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE memory_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                title TEXT,
                solution TEXT,
                created_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE memory_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                started_at TEXT,
                ended_at TEXT,
                summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE memory_consolidation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_table TEXT,
                source_id INTEGER,
                weight REAL DEFAULT 1.0,
                status TEXT,
                created_at TEXT
            )
        """)
        conn.commit()

    @contextmanager
    def get_bach():
        conn = sqlite3.connect(bach_db_path)
        try:
            yield conn
        finally:
            conn.close()

    def get_user():
        return sqlite3.connect(user_db_path)

    bridge = MemoryGUIBridge(db_func=get_bach, user_db_func=get_user)
    return bridge


def test_working_memory_crud(test_dbs):
    bridge = test_dbs

    # 1. Add
    res = bridge.add_working("Test Notiz 1")
    assert res["status"] == "created"

    # 2. Get
    working = bridge.get_working()
    assert working["count"] == 1
    assert working["entries"][0]["content"] == "Test Notiz 1"
    entry_id = working["entries"][0]["id"]

    # 3. Delete
    del_res = bridge.delete_working(entry_id)
    assert del_res["status"] == "deleted"

    working_after = bridge.get_working()
    assert working_after["count"] == 0


def test_facts_crud(test_dbs):
    bridge = test_dbs

    # Empty validation
    err_res = bridge.add_fact("", "")
    assert err_res["status"] == "error"

    # Add
    res = bridge.add_fact("key1", "value1", "category_a")
    assert res["status"] == "created"

    # Get
    facts = bridge.get_facts()
    assert len(facts["facts"]) == 1
    fact = facts["facts"][0]
    assert fact["key"] == "key1"
    assert fact["value"] == "value1"

    # Delete
    del_res = bridge.delete_fact(fact["id"])
    assert del_res["status"] == "deleted"

    facts_after = bridge.get_facts()
    assert len(facts_after["facts"]) == 0


def test_lessons_crud(test_dbs):
    bridge = test_dbs

    # Add
    res = bridge.add_lesson("Always test first", category="dev")
    assert res["status"] == "created"

    # Get
    lessons = bridge.get_lessons(category="dev")
    assert lessons["count"] == 1
    assert lessons["entries"][0]["content"] == "Always test first"
    lesson_id = lessons["entries"][0]["id"]

    # Delete
    del_res = bridge.delete_lesson(lesson_id)
    assert del_res["status"] == "deleted"

    lessons_after = bridge.get_lessons()
    assert lessons_after["count"] == 0


def test_sessions_and_overview(test_dbs):
    bridge = test_dbs

    # Populate data
    bridge.add_working("Overview note")
    bridge.add_fact("env", "prod", "config")
    bridge.add_lesson("Overview lesson")

    # Overview
    overview = bridge.get_overview()
    assert len(overview["working"]) == 1
    assert len(overview["facts"]) == 1
    assert len(overview["lessons"]) == 1

    # User session
    sess_res = bridge.add_session("Session context content", "sess-123")
    assert sess_res["status"] == "ok"

    # Stats db
    stats = bridge.get_stats_db()
    assert stats["success"] is True
    assert stats["count"] >= 5

    # Cleanup
    cleanup = bridge.maintenance_cleanup()
    assert cleanup["success"] is True
