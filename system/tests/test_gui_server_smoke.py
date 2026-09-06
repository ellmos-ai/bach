# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Smoke tests for gui/server.py using FastAPI TestClient.

Verifies that the 33+ narrowed exception handlers in Iteration 18
don't crash real endpoints when the DB has missing/empty tables.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def test_db(tmp_path):
    """Creates a minimal bach.db with core tables."""
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'open',
            category TEXT DEFAULT 'general',
            project TEXT,
            assigned_to TEXT DEFAULT 'user',
            created_by TEXT DEFAULT 'user',
            depends_on TEXT,
            image_data BLOB,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        -- T-20260906-985973908: task_history existiert real (schema.sql), fehlte hier bisher
        -- komplett -- jeder Statuswechsel gegen diese Fixture haette sonst mit
        -- "no such table: task_history" abgebrochen, sobald update_task hineinschreibt.
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT DEFAULT 'user',
            changed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ati_tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT DEFAULT 'offen',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            direction TEXT DEFAULT 'inbox',
            sender TEXT,
            recipient TEXT,
            subject TEXT,
            body TEXT,
            status TEXT DEFAULT 'unread',
            priority INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS scheduler_jobs (
            id INTEGER PRIMARY KEY,
            name TEXT,
            is_active INTEGER DEFAULT 1,
            job_type TEXT,
            schedule TEXT,
            command TEXT
        );
        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY,
            started_at TEXT
        );
        CREATE TABLE IF NOT EXISTS memory_working (
            id INTEGER PRIMARY KEY,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS memory_sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            partner TEXT,
            started_at TEXT,
            ended_at TEXT,
            summary TEXT,
            topics TEXT
        );
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY,
            key TEXT,
            value TEXT,
            category TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY,
            content TEXT,
            severity TEXT DEFAULT 'medium',
            source TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS denkarium_entries (
            id INTEGER PRIMARY KEY,
            entry_type TEXT DEFAULT 'denkarium',
            title TEXT,
            content TEXT,
            category TEXT,
            source TEXT,
            mood TEXT,
            promoted_to TEXT,
            promoted_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS partners (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            category TEXT,
            path TEXT,
            version TEXT,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 0,
            trigger_phrases TEXT
        );
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            category TEXT,
            description TEXT,
            path TEXT,
            command TEXT
        );
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- Sample data
        INSERT INTO tasks (title, status, priority) VALUES ('Test task', 'open', 'P2');
        INSERT INTO messages (sender, recipient, body, status) VALUES ('system', 'user', 'Hello', 'unread');
    """)
    conn.commit()
    conn.close()
    return tmp_path


@pytest.fixture
def client(test_db, monkeypatch):
    """Creates a TestClient with patched DB paths."""
    db_path = test_db / "data" / "bach.db"

    # Create minimal directory structure the server expects
    gui_dir = test_db / "gui"
    gui_dir.mkdir(exist_ok=True)
    templates_dir = gui_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    static_dir = gui_dir / "static"
    static_dir.mkdir(exist_ok=True)
    docs_dir = test_db / "docs" / "help"
    docs_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir = test_db / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    skills_dir = test_db / "skills"
    skills_dir.mkdir(exist_ok=True)
    agents_dir = test_db / "agents" / "_experts"
    agents_dir.mkdir(parents=True, exist_ok=True)

    import gui.server as srv
    monkeypatch.setattr(srv, "BACH_DB", db_path)
    monkeypatch.setattr(srv, "USER_DB", db_path)
    monkeypatch.setattr(srv, "DATA_DIR", test_db / "data")
    monkeypatch.setattr(srv, "BACH_DIR", test_db)
    monkeypatch.setattr(srv, "GUI_DIR", gui_dir)
    monkeypatch.setattr(srv, "TEMPLATES_DIR", templates_dir)
    monkeypatch.setattr(srv, "STATIC_DIR", static_dir)
    monkeypatch.setattr(srv, "HELP_DIR", docs_dir)
    monkeypatch.setattr(srv, "WIKI_DIR", wiki_dir)
    monkeypatch.setattr(srv, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(srv, "AGENTS_DIR", test_db / "agents")
    monkeypatch.setattr(srv, "EXPERTS_DIR", agents_dir)
    tools_dir = test_db / "tools"
    tools_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(srv, "TOOLS_DIR", tools_dir)

    return TestClient(srv.app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════
# SMOKE TESTS — GET endpoints (read-only, safe)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestGUIServerSmoke:
    """Smoke tests: endpoints return valid JSON, don't crash."""

    def test_status_endpoint(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"
        assert "stats" in data

    def test_theme_settings_roundtrip(self, client, test_db):
        initial = client.get("/api/settings/theme")
        assert initial.status_code == 200
        assert initial.json()["theme"] == "dark"
        assert initial.json()["configured"] is False

        updated = client.put(
            "/api/settings/theme",
            json={"theme": "custom", "custom": {"accent": "#aabbcc"}},
        )
        assert updated.status_code == 200
        assert updated.json()["custom"]["accent"] == "#aabbcc"

        saved = json.loads(
            (test_db / "data" / "user_config.json").read_text(encoding="utf-8")
        )
        assert saved["gui"]["theme"] == "custom"
        assert client.get("/api/settings/theme").json()["theme"] == "custom"

    def test_theme_settings_reject_css_injection(self, client):
        response = client.put(
            "/api/settings/theme",
            json={"theme": "custom", "custom": {"accent": "red;url(x)"}},
        )
        assert response.status_code == 400
        assert "#RRGGBB" in response.json()["detail"]

    def test_tasks_list(self, client):
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["tasks"], list)

    def test_tasks_list_with_filters(self, client):
        resp = client.get("/api/tasks?status=open&priority=P2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_task_get_nonexistent(self, client):
        resp = client.get("/api/tasks/99999")
        assert resp.status_code in (200, 404)

    def test_task_create(self, client):
        resp = client.post("/api/tasks", json={"title": "Smoke test task"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True or "id" in data

    def test_messages_list(self, client):
        resp = client.get("/api/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_partners_list(self, client):
        resp = client.get("/api/partners")
        assert resp.status_code == 200

    def test_assignees(self, client):
        resp = client.get("/api/assignees")
        assert resp.status_code == 200

    def test_agents_list(self, client):
        resp = client.get("/api/agents")
        assert resp.status_code == 200

    def test_skills_list(self, client):
        resp = client.get("/api/skills")
        assert resp.status_code == 200

    def test_skills_categories(self, client):
        resp = client.get("/api/skills/categories")
        assert resp.status_code == 200

    def test_denkarium_list(self, client):
        resp = client.get("/api/denkarium")
        assert resp.status_code == 200

    def test_memory_overview(self, client):
        resp = client.get("/api/memory/overview")
        assert resp.status_code == 200

    def test_memory_working(self, client):
        resp = client.get("/api/memory/working")
        assert resp.status_code == 200

    def test_memory_lessons(self, client):
        resp = client.get("/api/memory/lessons")
        assert resp.status_code == 200

    def test_memory_facts(self, client):
        resp = client.get("/api/memory/facts")
        assert resp.status_code == 200

    def test_memory_sessions(self, client):
        resp = client.get("/api/memory/sessions")
        assert resp.status_code == 200

    def test_help_list(self, client):
        resp = client.get("/api/help")
        assert resp.status_code == 200

    def test_system_logs(self, client):
        resp = client.get("/api/system/logs")
        assert resp.status_code == 200

    def test_tools_list(self, client):
        resp = client.get("/api/tools")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# TASK DEPENDENCY — depends_on type-safety (advisor-identified risk)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestTaskDependsSafety:
    """Verifies depends_on.split() doesn't crash on non-string values."""

    def test_depends_on_integer_no_crash(self, test_db, client):
        db_path = test_db / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO tasks (title, status, depends_on) VALUES (?, ?, ?)",
            ("dep-test", "open", 42),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_depends_on_null_no_crash(self, test_db, client):
        db_path = test_db / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO tasks (title, status, depends_on) VALUES (?, ?, ?)",
            ("null-dep", "open", None),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/tasks")
        assert resp.status_code == 200

    def test_depends_on_valid_string(self, test_db, client):
        db_path = test_db / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO tasks (title, status, depends_on) VALUES (?, ?, ?)",
            ("str-dep", "open", "1,2,3"),
        )
        conn.commit()
        conn.close()

        resp = client.get("/api/tasks")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# WRITE ENDPOINTS — minimal creation/update tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestGUIServerWrite:
    """Tests for POST/PUT/DELETE endpoints."""

    def test_task_update(self, client):
        resp = client.put("/api/tasks/1", json={"status": "done"})
        assert resp.status_code == 200

    def test_task_delete(self, client):
        create = client.post("/api/tasks", json={"title": "To delete"})
        if create.status_code == 200:
            data = create.json()
            task_id = data.get("id") or data.get("task_id") or 999
            resp = client.delete(f"/api/tasks/{task_id}")
            assert resp.status_code == 200

    def test_message_create(self, client):
        resp = client.post("/api/messages", json={
            "recipient": "system",
            "body": "Test message"
        })
        assert resp.status_code == 200

    def test_denkarium_create(self, client):
        resp = client.post("/api/denkarium", json={
            "content": "Test thought",
            "category": "test"
        })
        assert resp.status_code == 200

    def test_memory_working_create(self, client):
        resp = client.post("/api/memory/working", json={
            "content": "test working memory"
        })
        assert resp.status_code == 200

    def test_memory_fact_create(self, client):
        resp = client.post("/api/memory/facts", json={
            "key": "test_key",
            "value": "test_value"
        })
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# TASK HISTORY / started_at — T-20260906-985973908
# ═══════════════════════════════════════════════════════════════


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestTaskHistoryAndStartedAt:
    """Vorher wurde `task_history` nie beschrieben (0 Zeilen systemweit) und `started_at`
    beim Wechsel auf 'in_progress' nie gesetzt. Diese Tests belegen den Schreibpfad in
    update_task (system/gui/server.py)."""

    @staticmethod
    def _history_rows(test_db, task_id):
        conn = sqlite3.connect(str(test_db / "data" / "bach.db"))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM task_history WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def _task_row(test_db, task_id):
        conn = sqlite3.connect(str(test_db / "data" / "bach.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return dict(row)

    def test_in_progress_sets_started_at_once(self, client, test_db):
        resp = client.put("/api/tasks/1", json={"status": "in_progress"})
        assert resp.status_code == 200
        first = self._task_row(test_db, 1)
        assert first["started_at"] not in (None, "")

        # Zurueckfallen und erneut in_progress darf den Erststart NICHT ueberschreiben.
        client.put("/api/tasks/1", json={"status": "open"})
        client.put("/api/tasks/1", json={"status": "in_progress"})
        second = self._task_row(test_db, 1)
        assert second["started_at"] == first["started_at"]

    def test_completed_still_sets_completed_at(self, client, test_db):
        resp = client.put("/api/tasks/1", json={"status": "completed"})
        assert resp.status_code == 200
        row = self._task_row(test_db, 1)
        assert row["completed_at"] not in (None, "")

    def test_status_change_writes_exactly_one_history_row(self, client, test_db):
        resp = client.put("/api/tasks/1", json={"status": "in_progress"})
        assert resp.status_code == 200

        rows = self._history_rows(test_db, 1)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "status_change"
        assert row["field_changed"] == "status"
        assert row["old_value"] == "open"  # Fixture-Default, siehe test_db
        assert row["new_value"] == "in_progress"
        assert row["changed_by"] == "api"  # Default ohne mitgegebenen changed_by
        assert row["changed_at"]

    def test_changed_by_override_from_caller(self, client, test_db):
        resp = client.put(
            "/api/tasks/1", json={"status": "in_progress", "changed_by": "idle-worker"}
        )
        assert resp.status_code == 200
        rows = self._history_rows(test_db, 1)
        assert rows[0]["changed_by"] == "idle-worker"

    def test_no_op_status_writes_no_history_row(self, client, test_db):
        """Denselben Wert erneut zu setzen ist kein Statuswechsel."""
        client.put("/api/tasks/1", json={"status": "open"})  # bereits der Fixture-Default
        rows = self._history_rows(test_db, 1)
        assert rows == []

    def test_multiple_field_changes_write_multiple_history_rows(self, client, test_db):
        resp = client.put(
            "/api/tasks/1", json={"status": "in_progress", "priority": "P1"}
        )
        assert resp.status_code == 200
        rows = self._history_rows(test_db, 1)
        fields_changed = {r["field_changed"] for r in rows}
        assert fields_changed == {"status", "priority"}
        priority_row = next(r for r in rows if r["field_changed"] == "priority")
        assert priority_row["action"] == "field_change"
        assert priority_row["old_value"] == "P2"  # Fixture-Default, siehe test_db
        assert priority_row["new_value"] == "P1"


# ═══════════════════════════════════════════════════════════════
# DB-MISSING SCENARIO — server returns 503, not crash
# ═══════════════════════════════════════════════════════════════


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestGUIServerNoDB:
    """Verifies 503 when DB is missing (FileNotFoundError handler)."""

    def test_status_no_db(self, tmp_path, monkeypatch):
        missing = tmp_path / "nonexistent.db"
        import gui.server as srv
        monkeypatch.setattr(srv, "BACH_DB", missing)
        monkeypatch.setattr(srv, "USER_DB", missing)

        test_client = TestClient(srv.app, raise_server_exceptions=False)
        resp = test_client.get("/api/status")
        assert resp.status_code == 503
