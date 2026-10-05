"""Read-only, evidence-separated observations for the hardware cockpit."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_lock() -> dict[str, Any]:
    """Observe the configured lock file without executing its optional script."""
    from hub.compute_lock import DEFAULT_LOCK_PATH

    result: dict[str, Any] = {
        "state": "unknown", "source": "compute_lock_file",
        "observed_at": _now(), "reason_code": "source_unavailable",
        "reported_jobs": None,
    }
    path = Path(os.path.expanduser(DEFAULT_LOCK_PATH))
    try:
        if not path.is_file():
            return result
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        if age < -60 or age > 300:
            result.update(state="stale", reason_code="lock_file_stale")
            return result
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = data.get("active_compute_jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            result["reason_code"] = "invalid_lock_schema"
            return result
        result["reported_jobs"] = len(jobs)
        result["state"] = "none_reported" if not jobs else "reported_unverified"
        result["reason_code"] = "fresh_lock_file"
        return result
    except (OSError, ValueError, TypeError):
        result["reason_code"] = "lock_read_failed"
        return result


def _capacity() -> dict[str, Any]:
    """Keep Ollama connection evidence separate from memory and holder state."""
    result: dict[str, Any] = {
        "state": "unknown", "observed_at": _now(),
        "source": "ollama_ps_and_fackel_capacity",
        "reason_code": "provider_unavailable", "loaded_models": None,
        "loaded_model_count": None, "used_gib": None,
        "capacity_gib": None, "occupied_units": None,
    }
    try:
        from hub._services import fackel

        connected, models = fackel.probe_loaded_models()
        if not connected:
            return result
        stand = fackel.stand()
        result["loaded_models"] = models
        result["loaded_model_count"] = len(models)
        if stand.get("messbar") and stand.get("modelle") == models:
            result.update(
                state="measured", reason_code="provider_and_capacity_observed",
                used_gib=stand.get("belegt_gib"),
                capacity_gib=stand.get("kapazitaet_gib"),
                occupied_units=stand.get("belegt_fackeln"),
            )
        else:
            result.update(state="partial", reason_code="capacity_unavailable")
        return result
    except Exception:
        result["reason_code"] = "capacity_probe_failed"
        return result


def _task_counts(db_path: Path) -> tuple[int | None, int | None]:
    """Read the current BACH task table without creating a database on GET."""
    if not db_path.is_file():
        return None, None
    try:
        conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            conn.execute("PRAGMA query_only=ON")
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            user = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assigned_to = 'user'"
            ).fetchone()[0]
            return total, user
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error):
        return None, None


def _runtime_compute_turn() -> dict[str, Any]:
    """Read the Control API's live local-inference gate, never infer from settings."""
    result: dict[str, Any] = {
        "state": "unknown", "source": "local_control_api",
        "observed_at": None, "reason_code": "control_status_unavailable",
        "active": None, "priority": None, "foreground_waiters": None,
    }
    try:
        from gui import server as gui_server
        base = gui_server._chat_control_base_url()
        if not isinstance(base, str):
            return result
        from urllib.parse import urlsplit
        parsed = urlsplit(base)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.path.rstrip("/") != "/api" or parsed.username or parsed.password):
            result["reason_code"] = "control_target_not_local"
            return result

        import httpx
        from hub._services.chat.control_auth import get_control_api_auth_header

        auth = get_control_api_auth_header()
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = auth
        with httpx.Client(timeout=2.0, trust_env=False, follow_redirects=False) as client:
            response = client.get(base.rstrip("/") + "/status", headers=headers)
        if response.status_code != 200 or len(response.content) > 256_000:
            result["reason_code"] = "control_status_unavailable"
            return result
        payload = response.json()
        turn = payload.get("compute_turn") if isinstance(payload, dict) else None
        if not isinstance(turn, dict) or type(turn.get("active")) is not bool:
            result["reason_code"] = "compute_turn_evidence_missing"
            return result
        active = turn["active"]
        waiters = turn.get("foreground_waiters")
        result.update(
            state="owned_by_this_system" if active else "idle",
            observed_at=_now(),
            reason_code="local_inference_gate_active" if active else "no_local_inference_active",
            active=active,
            priority=turn.get("priority"),
            foreground_waiters=waiters if isinstance(waiters, int) and not isinstance(waiters, bool) else None,
            chat_id=turn.get("chat_id") if isinstance(turn.get("chat_id"), str) else None,
        )
        return result
    except Exception:
        result["reason_code"] = "control_status_read_failed"
        return result


