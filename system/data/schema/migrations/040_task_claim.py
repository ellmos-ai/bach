# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Add claimed_by and claimed_at columns for atomic task claim."""

import sqlite3

from hub._services.task_schema import ensure_task_claim_columns


def run_migration(conn: sqlite3.Connection | None = None) -> None:
    """Apply the additive task claim migration, optionally using the canonical DB."""
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(str(BACH_DB))

    try:
        ensure_task_claim_columns(conn)
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    run_migration()
