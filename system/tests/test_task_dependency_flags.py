"""Task API marks dependency-blocked tasks fail-closed (list and detail)."""

import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from gui import server

    db = tmp_path / "tasks.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, title TEXT, status TEXT, priority TEXT,
                category TEXT, assigned_to TEXT, delegated_to TEXT,
                created_at TEXT, depends_on TEXT, image_data TEXT
            );
        """)
        conn.executemany(
            "INSERT INTO tasks (id,title,status,priority,category,assigned_to,created_at,depends_on) "
            "VALUES (?,?,?,'P2','gui','OLLAMA','2026-10-06',?)",
            [
                (1, "Done predecessor", "done", None),
                (2, "Open predecessor", "open", None),
                (10, "Free", "open", None),
                (11, "Waits on done", "open", "1"),
                (12, "Waits on open", "open", "1, 2"),
                (13, "Waits on missing", "open", "999"),
                (14, "Legacy label", "open", "P1"),
            ],
        )

    def connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "dep-fixture" else None)
    test_client = TestClient(server.app, headers={"Authorization": "Bearer dep-fixture"})
    try:
        yield test_client
    finally:
        test_client.close()


EXPECTED = {10: False, 11: False, 12: True, 13: True, 14: True}


def test_list_sets_dependency_flag_on_every_task(client):
    result = client.get("/api/tasks?status=open&limit=50").json()
    assert result["success"] is True
    flags = {task["id"]: task["is_blocked_by_dep"] for task in result["tasks"]}
    assert {task_id: flags[task_id] for task_id in EXPECTED} == EXPECTED


@pytest.mark.parametrize("task_id,blocked", sorted(EXPECTED.items()))
def test_detail_sets_dependency_flag(client, task_id, blocked):
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["id"] == task_id
    assert task["is_blocked_by_dep"] is blocked


def test_detail_unknown_task_is_404(client):
    assert client.get("/api/tasks/4242").status_code == 404
