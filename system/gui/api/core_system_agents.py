"""Device-authenticated configuration and live state of system slots."""
from __future__ import annotations

from typing import Any
import hashlib
import json

import asyncio
from fastapi import APIRouter, Body, HTTPException, Request
from .worker_status_adapter import WorkerActionRejected

from hub._services.chat.slots_config import (
    CORE_SYSTEM_AGENT_IDS,
    change_core_system_agent,
    core_system_agents_snapshot,
    create_system_slot,
    delete_system_slot,
    get_system_slot,
)

router = APIRouter(prefix="/api/system/core-agents", tags=["core-system-agents"])
prompt_router = APIRouter(prefix="/api/system/core-prompts", tags=["core-prompts"])


def _snapshot() -> dict[str, Any]:
    try:
        result = core_system_agents_snapshot()
    except (OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="System-Agentenkonfiguration nicht lesbar")
    try:
        from .worker_status_adapter import _request_control_api
        live = _request_control_api("GET", "system-slots", device_token="", timeout=3)
        if (live.get("configuration_version") == result["configuration_version"]
                and isinstance(live.get("agents"), list)):
            by_id = {item["id"]: item for item in live["agents"] if isinstance(item, dict) and "id" in item}
            fields = ("living", "running", "runtime_verified", "runtime_reason_code", "status",
                      "current_tool", "tool_round", "execution", "task_id")
            for agent in result["agents"]:
                current = by_id.get(agent["id"], {})
                agent.update({key: current[key] for key in fields if key in current})
    except Exception:
        # Missing runtime evidence must remain unknown, never a Ready badge.
        pass
    result["blueprints"] = [
        {
            "blueprint_id": "system:" + agent["id"],
            "technical_agent_id": agent["id"],
            "name": agent["name"],
            "icon": agent["icon"],
            "source": "core_slots_config",
            "is_system": True,
            "is_template": True,
            "editable": True,
            "deletable": agent["deletable"],
            "configured_model": agent["model"],
            "configured_mode": agent["mode"],
            "runtime_state": agent["status"] if agent.get("runtime_verified") else "unknown",
        }
        for agent in result["agents"]
    ]
    return result


def _version(payload: dict[str, Any]) -> str:
    value = payload.get("configuration_version")
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise HTTPException(status_code=400, detail="Gültige Konfigurationsversion erforderlich")
    return value


def _change(slot_id: str, payload: dict[str, Any], *, reset: bool) -> dict[str, Any]:
    if not get_system_slot(slot_id):
        raise HTTPException(status_code=404, detail="Unbekannte System-Agenten-ID")
    try:
        change_core_system_agent(
            slot_id, _version(payload), payload.get("changes"),
            reset=reset,
        )
        result = _snapshot()
        result["ack"] = {
            "technical_agent_id": slot_id,
            "configuration_saved": True,
            "worker_started": False,
            "runtime_verified": False,
        }
        return result
    except RuntimeError as exc:
        if str(exc) == "configuration_version_conflict":
            raise HTTPException(status_code=409, detail="Konfiguration wurde inzwischen geändert")
        raise HTTPException(status_code=503, detail="Konfiguration konnte nicht bestätigt werden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige System-Agentenkonfiguration")
    except OSError:
        raise HTTPException(status_code=503, detail="Konfiguration konnte nicht gespeichert werden")


@router.get("")
async def list_core_system_agents():
    return await asyncio.to_thread(_snapshot)


@router.get("/timeline")
async def system_agent_timeline():
    """Real session/task events from the authenticated live Control service."""
    from .worker_status_adapter import _request_control_api, WorkerStatusUnavailable
    try:
        upstream = await asyncio.to_thread(_request_control_api, "GET", "activity",
            device_token="", params={"limit": 50}, timeout=5)
        if upstream.get("ok") is not True or not isinstance(upstream.get("history"), list):
            raise ValueError("Aktivitätsquelle nicht bestätigt")
        fields = ("id", "timestamp", "source", "activity", "status", "event", "task_id",
                  "slot_id", "session_id", "assignment_id", "backend_id", "model_id", "task_title")
        events = [{key: item[key] for key in fields if key in item}
                  for item in upstream["history"] if isinstance(item, dict)]
        return {"schema": "bach.agent-timeline.v1", "source": "control_activity", "events": events}
    except (WorkerStatusUnavailable, WorkerActionRejected, ValueError):
        raise HTTPException(503, "Timeline-Quelle derzeit nicht verfügbar")


