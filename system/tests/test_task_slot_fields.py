# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Task model and slot fields survive migration and public write paths."""

import asyncio
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from bach_api import _TaskProxy
from hub.task import TaskHandler


def test_migration_adds_routing_columns_idempotently():
    path = SYSTEM_ROOT / "data/schema/migrations/050_task_slot_routing.py"
    spec = importlib.util.spec_from_file_location("task_slot_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
        module.run_migration(conn)
        module.run_migration(conn)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(tasks)")]
        assert columns.count("required_model") == 1
        assert columns.count("assigned_slot") == 1


@pytest.fixture
def task_handler(tmp_path, monkeypatch):
    db_path = tmp_path / "bach.db"
    schema = (SYSTEM_ROOT / "data/schema/schema.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    handler = TaskHandler(tmp_path)
    handler.db_path = db_path
    monkeypatch.setenv("BACH_RHEINGOLD_DISABLED", "1")
    return handler, db_path


def test_cli_add_and_edit_routing_fields(task_handler):
    handler, db_path = task_handler
    ok, message = handler.handle("add", [
        "Cloud-Aufgabe", "--required-model", "glm-5.3:cloud",
        "--assigned-slot", "cloud_worker",
    ])
    assert ok, message
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, required_model, assigned_slot FROM tasks WHERE title = ?",
            ("Cloud-Aufgabe",),
        ).fetchone()
    assert row[1:] == ("glm-5.3:cloud", "cloud_worker")

    ok, message = handler.handle("edit", [
        str(row[0]), "--required-model", "qwen3.8:27b-mlx",
        "--assigned-slot", "local_worker",
    ])
    assert ok, message
    with sqlite3.connect(db_path) as conn:
        updated = conn.execute(
            "SELECT required_model, assigned_slot FROM tasks WHERE id = ?", (row[0],)
        ).fetchone()
        history = conn.execute(
            "SELECT field_changed FROM task_history WHERE task_id = ? ORDER BY id",
            (row[0],),
        ).fetchall()
    assert updated == ("qwen3.8:27b-mlx", "local_worker")
    assert [item[0] for item in history] == ["required_model", "assigned_slot"]


def test_structured_api_forwards_routing_fields(monkeypatch):
    proxy = _TaskProxy("task")
    captured = []

    def raw(operation, *args):
        captured.append((operation, args))
        if operation == "add":
            return True, "[OK] Task 7 erstellt: Cloud-Aufgabe"
        return True, "[OK] Task 7 bearbeitet"

    monkeypatch.setattr(proxy, "raw", raw)
    monkeypatch.setattr(proxy, "show", lambda task_id: {"id": int(task_id)})
    assert proxy.add(
        "Cloud-Aufgabe", required_model="glm-5.3:cloud", assigned_slot="cloud_worker"
    )["id"] == 7
    assert captured[0][1][-4:] == (
        "--required-model", "glm-5.3:cloud", "--assigned-slot", "cloud_worker"
    )
    assert proxy.edit(7, required_model="qwen3.8:27b-mlx", assigned_slot="local_worker")["id"] == 7
    assert captured[1] == (
        "edit",
        ("7", "--required-model", "qwen3.8:27b-mlx", "--assigned-slot", "local_worker"),
    )


def test_gui_http_create_persists_routing_fields(task_handler, monkeypatch):
    from gui import server

    _, db_path = task_handler
    monkeypatch.setattr(server, "get_bach_db", lambda: sqlite3.connect(db_path))
    response = asyncio.run(server.api_post_task({
        "title": "Cloud-Aufgabe",
        "required_model": "glm-5.3:cloud",
        "assigned_slot": "cloud_worker",
    }))
    assert response["success"] is True, response
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT required_model, assigned_slot FROM tasks WHERE id = ?",
            (response["id"],),
        ).fetchone()
    assert row == ("glm-5.3:cloud", "cloud_worker")
