# -*- coding: utf-8 -*-
"""Regression tests for `bach task reopen --note` and `bach task archive --reason`."""

import re
import sqlite3
from pathlib import Path

from hub.task import TaskHandler

SYSTEM_DIR = Path(__file__).resolve().parent.parent


def _init_db(db_file: Path) -> None:
    conn = sqlite3.connect(db_file)
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'general',
            description TEXT,
            status TEXT DEFAULT 'pending',
            due_date TEXT,
            required_model TEXT,
            assigned_slot TEXT,
            result_max_chars INTEGER,
            created_at TEXT,
            updated_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            claimed_by TEXT,
            claimed_at TEXT,
            source TEXT,
            creation_origin TEXT,
            assigned_to TEXT,
            tags TEXT
        );
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            action TEXT,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT,
            changed_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def test_task_reopen_persists_note_and_history(tmp_path):
    db_file = tmp_path / "bach.db"
    _init_db(db_file)
    handler = TaskHandler(SYSTEM_DIR)
    handler.db_path = db_file

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO tasks (id, title, description, status, completed_at) VALUES (1, 'Reopen-Test-Task', 'Initial', 'done', '2026-11-01T12:00:00')"
    )
    conn.commit()
    conn.close()

    ok, msg = handler.handle("reopen", ["1", "--note", "Fehlabschluss ohne PR"])
    assert ok, msg
    assert "Fehlabschluss ohne PR" in msg

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status, description, completed_at FROM tasks WHERE id = 1").fetchone()
    assert row["status"] == "pending"
    assert row["completed_at"] is None
    assert "[REOPEN] Fehlabschluss ohne PR" in (row["description"] or "")

    hist = conn.execute("SELECT field_changed, new_value FROM task_history WHERE task_id = 1").fetchall()
    fields = {r["field_changed"] for r in hist}
    assert "status" in fields
    assert "description" in fields
    conn.close()


def test_task_archive_requires_reason_and_writes_history(tmp_path):
    db_file = tmp_path / "bach.db"
    _init_db(db_file)
    handler = TaskHandler(SYSTEM_DIR)
    handler.db_path = db_file

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO tasks (id, title, description, status) VALUES (2, 'Obsolete-Task', 'Altbestand', 'pending')"
    )
    conn.commit()
    conn.close()

    ok_missing, _ = handler.handle("archive", ["2"])
    assert not ok_missing

    ok, msg = handler.handle("archive", ["2", "--reason", "Durch #2441 abgeloest"])
    assert ok, msg
    assert "archiviert" in msg

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status, description FROM tasks WHERE id = 2").fetchone()
    assert row["status"] == "archived"
    assert "[ARCHIVED] Durch #2441 abgeloest" in (row["description"] or "")
    conn.close()