@router.post("")
async def add_core_system_agent(payload: dict[str, Any] = Body(...)):
    try:
        result = create_system_slot(payload.get("changes", {}), _version(payload),
                                    preset=payload.get("preset", "assistant"))
        return {**await asyncio.to_thread(_snapshot), "ack": {
            "technical_agent_id": result["slot_id"], "configuration_saved": True,
            "worker_started": False}}
    except RuntimeError:
        raise HTTPException(409, "Konfiguration wurde inzwischen geändert")
    except (ValueError, OSError):
        raise HTTPException(400, "Steckplatz konnte nicht angelegt werden")


@router.put("/{slot_id}")
async def save_core_system_agent(slot_id: str, payload: dict[str, Any] = Body(...)):
    return await asyncio.to_thread(_change, slot_id, payload, reset=False)


@router.post("/{slot_id}/reset")
async def reset_core_system_agent(slot_id: str, payload: dict[str, Any] = Body(...)):
    return await asyncio.to_thread(_change, slot_id, payload, reset=True)


@router.post("/{slot_id}/toggle")
async def toggle_core_system_agent(slot_id: str, request: Request, payload: dict[str, Any] = Body(...)):
    """Versioned desired state, followed by a real controller action."""
    current = get_system_slot(slot_id)
    if not current:
        raise HTTPException(status_code=404, detail="Unbekannte System-Agenten-ID")
    enabled = payload.get("enabled")
    if type(enabled) is not bool:
        raise HTTPException(400, "Gewünschter Schalterzustand erforderlich")
    try:
        from .unified_api import _require_memory_device_token
        from .worker_status_adapter import worker_action, start_worker, read_worker_status
        token = _require_memory_device_token(request)
        change_core_system_agent(slot_id, _version(payload), {"enabled": enabled})
        action = None
        worker_slot = slot_id == "buddha_always_on" or current.get("execution_kind") == "worker"
        if worker_slot:
            if enabled:
                observed = await asyncio.to_thread(read_worker_status, device_token=token)
                worker = next((item for item in observed["workers"] if item["id"] == slot_id), {})
                if worker.get("status") == "running":
                    action = {"ok": True, "action": "already_running", "worker": worker}
                else:
                    action = await asyncio.to_thread(start_worker, slot_id, device_token=token)
            else:
                action = await asyncio.to_thread(worker_action, "pause", {"id": slot_id}, device_token=token)
        result = await asyncio.to_thread(_snapshot)
        result["ack"] = {
            "technical_agent_id": slot_id,
            "enabled": enabled,
            "configuration_saved": True,
            "controller_action": action,
        }
        return result
    except WorkerActionRejected as exc:
        raise HTTPException(exc.status_code, str(exc))
    except RuntimeError:
        raise HTTPException(409, "Konfiguration wurde inzwischen geändert")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Schalter gespeichert; Ausführungszustand nicht bestätigt. Status neu prüfen.")




