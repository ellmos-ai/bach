"""Device-authenticated API for safe per-tool-call task trace events.

This router is deliberately separate from server.py so the shared server mount can
be reviewed and integrated by its current writer.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from hub.bach_paths import BACH_DB
from hub._services.chat.worker_tool_trace import (
    SCHEMA, TraceIdentity, TraceAuthorityError, TraceReplayError,
    WorkerToolTraceError, append_started, append_phase, list_events,
)

router = APIRouter(prefix="/api/tasks", tags=["worker-tool-trace"])
_MAX_BODY = 16_384


def _authorize(request: Request) -> None:
    from .unified_api import _require_memory_device
    _require_memory_device(request)


async def _authorized_json(request: Request) -> dict:
    """Authenticate before reading a small, non-secret event payload."""
    _authorize(request)
    if request.headers.get("transfer-encoding") is not None:
        raise HTTPException(400, "Trace-Auftrag ist ungültig")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > _MAX_BODY or int(length) < 0:
                raise HTTPException(413, "Trace-Auftrag ist zu groß")
        except ValueError:
            raise HTTPException(400, "Trace-Auftrag ist ungültig") from None
    chunks = []
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > _MAX_BODY:
                raise HTTPException(413, "Trace-Auftrag ist zu groß")
            chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
    except HTTPException:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise HTTPException(422, "Trace-Auftrag ist ungültig") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, "Trace-Auftrag ist ungültig")
    return payload


def _connection(*, read_only=False):
    try:
        path = Path(BACH_DB).resolve(strict=True)
        if not path.is_file():
            raise OSError
    except (OSError, RuntimeError):
        raise sqlite3.OperationalError("Kanonischer BACH-Speicher ist nicht verfügbar") from None
    mode = "ro" if read_only else "rw"
    conn = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    if read_only:
        conn.execute("PRAGMA query_only=ON")
    return conn


def _identity(task_id: int, payload: dict) -> TraceIdentity:
    return TraceIdentity(
        task_id=task_id, fence=payload["fence"], worker_id=payload["worker_id"],
        generation=payload["generation"], task_version=payload["task_version"],
        request_id=payload["request_id"], source=payload["source"],
        tool_name=payload["tool_name"],
    )


def _status(exc: Exception) -> HTTPException:
    if isinstance(exc, (TraceAuthorityError, TraceReplayError)):
        return HTTPException(409, "Trace-Ereignis ist nicht bestätigt")
    if isinstance(exc, WorkerToolTraceError):
        return HTTPException(422, "Trace-Ereignis ist ungültig")
    if isinstance(exc, sqlite3.Error):
        return HTTPException(503, "Kanonischer Trace-Speicher ist nicht verfügbar")
    return HTTPException(503, "Kanonischer Trace-Speicher ist nicht verfügbar")


@router.post("/{task_id}/tool-trace/start")
def start_tool_trace(
    request: Request,
    task_id: int,
    x_lease_id: str | None = Header(None, alias="X-Lease-Id"),
    payload: dict = Depends(_authorized_json),
):
    required = {"schema", "fence", "worker_id", "generation", "task_version",
                "request_id", "source", "tool_name", "arguments_sha256"}
    if (set(payload) != required or payload.get("schema") != SCHEMA
            or not isinstance(x_lease_id, str) or not x_lease_id):
        raise HTTPException(422, "Trace-Auftrag ist ungültig")
    try:
        identity = _identity(task_id, payload)
        with closing(_connection(read_only=False)) as conn:
            return append_started(conn, identity, lease_id=x_lease_id,
                                  arguments_sha256=payload["arguments_sha256"])
    except Exception as exc:
        raise _status(exc) from None


@router.post("/{task_id}/tool-trace/events")
def append_tool_trace_phase(
    request: Request,
    task_id: int,
    x_trace_completion: str | None = Header(None, alias="X-Trace-Completion"),
    payload: dict = Depends(_authorized_json),
):
    required = {"schema", "fence", "worker_id", "generation", "task_version",
                "request_id", "source", "tool_name", "phase", "receipt_id",
                "result_sha256"}
    if set(payload) != required or payload.get("schema") != SCHEMA:
        raise HTTPException(422, "Trace-Auftrag ist ungültig")
    try:
        identity = _identity(task_id, payload)
        with closing(_connection(read_only=False)) as conn:
            return append_phase(conn, identity, payload["phase"],
                                receipt_id=payload["receipt_id"],
                                result_sha256=payload["result_sha256"],
                                completion_token=x_trace_completion)
    except Exception as exc:
        raise _status(exc) from None


@router.get("/{task_id}/tool-trace/events")
def read_tool_trace_events(
    request: Request,
    task_id: int,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
):
    _authorize(request)
    try:
        with closing(_connection(read_only=True)) as conn:
            return list_events(conn, task_id, limit=limit, offset=offset)
    except Exception as exc:
        raise _status(exc) from None