def build_cluster_cockpit(db_path: Path) -> dict[str, Any]:
    """Separate settings, lock reports, loaded-model capacity and actual ownership."""
    from hub.compute_lock import get_fackel_preference

    checked_at = _now()
    try:
        preference = get_fackel_preference(migrate=False)
    except Exception:
        preference = None
    compute_lock = _compute_lock()
    capacity = _capacity()
    total_tasks, user_tasks = _task_counts(Path(db_path))
    compute_turn = _runtime_compute_turn()
    local_inference_active = compute_turn.get("active") is True
    lock_state = compute_lock.get("state")
    lock_is_clear = lock_state == "none_reported" and compute_lock.get("reported_jobs") == 0
    is_active = local_inference_active and lock_is_clear
    if is_active:
        ownership_state = "owned_by_this_system"
        ownership_reason = "local_inference_active_and_compute_lock_clear"
    elif local_inference_active and lock_state == "reported_unverified":
        ownership_state = "competing_compute_reported"
        ownership_reason = "compute_lock_reports_competing_jobs"
    elif local_inference_active and lock_state == "stale":
        ownership_state = "unknown"
        ownership_reason = "compute_lock_stale_during_local_inference"
    elif local_inference_active:
        ownership_state = "unknown"
        ownership_reason = "compute_lock_clearance_not_confirmed"
    elif compute_turn.get("active") is False:
        ownership_state = "idle"
        ownership_reason = "no_local_inference_active"
    else:
        ownership_state = "unknown"
        ownership_reason = compute_turn.get("reason_code", "control_status_unavailable")
    ownership = {
        "scope": "local_bach_inference_without_competing_compute_jobs",
        "state": ownership_state,
        "holder": "BACH" if is_active else None,
        "holder_is_this_system": True if is_active else None,
        "flame": is_active,
        "observed_at": checked_at if local_inference_active or compute_turn.get("active") is False else None,
        "reason_code": ownership_reason,
    }
    return {
        "observed_at": checked_at,
        "trithon": {
            "status": "unknown", "name": "Trithon",
            "label": "Konfiguration und Laufzeit nicht geprüft",
            "cluster_host": None, "endpoints": [],
        },
        "muschelgrund": {
            "status": "unknown", "name": "Muschelgrund",
            "label": "Aufgaben- und Speicheranbindung nicht geprüft",
            "total_tasks": total_tasks, "user_tasks": user_tasks,
            "synced": None,
        },
        "salt": {
            "status": "unknown", "name": "SALT",
            "label": "Lease- und Claim-Zustand nicht geprüft",
            "lease_status": None, "client": None,
        },
        "fackel": {
            "ownership": ownership,
            "compute_turn": compute_turn,
            "priority": {"value": preference, "source": "configured_or_default"},
            "compute_lock": compute_lock,
            "capacity": capacity,
            # Safe values for clients on the previous response schema.
            "preference": preference,
            "flame_animated": is_active,
            "compute_active": is_active,
            "current_holder": (
                "BACH" if is_active else
                "Rechenjobs melden Konkurrenz" if ownership_state == "competing_compute_reported" else
                "Derzeit kein lokaler BACH-Lauf" if compute_turn.get("active") is False else
                "Nicht geprüft"
            ),
            "competitors": [],
            "models_loaded": capacity["loaded_models"],
            "messbar": False,
            "belegt_gib": None, "belegt_fackeln": None,
        },
    }
