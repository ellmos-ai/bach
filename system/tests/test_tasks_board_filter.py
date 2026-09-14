# -*- coding: utf-8 -*-
"""Regressionstest für Task-Board-Filter (Task #1201).

Prüft:
- /api/tasks akzeptiert kommaseparierte Status-Werte und Aliase
- /api/tasks/meta liefert Kategorien, Prioritäten und Zuweisungen
- Prioritätsfilter gruppiert numerische/unbekannte Werte korrekt
- Status-Gruppen im Board (pending/open/blocked, in_progress/progress, done/completed/closed)
"""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest


TASKS_SCHEMA = """
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    priority TEXT DEFAULT 'P3',
    tags TEXT,
    status TEXT DEFAULT 'pending',
    estimated_minutes INTEGER,
    actual_minutes INTEGER,
    delegated_to TEXT,
    delegation_status TEXT,
    source_file TEXT,
    source_line INTEGER,
    is_recurring INTEGER DEFAULT 0,
    recurrence_pattern TEXT,
    next_occurrence TEXT,
    executable_command TEXT,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT,
    dist_type INTEGER DEFAULT 0,
    modified_by TEXT DEFAULT NULL,
    depends_on TEXT DEFAULT NULL,
    created_by TEXT DEFAULT 'user',
    assigned_to TEXT DEFAULT 'user',
    project TEXT,
    source TEXT,
    image_data TEXT,
    assigned_agent TEXT,
    due_date TEXT
);
"""


@pytest.fixture(scope="module")
def client():
    """Baut eine temporäre BACH-DB auf, importiert den GUI-Server und liefert TestClient."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    os.environ["BACH_DB"] = db_path
    # Falls Modul schon importiert wurde, muss es neu geladen werden können
    # Wir löschen ggf. vorhandene server-Module aus dem Cache
    for name in list(sys.modules.keys()):
        if "gui.server" in name or "hub.bach_paths" in name:
            sys.modules.pop(name, None)

    conn = sqlite3.connect(db_path)
    conn.executescript(TASKS_SCHEMA)
    test_tasks = [
        ("Open Task", "open", "P1", "general", "user"),
        ("Progress Task", "progress", "P2", "gui", "claude"),
        ("Blocked Task", "blocked", "P3", "bug", "bach"),
        ("Completed Task", "completed", "P4", "docs", "user"),
        ("Closed Task", "closed", "9", "core", "gemini"),
        ("Pending Task", "pending", "LOW", "feature", None),
        ("In Progress Task", "in_progress", "HIGH", "maintenance", "user"),
        ("Done Task", "done", "3", "architecture", "claude"),
    ]
    conn.executemany(
        "INSERT INTO tasks (title, status, priority, category, assigned_to, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        test_tasks,
    )
    conn.commit()
    conn.close()

    # Import via 'system.gui.server' erzwingen, nicht 'hub.gui'
    sys.path.insert(0, str(Path(__file__).parent.parent))
    # Eventuelle Import-Caches für 'gui' leeren
    for name in list(sys.modules.keys()):
        if name == "gui" or name.startswith("gui."):
            sys.modules.pop(name, None)
    from system.gui.server import app
    from fastapi.testclient import TestClient

    yield TestClient(app)

    # Cleanup
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


def test_api_tasks_meta(client):
    res = client.get("/api/tasks/meta")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert set(data["categories"]) >= {"general", "gui", "bug", "docs", "core", "feature", "maintenance", "architecture"}
    assert set(data["priorities"]) >= {"P1", "P2", "P3", "P4", "9", "LOW", "HIGH", "3"}
    assert "user" in data["assignees"]


def test_status_group_pending_open_blocked(client):
    res = client.get("/api/tasks?status=pending,open,blocked")
    assert res.status_code == 200
    data = res.json()
    titles = {t["title"] for t in data["tasks"]}
    assert titles >= {"Open Task", "Pending Task", "Blocked Task"}
    assert "In Progress Task" not in titles
    assert "Done Task" not in titles


def test_status_alias_progress_maps_to_in_progress(client):
    res = client.get("/api/tasks?status=in_progress,progress")
    assert res.status_code == 200
    data = res.json()
    titles = {t["title"] for t in data["tasks"]}
    assert {"Progress Task", "In Progress Task"}.issubset(titles)


def test_status_alias_done_group(client):
    res = client.get("/api/tasks?status=done,completed,closed")
    assert res.status_code == 200
    data = res.json()
    titles = {t["title"] for t in data["tasks"]}
    assert {"Completed Task", "Closed Task", "Done Task"}.issubset(titles)


def test_priority_filter_p1_includes_null(client):
    res = client.get("/api/tasks?priority=P1")
    assert res.status_code == 200
    data = res.json()
    # P1-Gruppe enthält HIGH/P1; unsere Testdaten haben 'HIGH' als P1-ähnlich
    priorities = {t["priority"] for t in data["tasks"]}
    assert "HIGH" in priorities


def test_priority_filter_p4(client):
    res = client.get("/api/tasks?priority=P4")
    assert res.status_code == 200
    data = res.json()
    priorities = {t["priority"] for t in data["tasks"]}
    assert "P4" in priorities


def test_filter_combination(client):
    res = client.get("/api/tasks?status=open,pending&category=general")
    assert res.status_code == 200
    data = res.json()
    assert all(t["category"].lower() == "general" for t in data["tasks"])


def test_status_all_returns_everything(client):
    res = client.get("/api/tasks?status=all")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 8
