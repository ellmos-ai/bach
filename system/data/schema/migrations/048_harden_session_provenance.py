# -*- coding: utf-8 -*-
"""Harden session provenance triggers and close stale open sessions."""

import importlib.util
import sqlite3
from pathlib import Path


_HERE = Path(__file__).resolve().parent.parent / "memory_union"


def _union_module():
    spec = importlib.util.spec_from_file_location(
        "bach_memory_union_048", _HERE / "memory_union.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mu = _union_module()


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def run_migration(conn=None):
    """Replace legacy provenance triggers and close stale open sessions."""
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(BACH_DB)

    if not _table_exists(conn, "memory_sessions"):
        if owns_connection:
            conn.close()
        return

    try:
        for table in mu.PROVENANCE_TABLES:
            conn.execute(f"DROP TRIGGER IF EXISTS trg_{table}_session_provenance_insert")
            conn.execute(f"DROP TRIGGER IF EXISTS trg_{table}_session_provenance_update")
        mu.install_provenance_triggers(conn)
        conn.execute(
            f"""
            UPDATE memory_sessions
            SET ended_at = datetime('now'),
                summary = COALESCE(summary, '') || ' [AUTO-CLOSED: stale]'
            WHERE ended_at IS NULL
              AND started_at < datetime('now', '-{mu._SESSION_STALENESS_HOURS} hours')
            """
        )
        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    run_migration()
