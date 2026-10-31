"""Device-authenticated read-only native chat and task history; no provider starts."""
from __future__ import annotations

import asyncio
import json
from contextlib import closing
import re
import sqlite3

from fastapi import APIRouter, Body, HTTPException, Query, Request, Path as PathParam
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
def session(request: Request, snapshot_id: int = PathParam(..., ge=1, le=2_147_483_647), agent_id: int | None = Query(None, ge=1, le=2_147_483_647), include_tools: bool = Query(False)):
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
            if message["role"] == "tool" and include_tools:
                item["tool_result"] = True
                try:
                    decoded = json.loads(content)
                except (ValueError, TypeError):
                    decoded = None
                if isinstance(decoded, dict):
                    raw_name = decoded.get("tool")
                    if raw_name is None:
                        raw_name = decoded.get("name")
                    if raw_name is not None:
                        item["tool_name"] = (raw_name if isinstance(raw_name, str) else str(raw_name))[:200]
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


def _resume_zettel(raw_messages, prompt):
    # Deterministic handover note: original assignment, last ten messages, optional hint.
    assignment = ""
    seen_user = False
    lines = []
    for message in raw_messages:
        role = message.get("role")
        content = message.get("content") if isinstance(message.get("content"), str) else ""
        if role == "assistant":
            label = "Assistent|FEHLGESCHLAGEN" if message.get("answer_status") == "failed" else "Assistent"
            text = _visible_assistant_text(content)
        elif role == "tool":
            label = "Werkzeug"
            text = content
        else:
            label = "Nutzer"
            text = content
        text = text.replace("\x00", "").strip()
        if role == "user" and not seen_user:
            assignment = text[:6000]
            seen_user = True
        lines.append("[" + label + "] " + text[:1500])
    history = lines[-10:]

    def compose(history_lines):
        parts = ["AUFTRAG: " + assignment]
        if history_lines:
            parts.append("VERLAUF:\n" + "\n".join(history_lines))
        if prompt:
            parts.append("NUTZERHINWEIS: " + prompt.replace("\x00", "").strip()[:2000])
        return "\n\n".join(parts)

    body = compose(history)
    while history and len(body) > 18000:
        history.pop(0)
        body = compose(history)
    return ("Du setzt eine begonnene Arbeit fort. Das ist dein eigener Uebergabezettel:\n\n"
            + body + "\n\nArbeite ab RESUME weiter. Frage nicht nach.")


@router.post("/sessions/{snapshot_id}/resume")
async def resume_session(request: Request,
                         snapshot_id: int = PathParam(..., ge=1, le=2_147_483_647),
                         payload: dict = Body(...)):
    authorize(request)
    from .unified_api import _require_memory_device_token
    device_token = _require_memory_device_token(request)
    if snapshot_id <= 0:
        raise HTTPException(422, "Gültige Snapshot-ID erforderlich")
    if not isinstance(payload, dict):
        raise HTTPException(422, "Anfragendaten ungültig")
    worker_id = payload.get("worker_id")
    if not isinstance(worker_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", worker_id):
        raise HTTPException(422, "Gültige Worker-ID erforderlich")
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise HTTPException(422, "Modellname ungültig")
    if isinstance(model, str) and len(model) > 200:
        raise HTTPException(422, "Modellname zu lang")
    if isinstance(model, str) and not model.strip():
        model = None
    prompt = payload.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        raise HTTPException(422, "Nutzerhinweis ungültig")
    if isinstance(prompt, str) and len(prompt) > 2000:
        raise HTTPException(422, "Nutzerhinweis zu lang")
    try:
        snapshot = _store().get_snapshot_by_id(snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "Gespeichertes Transkript nicht gefunden")
        binding = snapshot.get("binding")
        if binding is not None:
            require_current_binding(binding)
        elif str(snapshot.get("chat_id", "")).startswith("agent:"):
            raise HTTPException(409, "Transkript gehört nicht zum gewählten Kontext")
        raw_messages = snapshot.get("messages")
        if not isinstance(raw_messages, list) or len(raw_messages) > 1000:
            raise ChatSessionStoreError("invalid transcript messages")
        for message in raw_messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
                raise ChatSessionStoreError("invalid transcript role")
            content = message.get("content")
            if not isinstance(content, str) or len(content) > 1_000_000:
                raise ChatSessionStoreError("invalid transcript content")
        zettel = _resume_zettel(raw_messages, prompt)
    except ProfileUnavailable:
        raise HTTPException(409, "Gespeicherte Profilbindung nicht mehr verifiziert")
    except (ChatSessionStoreError, OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Gespeichertes Transkript nicht lesbar")
    from .worker_status_adapter import (
        WorkerActionRejected, WorkerStatusUnavailable, update_worker_configuration,
        start_worker, _request_control_api,
    )
    try:
        source = await asyncio.to_thread(
            _request_control_api, "GET", "system-slots", device_token=device_token)
        version = source.get("configuration_version") if isinstance(source, dict) else None
        if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version):
            raise WorkerStatusUnavailable("Konfigurationsversion nicht ermittelbar")
        changes = {"task_prompt": zettel}
        if model:
            changes["model"] = model
        await asyncio.to_thread(
            update_worker_configuration, worker_id, version, changes, device_token=device_token)
        start_result = await asyncio.to_thread(
            start_worker, worker_id, device_token=device_token, timeout=15.0)
    except WorkerActionRejected as exc:
        raise HTTPException(getattr(exc, "status_code", 409), str(exc))
    except WorkerStatusUnavailable as exc:
        raise HTTPException(getattr(exc, "status_code", 503), str(exc))
    except ValueError:
        raise HTTPException(400, "Ungültige Resume-Anfrage")
    except (ChatSessionStoreError, OSError):
        raise HTTPException(503, "Hintergrundworker-Steuerung nicht verfügbar")
    return {"ok": True, "action": "resume", "worker_id": worker_id, "snapshot_id": snapshot_id,
            "model": model, "start": start_result}
