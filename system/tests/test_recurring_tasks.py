# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
RECURRING_ROOT = SYSTEM_ROOT / "hub" / "_services" / "recurring"

if str(RECURRING_ROOT) not in sys.path:
    sys.path.insert(0, str(RECURRING_ROOT))

import recurring_tasks


def test_list_recurring_tasks_not_due_until_exact_timestamp(monkeypatch):
    last_run = datetime.now() - timedelta(days=14) + timedelta(hours=1)
    config = {
        "recurring_tasks": {
            "edge_case": {
                "enabled": True,
                "interval_days": 14,
                "task_text": "Edge case",
                "target": "tasks",
                "last_run": last_run.isoformat(),
            }
        }
    }

    monkeypatch.setattr(recurring_tasks, "load_config", lambda: config)
    monkeypatch.setattr(recurring_tasks, "load_state", lambda: {"last_runs": {}})

    tasks = recurring_tasks.list_recurring_tasks()

    assert tasks["edge_case"]["days_until"] == 0
    assert tasks["edge_case"]["is_due"] is False


def test_list_recurring_tasks_due_after_deadline_passes(monkeypatch):
    last_run = datetime.now() - timedelta(days=14, minutes=1)
    config = {
        "recurring_tasks": {
            "overdue": {
                "enabled": True,
                "interval_days": 14,
                "task_text": "Overdue case",
                "target": "tasks",
                "last_run": last_run.isoformat(),
            }
        }
    }

    monkeypatch.setattr(recurring_tasks, "load_config", lambda: config)
    monkeypatch.setattr(recurring_tasks, "load_state", lambda: {"last_runs": {}})

    tasks = recurring_tasks.list_recurring_tasks()

    assert tasks["overdue"]["days_until"] == 0
    assert tasks["overdue"]["is_due"] is True


def test_list_recurring_tasks_prefers_local_state_last_run(monkeypatch):
    config_last_run = datetime.now() - timedelta(days=30)
    state_last_run = datetime.now() - timedelta(days=1)
    config = {
        "recurring_tasks": {
            "stateful": {
                "enabled": True,
                "interval_days": 14,
                "task_text": "Stateful case",
                "target": "tasks",
                "last_run": config_last_run.isoformat(),
            }
        }
    }

    monkeypatch.setattr(recurring_tasks, "load_config", lambda: config)
    monkeypatch.setattr(
        recurring_tasks,
        "load_state",
        lambda: {"last_runs": {"stateful": state_last_run.isoformat()}},
    )

    tasks = recurring_tasks.list_recurring_tasks()

    assert tasks["stateful"]["last_run"] == state_last_run.isoformat()
    assert tasks["stateful"]["is_due"] is False


