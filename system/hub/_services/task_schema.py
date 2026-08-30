# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Additive schema helpers for BACH tasks."""

import sqlite3


def task_has_due_date(conn: sqlite3.Connection) -> bool:
    """Return whether the current ``tasks`` table exposes ``due_date``."""
    return any(row[1] == "due_date" for row in conn.execute("PRAGMA table_info(tasks)"))


def ensure_task_due_date(conn: sqlite3.Connection) -> None:
    """Add the ISO date field and its lookup index to an existing task table."""
    table = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'tasks'"
    ).fetchone()
    if not table or table[0] != "table":
        raise RuntimeError("Task-Migration abgebrochen: tasks-Tabelle fehlt.")

    if not task_has_due_date(conn):
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)"
    )
