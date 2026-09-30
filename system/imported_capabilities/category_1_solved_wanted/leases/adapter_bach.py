# SPDX-License-Identifier: MIT
"""
Bach Adapter for Atomic Distributed Leases (from Roshambo).

Experimental SQLite adapter; not wired into runtime workers or federation.
Uses BACH task_audit's conditional UPDATE/status gate and Roshambo's exclusive,
expiring UUID lease contract. PostgreSQL support belongs to the copied original,
which needs its own dependencies; this adapter does not provide it.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


def _validate(conn, task_id, token, ttl=None):
    if conn.in_transaction:
        raise ValueError("Lease API requires a separate connection without an active transaction")
    if type(task_id) is not int or task_id <= 0:
        raise ValueError("task_id must be a positive integer")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("Owner/claim token must be a nonempty string")
    if ttl is not None and (type(ttl) is not int or not 0 < ttl <= 2147483647):
        raise ValueError("ttl_seconds must be a positive bounded integer")


def _uuid4(value):
    """The adapter issues canonical RFC 4122 UUIDv4 fences, never NIL UUIDs."""
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122 and str(parsed) == value


def _expiry(value):
    """Validate full calendar/time/offset before SQLite compares an instant.

    SQLite accepts Julian numbers, time-only strings and impossible dates.
    Legacy ISO timestamps with space/T, optional microseconds and valid UTC
    offset remain supported. Naive timestamps follow SQLite's UTC convention.
    """
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", value
    ):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        # fromisoformat normalizes overflowing offset minutes; validate them
        # separately instead of silently repairing persisted lease data.
        if re.search(r"[+-]\d{2}:\d{2}$", value) and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            return None
        parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        return parsed.isoformat(sep=" ", timespec="microseconds").removesuffix("+00:00")
    except (ValueError, OverflowError):
        return None


def _functions(conn):
    conn.create_function("bach_t797_expiry", 1, _expiry, deterministic=True)
    conn.create_function("bach_t797_uuid4", 1, _uuid4, deterministic=True)


def _commit_owned(conn):
    conn.commit()
    # In Python 3.12 autocommit=True the method deliberately does nothing,
    # even for our explicit BEGIN. Keep method-level failure semantics, then
    # close only the transaction that this adapter explicitly opened.
    if conn.in_transaction:
        conn.execute("COMMIT")


def _rollback_owned(conn):
    try:
        conn.rollback()
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")


def _owned_update(conn, statement, parameters, *, returning=False):
    """Rollback even RAISE(FAIL), which can retain the already updated row."""
    try:
        # Also own the transaction on autocommit connections: RAISE(FAIL)
        # otherwise commits partial UPDATE effects before rollback can help.
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(statement, parameters)
        result = cursor.fetchone() if returning else cursor.rowcount > 0
        _commit_owned(conn)
        return result
    except BaseException:
        _rollback_owned(conn)
        raise


@dataclass(frozen=True)
class TaskClaimResult:
    success: bool
    task_id: int
    claim_id: str | None
    claimed_by: str
    holder: str | None
    expires_at: str | None
    reason: str


def ensure_task_lease_schema(conn: sqlite3.Connection) -> None:
    """Ensures lease tracking columns exist on the tasks table in SQLite."""
    if conn.in_transaction:
        raise ValueError("Schema initialization cannot commit a caller transaction")
    # Serialize first-time DDL as well as claims: concurrent initializers must
    # inspect the schema AFTER obtaining the write lock.
    conn.execute("BEGIN IMMEDIATE")
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if not {"id", "status"} <= columns:
            raise ValueError("Existing tasks table with id/status is required")
        for column in ("claim_id", "claimed_by", "claim_expires_at", "claim_heartbeat_at", "claim_host"):
            if column not in columns:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")
        _commit_owned(conn)
    except BaseException:
        _rollback_owned(conn)
        raise


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
    2. A valid existing lease has expired on an eligible task.

    Terminal/blocked/unknown statuses and malformed/unbounded existing leases
    are denied. Same-owner acquisition is not renewal. This standalone API
    owns its commits and rejects active caller transactions. Initialize only
    disposable/explicitly authorized databases; no runtime caller is wired.
    """
    if ttl_seconds is None:
        raise ValueError("ttl_seconds must be a positive bounded integer")
    _validate(conn, task_id, agent_id, ttl_seconds)
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host must be a nonempty string")
    ensure_task_lease_schema(conn)
    _functions(conn)
    cursor = conn.cursor()
    claim_id = str(uuid.uuid4())

    # Single atomic UPDATE with conditional WHERE
    row = _owned_update(conn,
        """
        UPDATE tasks
           SET claim_id = ?,
               claimed_by = ?,
               claim_expires_at = datetime('now', '+' || ? || ' seconds'),
               claim_heartbeat_at = datetime('now'),
               claim_host = ?,
               status = 'in_progress'
         WHERE id = ?
           AND status IN ('pending', 'open', 'in_progress')
           AND (
               (status IN ('pending', 'open') AND claim_id IS NULL
                AND claimed_by IS NULL AND claim_expires_at IS NULL
                AND claim_heartbeat_at IS NULL AND claim_host IS NULL)
               OR (bach_t797_uuid4(claim_id) AND length(trim(claimed_by)) > 0
                   AND julianday(bach_t797_expiry(claim_expires_at)) < julianday('now'))
           )
         RETURNING claim_expires_at
        """,
        (claim_id, agent_id, ttl_seconds, host, task_id),
        returning=True,
    )

    if row is not None:
        expires = row[0]
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
    if ttl_seconds is None:
        raise ValueError("ttl_seconds must be a positive bounded integer")
    _validate(conn, task_id, claim_id, ttl_seconds)
    if not _uuid4(claim_id):
        raise ValueError("claim_id must be a canonical RFC 4122 UUIDv4")
    _functions(conn)
    return _owned_update(conn,
        """
        UPDATE tasks
           SET claim_heartbeat_at = datetime('now'),
               claim_expires_at = datetime('now', '+' || ? || ' seconds')
         WHERE id = ?
           AND claim_id = ?
           AND status = 'in_progress'
           AND length(trim(claimed_by)) > 0
           AND julianday('now') < julianday(bach_t797_expiry(claim_expires_at))
        """,
        (ttl_seconds, task_id, claim_id),
    )


def release_task_lease(
    conn: sqlite3.Connection,
    task_id: int,
    claim_id: str,
    mark_status: str | None = None,
) -> bool:
    """Release a live fenced lease; default pending permits a later claim."""
    _validate(conn, task_id, claim_id)
    if not _uuid4(claim_id):
        raise ValueError("claim_id must be a canonical RFC 4122 UUIDv4")
    status = "pending" if mark_status is None else mark_status
    if status not in {"pending", "open", "done", "completed", "cancelled", "blocked"}:
        raise ValueError("Unsupported release status")
    _functions(conn)
    params = [status, task_id, claim_id]

    return _owned_update(conn,
        """
        UPDATE tasks
           SET claim_id = NULL,
               claimed_by = NULL,
               claim_expires_at = NULL,
               claim_heartbeat_at = NULL,
               claim_host = NULL,
               status = ?
         WHERE id = ?
           AND claim_id = ?
           AND status = 'in_progress'
           AND length(trim(claimed_by)) > 0
           AND julianday('now') < julianday(bach_t797_expiry(claim_expires_at))
        """,
        params,
    )
