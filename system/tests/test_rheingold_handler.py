# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit- und Integrationstests fuer Rheingold Client & Hash-to-TaskID Staging."""

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.rheingold import (
    generate_draft_hash,
    is_rheingold_lead,
    post_task_to_rheingold,
    sync_drafts_to_rheingold,
)
from hub.task import TaskHandler


def _create_test_tasks_table(conn):
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'P3',
            category TEXT DEFAULT 'general',
            description TEXT DEFAULT '',
            assigned_to TEXT,
            delegated_to TEXT,
            depends_on TEXT,
            source TEXT,
            due_date TEXT,
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        )
    """)
    conn.commit()


def test_is_rheingold_lead_with_env(monkeypatch):
    monkeypatch.setenv("BACH_IS_RHEINGOLD_LEAD", "1")
    assert is_rheingold_lead() is True

    monkeypatch.setenv("BACH_IS_RHEINGOLD_LEAD", "0")
    monkeypatch.setattr("socket.gethostname", lambda: "WORKSTATION-LG")
    assert is_rheingold_lead() is False


def test_generate_draft_hash_format():
    h = generate_draft_hash("Mein lokaler Task", "feature", host="laptop")
    assert h.startswith("draft:laptop:")
    assert len(h.split(":")) == 3
    assert len(h.split(":")[2]) == 8


def test_offline_task_staging_with_negative_id(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)
    conn.close()

    handler = TaskHandler(tmp_path)
    handler.db_path = db_path

    # Im Offline-Modus anlegen
    ok, msg = handler.handle("add", ["Test Offline Task", "--priority", "P2", "--offline"])
    assert ok is True
    assert "[OFFLINE]" in msg
    assert "draft:" in msg

    # Task prüfen
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT id, title, priority, source FROM tasks").fetchone()
    conn.close()

    assert row is not None
    assert row[0] < 0  # Negative Staging-ID
    assert row[1] == "Test Offline Task"
    assert row[2] == "P2"
    assert row[3].startswith("draft:")

    # Prüfen, dass list den Draft sauber anzeigt
    ok_list, list_msg = handler.handle("list", ["all"])
    assert ok_list is True
    assert "[DRAFT -1]" in list_msg
    assert "(lokaler Entwurf)" in list_msg


def test_sync_drafts_promotes_to_official_id(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_test_tasks_table(conn)

    # Einen Offline-Draft manuell anlegen
    conn.execute("""
        INSERT INTO tasks (id, title, priority, category, description, status, source, created_at)
        VALUES (-1, 'Gestageter Task', 'P1', 'feature', 'Wartet auf Rheingold', 'pending', 'draft:wks:12345678', datetime('now'))
    """)
    conn.commit()

    # Mock: Rheingold vergibt ID 1250
    mock_response = (True, {"success": True, "id": 1250, "status": "created"})
    with patch("hub.rheingold.post_task_to_rheingold", return_value=mock_response):
        promoted = sync_drafts_to_rheingold(conn, "http://fake-rheingold:8000")

    assert len(promoted) == 1
    assert promoted[0]["old_id"] == -1
    assert promoted[0]["new_id"] == 1250
    assert promoted[0]["draft_hash"] == "draft:wks:12345678"

    # Prüfe DB-Stand
    row = conn.execute("SELECT id, title, source FROM tasks WHERE id = 1250").fetchone()
    assert row is not None
    assert row[0] == 1250
    assert row[1] == "Gestageter Task"
    assert row[2] == "promoted:draft:wks:12345678"

    # Der alte negative Eintrag darf nicht mehr existieren
    old_row = conn.execute("SELECT id FROM tasks WHERE id = -1").fetchone()
    assert old_row is None

    conn.close()
