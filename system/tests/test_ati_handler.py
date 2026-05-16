#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer ATIHandler"""

import sys
import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.ati import ATIHandler


ATI_TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ati_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_id INTEGER,
    tool_name TEXT NOT NULL,
    tool_path TEXT NOT NULL,
    task_text TEXT NOT NULL,
    aufwand TEXT DEFAULT 'mittel' CHECK(aufwand IN ('niedrig', 'mittel', 'hoch')),
    status TEXT DEFAULT 'offen' CHECK(status IN ('offen', 'in_arbeit', 'erledigt', 'blockiert')),
    priority_score REAL DEFAULT 0,
    source_file TEXT NOT NULL,
    line_number INTEGER,
    file_hash TEXT,
    last_modified TIMESTAMP,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_synced INTEGER DEFAULT 1,
    linked_task_id INTEGER,
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0,
    depends_on TEXT
);
"""


@pytest.fixture
def ati_env(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()

    agents_dir = system_dir / "agents" / "ati"
    agents_dir.mkdir(parents=True)

    data_dir = system_dir / "data" / "ati"
    data_dir.mkdir(parents=True)

    daemon_dir = system_dir / "hub" / "_services" / "daemon"
    daemon_dir.mkdir(parents=True)

    db_path = tmp_path / ".bach" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(ATI_TASKS_SCHEMA)
    conn.close()

    handler = ATIHandler(system_dir)
    handler.db_path = db_path
    return handler, db_path


# ================================================================
# PROPERTIES
# ================================================================

class TestProperties:
    def test_profile_name(self, ati_env):
        h, _ = ati_env
        assert h.profile_name == "ati"

    def test_target_file(self, ati_env):
        h, _ = ati_env
        assert h.target_file == h.ati_dir

    def test_operations(self, ati_env):
        h, _ = ati_env
        ops = h.get_operations()
        assert "status" in ops
        assert "start" in ops
        assert "stop" in ops
        assert "task" in ops
        assert "scan" in ops
        assert "onboard" in ops
        assert "check" in ops
        assert "context" in ops
        assert "modules" in ops


# ================================================================
# ROUTING
# ================================================================

class TestRouting:
    def test_unknown_operation(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte ATI-Operation" in msg

    def test_help(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("help", [])
        assert ok is True
        assert "ATI" in msg


# ================================================================
# STATUS
# ================================================================

class TestStatus:
    def test_status_basic(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("status", [])
        assert ok is True
        assert "ATI STATUS" in msg
        assert "Struktur" in msg

    def test_status_shows_dirs(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("status", [])
        assert "ATI-Ordner" in msg
        assert "[OK]" in msg


# ================================================================
# BETWEEN-CHECKS
# ================================================================

class TestBetweenChecks:
    def test_check(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("check", [])
        assert ok is True
        assert "BETWEEN-TASK-CHECKS" in msg
        assert "Memory" in msg or "Aenderungen" in msg or "Tests" in msg


# ================================================================
# PROBLEMS FIRST
# ================================================================

class TestProblemsFirst:
    def test_problems(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("problems", [])
        assert ok is True
        assert "PROBLEMS FIRST" in msg


# ================================================================
# CONTEXT TRIGGER
# ================================================================

class TestContextTrigger:
    def test_no_args(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("context", [])
        assert ok is False
        assert "Verwendung" in msg or "KEYWORD" in msg

    def test_known_keyword(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("context", ["fehler"])
        assert ok is True
        assert "lessons_learned" in msg

    def test_unknown_keyword(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("context", ["unbekannt"])
        assert ok is False
        assert "Unbekanntes Keyword" in msg


# ================================================================
# TASK
# ================================================================

class TestTask:
    def test_task_no_args(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", [])
        assert ok is False
        assert "Verwendung" in msg

    def test_task_list_empty(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["list"])
        assert ok is True
        assert "ATI TASKS" in msg
        assert "Gesamt: 0" in msg

    def test_task_add(self, ati_env):
        h, db = ati_env
        ok, msg = h.handle("task", ["add", "Fix button alignment"])
        assert ok is True
        assert "erstellt" in msg

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT task_text, status, aufwand FROM ati_tasks WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "Fix button alignment"
        assert row[1] == "offen"
        assert row[2] == "mittel"

    def test_task_add_with_options(self, ati_env):
        h, db = ati_env
        ok, msg = h.handle("task", ["add", "Refactor API", "--tool", "my-tool", "--aufwand", "hoch"])
        assert ok is True

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT tool_name, aufwand FROM ati_tasks WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "my-tool"
        assert row[1] == "hoch"

    def test_task_add_no_title(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["add"])
        assert ok is False
        assert "Verwendung" in msg

    def test_task_done(self, ati_env):
        h, db = ati_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file) VALUES (?, ?, ?, ?)",
            ("test", "", "Sample task", "manual")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("task", ["done", "1"])
        assert ok is True
        assert "erledigt" in msg

        conn = sqlite3.connect(str(db))
        status = conn.execute("SELECT status FROM ati_tasks WHERE id = 1").fetchone()[0]
        conn.close()
        assert status == "erledigt"

    def test_task_done_not_found(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["done", "999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_task_done_already(self, ati_env):
        h, db = ati_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file, status) VALUES (?, ?, ?, ?, ?)",
            ("test", "", "Done task", "manual", "erledigt")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("task", ["done", "1"])
        assert ok is False
        assert "bereits erledigt" in msg

    def test_task_done_invalid_id(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["done", "abc"])
        assert ok is False
        assert "Ungueltige ID" in msg

    def test_task_list_with_data(self, ati_env):
        h, db = ati_env
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file, priority_score) VALUES (?, ?, ?, ?, ?)",
            ("web-app", "", "Add dark mode", "manual", 80)
        )
        conn.execute(
            "INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file, priority_score, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("api", "", "Fix auth", "manual", 90, "erledigt")
        )
        conn.commit()
        conn.close()

        ok, msg = h.handle("task", ["list"])
        assert ok is True
        assert "Offen: 1" in msg
        assert "Erledigt: 1" in msg
        assert "Add dark mode" in msg

    def test_task_unknown_subop(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["xyz"])
        assert ok is False
        assert "Unbekannte Operation" in msg


# ================================================================
# TASK DEPENDENCIES
# ================================================================

class TestTaskDependencies:
    def test_depends_too_few_args(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["depends", "1"])
        assert ok is False

    def test_depends_invalid_ids(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["depends", "abc", "def"])
        assert ok is False
        assert "Ungueltige IDs" in msg

    def test_depends_task_not_found(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["depends", "1", "2"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_depends_success(self, ati_env):
        h, db = ati_env
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file) VALUES (?, ?, ?, ?)",
                     ("t", "", "Task A", "m"))
        conn.execute("INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file) VALUES (?, ?, ?, ?)",
                     ("t", "", "Task B", "m"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("task", ["depends", "1", "2"])
        assert ok is True
        assert "haengt jetzt von" in msg

        conn = sqlite3.connect(str(db))
        deps = conn.execute("SELECT depends_on FROM ati_tasks WHERE id = 1").fetchone()[0]
        conn.close()
        assert json.loads(deps) == [2]

    def test_depends_duplicate(self, ati_env):
        h, db = ati_env
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file, depends_on) VALUES (?, ?, ?, ?, ?)",
                     ("t", "", "Task A", "m", "[2]"))
        conn.execute("INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file) VALUES (?, ?, ?, ?)",
                     ("t", "", "Task B", "m"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("task", ["depends", "1", "2"])
        assert ok is False
        assert "bereits vorhanden" in msg


# ================================================================
# DAEMON POPEN (cross-platform regression)
# ================================================================

class TestDaemonPopen:
    @patch("subprocess.Popen")
    def test_start_daemon_win32_creationflags(self, mock_popen, ati_env):
        """Regression: daemon Popen must pass CREATE_NO_WINDOW on Windows."""
        h, _ = ati_env
        daemon_script = h.session_service_dir / "session_daemon.py"
        daemon_script.parent.mkdir(parents=True, exist_ok=True)
        daemon_script.write_text("# daemon", encoding="utf-8")

        with patch("hub.ati.sys.platform", "win32"):
            ok, msg = h.handle("start", [])
        assert ok is True
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("creationflags") == 0x08000000
        assert "start_new_session" not in call_kwargs

    @patch("subprocess.Popen")
    def test_start_daemon_unix_start_new_session(self, mock_popen, ati_env):
        """Regression: daemon Popen must pass start_new_session on Unix."""
        h, _ = ati_env
        daemon_script = h.session_service_dir / "session_daemon.py"
        daemon_script.parent.mkdir(parents=True, exist_ok=True)
        daemon_script.write_text("# daemon", encoding="utf-8")

        with patch("hub.ati.sys.platform", "linux"):
            ok, msg = h.handle("start", [])
        assert ok is True
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("start_new_session") is True
        assert "creationflags" not in call_kwargs


# ================================================================
# TASK BLOCKED
# ================================================================

class TestTaskBlocked:
    def test_blocked_empty(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("task", ["blocked"])
        assert ok is True
        assert "Keine blockierten Tasks" in msg

    def test_blocked_with_data(self, ati_env):
        h, db = ati_env
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file, depends_on) VALUES (?, ?, ?, ?, ?)",
                     ("t", "", "Blocked task", "m", "[2]"))
        conn.execute("INSERT INTO ati_tasks (tool_name, tool_path, task_text, source_file) VALUES (?, ?, ?, ?)",
                     ("t", "", "Blocker task", "m"))
        conn.commit()
        conn.close()

        ok, msg = h.handle("task", ["blocked"])
        assert ok is True
        assert "Blocked task" in msg or "blockierte Tasks" in msg


# ================================================================
# ONBOARD
# ================================================================

class TestOnboard:
    def test_onboard_no_args(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("onboard", [])
        assert ok is False
        assert "Verwendung" in msg or "ONBOARD" in msg

    def test_onboard_nonexistent_path(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("onboard", ["/nonexistent/path"])
        assert ok is False
        assert "existiert nicht" in msg


# ================================================================
# SCAN
# ================================================================

class TestScan:
    def test_scan_unknown_subop(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("scan", ["unknown"])
        assert ok is False
        assert "Unbekannte Operation" in msg or "Verwendung" in msg

    def test_scan_dry_run(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("scan", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg


# ================================================================
# DAEMON START/STOP
# ================================================================

class TestDaemon:
    def test_start_daemon_no_script(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("start", [])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_start_daemon_dry_run(self, ati_env):
        h, _ = ati_env
        (h.session_service_dir / "session_daemon.py").write_text("# stub", encoding="utf-8")
        ok, msg = h.handle("start", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_stop_daemon_no_script(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("stop", [])
        assert ok is False
        assert "nicht gefunden" in msg


# ================================================================
# SESSION
# ================================================================

class TestSession:
    def test_session_no_script(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("session", [])
        assert ok is False
        assert "nicht gefunden" in msg


# ================================================================
# EXPORT / INSTALL / BOOTSTRAP / MIGRATE / MODULES
# ================================================================

class TestMiscOperations:
    def test_modules_no_subop(self, ati_env):
        h, _ = ati_env
        ok, msg = h.handle("modules", [])
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
