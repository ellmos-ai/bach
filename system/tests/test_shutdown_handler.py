# -*- coding: utf-8 -*-
"""Tests for ShutdownHandler (hub/shutdown.py)."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hub.shutdown import ShutdownHandler


def _create_schema(conn):
    """Erstellt alle von ShutdownHandler benoetigten Tabellen."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS partner_presence (
            partner_name TEXT PRIMARY KEY,
            status TEXT DEFAULT 'offline',
            clocked_in TEXT,
            clocked_out TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS memory_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            partner_id TEXT,
            started_at TEXT,
            ended_at TEXT,
            summary TEXT,
            tasks_created INTEGER DEFAULT 0,
            tasks_completed INTEGER DEFAULT 0,
            is_compressed INTEGER DEFAULT 0,
            continuation_context TEXT
        );
        CREATE TABLE IF NOT EXISTS memory_working (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            content TEXT,
            priority INTEGER DEFAULT 5,
            created_at TEXT,
            updated_at TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS memory_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            priority INTEGER DEFAULT 5,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            completed_at TEXT
        );
    """)
    conn.commit()


@pytest.fixture
def shutdown_env(tmp_path):
    """Erstellt ShutdownHandler mit temp-DB und Verzeichnisstruktur."""
    base = tmp_path / "bach" / "system"
    (base / "data" / "logs").mkdir(parents=True)
    (base / "hub").mkdir()
    (base / "tools").mkdir()

    db_path = base / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_schema(conn)
    conn.close()

    h = ShutdownHandler(base)
    h.db_path = db_path
    return h, base, db_path


class TestInit:
    def test_profile_name(self, shutdown_env):
        h, _, _ = shutdown_env
        assert h.profile_name == "shutdown"

    def test_target_file(self, shutdown_env):
        h, _, db_path = shutdown_env
        assert h.target_file == db_path

    def test_operations(self, shutdown_env):
        h, _, _ = shutdown_env
        ops = h.get_operations()
        assert "complete" in ops
        assert "quick" in ops
        assert "emergency" in ops


class TestPartnerParsing:
    def test_default_partner(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner"), \
             patch.object(h, "_complete", return_value=(True, "OK")):
            h.handle("", [], dry_run=True)

    def test_explicit_partner_extracted(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner") as mock_clock, \
             patch.object(h, "_complete", return_value=(True, "OK")):
            h.handle("", ["--partner=claude", "some summary"], dry_run=False)
            mock_clock.assert_called_once_with("claude")

    def test_partner_removed_from_args(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner"), \
             patch.object(h, "_complete", return_value=(True, "OK")) as mock_complete:
            h.handle("", ["--partner=claude", "test summary"], dry_run=True)
            _, call_kwargs = mock_complete.call_args
            assert call_kwargs.get("summary") is None or "partner" not in str(mock_complete.call_args)


class TestClockOut:
    def test_clock_out_updates_presence(self, shutdown_env):
        h, _, db_path = shutdown_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO partner_presence (partner_name, status, clocked_in) VALUES (?, ?, ?)",
            ("claude", "online", datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        h._clock_out_partner("claude")

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status, clocked_out FROM partner_presence WHERE partner_name='claude'"
        ).fetchone()
        conn.close()
        assert row[0] == "offline"
        assert row[1] is not None

    def test_clock_out_ignores_offline_partner(self, shutdown_env):
        h, _, db_path = shutdown_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO partner_presence (partner_name, status) VALUES (?, ?)",
            ("test", "offline"),
        )
        conn.commit()
        conn.close()

        h._clock_out_partner("test")

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status, clocked_out FROM partner_presence WHERE partner_name='test'"
        ).fetchone()
        conn.close()
        assert row[0] == "offline"
        assert row[1] is None

    def test_clock_out_nonexistent_partner(self, shutdown_env):
        h, _, _ = shutdown_env
        result = h._clock_out_partner("nobody")
        assert result is True


class TestEmergency:
    def test_emergency_saves_note(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._emergency("System haengt", dry_run=False)
        assert ok is True
        assert "EMERGENCY SHUTDOWN" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT content, type, priority FROM memory_working ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert "System haengt" in row[0]
        assert row[1] == "emergency"
        assert row[2] == 10

    def test_emergency_dry_run(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._emergency("crash", dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0]
        conn.close()
        assert count == 0

    def test_emergency_no_summary(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._emergency(None, dry_run=False)
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT content FROM memory_working").fetchone()
        conn.close()
        assert "Keine Details" in row[0]


class TestQuick:
    def test_quick_saves_note(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._quick("Mittagspause", dry_run=False)
        assert ok is True
        assert "pausiert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT content, type FROM memory_working").fetchone()
        conn.close()
        assert "Mittagspause" in row[0]
        assert row[1] == "note"

    def test_quick_no_summary_skips_db(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._quick(None, dry_run=False)
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0]
        conn.close()
        assert count == 0

    def test_quick_dry_run(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._quick("Test", dry_run=True)
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0]
        conn.close()
        assert count == 0


class TestComplete:
    def test_complete_dry_run(self, shutdown_env):
        h, _, _ = shutdown_env
        ok, msg = h._complete("Test", dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        assert "COMPLETE SHUTDOWN" in msg

    def test_complete_closes_active_session(self, shutdown_env):
        h, _, db_path = shutdown_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_sessions (session_id, started_at) VALUES (?, ?)",
            ("ses_001", datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        with patch("hub.shutdown.ShutdownHandler._complete", wraps=h._complete):
            ok, msg = h._complete("Aufgaben erledigt", dry_run=False)

        assert ok is True
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT ended_at, summary FROM memory_sessions WHERE session_id='ses_001'"
        ).fetchone()
        conn.close()
        assert row[0] is not None
        assert "Aufgaben erledigt" in row[1]

    def test_complete_creates_session_without_active(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._complete("Standalone-Bericht", dry_run=False)
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT session_id, summary FROM memory_sessions").fetchone()
        conn.close()
        assert row is not None
        assert "Standalone-Bericht" in row[1]

    def test_complete_no_summary_no_active_session(self, shutdown_env):
        h, _, db_path = shutdown_env
        ok, msg = h._complete(None, dry_run=False)
        assert ok is True
        assert "Keine aktive Session" in msg

    def test_complete_memory_stats(self, shutdown_env):
        h, _, db_path = shutdown_env
        conn = sqlite3.connect(str(db_path))
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO memory_working (type, content, created_at, updated_at, is_active) VALUES (?, ?, ?, ?, 1)",
            ("note", "test", now, now),
        )
        conn.execute("INSERT INTO memory_facts (fact, created_at) VALUES (?, ?)", ("fakt", now))
        conn.commit()
        conn.close()

        ok, msg = h._complete(None, dry_run=False)
        assert ok is True
        assert "Working: 1" in msg
        assert "Facts: 1" in msg

    def test_complete_task_statistics(self, shutdown_env):
        h, _, db_path = shutdown_env
        now = datetime.now().isoformat()
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_sessions (session_id, started_at) VALUES (?, ?)",
            ("ses_stats", now),
        )
        conn.execute(
            "INSERT INTO tasks (title, priority, status, created_at) VALUES (?, ?, ?, ?)",
            ("Task A", 5, "pending", now),
        )
        conn.execute(
            "INSERT INTO tasks (title, priority, status, created_at, completed_at) VALUES (?, ?, ?, ?, ?)",
            ("Task B", 5, "done", now, now),
        )
        conn.commit()
        conn.close()

        ok, msg = h._complete("stats test", dry_run=False)
        assert ok is True
        assert "+2 erstellt" in msg or "+1 erstellt" in msg


class TestGetActiveSession:
    def test_returns_none_when_no_session(self, shutdown_env):
        h, _, db_path = shutdown_env
        conn = sqlite3.connect(str(db_path))
        result = h._get_active_session(conn)
        conn.close()
        assert result is None

    def test_returns_active_session(self, shutdown_env):
        h, _, db_path = shutdown_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_sessions (session_id, started_at) VALUES (?, ?)",
            ("active_1", "2026-01-01T10:00:00"),
        )
        conn.commit()
        row = h._get_active_session(conn)
        conn.close()
        assert row is not None
        assert row[1] == "active_1"

    def test_ignores_ended_sessions(self, shutdown_env):
        h, _, db_path = shutdown_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_sessions (session_id, started_at, ended_at) VALUES (?, ?, ?)",
            ("ended_1", "2026-01-01T10:00:00", "2026-01-01T12:00:00"),
        )
        conn.commit()
        row = h._get_active_session(conn)
        conn.close()
        assert row is None


class TestFallbackSummary:
    def test_no_autolog_returns_none(self, shutdown_env):
        h, _, _ = shutdown_env
        result = h._generate_fallback_summary("2026-01-01T10:00:00")
        assert result is None

    def test_autolog_extracts_commands(self, shutdown_env):
        h, base, _ = shutdown_env
        autolog = base / "data" / "logs" / "auto_log_extended.txt"
        now = datetime.now()
        autolog.write_text(
            f"[{now.strftime('%H:%M:%S')}] CMD: task list\n"
            f"[{now.strftime('%H:%M:%S')}] CMD: memory search test\n"
            f"[{now.strftime('%H:%M:%S')}] INFO: something\n",
            encoding="utf-8",
        )
        start = (now - timedelta(minutes=5)).isoformat()
        result = h._generate_fallback_summary(start)
        assert result is not None
        assert "AUTO-FALLBACK" in result
        assert "task list" in result

    def test_autolog_ignores_startup_shutdown(self, shutdown_env):
        h, base, _ = shutdown_env
        autolog = base / "data" / "logs" / "auto_log_extended.txt"
        now = datetime.now()
        autolog.write_text(
            f"[{now.strftime('%H:%M:%S')}] CMD: startup\n"
            f"[{now.strftime('%H:%M:%S')}] CMD: shutdown\n",
            encoding="utf-8",
        )
        start = (now - timedelta(minutes=5)).isoformat()
        result = h._generate_fallback_summary(start)
        assert result is not None
        assert "Keine Befehle" in result

    def test_autolog_deduplicates_commands(self, shutdown_env):
        h, base, _ = shutdown_env
        autolog = base / "data" / "logs" / "auto_log_extended.txt"
        now = datetime.now()
        lines = [f"[{now.strftime('%H:%M:%S')}] CMD: task list\n"] * 5
        autolog.write_text("".join(lines), encoding="utf-8")
        start = (now - timedelta(minutes=5)).isoformat()
        result = h._generate_fallback_summary(start)
        assert "5 (1 unique)" in result

    def test_autolog_bad_format_returns_error(self, shutdown_env):
        h, base, _ = shutdown_env
        autolog = base / "data" / "logs" / "auto_log_extended.txt"
        autolog.write_text("totally broken\n", encoding="utf-8")
        result = h._generate_fallback_summary("2026-01-01T10:00:00")
        assert result is not None


class TestHooksScope:
    def test_after_shutdown_hook_reimports(self, shutdown_env):
        h, _, _ = shutdown_env
        mock_hooks = MagicMock()
        mock_module = MagicMock()
        mock_module.hooks = mock_hooks

        with patch.object(h, "_clock_out_partner"), \
             patch.object(h, "_complete", return_value=(True, "OK")), \
             patch.dict("sys.modules", {"core.hooks": mock_module}):
            ok, msg = h.handle("", [], dry_run=True)

        assert ok is True

    def test_hook_import_failure_does_not_crash(self, shutdown_env):
        h, _, _ = shutdown_env

        with patch.object(h, "_clock_out_partner"), \
             patch.object(h, "_complete", return_value=(True, "OK")), \
             patch.dict("sys.modules", {"core.hooks": None}):
            ok, msg = h.handle("", [], dry_run=True)

        assert ok is True


class TestHandleDispatch:
    def test_dispatch_emergency(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner"):
            ok, msg = h.handle("emergency", ["Panik!"], dry_run=False)
        assert ok is True
        assert "EMERGENCY" in msg

    def test_dispatch_quick(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner"):
            ok, msg = h.handle("quick", ["Pause"], dry_run=False)
        assert ok is True
        assert "QUICK" in msg

    def test_dispatch_complete(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner"):
            ok, msg = h.handle("complete", [], dry_run=True)
        assert ok is True
        assert "COMPLETE" in msg

    def test_dispatch_default_is_complete(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner"):
            ok, msg = h.handle("", [], dry_run=True)
        assert ok is True
        assert "COMPLETE" in msg

    def test_dry_run_skips_clock_out(self, shutdown_env):
        h, _, _ = shutdown_env
        with patch.object(h, "_clock_out_partner") as mock_clock:
            h.handle("quick", [], dry_run=True)
        mock_clock.assert_not_called()
