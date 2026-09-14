# -*- coding: utf-8 -*-
"""Add per-entry BACH session provenance to memory tables.

Historical records are deliberately left NULL: inferring an author from a
timestamp would create false privacy and audit claims.  SQLite triggers cover
all existing write paths, including legacy, GUI, and service inserts.
The optional connection supports both the core migration runner and the
legacy ``bach update migrations run`` entrypoint.
"""

import sqlite3


MEMORY_TABLES = ("memory_working", "memory_facts", "memory_lessons")


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _active_session_sql():
    return (
        "SELECT session_id FROM memory_sessions "
        "WHERE ended_at IS NULL ORDER BY started_at DESC, id DESC LIMIT 1"
    )


def _install_triggers(conn, table):
    active_session = _active_session_sql()
    conn.executescript(
        f"""
        CREATE TRIGGER IF NOT EXISTS trg_{table}_session_provenance_insert
        AFTER INSERT ON {table}
        WHEN NEW.created_by_session_id IS NULL
        BEGIN
            UPDATE {table}
            SET created_by_session_id = ({active_session}),
                updated_by_session_id = ({active_session})
            WHERE id = NEW.id;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_{table}_session_provenance_update
        AFTER UPDATE ON {table}
        WHEN NEW.updated_by_session_id IS OLD.updated_by_session_id
        BEGIN
            UPDATE {table}
            SET updated_by_session_id = ({active_session})
            WHERE id = NEW.id
              AND EXISTS (SELECT 1 FROM memory_sessions WHERE ended_at IS NULL);
        END;
        """
    )


def run_migration(conn=None):
    """Make provenance additive and safe for existing BACH databases."""
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(BACH_DB)

    if not _table_exists(conn, "memory_sessions"):
        if owns_connection:
            conn.close()
        return

    try:
        for table in MEMORY_TABLES:
            if not _table_exists(conn, table):
                continue
            columns = _columns(conn, table)
            if "created_by_session_id" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN created_by_session_id TEXT")
            if "updated_by_session_id" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN updated_by_session_id TEXT")
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_created_by_session "
                f"ON {table}(created_by_session_id)"
            )
            _install_triggers(conn, table)
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()
