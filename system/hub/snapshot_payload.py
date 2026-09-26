# SPDX-License-Identifier: MIT
"""
Read-only BACH session-checkpoint payload collector.
====================================================

INACTIVE PREPARATION SEAM.

This module is NOT wired into SnapshotHandler and does NOT change any
create / load / delete / list or restore behaviour. It only collects the same
payload that ``SnapshotHandler._create`` currently builds into ``snapshot_data``,
so the collection logic can be unit-tested in isolation against temporary
databases without touching the canonical live DB.

The returned payload has exactly six fields, identical to the JSON object that
``SnapshotHandler._create`` stores in ``session_snapshots.snapshot_data``:

    session_id, open_tasks, recent_memory, active_files, token_usage, created_at

Limits and ordering mirror ``SnapshotHandler._create`` exactly:
    - open_tasks:    at most 10 pending task (id, title) pairs
    - recent_memory: at most 5 active memory_working contents, newest by created_at
    - active_files:  at most 10 existing files_truth paths, newest by modified_at
    - token_usage:   newest monitor_tokens.tokens_total by id
    - session_id:    system_config current_session, falling back to "unknown"

The optional legacy tables ``files_truth`` and ``monitor_tokens`` may be absent;
in that case ``active_files`` yields ``[]`` and ``token_usage`` yields ``None``.

The database is always opened read-only via a SQLite URI (``mode=ro``), so the
caller's database file is never written to by this collector.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

# Limits mirrored exactly from SnapshotHandler._create.
OPEN_TASKS_LIMIT = 10
RECENT_MEMORY_LIMIT = 5
ACTIVE_FILES_LIMIT = 10


def _open_readonly(db_path: Union[str, "Path"]) -> "sqlite3.Connection":
    """Open the BACH SQLite database strictly read-only via a SQLite URI.

    Using ``mode=ro`` guarantees the collector never obtains a write handle on
    the database, so the canonical live DB can be inspected without risk of
    modification.
    """
    path = Path(db_path).resolve()
    uri = "file:" + str(path) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _current_session_id(cursor: "sqlite3.Cursor") -> str:
    """Current session id from system_config, falling back to 'unknown'."""
    cursor.execute("SELECT value FROM system_config WHERE key = 'current_session'")
    row = cursor.fetchone()
    return row[0] if row else "unknown"


def _open_tasks(cursor: "sqlite3.Cursor") -> list:
    """At most 10 pending task (id, title) pairs, mirroring _create."""
    cursor.execute(
        "SELECT id, title FROM tasks WHERE status = 'pending' "
        "LIMIT " + str(OPEN_TASKS_LIMIT)
    )
    return [{"id": r[0], "title": r[1]} for r in cursor.fetchall()]


def _recent_memory(cursor: "sqlite3.Cursor") -> list:
    """At most 5 active memory_working contents, newest by created_at."""
    cursor.execute(
        "SELECT content FROM memory_working WHERE is_active = 1 "
        "ORDER BY created_at DESC LIMIT " + str(RECENT_MEMORY_LIMIT)
    )
    return [r[0] for r in cursor.fetchall()]


def _active_files(cursor: "sqlite3.Cursor") -> list:
    """At most 10 existing files_truth paths, newest by modified_at.

    ``files_truth`` is an optional legacy table; when absent the result is [].
    """
    try:
        cursor.execute(
            "SELECT path FROM files_truth WHERE file_exists = 1 "
            "ORDER BY modified_at DESC LIMIT " + str(ACTIVE_FILES_LIMIT)
        )
        return [r[0] for r in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []


def _token_usage(cursor: "sqlite3.Cursor") -> Optional[int]:
    """Newest monitor_tokens.tokens_total by id, or None when absent.

    ``monitor_tokens`` is an optional legacy table; when absent the result is
    None.
    """
    try:
        row = cursor.execute(
            "SELECT tokens_total FROM monitor_tokens ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def collect_snapshot_payload(
    db_path: Union[str, "Path"],
    *,
    created_at: Optional[str] = None,
) -> dict:
    """Collect a read-only session-checkpoint payload from a BACH SQLite DB.

    Args:
        db_path: explicit path to the BACH SQLite database (never the caller's
            responsibility to open; the collector opens it read-only).
        created_at: optional ISO timestamp. When omitted,
            ``datetime.now().isoformat()`` is used. Injecting a value makes the
            payload deterministically testable without weakening production
            behaviour.

    Returns:
        A dict with exactly six keys:
            session_id, open_tasks, recent_memory, active_files,
            token_usage, created_at
    """
    if created_at is None:
        created_at = datetime.now().isoformat()

    conn = _open_readonly(db_path)
    try:
        cursor = conn.cursor()

        session_id = _current_session_id(cursor)
        open_tasks = _open_tasks(cursor)
        recent_memory = _recent_memory(cursor)
        active_files = _active_files(cursor)
        token_usage = _token_usage(cursor)

        return {
            "session_id": session_id,
            "open_tasks": open_tasks,
            "recent_memory": recent_memory,
            "active_files": active_files,
            "token_usage": token_usage,
            "created_at": created_at,
        }
    finally:
        conn.close()
