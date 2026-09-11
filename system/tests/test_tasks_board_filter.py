# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests for Task Board Filter Categories and Priority filtering (Task #1201).
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
def filter_test_db(tmp_path):
    """Creates a test database with diverse tasks for filtering."""
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
            due_date TEXT,
            source TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        INSERT INTO tasks (id, title, priority, category, status, assigned_to)
        VALUES (1, 'Bug in GUI', 'P1', 'bug', 'open', 'user');

        INSERT INTO tasks (id, title, priority, category, status, assigned_to)
        VALUES (2, 'Old Bug in Core', 'HIGH', 'BUG', 'open', 'claude');

        INSERT INTO tasks (id, title, priority, category, status, assigned_to)
        VALUES (3, 'Feature Request', 'P2', 'feature', 'open', 'gemini');

        INSERT INTO tasks (id, title, priority, category, status, assigned_to)
        VALUES (4, 'Documentation update', '3', 'docs', 'open', 'bach');
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not available")
class TestTasksBoardFilter:
    @pytest.fixture
    def client(self, filter_test_db, monkeypatch):
        import gui.server as srv
        monkeypatch.setattr(srv, "BACH_DIR", filter_test_db.parent.parent)

        def _get_db():
            conn = sqlite3.connect(str(filter_test_db))
            conn.row_factory = sqlite3.Row
            return conn

        monkeypatch.setattr(srv, "get_bach_db", _get_db)
        return TestClient(srv.app)

    def test_tasks_meta_endpoint(self, client):
        resp = client.get("/api/tasks/meta")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "categories" in data
        assert "priorities" in data
        assert "assignees" in data
        # Check that categories contain BUG / bug
        assert any(c.lower() == "bug" for c in data["categories"])

    def test_category_case_insensitive_filtering(self, client):
        # 'bug' lowercase
        resp_lower = client.get("/api/tasks?category=bug")
        assert resp_lower.status_code == 200
        tasks_lower = resp_lower.json()["tasks"]
        assert len(tasks_lower) == 2  # Matches id 1 ('bug') and id 2 ('BUG')

        # 'BUG' uppercase
        resp_upper = client.get("/api/tasks?category=BUG")
        assert resp_upper.status_code == 200
        tasks_upper = resp_upper.json()["tasks"]
        assert len(tasks_upper) == 2

        # 'project' parameter alias
        resp_proj = client.get("/api/tasks?project=bug")
        assert resp_proj.status_code == 200
        tasks_proj = resp_proj.json()["tasks"]
        assert len(tasks_proj) == 2

    def test_priority_filtering_normalization(self, client):
        # P1 filter should match 'P1' and 'HIGH'
        resp_p1 = client.get("/api/tasks?priority=P1")
        assert resp_p1.status_code == 200
        tasks_p1 = resp_p1.json()["tasks"]
        assert len(tasks_p1) == 2
        p1_ids = {t["id"] for t in tasks_p1}
        assert p1_ids == {1, 2}

        # P2 filter
        resp_p2 = client.get("/api/tasks?priority=P2")
        assert resp_p2.status_code == 200
        tasks_p2 = resp_p2.json()["tasks"]
        assert len(tasks_p2) == 1
        assert tasks_p2[0]["id"] == 3

        # P3 filter matching numeric '3'
        resp_p3 = client.get("/api/tasks?priority=P3")
        assert resp_p3.status_code == 200
        tasks_p3 = resp_p3.json()["tasks"]
        assert len(tasks_p3) == 1
        assert tasks_p3[0]["id"] == 4

    def test_tasks_board_template_elements(self):
        tmpl_path = SYSTEM_ROOT / "gui" / "templates" / "tasks_board.html"
        assert tmpl_path.exists()
        content = tmpl_path.read_text(encoding="utf-8")
        assert 'id="filter-priority"' in content
        assert "loadFilterOptions" in content
        assert "normalizePriorityClass" in content
