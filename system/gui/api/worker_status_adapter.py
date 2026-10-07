"""Authenticated adapter for BACH Control API worker profiles and actions.

The browser authenticates with a registered device token at the GUI. This
adapter forwards that verified, device-scoped token only to the local Control
API loopback hop and returns a small, secret-free worker projection.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx


class WorkerStatusUnavailable(RuntimeError):
    """The local Control API did not return a valid live worker snapshot."""


class WorkerActionRejected(RuntimeError):
    """A Control API worker action was not accepted or acknowledged."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_RUN_ID = re.compile(r"^[0-9a-f]{32}$")
_TOOL_ROUND_ACTIVITY = re.compile(r"^Tool \[(\d+)\]:")
_MAX_RESPONSE_BYTES = 2_000_000
_SAFE_TEXT_FIELDS = (
    "name", "backend", "model", "resolved_model", "mode", "sub_mode", "role_id", "status", "pause_basis",
    "current_activity", "created_at", "expires_at",
)
_NUMERIC_FIELDS = ("max_tool_rounds", "pause_after", "pause_minutes", "max_experts")
_BOOL_FIELDS = ("auto_paused",)
_ALLOWED_CONTROL = {
    ("GET", "status"), ("GET", "auth/check"), ("GET", "workers"),
    ("GET", "models"), ("GET", "readiness"),
    ("POST", "workers"), ("POST", "workers/run"),
    ("POST", "workers/toggle"), ("POST", "workers/stop"),
    ("POST", "workers/delete"),
    ("POST", "workers/handoff"),
    ("POST", "workers/decompose"),
    ("GET", "workers/configuration"), ("POST", "workers/configuration"),
}
_ACTIONS = {
    "create": ("POST", "workers"),
    "start": ("POST", "workers/run"),
    "pause": ("POST", "workers/toggle"),
    "stop": ("POST", "workers/stop"),
    "delete": ("POST", "workers/delete"),
}

_WORKER_SUB_MODES = (
    {"id": "hintergrund_worker", "label": "Hintergrundworker"},
    {"id": "task_worker", "label": "Taskworker"},
    {"id": "boss_routing", "label": "Bossrouting"},
    {"id": "expert_role", "label": "Expertenrolle"},
)
_BASE_ROLE_IDS = {"hintergrund_worker", "task_worker", "boss_routing"}
_EXPERT_ROLE_LABELS = {
    "task-divider": "Task-Divider · Aufgabenzerlegung",
    "ticket-master": "Ticket-Master · Triage",
    "entwickler": "Entwickler",
    "bueroassistent": "Büroassistent",
    "gesundheitsassistent": "Gesundheitsassistent",
    "steuer": "Steuer-Agent",
    "foerderplaner": "Förderplaner",
    "recherche": "Recherche-Experte",
    "psycho-berater": "Psycho-Berater",
    "haushaltsmanagement": "Haushaltsmanagement",
    "aboservice": "Vertrags- & Abo-Service",
    "data-analysis": "Datenanalyse & Reporting",
    "decision-briefing": "Entscheidungs-Briefing",
}


