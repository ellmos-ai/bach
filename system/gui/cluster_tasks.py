# SPDX-License-Identifier: MIT
"""Cluster-Task-Client mit lokalem SQLite-Fallback.

Dieses Modul kapselt alle CRUD-Operationen fuer Tasks im Web-Dashboard.
Sobald `settings.cluster.is_online` wahr ist und die entfernte BACH-Node
antwortet, werden die Operationen gegen die Cluster-API gespielt. Bei
Fehlen oder Nichterreichbarkeit des Clusters wird transparent auf die
lokale `bach.db` zurueckgefallen.

Die lokalen Fallback-Funktionen spiegeln die Logik aus `gui/server.py`
weitgehend eins zu eins wider, damit sich das GUI-Verhalten unabhaengig
davon bleibt, ob gerade ein Cluster-Knoten verfuegbar ist.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any

import httpx

from gui import config
from gui.task_db import (
    DEFAULT_TASK_ASSIGNEE,
    create_cluster_node,
    delete_cluster_node,
    get_bach_db,
    get_cluster_node,
    list_cluster_nodes,
    row_to_dict,
    rows_to_list,
    update_cluster_node,
)

logger = logging.getLogger(__name__)


def _get_db() -> sqlite3.Connection:
    """Liefert eine SQLite-Verbindung mit Row-Factory."""
    conn = get_bach_db()
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


# ═══════════════════════════════════════════════════════════════
# Lokale Fallback-Funktionen
# ═══════════════════════════════════════════════════════════════


def _local_list_tasks(
    status: str = "all",
    project: str | None = None,
    category: str | None = None,
    assigned_to: str | None = None,
    priority: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Lokale Variante von GET /api/tasks."""
    conn = _get_db()
    try:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list[Any] = []

        if status and status.lower() != "all":
            STATUS_ALIASES = {
                "in_progress": ["in_progress", "progress"],
                "pending": ["pending", "open"],
                "done": ["done", "completed", "closed"],
                "blocked": ["blocked"],
                "cancelled": ["cancelled", "canceled"],
                "duplicate": ["duplicate"],
            }
            requested = [s.strip().lower() for s in status.split(",") if s.strip()]
            normalized: set[str] = set()
            for s in requested:
                matched = False
                for canonical, aliases in STATUS_ALIASES.items():
                    if s in aliases:
                        normalized.update(aliases)
                        matched = True
                        break
                if not matched:
                    normalized.add(s)
            if normalized:
                placeholders = ",".join(["?"] * len(normalized))
                query += f" AND (LOWER(status) IN ({placeholders}))"
                params.extend(sorted(normalized))

        target_cat = category or project
        if target_cat:
            query += " AND UPPER(category) = UPPER(?)"
            params.append(target_cat)

        if assigned_to:
            query += " AND UPPER(assigned_to) = UPPER(?)"
            params.append(assigned_to)

        if priority:
            prio_clean = priority.strip().upper()
            if prio_clean in ("P1", "1", "HIGH", "HOCH", "KRITISCH"):
                query += (
                    " AND (UPPER(priority) IN ('P1', '1', 'HIGH', 'HOCH', 'KRITISCH') OR priority IS NULL)"
                )
            elif prio_clean in ("P2", "2", "MEDIUM", "MITTEL", "WICHTIG"):
                query += " AND (UPPER(priority) IN ('P2', '2', 'MEDIUM', 'MITTEL', 'WICHTIG'))"
            elif prio_clean in ("P3", "3", "LOW", "NIEDRIG", "NORMAL"):
                query += " AND (UPPER(priority) IN ('P3', '3', 'LOW', 'NIEDRIG', 'NORMAL'))"
            elif prio_clean in ("P4", "4", "MINIMAL"):
                query += " AND (UPPER(priority) IN ('P4', '4', 'MINIMAL'))"
            else:
                query += " AND UPPER(priority) = UPPER(?)"
                params.append(priority)

        query += (
            " ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 "
            "WHEN 'P3' THEN 3 WHEN 'P4' THEN 4 ELSE 5 END ASC, created_at DESC LIMIT ?"
        )
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        tasks = _rows_to_list(rows)

        for task in tasks:
            if task.get("image_data"):
                task["has_image"] = True
            task.pop("image_data", None)

            if task.get("depends_on"):
                try:
                    dep_ids = [int(x.strip()) for x in str(task["depends_on"]).split(",") if x.strip()]
                    if dep_ids:
                        placeholders = ",".join(["?"] * len(dep_ids))
                        unfinished = conn.execute(
                            f"SELECT COUNT(*) FROM tasks WHERE id IN ({placeholders}) AND status != 'done'",
                            dep_ids,
                        ).fetchone()[0]
                        if unfinished > 0:
                            task["is_blocked_by_dep"] = True
                except (sqlite3.OperationalError, sqlite3.DatabaseError, ValueError, AttributeError):
                    pass

        return {"success": True, "tasks": tasks, "count": len(tasks)}
    finally:
        conn.close()


