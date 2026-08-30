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
