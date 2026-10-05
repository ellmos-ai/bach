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
_TOOL_ROUND_ACTIVITY = re.compile(r"^Tool \[(\d+)\]:")
_MAX_RESPONSE_BYTES = 2_000_000
_SAFE_TEXT_FIELDS = (
    "name", "backend", "model", "mode", "sub_mode", "role_id", "status", "pause_basis",
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
    return item


def _control_context(device_token: str):
    """Resolve the local controller and forward the already-verified device token."""
    try:
        from gui import server as gui_server

        base = gui_server._chat_control_base_url()
        ready_check = gui_server._chat_control_payload_ready
    except (ImportError, AttributeError, OSError, ValueError) as exc:
        raise WorkerStatusUnavailable("Control-API-Verbindung nicht verfügbar") from exc

    if not isinstance(base, str) or not isinstance(device_token, str) or not device_token.strip():
        raise WorkerStatusUnavailable("Control-API-Verbindung oder Geräteautorisierung fehlt")
    parsed = urlsplit(base)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/api"):
        raise WorkerStatusUnavailable("Control-API-Ziel ist nicht der erwartete Loopback-Dienst")
    headers = {"Authorization": f"Bearer {device_token.strip()}", "Accept": "application/json"}
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
            "pause_basis": "runs",
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