def _local_create_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Lokale Variante von POST /api/tasks."""
    conn = _get_db()
    try:
        from hub._services.task_schema import ensure_task_slot_columns

        ensure_task_slot_columns(conn)

        draft_source = payload.get("source") or payload.get("draft_hash")
        if draft_source:
            existing = conn.execute(
                "SELECT * FROM tasks WHERE source = ?", (draft_source,)
            ).fetchone()
            if existing:
                return {"success": True, "task": dict(existing), "status": "already_present"}

        now = datetime.now().isoformat()
        cursor = conn.execute(
            """
            INSERT INTO tasks (title, description, priority, category, status, created_at,
                               created_by, assigned_to, depends_on, image_data, due_date, source,
                               required_model, assigned_slot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("title"),
                payload.get("description", ""),
                payload.get("priority", "P3"),
                payload.get("category", "general"),
                payload.get("status", "pending"),
                now,
                payload.get("created_by", "user"),
                payload.get("assigned_to") or DEFAULT_TASK_ASSIGNEE,
                payload.get("depends_on"),
                payload.get("image"),
                payload.get("due_date"),
                draft_source,
                payload.get("required_model") or None,
                payload.get("assigned_slot") or None,
            ),
        )
        conn.commit()
        task_id = cursor.lastrowid
        task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return {"success": True, "task": dict(task_row)}
    finally:
        conn.close()


def _local_update_task(task_id: int, update: dict[str, Any]) -> dict[str, Any]:
    """Lokale Variante von PUT /api/tasks/{task_id}.

    Benutzt `apply_task_field_changes` und `claim_task_atomic` aus
    `hub.task_audit`, um exakt das gleiche Verhalten wie `gui.server.py`
    zu erreichen (Claim-Logik, Historie, Gate-Reopen-Guard).
    """
    from hub.task_audit import apply_task_field_changes, claim_task_atomic, GateReopenBlocked

    conn = _get_db()
    try:
        from hub._services.task_schema import ensure_task_slot_columns

        fields_set = set(update.keys())
        if "required_model" in fields_set or "assigned_slot" in fields_set:
            ensure_task_slot_columns(conn)

        existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            return {"success": False, "error": "Task nicht gefunden", "status_code": 404}
        existing_row = _row_to_dict(existing)

        changed_by = update.get("changed_by") or "api"

        is_new_claim = (
            update.get("status") == "in_progress"
            and not (
                existing_row.get("status") == "in_progress"
                and existing_row.get("claimed_by") == changed_by
            )
        )

        did_update = False
        if is_new_claim:
            if not claim_task_atomic(conn, task_id, changed_by):
                return {"status": "claim_failed", "success": False}
            did_update = True

        field_values: dict[str, Any] = {}
        if update.get("title") is not None:
            field_values["title"] = update["title"]
        if update.get("description") is not None:
            field_values["description"] = update["description"]
        if update.get("priority") is not None:
            field_values["priority"] = update["priority"]
        if update.get("status") is not None and not is_new_claim:
            field_values["status"] = update["status"]
        if update.get("project") is not None:
            field_values["category"] = update["project"]
        if update.get("assigned_to") is not None:
            field_values["assigned_to"] = update["assigned_to"]
        if update.get("created_by") is not None:
            field_values["created_by"] = update["created_by"]
        if update.get("depends_on") is not None:
            field_values["depends_on"] = update["depends_on"]
        if "required_model" in fields_set:
            field_values["required_model"] = update.get("required_model") or None
        if "assigned_slot" in fields_set:
            field_values["assigned_slot"] = update.get("assigned_slot") or None

        try:
            if apply_task_field_changes(
                conn,
                task_id,
                existing_row,
                field_values,
                changed_by=changed_by,
                allow_reopen=bool(update.get("allow_reopen")),
            ):
                did_update = True
        except GateReopenBlocked as exc:
            return {"success": False, "error": str(exc), "status_code": 409}

        if did_update:
            conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return {"success": True, "task": dict(row)}
    finally:
        conn.close()


