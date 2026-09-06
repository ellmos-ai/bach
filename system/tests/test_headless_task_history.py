# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer PUT /api/v1/tasks/{id} in gui/api/headless.py (T-20260906-240256515).

Folgefund aus T-20260906-985973908 (system/gui/server.py, PR #21): headless.py betreibt
einen separaten REST-Server (Port 8001) mit derselben Luecke -- kein task_history-
Schreibpfad, started_at nie gesetzt. Beide Server teilen sich jetzt die Schreiblogik aus
hub.task_audit.apply_task_field_changes; diese Tests decken die Headless-Seite ab
(GUI-Seite bereits in test_gui_server_smoke.py::TestTaskHistoryAndStartedAt).

Statuskonvention hier bewusst 'done'/'pending' (Headless-eigen), nicht 'completed'/'open'
wie im GUI-Server -- siehe hub/task_audit.py COMPLETED_STATUSES.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


@pytest.fixture
def db_path(tmp_path):
    """Minimale bach.db mit tasks + task_history (Spalten wie system/data/schema/schema.sql)."""
    p = tmp_path / "bach.db"
    conn = sqlite3.connect(str(p))
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'pending',
            category TEXT DEFAULT 'general',
            assigned_to TEXT DEFAULT '',
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
    return p


@pytest.fixture
def client(db_path, monkeypatch):
    """TestClient gegen headless.app, DB umgebogen, Auth ausgehebelt (Trust-Modus
    greift nicht, weil TestClient als request.client.host 'testclient' liefert,
    nicht '127.0.0.1')."""
    from gui.api import headless

    monkeypatch.setattr(headless, "BACH_DB", str(db_path))
    headless.app.dependency_overrides[headless.verify_auth] = lambda: True
    try:
        yield TestClient(headless.app, raise_server_exceptions=False)
    finally:
        headless.app.dependency_overrides.pop(headless.verify_auth, None)


@pytest.fixture
def history_rows(db_path):
    def _read(task_id):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM task_history WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return _read


@pytest.fixture
def task_row(db_path):
    def _read(task_id):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return dict(row)
    return _read


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestHeadlessTaskUpdateExistingBehavior:
    """Verhalten, das schon vor T-20260906-240256515 galt und erhalten bleiben muss."""

    def test_404_for_missing_task(self, client):
        resp = client.put("/api/v1/tasks/9999", json={"status": "done"})
        assert resp.status_code == 404

    def test_400_when_no_fields(self, client):
        resp = client.put("/api/v1/tasks/1", json={})
        assert resp.status_code == 400

    def test_400_when_only_changed_by_given(self, client):
        """changed_by ist Metadaten fuer task_history, keine tasks-Spalte -- zaehlt
        nicht als 'Feld zum Aktualisieren'."""
        resp = client.put("/api/v1/tasks/1", json={"changed_by": "someone"})
        assert resp.status_code == 400

    def test_update_returns_id_and_updated_true(self, client):
        resp = client.put("/api/v1/tasks/1", json={"priority": "P1"})
        assert resp.status_code == 200
        assert resp.json() == {"id": 1, "updated": True}


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestHeadlessTaskHistoryAndStartedAt:
    def test_in_progress_sets_started_at_once(self, client, task_row):
        resp = client.put("/api/v1/tasks/1", json={"status": "in_progress"})
        assert resp.status_code == 200
        first = task_row(1)
        assert first["started_at"] not in (None, "")

        client.put("/api/v1/tasks/1", json={"status": "pending"})
        client.put("/api/v1/tasks/1", json={"status": "in_progress"})
        second = task_row(1)
        assert second["started_at"] == first["started_at"]

    def test_done_sets_completed_at(self, client, task_row):
        """Headless nutzt 'done' statt 'completed' (GUI-Server) -- eigene Konvention,
        bewusst nicht vereinheitlicht (siehe hub/task_audit.py)."""
        resp = client.put("/api/v1/tasks/1", json={"status": "done"})
        assert resp.status_code == 200
        row = task_row(1)
        assert row["completed_at"] not in (None, "")

    def test_status_change_writes_exactly_one_history_row_with_default_changed_by(
        self, client, history_rows
    ):
        resp = client.put("/api/v1/tasks/1", json={"status": "in_progress"})
        assert resp.status_code == 200
        rows = history_rows(1)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "status_change"
        assert row["field_changed"] == "status"
        assert row["old_value"] == "pending"  # Fixture-Default
        assert row["new_value"] == "in_progress"
        assert row["changed_by"] == "headless-api"  # eigener Default, nicht GUI's "api"
        assert row["changed_at"]

    def test_changed_by_override_from_caller(self, client, history_rows):
        resp = client.put(
            "/api/v1/tasks/1", json={"status": "in_progress", "changed_by": "external-client"}
        )
        assert resp.status_code == 200
        assert history_rows(1)[0]["changed_by"] == "external-client"

    def test_no_op_status_writes_no_history_row(self, client, history_rows):
        client.put("/api/v1/tasks/1", json={"status": "pending"})  # bereits Fixture-Default
        assert history_rows(1) == []

    def test_multiple_field_changes_write_multiple_history_rows(self, client, history_rows):
        resp = client.put(
            "/api/v1/tasks/1", json={"status": "in_progress", "priority": "P1"}
        )
        assert resp.status_code == 200
        rows = history_rows(1)
        fields_changed = {r["field_changed"] for r in rows}
        assert fields_changed == {"status", "priority"}
        priority_row = next(r for r in rows if r["field_changed"] == "priority")
        assert priority_row["action"] == "field_change"
        assert priority_row["old_value"] == "P2"  # Fixture-Default
        assert priority_row["new_value"] == "P1"
