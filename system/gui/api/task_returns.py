"""Read-only task return accounting for the GUI (PB-1 #3985, display in PB-4).

Fields come from the task kernel (taskplan.return_policy, task-returns.v1):
return_count, last_return_reason, last_return_at, consecutive_identical,
flapping, host_scoped. Without the kernel every entry reads available=false.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["task-returns"])
_MAX_IDS = 200


def _connection():
    from hub import bach_paths
    try:
        path = bach_paths.BACH_DB.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(503, "Taskdatenbank nicht lesbar") from exc
    return closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2))


def _summaries(task_ids):
    from hub._services.task_return_stats import summarize_task_returns
    with _connection() as conn:
        return {str(tid): summarize_task_returns(conn, tid) for tid in task_ids}


@router.get("/api/tasks/{task_id}/returns")
async def task_returns(task_id: int):
    if task_id <= 0:
        raise HTTPException(400, "task_id ist ungültig")
    return {"task_id": task_id, **_summaries([task_id])[str(task_id)]}


@router.get("/api/task-returns")
async def task_returns_batch(ids: str = Query(..., description="Komma-getrennte Task-IDs")):
    try:
        task_ids = sorted({int(part) for part in ids.split(",") if part.strip()})
    except ValueError as exc:
        raise HTTPException(400, "ids muss eine Liste von Ganzzahlen sein") from exc
    if not task_ids or len(task_ids) > _MAX_IDS or task_ids[0] <= 0:
        raise HTTPException(400, f"1 bis {_MAX_IDS} positive Task-IDs angeben")
    return {"tasks": _summaries(task_ids)}


# A return is a lease release that did not deliver a result (same rule as the kernel summary).
_RETURNS = ("h.action = 'lease_release' AND h.changed_at >= ? AND json_valid(h.new_value) "
            "AND COALESCE(json_extract(h.new_value, '$.outcome'), '') NOT IN ('review', 'done', 'completed')")


@router.get("/api/task-returns/timeline")
async def task_returns_timeline(hours: int = Query(24, ge=1, le=720), limit: int = Query(200, ge=1, le=500),
                                task_id: int | None = Query(None, ge=1)):
    """Returns of all tasks in the last ``hours``, newest first (PB-4: make loops visible)."""
    where, args = _RETURNS, [(datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%f")]
    if task_id is not None:
        where, args = where + " AND h.task_id = ?", [*args, task_id]
    with _connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM task_history h WHERE {where}", args).fetchone()[0]
        by_reason = dict(conn.execute(
            f"SELECT COALESCE(json_extract(h.new_value, '$.note'), ''), COUNT(*) AS n FROM task_history h "
            f"WHERE {where} GROUP BY 1 ORDER BY n DESC LIMIT 20", args).fetchall())
        rows = conn.execute(
            "SELECT h.task_id, t.title, h.changed_at, h.changed_by, json_extract(h.new_value, '$.note'), "
            "json_extract(h.new_value, '$.outcome') FROM task_history h LEFT JOIN tasks t ON t.id = h.task_id "
            f"WHERE {where} ORDER BY h.id DESC LIMIT ?", [*args, limit]).fetchall()
    events = [{"task_id": r[0], "task_title": r[1] or "", "at": r[2], "worker": r[3] or "",
               "reason": r[4] or "", "outcome": r[5] or ""} for r in rows]
    return {"schema": "bach.task-return-timeline.v1", "hours": hours, "total": total, "truncated": total > len(events),
            "by_reason": by_reason, "events": events}
