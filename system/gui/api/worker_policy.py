"""Device-authorized settings adapter; no worker starts or task acceptance."""
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Body, HTTPException, Request

from hub._services import worker_policy_settings as service

router = APIRouter(prefix="/api", tags=["worker-policy"])


def _db_path():
    from hub.bach_paths import BACH_DB
    return BACH_DB


def _actor(request):
    # Reuse the existing strict device check even when mounted independently.
    from .unified_api import _require_memory_device
    return "device:" + str(_require_memory_device(request))


async def _call(function, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, db_path=_db_path(), **kwargs)
    except service.PolicyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except service.PolicyUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Task nicht gefunden") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "Ungültige Worker-Regeln: " + str(exc)) from exc


@router.get("/system/worker-policy")
async def get_worker_policy(request: Request):
    _actor(request)
    return await _call(service.read_global_policy)


@router.put("/system/worker-policy")
async def put_worker_policy(request: Request, payload: dict = Body(...)):
    actor = _actor(request)
    return await _call(service.write_global_policy, payload, actor=actor)


@router.get("/tasks/{task_id}/worker-policy")
async def get_task_worker_policy(task_id: int, request: Request):
    _actor(request)
    return await _call(service.read_task_policy, task_id)


@router.put("/tasks/{task_id}/worker-policy")
async def put_task_worker_policy(task_id: int, request: Request, payload: dict = Body(...)):
    actor = _actor(request)
    return await _call(service.write_task_policy, task_id, payload, actor=actor)
