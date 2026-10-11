# SPDX-License-Identifier: MIT
"""Authenticated HTTP transport for the existing subscription-agent composer."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request

from hub._services.subscription_agents_composer import (
    MAX_REQUEST_BYTES,
    SubscriptionAgentsComposer,
)


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
