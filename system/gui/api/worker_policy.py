"""Device-authorized settings adapter; no worker starts or task acceptance."""
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Body, HTTPException, Request, Query

from hub._services import task_lease_settings as lease_settings
from hub._services import worker_policy_settings as service
from hub._services import worker_review_identity as identities

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
    except PermissionError as exc:
        raise HTTPException(403, "Gesonderte Operatorberechtigung erforderlich") from exc
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
    return await _call(service.write_global_policy, payload, actor=actor,
                       operator_token=request.headers.get("X-BACH-Result-Operator", ""))


@router.get("/system/workers/{worker_id}/selection-preview")
async def get_worker_selection_preview(worker_id: str, request: Request,
                                       limit: int = Query(50, ge=1, le=100),
                                       offset: int = Query(0, ge=0, le=100_000)):
    from .unified_api import _require_memory_device_token
    from .worker_status_adapter import (
        WorkerActionRejected, WorkerStatusUnavailable, read_worker_selection_preview,
    )
    token = _require_memory_device_token(request)
    try:
        return await asyncio.to_thread(read_worker_selection_preview, worker_id,
            device_token=token, limit=limit, offset=offset)
    except WorkerActionRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except WorkerStatusUnavailable as exc:
        raise HTTPException(503, "Auswahlvorschau nicht bestätigt") from exc


@router.get("/system/worker-model-principals")
async def get_worker_model_principals(request: Request):
    _actor(request)
    return await _call(identities.read_model_bindings)


@router.put("/system/worker-model-principals")
async def put_worker_model_principals(request: Request, payload: dict = Body(...)):
    _actor(request)
    return await _call(identities.write_model_bindings, payload,
                       operator_token=request.headers.get("X-BACH-Result-Operator", ""))


@router.get("/system/task-lease-settings")
async def get_task_lease_settings(request: Request):
    _actor(request)
    return await _call(lease_settings.read_setting)


@router.put("/system/task-lease-settings")
async def put_task_lease_settings(request: Request, payload: dict = Body(...)):
    actor = _actor(request)
    return await _call(lease_settings.write_setting, payload, actor=actor)


@router.get("/tasks/{task_id}/worker-policy")
async def get_task_worker_policy(task_id: int, request: Request):
    _actor(request)
    return await _call(service.read_task_policy, task_id)


@router.put("/tasks/{task_id}/worker-policy")
async def put_task_worker_policy(task_id: int, request: Request, payload: dict = Body(...)):
    actor = _actor(request)
    return await _call(service.write_task_policy, task_id, payload, actor=actor)
