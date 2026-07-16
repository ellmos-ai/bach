# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Bridge between BACH's legacy task table and the taskplan module.

The bridge is intentionally additive: it can mirror selected BACH tasks into a
taskplan database without changing or deleting rows in BACH's own ``tasks``
table. This keeps the GUI/API surfaces stable while taskplan adoption is gated.
"""

from __future__ import annotations

import importlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


TASKPLAN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rinnsal_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'medium',
    agent_id TEXT NOT NULL DEFAULT 'default',
    tags TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    done_at TEXT,
    project_path TEXT DEFAULT '',
    root_id TEXT DEFAULT '',
    effort TEXT DEFAULT '',
    scope TEXT DEFAULT 'local',
    source TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    assigned_to TEXT DEFAULT '',
    delegation_status TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON rinnsal_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON rinnsal_tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON rinnsal_tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_effort ON rinnsal_tasks(effort);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON rinnsal_tasks(project_path);
CREATE INDEX IF NOT EXISTS idx_tasks_root ON rinnsal_tasks(root_id);
"""

TASKPLAN_SELECT_COLUMNS = (
    "id, title, description, status, priority, agent_id, tags, "
    "created_at, updated_at, done_at, "
    "project_path, root_id, effort, scope, source, "
    "created_by, assigned_to, delegation_status"
)

VALID_TASKPLAN_PRIORITIES = ("critical", "high", "medium", "low")
VALID_TASKPLAN_STATUSES = ("open", "active", "done", "cancelled")

BACH_PRIORITY_TO_TASKPLAN = {
    "P1": "critical",
    "P2": "high",
    "HIGH": "high",
    "P3": "medium",
    "MEDIUM": "medium",
    "P4": "low",
    "LOW": "low",
}