def _text(value: Any, *, limit: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    clean = "".join(ch for ch in value if ch >= " " or ch in "\t\n").strip()
    return clean[:limit] if clean else None


def _project_worker(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkerStatusUnavailable("Workerantwort enthält einen ungültigen Eintrag")
    worker_id = raw.get("id")
    if not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id):
        raise WorkerStatusUnavailable("Workerantwort enthält eine ungültige ID")

    item: dict[str, Any] = {"id": worker_id}
    for field in _SAFE_TEXT_FIELDS:
        value = _text(raw.get(field), limit=240 if field == "current_activity" else 160)
        if value is not None:
            item[field] = value

    for field in _NUMERIC_FIELDS:
        value = raw.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            item[field] = value

    for field in _BOOL_FIELDS:
        value = raw.get(field)
        if isinstance(value, bool):
            item[field] = value

    # ChatRuntime writes this exact activity string after each real tool round.
    # Project only the number; never infer progress from a configured limit or
    # from an old activity string on an idle/paused profile.
    activity = item.get("current_activity", "")
    round_match = _TOOL_ROUND_ACTIVITY.match(activity)
    if raw.get("status") == "running" and round_match:
        item["tool_round"] = int(round_match.group(1))

    task_id = raw.get("task_id")
    if isinstance(task_id, int) and not isinstance(task_id, bool):
        item["task_id"] = task_id
    generation = raw.get("generation")
    if isinstance(generation, str) and _RUN_ID.fullmatch(generation):
        item["generation"] = generation
    capabilities = raw.get("action_capabilities")
    if isinstance(capabilities, dict):
        item["action_capabilities"] = {
            name: capabilities.get(name) is True for name in ("handoff", "decompose")
        }
    receipt = _project_handoff_receipt(raw.get("handoff_receipt"), worker_id)
    if receipt is not None:
        item["handoff_receipt"] = receipt
    binding = _project_task_action_binding(raw.get("task_action_binding"))
    if binding is not None:
        item["task_action_binding"] = binding
    receipt = _project_task_action_receipt(raw.get("task_action_receipt"), worker_id)
    if receipt is not None:
        item["task_action_receipt"] = receipt
    return item


def _project_handoff_receipt(raw: Any, worker_id: str) -> dict[str, Any] | None:
    if (not isinstance(raw, dict) or raw.get("kind") != "worker-handoff"
            or raw.get("worker_id") != worker_id
            or raw.get("state") not in {"pending", "running", "confirmed", "error", "cancelled"}):
        return None
    for field in ("generation", "request_id"):
        if not isinstance(raw.get(field), str) or not _RUN_ID.fullmatch(raw[field]):
            return None
    if raw["state"] == "confirmed" and not _text(raw.get("confirmed_at"), limit=80):
        return None
    return {key: raw[key] for key in ("kind", "worker_id", "generation", "request_id", "state")} | {
        key: _text(raw.get(key), limit=80) for key in ("requested_at", "confirmed_at")
    }


def _project_task_action_binding(raw):
    if (not isinstance(raw, dict) or type(raw.get("task_id")) is not int or raw["task_id"] <= 0
            or not isinstance(raw.get("task_version"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", raw["task_version"])):
        return None
    return {key: raw[key] for key in ("task_id", "task_version")}


def _project_task_action_receipt(raw, worker_id):
    if (not isinstance(raw, dict) or raw.get("kind") != "worker-decompose"
            or raw.get("worker_id") != worker_id
            or raw.get("state") not in {"pending", "running", "confirmed", "error", "cancelled"}
            or _project_task_action_binding(raw) is None):
        return None
    for field in ("generation", "request_id"):
        if not isinstance(raw.get(field), str) or not _RUN_ID.fullmatch(raw[field]):
            return None
    result = {key: raw[key] for key in ("kind", "worker_id", "generation", "request_id",
                                        "task_id", "task_version", "state")}
    result.update({key: _text(raw.get(key), limit=80) for key in ("requested_at", "confirmed_at")})
    if raw["state"] == "confirmed":
        ids = raw.get("created_ids")
        if (not result["confirmed_at"] or not isinstance(ids, list) or not 1 <= len(ids) <= 100
                or any(type(value) is not int or value <= 0 for value in ids)
                or len(set(ids)) != len(ids) or type(raw.get("parent_closed")) is not bool
                or not _text(raw.get("backend"), limit=80) or not _text(raw.get("model"), limit=160)):
            return None
        result.update(created_ids=list(ids), parent_closed=raw["parent_closed"])
    for key in ("backend", "model"):
        if _text(raw.get(key), limit=160):
            result[key] = _text(raw[key], limit=160)
    return result


def request_worker_decomposition(worker_id, generation, task_id, task_version, *, device_token, timeout=8.0):
    binding = _project_task_action_binding({"task_id": task_id, "task_version": task_version})
    if (not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id)
            or not isinstance(generation, str) or not _RUN_ID.fullmatch(generation) or binding is None):
        raise WorkerActionRejected("Aktueller Workerlauf und Task-Inhaltsversion erforderlich", 400)
    current = read_worker_status(device_token=device_token, timeout=timeout)
    worker = next((w for w in current["workers"] if w["id"] == worker_id), None)
    if (not worker or worker.get("status") != "running" or worker.get("generation") != generation
            or worker.get("task_action_binding") != binding):
        raise WorkerActionRejected("Workerlauf oder Auftrag ist nicht mehr aktuell", 409)
    result = _request_control_api("POST", "workers/decompose", device_token=device_token,
                                  body={"id": worker_id, "generation": generation, **binding}, timeout=timeout)
    receipt = _project_task_action_receipt(result.get("receipt"), worker_id)
    if (result.get("ok") is not True or receipt is None or receipt["generation"] != generation
            or _project_task_action_binding(receipt) != binding):
        raise WorkerActionRejected("Zerlegungsanfrage wurde nicht für diesen Auftrag bestätigt", 503)
    observed = None
    try:
        snapshot = read_worker_status(device_token=device_token, timeout=timeout)
        latest = next((w for w in snapshot["workers"] if w["id"] == worker_id), {})
        candidate = _project_task_action_receipt(latest.get("task_action_receipt"), worker_id)
        if (candidate and candidate["generation"] == generation
                and candidate["request_id"] == receipt["request_id"]
                and _project_task_action_binding(candidate) == binding):
            observed = candidate
    except WorkerStatusUnavailable:
        pass
    return {"ok": True, "action": "decompose", "receipt": observed or receipt,
            "runtime_readback": "available" if observed else "unavailable"}


def request_worker_handoff(worker_id: str, generation: str, *, device_token: str,
                           timeout: float = 8.0) -> dict[str, Any]:
    if (not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id)
            or not isinstance(generation, str) or not _RUN_ID.fullmatch(generation)):
        raise WorkerActionRejected("Worker-ID oder Laufgeneration ist ungültig", 400)
    current = read_worker_status(device_token=device_token, timeout=timeout)
    worker = next((w for w in current["workers"] if w["id"] == worker_id), None)
    if not worker or worker.get("status") != "running" or worker.get("generation") != generation:
        raise WorkerActionRejected("Workerlauf ist nicht mehr aktuell", 409)
    result = _request_control_api("POST", "workers/handoff", device_token=device_token,
                                  body={"id": worker_id, "generation": generation}, timeout=timeout)
    receipt = _project_handoff_receipt(result.get("receipt"), worker_id)
    if result.get("ok") is not True or receipt is None or receipt["generation"] != generation:
        raise WorkerActionRejected("Kontextübergabe wurde nicht für diesen Lauf bestätigt", 503)
    observed = None
    try:
        snapshot = read_worker_status(device_token=device_token, timeout=timeout)
        latest = next((w for w in snapshot["workers"] if w["id"] == worker_id), {})
        candidate = _project_handoff_receipt(latest.get("handoff_receipt"), worker_id)
        if (candidate and candidate["generation"] == generation
                and candidate["request_id"] == receipt["request_id"]):
            observed = candidate
    except WorkerStatusUnavailable:
        pass
    return {"ok": True, "action": "handoff", "receipt": observed or receipt,
            "runtime_readback": "available" if observed else "unavailable"}


def _project_configuration(result: dict[str, Any], worker_id: str) -> dict[str, Any]:
    from hub._services.chat.slots_config import WORKER_EDITABLE_FIELDS, DEFAULT_ROLE_PROMPTS
    version = result.get("configuration_version")
    configuration = result.get("configuration")
    if (result.get("ok") is not True or result.get("id") != worker_id
            or not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version)
            or not isinstance(configuration, dict)):
        raise WorkerStatusUnavailable("Worker-Konfigurationsbeleg ist ungültig")
    projected = {}
    for key, value in configuration.items():
        if key not in WORKER_EDITABLE_FIELDS:
            continue
        if value is None:
            if key == "task_id":
                projected[key] = None
            continue
        if key == "expert_models":
            if (not isinstance(value, dict) or len(value) > 10 or any(
                    role not in {*DEFAULT_ROLE_PROMPTS, "default"} or not isinstance(model, str)
                    or len(model) > 180 for role, model in value.items())):
                raise WorkerStatusUnavailable("Experten-Modellzuordnung ist ungültig")
            projected[key] = dict(value)
        elif key in {"think", "allow_tools", "include_system_prompt", "multi_role"}:
            if type(value) is not bool:
                raise WorkerStatusUnavailable("Worker-Konfiguration enthält ungültige Flags")
            projected[key] = value
        elif key in {"task_id", "max_tool_rounds", "max_experts", "pause_after", "pause_minutes"}:
            if type(value) is not int:
                raise WorkerStatusUnavailable("Worker-Konfiguration enthält ungültige Zahlen")
            projected[key] = value
        else:
            if not isinstance(value, str) or len(value) > (20000 if key == "task_prompt" else 180) or "\x00" in value:
                raise WorkerStatusUnavailable("Worker-Konfiguration enthält ungültigen Text")
            projected[key] = value
    return {"ok": True, "id": worker_id, "configuration_version": version, "configuration": projected}


def read_worker_configuration(worker_id: str, *, device_token: str, timeout: float = 8.0):
    if not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id):
        raise WorkerActionRejected("Worker-ID ist ungültig", 400)
    result = _request_control_api("GET", "workers/configuration", device_token=device_token,
                                  params={"id": worker_id}, timeout=timeout)
    return _project_configuration(result, worker_id)


