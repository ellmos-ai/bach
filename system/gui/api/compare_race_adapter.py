"""Guarded optional adapter to the installed compare-race and COMA SDKs."""
from __future__ import annotations

import importlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class RaceUnavailable(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _config_path() -> Path | None:
    configured = os.environ.get("BACH_COMPARE_RACE_CONFIG") or os.environ.get("COMPARE_RACE_CONFIG")
    candidate = Path(os.path.expanduser(configured)) if configured else Path.home() / ".compare-race" / "compare-race.config.json"
    if not candidate.is_absolute():
        return None
    return candidate if candidate.is_file() else None


def _budget() -> tuple[int, int] | None:
    try:
        lanes = int(os.environ["BACH_COMPARE_RACE_MAX_LANES"])
        seconds = int(os.environ["BACH_COMPARE_RACE_MAX_SECONDS"])
    except (KeyError, ValueError):
        return None
    if not (2 <= lanes <= 4 and 10 <= seconds <= 300):
        return None
    return lanes, seconds


def _spend_authority() -> Any | None:
    """Optional reviewed authority: available() and reserve(...) context manager.

    A time/lane limit is not a money budget. The provider-specific module must
    reserve a durable allowance before any subprocess starts and settle it on
    exit, including failures. Import absence fails closed.
    """
    try:
        authority = importlib.import_module("gui.api.compare_race_spend_authority")
        if callable(getattr(authority, "available", None)) and callable(getattr(authority, "reserve", None)):
            return authority
    except ImportError:
        pass
    return None


def _sdk_settings() -> tuple[Any, Any] | None:
    if not _config_path():
        return None
    try:
        config = importlib.import_module("compare_race.config")
        race = importlib.import_module("compare_race.race")
        importlib.import_module("coma")
        return config.load(path=_config_path()), race
    except (ImportError, OSError, ValueError, TypeError, AttributeError):
        return None


def _trusted_models(settings: Any) -> list[dict[str, str]]:
    from coma.adapters import get_adapter
    seen: set[str] = set()
    models = []
    for entry in settings.models:
        if (not entry.name or entry.name in seen or entry.backend not in ("claude", "codex", "agy")
                or entry.allow_unverified):
            continue
        seen.add(entry.name)
        try:
            adapter = get_adapter(entry.backend, **({"model": entry.model} if entry.model else {}))
            detected = bool(adapter.resolve_executable())
        except (OSError, TypeError, ValueError):
            detected = False
        models.append({"id": entry.name, "backend": entry.backend,
                       "runtime": "cli_detected" if detected else "cli_missing"})
    return models


def readiness(*, worker: bool = False) -> dict[str, Any]:
    """Public, non-secret metadata; no model or provider call occurs."""
    blockers = []
    if not worker:
        authority = _spend_authority()
        try:
            if authority is None or authority.available() is not True:
                blockers.append("spend_authority_unavailable")
        except Exception:
            blockers.append("spend_authority_unavailable")
    if os.environ.get("BACH_COMPARE_RACE_ENABLED") != "1":
        blockers.append("operator_gate_disabled")
    if _budget() is None:
        blockers.append("call_budget_unconfigured")
    if _config_path() is None:
        blockers.append("model_registry_missing")
    sdk = _sdk_settings()
    if sdk is None:
        blockers.append("sdk_or_config_unavailable")
        models = []
    else:
        settings, _race = sdk
        if getattr(settings, "source", "defaults") == "defaults":
            blockers.append("model_registry_invalid")
            models = []
        else:
            models = _trusted_models(settings)
        if len([m for m in models if m["runtime"] == "cli_detected"]) < 2:
            blockers.append("configured_lanes_insufficient")
    budget = _budget()
    return {"availability": "ready" if not blockers else "unavailable",
            "source": "compare_race_config", "models": models,
            "blockers": blockers, "provider_auth": "not_checked",
            "winner_policy": "manual_review",
            "budget": {"max_lanes": budget[0], "max_seconds": budget[1]} if budget else None}


def _validate_request(payload: dict[str, Any], state: dict[str, Any]) -> tuple[str, list[str], int]:
    if state["availability"] != "ready":
        raise RaceUnavailable(state["blockers"][0])
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000:
        raise ValueError("prompt_invalid")
    names = payload.get("models")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names) or len(names) != len(set(names)):
        raise ValueError("models_invalid")
    budget = _budget()
    if budget is None or len(names) < 2 or len(names) > budget[0]:
        raise RaceUnavailable("call_budget_exceeded")
    permitted = {model["id"] for model in state["models"] if model["runtime"] == "cli_detected"}
    if not set(names).issubset(permitted):
        raise RaceUnavailable("model_not_configured")
    if payload.get("confirm_cost") is not True:
        raise RaceUnavailable("cost_confirmation_required")
    return prompt.strip(), names, budget[1]


