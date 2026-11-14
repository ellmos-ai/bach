# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB-3 (#3987): `bach task list` darf unbekannte Filter nicht still auf pending fallen lassen
und eine Kappung nicht verschweigen."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.task import TaskHandler  # noqa: E402


@pytest.fixture
def handler(tmp_path):
    db = tmp_path / "tasks.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, status TEXT, priority TEXT, "
            "category TEXT, assigned_to TEXT, delegated_to TEXT, depends_on TEXT, due_date TEXT)"
        )
        rows = [(i, f"pending-{i}", "pending") for i in range(1, 13)]
        rows += [(100, "in-review", "review"), (200, "gone", "archived"), (201, "gone2", "archived")]
        conn.executemany("INSERT INTO tasks (id,title,status,priority) VALUES (?,?,?,'P2')", rows)
    h = TaskHandler.__new__(TaskHandler)
    h.db_path = db
    return h


def test_list_review_zeigt_review_tasks_nicht_pending(handler):
    ok, out = handler.handle("list", ["review"])
    assert ok is True
    assert "in-review" in out and "pending-1" not in out
    assert "(review)" in out


def test_list_archived_zeigt_archivierte_nicht_pending(handler):
    ok, out = handler.handle("list", ["archived"])
    assert ok is True
    assert "gone" in out and "gone2" in out and "pending-1" not in out


def test_list_unbekannter_filter_ist_fehler_mit_erlaubten_werten(handler):
    ok, out = handler.handle("list", ["bogus"])
    assert ok is False
    assert "bogus" in out and "review" in out and "archived" in out


def test_list_limit_zeigt_weitere_statt_stiller_kappung(handler):
    ok, out = handler.handle("list", ["pending", "--limit", "5"])
    assert ok is True
    assert out.count("pending-") == 5
    assert "7 weitere" in out


def test_list_ohne_limit_zeigt_alle(handler):
    ok, out = handler.handle("list", ["pending"])
    assert ok is True and out.count("pending-") == 12
    assert "weitere" not in out
