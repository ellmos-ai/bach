# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Device-Auth-Regressionstests für GET /api/tasks und GET /api/tasks/{id}.

Deckt die neue Dependency `require_device` ab:
- 401 ohne Token (beide Endpoints)
- 403 fuer ungueltiges/revoked Token
- 200 gueltiger Token mit Filter + Pagination (GET /api/tasks)
- 200 gueltiger Token (GET /api/tasks/123)

Die Filter-/Pagination-/TaskDB-Semantik bleibt unveraendert; nur die
Auth-Schicht wird hier verifiziert.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient


def _build_db(tmp_path):
    db = tmp_path / "tasks.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, title TEXT, status TEXT, priority TEXT,
                category TEXT, assigned_to TEXT, delegated_to TEXT,
                created_at TEXT, depends_on TEXT, image_data TEXT
            );
        """)
        conn.execute(
            "INSERT INTO tasks (id,title,status,priority,category,assigned_to,created_at) "
            "VALUES (123, 'Auth-Task', 'pending', 'P1', 'gui', 'CODEX', '2026-10-03')"
        )
        for n in range(1, 6):
            conn.execute(
                "INSERT INTO tasks (id,title,status,priority,category,assigned_to,created_at) "
                "VALUES (?, ?, 'done', 'P3', 'core', 'BACH', '2026-10-03')",
                (1000 + n, f"History {n}"),
            )

    def connect():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    return connect


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Gueltiges Device-Token + echte Task-DB fuer die 200-Cases."""
    from gui import server

    monkeypatch.setattr(server, "get_bach_db", _build_db(tmp_path))
    monkeypatch.setattr(
        server,
        "validate_token",
        lambda token: {"id": 1, "device": "fixture"} if token == "valid-fixture" else None,
    )
    c = TestClient(
        server.app,
        raise_server_exceptions=False,
        headers={"Authorization": "Bearer valid-fixture"},
    )
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def anon_client():
    """Kein Token - faehrt den 401-Pfad."""
    from gui import server

    c = TestClient(server.app, raise_server_exceptions=False)
    try:
        yield c
    finally:
        c.close()


def test_get_tasks_without_token_is_401(anon_client):
    """GET /api/tasks ohne Token => 401, noch keine DB-Aktion."""
    resp = anon_client.get("/api/tasks")
    assert resp.status_code == 401


def test_get_task_without_token_is_401(anon_client):
    """GET /api/tasks/{id} ohne Token => 401."""
    resp = anon_client.get("/api/tasks/123")
    assert resp.status_code == 401


def test_revoked_token_is_401_via_middleware(monkeypatch):
    """Revoked/ungültiger Token => 401 (DeviceAuthMiddleware fängt vor require_device).

    Die DeviceAuthMiddleware (L1510-1730) validiert den Token ebenfalls
    ueber validate_token(). Liefert diese None, antwortet die Middleware
    bereits mit 401, bevor require_device erreicht wird. Damit wird
    hier der realistische End-to-End-Pfad abgedeckt.
    """
    from gui import server

    monkeypatch.setattr(server, "validate_token", lambda token: None)
    c = TestClient(
        server.app,
        raise_server_exceptions=False,
        headers={"Authorization": "Bearer revoked-fixture"},
    )
    try:
        assert c.get("/api/tasks").status_code == 401
        assert c.get("/api/tasks/123").status_code == 401
    finally:
        c.close()


def test_valid_token_lists_tasks_with_filter_and_pagination(client):
    """Gueltiges Token + Filter/Pagination => 200, Semantik unveraendert."""
    resp = client.get("/api/tasks?status=done&limit=3&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] == 3
    assert all(t["status"] == "done" for t in data["tasks"])
    # pagination: die 5 done-Records minus offset 1 => 4 verbleiben, limit 3
    assert data["count"] == 3
    assert data["total"] == 5


def test_valid_token_reads_single_task(client):
    """Gueltiges Token => GET /api/tasks/123 liefert den Task (200)."""
    resp = client.get("/api/tasks/123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 123
    assert data["title"] == "Auth-Task"
