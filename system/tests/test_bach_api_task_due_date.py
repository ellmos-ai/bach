# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Due-date contract tests for the structured BACH task API."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from bach_api import BachAPIError, _TaskProxy


def test_structured_task_add_forwards_due_date_keyword(monkeypatch):
    proxy = _TaskProxy("task")
    captured = {}

    def fake_raw(operation, *args):
        captured["operation"] = operation
        captured["args"] = args
        return True, "[OK] Task 41 erstellt: Termin"

    monkeypatch.setattr(proxy, "raw", fake_raw)
    monkeypatch.setattr(
        proxy,
        "show",
        lambda task_id: {"id": task_id, "title": "Termin", "due_date": "2026-09-15"},
    )

    created = proxy.add("Termin", due_date="2026-09-15")

    assert captured == {
        "operation": "add",
        "args": (
            "Termin",
            "--priority",
            "P3",
            "--category",
            "general",
            "--due",
            "2026-09-15",
        ),
    }
    assert created["due_date"] == "2026-09-15"


def test_structured_task_add_accepts_rheingold_lead_success(monkeypatch):
    proxy = _TaskProxy("task")
    monkeypatch.setattr(
        proxy,
        "raw",
        lambda operation, *args: (
            True,
            "[OK] Task #1340 via Rheingold-Lead (http://lead.invalid) erstellt: Folgeaufgabe",
        ),
    )
    monkeypatch.setattr(
        proxy,
        "show",
        lambda task_id: {"id": task_id, "title": "Folgeaufgabe"},
    )

    created = proxy.add("Folgeaufgabe")

    assert created["id"] == 1340
    assert "Rheingold-Lead" in created["_message"]


@pytest.mark.parametrize(
    "args",
    [
        ("--due", "2026-09-15"),
        ("--due=2026-09-15",),
    ],
)
def test_structured_task_add_forwards_due_date_positional_forms(monkeypatch, args):
    proxy = _TaskProxy("task")
    captured = {}

    def fake_raw(operation, *raw_args):
        captured["args"] = raw_args
        return True, "[OK] Task 42 erstellt: Termin"

    monkeypatch.setattr(proxy, "raw", fake_raw)
    monkeypatch.setattr(proxy, "show", lambda task_id: {"id": task_id})

    proxy.add("Termin", *args)

    assert captured["args"][-2:] == ("--due", "2026-09-15")


def test_structured_task_add_surfaces_due_date_validation_failure(monkeypatch):
    proxy = _TaskProxy("task")
    monkeypatch.setattr(
        proxy,
        "raw",
        lambda operation, *args: (
            False,
            "Ungültiges Fälligkeitsdatum. Erwartet: YYYY-MM-DD",
        ),
    )

    with pytest.raises(BachAPIError, match="YYYY-MM-DD"):
        proxy.add("Termin", due_date="15.09.2026")


@pytest.mark.parametrize("with_due_column", [True, False])
def test_structured_task_list_exposes_due_date_with_legacy_fallback(
    monkeypatch,
    with_due_column,
):
    proxy = _TaskProxy("task")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    due_column = ", due_date TEXT" if with_due_column else ""
    conn.execute(
        "CREATE TABLE tasks ("
        "id INTEGER PRIMARY KEY, priority TEXT, title TEXT, status TEXT, "
        "category TEXT, description TEXT, assigned_to TEXT, delegated_to TEXT, "
        "depends_on TEXT, created_at TEXT, completed_at TEXT, updated_at TEXT"
        f"{due_column})"
    )
    insert_columns = "id, priority, title, status"
    insert_values = "1, 'P3', 'Termin', 'pending'"
    if with_due_column:
        insert_columns += ", due_date"
        insert_values += ", '2026-09-15'"
    conn.execute(f"INSERT INTO tasks ({insert_columns}) VALUES ({insert_values})")
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    rows = proxy.list()

    expected_due = "2026-09-15" if with_due_column else None
    assert rows[0]["due_date"] == expected_due


def test_structured_task_list_fails_closed_on_malformed_dependency(monkeypatch):
    proxy = _TaskProxy("task")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE tasks ("
        "id INTEGER PRIMARY KEY, priority TEXT, title TEXT, status TEXT, "
        "category TEXT, description TEXT, assigned_to TEXT, delegated_to TEXT, "
        "depends_on TEXT, created_at TEXT, completed_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO tasks (id, priority, title, status, depends_on) "
        "VALUES (1, 'P3', 'Legacy', 'done', 'P1')"
    )
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    rows = proxy.list(status=None)

    assert rows[0]["is_blocked_by_dep"] is True


