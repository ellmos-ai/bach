# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer exec_tool("task_manage", ..., action="done") in chat_runtime.py.

T-20260906-833218904 (Folgefund aus T-20260906-985973908/PR #21, gemeldet beim Merge-
Review von PR #21): chat_runtime.py setzte Task-Status direkt per SQL, ohne
task_history-Zeile. Nutzt jetzt wie server.py/headless.py/task.py
hub.task_audit.apply_task_field_changes.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat import chat_runtime
from hub._services.chat.chat_runtime import exec_tool


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "bach.db"
    conn = sqlite3.connect(str(p))
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
        INSERT INTO tasks (title, status, priority) VALUES ('Test task', 'pending', 'P2');
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(chat_runtime, "RUNTIME_BACH_DB", str(p))
    return p


def _history_rows(db_path, task_id=1):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM task_history WHERE task_id = ? ORDER BY id", (task_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _task_row(db_path, task_id=1):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


class TestTaskManageDone:
    def test_done_sets_completed_at_and_returns_confirmation(self, db_path):
        result = exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")
        assert result == "Task #1 erledigt."
        row = _task_row(db_path)
        assert row["status"] == "done"
        assert row["completed_at"] not in (None, "")
        assert row["updated_at"] not in (None, "")

    def test_done_writes_history_row_with_default_changed_by(self, db_path):
        exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")
        rows = _history_rows(db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "status_change"
        assert row["field_changed"] == "status"
        assert row["old_value"] == "pending"
        assert row["new_value"] == "done"
        assert row["changed_by"] == "chat-runtime"

    def test_done_missing_task_returns_not_found(self, db_path):
        result = exec_tool("task_manage", {"action": "done", "task_id": 999}, mode="safe")
        assert result == "Task #999 nicht gefunden"
        assert _history_rows(db_path, task_id=999) == []

    def test_done_missing_task_id_returns_hint(self, db_path):
        result = exec_tool("task_manage", {"action": "done"}, mode="safe")
        assert result == "Keine Task-ID angegeben"

    def test_done_fallback_without_task_audit(self, db_path, monkeypatch):
        """Wenn hub.task_audit nicht importierbar ist (identischer sys.path-Vorbehalt
        wie RUNTIME_BACH_DB), soll die Aktion trotzdem funktionieren -- nur ohne
        Audit-Trail, statt hart zu brechen."""
        monkeypatch.setattr(chat_runtime, "apply_task_field_changes", None)
        result = exec_tool("task_manage", {"action": "done", "task_id": 1}, mode="safe")
        assert result == "Task #1 erledigt."
        row = _task_row(db_path)
        assert row["status"] == "done"
        assert row["completed_at"] not in (None, "")
        assert _history_rows(db_path) == []  # kein Fallback-Audit-Trail, aber kein Crash
