"""Append-only, content-redacted trace for bound BACH worker tool calls.

Events share the canonical task database. A started row is committed before a
tool is entered; later rows are correlated to it and never imply external
effect or successful completion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import sqlite3

from hub._services import task_lease


SCHEMA = "bach.worker-tool-trace.v1"
SOURCES = frozenset({"normal-loop", "cli-relay"})
PHASES = frozenset({"started", "returned", "failed", "acknowledged"})
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[a-f0-9]{32}\Z")
_COMPLETION_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_GENERATION = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOOL = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_WORKER = re.compile(r"[A-Za-z0-9_.@-]{1,255}\Z")


class WorkerToolTraceError(Exception):
    """The trace could not safely accept or correlate an event."""


class TraceAuthorityError(WorkerToolTraceError):
    """The canonical live task lease does not authorize a new call."""


class TraceReplayError(WorkerToolTraceError):
    """A request id was already used or a call transition conflicts."""


class TraceCorrelationError(WorkerToolTraceError):
    """A terminal event has no matching durable start event."""


class TraceUnavailableError(WorkerToolTraceError):
    """The canonical trace table is unavailable for a read."""


@dataclass(frozen=True)
class TraceIdentity:
    """Safe call identity; deliberately excludes the private lease id."""

    task_id: int
    fence: int
    worker_id: str
    generation: str
    task_version: str
    request_id: str
    source: str
    tool_name: str


def digest_json(value) -> str:
    """Return a stable digest without retaining the serialized value."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WorkerToolTraceError("Werkzeugargumente können nicht sicher gehasht werden") from None
    return hashlib.sha256(encoded).hexdigest()


def digest_text(value) -> str:
    if not isinstance(value, str):
        raise WorkerToolTraceError("Werkzeugergebnis ist ungültig")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        raise WorkerToolTraceError("Werkzeugergebnis kann nicht sicher gehasht werden") from None
    return hashlib.sha256(encoded).hexdigest()


def ensure_worker_tool_trace_schema(conn: sqlite3.Connection) -> None:
    """Create the event table in the same database as canonical BACH tasks."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS worker_tool_trace_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema TEXT NOT NULL CHECK (schema = 'bach.worker-tool-trace.v1'),
            task_id INTEGER NOT NULL CHECK (task_id > 0),
            fence INTEGER NOT NULL CHECK (fence > 0),
            worker_id TEXT NOT NULL,
            generation TEXT NOT NULL,
            task_version TEXT NOT NULL,
            request_id TEXT NOT NULL,
            receipt_id TEXT,
            source TEXT NOT NULL CHECK (source IN ('normal-loop', 'cli-relay')),
            tool_name TEXT NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('started', 'returned', 'failed', 'acknowledged')),
            occurred_at TEXT NOT NULL,
            arguments_sha256 TEXT,
            result_sha256 TEXT,
            completion_sha256 TEXT,
            effect_status TEXT NOT NULL CHECK (effect_status = 'unknown'),
            CHECK (
                (phase = 'started' AND receipt_id IS NULL
                    AND arguments_sha256 IS NOT NULL AND result_sha256 IS NULL)
                OR (phase = 'returned' AND receipt_id IS NOT NULL
                    AND arguments_sha256 IS NULL AND result_sha256 IS NOT NULL)
                OR (phase = 'failed' AND receipt_id IS NULL
                    AND arguments_sha256 IS NULL AND result_sha256 IS NULL)
                OR (phase = 'acknowledged' AND receipt_id IS NOT NULL
                    AND arguments_sha256 IS NULL AND result_sha256 IS NULL)
            ),
            CHECK (
                (phase = 'started' AND completion_sha256 IS NOT NULL)
                OR (phase != 'started' AND completion_sha256 IS NULL)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_worker_tool_trace_phase
            ON worker_tool_trace_events(task_id, generation, request_id, source, phase);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_worker_tool_trace_returned_receipt
            ON worker_tool_trace_events(receipt_id)
            WHERE receipt_id IS NOT NULL AND phase = 'returned';
        DROP INDEX IF EXISTS ux_worker_tool_trace_receipt;
        CREATE INDEX IF NOT EXISTS ix_worker_tool_trace_task_event
            ON worker_tool_trace_events(task_id, event_id);
        CREATE TRIGGER IF NOT EXISTS worker_tool_trace_no_update
            BEFORE UPDATE ON worker_tool_trace_events
            BEGIN SELECT RAISE(ABORT, 'worker tool trace is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS worker_tool_trace_no_delete
            BEFORE DELETE ON worker_tool_trace_events
            BEGIN SELECT RAISE(ABORT, 'worker tool trace is append-only'); END;
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(worker_tool_trace_events)")}
    if "completion_sha256" not in columns:
        conn.execute("ALTER TABLE worker_tool_trace_events ADD COLUMN completion_sha256 TEXT")
    conn.commit()


def _validate_identity(identity: TraceIdentity) -> None:
    if (not isinstance(identity, TraceIdentity)
            or type(identity.task_id) is not int or identity.task_id <= 0
            or type(identity.fence) is not int or identity.fence <= 0
            or not isinstance(identity.worker_id, str) or not _WORKER.fullmatch(identity.worker_id)
            or not isinstance(identity.generation, str) or not _GENERATION.fullmatch(identity.generation)
            or not isinstance(identity.task_version, str) or not _HASH.fullmatch(identity.task_version)
            or not isinstance(identity.request_id, str) or not _ID.fullmatch(identity.request_id)
            or not isinstance(identity.source, str) or identity.source not in SOURCES
            or not isinstance(identity.tool_name, str) or not _TOOL.fullmatch(identity.tool_name)):
        raise WorkerToolTraceError("Ungültige Werkzeug-Trace-Bindung")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_dict(row):
    if row is None:
        return None
    return dict(row) if hasattr(row, "keys") else row


def _insert(conn, identity, phase, *, receipt_id=None, arguments_sha256=None,
            result_sha256=None, completion_sha256=None):
    cursor = conn.execute(
        """INSERT INTO worker_tool_trace_events
           (schema, task_id, fence, worker_id, generation, task_version, request_id,
            receipt_id, source, tool_name, phase, occurred_at, arguments_sha256,
            result_sha256, completion_sha256, effect_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown')""",
        (SCHEMA, identity.task_id, identity.fence, identity.worker_id, identity.generation,
         identity.task_version, identity.request_id, receipt_id, identity.source,
         identity.tool_name, phase, _timestamp(), arguments_sha256, result_sha256,
         completion_sha256),
    )
    return cursor.lastrowid


