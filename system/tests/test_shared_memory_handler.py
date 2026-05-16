# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SharedMemoryHandler (hub/shared_memory.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.shared_memory import SharedMemoryHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_shared_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shared_memory_facts (
            id INTEGER PRIMARY KEY,
            agent_id TEXT,
            namespace TEXT DEFAULT 'default',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            visibility TEXT DEFAULT 'global',
            confidence REAL DEFAULT 0.5,
            created_at TEXT,
            updated_at TEXT,
            modified_by TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shared_memory_lessons (
            id INTEGER PRIMARY KEY,
            agent_id TEXT,
            namespace TEXT DEFAULT 'default',
            visibility TEXT DEFAULT 'global',
            severity TEXT DEFAULT 'info',
            title TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            times_shown INTEGER DEFAULT 0,
            confidence REAL DEFAULT 1.0,
            source TEXT DEFAULT 'cli',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shared_memory_working (
            id INTEGER PRIMARY KEY,
            agent_id TEXT,
            session_id TEXT,
            type TEXT DEFAULT 'note',
            content TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            expires_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shared_memory_sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            agent_id TEXT,
            started_at TEXT,
            ended_at TEXT,
            tasks_completed INTEGER DEFAULT 0,
            is_archived INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shared_memory_consolidation (
            id INTEGER PRIMARY KEY,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            agent_id TEXT,
            times_accessed INTEGER DEFAULT 0,
            weight REAL DEFAULT 0.5,
            decay_rate REAL DEFAULT 0.95,
            threshold REAL DEFAULT 0.1,
            status TEXT DEFAULT 'active',
            last_accessed TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shared_context_triggers (
            id INTEGER PRIMARY KEY,
            agent_id TEXT,
            namespace TEXT DEFAULT 'default',
            trigger_phrase TEXT NOT NULL,
            hint_text TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            status TEXT DEFAULT 'approved',
            usage_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()


def _seed_shared(conn):
    conn.executemany(
        "INSERT INTO shared_memory_facts (agent_id, namespace, key, value, visibility, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("claude", "default", "system_os", "Windows 11", "global", 0.9, "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("gemini", "default", "python_version", "3.13", "global", 0.8, "2026-05-15T11:00:00", "2026-05-15T11:00:00"),
            (None, "project", "bach_version", "3.9.2", "team", 0.7, "2026-05-15T09:00:00", "2026-05-15T09:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO shared_memory_lessons (agent_id, namespace, visibility, severity, title, is_active, times_shown, confidence, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("claude", "default", "global", "high", "UTF-8 Encoding setzen", 1, 5, 1.0, "cli", "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("gemini", "default", "global", "medium", "OneDrive Lock-Files pruefen", 1, 2, 0.8, "auto", "2026-05-15T11:00:00", "2026-05-15T11:00:00"),
            (None, "default", "global", "low", "Alte Lesson inaktiv", 0, 0, 0.5, "cli", "2026-05-14T10:00:00", "2026-05-14T10:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO shared_memory_working (agent_id, session_id, type, content, priority, is_active, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("claude", "ses-001", "note", "DB-Pfad-Fixes durchfuehren", 3, 1, None, "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("claude", "ses-001", "current_task", "Test-Suite schreiben", 9, 1, None, "2026-05-15T11:00:00", "2026-05-15T11:00:00"),
            ("gemini", None, "note", "Abgelaufene Notiz", 0, 1, "2026-01-01T00:00:00", "2026-05-14T10:00:00", "2026-05-14T10:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO shared_memory_sessions (session_id, agent_id, started_at, ended_at, tasks_completed, is_archived) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("ses-001", "claude", "2026-05-15T10:00:00", None, 5, 0),
            ("ses-002", "gemini", "2026-05-14T10:00:00", "2026-05-14T12:00:00", 3, 0),
            ("ses-old", "claude", "2026-01-01T10:00:00", "2026-01-01T12:00:00", 1, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO shared_memory_consolidation (source_table, source_id, agent_id, times_accessed, weight, decay_rate, threshold, status, last_accessed, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("facts", 1, "claude", 10, 0.9, 0.95, 0.1, "active", "2026-05-15T10:00:00", "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            ("lessons", 1, "gemini", 3, 0.5, 0.95, 0.1, "active", "2026-05-14T10:00:00", "2026-05-14T10:00:00", "2026-05-14T10:00:00"),
            ("facts", 2, None, 0, 0.05, 0.95, 0.1, "active", None, "2026-05-13T10:00:00", "2026-05-13T10:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO shared_context_triggers (agent_id, namespace, trigger_phrase, hint_text, is_active, status, usage_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("claude", "default", "deployment", "Pruefe Server-Zustand vor Deploy", 1, "approved", 7, "2026-05-15T10:00:00", "2026-05-15T10:00:00"),
            (None, "default", "backup", "Erstelle DB-Backup vor grossen Aenderungen", 1, "approved", 3, "2026-05-15T11:00:00", "2026-05-15T11:00:00"),
            ("gemini", "default", "deactivated_trigger", "Sollte nicht angezeigt werden", 0, "draft", 0, "2026-05-14T10:00:00", "2026-05-14T10:00:00"),
        ],
    )
    conn.commit()


@pytest.fixture
def smem_env(tmp_path, monkeypatch):
    """Shared memory env with tables and seed data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_shared_tables(conn)
    _seed_shared(conn)
    conn.close()

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def empty_smem_env(tmp_path, monkeypatch):
    """Shared memory env with tables but no data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_shared_tables(conn)
    conn.close()

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


# ═══════════════════════════════════════════════════════════════
# TESTS: Init & Operations
# ═══════════════════════════════════════════════════════════════


class TestSharedMemoryInit:
    def test_handler_creates(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        assert handler.profile_name == "shared-mem"

    def test_get_operations(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ops = handler.get_operations()
        assert "facts" in ops
        assert "lessons" in ops
        assert "working" in ops
        assert "sessions" in ops
        assert "consolidation" in ops
        assert "triggers" in ops
        assert "context" in ops
        assert "changes" in ops

    def test_handle_unknown_operation(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("nonexistent", [])
        assert not ok
        assert "Unbekannte Operation" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Facts
# ═══════════════════════════════════════════════════════════════


class TestFacts:
    def test_facts_list(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["list"])
        assert ok
        assert "system_os" in msg
        assert "python_version" in msg
        assert "bach_version" in msg

    def test_facts_list_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["list"])
        assert ok
        assert "Keine" in msg

    def test_facts_list_default(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", [])
        assert ok
        assert "Shared Memory Facts" in msg

    def test_facts_add(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["add", "test_key", "test_value"])
        assert ok
        assert "hinzugefuegt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT key, value FROM shared_memory_facts WHERE key = 'test_key'").fetchone()
        conn.close()
        assert row is not None
        assert row[1] == "test_value"

    def test_facts_add_with_flags(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", [
            "add", "flagged_key", "flagged_value",
            "--agent", "test-agent",
            "--namespace", "test-ns",
            "--visibility", "private",
            "--confidence", "0.75"
        ])
        assert ok

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT agent_id, namespace, visibility, confidence FROM shared_memory_facts WHERE key = 'flagged_key'"
        ).fetchone()
        conn.close()
        assert row == ("test-agent", "test-ns", "private", 0.75)

    def test_facts_add_missing_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["add"])
        assert not ok
        assert "Verwendung" in msg or "erforderlich" in msg

    def test_facts_add_dry_run(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["add", "dry_key", "dry_val"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM shared_memory_facts WHERE key = 'dry_key'").fetchone()
        conn.close()
        assert row is None

    def test_facts_add_conflict_resolution_higher_confidence(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", [
            "add", "system_os", "Windows 12",
            "--agent", "claude",
            "--confidence", "0.95"
        ])
        assert ok
        assert "aktualisiert" in msg
        assert "Conflict Resolution" in msg

    def test_facts_add_conflict_resolution_lower_confidence(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", [
            "add", "system_os", "Linux",
            "--agent", "claude",
            "--confidence", "0.1"
        ])
        assert ok
        assert "NICHT aktualisiert" in msg

    def test_facts_get(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["get", "1"])
        assert ok
        assert "system_os" in msg
        assert "Windows 11" in msg

    def test_facts_get_not_found(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["get", "9999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_facts_get_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["get"])
        assert not ok
        assert "Verwendung" in msg

    def test_facts_delete(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["delete", "1"])
        assert ok
        assert "gelöscht" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM shared_memory_facts WHERE id = 1").fetchone()
        conn.close()
        assert row is None

    def test_facts_delete_not_found(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["delete", "9999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_facts_delete_dry_run(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["delete", "1"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM shared_memory_facts WHERE id = 1").fetchone()
        conn.close()
        assert row is not None

    def test_facts_unknown_subop(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("facts", ["bogus"])
        assert not ok
        assert "Unbekannte" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Lessons
# ═══════════════════════════════════════════════════════════════


class TestLessons:
    def test_lessons_list(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["list"])
        assert ok
        assert "UTF-8" in msg
        assert "OneDrive" in msg

    def test_lessons_list_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["list"])
        assert ok
        assert "Keine" in msg

    def test_lessons_add(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["add", "Neue", "Lesson", "--severity", "critical"])
        assert ok
        assert "hinzugefügt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT title, severity FROM shared_memory_lessons WHERE title LIKE '%Neue Lesson%'").fetchone()
        conn.close()
        assert row is not None
        assert row[1] == "critical"

    def test_lessons_add_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["add"])
        assert not ok
        assert "Verwendung" in msg

    def test_lessons_add_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["add", "DryLesson"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_lessons_activate(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["activate", "3"])
        assert ok
        assert "aktiviert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT is_active FROM shared_memory_lessons WHERE id = 3").fetchone()
        conn.close()
        assert row[0] == 1

    def test_lessons_activate_not_found(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["activate", "9999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_lessons_deactivate(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["deactivate", "1"])
        assert ok
        assert "deaktiviert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT is_active FROM shared_memory_lessons WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == 0

    def test_lessons_deactivate_not_found(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["deactivate", "9999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_lessons_unknown_subop(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("lessons", ["bogus"])
        assert not ok
        assert "Unbekannte" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Working Memory
# ═══════════════════════════════════════════════════════════════


class TestWorking:
    def test_working_list(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["list"])
        assert ok
        assert "DB-Pfad-Fixes" in msg or "Test-Suite" in msg

    def test_working_list_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["list"])
        assert ok
        assert "leer" in msg

    def test_working_add(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["add", "Neue", "Notiz", "--type", "context", "--priority", "5"])
        assert ok
        assert "hinzugefügt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT type, priority FROM shared_memory_working WHERE content LIKE '%Neue Notiz%'").fetchone()
        conn.close()
        assert row == ("context", 5)

    def test_working_add_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["add"])
        assert not ok
        assert "Verwendung" in msg

    def test_working_add_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["add", "DryNote"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_working_cleanup(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["cleanup"])
        assert ok
        assert "1" in msg and "gelöscht" in msg

    def test_working_cleanup_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["cleanup"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_working_current_task(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["current-task", "Neuer", "Task", "--agent", "test"])
        assert ok
        assert "Current Task gesetzt" in msg

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT content, is_active FROM shared_memory_working WHERE type = 'current_task' AND agent_id = 'test'"
        ).fetchall()
        conn.close()
        active = [r for r in rows if r[1] == 1]
        assert len(active) == 1
        assert "Neuer Task" in active[0][0]

    def test_working_current_task_deactivates_previous(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        handler.handle("working", ["current-task", "Erster Task", "--agent", "claude"])
        handler.handle("working", ["current-task", "Zweiter Task", "--agent", "claude"])

        conn = sqlite3.connect(str(db_path))
        active = conn.execute(
            "SELECT content FROM shared_memory_working WHERE type = 'current_task' AND agent_id = 'claude' AND is_active = 1"
        ).fetchall()
        conn.close()
        assert len(active) == 1
        assert "Zweiter Task" in active[0][0]

    def test_working_current_task_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["current-task"])
        assert not ok
        assert "Verwendung" in msg

    def test_working_current_task_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["current-task", "DryTask"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_working_unknown_subop(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("working", ["bogus"])
        assert not ok
        assert "Unbekannte" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Sessions
# ═══════════════════════════════════════════════════════════════


class TestSessions:
    def test_sessions_list(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["list"])
        assert ok
        assert "ses-001" in msg
        assert "ACTIVE" in msg

    def test_sessions_list_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["list"])
        assert ok
        assert "Keine" in msg

    def test_sessions_list_with_limit(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["list", "1"])
        assert ok
        assert "Top 1" in msg

    def test_sessions_current(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["current"])
        assert ok
        assert "ses-001" in msg
        assert "Aktive Sessions" in msg

    def test_sessions_current_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["current"])
        assert ok
        assert "Keine aktiven" in msg

    def test_sessions_archive(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["archive", "30"])
        assert ok
        assert "archiviert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT is_archived FROM shared_memory_sessions WHERE session_id = 'ses-old'").fetchone()
        conn.close()
        assert row[0] == 1

    def test_sessions_archive_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["archive", "30"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_sessions_archive_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["archive"])
        assert not ok
        assert "Verwendung" in msg

    def test_sessions_unknown_subop(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("sessions", ["bogus"])
        assert not ok
        assert "Unbekannte" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Consolidation
# ═══════════════════════════════════════════════════════════════


class TestConsolidation:
    def test_consolidation_list(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["list"])
        assert ok
        assert "facts:1" in msg or "facts" in msg

    def test_consolidation_list_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["list"])
        assert ok
        assert "Keine" in msg

    def test_consolidation_stats(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["stats"])
        assert ok
        assert "Total Entries: 3" in msg
        assert "Active: 3" in msg

    def test_consolidation_stats_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["stats"])
        assert ok
        assert "Total Entries: 0" in msg

    def test_consolidation_add(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["add", "working", "1", "--agent", "test"])
        assert ok
        assert "hinzugefügt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT source_table, source_id, agent_id FROM shared_memory_consolidation WHERE source_table = 'working' AND source_id = 1"
        ).fetchone()
        conn.close()
        assert row == ("working", 1, "test")

    def test_consolidation_add_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["add"])
        assert not ok
        assert "Verwendung" in msg

    def test_consolidation_add_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["add", "facts", "99"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_consolidation_consolidate(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["consolidate", "0.1"])
        assert ok
        assert "konsolidiert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status FROM shared_memory_consolidation WHERE source_table = 'facts' AND source_id = 2"
        ).fetchone()
        conn.close()
        assert row[0] == "consolidated"

    def test_consolidation_consolidate_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["consolidate", "0.1"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_consolidation_run_decay(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["run"])
        assert ok
        assert "Decay ausgefuehrt" in msg
        assert "archiviert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT weight, status FROM shared_memory_consolidation WHERE id = 1").fetchone()
        conn.close()
        assert row[0] < 0.9
        assert abs(row[0] - 0.9 * 0.95) < 0.001

    def test_consolidation_run_decay_archives_low_weight(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["run"])
        assert ok

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT status FROM shared_memory_consolidation WHERE id = 3").fetchone()
        conn.close()
        assert row[0] == "archived"

    def test_consolidation_run_decay_dry_run(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["run"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT weight FROM shared_memory_consolidation WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == 0.9

    def test_consolidation_run_decay_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["run"])
        assert ok
        assert "Keine aktiven" in msg

    def test_consolidation_unknown_subop(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("consolidation", ["bogus"])
        assert not ok
        assert "Unbekannte" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Triggers
# ═══════════════════════════════════════════════════════════════


class TestTriggers:
    def test_triggers_list(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["list"])
        assert ok
        assert "deployment" in msg
        assert "backup" in msg

    def test_triggers_list_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["list"])
        assert ok
        assert "Keine" in msg

    def test_triggers_list_all(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["list", "--all"])
        assert ok
        assert "deactivated_trigger" in msg

    def test_triggers_add(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["add", "migration", "DB-Backup vor Migration erstellen"])
        assert ok
        assert "hinzugefügt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT trigger_phrase, hint_text FROM shared_context_triggers WHERE trigger_phrase = 'migration'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert "DB-Backup" in row[1]

    def test_triggers_add_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["add"])
        assert not ok
        assert "Verwendung" in msg

    def test_triggers_add_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["add", "dry", "DryHint"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_triggers_activate(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["activate", "3"])
        assert ok
        assert "aktiviert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT is_active FROM shared_context_triggers WHERE id = 3").fetchone()
        conn.close()
        assert row[0] == 1

    def test_triggers_activate_not_found(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["activate", "9999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_triggers_deactivate(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["deactivate", "1"])
        assert ok
        assert "deaktiviert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT is_active FROM shared_context_triggers WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == 0

    def test_triggers_deactivate_not_found(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["deactivate", "9999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_triggers_delete(self, smem_env):
        base, db_path = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["delete", "1"])
        assert ok
        assert "gelöscht" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM shared_context_triggers WHERE id = 1").fetchone()
        conn.close()
        assert row is None

    def test_triggers_delete_not_found(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["delete", "9999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_triggers_delete_dry_run(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["delete", "1"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_triggers_unknown_subop(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("triggers", ["bogus"])
        assert not ok
        assert "Unbekannte" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Context (B55)
# ═══════════════════════════════════════════════════════════════


class TestContext:
    def test_generate_context(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("context", [])
        assert ok
        assert "Shared Memory Context" in msg
        assert "Current Tasks" in msg
        assert "Top Facts" in msg
        assert "Aktive Lessons" in msg

    def test_generate_context_contains_data(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("context", [])
        assert ok
        assert "Test-Suite" in msg
        assert "system_os" in msg
        assert "UTF-8" in msg

    def test_generate_context_empty(self, empty_smem_env):
        base, _ = empty_smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("context", [])
        assert ok
        assert "Kein aktiver Task" in msg
        assert "Keine Facts" in msg
        assert "Keine aktiven Lessons" in msg


# ═══════════════════════════════════════════════════════════════
# TESTS: Changes (B58)
# ═══════════════════════════════════════════════════════════════


class TestChanges:
    def test_get_changes(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("changes", ["2026-05-15T00:00:00"])
        assert ok
        assert "Aenderungen seit" in msg
        assert "Facts" in msg

    def test_get_changes_no_results(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("changes", ["2099-01-01T00:00:00"])
        assert ok
        assert "Keine Aenderungen" in msg

    def test_get_changes_no_args(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("changes", [])
        assert not ok
        assert "Verwendung" in msg

    def test_get_changes_includes_all_types(self, smem_env):
        base, _ = smem_env
        handler = SharedMemoryHandler(base)
        ok, msg = handler.handle("changes", ["2026-05-14T00:00:00"])
        assert ok
        assert "Facts" in msg
        assert "Lessons" in msg
        assert "Working Memory" in msg
