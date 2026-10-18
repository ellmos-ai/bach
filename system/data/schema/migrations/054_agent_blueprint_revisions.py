# SPDX-License-Identifier: MIT
"""Create immutable blueprint revision pins for existing and new agent definitions."""

import sqlite3

from hub._services.blueprint_service import ensure_blueprint_schema


def run_migration(conn: sqlite3.Connection | None = None) -> None:
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(str(BACH_DB))
        conn.row_factory = sqlite3.Row

    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_blueprint_schema(conn, commit=False)
        if owns_connection:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    run_migration()
