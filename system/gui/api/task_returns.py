"""Read-only task return accounting for the GUI (PB-1 #3985, display in PB-4).

Fields come from the task kernel (taskplan.return_policy, task-returns.v1):
return_count, last_return_reason, last_return_at, consecutive_identical,
flapping, host_scoped. Without the kernel every entry reads available=false.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing

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
