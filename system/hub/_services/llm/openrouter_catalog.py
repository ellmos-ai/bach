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
CATALOG_REQUEST_TIMEOUT_SECONDS = 6.0
CATALOG_MAX_ATTEMPTS = 2
_TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_SAFE_STATUS_CODES = {401, 403, *_TRANSIENT_HTTP_STATUSES}

_lock = threading.Lock()
_cached: dict[str, Any] | None = None
_cached_at = 0.0
_cached_admission: dict[str, str | None] = {}


_SAFE_MESSAGES = {
    "catalog_timeout": "OpenRouter-Katalog: Zeitlimit beim Abruf.",
    "catalog_transport_error": "OpenRouter-Katalog: Verbindung nicht verfügbar.",
    "catalog_http_transient": "OpenRouter-Katalog: Dienst vorübergehend nicht verfügbar.",
    "catalog_http_error": "OpenRouter-Katalog: Anfrage abgelehnt.",
    "catalog_auth_rejected": "OpenRouter-Katalog: Authentifizierung abgelehnt.",
    "catalog_invalid_schema": "OpenRouter-Katalog: Antwortformat ungültig.",
    "model_not_listed": "OpenRouter-Modell ist im bestätigten Katalog nicht aufgeführt.",
    "model_price_missing": "OpenRouter-Katalog enthält keinen vollständigen Preisnachweis.",
    "model_price_invalid": "OpenRouter-Katalog enthält einen ungültigen Preisnachweis.",
    "model_price_nonzero": "OpenRouter-Katalog weist mindestens einen nicht kostenlosen Preis aus.",
    "model_not_free_variant": "OpenRouter-Modell ist keine ausdrücklich ausgewiesene :free-Variante.",
    "model_ambiguous": "OpenRouter-Katalog enthält mehrere Einträge für dieses Modell.",
}


class OpenRouterCatalogError(ValueError):
    """Safe, typed rejection of an individual model without provider text."""

    def __init__(self, code: str):
        self.code = code if code in _SAFE_MESSAGES else "catalog_invalid_schema"
        super().__init__(_SAFE_MESSAGES[self.code])


class _CatalogFetchFailure(Exception):
    def __init__(self, code: str, status_code: int | None = None):
        self.code = code
        self.status_code = status_code if status_code in _SAFE_STATUS_CODES else None
        super().__init__(code)


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


def _price_rejection(pricing: Any) -> str | None:
    if not isinstance(pricing, dict):
        return "model_price_missing"

    invalid = False
    nonzero = False
    for value in pricing.values():
        try:
            price = Decimal(str(value).strip())
        except (InvalidOperation, TypeError, ValueError):
            invalid = True
            continue
        if not price.is_finite():
            invalid = True
        elif price != 0:
            nonzero = True

    # A definite non-zero published price is sufficient to deny free-only
    # admission even if another field is malformed or absent.
    if nonzero:
        return "model_price_nonzero"
    if invalid:
        return "model_price_invalid"
    if "prompt" not in pricing or "completion" not in pricing:
        return "model_price_missing"
    return None


def _tools_rejection(model: dict[str, Any]) -> str | None:
    """Reject free models that cannot serve tool calls.

    ``supported_parameters`` is optional in the OpenRouter payload. A missing,
    empty or unreadable value is treated as *unknown* and therefore admitted;
    only a published parameter list without ``tools`` denies admission. This
    keeps the free-catalog contract stable for providers that do not publish
    the field (and for existing fixtures).
    """
    supported = model.get("supported_parameters")
    if not isinstance(supported, (list, tuple, set)):
        return None
    normalized = {str(item).strip().lower() for item in supported if isinstance(item, str)}
    if not normalized:
        return None
    if "tools" in normalized:
        return None
    return "model_tools_unsupported"


def _model_admission_rejection(model: dict[str, Any]) -> str | None:
    model_id = model.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return "model_not_listed"
    model_id = model_id.strip()
    if model_id == FREE_ROUTER_ID:
        return None
    price_rejection = _price_rejection(model.get("pricing"))
    if price_rejection:
        return price_rejection
    if not model_id.endswith(":free"):
        return "model_not_free_variant"
    return _tools_rejection(model)


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
    if _model_admission_rejection(model):
        return None
    return {
        "id": model_id,
        "name": str(model.get("name") or model_id),
        "free": True,
        "kind": "model",
    }


