# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: message_delivery
======================================
Self-contained message delivery and multi-partner routing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def init_messages_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            read_at TEXT,
            archived_at TEXT,
            ack_at TEXT
        )
    """)
    conn.commit()


class MessageDeliveryEngine:
    """Self-contained message delivery manager."""

    def __init__(self, db_path_or_conn_factory: Any = None):
        if callable(db_path_or_conn_factory):
            self._factory = db_path_or_conn_factory
            self._db_path = None
        elif isinstance(db_path_or_conn_factory, (str, Path)):
            self._db_path = Path(db_path_or_conn_factory)
            self._factory = None
        else:
            self._db_path = Path(":memory:")
            self._factory = None

    def get_connection(self) -> sqlite3.Connection:
        if self._factory:
            conn = self._factory()
        else:
            conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        init_messages_schema(conn)
        return conn

    def send(self, recipient: str, message: str, sender: str = "user") -> int:
        recipient = (recipient or "").strip().lower()
        sender = (sender or "").strip().lower()
        message = (message or "").strip()
        if not recipient or not message:
            raise ValueError("Recipient und Nachricht duerfen nicht leer sein")

        now = datetime.now().isoformat()
        conn = self.get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO messages (sender, recipient, message, created_at) VALUES (?, ?, ?, ?)",
                (sender, recipient, message, now)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def list_messages(self, box: str = "inbox", partner: str = "user", unread_only: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
        box = (box or "inbox").lower()
        partner = (partner or "user").lower()
        conn = self.get_connection()
        try:
            if box == "outbox":
                query = "SELECT * FROM messages WHERE sender = ? AND archived_at IS NULL"
                params = [partner]
            elif box == "archive":
                query = "SELECT * FROM messages WHERE (recipient = ? OR sender = ?) AND archived_at IS NOT NULL"
                params = [partner, partner]
            else: # inbox
                query = "SELECT * FROM messages WHERE recipient = ? AND archived_at IS NULL"
                params = [partner]
                if unread_only:
                    query += " AND read_at IS NULL"

            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def read(self, msg_id: int, mark_ack: bool = False) -> Optional[Dict[str, Any]]:
        now = datetime.now().isoformat()
        conn = self.get_connection()
        try:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE messages SET read_at = COALESCE(read_at, ?) WHERE id = ?", (now, msg_id))
            if mark_ack:
                conn.execute("UPDATE messages SET ack_at = COALESCE(ack_at, ?) WHERE id = ?", (now, msg_id))
            conn.commit()
            updated = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
            return dict(updated)
        finally:
            conn.close()

    def count(self, recipient: str = "user", unread_only: bool = True) -> int:
        recipient = (recipient or "user").lower()
        conn = self.get_connection()
        try:
            if unread_only:
                res = conn.execute("SELECT COUNT(*) FROM messages WHERE recipient = ? AND read_at IS NULL AND archived_at IS NULL", (recipient,)).fetchone()
            else:
                res = conn.execute("SELECT COUNT(*) FROM messages WHERE recipient = ? AND archived_at IS NULL", (recipient,)).fetchone()
            return res[0] if res else 0
        finally:
            conn.close()

    def delete(self, msg_id: int) -> bool:
        conn = self.get_connection()
        try:
            cur = conn.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def archive(self, msg_id: int) -> bool:
        now = datetime.now().isoformat()
        conn = self.get_connection()
        try:
            cur = conn.execute("UPDATE messages SET archived_at = ? WHERE id = ?", (now, msg_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
