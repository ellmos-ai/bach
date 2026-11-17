"""Created-date filters and stable ordering against isolated synthetic tasks only."""
import sqlite3
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    from gui import server
    db = tmp_path / "task-created-dates.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE tasks (
            id INTEGER PRIMARY KEY, title TEXT, description TEXT, status TEXT,
            priority TEXT, category TEXT, assigned_to TEXT, delegated_to TEXT,
            created_at TEXT, depends_on TEXT, image_data TEXT)""")
        rows = [
            (1, "2026-11-16T23:59:59.999999-10:00", "P1", "pending", "CODEX"),
            (2, "2026-11-17T00:00:00+14:00", "P4", "pending", "CODEX"),
            (3, "2026-11-17 09:00:00", "P3", "done", "CODEX"),
            (4, "2026-11-17T09:00:00", "P1", "pending", "BACH"),
            (5, "2026-11-17T23:59:59.999999Z", "P2", "pending", "CODEX"),
            (6, "2026-11-18T00:00:00-10:00", "P3", "pending", "CODEX"),
            (7, None, "P1", "pending", "CODEX"),
            (8, "not-a-date", "P2", "pending", "CODEX"),
            (9, "2026-02-30T11:22:33", "P3", "pending", "CODEX"),
            (10, "2024-02-29", "P4", "pending", "CODEX"),
        ]
        conn.executemany(
            "INSERT INTO tasks (id,created_at,priority,status,assigned_to,title,description,category) VALUES (?,?,?,?,?,?,?,?)",
            [(ident, created, priority, status, agent, f"Task {ident}", "synthetic", "gui")
             for ident, created, priority, status, agent in rows],
        )
    def connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "date-test" else None)
    test_client = TestClient(server.app, headers={"Authorization": "Bearer date-test"})
    yield test_client, db
    test_client.close()

def get(client, query):
    response = client[0].get("/api/tasks?status=all&" + query)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    return data

@pytest.mark.parametrize("sort,ids", [
    ("created_desc", [5, 4, 3, 2]),
    ("created_asc", [2, 3, 4, 5]),
])
def test_inclusive_calendar_range_and_stable_order_before_pagination(client, sort, ids):
    query = "created_from=2026-11-17&created_to=2026-11-17&sort=" + sort
    first = get(client, query + "&limit=2")
    second = get(client, query + "&limit=2&offset=2")
    assert [t["id"] for t in first["tasks"] + second["tasks"]] == ids
    assert first["total"] == second["total"] == 4
    assert first["has_more"] is True and second["has_more"] is False
    assert first["applied_filters"] == second["applied_filters"]
    receipt = first["applied_filters"]
    assert receipt["created_from"] == receipt["created_to"] == "2026-11-17"
    assert receipt["sort"] == sort and receipt["created_date_semantics"] == "stored_calendar"

def test_date_and_existing_filters_combine_before_count(client):
    response = client[0].get("/api/tasks?status=pending&assigned_to=CODEX&priority=P2&q=synthetic&created_from=2026-11-17&created_to=2026-11-17&sort=created_desc&limit=0")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True and data["total"] == 1 and data["tasks"] == []
    assert get(client, "created_from=2026-11-17&created_to=2026-11-17&sort=priority")["tasks"][0]["id"] == 4

def test_stored_calendar_does_not_convert_offsets_or_naive_times(client):
    assert [t["id"] for t in get(client, "created_from=2026-11-16&created_to=2026-11-16")["tasks"]] == [1]
    assert [t["id"] for t in get(client, "created_from=2026-11-18&created_to=2026-11-18")["tasks"]] == [6]
    assert [t["id"] for t in get(client, "created_from=2024-02-29&created_to=2024-02-29")["tasks"]] == [10]

@pytest.mark.parametrize("query", [
    "created_from=2026-02-29", "created_to=2026-11-31",
    "created_from=2026-1-01", "created_from=0000-01-01",
    "created_from=2026-11-18&created_to=2026-11-17",
    "created_to=2026-11-17T23:59:59", "sort=unknown",
    "sort=created_desc%3BDROP%20TABLE%20tasks",
])
def test_invalid_dates_ranges_and_sort_are_rejected(client, query):
    response = client[0].get("/api/tasks?" + query)
    assert response.status_code == 400

def test_extreme_valid_dates_do_not_require_next_day_overflow(client):
    assert get(client, "created_from=9999-12-31&created_to=9999-12-31")["total"] == 0
    assert get(client, "created_from=0001-01-01&created_to=9999-12-31")["total"] == 7

@pytest.mark.parametrize("sort,last", [("created_desc", [9, 8, 7]), ("created_asc", [7, 8, 9])])
def test_missing_or_invalid_timestamps_sort_last(client, sort, last):
    data = get(client, "sort=" + sort)
    assert [t["id"] for t in data["tasks"]][-3:] == last
    assert len(data["tasks"]) == 10

def test_created_sort_covers_more_than_two_pages_without_priority_bias(client):
    with sqlite3.connect(client[1]) as conn:
        conn.executemany(
            "INSERT INTO tasks (id,title,status,priority,created_at) VALUES (?,?,?,?,?)",
            [(100 + i, f"Bulk {i}", "pending", "P1" if i % 2 else "P4",
              f"2026-12-{1 + i % 28:02d}T10:{i % 60:02d}:00") for i in range(230)],
        )
    query = "created_from=2026-12-01&created_to=2026-12-31&sort=created_desc"
    pages = [get(client, query + f"&limit=100&offset={offset}") for offset in [0, 100, 200]]
    rows = [task for page in pages for task in page["tasks"]]
    assert all(page["total"] == 230 for page in pages)
    assert [page["has_more"] for page in pages] == [True, True, False]
    assert len(rows) == len({task["id"] for task in rows}) == 230
    assert [task["id"] for task in rows] == [
        task["id"] for task in sorted(rows, key=lambda task: (task["created_at"], task["id"]), reverse=True)
    ]

def test_existing_api_default_remains_priority(client):
    data = get(client, "")
    assert data["applied_filters"]["sort"] == "priority"
    priorities = [task["priority"] for task in data["tasks"]]
    assert priorities == sorted(priorities)
