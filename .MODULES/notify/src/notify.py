# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: notify
=============================
Multi-channel notification routing, priority tagging, and queue persistence.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


VALID_CHANNELS = frozenset({"desktop", "console", "queue", "webhook", "email", "all"})
VALID_PRIORITIES = frozenset({"low", "normal", "high", "urgent"})


def tag_notification(text: str, tags: Sequence[str] | str) -> str:
    """Format and prepend tags to a notification text."""
    if isinstance(tags, str):
        parsed = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        parsed = [str(t).strip() for t in tags if str(t).strip()]
    if not parsed:
        return text
    tag_header = "".join(f"[{t}] " for t in parsed)
    return f"{tag_header}{text}"


def init_notify_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_queue (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            channel TEXT NOT NULL,
            priority TEXT NOT NULL,
            tags TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            metadata TEXT
        )
    """)
    conn.commit()


class NotificationRouter:
    """Dispatches and persists notifications across channels."""

    def __init__(self, db_path: Path | str = ":memory:"):
        self.db_path = str(db_path)
        self._handlers: Dict[str, Callable[[Dict[str, Any]], bool]] = {}

    def register_channel_handler(self, channel: str, handler: Callable[[Dict[str, Any]], bool]) -> None:
        self._handlers[channel.lower()] = handler

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        init_notify_schema(conn)
        return conn

    def send(
        self,
        title: str,
        message: str,
        *,
        channel: str = "queue",
        priority: str = "normal",
        tags: Optional[Sequence[str] | str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Dispatch a notification to specified channel or persist in queue."""
        ch = str(channel or "queue").strip().lower()
        if ch not in VALID_CHANNELS:
            ch = "queue"
        prio = str(priority or "normal").strip().lower()
        if prio not in VALID_PRIORITIES:
            prio = "normal"

        tagged_msg = tag_notification(message, tags) if tags else message
        notif_id = f"notif_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(list(tags) if isinstance(tags, (list, tuple)) else ([tags] if tags else []))
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        payload = {
            "id": notif_id,
            "title": str(title or "").strip(),
            "message": tagged_msg,
            "channel": ch,
            "priority": prio,
            "tags": tags_json,
            "created_at": now,
            "metadata": metadata or {},
        }

        delivered = False
        if ch in self._handlers:
            try:
                delivered = bool(self._handlers[ch](payload))
            except Exception:
                delivered = False
        elif ch == "console":
            delivered = True

        status = "delivered" if delivered else "pending"
        delivered_at = now if delivered else None

        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO notification_queue "
                    "(id, title, message, channel, priority, tags, status, created_at, delivered_at, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (notif_id, payload["title"], tagged_msg, ch, prio, tags_json, status, now, delivered_at, meta_json)
                )
        finally:
            conn.close()

        return {
            "ok": True,
            "id": notif_id,
            "channel": ch,
            "priority": prio,
            "status": status,
            "delivered": delivered,
        }

    def get_pending(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM notification_queue WHERE status = 'pending' ORDER BY created_at ASC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_delivered(self, notif_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE notification_queue SET status = 'delivered', delivered_at = ? WHERE id = ?",
                    (now, notif_id)
                )
                return cur.rowcount > 0
        finally:
            conn.close()
