"""Dashboard task totals must describe the filtered result before pagination."""

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
        rows = [
            (f"Finished {n}", "completed", "P1", "gui", "CODEX")
            for n in range(130)
        ] + [
            (status, status, "P2", "gui", "CODEX")
            for status in ("pending", "open", "in_progress", "progress")
            for _ in range(3)
        ] + [("Other", "pending", "P3", "core", "BACH")]
        conn.executemany(
            "INSERT INTO tasks (title,status,priority,category,assigned_to,created_at) "
            "VALUES (?,?,?,?,?,'2026-10-03')", rows,
        )

    def connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(server, "has_active_devices", lambda: False)
    test_client = TestClient(server.app)
    try:
        yield test_client
    finally:
        test_client.close()


def test_open_total_is_not_truncated_by_limit_or_finished_history(client):
    result = client.get("/api/tasks?status=pending,in_progress&limit=5").json()
    assert result["success"] is True
    assert result["count"] == len(result["tasks"]) == 5
    assert result["total"] == 13
    assert {task["status"] for task in result["tasks"]} <= {
        "pending", "open", "in_progress", "progress",
    }


@pytest.mark.parametrize("category_filter", ["category", "project"])
def test_total_uses_all_filters_and_status_aliases(client, category_filter):
    result = client.get(
        f"/api/tasks?status=open,progress&{category_filter}=GUI"
        "&assigned_to=codex&priority=medium&limit=2"
    ).json()
    assert result["count"] == 2
    assert result["total"] == 12


def test_empty_result_has_zero_total(client):
    result = client.get("/api/tasks?status=pending&assigned_to=nobody").json()
    assert result["tasks"] == []
    assert result["count"] == result["total"] == 0


def test_default_response_keeps_page_count_contract(client):
    result = client.get("/api/tasks").json()
    assert result["count"] == 100
    assert result["total"] == 143


def test_database_failure_does_not_claim_zero_tasks(client, monkeypatch):
    from gui import server

    def unavailable():
        raise sqlite3.OperationalError("unavailable fixture")

    monkeypatch.setattr(server, "get_bach_db", unavailable)
    result = client.get("/api/tasks?status=pending,in_progress&limit=5").json()
    assert result["success"] is False
    assert "total" not in result


@pytest.mark.parametrize("priority", ["P1", "1", "HIGH", " hoch ", "kritisch"])
def test_high_priority_aliases_are_not_lost_before_dashboard_limit(client, priority):
    from gui import server

    conn = server.get_bach_db()
    try:
        conn.execute(
            "INSERT INTO tasks (title,status,priority,created_at) "
            "VALUES ('Urgent alias task','pending',?,'2026-10-01')", (priority,),
        )
        conn.executemany(
            "INSERT INTO tasks (title,status,priority,created_at) "
            "VALUES ('Low priority task','pending','P4','2026-10-03')",
            [() for _ in range(6)],
        )
        conn.commit()
    finally:
        conn.close()
    result = client.get("/api/tasks?status=pending,in_progress&limit=5").json()
    assert result["tasks"][0]["title"] == "Urgent alias task"
    assert result["total"] == 20