def _request_catalog_data() -> list[Any]:
    last_failure: _CatalogFetchFailure | None = None
    for attempt in range(CATALOG_MAX_ATTEMPTS):
        try:
            response = httpx.get(
                OPENROUTER_MODELS_URL,
                timeout=CATALOG_REQUEST_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            last_failure = _CatalogFetchFailure("catalog_timeout")
        except httpx.NetworkError:
            last_failure = _CatalogFetchFailure("catalog_transport_error")
        except httpx.HTTPError:
            raise _CatalogFetchFailure("catalog_transport_error") from None
        else:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code in {401, 403}:
                    raise _CatalogFetchFailure(
                        "catalog_auth_rejected", status_code
                    ) from None
                if status_code in _TRANSIENT_HTTP_STATUSES:
                    last_failure = _CatalogFetchFailure(
                        "catalog_http_transient", status_code
                    )
                else:
                    raise _CatalogFetchFailure("catalog_http_error") from None
            except httpx.HTTPError:
                raise _CatalogFetchFailure("catalog_http_error") from None
            else:
                try:
                    payload = response.json()
                except (TypeError, ValueError):
                    raise _CatalogFetchFailure("catalog_invalid_schema") from None
                except httpx.HTTPError:
                    raise _CatalogFetchFailure("catalog_invalid_schema") from None
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, list):
                    raise _CatalogFetchFailure("catalog_invalid_schema")
                return data

        if attempt + 1 < CATALOG_MAX_ATTEMPTS:
            continue
    if last_failure is None:
        last_failure = _CatalogFetchFailure("catalog_transport_error")
    raise last_failure


def _fetch_catalog_snapshot() -> tuple[list[dict[str, Any]], dict[str, str | None]]:
    data = _request_catalog_data()
    observations: dict[str, list[tuple[dict[str, Any] | None, str | None]]] = {}
    for raw in data:
        if not isinstance(raw, dict):
            continue
        raw_id = raw.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        model_id = raw_id.strip()
        record = _model_record(raw)
        rejection = _model_admission_rejection(raw)
        observations.setdefault(model_id, []).append((record, rejection))

    records: list[dict[str, Any]] = []
    admission: dict[str, str | None] = {}
    for model_id, entries in observations.items():
        if model_id == FREE_ROUTER_ID:
            records.append(entries[0][0] or {
                "id": FREE_ROUTER_ID,
                "name": "Free Models Router",
                "free": True,
                "kind": "provider_router",
            })
            admission[model_id] = None
            continue
        if len(entries) > 1:
            admission[model_id] = "model_ambiguous"
            continue
        record, rejection = entries[0]
        admission[model_id] = rejection
        if record is not None:
            records.append(record)

    if not any(item["id"] == FREE_ROUTER_ID for item in records):
        records.append({
            "id": FREE_ROUTER_ID,
            "name": "Free Models Router",
            "free": True,
            "kind": "provider_router",
        })
    records.sort(key=lambda item: (item["id"] != FREE_ROUTER_ID, item["name"].casefold(), item["id"]))
    return records, admission


def _fetch_catalog() -> list[dict[str, Any]]:
    return _fetch_catalog_snapshot()[0]


def _with_model_selection(
    result: dict[str, Any],
    model_id: str | None,
    admission: dict[str, str | None],
) -> dict[str, Any]:
    if model_id is None:
        return result
    selected = model_id.strip() if isinstance(model_id, str) else ""
    if selected == FREE_ROUTER_ID:
        reason = None
    elif result.get("stale"):
        reason = str(result.get("failure_code") or "catalog_transport_error")
    elif selected in admission:
        reason = admission[selected]
    elif selected in {item.get("id") for item in result.get("models", [])}:
        reason = None
    else:
        reason = "model_not_listed"
    result["selection"] = {"allowed": reason is None, "reason": reason}
    return result


def get_openrouter_catalog(
    *, force_refresh: bool = False, model_id: str | None = None
) -> dict[str, Any]:
    """Return confirmed free models and an optional safe model-selection result."""
    global _cached, _cached_at, _cached_admission
    now = time.monotonic()
    with _lock:
        if not force_refresh and _cached is not None and now - _cached_at < CATALOG_TTL_SECONDS:
            result = {**_cached, "source": "cache", "stale": False}
            return _with_model_selection(result, model_id, _cached_admission)
        try:
            models, admission = _fetch_catalog_snapshot()
            observed_at = datetime.now(timezone.utc).isoformat()
            _cached = {
                "models": models,
                "source": "openrouter_models_api",
                "stale": False,
                "observed_at": observed_at,
            }
            _cached_admission = admission
            _cached_at = now
            return _with_model_selection(dict(_cached), model_id, _cached_admission)
        except _CatalogFetchFailure as exc:
            # A failed refresh invalidates prior model proofs. Do not serve an
            # expired free ID after the provider becomes unknown.
            _cached = None
            _cached_admission = {}
            _cached_at = 0.0
            fallback = {
                "models": [{
                    "id": FREE_ROUTER_ID,
                    "name": "Free Models Router",
                    "free": True,
                    "kind": "provider_router",
                }],
                "source": "router_selector_only",
                "stale": True,
                "observed_at": None,
                "failure_code": exc.code,
            }
            if exc.status_code is not None:
                fallback["status_code"] = exc.status_code
            return _with_model_selection(fallback, model_id, {})
        except (ValueError, TypeError):
            _cached = None
            _cached_admission = {}
            _cached_at = 0.0
            fallback = {
                "models": [{
                    "id": FREE_ROUTER_ID,
                    "name": "Free Models Router",
                    "free": True,
                    "kind": "provider_router",
                }],
                "source": "router_selector_only",
                "stale": True,
                "observed_at": None,
                "failure_code": "catalog_invalid_schema",
            }
            return _with_model_selection(fallback, model_id, {})