def update_worker_configuration(worker_id: str, version: str, changes: dict[str, Any], *,
                                 device_token: str, timeout: float = 8.0):
    from hub._services.chat.slots_config import WORKER_EDITABLE_FIELDS
    if (not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id)
            or not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version)
            or not isinstance(changes, dict) or not changes or set(changes) - WORKER_EDITABLE_FIELDS):
        raise WorkerActionRejected("Worker-Konfigurationsanfrage ist ungültig", 400)
    current = read_worker_status(device_token=device_token, timeout=timeout)
    worker = next((w for w in current["workers"] if w["id"] == worker_id), None)
    if not worker or worker.get("status") not in {"idle", "paused", "completed", "error"}:
        raise WorkerActionRejected("Worker muss vor einer Änderung pausiert oder gestoppt sein", 409)
    accepted = _request_control_api("POST", "workers/configuration", device_token=device_token,
        body={"id": worker_id, "configuration_version": version, "changes": changes}, timeout=timeout)
    acknowledged = _project_configuration(accepted, worker_id)
    observed = read_worker_configuration(worker_id, device_token=device_token, timeout=timeout)
    if (observed != acknowledged
            or any(observed["configuration"].get(key) != value for key, value in changes.items())):
        raise WorkerActionRejected("Gespeicherte Worker-Konfiguration stimmt nicht mit der Anfrage überein", 409)
    return observed


