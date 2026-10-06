"""Small, fail-closed OpenRouter catalog for the System GUI and backend.

Only the provider's free router and models whose public catalog prices are
explicitly zero are returned. A catalog outage never promotes paid models.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
FREE_ROUTER_ID = "openrouter/free"
CATALOG_TTL_SECONDS = 300

_lock = threading.Lock()
_cached: dict[str, Any] | None = None
_cached_at = 0.0


def _credentials_env_path() -> Path:
    credentials_dir = os.environ.get("ELLMOS_CREDENTIALS_DIR")
    if credentials_dir:
        return Path(credentials_dir) / "openrouter.env"
    if os.name == "nt":
        return Path(r"C:\_Local_DEV\CREDENTIALS\openrouter.env")
    return Path.home() / "CREDENTIALS" / "openrouter.env"


def _read_key_from_env_file(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return ""
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or key.strip() != "OPENROUTER_API_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1].strip()
        if value:
            return value
    return ""


def _read_openrouter_credential() -> tuple[str, str]:
    configured = str(os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if configured:
        return configured, "environment"

    configured = _read_key_from_env_file(_credentials_env_path())
    if configured:
        return configured, "credentials_dir"

    # Keep the old per-user file as a migration fallback for existing installs.
    key_file = Path.home() / ".credentials" / "openrouter_api_key"
    try:
        configured = key_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        configured = ""
    return configured, "legacy_credentials_file" if configured else "none"


def read_openrouter_api_key() -> str:
    """Read the key for server-side use; callers must never return it."""
    return _read_openrouter_credential()[0]


def openrouter_credential_status() -> dict[str, str | bool]:
    """Return only credential metadata; never return key material."""
    key, source = _read_openrouter_credential()
    return {"configured": bool(key), "source": source}


def _is_zero_price(value: Any) -> bool:
    try:
        return Decimal(str(value).strip()) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _model_record(model: dict[str, Any]) -> dict[str, Any] | None:
    model_id = model.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    model_id = model_id.strip()
    if model_id == FREE_ROUTER_ID:
        return {
            "id": FREE_ROUTER_ID,
            "name": str(model.get("name") or "Free Models Router"),
            "free": True,
            "kind": "provider_router",
        }

    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        return None
    # The model ID suffix is descriptive, not a pricing receipt. Accept an
    # individual model only when the provider catalog explicitly reports zero
    # for both base prices and every additional price field it publishes.
    # Unknown or non-zero pricing fields fail closed; openrouter/free remains
    # available as the provider-owned free router selector.
    is_free = (
        # OpenRouter's free variant is a provider-level routing contract. Do
        # not treat an unrelated zero-price promotion on a normal model slug
        # as a stable free model; only its explicit :free variant is eligible.
        model_id.endswith(":free")
        and
        "prompt" in pricing
        and "completion" in pricing
        and all(_is_zero_price(value) for value in pricing.values())
    )
    if not is_free:
        return None
    return {
        "id": model_id,
        "name": str(model.get("name") or model_id),
        "free": True,
        "kind": "model",
    }


def _fetch_catalog() -> list[dict[str, Any]]:
    response = httpx.get(OPENROUTER_MODELS_URL, timeout=6.0, follow_redirects=False)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("invalid_openrouter_catalog")
    records = [item for raw in data if isinstance(raw, dict)
               if (item := _model_record(raw)) is not None]
    if not any(item["id"] == FREE_ROUTER_ID for item in records):
        records.append({
            "id": FREE_ROUTER_ID,
            "name": "Free Models Router",
            "free": True,
            "kind": "provider_router",
        })
    records.sort(key=lambda item: (item["id"] != FREE_ROUTER_ID, item["name"].casefold(), item["id"]))
    return records


def get_openrouter_catalog(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return current free model IDs, or a router-only fallback on outage."""
    global _cached, _cached_at
    now = time.monotonic()
    with _lock:
        if not force_refresh and _cached is not None and now - _cached_at < CATALOG_TTL_SECONDS:
            return {**_cached, "source": "cache", "stale": False}
        try:
            models = _fetch_catalog()
            observed_at = datetime.now(timezone.utc).isoformat()
            _cached = {
                "models": models,
                "source": "openrouter_models_api",
                "stale": False,
                "observed_at": observed_at,
            }
            _cached_at = now
            return dict(_cached)
        except (httpx.HTTPError, ValueError, TypeError):
            # A model can stop being free while this process is offline. Never
            # suggest stale model IDs for a free-only workflow; keep only the
            # provider-owned free router selector.
            return {
                "models": [{
                    "id": FREE_ROUTER_ID,
                    "name": "Free Models Router",
                    "free": True,
                    "kind": "provider_router",
                }],
                "source": "router_selector_only",
                "stale": True,
                "observed_at": None,
            }
