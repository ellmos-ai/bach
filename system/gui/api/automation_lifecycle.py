# SPDX-License-Identifier: MIT
"""Device-authenticated CRUD, Scheduling, Calendar & Run Lifecycle API for #2329.

Delegates runtime storage to Ocean's `agent-library` (`AutomationLifecycleRegistry`)
via `hub._services.automation_agents_lifecycle.get_automation_lifecycle_registry`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from hub._services.automation_agents_lifecycle import get_automation_lifecycle_registry

router = APIRouter(prefix="/api/automations/lifecycle", tags=["automation-lifecycle"])


def _resolve_db_path():
    from gui import server

    return server.BACH_DB


def _get_registry():
    reg, provider = get_automation_lifecycle_registry(db_path=_resolve_db_path())
    return reg, provider


@router.get("")
async def list_lifecycle_entries(
    family: str | None = Query(None),
    state: str | None = Query(None),
    trigger: str | None = Query(None),
):
    reg, provider = _get_registry()
    entries = reg.list_entries(family=family, state=state, trigger=trigger)
    return {
        "ok": True,
        "provider": provider,
        "count": len(entries),
        "entries": entries,
    }


@router.post("")
async def register_lifecycle_entry(payload: dict[str, Any] = Body(...)):
    reg, provider = _get_registry()
    try:
        entry = reg.register_entry(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "provider": provider, "entry": entry}


@router.get("/runs")
async def list_lifecycle_runs(
    entry_id: str | None = Query(None),
    start_trigger: str | None = Query(None),
    group_by_trigger: bool = Query(False),
):
    reg, provider = _get_registry()
    try:
        runs = reg.list_runs(
            entry_id,
            start_trigger=start_trigger,
            group_by_trigger=group_by_trigger,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "provider": provider, "runs": runs}


@router.get("/{entry_id}")
async def get_lifecycle_entry(entry_id: str):
    reg, provider = _get_registry()
    try:
        entry = reg.get_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    bindings = reg.list_calendar_bindings(entry_id)
    return {"ok": True, "provider": provider, "entry": entry, "calendar_bindings": bindings}


@router.patch("/{entry_id}")
async def update_lifecycle_entry(entry_id: str, payload: dict[str, Any] = Body(...)):
    reg, provider = _get_registry()
    expected_fence = payload.get("expected_fence")
    patch = {k: v for k, v in payload.items() if k != "expected_fence"}
    try:
        entry = reg.update_entry(entry_id, patch, expected_fence=expected_fence)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "provider": provider, "entry": entry}


@router.delete("/{entry_id}")
async def delete_lifecycle_entry(entry_id: str, expected_fence: int | None = Query(None)):
    reg, provider = _get_registry()
    try:
        result = reg.delete_entry(entry_id, expected_fence=expected_fence)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"ok": True, "provider": provider, **result}


@router.post("/{entry_id}/schedule")
async def schedule_lifecycle_entry(entry_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    reg, provider = _get_registry()
    try:
        entry = reg.schedule_entry(
            entry_id,
            schedule_spec=payload.get("schedule_spec"),
            timezone=payload.get("timezone"),
            expected_fence=payload.get("expected_fence"),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "provider": provider, "entry": entry}


@router.post("/{entry_id}/start")
async def start_lifecycle_entry(entry_id: str, payload: dict[str, Any] = Body(...)):
    reg, provider = _get_registry()
    try:
        entry = reg.trigger_start(
            entry_id,
            start_trigger=str(payload.get("start_trigger") or ""),
            dedup_key=str(payload.get("dedup_key") or ""),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "provider": provider, "entry": entry}


@router.post("/{entry_id}/stop")
async def stop_lifecycle_entry(entry_id: str, payload: dict[str, Any] = Body(...)):
    reg, provider = _get_registry()
    if "expected_fence" not in payload or not isinstance(payload["expected_fence"], int):
        raise HTTPException(400, "expected_fence (int) erforderlich")
    try:
        entry = reg.stop_entry(
            entry_id,
            expected_fence=payload["expected_fence"],
            status=str(payload.get("status") or "stopped"),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"ok": True, "provider": provider, "entry": entry}


@router.get("/{entry_id}/calendar")
async def list_lifecycle_calendar(entry_id: str, status: str | None = Query(None)):
    reg, provider = _get_registry()
    try:
        reg.get_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    bindings = reg.list_calendar_bindings(entry_id, status=status)
    return {"ok": True, "provider": provider, "calendar_bindings": bindings}


@router.post("/{entry_id}/calendar")
async def bind_lifecycle_calendar(entry_id: str, payload: dict[str, Any] = Body(...)):
    reg, provider = _get_registry()
    try:
        binding = reg.bind_calendar_event(
            entry_id,
            calendar_event_id=str(payload.get("calendar_event_id") or ""),
            scheduled_at=str(payload.get("scheduled_at") or ""),
            sync_direction=str(payload.get("sync_direction") or "bidirectional"),
            external_etag=payload.get("external_etag"),
            confirm_schedule=bool(payload.get("confirm_schedule", True)),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "provider": provider, "binding": binding}


@router.post("/{entry_id}/calendar/cancel")
async def cancel_lifecycle_calendar(entry_id: str, payload: dict[str, Any] = Body(...)):
    reg, provider = _get_registry()
    try:
        cancelled = reg.cancel_calendar_event(
            entry_id,
            calendar_event_id=payload.get("calendar_event_id"),
            binding_id=payload.get("binding_id"),
            source=str(payload.get("source") or "local"),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "provider": provider, "binding": cancelled}