def _control_context(device_token: str):
    """Resolve the local controller and forward the already-verified device token."""
    try:
        from gui import server as gui_server

        base = gui_server._chat_control_base_url()
        ready_check = gui_server._chat_control_payload_ready
    except (ImportError, AttributeError, OSError, ValueError) as exc:
        raise WorkerStatusUnavailable("Control-API-Verbindung nicht verfügbar") from exc

    effective_token = (device_token or "").strip()
    if not effective_token:
        try:
            from hub._services.chat.control_auth import get_control_api_token

            effective_token = get_control_api_token()
        except (ImportError, OSError, ValueError, RuntimeError, AttributeError):
            effective_token = ""

    if not isinstance(base, str) or not effective_token:
        raise WorkerStatusUnavailable("Control-API-Verbindung oder Geräteautorisierung fehlt")
    parsed = urlsplit(base)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/api"):
        raise WorkerStatusUnavailable("Control-API-Ziel ist nicht der erwartete Loopback-Dienst")
    headers = {"Authorization": f"Bearer {effective_token}", "Accept": "application/json"}
    return base.rstrip("/"), headers, ready_check


def _request_control_api(
    method: str,
    endpoint: str,
    *,
    device_token: str,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    method = method.upper()
    if (method, endpoint) not in _ALLOWED_CONTROL:
        raise WorkerStatusUnavailable("Control-API-Endpunkt ist nicht freigegeben")
    base, headers, ready_check = _control_context(device_token)

    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            identity_response = client.get(base + "/status", headers=headers)
            identity = identity_response.json() if identity_response.status_code == 200 else None
            if identity_response.status_code != 200 or not ready_check(identity):
                raise WorkerStatusUnavailable("Control-API-Identität nicht bestätigt")

            if method != "GET":
                auth_response = client.get(base + "/auth/check", headers=headers)
                auth_payload = auth_response.json() if auth_response.status_code == 200 else None
                if (auth_response.status_code != 200 or not isinstance(auth_payload, dict)
                        or auth_payload.get("authenticated") is not True):
                    raise WorkerActionRejected("Control-API-Autorisierung fehlgeschlagen", 503)

            response = client.request(
                method, f"{base}/{endpoint}", params=params, json=body, headers=headers,
            )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        if isinstance(exc, (WorkerStatusUnavailable, WorkerActionRejected)):
            raise
        raise WorkerStatusUnavailable("Lokale Control-API nicht erreichbar") from exc

    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise WorkerStatusUnavailable("Control-API-Antwort überschreitet das Größenlimit")
    if response.status_code in (401, 403):
        raise WorkerActionRejected("Control-API hat die Anfrage abgelehnt", response.status_code)
    if not 200 <= response.status_code < 300:
        raise WorkerActionRejected("Control-API hat die Workeraktion nicht bestätigt", response.status_code)
    try:
        payload = response.json()
    except ValueError as exc:
        raise WorkerStatusUnavailable("Control-API lieferte kein gültiges JSON") from exc
    if not isinstance(payload, dict):
        raise WorkerStatusUnavailable("Control-API lieferte kein Objekt")
    return payload


def read_worker_status(*, device_token: str, timeout: float = 5.0) -> dict[str, Any]:
    """Read one authenticated live worker snapshot from the local Control API."""
    payload = _request_control_api("GET", "workers", device_token=device_token, timeout=timeout)
    if payload.get("ok") is not True or not isinstance(payload.get("workers"), list):
        raise WorkerStatusUnavailable("Lokale Control-API lieferte keinen Workerstatus")
    workers = [_project_worker(entry) for entry in payload["workers"]]
    from datetime import datetime, timezone

    return {
        "schema": "bach.workers.status.v1",
        "availability": "available",
        "source": "authenticated_local_control_api",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "count": len(workers),
        "workers": workers,
    }


def worker_model_catalog(
    backend: str,
    *,
    device_token: str | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Return only models from the selected provider's current catalog."""
    if backend not in {"ollama", "ollama-cloud", "openrouter"}:
        raise WorkerActionRejected("Dieses Blueprint unterstützt den Provider nicht", 400)
    if backend == "openrouter":
        from hub._services.llm.openrouter_catalog import (
            get_openrouter_catalog,
            openrouter_credential_status,
        )

        catalog = get_openrouter_catalog()
        models = [item["id"] for item in catalog.get("models", []) if item.get("free") is True]
        return {
            "provider": backend,
            "models": models,
            "credential_configured": openrouter_credential_status()["configured"],
            "source": catalog.get("source"),
            "stale": catalog.get("stale", False),
        }

    payload = _request_control_api(
        "GET", "models", device_token=device_token or "", params={"provider": backend}, timeout=timeout,
    )
    models = payload.get("models")
    if payload.get("provider") != backend or not isinstance(models, list):
        raise WorkerStatusUnavailable("Control-API-Modellkatalog ist ungültig")
    clean_models = [model for model in models if isinstance(model, str) and model.strip()]
    return {
        "provider": backend,
        "models": clean_models,
        "credential_configured": payload.get("credential_configured"),
        "source": "control_api",
        "stale": False,
    }


def worker_creation_options() -> dict[str, list[dict[str, str]]]:
    """Expose only worker modes and expert roles implemented by BACH."""
    try:
        from hub._services.chat.slots_config import DEFAULT_ROLE_PROMPTS
    except ImportError as exc:
        raise WorkerStatusUnavailable("BACH-Rollenliste nicht verfügbar") from exc

    expert_roles = [
        {
            "id": role_id,
            "label": _EXPERT_ROLE_LABELS.get(role_id, role_id.replace("-", " ").replace("_", " ").title()),
        }
        for role_id in DEFAULT_ROLE_PROMPTS
        if role_id not in _BASE_ROLE_IDS
    ]
    if not expert_roles:
        raise WorkerStatusUnavailable("BACH-Rollenliste enthält keine Expertenrollen")
    return {"sub_modes": list(_WORKER_SUB_MODES), "expert_roles": expert_roles}


def background_worker_blueprint() -> dict[str, Any]:
    """Describe the built-in worker recipe using the current Always-On defaults."""
    try:
        from hub._services.chat.slots_config import core_system_agents_snapshot

        snapshot = core_system_agents_snapshot()
        always_on = next(
            (item for item in snapshot.get("agents", []) if item.get("id") == "buddha_always_on"),
            None,
        )
        if not isinstance(always_on, dict):
            raise ValueError("always_on_missing")
    except (ImportError, OSError, ValueError, TypeError) as exc:
        raise WorkerStatusUnavailable("Hintergrundworker-Vorlage nicht verfügbar") from exc

    def configured_int(field: str, fallback: int) -> int:
        value = always_on.get(field)
        return value if type(value) is int else fallback

    creation_options = worker_creation_options()
    pause_basis = always_on.get("pause_basis")
    if not isinstance(pause_basis, str) or pause_basis not in {"runs", "tasks"}:
        pause_basis = "runs"
    return {
        "schema": "bach.worker-blueprint.v1",
        "blueprint_id": "system:hintergrundworker",
        "name": "BACH Hintergrundworker",
        "description": "Bearbeitet nach ausdrücklichem Start offene BACH-Aufgaben mit dem gewählten Modell.",
        "sub_mode": "hintergrund_worker",
        "source": "BACH-Control-Rollenvertrag",
        "defaults_source": "buddha_always_on_system_agent",
        "defaults": {
            "backend": "ollama-cloud",
            "max_tool_rounds": configured_int("max_tool_rounds", 25),
            "mode": always_on.get("mode") or "full",
            "think": bool(always_on.get("think", True)),
            "pause_after": configured_int("pause_after", 5),
            "pause_minutes": configured_int("pause_minutes", 1),
            "pause_basis": pause_basis,
            "include_system_prompt": True,
            "allow_tools": True,
            "type": "continuous",
            "ttl_minutes": 0,
        },
        "backend_options": ["ollama-cloud", "openrouter", "ollama"],
        **creation_options,
        "creation_state": "idle",
        "requires_explicit_start": True,
    }


def worker_action(
    action: str,
    payload: dict[str, Any],
    *,
    device_token: str,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Invoke one explicit worker action through the authenticated controller."""
    route = _ACTIONS.get(action)
    if route is None:
        raise WorkerActionRejected("Workeraktion ist nicht freigegeben", 400)
    method, endpoint = route
    if action in {"start", "pause", "stop", "delete"}:
        worker_id = payload.get("id")
        if not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id):
            raise WorkerActionRejected("Worker-ID ist ungültig", 400)

        if action == "delete":
            snapshot = read_worker_status(device_token=device_token, timeout=timeout)
            existing = next((item for item in snapshot["workers"] if item["id"] == worker_id), None)
            if existing is None:
                raise WorkerActionRejected("Workerprofil nicht gefunden", 404)
            if existing.get("status") in {"running", "stopping"}:
                raise WorkerActionRejected("Laufende Worker müssen zuerst gestoppt werden", 409)

    result = _request_control_api(
        method, endpoint, device_token=device_token, body=payload, timeout=timeout,
    )
    if result.get("ok") is not True:
        raise WorkerActionRejected("Control-API hat die Workeraktion nicht bestätigt", 409)

    response: dict[str, Any] = {"ok": True, "action": action}
    if isinstance(result.get("worker"), dict):
        worker = _project_worker(result["worker"])
        if action == "create" and worker.get("status") != "idle":
            raise WorkerActionRejected("Neues Profil wurde nicht als Living/idle bestätigt", 503)
        response["worker"] = worker
    if isinstance(result.get("id"), str) and _SAFE_ID.fullmatch(result["id"]):
        response["id"] = result["id"]
    receipt = result.get("receipt")
    if isinstance(receipt, dict):
        response["receipt"] = {
            key: _text(receipt.get(key), limit=120)
            for key in ("outcome", "status", "worker_id", "requested_status", "confirmed_at")
            if _text(receipt.get(key), limit=120) is not None
        }
    return response


def _configured_task_prompt(worker_id: str) -> str | None:
    """Read a worker's saved task prompt for the explicit start request.

    The Control API accepts an optional per-run prompt. Passing the saved
    prompt here prevents the generic background-worker instruction from
    silently replacing the user's configured task when the profile starts.
    The prompt stays on the server-to-server loopback request and is never
    included in the browser-facing worker projection.
    """
    try:
        from hub._services.chat.slots_config import get_worker_slot

        profile = get_worker_slot(worker_id)
    except Exception as exc:
        raise WorkerStatusUnavailable("Gespeicherter Workerauftrag nicht lesbar") from exc
    if not profile:
        return None
    prompt = profile.get("task_prompt")
    if prompt in (None, ""):
        return None
    if not isinstance(prompt, str) or len(prompt) > 20000 or "\x00" in prompt:
        raise WorkerActionRejected("Gespeicherter Workerauftrag ist ungültig", 409)
    return prompt.strip() or None


def start_worker(worker_id: str, *, device_token: str, timeout: float = 8.0) -> dict[str, Any]:
    """Preflight one existing worker, explicitly start it, then read back state."""
    if not isinstance(worker_id, str) or not _SAFE_ID.fullmatch(worker_id):
        raise WorkerActionRejected("Worker-ID ist ungültig", 400)
    current = read_worker_status(device_token=device_token, timeout=timeout)
    worker = next((item for item in current["workers"] if item["id"] == worker_id), None)
    if worker is None:
        raise WorkerActionRejected("Workerprofil nicht gefunden", 404)
    if worker.get("status") in {"running", "stopping"}:
        raise WorkerActionRejected("Worker läuft bereits oder wird beendet", 409)
    if worker.get("status") in {"expired", "deleted"}:
        raise WorkerActionRejected("Worker-Lease ist abgelaufen", 409)

    readiness = _request_control_api(
        "GET", "readiness", device_token=device_token,
        params={"chat_id": worker_id}, timeout=timeout,
    )
    if readiness.get("available") is not True:
        raise WorkerActionRejected("Gewähltes Modell ist derzeit nicht bereit", 503)

    start_payload: dict[str, Any] = {"id": worker_id}
    task_prompt = _configured_task_prompt(worker_id)
    if task_prompt:
        start_payload["prompt"] = task_prompt
    accepted = worker_action("start", start_payload, device_token=device_token, timeout=timeout)
    try:
        snapshot = read_worker_status(device_token=device_token, timeout=timeout)
        observed = next((item for item in snapshot["workers"] if item["id"] == worker_id), None)
    except WorkerStatusUnavailable:
        observed = None
    return {
        **accepted,
        "start_acknowledged": True,
        "runtime_state": observed.get("status") if observed else "unknown",
        "runtime_readback": "available" if observed else "unavailable",
        "worker": observed or worker,
    }
