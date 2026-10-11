# SPDX-License-Identifier: MIT
"""Native model socket configuration, using the existing device and CAS gates."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, HTTPException, Request
from hub._services.chat import model_sockets as service

from .core_system_agents import _version

router = APIRouter(prefix="/api/system/model-sockets", tags=["model-sockets"])


async def _read():
    try:
        return await asyncio.to_thread(service.model_sockets_snapshot)
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "Modellsteckplatzkonfiguration nicht verifizierbar") from None


async def _write(request, payload, operation, *args, **kwargs):
    from .unified_api import _require_memory_device_token
    _require_memory_device_token(request)
    version = _version(payload)
    try:
        result = await asyncio.to_thread(operation, version, *args, **kwargs)
    except KeyError:
        raise HTTPException(404, "Agentenslotbindung nicht vorhanden") from None
    except RuntimeError as exc:
        if str(exc) == "configuration_version_conflict":
            raise HTTPException(409, "Konfiguration wurde inzwischen geändert") from None
        raise HTTPException(503, "Modellsteckplatzänderung nicht bestätigt") from None
    except ValueError:
        raise HTTPException(400, "Ungültige Modellsteckplatzänderung") from None
    except (OSError, TypeError):
        raise HTTPException(503, "Modellsteckplatzänderung nicht bestätigt") from None
    return {**result, "ack": {"configuration_saved": True, "worker_started": False,
                              "runtime_verified": False}}


@router.get("")
async def list_model_sockets():
    return await _read()


@router.get("/catalog")
async def local_model_catalog():
    from hub._services.chat.local_model_catalog import local_model_catalog as catalog
    try:
        return await asyncio.to_thread(catalog)
    except (OSError, ValueError, TypeError):
        raise HTTPException(503, "Lokaler Modellkatalog nicht verifizierbar") from None


@router.post("/migrate")
async def migrate_model_sockets(request: Request, payload: dict = Body(...)):
    return await _write(request, payload, service.migrate_model_sockets)


@router.put("")
async def configure_model_socket(request: Request, payload: dict = Body(...)):
    return await _write(request, payload, service.configure_model_socket, payload.get("changes"))


@router.put("/bindings/{agent_id}/{socket_id}")
async def bind_model_agent(agent_id: str, socket_id: str, request: Request, payload: dict = Body(...)):
    return await _write(request, payload, service.bind_model_agent, agent_id, socket_id, payload.get("changes"))


@router.delete("/bindings/{binding_id}")
async def remove_model_binding(binding_id: str, request: Request, payload: dict = Body(...)):
    return await _write(request, payload, service.remove_model_binding, binding_id)
