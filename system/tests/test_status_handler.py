# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for StatusHandler (hub/status.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.status import StatusHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_tables(conn):
    conn.execute("""
        CREATE TABLE memory_sessions (
            id INTEGER PRIMARY KEY, session_id TEXT,
            partner_id TEXT, started_at TEXT, ended_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE partner_presence (
            id INTEGER PRIMARY KEY, partner_name TEXT,
            status TEXT, clocked_in TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE memory_working (id INTEGER PRIMARY KEY, content TEXT)
    """)
    conn.execute("""
        CREATE TABLE memory_facts (id INTEGER PRIMARY KEY, content TEXT)
    """)
    conn.execute("""
        CREATE TABLE memory_lessons (id INTEGER PRIMARY KEY, content TEXT)
    """)
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, content TEXT, status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY, title TEXT, status TEXT,
            priority TEXT, category TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tools (
            id INTEGER PRIMARY KEY, name TEXT, is_available INTEGER DEFAULT 1
        )
    """)
    conn.commit()


@pytest.fixture
def fake_status_env(tmp_path, monkeypatch):
    """Minimal BACH env with all tables StatusHandler queries."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tables(conn)
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def populated_env(tmp_path, monkeypatch):
    """Env with sessions, partners, tasks, etc."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tables(conn)

    conn.execute(
        "INSERT INTO memory_sessions (session_id, partner_id, ended_at) "
        "VALUES ('sess-1', 'claude', NULL)"
    )
    conn.execute(
        "INSERT INTO partner_presence (partner_name, status, clocked_in) "
        "VALUES ('claude', 'online', '2026-01-01 10:00')"
    )
    conn.execute(
        "INSERT INTO partner_presence (partner_name, status, clocked_in) "
        "VALUES ('gemini', 'online', '2026-01-01 09:00')"
    )
    for i in range(5):
        conn.execute("INSERT INTO memory_working (content) VALUES (?)", (f"note {i}",))
    for i in range(3):
        conn.execute("INSERT INTO memory_facts (content) VALUES (?)", (f"fact {i}",))
    conn.execute("INSERT INTO memory_lessons (content) VALUES ('lesson 1')")

    conn.execute(
        "INSERT INTO messages (content, status) VALUES ('hi', 'unread')"
    )
    conn.execute(
        "INSERT INTO messages (content, status) VALUES ('hello', 'read')"
    )

    conn.execute(
        "INSERT INTO tasks (title, status, priority) VALUES ('Fix bug', 'pending', 'P1')"
    )
    conn.execute(
        "INSERT INTO tasks (title, status, priority) VALUES ('Docs', 'pending', 'P3')"
    )
    conn.execute(
        "INSERT INTO tasks (title, status, priority) VALUES ('Blocked item', 'blocked', 'P2')"
    )
    conn.execute(
        "INSERT INTO tasks (title, status, priority) VALUES ('Done task', 'done', 'P4')"
    )

    for i in range(7):
        conn.execute("INSERT INTO tools (name, is_available) VALUES (?, 1)", (f"tool_{i}",))
    conn.execute("INSERT INTO tools (name, is_available) VALUES ('disabled', 0)")

    conn.commit()
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def handler(fake_status_env):
    base, _ = fake_status_env
    return StatusHandler(base)


@pytest.fixture
def populated_handler(populated_env):
    base, _ = populated_env
    return StatusHandler(base)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "status"

    def test_target_file(self, handler, fake_status_env):
        base, _ = fake_status_env
        assert handler.target_file == base

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "show" in ops


# ═══════════════════════════════════════════════════════════════
# EMPTY DATABASE
# ═══════════════════════════════════════════════════════════════


class TestEmptyDb:
    def test_status_empty(self, handler):
        ok, output = handler.handle("show", [])
        assert ok is True
        assert "BACH Status" in output
        assert "0 online" in output
        assert "0 Working" in output
        assert "0 offen" in output
        assert "Health:   OK" in output

    def test_no_active_session(self, handler):
        ok, output = handler.handle("show", [])
        assert "Keine aktive Session" in output

    def test_any_operation_calls_show(self, handler):
        ok1, out1 = handler.handle("show", [])
        ok2, out2 = handler.handle("anything", [])
        assert ok1 == ok2
        assert out1 == out2


# ═══════════════════════════════════════════════════════════════
# POPULATED DATABASE
# ═══════════════════════════════════════════════════════════════


class TestPopulatedDb:
    def test_active_session(self, populated_handler):
        ok, output = populated_handler.handle("show", [])
        assert ok is True
        assert "Aktiv" in output
        assert "claude" in output

    def test_partners_online(self, populated_handler):
        ok, output = populated_handler.handle("show", [])
        assert "2 online" in output
        assert "claude" in output
        assert "gemini" in output

    def test_memory_counts(self, populated_handler):
        ok, output = populated_handler.handle("show", [])
        assert "5 Working" in output
        assert "3 Facts" in output
        assert "1 Lessons" in output

    def test_unread_messages(self, populated_handler):
        ok, output = populated_handler.handle("show", [])
        assert "1 ungelesen" in output

    def test_task_counts(self, populated_handler):
        ok, output = populated_handler.handle("show", [])
        assert "2 offen" in output
        assert "1 P1/P2" in output
        assert "1 blocked" in output

    def test_tool_count(self, populated_handler):
        ok, output = populated_handler.handle("show", [])
        assert "7 registriert" in output

    def test_health_ok(self, populated_handler):
        ok, output = populated_handler.handle("show", [])
        assert "Health:   OK" in output


# ═══════════════════════════════════════════════════════════════
# ERROR PATHS
# ═══════════════════════════════════════════════════════════════


class TestErrors:
    def test_db_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("hub.bach_paths.BACH_DB", tmp_path / "bach.db")
        h = StatusHandler(tmp_path)
        ok, output = h.handle("show", [])
        assert ok is False
        assert "FEHLER" in output
        assert "bach.db fehlt" in output

    def test_db_corrupt(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = data_dir / "bach.db"
        db_path.write_text("not a database", encoding="utf-8")
        monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
        h = StatusHandler(tmp_path)
        ok, output = h.handle("show", [])
        assert ok is False
        assert "FEHLER" in output


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import inspect
        source = inspect.getsource(StatusHandler)
        for i, line in enumerate(source.split("\n")):
            stripped = line.strip()
            if stripped == "except:" or stripped == "except: pass":
                pytest.fail(f"Bare except at line {i+1}: {stripped}")
