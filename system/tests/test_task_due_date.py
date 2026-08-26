# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for the BACH task due-date contract."""

import importlib.util
import re
import sqlite3
import sys
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

MIGRATION = (
    SYSTEM_ROOT
    / "data"
    / "schema"
    / "migrations"
    / "038_task_due_date.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_038_task_due_date", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _task_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}


@pytest.mark.parametrize(
    "schema_name",
    ["schema.sql", "schema_bach.sql", "schema_user_v2.sql"],
)
def test_fresh_schemas_define_due_date(schema_name):
    schema = (SYSTEM_ROOT / "data" / "schema" / schema_name).read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS tasks\s*\(.*?\);",
        schema,
        flags=re.DOTALL,
    )
    assert match is not None
    with sqlite3.connect(":memory:") as conn:
        conn.execute(match.group(0))
        assert "due_date" in _task_columns(conn)
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS idx_tasks_due_date\s+ON tasks\s*\(due_date\)",
        schema,
    )


def test_migration_adds_due_date_and_index_idempotently():
    module = _load_migration()
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")

        module.run_migration(conn)
        module.run_migration(conn)

        assert "due_date" in _task_columns(conn)
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(tasks)")}
        assert "idx_tasks_due_date" in indexes