def _ack(event_id, identity, phase, *, completion_token=None):
    ack = {"schema": SCHEMA, "accepted": True, "event_id": event_id,
           "task_id": identity.task_id, "request_id": identity.request_id,
           "phase": phase}
    if completion_token is not None:
        ack["completion_token"] = completion_token
    return ack


def append_started(conn: sqlite3.Connection, identity: TraceIdentity, *,
                   lease_id: str, arguments_sha256: str) -> dict:
    """Verify the live native lease and durably append before tool dispatch."""
    _validate_identity(identity)
    if (not isinstance(lease_id, str) or not lease_id
            or not isinstance(arguments_sha256, str) or not _HASH.fullmatch(arguments_sha256)):
        raise WorkerToolTraceError("Werkzeugstart ist unvollständig")
    if conn.in_transaction:
        raise WorkerToolTraceError("Trace-Start benötigt eine eigene Transaktion")
    task_lease.ensure_task_lease_schema(conn)
    ensure_worker_tool_trace_schema(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        now = task_lease._utcnow()
        row, problem = task_lease._load_for_holder(
            conn, identity.task_id, lease_id, identity.fence, now,
            task_lease.LeaseConfig.from_env(), identity.task_version)
        if (problem or row.get("claimed_by") != identity.worker_id
                or row.get("claim_result_generation") != identity.generation
                or row.get("claim_task_version") != identity.task_version):
            raise TraceAuthorityError("Aktive Task-Lease bestätigt den Werkzeugstart nicht")
        duplicate = conn.execute(
            """SELECT 1 FROM worker_tool_trace_events
               WHERE task_id=? AND generation=? AND request_id=? AND source=?""",
            (identity.task_id, identity.generation, identity.request_id, identity.source),
        ).fetchone()
        if duplicate:
            raise TraceReplayError("Werkzeug-Request wurde bereits begonnen")
        completion_token = secrets.token_urlsafe(32)
        completion_sha256 = hashlib.sha256(completion_token.encode("ascii")).hexdigest()
        event_id = _insert(conn, identity, "started", arguments_sha256=arguments_sha256,
                           completion_sha256=completion_sha256)
        conn.commit()
        return _ack(event_id, identity, "started", completion_token=completion_token)
    except Exception:
        conn.rollback()
        raise


def append_phase(conn: sqlite3.Connection, identity: TraceIdentity, phase: str, *,
                 receipt_id: str | None = None, result_sha256: str | None = None,
                 completion_token: str | None = None) -> dict:
    """Append a return/failure/relay ACK only when its durable start exists."""
    _validate_identity(identity)
    if not isinstance(phase, str) or phase not in {"returned", "failed", "acknowledged"}:
        raise WorkerToolTraceError("Ungültige Werkzeug-Trace-Phase")
    if receipt_id is not None and (not isinstance(receipt_id, str) or not _ID.fullmatch(receipt_id)):
        raise WorkerToolTraceError("Ungültige Werkzeug-Receipt-ID")
    if result_sha256 is not None and (not isinstance(result_sha256, str) or not _HASH.fullmatch(result_sha256)):
        raise WorkerToolTraceError("Ungültiger Werkzeug-Ergebnisdigest")
    if not isinstance(completion_token, str) or not _COMPLETION_TOKEN.fullmatch(completion_token):
        raise WorkerToolTraceError("Werkzeug-Trace-Abschluss ist ungültig")
    if ((phase == "returned" and (receipt_id is None or result_sha256 is None))
            or (phase == "failed" and (receipt_id is not None or result_sha256 is not None))
            or (phase == "acknowledged" and (receipt_id is None or result_sha256 is not None))):
        raise WorkerToolTraceError("Werkzeug-Trace-Phase ist unvollständig")
    if conn.in_transaction:
        raise WorkerToolTraceError("Trace-Phase benötigt eine eigene Transaktion")
    ensure_worker_tool_trace_schema(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        start = _row_dict(conn.execute(
            """SELECT * FROM worker_tool_trace_events
               WHERE task_id=? AND generation=? AND request_id=?
                 AND source=? AND phase='started'""",
            (identity.task_id, identity.generation, identity.request_id, identity.source),
        ).fetchone())
        if start is None:
            raise TraceCorrelationError("Kein dauerhafter Werkzeugstart gefunden")
        if (start["fence"] != identity.fence
                or start["worker_id"] != identity.worker_id
                or start["task_version"] != identity.task_version
                or start["tool_name"] != identity.tool_name):
            raise TraceCorrelationError("Werkzeug-Trace-Bindung stimmt nicht überein")
        token_hash = hashlib.sha256(completion_token.encode("ascii")).hexdigest()
        if (not isinstance(start.get("completion_sha256"), str)
                or not hmac.compare_digest(start["completion_sha256"], token_hash)):
            raise TraceAuthorityError("Werkzeug-Trace-Abschluss ist nicht an den Start gebunden")
        prior = _row_dict(conn.execute(
            """SELECT * FROM worker_tool_trace_events
               WHERE task_id=? AND generation=? AND request_id=?
                 AND source=? AND phase=?""",
            (identity.task_id, identity.generation, identity.request_id,
             identity.source, phase),
        ).fetchone())
        if prior is not None:
            if (prior["fence"] == identity.fence
                    and prior["worker_id"] == identity.worker_id
                    and prior["task_version"] == identity.task_version
                    and prior["tool_name"] == identity.tool_name
                    and prior["receipt_id"] == receipt_id
                    and prior["result_sha256"] == result_sha256):
                conn.commit()
                return _ack(prior["event_id"], identity, phase)
            raise TraceReplayError("Widersprüchliches Werkzeug-Trace-Ereignis")
        returned = _row_dict(conn.execute(
            """SELECT * FROM worker_tool_trace_events
               WHERE task_id=? AND generation=? AND request_id=?
                 AND source=? AND phase='returned'""",
            (identity.task_id, identity.generation, identity.request_id, identity.source),
        ).fetchone())
        failed = _row_dict(conn.execute(
            """SELECT 1 FROM worker_tool_trace_events
               WHERE task_id=? AND generation=? AND request_id=?
                 AND source=? AND phase='failed'""",
            (identity.task_id, identity.generation, identity.request_id, identity.source),
        ).fetchone())
        if phase == "acknowledged":
            if returned is None or returned["fence"] != identity.fence or returned["receipt_id"] != receipt_id:
                raise TraceCorrelationError("Receipt ist keinem zurückgegebenen Toolcall zugeordnet")
        elif returned is not None or failed is not None:
            raise TraceReplayError("Werkzeug-Trace hat bereits einen Endzustand")
        event_id = _insert(conn, identity, phase, receipt_id=receipt_id,
                           result_sha256=result_sha256)
        conn.commit()
        return _ack(event_id, identity, phase)
    except Exception:
        conn.rollback()
        raise


def list_events(conn: sqlite3.Connection, task_id: int, *, limit=100, offset=0) -> dict:
    """Read a bounded event page without changing the database."""
    if (type(task_id) is not int or task_id <= 0 or type(limit) is not int
            or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 100_000):
        raise WorkerToolTraceError("Ungültige Werkzeug-Trace-Abfrage")
    present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_tool_trace_events'"
    ).fetchone()
    if not present:
        return {"schema": SCHEMA, "task_id": task_id, "events": [], "count": 0,
                "limit": limit, "offset": offset}
    rows = conn.execute(
        """SELECT event_id, schema, task_id, fence, worker_id, generation, task_version,
                  request_id, receipt_id, source, tool_name, phase, occurred_at,
                  arguments_sha256, result_sha256, effect_status
           FROM worker_tool_trace_events WHERE task_id=?
           ORDER BY event_id LIMIT ? OFFSET ?""",
        (task_id, limit, offset),
    ).fetchall()
    events = [_row_dict(row) for row in rows]
    return {"schema": SCHEMA, "task_id": task_id, "events": events,
            "count": len(events), "limit": limit, "offset": offset}
