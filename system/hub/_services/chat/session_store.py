"""Persistent ChatRuntime transcripts in BACH's existing snapshot store.

The chat service must not create a second database.  ``session_snapshots`` in
the canonical ``bach.db`` already owns JSON session state, so chat transcripts
use a dedicated snapshot type there.  Chat identifiers are hashed before they
reach SQLite; a Telegram id or another transport-specific identifier therefore
does not become an index value in the database.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


CHAT_SNAPSHOT_TYPE = "chat-transcript.v1"
CHAT_SESSION_PREFIX = "chat-runtime:v1:"
_ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool"})


class ChatSessionStoreError(RuntimeError):
    """The canonical snapshot store could not safely serve an operation."""


class SQLiteChatSessionStore:
    """Store one current transcript snapshot per hashed chat identifier."""

    def __init__(self, db_path: str | Path, *, max_messages: int = 40,
                 max_content_chars: int = 24_000):
        self.db_path = Path(db_path)
        self.max_messages = max_messages
        self.max_content_chars = max_content_chars

    @staticmethod
    def session_id(chat_id: str) -> str:
        digest = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()
        return f"{CHAT_SESSION_PREFIX}{digest}"

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise ChatSessionStoreError(
                "canonical BACH database is unavailable"
            )
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as exc:
            raise ChatSessionStoreError(
                f"cannot open canonical BACH database: {exc}"
            ) from exc

    def _normalise_messages(self, messages: Iterable[dict]) -> list[dict]:
        if not isinstance(messages, (list, tuple)):
            raise ChatSessionStoreError("chat transcript messages must be a list")

        normalised: list[dict] = []
        for item in messages:
            if not isinstance(item, dict):
                raise ChatSessionStoreError("chat transcript entry must be an object")
            role = item.get("role")
            content = item.get("content", "")
            if role not in _ALLOWED_ROLES or not isinstance(content, str):
                raise ChatSessionStoreError("chat transcript entry has invalid role/content")
            normalised.append({
                "role": role,
                "content": content[:self.max_content_chars],
            })

        if len(normalised) <= self.max_messages:
            return normalised

        # A summarised-context system entry belongs to the model context even
        # when the visible tail is trimmed.  Keep it plus the newest turns.
        first = normalised[0]
        if first["role"] == "system" and self.max_messages > 1:
            return [first] + normalised[-(self.max_messages - 1):]
        return normalised[-self.max_messages:]

    def load(self, chat_id: str) -> list[dict]:
        session_id = self.session_id(chat_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT snapshot_data FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (session_id, CHAT_SNAPSHOT_TYPE),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ChatSessionStoreError(f"cannot load chat transcript: {exc}") from exc
        finally:
            conn.close()

        if row is None:
            return []
        try:
            payload = json.loads(row["snapshot_data"] or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ChatSessionStoreError("chat transcript snapshot is invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ChatSessionStoreError("unsupported chat transcript snapshot version")
        return self._normalise_messages(payload.get("messages", []))

    def save(self, chat_id: str, messages: Iterable[dict]) -> None:
        session_id = self.session_id(chat_id)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = json.dumps(
            {
                "version": 1,
                "messages": self._normalise_messages(messages),
                "updated_at": timestamp,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (session_id, CHAT_SNAPSHOT_TYPE),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO session_snapshots "
                    "(session_id, snapshot_type, name, snapshot_data, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session_id, CHAT_SNAPSHOT_TYPE, "Chat transcript", payload, timestamp),
                )
            else:
                snapshot_id = row["id"]
                conn.execute(
                    "DELETE FROM session_snapshots WHERE session_id = ? "
                    "AND snapshot_type = ? AND id <> ?",
                    (session_id, CHAT_SNAPSHOT_TYPE, snapshot_id),
                )
                conn.execute(
                    "UPDATE session_snapshots SET snapshot_data = ?, created_at = ? "
                    "WHERE id = ?",
                    (payload, timestamp, snapshot_id),
                )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise ChatSessionStoreError(f"cannot persist chat transcript: {exc}") from exc
        finally:
            conn.close()

    def delete(self, chat_id: str) -> None:
        session_id = self.session_id(chat_id)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ?",
                (session_id, CHAT_SNAPSHOT_TYPE),
            )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise ChatSessionStoreError(f"cannot delete chat transcript: {exc}") from exc
        finally:
            conn.close()
