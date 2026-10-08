"""Typed task destinations from native slots and their blueprint instances.

Selecting a destination changes routing only. It never starts a worker or
materializes a template; canonical TaskLease acquisition remains authoritative.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import re
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/task-assignees", tags=["task-assignees"])


def project_targets(core: dict, blueprints: dict) -> dict:
    if blueprints.get("configuration_version") != core.get("configuration_version"):
        raise HTTPException(409, "Agentenkonfiguration inzwischen geändert; Auswahl neu laden")
    targets = []
    by_slot = {}
    for slot in core.get("agents", []):
        if slot.get("sequence_run_id"):
            continue  # Private execution slots belong to their admitted run.
        verified = slot.get("runtime_verified") is True
        enabled = slot.get("enabled") is True
        worker = slot.get("execution_kind") == "worker"
        live = verified and slot.get("living") is True
        tools = slot.get("allowed_tools")
        task_tool = slot.get("allow_tools") is not False and (tools is None or "task_manage" in tools)
        assignable = enabled and worker and live and task_tool
        reason = ("disabled" if not enabled else "not_task_worker" if not worker else
                  "task_tool_unavailable" if not task_tool else
                  "runtime_not_verified" if not verified else "worker_not_ready" if not live else "")
        target = {
            "id": "slot:" + slot["id"], "type": "system-slot", "name": slot["name"],
            "slot_id": slot["id"], "blueprint_id": slot.get("blueprint_id"),
            "blueprint_version": slot.get("blueprint_version"), "backend": slot.get("backend"),
            "model": slot.get("model"), "enabled": enabled, "living": slot.get("living"),
            "running": slot.get("running"), "runtime_verified": verified,
            "assignable": assignable, "reason": reason,
            "binding": {"assigned_slot": slot["id"], "assigned_to": str(slot.get("backend") or "").upper(),
                        "required_model": slot.get("model")},
        }
        by_slot[slot["id"]] = target
        targets.append(target)
    for bp in blueprints.get("templates", []) + blueprints.get("blueprints", []):
        if bp.get("kind") not in {"agent", "role"}:
            continue
        instance = bp.get("instance") or {}
        target = by_slot.get(instance.get("id"))
        # An old instance must not silently execute a newer blueprint revision.
        current = target is not None and target.get("blueprint_version") == bp.get("version")
        targets.append({
            "id": "blueprint:" + str(bp["id"]), "type": "blueprint", "name": bp.get("title") or bp["name"],
            "slot_id": target["slot_id"] if current else None, "blueprint_id": bp["id"],
            "blueprint_version": bp.get("version"), "backend": target.get("backend") if current else None,
            "model": target.get("model") if current else None, "enabled": target.get("enabled") if current else False,
            "living": target.get("living") if current else None, "running": target.get("running") if current else None,
            "runtime_verified": target.get("runtime_verified") if current else False,
            "assignable": target.get("assignable") if current else False,
            "reason": target["reason"] if current else "blueprint_requires_instance",
            "binding": dict(target["binding"]) if current else None,
        })
    return {"schema": "bach.task-assignees.v1", "source": "native_control_and_blueprints",
            "configuration_version": core["configuration_version"],
            "runtime_verified": bool(by_slot) and all(item["runtime_verified"] for item in by_slot.values()),
            "targets": targets}


@router.get("")
async def task_assignees():
    from .core_system_agents import _snapshot
    from .unified_api import list_agent_blueprints
    core = await asyncio.to_thread(_snapshot)
    blueprints = await list_agent_blueprints()
    return project_targets(core, blueprints)


def validate_assignment(payload: dict, existing: dict | None = None) -> str | None:
    """Validate a newly selected native destination without acquiring its task."""
    existing = existing or {}
    keys = {"assigned_slot", "assigned_to", "required_model"}
    changed = any(key in payload and (payload[key] or None) != (existing.get(key) or None) for key in keys)
    ident = payload.get("assigned_slot", existing.get("assigned_slot"))
    if not changed or not (ident or existing.get("assigned_slot")):
        return
    version = payload.get("assignment_configuration_version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version):
        raise HTTPException(400, "Gültige Konfigurationsversion für Zuweisungsänderung erforderlich")
    from .core_system_agents import _snapshot
    core = _snapshot()
    if version != core["configuration_version"]:
        raise HTTPException(409, "Agentenkonfiguration inzwischen geändert; Auswahl neu laden")
    if not ident:
        return version
    target = next((s for s in core["agents"] if s["id"] == ident), None)
    if (not target or target.get("sequence_run_id") or target.get("execution_kind") != "worker"
            or target.get("enabled") is not True or target.get("allow_tools") is False
            or target.get("runtime_verified") is not True or target.get("living") is not True
            or (target.get("allowed_tools") is not None and "task_manage" not in target["allowed_tools"])):
        raise HTTPException(422, "Kein verfügbarer Task-Steckplatz; Auswahl neu laden")
    model = payload.get("required_model", existing.get("required_model"))
    if model and model != target.get("model"):
        raise HTTPException(409, "Das benötigte Modell passt nicht zum ausgewählten Steckplatz")
    backend = payload.get("assigned_to", existing.get("assigned_to"))
    if backend and str(backend).casefold() not in {str(target.get("backend") or "").casefold(), ident.casefold()}:
        raise HTTPException(409, "Zuweisung und ausgewählter Steckplatz passen nicht zusammen")
    return version


@contextmanager
def assignment_write_guard(payload: dict, existing: dict | None = None):
    """Keep configuration CAS valid through the caller's canonical DB commit.

    Probe Control before taking the cross-process configuration lock. Calling
    the other service while holding its file lock would invert admission locks.
    No configuration revision is advanced by a task routing edit.
    """
    version = validate_assignment(payload, existing)
    if version is None:
        yield
        return
    from hub._services.chat.slots_config import worker_admission_transaction, core_system_agents_snapshot
    with worker_admission_transaction():
        if core_system_agents_snapshot()["configuration_version"] != version:
            raise HTTPException(409, "Agentenkonfiguration inzwischen geändert; Auswahl neu laden")
        yield
