# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ScanHandler (hub/scan.py)."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.scan import ScanHandler


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


def _create_ati_tables(conn):
    """Create the ATI schema in-memory."""
    conn.executescript("""
        CREATE TABLE ati_scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            duration_seconds REAL,
            tools_scanned INTEGER DEFAULT 0,
            tasks_found INTEGER DEFAULT 0,
            tasks_new INTEGER DEFAULT 0,
            tasks_updated INTEGER DEFAULT 0,
            tasks_removed INTEGER DEFAULT 0,
            triggered_by TEXT,
            errors TEXT
        );

        CREATE TABLE ati_tool_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'aktiv',
            has_aufgaben INTEGER DEFAULT 0,
            has_test INTEGER DEFAULT 0,
            has_feedback INTEGER DEFAULT 0,
            task_count INTEGER DEFAULT 0,
            last_scan TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE ati_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            tool_path TEXT NOT NULL,
            task_text TEXT NOT NULL,
            aufwand TEXT DEFAULT 'mittel',
            status TEXT DEFAULT 'offen',
            priority_score REAL DEFAULT 0,
            source_file TEXT NOT NULL,
            line_number INTEGER,
            file_hash TEXT,
            last_modified TEXT,
            synced_at TEXT,
            is_synced INTEGER DEFAULT 1,
            tags TEXT,
            depends_on TEXT,
            created_at TEXT
        );
    """)


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def scan_env(tmp_path, monkeypatch):
    """Minimal env with ATI tables."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    scanner_dir = tmp_path / "scanner"
    scanner_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_ati_tables(conn)
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def seeded_scan_env(tmp_path, monkeypatch):
    """Env with pre-existing scan data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    scanner_dir = tmp_path / "scanner"
    scanner_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_ati_tables(conn)

    # Seed scan run
    conn.execute("""
        INSERT INTO ati_scan_runs (started_at, finished_at, duration_seconds,
                                   tools_scanned, tasks_found, tasks_new, tasks_updated)
        VALUES ('2026-05-17 10:00:00', '2026-05-17 10:00:05', 5.2, 12, 45, 3, 7)
    """)

    # Seed tools
    conn.execute("""
        INSERT INTO ati_tool_registry (name, path, status, task_count, last_scan)
        VALUES ('TestTool', '/path/to/tool', 'aktiv', 5, '2026-05-17 10:00:05')
    """)
    conn.execute("""
        INSERT INTO ati_tool_registry (name, path, status, task_count, last_scan)
        VALUES ('OtherTool', '/path/to/other', 'aktiv', 3, '2026-05-16 08:00:00')
    """)

    # Seed tasks
    conn.execute("""
        INSERT INTO ati_tasks (tool_name, tool_path, task_text, aufwand, status, priority_score, source_file)
        VALUES ('TestTool', '/path/to/tool', 'Fix the parser bug', 'hoch', 'offen', 8.5, 'TODO.md')
    """)
    conn.execute("""
        INSERT INTO ati_tasks (tool_name, tool_path, task_text, aufwand, status, priority_score, source_file)
        VALUES ('TestTool', '/path/to/tool', 'Add unit tests', 'mittel', 'offen', 5.0, 'TODO.md')
    """)
    conn.execute("""
        INSERT INTO ati_tasks (tool_name, tool_path, task_text, aufwand, status, priority_score, source_file)
        VALUES ('OtherTool', '/path/to/other', 'Update README', 'klein', 'erledigt', 2.0, 'AUFGABEN.md')
    """)

    conn.commit()
    conn.close()
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def handler(scan_env):
    base, _ = scan_env
    return ScanHandler(base)


@pytest.fixture
def seeded_handler(seeded_scan_env):
    base, _ = seeded_scan_env
    return ScanHandler(base)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "scan"

    def test_target_file(self, handler):
        assert handler.target_file == handler.base_path / "scanner"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "run" in ops
        assert "status" in ops
        assert "tasks" in ops
        assert "tools" in ops
        assert "dir" in ops


# ═══════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_no_scans(self, handler):
        ok, output = handler.handle("status", [])
        assert ok is True
        assert "Noch kein Scan" in output

    def test_status_with_data(self, seeded_handler):
        ok, output = seeded_handler.handle("status", [])
        assert ok is True
        assert "SCAN STATUS" in output
        assert "5.20s" in output
        assert "Registrierte Tools: 2" in output
        assert "Offene Tasks: 2" in output

    def test_unknown_op_falls_through_to_status(self, seeded_handler):
        """Unknown operations fall through to _show_status."""
        ok, output = seeded_handler.handle("unknown_op", [])
        assert ok is True
        assert "SCAN STATUS" in output


# ═══════════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════════


class TestTasks:
    def test_tasks_show_open(self, seeded_handler):
        ok, output = seeded_handler.handle("tasks", [])
        assert ok is True
        assert "GESCANNTE TASKS" in output
        assert "Fix the parser bug" in output
        assert "Add unit tests" in output
        # Completed task should not appear
        assert "Update README" not in output

    def test_tasks_filter_by_tool(self, seeded_handler):
        ok, output = seeded_handler.handle("tasks", ["--tool", "TestTool"])
        assert ok is True
        assert "Fix the parser bug" in output

    def test_tasks_empty_result(self, handler):
        ok, output = handler.handle("tasks", [])
        assert ok is True
        assert "Keine offenen Tasks" in output


# ═══════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════


class TestTools:
    def test_tools_show_registered(self, seeded_handler):
        ok, output = seeded_handler.handle("tools", [])
        assert ok is True
        assert "REGISTRIERTE TOOLS" in output
        assert "TestTool" in output
        assert "OtherTool" in output
        assert "Gesamt: 2 Tools" in output

    def test_tools_empty(self, handler):
        ok, output = handler.handle("tools", [])
        assert ok is True
        assert "Keine Tools registriert" in output


# ═══════════════════════════════════════════════════════════════
# RUN (mocked)
# ═══════════════════════════════════════════════════════════════


class TestRun:
    def test_run_dry_run(self, handler):
        ok, output = handler.handle("run", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output

    @patch("hub.scan.ScanHandler._run_scan")
    def test_run_delegates(self, mock_run, handler):
        mock_run.return_value = (True, "[OK] Scan abgeschlossen")
        ok, output = handler.handle("run", [])
        assert ok is True
        mock_run.assert_called_once_with(False)


# ═══════════════════════════════════════════════════════════════
# DIR (directory scan)
# ═══════════════════════════════════════════════════════════════


class TestDir:
    def test_dir_missing_path(self, handler):
        ok, output = handler.handle("dir", [])
        assert ok is False
        assert "Pfad fehlt" in output

    def test_dir_nonexistent_path(self, handler):
        ok, output = handler.handle("dir", ["/nonexistent/path/xyz"])
        assert ok is False
        assert "existiert nicht" in output

    def test_dir_dry_run(self, handler, tmp_path):
        target = tmp_path / "scan_target"
        target.mkdir()
        ok, output = handler.handle("dir", [str(target)], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output
        assert str(target) in output

    def test_dir_not_a_directory(self, handler, tmp_path):
        file_path = tmp_path / "somefile.txt"
        file_path.write_text("hello")
        ok, output = handler.handle("dir", [str(file_path)])
        assert ok is False
        assert "Kein Verzeichnis" in output
