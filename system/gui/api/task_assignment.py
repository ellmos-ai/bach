"""Typed task destinations from native slots and their blueprint instances.

Selecting a destination changes routing only. It never starts a worker or
materializes a template; canonical TaskLease acquisition remains authoritative.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/task-assignees", tags=["task-assignees"])


def _profile_configuration():
    """Read profiles and the authoritative CAS from the same untouched image.

    The general loader fills defaults and migrates versions in memory; those
    changes must not manufacture a conflict with an unchanged legacy file.
    """
    from hub._services.chat.slots_config import _resolve_path, _core_snapshot_from_bytes
    raw = _resolve_path().read_bytes()
    snapshot = _core_snapshot_from_bytes(raw)
    return json.loads(raw.decode("utf-8")), snapshot["configuration_version"]


def _profile_is_available(profile: dict) -> bool:
    status = profile.get("status")
    if not isinstance(status, str) or status not in {"idle", "completed", "running"}:
        return False
    expiry = profile.get("expires_at")
    if expiry is None or expiry == "":
        return True
    try:
        until = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        return until.tzinfo is not None and until > datetime.now(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return False


def dynamic_worker_snapshot(core: dict) -> dict:
    """Join configured profiles with authenticated observations at one CAS.

    Read Control outside the configuration transaction. Runtime progress is
    not authority; the existing global token includes profile configuration,
    lifecycle status and admission revisions and is rechecked after the probe.
    """
    from hub._services.chat.slots_config import (
        core_system_agents_snapshot, CORE_KNOWN_BACKENDS,
    )
    from .worker_status_adapter import read_worker_status, WorkerStatusUnavailable, WorkerActionRejected

    try:
        config, version = _profile_configuration()
        profiles = config.get("dynamic_workers", [])
        if not isinstance(profiles, list) or any(not isinstance(p, dict) for p in profiles):
            raise ValueError("Invalid worker profiles")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(503, "Workerprofil-Konfiguration nicht lesbar") from exc
    if version != core["configuration_version"]:
        raise HTTPException(409, "Agentenkonfiguration inzwischen geändert; Auswahl neu laden")
    ids = {s["id"] for s in core.get("agents", [])}
    for profile in profiles:
        ident = profile.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", ident) or ident in ids:
            raise HTTPException(503, "Workerprofil-Identität nicht eindeutig")
        grants = profile.get("allowed_tools")
        if grants is not None and (not isinstance(grants, list) or any(not isinstance(g, str) for g in grants)):
            raise HTTPException(503, "Workerprofil-Werkzeugrechte nicht lesbar")
        ids.add(ident)
    observed = {}
    if profiles:
        try:
            live = read_worker_status(device_token="")
            if live.get("availability") == "available" and live.get("source") == "authenticated_local_control_api":
                for item in live.get("workers", []):
                    if item["id"] in observed:
                        raise WorkerStatusUnavailable("Worker-ID mehrfach gemeldet")
                    observed[item["id"]] = item
        except (WorkerStatusUnavailable, WorkerActionRejected):
            observed = {}
    try:
        current_version = core_system_agents_snapshot()["configuration_version"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(503, "Workerprofil-Konfiguration nicht lesbar") from exc
    if current_version != version:
        raise HTTPException(409, "Agentenkonfiguration inzwischen geändert; Auswahl neu laden")
    slots = []
    for profile in profiles:
        current = observed.get(profile["id"], {})
        verified = (current.get("runtime_verified") is True
                    and isinstance(profile.get("backend"), str)
                    and profile.get("backend") in CORE_KNOWN_BACKENDS
                    and isinstance(profile.get("model"), str) and bool(profile["model"].strip())
                    and current.get("model") == profile.get("model")
                    and current.get("backend") == profile.get("backend"))
        available = _profile_is_available(profile)
        slots.append({
            "id": profile["id"], "name": profile.get("name") or profile["id"],
            "execution_kind": "worker", "_task_destination_type": "worker-profile",
            "backend": profile.get("backend"), "model": profile.get("model"),
            "enabled": available,
            "living": verified and available and current.get("status") in {"idle", "completed", "running"},
            "running": current.get("running") is True if verified else None,
            "runtime_verified": verified, "allow_tools": profile.get("allow_tools", True),
            "allowed_tools": profile.get("allowed_tools"), "sequence_run_id": profile.get("sequence_run_id"),
        })
    return {"configuration_version": version, "agents": slots}


def project_targets(core: dict, blueprints: dict, profiles: dict | None = None) -> dict:
    if blueprints.get("configuration_version") != core.get("configuration_version"):
        raise HTTPException(409, "Agentenkonfiguration inzwischen geändert; Auswahl neu laden")
    targets = []
    by_slot = {}
    if profiles is not None and profiles.get("configuration_version") != core["configuration_version"]:
        raise HTTPException(409, "Worker-Konfiguration inzwischen geändert; Auswahl neu laden")
    for slot in core.get("agents", []) + (profiles or {}).get("agents", []):
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
        kind = slot.get("_task_destination_type", "system-slot")
        target = {
            "id": ("worker:" if kind == "worker-profile" else "slot:") + slot["id"],
            "type": kind, "name": slot["name"],
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
    profiles = await asyncio.to_thread(dynamic_worker_snapshot, core)
    return project_targets(core, blueprints, profiles)


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
    if target is None:
        profiles = dynamic_worker_snapshot(core)
        target = next((s for s in profiles["agents"] if s["id"] == ident), None)
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
        # Time can expire a profile without changing a configuration byte.
        # Recheck that boundary under the same lock as the task commit.
        ident = payload.get("assigned_slot", (existing or {}).get("assigned_slot"))
        profiles = _profile_configuration()[0].get("dynamic_workers", [])
        profile = next((p for p in profiles if p.get("id") == ident), None)
        if profile is not None and not _profile_is_available(profile):
            raise HTTPException(422, "Workerprofil inzwischen nicht verfügbar; Auswahl neu laden")
        yield