def _local_delete_task(task_id: int) -> dict[str, Any]:
    """Lokale Variante von DELETE /api/tasks/{task_id}."""
    conn = _get_db()
    try:
        existing = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            return {"success": False, "error": "Task nicht gefunden", "status_code": 404}
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def _local_get_task(task_id: int) -> dict[str, Any]:
    """Lokale Variante von GET /api/tasks/{task_id}."""
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return {"success": False, "error": "Task nicht gefunden", "status_code": 404}
        task = _row_to_dict(row)
        if task.get("image_data"):
            task["has_image"] = True
        task.pop("image_data", None)
        return {"success": True, "task": task}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# Lokale Fallback-Funktionen fuer Cluster-Nodes
# ═══════════════════════════════════════════════════════════════


def _local_list_nodes() -> dict[str, Any]:
    """Lokale Variante von GET /api/cluster/nodes."""
    conn = _get_db()
    try:
        return list_cluster_nodes(conn)
    finally:
        conn.close()


def _local_register_node(payload: dict[str, Any]) -> dict[str, Any]:
    """Lokale Variante von POST /api/cluster/nodes."""
    conn = _get_db()
    try:
        return create_cluster_node(
            conn,
            name=payload["name"],
            url=payload["url"],
            token=payload.get("token"),
            role=payload.get("role", "worker"),
            status=payload.get("status", "offline"),
            capabilities=payload.get("capabilities"),
        )
    finally:
        conn.close()


def _local_get_node(node_id: int) -> dict[str, Any]:
    """Lokale Variante von GET /api/cluster/nodes/{node_id}."""
    conn = _get_db()
    try:
        return get_cluster_node(conn, node_id)
    finally:
        conn.close()


def _local_update_node(node_id: int, update: dict[str, Any]) -> dict[str, Any]:
    """Lokale Variante von PUT /api/cluster/nodes/{node_id}."""
    conn = _get_db()
    try:
        return update_cluster_node(conn, node_id, update)
    finally:
        conn.close()


def _local_delete_node(node_id: int) -> dict[str, Any]:
    """Lokale Variante von DELETE /api/cluster/nodes/{node_id}."""
    conn = _get_db()
    try:
        return delete_cluster_node(conn, node_id)
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# Cluster-Task-Client
# ═══════════════════════════════════════════════════════════════


