# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SessionHandler (hub/session.py)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.session import SessionHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_tables(conn):
    conn.execute("""
        CREATE TABLE memory_sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            partner_id TEXT,
            started_at TEXT,
            ended_at TEXT,
            summary TEXT,
            tasks_created INTEGER DEFAULT 0,
            tasks_completed INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'P3',
            created_at TEXT,
            completed_at TEXT
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
    conn.commit()


@pytest.fixture
def empty_env(tmp_path):
    """Env with empty tables."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tables(conn)
    conn.close()
    return tmp_path, db_path


@pytest.fixture
def active_session_env(tmp_path):
    """Env with an active session and tasks."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tables(conn)

    conn.execute(
        "INSERT INTO memory_sessions (session_id, partner_id, started_at, ended_at, tasks_created, tasks_completed) "
        "VALUES ('sess-active', 'claude', '2026-01-15 10:00:00', NULL, 5, 2)"
    )
    conn.execute(
        "INSERT INTO memory_sessions (session_id, partner_id, started_at, ended_at, summary) "
        "VALUES ('sess-old', 'gemini', '2026-01-14 09:00:00', '2026-01-14 17:00:00', 'Refactoring abgeschlossen')"
    )

    conn.execute(
        "INSERT INTO tasks (title, status, priority, created_at) "
        "VALUES ('Fix critical bug', 'pending', 'P1', '2026-01-15 10:30')"
    )
    conn.execute(
        "INSERT INTO tasks (title, status, priority, created_at) "
        "VALUES ('Write docs', 'pending', 'P3', '2026-01-15 11:00')"
    )
    conn.execute(
        "INSERT INTO tasks (title, status, priority, created_at) "
        "VALUES ('Blocked item', 'blocked', 'P2', '2026-01-10 10:00')"
    )
    conn.execute(
        "INSERT INTO tasks (title, status, priority, created_at, completed_at) "
        "VALUES ('Done task', 'done', 'P4', '2026-01-15 10:00', datetime('now'))"
    )

    conn.commit()
    conn.close()
    return tmp_path, db_path


@pytest.fixture
def handler(empty_env):
    base, _ = empty_env
    return SessionHandler(base)


@pytest.fixture
def active_handler(active_session_env):
    base, _ = active_session_env
    return SessionHandler(base)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "session"

    def test_target_file(self, handler, empty_env):
        _, db_path = empty_env
        assert handler.target_file == db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "start" in ops
        assert "status" in ops
        assert "end" in ops
        assert "check" in ops
        assert "next" in ops
        assert "help" in ops


# ═══════════════════════════════════════════════════════════════
# SESSION QUERIES
# ═══════════════════════════════════════════════════════════════


class TestSessionQueries:
    def test_no_current_session(self, handler):
        assert handler._get_current_session() is None

    def test_no_last_session(self, handler):
        assert handler._get_last_session() is None

    def test_current_session_found(self, active_handler):
        current = active_handler._get_current_session()
        assert current is not None
        assert current['session_id'] == 'sess-active'
        assert current['partner_id'] == 'claude'
        assert current['ended_at'] is None

    def test_last_session_found(self, active_handler):
        last = active_handler._get_last_session()
        assert last is not None
        assert last['session_id'] == 'sess-old'
        assert 'Refactoring' in last['summary']


# ═══════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_no_session(self, handler):
        ok, output = handler.handle("status", [])
        assert ok is True
        assert "SESSION STATUS" in output
        assert "KEINE AKTIVE SESSION" in output

    def test_status_with_active_session(self, active_handler):
        ok, output = active_handler.handle("status", [])
        assert ok is True
        assert "AKTIVE SESSION" in output
        assert "sess-active" in output
        assert "DENKANSTOESSE" in output
        assert "AUFGABEN-STATUS" in output

    def test_status_shows_last_session_when_no_active(self, empty_env):
        base, db_path = empty_env
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO memory_sessions (session_id, partner_id, started_at, ended_at, summary) "
            "VALUES ('sess-old', 'gemini', '2026-01-14 09:00:00', '2026-01-14 17:00:00', 'Refactoring abgeschlossen')"
        )
        conn.commit()
        conn.close()
        h = SessionHandler(base)
        ok, output = h.handle("status", [])
        assert "LETZTE SESSION" in output
        assert "sess-old" in output
        assert "Refactoring" in output

    def test_status_task_summary(self, active_handler):
        ok, output = active_handler.handle("status", [])
        assert "Offen: 2" in output
        assert "Blockiert: 1" in output


# ═══════════════════════════════════════════════════════════════
# TASK SUMMARY
# ═══════════════════════════════════════════════════════════════


class TestTaskSummary:
    def test_empty_task_summary(self, handler):
        summary = handler._get_task_summary()
        assert summary['open'] == 0
        assert summary['blocked'] == 0
        assert summary['done_today'] == 0
        assert not summary['high_priority']

    def test_populated_task_summary(self, active_handler):
        summary = active_handler._get_task_summary()
        assert summary['open'] == 2
        assert summary['blocked'] == 1
        assert summary['done_today'] >= 1
        assert summary['high_priority'] != ""


# ═══════════════════════════════════════════════════════════════
# THOUGHT PROMPTS
# ═══════════════════════════════════════════════════════════════


class TestThoughtPrompts:
    def test_returns_three_prompts(self, handler):
        prompts = handler._get_thought_prompts()
        assert len(prompts) == 3

    def test_prompts_are_strings(self, handler):
        prompts = handler._get_thought_prompts()
        assert all(isinstance(p, str) for p in prompts)

    def test_blocked_tasks_prompt(self, active_handler):
        prompts = active_handler._get_thought_prompts()
        has_blocked_prompt = any("blockiert" in p.lower() for p in prompts)
        assert has_blocked_prompt


# ═══════════════════════════════════════════════════════════════
# USER CONFIG
# ═══════════════════════════════════════════════════════════════


class TestUserConfig:
    def test_load_default_config(self, handler):
        config = handler._load_user_config()
        assert config["session_duration_minutes"] == 120

    def test_load_custom_config(self, handler, empty_env):
        base, _ = empty_env
        config_path = base / "data" / "user_config.json"
        config_path.write_text(
            json.dumps({"session_duration_minutes": 90}),
            encoding="utf-8"
        )
        config = handler._load_user_config()
        assert config["session_duration_minutes"] == 90

    def test_load_corrupt_config_returns_default(self, handler, empty_env):
        base, _ = empty_env
        config_path = base / "data" / "user_config.json"
        config_path.write_text("not valid json", encoding="utf-8")
        config = handler._load_user_config()
        assert config["session_duration_minutes"] == 120

    def test_load_null_config_returns_default(self, handler, empty_env):
        base, _ = empty_env
        config_path = base / "data" / "user_config.json"
        config_path.write_text("null", encoding="utf-8")
        config = handler._load_user_config()
        assert config["session_duration_minutes"] == 120

    def test_load_list_config_returns_default(self, handler, empty_env):
        base, _ = empty_env
        config_path = base / "data" / "user_config.json"
        config_path.write_text("[1, 2, 3]", encoding="utf-8")
        config = handler._load_user_config()
        assert config["session_duration_minutes"] == 120

    def test_save_config(self, handler, empty_env):
        base, _ = empty_env
        handler._save_user_config({"session_duration_minutes": 60})
        config = handler._load_user_config()
        assert config["session_duration_minutes"] == 60
        assert "last_updated" in config


# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════


class TestHelp:
    def test_help(self, handler):
        ok, output = handler.handle("help", [])
        assert ok is True
        assert "session" in output.lower()

    def test_unknown_op(self, handler):
        ok, output = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte" in output


# ═══════════════════════════════════════════════════════════════
# START DELEGATION
# ═══════════════════════════════════════════════════════════════


class TestStartDelegation:
    def test_start_already_active(self, active_handler):
        ok, output = active_handler.handle("start", [])
        assert ok is True
        assert "bereits aktiv" in output
        assert "sess-active" in output


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import inspect
        source = inspect.getsource(SessionHandler)
        for i, line in enumerate(source.split("\n")):
            stripped = line.strip()
            if stripped == "except:" or stripped == "except: pass":
                pytest.fail(f"Bare except at line {i+1}: {stripped}")
