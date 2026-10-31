"""Worker provider settings reach the actual backend without live inference."""
import copy

import pytest
from hub._services.chat.local_provider_config import local_backend_configs
from hub._services.llm.model_backend import create_backend


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    for key in ("OLLAMA_URL", "OLLAMA_MODEL", "OLLAMA_NUM_CTX",
                "OLLAMA_TIMEOUT_SECONDS", "LM_STUDIO_URL", "LM_STUDIO_MODEL"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("kind", ["ollama", None])
def test_worker_factory_preserves_explicit_context_and_timeout(monkeypatch, kind):
    settings = {"num_ctx": 8192, "timeout_seconds": 125.5,
                "base_url": "http://127.0.0.1:19111", "default_model": "selected:27b",
                "unrelated_secret": "must-not-be-forwarded"}
    if kind is not None:
        settings["type"] = kind
    config = {"backend": settings}
    before = copy.deepcopy(config)
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "600")
    projected = local_backend_configs(config)["ollama"]
    backend = create_backend(projected)
    assert backend.num_ctx == backend.get_context_limit() == 8192
    assert backend.request_timeout == 125.5
    assert backend.base_url == settings["base_url"]
    assert backend.default_model == settings["default_model"]
    assert "unrelated_secret" not in projected
    assert config == before


@pytest.mark.parametrize("settings", [{}, {"num_ctx": None, "timeout_seconds": None}])
def test_absent_or_null_options_retain_backend_environment_fallback(monkeypatch, settings):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "600")
    backend = create_backend(local_backend_configs({"backend": settings})["ollama"])
    assert backend.num_ctx == 16384
    assert backend.request_timeout == 600


@pytest.mark.parametrize("key,value", [
    ("num_ctx", 511), ("num_ctx", "invalid"),
    ("timeout_seconds", 0), ("timeout_seconds", "invalid"),
    ("num_ctx", True), ("num_ctx", False),
    ("timeout_seconds", True), ("timeout_seconds", False),
])
def test_invalid_explicit_settings_are_not_silently_discarded(key, value):
    with pytest.raises(ValueError):
        projected = local_backend_configs({"backend": {"type": "ollama", key: value}})["ollama"]
        create_backend(projected)


@pytest.mark.parametrize("kind", ["lmstudio", "lm-studio", "lm_studio", "openrouter"])
def test_another_providers_options_never_change_local_ollama(kind):
    config = {"backend": {"type": kind, "num_ctx": 2048, "timeout_seconds": 50}}
    projected = local_backend_configs(config)
    for provider in ("ollama", "lmstudio"):
        assert "num_ctx" not in projected[provider]
        assert "timeout_seconds" not in projected[provider]


def test_context_options_do_not_change_url_model_environment_precedence(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:19112")
    monkeypatch.setenv("OLLAMA_MODEL", "override:27b")
    projected = local_backend_configs({"backend": {
        "type": "ollama", "base_url": "http://127.0.0.1:19111",
        "default_model": "selected:27b", "num_ctx": 4096, "timeout_seconds": 120,
    }})["ollama"]
    backend = create_backend(projected)
    assert backend.base_url == "http://127.0.0.1:19112"
    assert backend.default_model == "override:27b"
    assert backend.num_ctx == 4096 and backend.request_timeout == 120