class ClusterTaskClient:
    """HTTP-Client fuer Cluster-Task-Operationen mit lokalem Fallback.

    Alle CRUD-Methoden versuchen zuerst den konfigurierten Cluster-Knoten.
    Ist `settings.cluster.is_online` False oder schlaegt die Remote-Anfrage
    fehl, wird automatisch die lokale SQLite-Implementierung verwendet.
    """

    def __init__(self) -> None:
        self.settings = config.settings.cluster
        self.session: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self.session is None:
            self.session = httpx.AsyncClient(
                timeout=self.settings.timeout,
                headers={"Authorization": f"Bearer {self.settings.token}"},
            )
        return self.session

    def _base_url(self) -> str:
        return f"{self.settings.url}/api/tasks"

    def _should_use_local(self) -> bool:
        if not self.settings.is_online:
            return True
        if not self.settings.url or not self.settings.has_credentials:
            return True
        return False

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fuehert eine Remote-Anfrage mit Retry-Logik aus.

        Bei Netzwerk-/HTTP-Fehlern oder leerem Cluster-URL wird ein
        `ClusterUnavailable`-Signal (Exception) geworfen, damit die
        aufrufende Methode lokal fallbacken kann.
        """
        if self._should_use_local():
            raise ClusterUnavailable("Cluster offline oder nicht konfiguriert")

        client = await self._client()
        url = f"{self.settings.url}{path}"
        last_exc: Exception | None = None

        for attempt in range(max(1, self.settings.retries)):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    timeout=self.settings.timeout,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning("Cluster-Anfrage fehlgeschlagen (Versuch %d/%d): %s", attempt + 1, self.settings.retries, exc)
                continue

        raise ClusterUnavailable(f"Cluster nach {self.settings.retries} Versuchen nicht erreichbar: {last_exc}")

    async def list_tasks(
        self,
        status: str = "all",
        project: str | None = None,
        category: str | None = None,
        assigned_to: str | None = None,
        priority: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"status": status, "limit": limit}
        if project is not None:
            params["project"] = project
        if category is not None:
            params["category"] = category
        if assigned_to is not None:
            params["assigned_to"] = assigned_to
        if priority is not None:
            params["priority"] = priority

        try:
            return await self._request("GET", "/api/tasks", params=params)
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Task-Liste")
            return _local_list_tasks(
                status=status,
                project=project,
                category=category,
                assigned_to=assigned_to,
                priority=priority,
                limit=limit,
            )

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._request("POST", "/api/tasks", json=payload)
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Task-Erstellung")
            return _local_create_task(payload)

    async def update_task(self, task_id: int, update: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._request("PUT", f"/api/tasks/{task_id}", json=update)
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Task-Aktualisierung")
            return _local_update_task(task_id, update)

    async def delete_task(self, task_id: int) -> dict[str, Any]:
        try:
            return await self._request("DELETE", f"/api/tasks/{task_id}")
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Task-Loeschung")
            return _local_delete_task(task_id)

    async def get_task(self, task_id: int) -> dict[str, Any]:
        try:
            return await self._request("GET", f"/api/tasks/{task_id}")
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Task-Abfrage")
            return _local_get_task(task_id)

    async def list_nodes(self) -> dict[str, Any]:
        try:
            return await self._request("GET", "/api/cluster/nodes")
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Cluster-Node-Liste")
            return _local_list_nodes()

    async def register_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._request("POST", "/api/cluster/nodes", json=payload)
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Cluster-Node-Registrierung")
            return _local_register_node(payload)

    async def get_node(self, node_id: int) -> dict[str, Any]:
        try:
            return await self._request("GET", f"/api/cluster/nodes/{node_id}")
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Cluster-Node-Abfrage")
            return _local_get_node(node_id)

    async def update_node(self, node_id: int, update: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._request("PUT", f"/api/cluster/nodes/{node_id}", json=update)
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Cluster-Node-Aktualisierung")
            return _local_update_node(node_id, update)

    async def delete_node(self, node_id: int) -> dict[str, Any]:
        try:
            return await self._request("DELETE", f"/api/cluster/nodes/{node_id}")
        except ClusterUnavailable:
            logger.info("Fallback auf lokale Cluster-Node-Loeschung")
            return _local_delete_node(node_id)

    async def close(self) -> None:
        if self.session is not None:
            await self.session.aclose()
            self.session = None


class ClusterUnavailable(Exception):
    """Signalisiert, dass der entfernte Cluster-Knoten nicht verwendet werden kann."""


# ═══════════════════════════════════════════════════════════════
# Singleton-Instanz fuer das Dashboard
# ═══════════════════════════════════════════════════════════════

cluster_task_client = ClusterTaskClient()
