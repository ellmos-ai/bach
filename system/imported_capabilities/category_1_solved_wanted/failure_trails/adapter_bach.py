# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Negative Memory & Failure Trails (from Roshambo).

Records dead ends, runtime errors, and failed attempts so that autonomous subagents
do not repeatedly attempt known broken approaches. Integrates with Bach Memory and Task execution.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FailureTrail:
    id: Optional[int]
    task_id: Optional[int]
    category: str
    action_attempted: str
    failure_reason: str
    context_data: Dict[str, Any]
    recorded_by: str
    recorded_at: str


def ensure_failure_trails_schema(conn: sqlite3.Connection) -> None:
    """Ensures the failure_trails table exists in the database."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS failure_trails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            category TEXT NOT NULL,
            action_attempted TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            context_data TEXT,
            recorded_by TEXT DEFAULT 'agent',
            recorded_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_failure_trails_cat ON failure_trails(category)"
    )
    conn.commit()


class FailureMemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextlib.contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            ensure_failure_trails_schema(conn)
            with conn:
                yield conn
        finally:
            conn.close()

    def record_failure(
        self,
        action_attempted: str,
        failure_reason: str,
        category: str = "general",
        task_id: Optional[int] = None,
        context_data: Optional[Dict[str, Any]] = None,
        recorded_by: str = "agent",
    ) -> int:
        """Records a negative trail (failed attempt)."""
        now = datetime.now(timezone.utc).isoformat()
        ctx_json = json.dumps(context_data or {}, ensure_ascii=False)
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO failure_trails
                    (task_id, category, action_attempted, failure_reason, context_data, recorded_by, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, category, action_attempted, failure_reason, ctx_json, recorded_by, now),
            )
            conn.commit()
            return cursor.lastrowid

    def query_prior_failures(
        self,
        keywords: List[str],
        category: Optional[str] = None,
        limit: int = 5,
    ) -> List[FailureTrail]:
        """Queries for prior failed attempts matching keywords to warn against dead ends."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            query = "SELECT id, task_id, category, action_attempted, failure_reason, context_data, recorded_by, recorded_at FROM failure_trails WHERE 1=1"
            params: List[Any] = []

            if category:
                query += " AND category = ?"
                params.append(category)

            # Keyword filtering
            if keywords:
                clause = " OR ".join(["action_attempted LIKE ? OR failure_reason LIKE ?"] * len(keywords))
                query += f" AND ({clause})"
                for kw in keywords:
                    params.extend([f"%{kw}%", f"%{kw}%"])

            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            results = []
            for row in cursor.fetchall():
                results.append(
                    FailureTrail(
                        id=row[0],
                        task_id=row[1],
                        category=row[2],
                        action_attempted=row[3],
                        failure_reason=row[4],
                        context_data=json.loads(row[5] or "{}"),
                        recorded_by=row[6],
                        recorded_at=row[7],
                    )
                )
            return results
