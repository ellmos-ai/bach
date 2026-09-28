# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Atomic Distributed Leases (from Roshambo).

Provides an atomic, race-free task claiming mechanism for Bach workers and subagents,
solving Core Gap 1 (Kernlücke 1 in ROADMAP.md: "Kein atomarer Claim").
Compatible with SQLite (local ~/.bach/bach.db) and PostgreSQL / CockroachDB (Rheingold federation).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class TaskClaimResult:
    success: bool
    task_id: int
    claim_id: Optional[str]
    claimed_by: str
    holder: Optional[str]
    expires_at: Optional[str]
    reason: str


def ensure_task_lease_schema(conn: sqlite3.Connection) -> None:
    """Ensures lease tracking columns exist on the tasks table in SQLite."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(tasks)")
    columns = {row[1] for row in cursor.fetchall()}

    if "claim_id" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN claim_id TEXT")
    if "claimed_by" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN claimed_by TEXT")
    if "claim_expires_at" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN claim_expires_at TEXT")
    if "claim_heartbeat_at" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN claim_heartbeat_at TEXT")
    if "claim_host" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN claim_host TEXT")
    conn.commit()


def try_claim_task_atomic(
    conn: sqlite3.Connection,
    task_id: int,
    agent_id: str,
    host: str = "local",
    ttl_seconds: int = 300,
) -> TaskClaimResult:
    """
    Atomically claims a task in Bach without 'check-then-write' race conditions.
    
    A claim succeeds if:
    1. The task is pending/open and unassigned, OR
    2. Any existing lease has expired (current_time > claim_expires_at).
    """
    ensure_task_lease_schema(conn)
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    claim_id = str(uuid.uuid4())

    # Single atomic UPDATE with conditional WHERE
    cursor.execute(
        """
        UPDATE tasks
           SET claim_id = ?,
               claimed_by = ?,
               claim_expires_at = datetime('now', '+' || ? || ' seconds'),
               claim_heartbeat_at = datetime('now'),
               claim_host = ?,
               status = 'in_progress'
         WHERE id = ?
           AND (
               claim_expires_at IS NULL
               OR datetime('now') > datetime(claim_expires_at)
               OR status = 'pending'
               OR claimed_by = ?
           )
        """,
        (claim_id, agent_id, int(ttl_seconds), host, task_id, agent_id),
    )
    conn.commit()

    if cursor.rowcount > 0:
        cursor.execute("SELECT claim_expires_at FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        expires = row[0] if row else None
        return TaskClaimResult(
            success=True,
            task_id=task_id,
            claim_id=claim_id,
            claimed_by=agent_id,
            holder=agent_id,
            expires_at=expires,
            reason="Lease successfully acquired",
        )

    # Claim denied - query who currently holds the lease
    cursor.execute(
        "SELECT claimed_by, claim_expires_at FROM tasks WHERE id = ?",
        (task_id,),
    )
    row = cursor.fetchone()
    current_holder = row[0] if row else "unknown"
    current_expires = row[1] if row else "unknown"

    return TaskClaimResult(
        success=False,
        task_id=task_id,
        claim_id=None,
        claimed_by=agent_id,
        holder=current_holder,
        expires_at=current_expires,
        reason=f"Task already locked by {current_holder} until {current_expires}",
    )


def renew_task_lease(
    conn: sqlite3.Connection,
    task_id: int,
    claim_id: str,
    ttl_seconds: int = 300,
) -> bool:
    """Extends the heartbeat and expiration of an active lease."""
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE tasks
           SET claim_heartbeat_at = datetime('now'),
               claim_expires_at = datetime('now', '+' || ? || ' seconds')
         WHERE id = ?
           AND claim_id = ?
           AND datetime('now') <= datetime(claim_expires_at)
        """,
        (int(ttl_seconds), task_id, claim_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def release_task_lease(
    conn: sqlite3.Connection,
    task_id: int,
    claim_id: str,
    mark_status: Optional[str] = None,
) -> bool:
    """Releases an active lease, optionally updating status to 'done' or 'pending'."""
    cursor = conn.cursor()
    new_status_clause = ", status = ?" if mark_status else ""
    params = [mark_status, task_id, claim_id] if mark_status else [task_id, claim_id]

    cursor.execute(
        f"""
        UPDATE tasks
           SET claim_id = NULL,
               claimed_by = NULL,
               claim_expires_at = NULL,
               claim_heartbeat_at = NULL
               {new_status_clause}
         WHERE id = ?
           AND claim_id = ?
        """,
        params,
    )
    conn.commit()
    return cursor.rowcount > 0
