# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Additive schema helpers for BACH tasks."""

import sqlite3


def parse_task_dependency_ids(value: object) -> tuple[list[int], list[str]]:
    """Parse a legacy ``depends_on`` value without trusting its contents.

    The column predates strict validation and therefore may contain labels such
    as ``P1``.  Callers need both the valid IDs and the invalid tokens so they
    can fail closed instead of crashing or treating malformed dependencies as
    satisfied.
    """
    if value is None:
        return [], []

    ids: list[int] = []
    invalid: list[str] = []
    seen: set[int] = set()
    for raw_token in str(value).replace(";", ",").split(","):
        token = raw_token.strip()
        if not token:
            continue
        try:
            task_id = int(token)
        except (TypeError, ValueError):
            invalid.append(token)
            continue
        if task_id <= 0:
            invalid.append(token)
            continue
        if task_id not in seen:
            ids.append(task_id)
            seen.add(task_id)
    return ids, invalid


def inspect_task_dependencies(
    conn: sqlite3.Connection,
    value: object,
) -> dict[str, object]:
    """Return a fail-closed dependency state for one task row."""
    ids, invalid = parse_task_dependency_ids(value)
    if not ids:
        return {
            "ids": ids,
            "invalid": invalid,
            "missing": [],
            "unfinished": [],
            "blocked": bool(invalid),
        }

    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, status FROM tasks WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    statuses = {int(row[0]): row[1] for row in rows}
    missing = [task_id for task_id in ids if task_id not in statuses]
    unfinished = [
        task_id for task_id in ids
        if task_id in statuses and statuses[task_id] != "done"
    ]
    return {
        "ids": ids,
        "invalid": invalid,
        "missing": missing,
        "unfinished": unfinished,
        "blocked": bool(invalid or missing or unfinished),
    }


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


def task_has_claim_columns(conn: sqlite3.Connection) -> bool:
    """Return whether the current ``tasks`` table exposes ``claimed_by`` and ``claimed_at``."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    return "claimed_by" in cols and "claimed_at" in cols


def ensure_task_claim_columns(conn: sqlite3.Connection) -> None:
    """Add the atomic claim columns and lookup index to an existing task table."""
    table = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'tasks'"
    ).fetchone()
    if not table or table[0] != "table":
        raise RuntimeError("Task-Migration abgebrochen: tasks-Tabelle fehlt.")

    for col in ("claimed_by TEXT", "claimed_at TEXT"):
        name = col.split()[0]
        if not any(row[1] == name for row in conn.execute("PRAGMA table_info(tasks)")):
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_claimed_at ON tasks(claimed_at)"
    )


def ensure_task_slot_columns(conn: sqlite3.Connection) -> None:
    """Add optional model and slot routing fields to an existing tasks table."""
    table = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = 'tasks'"
    ).fetchone()
    if not table or table[0] != "table":
        raise RuntimeError("Task-Migration abgebrochen: tasks-Tabelle fehlt.")

    columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    for name in ("required_model", "assigned_slot"):
        if name not in columns:
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
