"""Device-authenticated read-only native chat and task history; no provider starts."""
from __future__ import annotations

from contextlib import closing
import re
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request, Path as PathParam
from hub.bach_paths import BACH_DB
from hub._services.chat.session_store import SQLiteChatSessionStore, ChatSessionStoreError
from hub._services.chat.agent_profile_context import (
    ProfileUnavailable, resolve_profile, require_current_binding, profile_chat_id_agent,
)

router = APIRouter(prefix="/api/agent-history", tags=["agent-history"])
STATUS = {"pending", "in_progress", "done", "blocked", "cancelled", "review"}
ACTION = re.compile(r"^[a-z0-9_.-]{1,64}$")


def authorize(request: Request):
    from .unified_api import _require_memory_device
    _require_memory_device(request)


def _store():
    return SQLiteChatSessionStore(BACH_DB)


@router.get("/sessions")
def sessions(request: Request, limit: int = Query(25, ge=1, le=100),
             offset: int = Query(0, ge=0, le=100_000),
             agent_id: int | None = Query(None, ge=1, le=2_147_483_647),
             archive: str = Query("all", pattern="^(all|current|archived)$")):
    authorize(request)
    try:
        if agent_id is not None:
            resolve_profile(agent_id)
        page = _store().list_snapshot_page(limit=limit, offset=offset, agent_id=agent_id, archive=archive)
        return {"schema": "bach.chat-sessions.v1", "source": "session_snapshots",
                "snapshot_type": "chat-transcript.v1", "context": "profile" if agent_id else "global",
                "agent_id": agent_id, "archive": archive, **page}
    except ProfileUnavailable:
        raise HTTPException(409, "Profilquelle nicht mehr verifiziert")
    except (ChatSessionStoreError, OSError, ValueError):
        raise HTTPException(503, "Native Transkriptquelle nicht verfügbar")


def _visible_assistant_text(content: str) -> str:
    # Reasoning fields are never projected; tagged private reasoning is omitted.
    content = re.sub(r"<(?:think|analysis)>.*?</(?:think|analysis)>", "", content,
                     flags=re.I | re.S)
    content = re.sub(r"<(?:think|analysis)>.*$", "", content, flags=re.I | re.S)
    return content.strip()


@router.get("/sessions/{snapshot_id}")
def session(request: Request, snapshot_id: int = PathParam(..., ge=1, le=2_147_483_647), agent_id: int | None = Query(None, ge=1, le=2_147_483_647)):
    authorize(request)
    if snapshot_id <= 0:
        raise HTTPException(422, "Gültige Snapshot-ID erforderlich")
    try:
        snapshot = _store().get_snapshot_by_id(snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "Gespeichertes Transkript nicht gefunden")
        binding = snapshot.get("binding")
        if binding is not None:
            if agent_id != binding["agent_id"] or profile_chat_id_agent(snapshot["chat_id"]) != agent_id:
                raise HTTPException(409, "Passende Profilbindung erforderlich")
            require_current_binding(binding)
        elif agent_id is not None or str(snapshot.get("chat_id", "")).startswith("agent:"):
            raise HTTPException(409, "Transkript gehört nicht zum gewählten Kontext")
        raw_messages = snapshot.get("messages")
        if not isinstance(raw_messages, list) or len(raw_messages) > 1000:
            raise ChatSessionStoreError("invalid transcript messages")
        messages = []
        for index, message in enumerate(raw_messages):
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
                raise ChatSessionStoreError("invalid transcript role")
            content = message.get("content")
            if not isinstance(content, str) or len(content) > 1_000_000:
                raise ChatSessionStoreError("invalid transcript content")
            if message["role"] == "system":
                continue
            item = {"index": index, "role": message["role"],
                    "content": _visible_assistant_text(content) if message["role"] == "assistant" else content}
            if message["role"] == "assistant":
                if message.get("answer_status") in {"success", "failed"}:
                    item["answer_status"] = message["answer_status"]
                ids = message.get("completed_task_ids")
                if message.get("answer_status") == "success" and isinstance(ids, list) and len(ids) <= 100 and all(type(i) is int and 0 < i <= 2_147_483_647 for i in ids):
                    item["completed_task_ids"] = list(dict.fromkeys(ids))
            messages.append(item)
        return {"schema": "bach.chat-session.v1", "source": "session_snapshots",
                "snapshot_id": snapshot_id, "created_at": snapshot.get("created_at"),
                "updated_at": snapshot.get("updated_at"), "name": snapshot.get("name"),
                "archived": ":archived:" in snapshot["session_id"],
                "context": "profile" if binding else "global", "agent_id": agent_id,
                "stored_message_count": len(raw_messages), "messages": messages,
                "available_excerpt": True, "system_messages_included": False,
                "reasoning_included": False}
    except ProfileUnavailable:
        raise HTTPException(409, "Gespeicherte Profilbindung nicht mehr verifiziert")
    except (ChatSessionStoreError, OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Gespeichertes Transkript nicht lesbar")


@router.get("/tasks")
def task_history(request: Request, limit: int = Query(25, ge=1, le=100),
                 offset: int = Query(0, ge=0, le=100_000),
                 task_id: int | None = Query(None, ge=1, le=2_147_483_647), status: str | None = None):
    authorize(request)
    if status is not None and status not in STATUS:
        raise HTTPException(422, "Unbekannter aktueller Aufgabenstatus")
    try:
        if not BACH_DB.is_file():
            raise OSError("database missing")
        with closing(sqlite3.connect(BACH_DB.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            filters = ["1=1"]
            args = []
            if task_id is not None:
                filters.append("h.task_id=?"); args.append(task_id)
            if status is not None:
                filters.append("t.status=?"); args.append(status)
            where = " AND ".join(filters)
            join = " FROM task_history h LEFT JOIN tasks t ON t.id=h.task_id WHERE " + where
            total = conn.execute("SELECT COUNT(*)" + join, args).fetchone()[0]
            rows = conn.execute(
                "SELECT h.rowid AS id,h.task_id,t.title,t.status AS current_task_status,"
                "h.action,h.field_changed,h.changed_at,"
                "CASE WHEN h.field_changed='status' THEN h.old_value ELSE NULL END AS old_status,"
                "CASE WHEN h.field_changed='status' THEN h.new_value ELSE NULL END AS new_status"
                + join + " ORDER BY h.rowid DESC LIMIT ? OFFSET ?", [*args,limit,offset]).fetchall()
            events = []
            for row in rows:
                item = dict(row)
                if type(item["task_id"]) is not int or item["task_id"] <= 0:
                    raise ValueError("invalid task history")
                item["action"] = item["action"] if isinstance(item["action"],str) and ACTION.fullmatch(item["action"]) else "unknown"
                field = item.pop("field_changed")
                item["field"] = field if isinstance(field,str) and re.fullmatch(r"[a-z_]{1,40}",field) else "unknown"
                for key in ("old_status","new_status","current_task_status"):
                    item[key] = item[key] if item[key] in STATUS else None
                item["title"] = str(item["title"] or "Aufgabe nicht mehr im Register")[:1000]
                events.append(item)
            return {"schema":"bach.task-history.v1","source":"task_history","events":events,
                    "total":total,"offset":offset,"limit":limit,"has_more":offset+len(events)<total,
                    "actors_included":False,"content_changes_included":False}
    except (sqlite3.Error,OSError,ValueError,TypeError):
        raise HTTPException(503, "Dauerhafter Taskverlauf nicht verfügbar")
