# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for MemoryHandler (hub/memory.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.memory import MemoryHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_memory_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_working (
            id INTEGER PRIMARY KEY,
            type TEXT DEFAULT 'note',
            content TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_facts (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source TEXT DEFAULT 'cli',
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(category, key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_lessons (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            solution TEXT DEFAULT '',
            severity TEXT DEFAULT 'medium',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            partner_id TEXT DEFAULT '',
            started_at TEXT,
            ended_at TEXT,
            summary TEXT DEFAULT '',
            tasks_created INTEGER DEFAULT 0,
            tasks_completed INTEGER DEFAULT 0,
            continuation_context TEXT DEFAULT ''
        )
    """)
    conn.commit()


def _seed_memory(conn):
    conn.executemany(
        "INSERT INTO memory_working (type, content, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        [
            ("note", "Python-Migration auf 3.12 planen", 1, "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("context", "BACH v3.9.2 Release vorbereiten", 1, "2026-05-15T11:00:00", "2026-05-15T11:00:00"),
            ("note", "Alte Notiz deaktiviert", 0, "2026-05-14T09:00:00", "2026-05-14T09:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO memory_facts (category, key, value, confidence, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("user", "name", "Lukas", 1.0, "explicit", "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("project", "version", "3.9.2", 0.9, "cli", "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("system", "os", "Windows 11", 0.7, "inferred", "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("project", "deadline", "2026-06-01", 0.3, "mentioned", "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO memory_lessons (title, solution, severity, is_active, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            ("UTF-8 Encoding", "PYTHONIOENCODING=utf-8 setzen", "high", 1, "2026-05-15T10:00:00"),
            ("NUL-Dateien", "Kein /dev/null auf Windows", "medium", 1, "2026-05-15T10:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO memory_sessions (session_id, partner_id, started_at, ended_at, summary) VALUES (?, ?, ?, ?, ?)",
        [
            ("session_20260515_100000", "claude", "2026-05-15T10:00:00", "2026-05-15T12:00:00", "BACH Handler-Tests geschrieben"),
            ("session_20260514_100000", "claude", "2026-05-14T10:00:00", "2026-05-14T11:00:00", "Bare-except Cleanup"),
        ],
    )
    conn.commit()


@pytest.fixture
def mem_env(tmp_path, monkeypatch):
    """Minimal env with memory tables and seed data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_memory_tables(conn)
    _seed_memory(conn)
    conn.close()

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def empty_mem_env(tmp_path, monkeypatch):
    """Env with tables but no data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_memory_tables(conn)
    conn.close()

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


# ═══════════════════════════════════════════════════════════════
# TESTS: Init & Operations
# ═══════════════════════════════════════════════════════════════


class TestMemoryInit:
    def test_handler_creates(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        assert handler.profile_name == "memory"

    def test_get_operations(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ops = handler.get_operations()
        assert "status" in ops
        assert "write" in ops
        assert "read" in ops
        assert "fact" in ops
        assert "search" in ops
        assert "context" in ops
        assert "clear" in ops

    def test_missing_db(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "data" / "nonexistent.db"
        monkeypatch.setattr("hub.bach_paths.BACH_DB", fake_db)
        handler = MemoryHandler(tmp_path)
        ok, msg = handler.handle("status", [], dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg.lower() or "not found" in msg.lower()


# ═══════════════════════════════════════════════════════════════
# TESTS: Status
# ═══════════════════════════════════════════════════════════════


class TestMemoryStatus:
    def test_status_shows_counts(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("status", [], dry_run=False)
        assert ok
        assert "2" in msg  # 2 active working notes
        assert "4" in msg  # 4 facts
        assert "2" in msg  # 2 lessons

    def test_status_empty_db(self, empty_mem_env):
        base, _ = empty_mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("status", [], dry_run=False)
        assert ok
        assert "0" in msg

    def test_unknown_operation_falls_back_to_status(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("nonexistent_op", [], dry_run=False)
        assert ok
        assert "MEMORY STATUS" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Write
# ═══════════════════════════════════════════════════════════════


class TestMemoryWrite:
    def test_write_stores_note(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("write", ["Neue", "Testnotiz"], dry_run=False)
        assert ok
        assert "gespeichert" in msg.lower() or "ok" in msg.lower()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT content FROM memory_working WHERE content LIKE '%Testnotiz%'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert "Neue Testnotiz" in row[0]

    def test_write_dry_run(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("write", ["Dry-Run-Notiz"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT content FROM memory_working WHERE content LIKE '%Dry-Run%'"
        ).fetchone()
        conn.close()
        assert row is None

    def test_write_no_args(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("write", [], dry_run=False)
        assert not ok
        assert "usage" in msg.lower()

    def test_write_unicode(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("write", ["Ärger mit Ölförderung über Bürokratie"], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT content FROM memory_working WHERE content LIKE '%Ölförderung%'"
        ).fetchone()
        conn.close()
        assert row is not None


# ═══════════════════════════════════════════════════════════════
# TESTS: Read
# ═══════════════════════════════════════════════════════════════


class TestMemoryRead:
    def test_read_default(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("read", [], dry_run=False)
        assert ok
        assert "Migration" in msg or "Release" in msg

    def test_read_limit(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("read", ["1"], dry_run=False)
        assert ok
        assert "letzte 1" in msg.lower()

    def test_read_excludes_inactive(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("read", ["100"], dry_run=False)
        assert ok
        assert "deaktiviert" not in msg

    def test_read_empty_db(self, empty_mem_env):
        base, _ = empty_mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("read", [], dry_run=False)
        assert ok
        assert "keine" in msg.lower()


# ═══════════════════════════════════════════════════════════════
# TESTS: Facts
# ═══════════════════════════════════════════════════════════════


class TestMemoryFacts:
    def test_add_fact_with_category(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("fact", ["user.email:test@example.com"], dry_run=False)
        assert ok
        assert "gespeichert" in msg.lower() or "ok" in msg.lower()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT value FROM memory_facts WHERE category='user' AND key='email'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "test@example.com"

    def test_add_fact_without_category_defaults_to_project(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("fact", ["tool_count:199"], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT category FROM memory_facts WHERE key='tool_count'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "project"

    def test_add_fact_with_confidence(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("fact", ["project.eta:June", "--conf=0.4"], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT confidence FROM memory_facts WHERE key='eta'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(row[0] - 0.4) < 0.01

    def test_add_fact_clamps_confidence(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, _ = handler.handle("fact", ["test.clamp:value", "--conf=5.0"], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT confidence FROM memory_facts WHERE key='clamp'"
        ).fetchone()
        conn.close()
        assert row[0] <= 1.0

    def test_add_fact_invalid_category_defaults(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("fact", ["invalid_cat.key:val"], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT category FROM memory_facts WHERE key='key'"
        ).fetchone()
        conn.close()
        assert row[0] == "project"

    def test_add_fact_no_colon_fails(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("fact", ["no_colon_here"], dry_run=False)
        assert not ok
        assert "format" in msg.lower() or "key:value" in msg.lower()

    def test_add_fact_no_args(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("fact", [], dry_run=False)
        assert not ok

    def test_add_fact_upsert_overwrites(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        handler.handle("fact", ["user.name:Updated"], dry_run=False)

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT value FROM memory_facts WHERE category='user' AND key='name'"
        ).fetchone()
        conn.close()
        assert row[0] == "Updated"

    def test_add_fact_dry_run(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("fact", ["test.drykey:dryval"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_list_facts_all(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("facts", [], dry_run=False)
        assert ok
        assert "name" in msg.lower()
        assert "version" in msg.lower()

    def test_list_facts_by_category(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("facts", ["user"], dry_run=False)
        assert ok
        assert "name" in msg.lower()
        assert "version" not in msg.lower()

    def test_list_facts_min_confidence(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("facts", ["--min-conf=0.8"], dry_run=False)
        assert ok
        assert "deadline" not in msg.lower()

    def test_list_facts_empty(self, empty_mem_env):
        base, _ = empty_mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("facts", [], dry_run=False)
        assert ok
        assert "keine" in msg.lower()

    def test_certain_facts(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("certain", [], dry_run=False)
        assert ok
        assert "name" in msg.lower()

    def test_uncertain_facts(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("uncertain", [], dry_run=False)
        assert ok
        assert "deadline" in msg.lower()

    def test_uncertain_empty(self, empty_mem_env):
        base, _ = empty_mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("uncertain", [], dry_run=False)
        assert ok
        assert "keine" in msg.lower() or "0.5" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Confidence Update
# ═══════════════════════════════════════════════════════════════


class TestMemoryConfidence:
    def test_update_confidence(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("confidence", ["project.deadline", "0.9"], dry_run=False)
        assert ok
        assert "aktualisiert" in msg.lower() or "ok" in msg.lower()

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT confidence FROM memory_facts WHERE category='project' AND key='deadline'"
        ).fetchone()
        conn.close()
        assert abs(row[0] - 0.9) < 0.01

    def test_update_confidence_not_found(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("confidence", ["nonexistent.key", "0.5"], dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg.lower()

    def test_update_confidence_missing_args(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("confidence", ["only_one_arg"], dry_run=False)
        assert not ok

    def test_update_confidence_invalid_number(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("confidence", ["user.name", "not_a_number"], dry_run=False)
        assert not ok

    def test_update_confidence_dry_run(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("confidence", ["user.name", "0.1"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_update_confidence_clamps_to_range(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, _ = handler.handle("confidence", ["user.name", "99.0"], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT confidence FROM memory_facts WHERE category='user' AND key='name'"
        ).fetchone()
        conn.close()
        assert row[0] <= 1.0


# ═══════════════════════════════════════════════════════════════
# TESTS: Search
# ═══════════════════════════════════════════════════════════════


class TestMemorySearch:
    def test_search_finds_working_notes(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("search", ["Migration"], dry_run=False)
        assert ok
        assert "migration" in msg.lower() or "Migration" in msg

    def test_search_finds_facts(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("search", ["Lukas"], dry_run=False)
        assert ok
        assert "lukas" in msg.lower() or "Lukas" in msg

    def test_search_finds_lessons(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("search", ["UTF-8"], dry_run=False)
        assert ok
        assert "utf" in msg.lower()

    def test_search_no_results(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("search", ["zzz_impossible_zzz"], dry_run=False)
        assert ok
        assert "keine" in msg.lower() or "0" in msg

    def test_search_no_args(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("search", [], dry_run=False)
        assert not ok

    def test_search_multi_keyword(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("search", ["Python", "Migration"], dry_run=False)
        assert ok
        assert "treffer" in msg.lower() or "Treffer" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Context Generation
# ═══════════════════════════════════════════════════════════════


class TestMemoryContext:
    def test_context_includes_notes(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("context", [], dry_run=False)
        assert ok
        assert "notizen" in msg.lower() or "Notizen" in msg

    def test_context_includes_facts(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("context", [], dry_run=False)
        assert ok
        assert "fakten" in msg.lower() or "Fakten" in msg

    def test_context_empty_db(self, empty_mem_env):
        base, _ = empty_mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("context", [], dry_run=False)
        assert ok
        assert "kein" in msg.lower() or "verfuegbar" in msg.lower()


# ═══════════════════════════════════════════════════════════════
# TESTS: Clear & Session
# ═══════════════════════════════════════════════════════════════


class TestMemoryClear:
    def test_clear_working(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("clear", [], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_working WHERE is_active=1"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_clear_dry_run(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("clear", [], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_working WHERE is_active=1"
        ).fetchone()[0]
        conn.close()
        assert count > 0


class TestMemorySessions:
    def test_save_session(self, mem_env):
        base, db_path = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("session", ["Test-Session abgeschlossen"], dry_run=False)
        assert ok

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT summary FROM memory_sessions WHERE summary LIKE '%Test-Session%'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_save_session_no_args(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("session", [], dry_run=False)
        assert not ok

    def test_save_session_dry_run(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("session", ["Dry-Run-Session"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_list_sessions(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("sessions", [], dry_run=False)
        assert ok
        assert "handler" in msg.lower() or "cleanup" in msg.lower() or "claude" in msg.lower()

    def test_list_sessions_empty(self, empty_mem_env):
        base, _ = empty_mem_env
        handler = MemoryHandler(base)
        ok, msg = handler.handle("sessions", [], dry_run=False)
        assert ok
        assert "keine" in msg.lower()


# ═══════════════════════════════════════════════════════════════
# TESTS: Confidence Bar (Internal)
# ═══════════════════════════════════════════════════════════════


class TestConfidenceBar:
    def test_full_confidence(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        bar = handler._confidence_bar(1.0)
        assert "*****" in bar
        assert "-" not in bar.split("]")[0]

    def test_zero_confidence(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        bar = handler._confidence_bar(0.0)
        assert "-----" in bar
        assert "*" not in bar.split("]")[0]

    def test_half_confidence(self, mem_env):
        base, _ = mem_env
        handler = MemoryHandler(base)
        bar = handler._confidence_bar(0.5)
        assert "**" in bar
        assert "---" in bar
