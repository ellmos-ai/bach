"""Repro task-2545: num_ctx-Unterstützung im Standalone-Ollama-Client (system/tools/ollama/ollama_client.py) und OllamaBackend-Spiegel."""

import importlib.util
import pathlib

import pytest

from hub._services.llm.model_backend import create_backend

_TOOL_FILE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "ollama" / "ollama_client.py"
_spec = importlib.util.spec_from_file_location("ollama_client_numctx", _TOOL_FILE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

OllamaClient = _mod.OllamaClient


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "OLLAMA_NUM_CTX",
        "OLLAMA_TIMEOUT_SECONDS",
        "LM_STUDIO_URL",
        "LM_STUDIO_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def stub_client(monkeypatch):
    client = OllamaClient()
    captures = []

    def fake_post(endpoint, data):
        captures.append((endpoint, data))
        return {"response": "ok", "message": {"content": "ok"}, "model": "m"}

    monkeypatch.setattr(client, "_post", fake_post)
    client.captures = captures
    return client


def test_generate_num_ctx_in_payload(stub_client):
    stub_client.generate("frage", num_ctx=2048)
    endpoint, data = stub_client.captures[0]
    assert endpoint == "/api/generate"
    assert data["options"]["num_ctx"] == 2048


def test_generate_without_num_ctx_keeps_options_clean(stub_client):
    stub_client.generate("frage")
    endpoint, data = stub_client.captures[0]
    assert endpoint == "/api/generate"
    assert "num_ctx" not in (data.get("options") or {})


def test_chat_num_ctx_in_payload(stub_client):
    stub_client.chat([{"role": "user", "content": "hi"}], num_ctx=4096)
    endpoint, data = stub_client.captures[0]
    assert endpoint == "/api/chat"
    assert data["options"]["num_ctx"] == 4096


def test_chat_without_num_ctx_keeps_options_clean(stub_client):
    stub_client.chat([{"role": "user", "content": "hi"}])
    endpoint, data = stub_client.captures[0]
    assert endpoint == "/api/chat"
    assert "num_ctx" not in (data.get("options") or {})


def test_backend_explicit_num_ctx_and_timeout(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "600")
    backend = create_backend({"type": "ollama", "num_ctx": 8192, "timeout_seconds": 125.5})
    assert backend.get_context_limit() == 8192
    assert backend.request_timeout == 125.5


def test_backend_env_fallbacks(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "600")
    backend = create_backend({"type": "ollama"})
    assert backend.get_context_limit() == 16384
    assert backend.request_timeout == 600.0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("num_ctx", 511),
        ("num_ctx", "invalid"),
        ("timeout_seconds", 0),
        ("timeout_seconds", "invalid"),
    ],
)
def test_backend_rejects_invalid_values(key, value):
    with pytest.raises(ValueError):
        create_backend({"type": "ollama", key: value})