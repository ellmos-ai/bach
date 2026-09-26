# -*- coding: utf-8 -*-
"""Harden session provenance triggers and close stale open sessions."""

import importlib.util
import logging
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
logger = logging.getLogger(__name__)


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def run_migration(conn=None) -> list[tuple[int, str]]:
    """Replace legacy provenance triggers and close stale open sessions."""
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB

        conn = sqlite3.connect(BACH_DB)

    if not _table_exists(conn, "memory_sessions"):
        if owns_connection:
            conn.close()
        return []

    try:
        for table in mu.PROVENANCE_TABLES:
            conn.execute(f"DROP TRIGGER IF EXISTS trg_{table}_session_provenance_insert")
            conn.execute(f"DROP TRIGGER IF EXISTS trg_{table}_session_provenance_update")
        mu.install_provenance_triggers(conn)
        stale_where = (
            "ended_at IS NULL "
            f"AND datetime(started_at) < datetime('now', 'localtime', '-{mu._SESSION_STALENESS_HOURS} hours')"
        )
        closed_sessions = [
            (int(session_id), str(session_key))
            for session_id, session_key in conn.execute(
                f"SELECT id, session_id FROM memory_sessions WHERE {stale_where}"
            ).fetchall()
        ]
        conn.execute(
            f"""
            UPDATE memory_sessions
            SET ended_at = strftime('%Y-%m-%dT%H:%M:%f', 'now', 'localtime') || '000',
                summary = CASE
                    WHEN summary IS NULL THEN '[AUTO-CLOSED: stale]'
                    ELSE summary || ' [AUTO-CLOSED: stale]'
                END
            WHERE {stale_where}
            """
        )
        for session_id, session_key in closed_sessions:
            logger.info(
                "Auto-closed stale memory session id=%s session_id=%s",
                session_id,
                session_key,
            )
        if owns_connection:
            conn.commit()
        return closed_sessions
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    for session_id, session_key in run_migration():
        print(f"Auto-closed stale session id={session_id} session_id={session_key}")
