# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Add the Routinika-compatible ISO due date to BACH tasks."""

import sqlite3

from hub._services.task_schema import ensure_task_due_date


def run_migration(conn: sqlite3.Connection | None = None) -> None:
    """Apply the additive task migration, optionally using the canonical DB."""
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(str(BACH_DB))

    try:
        ensure_task_due_date(conn)
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    run_migration()