def _make_task_conn(rows, with_due=False):
    """In-memory tasks table populated with the given row dicts."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    due_col = ", due_date TEXT" if with_due else ""
    conn.execute(
        "CREATE TABLE tasks ("
        "id INTEGER PRIMARY KEY, priority TEXT, title TEXT, status TEXT, "
        "category TEXT, description TEXT, assigned_to TEXT, delegated_to TEXT, "
        "depends_on TEXT, created_at TEXT, completed_at TEXT, updated_at TEXT"
        f"{due_col})"
    )
    defaults = {
        "priority": "P3",
        "category": "general",
        "description": "",
        "depends_on": "",
        "created_at": "",
        "completed_at": "",
        "updated_at": "",
        "assigned_to": "",
        "delegated_to": "",
    }
    for row in rows:
        data = {**defaults, **row}
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        conn.execute(
            f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
            tuple(data.values()),
        )
    return conn


def test_structured_task_list_assigned_to_matches_assigned_or_delegated(monkeypatch):
    proxy = _TaskProxy("task")
    conn = _make_task_conn([
        {"id": 1, "title": "A", "status": "pending", "assigned_to": "HUB"},
        {"id": 2, "title": "B", "status": "pending", "delegated_to": "HUB"},
        {"id": 3, "title": "C", "status": "pending", "assigned_to": "OTHER"},
    ])
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    rows = proxy.list(assigned_to="hub")

    assert {row["id"] for row in rows} == {1, 2}


def test_structured_task_list_unassigned_only_empty_owner_fields(monkeypatch):
    proxy = _TaskProxy("task")
    conn = _make_task_conn([
        {"id": 1, "title": "A", "status": "pending", "assigned_to": "HUB"},
        {"id": 2, "title": "B", "status": "pending", "delegated_to": "HUB"},
        {"id": 3, "title": "C", "status": "pending"},
        {"id": 4, "title": "D", "status": "pending", "assigned_to": "X", "delegated_to": "Y"},
    ])
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    rows = proxy.list(unassigned=True)

    assert {row["id"] for row in rows} == {3}


@pytest.mark.parametrize(
    "args, expected_ids",
    [
        (("--assigned=HUB",), {1, 2}),
        (("--assigned", "HUB"), {1, 2}),
        (("--unassigned",), {3}),
    ],
)
def test_structured_task_list_assigned_unassigned_cli_forms(monkeypatch, args, expected_ids):
    proxy = _TaskProxy("task")
    conn = _make_task_conn([
        {"id": 1, "title": "A", "status": "pending", "assigned_to": "HUB"},
        {"id": 2, "title": "B", "status": "pending", "delegated_to": "HUB"},
        {"id": 3, "title": "C", "status": "pending"},
    ])
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    rows = proxy.list(*args)

    assert {row["id"] for row in rows} == expected_ids


def test_structured_task_list_assigned_combined_with_status_and_filter(monkeypatch):
    proxy = _TaskProxy("task")
    conn = _make_task_conn([
        {"id": 1, "title": "A assigned hub", "status": "pending", "assigned_to": "HUB"},
        {"id": 2, "title": "B delegated hub", "status": "pending", "delegated_to": "HUB"},
        {"id": 3, "title": "E done assigned hub", "status": "done", "assigned_to": "HUB"},
    ])
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    assert {row["id"] for row in proxy.list("done", "--assigned=HUB")} == {3}
    assert {row["id"] for row in proxy.list("pending", "--assigned=HUB", "--filter", "delegated")} == {2}


def test_structured_task_list_in_progress_and_open(monkeypatch):
    proxy = _TaskProxy("task")
    conn = _make_task_conn([
        {"id": 1, "title": "Pending Task", "status": "pending"},
        {"id": 2, "title": "In Progress Task", "status": "in_progress"},
        {"id": 3, "title": "Done Task", "status": "done"},
    ])
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    in_prog = proxy.list("in_progress")
    assert {r["id"] for r in in_prog} == {2}

    open_tasks = proxy.list("open")
    assert {r["id"] for r in open_tasks} == {1, 2}


def test_structured_task_reap(monkeypatch):
    proxy = _TaskProxy("task")
    conn = _make_task_conn([
        {"id": 1, "title": "Old Task", "status": "in_progress"},
    ])
    from hub._services.task_schema import ensure_task_claim_columns
    ensure_task_claim_columns(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS task_history (id INTEGER PRIMARY KEY, task_id INTEGER, action TEXT, field_changed TEXT, old_value TEXT, new_value TEXT, changed_by TEXT, changed_at TEXT)")
    conn.execute("UPDATE tasks SET claimed_at = '2026-01-01T00:00:00.000000', claimed_by = 'worker' WHERE id = 1")
    conn.commit()
    monkeypatch.setattr(proxy, "_connect", lambda: conn)

    reaped = proxy.reap(lease_seconds=1800)
    assert reaped == [1]

    row = conn.execute("SELECT status, claimed_by, claimed_at FROM tasks WHERE id = 1").fetchone()
    assert row[0] == "pending"
    assert row[1] is None
    assert row[2] is None


def _task_db(tmp_path, monkeypatch, rows):
    import bach_api

    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, status TEXT, priority TEXT, "
        "category TEXT, description TEXT, assigned_to TEXT, delegated_to TEXT, depends_on TEXT, "
        "created_at TEXT, completed_at TEXT, updated_at TEXT, due_date TEXT)"
    )
    conn.executemany("INSERT INTO tasks (title, status, priority) VALUES (?, ?, 'P3')", rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(bach_api, "_resolve_db_path", lambda: db)


def test_task_list_status_all_returns_every_status(tmp_path, monkeypatch):
    _task_db(tmp_path, monkeypatch, [("a", "pending"), ("b", "done"), ("c", "blocked")])
    proxy = _TaskProxy("task")
    assert {t["title"] for t in proxy.list(status="all")} == {"a", "b", "c"}
    assert {t["title"] for t in proxy.list("all")} == {"a", "b", "c"}
    assert [t["title"] for t in proxy.list(status="all", filter_text="b")] == ["b"]


def test_task_list_status_all_on_empty_db_is_empty_not_error(tmp_path, monkeypatch):
    _task_db(tmp_path, monkeypatch, [])
    assert _TaskProxy("task").list(status="all") == []
