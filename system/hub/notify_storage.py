# SPDX-License-Identifier: MIT
"""BACH persistence adapter for assistant-core notifications.

The existing ``connections`` and ``connector_messages`` tables stay owned by
BACH.  This adapter creates no schema and exposes only the neutral storage
contract consumed by ``assistant_core.NotificationService``.
"""

from __future__ import annotations

import json
import os
import sqlite3

from assistant_core import ChannelConfig, NotificationRecord


class BachNotifyStorage:
    """Map the assistant-core storage protocol to BACH's existing tables."""

    def __init__(self, db_path: str | os.PathLike[str], timeout: float = 10.0) -> None:
        self.db_path = os.fspath(db_path)
        self.timeout = timeout

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=self.timeout)

    def get_channel(self, channel: str) -> ChannelConfig | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT name, type, endpoint, auth_config, is_active, last_used, success_count
                FROM connections
                WHERE name = ? AND category = 'notification'
                """,
                (f"notify_{channel}",),
            ).fetchone()
        if row is None:
            return None
        return ChannelConfig(
            name=str(row[0]),
            channel=str(row[1] or channel),
            endpoint=str(row[2] or ""),
            auth_config=str(row[3] or ""),
            is_active=bool(row[4]),
            last_used=str(row[5]) if row[5] else None,
            success_count=int(row[6] or 0),
        )

    def enqueue(self, connector_name: str, recipient: str, content: str, created_at: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO connector_messages
                    (connector_name, direction, sender, recipient, content, created_at)
                VALUES (?, 'out', 'bach', ?, ?, ?)
                """,
                (connector_name, recipient, content, created_at),
            )
            return int(cursor.lastrowid or 0)

    def mark_sent(self, message_id: int, connector_name: str, sent_at: str) -> None:
        with self.connect() as conn:
            updated = conn.execute(
                """
                UPDATE connector_messages SET processed = 1
                WHERE id = ? AND connector_name = ? AND processed = 0
                """,
                (message_id, connector_name),
            )
            if updated.rowcount:
                conn.execute(
                    """
                    UPDATE connections SET last_used = ?, success_count = success_count + 1
                    WHERE name = ?
                    """,
                    (sent_at, connector_name),
                )

    def upsert_channel(
        self,
        channel: str,
        endpoint: str,
        auth_type: str,
        auth_config: str,
        updated_at: str,
    ) -> None:
        name = f"notify_{channel}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO connections
                    (name, type, category, endpoint, auth_type, auth_config,
                     is_active, created_at, updated_at)
                VALUES (?, ?, 'notification', ?, ?, ?, 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    auth_config = CASE WHEN excluded.auth_config != '' THEN excluded.auth_config
                                      ELSE connections.auth_config END,
                    updated_at = excluded.updated_at
                """,
                (name, channel, endpoint, auth_type, auth_config, updated_at, updated_at),
            )

    def list_channels(self) -> list[ChannelConfig]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name, type, endpoint, auth_config, is_active, last_used, success_count
                FROM connections
                WHERE category = 'notification'
                ORDER BY name
                """
            ).fetchall()
        return [
            ChannelConfig(
                name=str(row[0]),
                channel=str(row[1] or str(row[0]).removeprefix("notify_")),
                endpoint=str(row[2] or ""),
                auth_config=str(row[3] or ""),
                is_active=bool(row[4]),
                last_used=str(row[5]) if row[5] else None,
                success_count=int(row[6] or 0),
            )
            for row in rows
        ]

    def history(self, limit: int) -> list[NotificationRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, connector_name, recipient, content, processed, created_at
                FROM connector_messages
                WHERE connector_name LIKE 'notify_%' AND direction = 'out'
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            NotificationRecord(
                id=int(row[0]),
                connector_name=str(row[1]),
                recipient=str(row[2] or ""),
                content=str(row[3] or ""),
                processed=bool(row[4]),
                created_at=str(row[5] or ""),
            )
            for row in rows
        ]

    def sender_tag(self, channel: str) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT auth_config FROM connections WHERE name = ? OR name = ?",
                (channel, f"notify_{channel}"),
            ).fetchone()
        if not row or not row[0]:
            return ""
        try:
            config = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return ""
        return str(config.get("sender_tag", "")) if isinstance(config, dict) else ""