async def _control_prompt_payload(endpoint: str = "prompts", body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the live typed Controller from its verified fixed loopback origin."""
    import httpx
    from gui import server as gui_server

    base = gui_server._chat_control_base_url()
    authorization = gui_server.get_control_api_auth_header()
    if not base or not authorization:
        raise HTTPException(status_code=503, detail="Control-Promptquelle nicht verbunden")
    headers = {"authorization": authorization}
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            status = await client.get(base + "/status", headers=headers)
            try:
                identity = status.json()
            except ValueError:
                identity = None
            if status.status_code != 200 or not gui_server._chat_control_payload_ready(identity):
                raise HTTPException(status_code=503, detail="Control-Identität nicht bestätigt")
            if body is None:
                response = await client.get(base + "/prompts", headers=headers)
            else:
                response = await client.post(base + "/" + endpoint, headers=headers, json=body)
            if response.status_code == 409:
                raise HTTPException(status_code=409, detail="Control-Konfiguration inzwischen geändert")
            if response.status_code != 200:
                raise HTTPException(status_code=503, detail="Control-Promptantwort nicht verfügbar")
            payload = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Control-Promptquelle nicht erreichbar")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise HTTPException(status_code=503, detail="Control-Promptantwort ungültig")
    return payload


def _project_control_prompts(payload: dict[str, Any]) -> dict[str, Any]:
    version = payload.get("configuration_version")
    source_version = payload.get("source_version")
    templates = payload.get("templates")
    if not isinstance(templates, dict):
        raise HTTPException(status_code=503, detail="Control-Promptquelle nicht verfügbar")
    mutation_supported = (isinstance(version, str) and len(version) == 64 and
                          isinstance(source_version, str) and len(source_version) == 64)
    system = templates.get("system_default")
    roles = templates.get("roles")
    if not isinstance(system, dict) or not isinstance(roles, dict):
        raise HTTPException(status_code=503, detail="Control-Promptschema ungültig")
    records = {"system_default": system}
    records.update({"role_" + str(key): value for key, value in roles.items()})
    prompts = {}
    for key, item in records.items():
        if (not isinstance(item, dict) or
                not isinstance(item.get("text"), str) or
                not isinstance(item.get("default"), str) or
                not isinstance(item.get("is_custom"), bool)):
            raise HTTPException(status_code=503, detail="Control-Promptfeld ungültig")
        prompts[key] = {
            "key": key, "effective": item["text"],
            "default": item["default"], "is_custom": item["is_custom"],
        }
    if not mutation_supported:
        defaults = {key: item["default"] for key, item in prompts.items()}
        source_version = hashlib.sha256(json.dumps(
            defaults, sort_keys=True, ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
    return {
        "schema": "bach.core-prompts.v1",
        "configuration_version": version if mutation_supported else None,
        "source_version": source_version,
        "mutation_supported": mutation_supported,
        "source": ("versioned_control_config" if mutation_supported else
                   "in_memory_defaults" if payload.get("source") == "in_memory_defaults" else
                   "legacy_unversioned"),
        "prompts": prompts,
    }


@prompt_router.get("")
async def list_core_prompts():
    return _project_control_prompts(await _control_prompt_payload())


async def _change_prompt(key: str, payload: dict[str, Any], *, reset: bool) -> dict[str, Any]:
    before = _project_control_prompts(await _control_prompt_payload())
    if key not in before["prompts"]:
        raise HTTPException(status_code=404, detail="Unbekannte Prompt-ID")
    if not before["mutation_supported"]:
        raise HTTPException(status_code=503, detail="Control unterstützt noch keinen versionierten Prompt-Write")
    version = _version(payload)
    if version != before["configuration_version"]:
        raise HTTPException(status_code=409, detail="Control-Konfiguration inzwischen geändert")
    if reset:
        if payload.get("text") is not None:
            raise HTTPException(status_code=400, detail="Reset nimmt keinen Prompttext an")
        endpoint = "prompts/reset"
        upstream = {"key": key, "configuration_version": version}
    else:
        value = payload.get("text")
        if not isinstance(value, str) or not value.strip() or len(value) > 50000 or "\x00" in value:
            raise HTTPException(status_code=400, detail="Ungültiger Prompttext")
        endpoint = "prompts"
        upstream = {"key": key, "text": value, "configuration_version": version}
    await _control_prompt_payload(endpoint, upstream)
    result = _project_control_prompts(await _control_prompt_payload())
    item = result["prompts"].get(key)
    if not item or (reset and (item["is_custom"] or item["effective"] != item["default"])) or (
            not reset and (item["effective"] != value or not item["is_custom"])):
        raise HTTPException(status_code=503, detail="Control-Readback bestätigt Änderung nicht")
    result["ack"] = {
        "key": key, "configuration_saved": True,
        "worker_started": False, "source": "live_chat_control",
    }
    return result


@prompt_router.put("/{key}")
async def save_core_prompt(key: str, payload: dict[str, Any] = Body(...)):
    return await _change_prompt(key, payload, reset=False)


@prompt_router.post("/{key}/reset")
async def reset_core_prompt(key: str, payload: dict[str, Any] = Body(...)):
    return await _change_prompt(key, payload, reset=True)


@router.delete("/{slot_id}")
async def protect_core_system_agent(slot_id: str, payload: dict[str, Any] = Body(...)):
    if not get_system_slot(slot_id):
        raise HTTPException(status_code=404, detail="Unbekannte System-Agenten-ID")
    if slot_id in CORE_SYSTEM_AGENT_IDS:
        raise HTTPException(status_code=409, detail="Feste System-Agenten können nicht gelöscht werden")
    current = next(item for item in (await asyncio.to_thread(_snapshot))["agents"] if item["id"] == slot_id)
    if not current.get("runtime_verified") or current.get("running") or (
            current.get("execution") and not current["execution"].get("terminal")):
        raise HTTPException(409, "Steckplatz erst nach bestätigtem Laufende löschen")
    try:
        delete_system_slot(slot_id, _version(payload))
        return await asyncio.to_thread(_snapshot)
    except RuntimeError:
        raise HTTPException(409, "Konfiguration wurde inzwischen geändert")
    except ValueError:
        raise HTTPException(400, "Steckplatz konnte nicht gelöscht werden")
    except OSError:
        raise HTTPException(503, "Konfiguration konnte nicht gespeichert werden")
