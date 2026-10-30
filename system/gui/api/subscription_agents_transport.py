# SPDX-License-Identifier: MIT
"""Authenticated HTTP transport for the existing subscription-agent composer."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading

from fastapi import APIRouter, HTTPException, Request

from hub._services.subscription_agents_composer import (
    MAX_REQUEST_BYTES,
    SubscriptionAgentsComposer,
)
from hub._services.subscription_agents_store import (
    create_subscription_agent,
    create_subscription_prompt,
    delete_subscription_agent,
    delete_subscription_prompt,
    duplicate_subscription_agent,
    ensure_subscription_agent_schema,
    get_subscription_agent,
    get_subscription_prompt,
    list_subscription_agents,
    list_subscription_prompts,
    record_subscription_agent_heartbeat,
    stop_subscription_agent,
    update_subscription_agent,
    update_subscription_prompt,
)
from hub.bach_paths import BACH_DB


router = APIRouter(
    prefix="/api/agent-studio/subscription-agents",
    tags=["subscription-agents"],
)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_field")
        result[key] = value
    return result


def _reject_constant(_value: str):
    raise ValueError("nonstandard_json_constant")


async def _read_request_object(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise _error(415, "json_required", "Der Request muss application/json verwenden.")

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_REQUEST_BYTES:
                raise _error(413, "request_too_large", "Der Request überschreitet das Composer-Limit.")
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _error(400, "body_unavailable", "Der Request-Body konnte nicht sicher gelesen werden.") from None

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise _error(400, "invalid_json", "Der Request enthält kein gültiges UTF-8-JSON mit eindeutigen Feldern.") from None
    if not isinstance(payload, dict):
        raise _error(422, "object_required", "Der Request muss ein JSON-Objekt enthalten.")
    return payload


async def _authorize_active_device(request: Request) -> None:
    """Use the existing read-only device-token check before touching the body."""
    try:
        from gui.api.unified_api import _require_memory_device

        await asyncio.to_thread(_require_memory_device, request)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise _error(401, "device_auth_required", "Eine aktive Geräteanmeldung ist erforderlich.") from None
        if exc.status_code == 403:
            raise _error(403, "device_auth_invalid", "Die Geräteanmeldung ist ungültig oder widerrufen.") from None
        raise _error(503, "device_auth_unavailable", "Die Geräteprüfung ist derzeit nicht verfügbar.") from None
    except Exception:
        raise _error(503, "device_auth_unavailable", "Die Geräteprüfung ist derzeit nicht verfügbar.") from None


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def _store_conn() -> sqlite3.Connection:
    """Open a busy-timeout connection and ensure the prompt-agent schema lazily."""
    global _SCHEMA_READY

    conn = sqlite3.connect(str(BACH_DB), timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    if not _SCHEMA_READY:
        with _SCHEMA_LOCK:
            if not _SCHEMA_READY:
                ensure_subscription_agent_schema(conn)
                _SCHEMA_READY = True
    return conn


def _run_store(fn, *args, **kwargs):
    """Run one store call on a short-lived connection inside the worker thread."""
    conn = _store_conn()
    try:
        return fn(conn, *args, **kwargs)
    finally:
        conn.close()


@router.post("/compose")
async def compose_subscription_agent_preview(request: Request):
    """Return a bounded preview only to an active registered device."""
    await _authorize_active_device(request)
    payload = await _read_request_object(request)

    try:
        composer = SubscriptionAgentsComposer()
        return await asyncio.to_thread(composer.compose, payload)
    except ValueError:
        raise _error(422, "compose_rejected", "Die Vorschau konnte aus den angegebenen Quellen nicht erstellt werden.") from None
    except Exception:
        raise _error(503, "compose_unavailable", "Die Vorschauquelle ist derzeit nicht verfügbar.") from None


@router.get("/list")
async def list_subscription_agent_records(request: Request):
    """Return the stored subscription prompt agents visible to this device."""
    await _authorize_active_device(request)
    try:
        agents = await asyncio.to_thread(_run_store, list_subscription_agents)
    except Exception:
        raise _error(503, "store_unavailable", "Die Agentenliste ist derzeit nicht verfügbar.") from None
    return {"agents": agents, "count": len(agents)}


@router.get("/prompts")
async def list_subscription_prompt_records(request: Request):
    """Return the stored subscription prompt agent prompts."""
    await _authorize_active_device(request)
    try:
        prompts = await asyncio.to_thread(_run_store, list_subscription_prompts)
    except Exception:
        raise _error(503, "store_unavailable", "Die Promptliste ist derzeit nicht verfügbar.") from None
    return {"prompts": prompts, "count": len(prompts)}


@router.post("/prompts")
async def create_subscription_prompt_record(request: Request):
    """Create one prompt record and couple it to its agent."""
    await _authorize_active_device(request)
    payload = await _read_request_object(request)
    try:
        prompt = await asyncio.to_thread(_run_store, create_subscription_prompt, payload)
    except ValueError:
        raise _error(422, "prompt_rejected", "Der Prompt wurde von der Ablage abgelehnt.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Promptablage ist derzeit nicht verfügbar.") from None
    return _unique_object([("prompt", prompt)])


@router.put("/prompts/{prompt_id}")
async def update_subscription_prompt_record(prompt_id: str, request: Request):
    """Update one stored prompt and its coupled agent fields."""
    await _authorize_active_device(request)
    payload = await _read_request_object(request)
    try:
        prompt = await asyncio.to_thread(_run_store, update_subscription_prompt, prompt_id, payload)
    except ValueError:
        raise _error(422, "prompt_rejected", "Der Prompt wurde von der Ablage abgelehnt.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Promptablage ist derzeit nicht verfügbar.") from None
    return _unique_object([("prompt", prompt)])


@router.delete("/prompts/{prompt_id}")
async def delete_subscription_prompt_record(prompt_id: str, request: Request):
    """Delete one prompt together with its coupled agent."""
    await _authorize_active_device(request)
    try:
        removed = await asyncio.to_thread(_run_store, delete_subscription_prompt, prompt_id)
    except Exception:
        raise _error(503, "store_unavailable", "Die Promptablage ist derzeit nicht verfügbar.") from None
    if not removed:
        raise _error(404, "prompt_not_found", "Der Prompt wurde nicht gefunden.")
    return {"deleted": True, "prompt_id": prompt_id, "agent_deleted": True}


@router.post("/create")
async def create_subscription_agent_record(request: Request):
    """Create one subscription prompt agent."""
    await _authorize_active_device(request)
    payload = await _read_request_object(request)
    try:
        agent = await asyncio.to_thread(_run_store, create_subscription_agent, payload)
    except ValueError:
        raise _error(422, "agent_rejected", "Der Agent wurde von der Ablage abgelehnt.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Agentenablage ist derzeit nicht verfügbar.") from None
    return _unique_object([("agent", agent)])


@router.put("/{agent_id}")
async def update_subscription_agent_record(agent_id: str, request: Request):
    """Update one stored subscription prompt agent."""
    await _authorize_active_device(request)
    payload = await _read_request_object(request)
    try:
        agent = await asyncio.to_thread(_run_store, update_subscription_agent, agent_id, payload)
    except ValueError:
        raise _error(422, "agent_rejected", "Der Agent wurde von der Ablage abgelehnt.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Agentenablage ist derzeit nicht verfügbar.") from None
    return _unique_object([("agent", agent)])


@router.delete("/{agent_id}")
async def delete_subscription_agent_record(agent_id: str, request: Request):
    """Delete one agent together with its coupled prompt."""
    await _authorize_active_device(request)
    try:
        removed = await asyncio.to_thread(_run_store, delete_subscription_agent, agent_id)
    except (LookupError, ValueError):
        raise _error(404, "agent_not_found", "Der Agent wurde nicht gefunden.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Agentenablage ist derzeit nicht verfügbar.") from None
    if not removed:
        raise _error(404, "agent_not_found", "Der Agent wurde nicht gefunden.")
    return {"deleted": True, "agent_id": agent_id, "prompt_deleted": True}


@router.post("/{agent_id}/duplicate")
async def duplicate_subscription_agent_record(agent_id: str, request: Request):
    """Copy one agent including its coupled prompt text."""
    await _authorize_active_device(request)
    payload = await _read_request_object(request)
    raw_name = payload.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        raise _error(422, "agent_rejected", "Der Name muss Text sein.")
    try:
        agent = await asyncio.to_thread(_run_store, duplicate_subscription_agent, agent_id, name=raw_name)
    except ValueError:
        raise _error(422, "agent_rejected", "Der Agent konnte nicht dupliziert werden.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Agentenablage ist derzeit nicht verfügbar.") from None
    return _unique_object([("agent", agent)])


@router.post("/{agent_id}/heartbeat")
async def heartbeat_subscription_agent_record(agent_id: str, request: Request):
    """Refresh the expiry window of one running agent."""
    await _authorize_active_device(request)
    payload = await _read_request_object(request)
    ttl_seconds = payload.get("ttl_seconds")
    if ttl_seconds is not None and (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int)):
        raise _error(422, "agent_rejected", "ttl_seconds muss eine ganze Zahl sein.")
    kwargs = {} if ttl_seconds is None else {"ttl_seconds": ttl_seconds}
    try:
        agent = await asyncio.to_thread(_run_store, record_subscription_agent_heartbeat, agent_id, **kwargs)
    except ValueError:
        raise _error(422, "agent_rejected", "Der Agent hat keinen gültigen Lebenslauf mehr.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Agentenablage ist derzeit nicht verfügbar.") from None
    return _unique_object([("agent", agent)])


@router.post("/{agent_id}/stop")
async def stop_subscription_agent_record(agent_id: str, request: Request):
    """Stop one agent and end its expiry window (auto-logout)."""
    await _authorize_active_device(request)
    try:
        agent = await asyncio.to_thread(_run_store, stop_subscription_agent, agent_id)
    except ValueError:
        raise _error(404, "agent_not_found", "Der Agent wurde nicht gefunden.") from None
    except Exception:
        raise _error(503, "store_unavailable", "Die Agentenablage ist derzeit nicht verfügbar.") from None
    return _unique_object([("agent", agent)])
