# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: conversation_store
========================================
Self-contained conversation transcript storage and snapshot hashing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


CHAT_SNAPSHOT_TYPE = "chat-transcript.v1"
CHAT_SESSION_PREFIX = "chat-runtime:v1:"
ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool"})


def init_snapshots_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_snapshots (
            session_id TEXT PRIMARY KEY,
            snapshot_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()


class ConversationTranscriptStore:
    """Self-contained transcript manager with hashed chat identifiers and bounded context."""

    def __init__(self, db_path_or_conn_factory: Any = None, *, max_messages: int = 40, max_content_chars: int = 24_000):
        if callable(db_path_or_conn_factory):
            self._factory = db_path_or_conn_factory
            self._db_path = None
        elif isinstance(db_path_or_conn_factory, (str, Path)):
            self._db_path = Path(db_path_or_conn_factory)
            self._factory = None
        else:
            self._db_path = Path(":memory:")
            self._factory = None
        self.max_messages = max_messages
        self.max_content_chars = max_content_chars

    @staticmethod
    def session_id(chat_id: str) -> str:
        digest = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()
        return f"{CHAT_SESSION_PREFIX}{digest}"

    def get_connection(self) -> sqlite3.Connection:
        if self._factory:
            conn = self._factory()
        else:
            conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        init_snapshots_schema(conn)
        return conn

    def get_transcript(self, chat_id: str) -> List[Dict[str, Any]]:
        sid = self.session_id(chat_id)
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT payload FROM session_snapshots WHERE session_id = ? AND snapshot_type = ?",
                (sid, CHAT_SNAPSHOT_TYPE)
            ).fetchone()
            if not row:
                return []
            try:
                data = json.loads(row["payload"])
                return data.get("messages", []) if isinstance(data, dict) else []
            except Exception:
                return []
        finally:
            conn.close()

    def append_message(self, chat_id: str, role: str, content: str, *, metadata: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        role = str(role or "user").strip().lower()
        if role not in ALLOWED_ROLES:
            raise ValueError(f"Ungueltige Rolle: {role}")
        content = str(content or "")

        messages = self.get_transcript(chat_id)
        new_msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            new_msg["metadata"] = metadata
        messages.append(new_msg)

        # Enforce bounds
        if len(messages) > self.max_messages:
            messages = messages[-self.max_messages:]

        total_chars = sum(len(m.get("content", "")) for m in messages)
        while messages and total_chars > self.max_content_chars:
            popped = messages.pop(0)
            total_chars -= len(popped.get("content", ""))

        sid = self.session_id(chat_id)
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps({"chat_id_hash": sid, "messages": messages}, ensure_ascii=False)

        conn = self.get_connection()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO session_snapshots (session_id, snapshot_type, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (sid, CHAT_SNAPSHOT_TYPE, payload, now)
            )
            conn.commit()
            return messages
        finally:
            conn.close()

    def clear_transcript(self, chat_id: str) -> bool:
        sid = self.session_id(chat_id)
        conn = self.get_connection()
        try:
            cur = conn.execute("DELETE FROM session_snapshots WHERE session_id = ?", (sid,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