BACH_STATUS_TO_TASKPLAN = {
    "pending": "open",
    "open": "open",
    "in_progress": "active",
    "in-progress": "active",
    "done": "done",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


class BundledTaskPlanClient:
    """Small taskplan-compatible fallback used when the package is absent."""

    def __init__(self, db_path: str | Path | None = None, agent_id: str = "bach"):
        if db_path is None:
            db_path = bundled_default_db_path()
        self.db_path = Path(db_path).expanduser()
        self.agent_id = agent_id
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(TASKPLAN_SCHEMA_SQL)
            conn.commit()

    def add(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        tags: str = "",
        effort: str = "",
        scope: str = "local",
        project_path: str = "",
        root_id: str = "",
        source: str = "",
    ) -> dict[str, Any]:
        if priority not in VALID_TASKPLAN_PRIORITIES:
            raise ValueError(f"priority muss einer von {VALID_TASKPLAN_PRIORITIES} sein")
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rinnsal_tasks
                    (title, description, status, priority, agent_id, tags,
                     created_at, updated_at, project_path, root_id, effort,
                     scope, source, created_by)
                VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    description,
                    priority,
                    self.agent_id,
                    tags,
                    now,
                    now,
                    project_path,
                    root_id,
                    effort,
                    scope,
                    source,
                    self.agent_id,
                ),
            )
            conn.commit()
            return self.get(cursor.lastrowid) or {"id": cursor.lastrowid, "title": title}

    def list(
        self,
        status: str | None = None,
        priority: str | None = None,
        include_done: bool = False,
        limit: int = 50,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        elif not include_done:
            conditions.append("status NOT IN ('done', 'cancelled')")
        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        for column in ("effort", "scope", "project_path", "root_id", "assigned_to"):
            value = filters.get(column)
            if value is not None:
                conditions.append(f"{column} = ?")
                params.append(value)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        with self._get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT {TASKPLAN_SELECT_COLUMNS}
                FROM rinnsal_tasks
                {where}
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5
                    END,
                    created_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [row_to_taskplan_dict(row) for row in rows]

    def get(self, task_id: int) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                f"SELECT {TASKPLAN_SELECT_COLUMNS} FROM rinnsal_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            return row_to_taskplan_dict(row) if row else None

    def assign(self, task_id: int, to: str, status: str = "assigned") -> bool:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE rinnsal_tasks
                SET assigned_to = ?, delegation_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (to, status, now, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def done(self, task_id: int) -> bool:
        return self._set_status(task_id, "done")

    def activate(self, task_id: int) -> bool:
        return self._set_status(task_id, "active")

    def cancel(self, task_id: int) -> bool:
        return self._set_status(task_id, "cancelled")

    def reopen(self, task_id: int) -> bool:
        return self._set_status(task_id, "open")

    def count(self) -> dict[str, int]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM rinnsal_tasks GROUP BY status"
            ).fetchall()
            result = {status: 0 for status in VALID_TASKPLAN_STATUSES}
            for status, count in rows:
                result[status] = count
            result["total"] = sum(result.values())
            return result

    def _set_status(self, task_id: int, status: str) -> bool:
        now = datetime.now().isoformat()
        done_at = now if status == "done" else None
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE rinnsal_tasks
                SET status = ?, updated_at = ?, done_at = ?
                WHERE id = ?
                """,
                (status, now, done_at, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0


def row_to_taskplan_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row[0],
        "title": row[1],
        "description": row[2],
        "status": row[3],
        "priority": row[4],
        "agent_id": row[5],
        "tags": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "done_at": row[9],
        "project_path": row[10],
        "root_id": row[11],
        "effort": row[12],
        "scope": row[13],
        "source": row[14],
        "created_by": row[15],
        "assigned_to": row[16],
        "delegation_status": row[17],
    }


def bundled_default_db_path() -> str:
    return str(Path.home() / ".taskplan" / "taskplan.db")


def _count_tasks_in(db_path: str | Path) -> int | None:
    path = Path(db_path).expanduser()
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
    except OSError:
        return None
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute("SELECT COUNT(*) FROM rinnsal_tasks").fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def load_taskplan_backend() -> dict[str, Any]:
    """Return the external taskplan backend or the bundled fallback."""
    try:
        client_module = importlib.import_module("taskplan.client")
        return {
            "engine": "taskplan",
            "external_available": True,
            "module_file": getattr(client_module, "__file__", ""),
            "client_cls": getattr(client_module, "TaskClient"),
            "default_db_path": getattr(client_module, "get_default_db_path"),
            "count_tasks_in": getattr(client_module, "count_tasks_in", _count_tasks_in),
        }
    except Exception:
        return {
            "engine": "bundled",
            "external_available": False,
            "module_file": __file__,
            "client_cls": BundledTaskPlanClient,
            "default_db_path": bundled_default_db_path,
            "count_tasks_in": _count_tasks_in,
        }


def resolve_taskplan_db(db_path: str | Path | None = None) -> Path:
    """Resolve the DB used by BACH's taskplan bridge.

    ``BACH_TASKPLAN_DB`` is a BACH-specific override for tests and staged
    migrations. Without it, the external taskplan configuration remains the
    authority.
    """
    if db_path:
        return Path(db_path).expanduser()
    override = os.environ.get("BACH_TASKPLAN_DB", "")
    if override:
        return Path(override).expanduser()
    backend = load_taskplan_backend()
    return Path(backend["default_db_path"]()).expanduser()


def taskplan_write_policy() -> dict[str, Any]:
    """Describe the current write contract between BACH tasks and taskplan.

    The bridge is still intentionally additive. This status block gives CLI,
    API, GUI, and automation callers a stable place to detect that BACH writes
    are not yet mirrored automatically while the cutover decision is open.
    """
    requested_mode = os.environ.get("BACH_TASKPLAN_WRITE_MODE", "").strip().lower()
    return {
        "effective_mode": "legacy_only",
        "requested_mode": requested_mode or None,
        "feature_flag": "BACH_TASKPLAN_WRITE_MODE",
        "automatic_write_mirror": False,
        "legacy_tasks_table": "authoritative",
        "taskplan_role": "manual_mirror_import_only",
        "implemented_write_operations": [],
        "gated_write_operations": ["add", "edit", "done", "reopen"],
        "decision_required": (
            "TASKPLAN #300 source-of-truth and conflict rules before "
            "BACH #1175 write adapter"
        ),
        "fallback": "BACH legacy tasks table remains unchanged",
    }


def get_taskplan_client(
    db_path: str | Path | None = None,
    agent_id: str = "bach",
) -> Any:
    backend = load_taskplan_backend()
    return backend["client_cls"](db_path=resolve_taskplan_db(db_path), agent_id=agent_id)


def taskplan_status(db_path: str | Path | None = None) -> dict[str, Any]:
    backend = load_taskplan_backend()
    resolved_db = resolve_taskplan_db(db_path)
    count = backend["count_tasks_in"](resolved_db)
    return {
        "engine": backend["engine"],
        "external_available": backend["external_available"],
        "module_file": backend["module_file"],
        "db_path": str(resolved_db),
        "task_count": count,
        "write_policy": taskplan_write_policy(),
    }


def taskplan_priority_from_bach(priority: str | None) -> str:
    return BACH_PRIORITY_TO_TASKPLAN.get(str(priority or "").upper(), "medium")


def taskplan_status_from_bach(status: str | None) -> str:
    return BACH_STATUS_TO_TASKPLAN.get(str(status or "").lower(), "open")


def _tag_value(task_id: int | str) -> str:
    return f"bach-task:{int(task_id)}"


def find_taskplan_mirror(client: Any, bach_task_id: int) -> dict[str, Any] | None:
    """Find an existing taskplan row previously mirrored from a BACH task."""
    db_path = Path(client.db_path).expanduser()
    if not db_path.exists():
        return None
    tag = f"%{_tag_value(bach_task_id)}%"
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT {TASKPLAN_SELECT_COLUMNS}
                FROM rinnsal_tasks
                WHERE tags LIKE ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (tag,),
            ).fetchone()
            return row_to_taskplan_dict(row) if row else None
    except sqlite3.Error:
        return None


def _sync_existing_status(
    client: Any,
    existing: dict[str, Any],
    target_status: str,
) -> tuple[str, dict[str, Any]]:
    task_id = int(existing["id"])
    if existing.get("status") == target_status:
        return "existing", existing

    if target_status == "active":
        changed = client.activate(task_id)
    elif target_status == "done":
        changed = client.done(task_id)
    elif target_status == "cancelled":
        changed = client.cancel(task_id)
    else:
        changed = client.reopen(task_id)

    refreshed = client.get(task_id) or existing
    return ("updated" if changed else "existing"), refreshed


def mirror_bach_task(
    bach_task: dict[str, Any] | sqlite3.Row,
    *,
    db_path: str | Path | None = None,
    agent_id: str = "bach",
    project_path: str | Path | None = None,
) -> dict[str, Any]:
    """Mirror one BACH task into taskplan, idempotently."""
    task = dict(bach_task)
    bach_id = int(task["id"])
    client = get_taskplan_client(db_path=db_path, agent_id=agent_id)
    existing = find_taskplan_mirror(client, bach_id)
    status = str(task.get("status") or "")
    target_status = taskplan_status_from_bach(status)
    if existing:
        action, synced = _sync_existing_status(client, existing, target_status)
        return {"action": action, "task": synced, "bach_task_id": bach_id}

    category = str(task.get("category") or "general")
    tags = ";".join(
        value
        for value in (
            _tag_value(bach_id),
            f"bach-status:{status or 'unknown'}",
            f"bach-category:{category}",
        )
        if value
    )
    description = str(task.get("description") or "")
    if status and status not in ("pending", "open"):
        status_note = f"[BACH status: {status}]"
        description = f"{status_note}\n\n{description}".strip()

    created = client.add(
        str(task.get("title") or f"BACH Task {bach_id}"),
        description=description,
        priority=taskplan_priority_from_bach(task.get("priority")),
        tags=tags,
        effort="",
        scope="central",
        project_path=str(project_path or ""),
        root_id="BACH",
        source="bach.db:tasks",
    )
    if target_status == "active":
        client.activate(int(created["id"]))
        created = client.get(int(created["id"])) or created
    elif target_status == "done":
        client.done(int(created["id"]))
        created = client.get(int(created["id"])) or created
    elif target_status == "cancelled":
        client.cancel(int(created["id"]))
        created = client.get(int(created["id"])) or created
    return {"action": "created", "task": created, "bach_task_id": bach_id}


def mirror_bach_tasks(
    bach_tasks: Iterable[dict[str, Any] | sqlite3.Row],
    *,
    db_path: str | Path | None = None,
    agent_id: str = "bach",
    project_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    return [
        mirror_bach_task(
            task,
            db_path=db_path,
            agent_id=agent_id,
            project_path=project_path,
        )
        for task in bach_tasks
    ]
