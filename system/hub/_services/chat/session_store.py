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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .agent_profile_context import binding_metadata, profile_chat_id_agent


CHAT_SNAPSHOT_TYPE = "chat-transcript.v1"
CHAT_SESSION_PREFIX = "chat-runtime:v1:"
_BINDING_FIELDS = ("context_class", "agent_id", "exact_slug", "db_version", "source_version", "profile_sha256")
_ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool"})
_ALLOWED_ANSWER_STATUSES = frozenset({"success", "failed"})


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

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise ChatSessionStoreError("canonical BACH database is unavailable")
        conn = None
        try:
            conn = sqlite3.connect(self.db_path.resolve(strict=True).as_uri() + "?mode=ro",
                                   uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            return conn
        except (sqlite3.Error, OSError) as exc:
            if conn is not None:
                conn.close()
            raise ChatSessionStoreError("cannot read canonical BACH database") from exc

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
            normalised_item = {
                "role": role,
                "content": content[:self.max_content_chars],
            }
            # Additive transcript metadata; old snapshots without this key
            # remain valid and are handled by ChatRuntime's legacy fallback.
            answer_status = item.get("answer_status")
            if role == "assistant" and answer_status in _ALLOWED_ANSWER_STATUSES:
                normalised_item["answer_status"] = answer_status
            completed_ids = item.get("completed_task_ids")
            if (
                role == "assistant" and answer_status == "success"
                and isinstance(completed_ids, list) and completed_ids
                and all(type(task_id) is int and task_id > 0 for task_id in completed_ids)
                and len(set(completed_ids)) == len(completed_ids)
            ):
                normalised_item["completed_task_ids"] = list(completed_ids)
            normalised.append(normalised_item)

        if len(normalised) <= self.max_messages:
            return normalised

        # A summarised-context system entry belongs to the model context even
        # when the visible tail is trimmed.  Keep it plus the newest turns.
        first = normalised[0]
        if first["role"] == "system" and self.max_messages > 1:
            return [first] + normalised[-(self.max_messages - 1):]
        return normalised[-self.max_messages:]

    def load_state(self, chat_id: str) -> dict:
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
            return {"messages": [], "binding": None}
        try:
            payload = json.loads(row["snapshot_data"] or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ChatSessionStoreError("chat transcript snapshot is invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ChatSessionStoreError("unsupported chat transcript snapshot version")
        binding = binding_metadata({k: payload[k] for k in _BINDING_FIELDS if k in payload} or None)
        return {"messages": self._normalise_messages(payload.get("messages", [])), "binding": binding}

    def load(self, chat_id: str) -> list[dict]:
        return self.load_state(chat_id)["messages"]

    def save(self, chat_id: str, messages: Iterable[dict], name: str = "Chat transcript",
             *, binding: dict | None = None) -> None:
        session_id = self.session_id(chat_id)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        binding = binding_metadata(binding)
        normalised = self._normalise_messages(messages)
        payload = json.dumps(
            {
                "version": 1,
                "chat_id": str(chat_id),
                "messages": normalised,
                "updated_at": timestamp,
                **(binding or {}),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, snapshot_data FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (session_id, CHAT_SNAPSHOT_TYPE),
            ).fetchone()
            if row is not None:
                previous = json.loads(row["snapshot_data"] or "{}")
                if not isinstance(previous, dict) or previous.get("version") != 1:
                    raise ChatSessionStoreError("existing transcript is invalid")
                prior_binding = binding_metadata({k: previous[k] for k in _BINDING_FIELDS if k in previous} or None)
                if prior_binding != binding or (prior_binding is None and binding is not None and previous.get("messages")):
                    raise ChatSessionStoreError("chat profile binding cannot change or absorb global history")
            if row is None:
                conn.execute(
                    "INSERT INTO session_snapshots "
                    "(session_id, snapshot_type, name, snapshot_data, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session_id, CHAT_SNAPSHOT_TYPE, name, payload, timestamp),
                )
            else:
                snapshot_id = row["id"]
                conn.execute(
                    "UPDATE session_snapshots SET snapshot_data = ?, created_at = ?, name = ? "
                    "WHERE id = ?",
                    (payload, timestamp, name, snapshot_id),
                )
            conn.commit()
        except (sqlite3.Error, ValueError, TypeError, ChatSessionStoreError) as exc:
            conn.rollback()
            if isinstance(exc, ChatSessionStoreError):
                raise
            raise ChatSessionStoreError(f"cannot persist chat transcript: {exc}") from exc
        finally:
            conn.close()

    def archive_current(self, chat_id: str, name_prefix: str = "Archiviert") -> int | None:
        """Kopiert die aktuelle Session als permanente Archiv-Session und vergibt eine neue Snapshot-ID."""
        session_id = self.session_id(chat_id)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT snapshot_data FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (session_id, CHAT_SNAPSHOT_TYPE),
            ).fetchone()
            if row is None:
                return None
            data = row["snapshot_data"]
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            archive_session_id = f"{session_id}:archived:{timestamp}"
            archive_name = f"{name_prefix} {timestamp}"
            cur = conn.execute(
                "INSERT INTO session_snapshots "
                "(session_id, snapshot_type, name, snapshot_data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (archive_session_id, CHAT_SNAPSHOT_TYPE, archive_name, data, timestamp),
            )
            archived_id = cur.lastrowid
            conn.commit()
            return archived_id
        except sqlite3.Error as exc:
            conn.rollback()
            raise ChatSessionStoreError(f"cannot archive chat transcript: {exc}") from exc
        finally:
            conn.close()

    def archive_and_delete(
        self, chat_id: str, ram_messages: Iterable[dict] | None = None,
        name_prefix: str = "Archiviert", *, binding: dict | None = None,
    ) -> int | None:
        """Atomically preserve DB and differing RAM transcripts before clear."""
        session_id = self.session_id(chat_id)
        ram = self._normalise_messages(list(ram_messages or []))
        binding = binding_metadata(binding)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT snapshot_data FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ? "
                "ORDER BY id DESC",
                (session_id, CHAT_SNAPSHOT_TYPE),
            ).fetchall()
            if len(rows) > 1:
                raise ChatSessionStoreError("cannot clear duplicate live chat snapshots")
            row = rows[0] if rows else None
            durable = []
            if row is not None:
                try:
                    payload = json.loads(row["snapshot_data"] or "")
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ChatSessionStoreError("cannot archive invalid chat snapshot") from exc
                if not isinstance(payload, dict) or payload.get("version") != 1:
                    raise ChatSessionStoreError("cannot archive unsupported chat snapshot")
                durable_binding = binding_metadata({k: payload[k] for k in _BINDING_FIELDS if k in payload} or None)
                if durable_binding != binding:
                    raise ChatSessionStoreError("archive binding differs from active session")
                durable = self._normalise_messages(payload.get("messages", []))

            archived_ids = []

            def archive(kind: str, data: str) -> None:
                archive_id = f"{session_id}:archived:{timestamp}:{uuid.uuid4().hex[:8]}"
                cur = conn.execute(
                    "INSERT INTO session_snapshots "
                    "(session_id, snapshot_type, name, snapshot_data, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (archive_id, CHAT_SNAPSHOT_TYPE,
                     f"{name_prefix} [{kind}] {timestamp}", data, timestamp),
                )
                archived_ids.append(cur.lastrowid)

            if row is not None:
                archive("DB", row["snapshot_data"])
            if ram and ram != durable:
                ram_data = json.dumps(
                    {"version": 1, "chat_id": str(chat_id),
                     "messages": ram, "updated_at": timestamp, **(binding or {})},
                    ensure_ascii=False, separators=(",", ":"),
                )
                archive("RAM", ram_data)

            conn.execute(
                "DELETE FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ?",
                (session_id, CHAT_SNAPSHOT_TYPE),
            )
            conn.commit()
            return archived_ids[-1] if archived_ids else None
        except (sqlite3.Error, ChatSessionStoreError, ValueError, TypeError) as exc:
            conn.rollback()
            if isinstance(exc, ChatSessionStoreError):
                raise
            raise ChatSessionStoreError(f"cannot clear chat transcript: {exc}") from exc
        finally:
            conn.close()

    def list_snapshot_page(self, *, limit: int = 25, offset: int = 0,
                           agent_id: int | None = None, archive: str = "all") -> dict:
        """Read an authenticated viewer's explicit context; filter before paging."""
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 100_000:
            raise ValueError("Invalid transcript page")
        if agent_id is not None and (type(agent_id) is not int or agent_id <= 0):
            raise ValueError("Invalid transcript profile")
        if archive not in {"all", "current", "archived"}:
            raise ValueError("Invalid transcript archive filter")
        if not self.db_path.is_file():
            raise ChatSessionStoreError("canonical BACH database is unavailable")
        conn = None
        try:
            conn = self._connect_readonly()
            conn.create_function("profile_chat_id_agent", 1, profile_chat_id_agent, deterministic=True)
            conn.execute("BEGIN")
            conditions = ["snapshot_type = ?"]
            args = [CHAT_SNAPSHOT_TYPE]
            if agent_id is None:
                conditions.extend(["COALESCE(json_extract(snapshot_data,'$.context_class'),'') != 'agent-profile'",
                                   "substr(COALESCE(json_extract(snapshot_data,'$.chat_id'),''),1,6) != 'agent:'"])
            else:
                conditions.extend(["json_extract(snapshot_data,'$.context_class') = 'agent-profile'",
                                   "json_type(snapshot_data,'$.agent_id') = 'integer'",
                                   "json_extract(snapshot_data,'$.agent_id') = ?",
                                   "profile_chat_id_agent(json_extract(snapshot_data,'$.chat_id')) = ?"])
                args.extend([agent_id, agent_id])
            if archive != "all":
                conditions.append("instr(session_id, ':archived:') " + ("> 0" if archive == "archived" else "= 0"))
            where = " AND ".join(conditions)
            total = conn.execute("SELECT COUNT(*) FROM session_snapshots WHERE " + where, args).fetchone()[0]
            rows = conn.execute(
                "SELECT id, session_id, name, created_at, length(snapshot_data) AS size_bytes, "
                "json_extract(snapshot_data,'$.chat_id') AS chat_id, "
                "json_extract(snapshot_data,'$.context_class') AS context_class, "
                "json_extract(snapshot_data,'$.agent_id') AS agent_id, "
                "json_array_length(snapshot_data,'$.messages') AS stored_message_count, "
                "json_extract(snapshot_data,'$.version') AS payload_version "
                "FROM session_snapshots WHERE " + where + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset]).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                if (item.pop("payload_version") != 1 or type(item["stored_message_count"]) is not int
                        or not 0 <= item["stored_message_count"] <= 1000
                        or any(type(item[key]) is not str for key in ("session_id", "chat_id", "name"))):
                    raise ChatSessionStoreError("stored transcript metadata is invalid")
                item["archived"] = ":archived:" in item["session_id"]
                items.append(item)
            return {"sessions": items, "total": total, "offset": offset, "limit": limit,
                    "has_more": offset + len(items) < total,
                    "save_limits": {"max_messages": self.max_messages, "max_content_chars": self.max_content_chars}}
        except (sqlite3.Error, OSError) as exc:
            raise ChatSessionStoreError("cannot read canonical transcript page") from exc
        finally:
            if conn is not None:
                conn.close()

    def list_snapshots(self, limit: int = 50) -> list[dict]:
        """Liefert eine sortierte Übersicht aller Chat-Transkripte."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT id, session_id, name, created_at, length(snapshot_data) as data_len, "
                "json_extract(snapshot_data, '$.chat_id') as chat_id, "
                "json_extract(snapshot_data, '$.agent_id') as agent_id, "
                "json_extract(snapshot_data, '$.context_class') as context_class "
                "FROM session_snapshots "
                "WHERE snapshot_type = ? "
                "ORDER BY id DESC LIMIT ?",
                (CHAT_SNAPSHOT_TYPE, limit),
            )
            result = []
            for r in cur.fetchall():
                result.append({
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "chat_id": r["chat_id"] or "",
                    "agent_id": r["agent_id"],
                    "context_class": r["context_class"],
                    "name": r["name"],
                    "created_at": r["created_at"],
                    "size_bytes": r["data_len"],
                })
            return result
        except sqlite3.Error as exc:
            raise ChatSessionStoreError(f"cannot list chat transcripts: {exc}") from exc
        finally:
            conn.close()

    def get_snapshot_by_id(self, snapshot_id: int) -> dict | None:
        """Holt ein konkretes Transkript per Primärschlüssel."""
        conn = self._connect_readonly()
        try:
            row = conn.execute(
                "SELECT id, session_id, name, snapshot_data, created_at "
                "FROM session_snapshots "
                "WHERE id = ? AND snapshot_type = ?",
                (snapshot_id, CHAT_SNAPSHOT_TYPE),
            ).fetchone()
            if not row:
                return None
            raw = row["snapshot_data"]
            if not isinstance(raw, str) or len(raw) > 5_000_000:
                raise ChatSessionStoreError("stored transcript exceeds readable bounds")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("version") != 1:
                raise ChatSessionStoreError("stored transcript version is invalid")
            return {
                "id": row["id"],
                "session_id": row["session_id"],
                "chat_id": payload.get("chat_id", ""),
                "name": row["name"],
                "created_at": row["created_at"],
                "messages": payload.get("messages", []),
                "updated_at": payload.get("updated_at"),
                "binding": binding_metadata({k: payload[k] for k in _BINDING_FIELDS if k in payload} or None),
            }
        except sqlite3.Error as exc:
            raise ChatSessionStoreError(f"cannot get chat transcript {snapshot_id}: {exc}") from exc
        finally:
            conn.close()

    def get_last_updated(self, chat_id: str) -> float | None:
        """Liefert den Unix-Timestamp der letzten Änderung der aktiven Session."""
        session_id = self.session_id(chat_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT snapshot_data, created_at FROM session_snapshots "
                "WHERE session_id = ? AND snapshot_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (session_id, CHAT_SNAPSHOT_TYPE),
            ).fetchone()
            if row is None:
                return None
            ts_str = row["created_at"]
            try:
                payload = json.loads(row["snapshot_data"] or "{}")
                if payload.get("updated_at"):
                    ts_str = payload["updated_at"]
            except Exception:
                pass
            if not ts_str:
                return None
            return datetime.fromisoformat(ts_str).timestamp()
        except Exception:
            return None
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
