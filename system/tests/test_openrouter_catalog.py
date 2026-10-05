"""Safety checks for the OpenRouter free-model catalog."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm import openrouter_catalog as catalog  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

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

    def raise_network_error(*_args, **_kwargs):
        request = httpx.Request("GET", catalog.OPENROUTER_MODELS_URL)
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(catalog.httpx, "get", raise_network_error)
    result = catalog.get_openrouter_catalog(force_refresh=True)
    assert result["stale"] is True
    assert result["source"] == "router_selector_only"
    assert [item["id"] for item in result["models"]] == ["openrouter/free"]


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
