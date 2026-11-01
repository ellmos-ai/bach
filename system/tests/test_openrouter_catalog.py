"""Safety checks for the OpenRouter free-model catalog."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm import openrouter_catalog as catalog  # noqa: E402


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", catalog.OPENROUTER_MODELS_URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("provider-secret-must-not-escape", request=request, response=response)

    def json(self):
        return self.payload


def test_catalog_preserves_free_router_and_excludes_paid_models(monkeypatch):
    monkeypatch.setattr(catalog.httpx, "get", lambda *_args, **_kwargs: _Response({
        "data": [
            {"id": "openrouter/free", "name": "Free Models Router"},
            {"id": "vendor/model:free", "name": "Free", "pricing": {"prompt": "0.0", "completion": "0.0"}},
            {"id": "vendor/promo-without-free-variant", "name": "Temporary zero price", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "vendor/suffix-lie:free", "name": "Conflicting price", "pricing": {"prompt": "0.1", "completion": "0"}},
            {"id": "vendor/suffix-unknown:free", "name": "Unknown suffix", "pricing": {"prompt": None, "completion": "0"}},
            {"id": "vendor/paid-cache", "name": "Paid cache input", "pricing": {"prompt": "0", "completion": "0", "input_cache_read": "0.01"}},
            {"id": "google/flash", "name": "Paid", "pricing": {"prompt": "0.1", "completion": "0.2"}},
            {"id": "vendor/unclear", "name": "Unknown price", "pricing": {"prompt": None, "completion": "0"}},
        ]
    }))

    models = catalog._fetch_catalog()
    ids = [item["id"] for item in models]
    assert ids[0] == "openrouter/free"
    assert "vendor/model:free" in ids
    assert "vendor/promo-without-free-variant" not in ids
    assert "vendor/suffix-lie:free" not in ids
    assert "vendor/suffix-unknown:free" not in ids
    assert "vendor/paid-cache" not in ids
    assert "google/flash" not in ids
    assert "vendor/unclear" not in ids
    assert all(item["free"] is True for item in models)


def test_catalog_outage_returns_only_router_without_a_prior_cache(monkeypatch):
    monkeypatch.setattr(catalog, "_cached", None)
    monkeypatch.setattr(catalog, "_cached_at", 0.0)
    monkeypatch.setattr(catalog, "_cached_admission", {})
    requests = []

    def raise_network_error(*_args, **_kwargs):
        requests.append(1)
        request = httpx.Request("GET", catalog.OPENROUTER_MODELS_URL)
        raise httpx.ConnectError("provider-secret-must-not-escape", request=request)

    monkeypatch.setattr(catalog.httpx, "get", raise_network_error)
    result = catalog.get_openrouter_catalog(force_refresh=True, model_id="vendor/model:free")
    assert len(requests) == catalog.CATALOG_MAX_ATTEMPTS
    assert result["stale"] is True
    assert result["source"] == "router_selector_only"
    assert result["failure_code"] == "catalog_transport_error"
    assert result["selection"] == {"allowed": False, "reason": "catalog_transport_error"}
    assert [item["id"] for item in result["models"]] == ["openrouter/free"]
    assert "provider-secret" not in repr(result)


def test_credential_status_never_returns_key_material(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-do-not-return")
    status = catalog.openrouter_credential_status()
    assert status == {"configured": True, "source": "environment"}
    assert "sk-or-do-not-return" not in repr(status)


def test_reads_canonical_credentials_env_file_without_exposing_key(tmp_path, monkeypatch):
    credentials_dir = tmp_path / "CREDENTIALS"
    credentials_dir.mkdir()
    secret = "sk-or-never-return-this"
    (credentials_dir / "openrouter.env").write_text(
        f"OPENROUTER_API_KEY={secret}\n", encoding="utf-8",
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ELLMOS_CREDENTIALS_DIR", str(credentials_dir))

    assert catalog.read_openrouter_api_key() == secret
    status = catalog.openrouter_credential_status()
    assert status == {"configured": True, "source": "credentials_dir"}
    assert secret not in repr(status)


def test_legacy_credentials_file_remains_a_fallback(tmp_path, monkeypatch):
    home = tmp_path / "home"
    legacy_dir = home / ".credentials"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "openrouter_api_key").write_text("legacy-key", encoding="utf-8")
    monkeypatch.setattr(catalog.Path, "home", lambda: home)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ELLMOS_CREDENTIALS_DIR", str(home / "no-canonical-credentials"))

    assert catalog.read_openrouter_api_key() == "legacy-key"
    assert catalog.openrouter_credential_status() == {
        "configured": True,
        "source": "legacy_credentials_file",
    }


def _reset_cache(monkeypatch):
    monkeypatch.setattr(catalog, "_cached", None)
    monkeypatch.setattr(catalog, "_cached_at", 0.0)
    monkeypatch.setattr(catalog, "_cached_admission", {})


def test_catalog_retries_one_transient_status_then_admits_confirmed_free_model(monkeypatch):
    _reset_cache(monkeypatch)
    response_payload = {
        "data": [{
            "id": "vendor/model:free",
            "name": "Public Free Variant",
            "pricing": {"prompt": "0", "completion": "0"},
        }]
    }
    responses = iter([
        _Response({"error": "provider-secret"}, status_code=503),
        _Response(response_payload),
    ])
    requests = []

    def fake_get(url, **kwargs):
        requests.append((url, kwargs))
        return next(responses)

    monkeypatch.setattr(catalog.httpx, "get", fake_get)
    result = catalog.get_openrouter_catalog(
        force_refresh=True, model_id="vendor/model:free"
    )

    assert len(requests) == 2
    assert all(url == catalog.OPENROUTER_MODELS_URL for url, _ in requests)
    assert all(
        call["timeout"] == catalog.CATALOG_REQUEST_TIMEOUT_SECONDS
        and call["follow_redirects"] is False
        for _, call in requests
    )
    assert result["selection"] == {"allowed": True, "reason": None}
    assert "vendor/model:free" in [item["id"] for item in result["models"]]
    assert "provider-secret" not in repr(result)


@pytest.mark.parametrize(
    ("status_code", "expected_code", "expected_attempts", "public_status"),
    [
        (401, "catalog_auth_rejected", 1, 401),
        (403, "catalog_auth_rejected", 1, 403),
        (404, "catalog_http_error", 1, None),
        (408, "catalog_http_transient", 2, 408),
        (425, "catalog_http_transient", 2, 425),
        (429, "catalog_http_transient", 2, 429),
        (500, "catalog_http_transient", 2, 500),
        (502, "catalog_http_transient", 2, 502),
        (503, "catalog_http_transient", 2, 503),
        (504, "catalog_http_transient", 2, 504),
    ],
)
def test_catalog_retry_policy_uses_only_fixed_http_statuses(
    monkeypatch, status_code, expected_code, expected_attempts, public_status
):
    _reset_cache(monkeypatch)
    requests = []

    def fake_get(*_args, **_kwargs):
        requests.append(1)
        return _Response({"error": "provider-secret"}, status_code=status_code)

    monkeypatch.setattr(catalog.httpx, "get", fake_get)
    result = catalog.get_openrouter_catalog(
        force_refresh=True, model_id="vendor/model:free"
    )

    assert len(requests) == expected_attempts
    assert result["failure_code"] == expected_code
    assert result.get("status_code") == public_status
    assert result["selection"]["reason"] == expected_code
    assert "provider-secret" not in repr(result)


def test_invalid_catalog_schema_is_not_retried_or_exposed(monkeypatch):
    _reset_cache(monkeypatch)
    requests = []

    def fake_get(*_args, **_kwargs):
        requests.append(1)
        return _Response({"data": {"not": "a list", "secret": "provider-secret"}})

    monkeypatch.setattr(catalog.httpx, "get", fake_get)
    result = catalog.get_openrouter_catalog(force_refresh=True)

    assert len(requests) == 1
    assert result["failure_code"] == "catalog_invalid_schema"
    assert "status_code" not in result
    assert "provider-secret" not in repr(result)


def test_catalog_reasons_separate_absence_price_and_ambiguity(monkeypatch):
    _reset_cache(monkeypatch)
    rows = [
        {"id": "vendor/good:free", "name": "Good", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "vendor/missing:free", "name": "Hidden Missing", "pricing": {"prompt": "0"}},
        {"id": "vendor/invalid:free", "name": "Hidden Invalid", "pricing": {"prompt": "NaN", "completion": "0"}},
        {"id": "vendor/paid:free", "name": "Hidden Paid", "pricing": {"prompt": "0.01", "completion": "0"}},
        {"id": "vendor/promo", "name": "Hidden Promo", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "vendor/duplicate:free", "name": "Duplicate A", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "vendor/duplicate:free", "name": "Duplicate B", "pricing": {"prompt": "0", "completion": "0"}},
    ]
    monkeypatch.setattr(catalog.httpx, "get", lambda *_args, **_kwargs: _Response({"data": rows}))

    expected = {
        "vendor/good:free": (True, None),
        "vendor/missing:free": (False, "model_price_missing"),
        "vendor/invalid:free": (False, "model_price_invalid"),
        "vendor/paid:free": (False, "model_price_nonzero"),
        "vendor/promo": (False, "model_not_free_variant"),
        "vendor/duplicate:free": (False, "model_ambiguous"),
        "vendor/absent:free": (False, "model_not_listed"),
    }
    for model_id, wanted in expected.items():
        result = catalog.get_openrouter_catalog(force_refresh=True, model_id=model_id)
        assert (result["selection"]["allowed"], result["selection"]["reason"]) == wanted
        ids = [item["id"] for item in result["models"]]
        assert "openrouter/free" in ids
        assert "vendor/good:free" in ids
        assert model_id not in ids if wanted[0] is False else model_id in ids
        assert all(name not in repr(result) for name in ("Hidden Missing", "Hidden Invalid", "Hidden Paid", "Hidden Promo"))


def test_catalog_rejects_free_model_without_published_tool_support(monkeypatch):
    _reset_cache(monkeypatch)
    rows = [
        {
            "id": "vendor/tools:free",
            "name": "Tool Capable",
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["tools", "completion"],
        },
        {
            "id": "vendor/chat-only:free",
            "name": "Chat Only",
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["completion", "prompt"],
        },
    ]
    monkeypatch.setattr(catalog.httpx, "get", lambda *_args, **_kwargs: _Response({"data": rows}))

    admitted = catalog.get_openrouter_catalog(force_refresh=True, model_id="vendor/tools:free")
    assert admitted["selection"] == {"allowed": True, "reason": None}
    admitted_ids = [item["id"] for item in admitted["models"]]
    assert "vendor/tools:free" in admitted_ids
    assert "vendor/chat-only:free" not in admitted_ids

    denied = catalog.get_openrouter_catalog(force_refresh=True, model_id="vendor/chat-only:free")
    assert denied["selection"] == {"allowed": False, "reason": "model_tools_unsupported"}
    denied_ids = [item["id"] for item in denied["models"]]
    assert "vendor/chat-only:free" not in denied_ids
    assert "vendor/tools:free" in denied_ids
    assert "Chat Only" not in repr(denied)


def test_failed_refresh_invalidates_expired_individual_model_proof(monkeypatch):
    _reset_cache(monkeypatch)
    good_payload = {
        "data": [{
            "id": "vendor/model:free",
            "name": "Free",
            "pricing": {"prompt": "0", "completion": "0"},
        }]
    }
    responses = iter([
        _Response(good_payload),
        _Response({"error": "secret"}, status_code=503),
        _Response({"error": "secret"}, status_code=503),
    ])
    monkeypatch.setattr(catalog.httpx, "get", lambda *_args, **_kwargs: next(responses))

    first = catalog.get_openrouter_catalog(force_refresh=True)
    assert "vendor/model:free" in [item["id"] for item in first["models"]]
    failed = catalog.get_openrouter_catalog(force_refresh=True, model_id="vendor/model:free")

    assert failed["stale"] is True
    assert failed["failure_code"] == "catalog_http_transient"
    assert failed["selection"]["reason"] == "catalog_http_transient"
    assert [item["id"] for item in failed["models"]] == ["openrouter/free"]
    assert catalog._cached is None


def test_catalog_retries_timeout_then_accepts_fresh_payload(monkeypatch):
    _reset_cache(monkeypatch)
    payload = {
        "data": [{
            "id": "vendor/model:free",
            "name": "Confirmed Free",
            "pricing": {"prompt": "0", "completion": "0"},
        }]
    }
    requests = []

    def fake_get(*_args, **_kwargs):
        requests.append(1)
        if len(requests) == 1:
            request = httpx.Request("GET", catalog.OPENROUTER_MODELS_URL)
            raise httpx.ReadTimeout("provider-secret", request=request)
        return _Response(payload)

    monkeypatch.setattr(catalog.httpx, "get", fake_get)
    result = catalog.get_openrouter_catalog(
        force_refresh=True, model_id="vendor/model:free"
    )

    assert len(requests) == 2
    assert result["selection"] == {"allowed": True, "reason": None}


def test_unlisted_httpx_transport_failure_is_redacted_without_retry(monkeypatch):
    _reset_cache(monkeypatch)
    requests = []

    def fake_get(*_args, **_kwargs):
        requests.append(1)
        request = httpx.Request("GET", catalog.OPENROUTER_MODELS_URL)
        raise httpx.ProxyError("provider-secret", request=request)

    monkeypatch.setattr(catalog.httpx, "get", fake_get)
    result = catalog.get_openrouter_catalog(
        force_refresh=True, model_id="vendor/model:free"
    )

    assert len(requests) == 1
    assert result["failure_code"] == "catalog_transport_error"
    assert result["selection"]["reason"] == "catalog_transport_error"
    assert "provider-secret" not in repr(result)