def test_set_last_run_writes_ignored_runtime_state(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    when = datetime(2026, 6, 18, 12, 0, 0)
    monkeypatch.setattr(recurring_tasks, "STATE_FILE", state_file)

    recurring_tasks._set_last_run("demo", when)

    assert recurring_tasks.load_state()["last_runs"]["demo"] == when.isoformat()


def test_create_bach_task_routes_through_handler_and_accepts_negative_draft(monkeypatch):
    calls = []

    class FakeTaskHandler:
        def handle(self, operation, args):
            calls.append((operation, args))
            return True, (
                "[OFFLINE] Task als Entwurf draft:abc (ID -7) im lokalen "
                "Bachgrund gespeichert"
            )

    monkeypatch.setattr(recurring_tasks, "_find_open_task_id", lambda *args: None)
    monkeypatch.setattr(recurring_tasks, "_task_handler", FakeTaskHandler)

    result = recurring_tasks.create_task_in_bach("Recurring demo", "P2", "BACH")

    assert result.status == "created"
    assert result.task_id == -7
    assert calls == [
        (
            "add",
            [
                "Recurring demo",
                "--priority",
                "P2",
                "--category",
                "BACH",
                "--creation-origin",
                "recurring",
            ],
        )
    ]


def test_create_bach_task_normalizes_titles_before_duplicate_check(tmp_path, monkeypatch):
    from hub.task import TaskHandler

    db_path = tmp_path / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority TEXT,
                category TEXT,
                description TEXT,
                status TEXT,
                created_at TEXT,
                source TEXT
            )
        """)

    monkeypatch.setattr(recurring_tasks, "USER_DB", db_path)

    def task_handler():
        handler = TaskHandler(SYSTEM_ROOT)
        handler.db_path = db_path
        return handler

    monkeypatch.setattr(recurring_tasks, "_task_handler", task_handler)
    title = "Review developer's notes"

    created = recurring_tasks.create_task_in_bach(title, "P2", "BACH")
    duplicate = recurring_tasks.create_task_in_bach(title, "P2", "BACH")

    assert created.status == "created"
    assert duplicate.status == "duplicate"
    assert duplicate.task_id == created.task_id
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT title, source, creation_origin FROM tasks"
        ).fetchone()
    assert row == ("Review developers notes", None, "recurring")


def test_create_bach_task_detects_legacy_raw_title(tmp_path, monkeypatch):
    db_path = tmp_path / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT
            )
        """)
        conn.execute(
            "INSERT INTO tasks (id, title, status) VALUES (42, ?, 'pending')",
            ("Review developer's notes",),
        )

    monkeypatch.setattr(recurring_tasks, "USER_DB", db_path)
    monkeypatch.setattr(
        recurring_tasks,
        "_task_handler",
        lambda: (_ for _ in ()).throw(AssertionError("handler must not run")),
    )

    result = recurring_tasks.create_task_in_bach(
        "Review developer's notes", "P2", "BACH"
    )

    assert result.status == "duplicate"
    assert result.task_id == 42


def test_create_bach_task_reports_duplicate_without_calling_handler(monkeypatch):
    monkeypatch.setattr(recurring_tasks, "_find_open_task_id", lambda *args: 1346)
    monkeypatch.setattr(
        recurring_tasks,
        "_task_handler",
        lambda: (_ for _ in ()).throw(AssertionError("handler must not run")),
    )

    result = recurring_tasks.create_task_in_bach("Recurring demo", "P2", "BACH")

    assert result.status == "duplicate"
    assert result.task_id == 1346


def test_create_ati_task_routes_through_handler_with_recurring_metadata(monkeypatch):
    calls = []

    class FakeATIHandler:
        def handle(self, operation, args):
            calls.append((operation, args))
            return True, "[ATI TASK] Task #23 erstellt: Recurring ATI"

    monkeypatch.setattr(recurring_tasks, "_find_open_task_id", lambda *args: None)
    monkeypatch.setattr(recurring_tasks, "_ati_handler", FakeATIHandler)

    result = recurring_tasks.create_task_in_ati(
        "Recurring ATI", "hoch", 85, "recurring,demo"
    )

    assert result.status == "created"
    assert result.task_id == 23
    assert calls == [
        (
            "task",
            [
                "add",
                "Recurring ATI",
                "--tool",
                "BACH",
                "--aufwand",
                "hoch",
                "--priority-score",
                "85",
                "--source",
                "recurring",
                "--tags",
                "recurring,demo",
            ],
        )
    ]


def test_check_recurring_tasks_counts_negative_draft_as_created(monkeypatch):
    config = {
        "recurring_tasks": {
            "worker_demo": {
                "enabled": True,
                "interval_days": 7,
                "task_text": "Worker draft",
                "target": "tasks",
            }
        }
    }
    last_runs = []
    monkeypatch.setattr(recurring_tasks, "load_config", lambda: config)
    monkeypatch.setattr(recurring_tasks, "load_state", lambda: {"last_runs": {}})
    monkeypatch.setattr(
        recurring_tasks,
        "create_task_in_bach",
        lambda *args: recurring_tasks.CreationResult("created", -1),
    )
    monkeypatch.setattr(
        recurring_tasks, "_set_last_run", lambda task_id, when: last_runs.append(task_id)
    )

    assert recurring_tasks.check_recurring_tasks() == ["Worker draft"]
    assert last_runs == ["worker_demo"]
