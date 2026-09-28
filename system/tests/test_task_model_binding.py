# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for Task Model Binding (#1386).

Covers:
- Migration 050 idempotency (Python and SQL)
- Task pickup / offene_tasks filtering (match, mismatch, unbound)
- GET /api/activity enrichment with required_model and assigned_slot from tasks
"""

import importlib
import os
import sqlite3
from pathlib import Path

import pytest

from hub._services.chat.slots_config import (
    get_activity_history,
    initialize_slots_config,
    record_activity,
)
from hub._services.chat.task_runner import offene_tasks
from hub._services.task_schema import ensure_task_slot_columns

SYSTEM_ROOT = Path(__file__).resolve().parent.parent


def test_migration_050_idempotent(tmp_path):
    """Applying migration 050 twice must succeed and keep columns intact."""
    db_path = tmp_path / "test_migration.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE tasks ("
            "id INTEGER PRIMARY KEY, "
            "title TEXT NOT NULL, "
            "status TEXT DEFAULT 'pending')"
        )
        conn.commit()

        # Apply python migration run 1
        ensure_task_slot_columns(conn)
        conn.commit()

        cols_1 = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        assert "required_model" in cols_1
        assert "assigned_slot" in cols_1

        # Apply python migration run 2 (idempotency check)
        ensure_task_slot_columns(conn)
        conn.commit()

        cols_2 = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        assert cols_1 == cols_2

    # Verify SQL file exists and statements run cleanly on a fresh table
    sql_path = SYSTEM_ROOT / "data" / "schema" / "migrations" / "051_task_model_binding.sql"
    assert sql_path.exists(), "051_task_model_binding.sql does not exist"

    sql_db = tmp_path / "test_sql.db"
    with sqlite3.connect(sql_db) as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
        conn.commit()
        # Execute each ALTER TABLE statement from sql file
        sql_content = sql_path.read_text(encoding="utf-8")
        for statement in sql_content.split(";"):
            lines = [l for l in statement.splitlines() if not l.strip().startswith("--")]
            stmt = "\n".join(lines).strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()

        cols_sql = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        assert "required_model" in cols_sql
        assert "assigned_slot" in cols_sql


def test_offene_tasks_model_and_slot_filtering(tmp_path):
    """offene_tasks must respect required_model and assigned_slot bindings."""
    db_path = tmp_path / "test_binding_tasks.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE tasks ("
            "id INTEGER PRIMARY KEY, "
            "title TEXT NOT NULL, "
            "description TEXT, "
            "status TEXT DEFAULT 'pending', "
            "priority TEXT DEFAULT 'P2', "
            "project TEXT DEFAULT 'bach', "
            "category TEXT DEFAULT 'general', "
            "depends_on TEXT, "
            "required_model TEXT, "
            "assigned_slot TEXT)"
        )
        conn.executemany(
            "INSERT INTO tasks (id, title, description, status, required_model, assigned_slot) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "Task Bound Chat Qwen", "desc 1", "pending", "qwen3.5:4b", "buddha_chat"),
                (2, "Task Bound Model Only", "desc 2", "pending", "claude-3-7-sonnet", None),
                (3, "Task Bound Slot Only", "desc 3", "pending", None, "buddha_always_on"),
                (4, "Task Unbound", "desc 4", "pending", None, None),
                (5, "Task Already Done", "desc 5", "done", "qwen3.5:4b", "buddha_chat"),
            ],
        )
        conn.commit()

    # Slot buddha_chat with qwen3.5:4b -> Matches Task 1 (exact match) and Task 4 (unbound)
    slot_qwen_chat = {"id": "buddha_chat", "model": "qwen3.5:4b"}
    tasks_1 = offene_tasks(str(db_path), "all", slot=slot_qwen_chat)
    task_ids_1 = [t["id"] for t in tasks_1]
    assert task_ids_1 == [1, 4]

    # Slot buddha_chat with different model -> Task 1 skipped (mismatched model), Task 4 matches
    slot_sonnet_chat = {"id": "buddha_chat", "model": "claude-3-7-sonnet"}
    tasks_2 = offene_tasks(str(db_path), "all", slot=slot_sonnet_chat)
    task_ids_2 = [t["id"] for t in tasks_2]
    assert task_ids_2 == [2, 4]

    # Slot buddha_always_on with sonnet -> Matches Task 2 (model match), Task 3 (slot match), Task 4 (unbound)
    slot_always_sonnet = {"id": "buddha_always_on", "model": "claude-3-7-sonnet"}
    tasks_3 = offene_tasks(str(db_path), "all", slot=slot_always_sonnet)
    task_ids_3 = [t["id"] for t in tasks_3]
    assert task_ids_3 == [2, 3, 4]

    # Without slot restriction -> all open tasks returned
    tasks_all = offene_tasks(str(db_path), "all")
    task_ids_all = [t["id"] for t in tasks_all]
    assert task_ids_all == [4]


def test_api_activity_enrichment(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    import hub.bach_paths

    """GET /api/activity must enrich history items that have task_id with task routing info."""
    db_path = tmp_path / "test_activity_bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE tasks ("
            "id INTEGER PRIMARY KEY, "
            "title TEXT NOT NULL, "
            "status TEXT DEFAULT 'pending', "
            "required_model TEXT, "
            "assigned_slot TEXT)"
        )
        conn.execute(
            "INSERT INTO tasks (id, title, required_model, assigned_slot) "
            "VALUES (42, 'Special Task', 'qwen3.8:27b-mlx', 'buddha_always_on')"
        )
        conn.commit()

    monkeypatch.setattr(hub.bach_paths, "BACH_DB", db_path)
    monkeypatch.setenv("BACH_DB", str(db_path))

    cfg_file = tmp_path / "activity-slots.json"
    monkeypatch.setenv("BACH_SLOTS_CONFIG_PATH", str(cfg_file))
    initialize_slots_config(str(cfg_file))

    # Record item with task_id
    record_activity(
        "worker_1",
        "Bearbeite Task 42",
        status="running",
        details={"task_id": 42},
        path=str(cfg_file),
    )
    # Record item without task_id
    record_activity(
        "system",
        "System heartbeat",
        status="ok",
        details={},
        path=str(cfg_file),
    )

    control = importlib.import_module("hub._services.chat.telegram_chat")

    monkeypatch.setattr(
        "hub._services.chat.telegram_chat.get_activity_history",
        lambda **kwargs: get_activity_history(**kwargs, path=str(cfg_file)),
    )

    handler = control.ControlHandler.__new__(control.ControlHandler)
    responses = []
    monkeypatch.setattr(handler, "_json", lambda body, code=200: responses.append((body, code)))

    handler.path = "/api/activity?limit=10&order=desc"
    handler.do_GET()

    assert responses[-1][1] == 200
    res_body = responses[-1][0]
    assert res_body["ok"] is True
    history = res_body["history"]
    assert len(history) == 2

    # Find the task-related item and heartbeat item
    task_item = next(h for h in history if h.get("source") == "worker_1")
    sys_item = next(h for h in history if h.get("source") == "system")

    # Enriched fields check
    assert task_item.get("required_model") == "qwen3.8:27b-mlx"
    assert task_item.get("assigned_slot") == "buddha_always_on"

    assert sys_item.get("required_model") is None
    assert sys_item.get("assigned_slot") is None
