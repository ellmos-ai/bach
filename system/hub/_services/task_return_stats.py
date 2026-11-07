# SPDX-License-Identifier: MIT
"""BACH adapter for the task kernel's return accounting (``taskplan.return_policy``).

The kernel owns the rules (task-returns.v1): when a task flaps and when n
identical task-scoped returns block it. BACH only reads its lease releases from
``task_history`` and acts on the decision. Without the kernel the adapter says
``available: False`` and returns stay plain returns, as before PB-1 (#3985).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

RETURN_BLOCK_THRESHOLD = 5  # ponytail: fixed; make it a worker-policy setting if it needs tuning
_HISTORY_LIMIT = 200
_PROGRESS_OUTCOMES = frozenset({"review", "done", "completed"})
# Only causes that belong to the task may block it. Provider errors, stops and
# host preconditions (host_precondition:*) never do.
_TASK_SCOPED_PREFIXES = ("task_scope_unavailable", "model_failure:", "worker_returned_open")
# Model failures caused by the host (local reserve) or the provider are not the task's fault
# (#657 review: a 15-minute outage blocked intact tasks).
_HOST_SCOPED_MODEL_FAILURES = ("model_failure:local_reserve_", "model_failure:temporary_",
                               "model_failure:cloud_call_retry_exhausted")


def _policy():
    try:
        from taskplan import return_policy
    except ImportError:
        return None
    return return_policy


def _aware(raw):
    at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return at if at.tzinfo else at.astimezone()  # BACH writes local wall-clock time


def release_events(conn, task_id, limit=_HISTORY_LIMIT):
    """Lease releases of one task, oldest first, as kernel events."""
    rows = conn.execute(
        "SELECT new_value, changed_at FROM task_history WHERE task_id = ? AND action = 'lease_release' "
        "ORDER BY id DESC LIMIT ?", (task_id, limit)).fetchall()
    events = []
    for value, changed_at in reversed(rows):
        try:
            data = json.loads(value) if value else {}
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        events.append({"at": _aware(changed_at), "reason": str(data.get("note") or ""),
                       "progress": data.get("outcome") in _PROGRESS_OUTCOMES})
    return events


def summarize_task_returns(conn, task_id):
    """API fields return_count, last_return_reason, flapping (+ details) for one task."""
    policy = _policy()
    if policy is None:
        return {"available": False}
    summary = policy.summarize_returns(release_events(conn, task_id), now=datetime.now(timezone.utc))
    return {"available": True, "contract": policy.CONTRACT_VERSION, **summary}


def block_reason_for_next_return(client, task_id, note):
    """Fixed block reason if this return would be the n-th identical task-scoped one."""
    policy = _policy()
    if (policy is None or getattr(client, "mode", None) != "local"
            or not isinstance(note, str) or not note.startswith(_TASK_SCOPED_PREFIXES)
            or note.startswith(_HOST_SCOPED_MODEL_FAILURES)):
        return None
    conn = client._get_local_connection()
    try:
        events = release_events(conn, task_id, limit=RETURN_BLOCK_THRESHOLD)
    finally:
        if conn is not getattr(client, "_conn", None):
            conn.close()
    now = datetime.now(timezone.utc)
    summary = policy.summarize_returns([*events, {"at": now, "reason": note, "progress": False}], now=now)
    return policy.block_reason(summary, threshold=RETURN_BLOCK_THRESHOLD)