def _worker_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Runs only inside the isolated worker process; SDK calls are real."""
    state = readiness(worker=True)
    prompt, names, max_seconds = _validate_request(payload, state)
    sdk = _sdk_settings()
    if sdk is None:
        raise RaceUnavailable("sdk_or_config_unavailable")
    settings, race = sdk
    settings.timeout_seconds = min(settings.timeout_seconds, max_seconds)
    result = race.run_race(prompt, settings, models=names, mode="sequential", repeats=1)
    candidates = []
    for run in result.results:
        kind = run.evidence_kind if run.evidence_kind in race.EVIDENCE_KINDS else "unknown"
        candidates.append({
            "model": run.identity.model, "backend": run.backend,
            "evidence_kind": kind, "ok": bool(run.ok) and kind == "live",
            "response": str(run.output or "")[:4000] if kind == "live" and run.ok else "",
            "latency_ms": round(run.latency_s * 1000) if kind == "live" and run.ok else None,
        })
    return {"candidates": candidates, "winner": None,
            "verdict": "manual_review_required",
            "evidence": "live" if candidates and all(c["ok"] for c in candidates) else "partial"}


def execute_isolated(payload: dict[str, Any], device_id: int) -> dict[str, Any]:
    """Run SDK in a child so its temporary chdir cannot affect GUI requests."""
    state = readiness()
    prompt, names, max_seconds = _validate_request(payload, state)
    authority = _spend_authority()
    if authority is None:
        raise RaceUnavailable("spend_authority_unavailable")
    startup = {}
    if os.name == "nt":
        startup["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = os.environ.copy()
    worker_token = secrets.token_urlsafe(32)
    env["BACH_RACE_WORKER_TOKEN"] = worker_token
    system_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (system_root, env.get("PYTHONPATH"))))
    worker_payload = {**payload, "_worker_token": worker_token}
    try:
        with authority.reserve(device_id=device_id, model_ids=tuple(names),
                               max_seconds=max_seconds, prompt_chars=len(prompt)):
            with tempfile.TemporaryDirectory(prefix="bach-race-lane-") as neutral_cwd:
                finished = subprocess.run(
                    [sys.executable, "-m", "gui.api.compare_race_adapter", "--worker"],
                    input=json.dumps(worker_payload), text=True, capture_output=True,
                    timeout=max_seconds * len(names) + 30, check=False,
                    cwd=neutral_cwd, env=env, **startup,
                )
    except (OSError, subprocess.TimeoutExpired):
        raise RaceUnavailable("worker_unavailable")
    except Exception as exc:
        raise RaceUnavailable("spend_authority_unavailable") from exc
    if finished.returncode != 0:
        raise RaceUnavailable("worker_failed")
    try:
        result = json.loads(finished.stdout)
    except json.JSONDecodeError:
        raise RaceUnavailable("worker_invalid_response")
    if not isinstance(result, dict) or not isinstance(result.get("candidates"), list):
        raise RaceUnavailable("worker_invalid_response")
    return result


def _main() -> int:
    if sys.argv[1:] != ["--worker"]:
        return 2
    try:
        payload = json.load(sys.stdin)
        expected = os.environ.get("BACH_RACE_WORKER_TOKEN", "")
        if not expected or not secrets.compare_digest(str(payload.pop("_worker_token", "")), expected):
            return 1
        result = _worker_result(payload)
    except (RaceUnavailable, ValueError, TypeError):
        return 1
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
