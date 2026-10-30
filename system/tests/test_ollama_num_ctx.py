"""Tests für die num_ctx-Steuerung des OllamaClient.

Geprüft werden:
- die ENV-Kette (OLLAMA_NUM_CTX, dann OLLAMA_NUM_CFG, dann Standard 4096),
- die Wertvalidierung (ganze Zahl, Grenzen 512 bis 262144),
- das Zusammenführen von options.num_ctx in generate und chat.

Netzaufrufe werden vollständig vermieden: OllamaClient._post wird durch
eine Funktion ersetzt, die den übergebenen Payload protokolliert und ein
vorgefertigtes Antwort-Dict zurückgibt.
"""

import pytest

from tools.ollama.ollama_client import DEFAULT_NUM_CTX, OllamaClient

GENERATE_OK = {
    "model": "llama3.2",
    "response": "ok",
    "prompt_eval_count": 5,
    "eval_count": 7,
    "total_duration": 123,
}

CHAT_OK = {
    "model": "llama3.2",
    "message": {"content": "ok"},
    "prompt_eval_count": 5,
    "eval_count": 7,
    "total_duration": 123,
}


def _client_with_post(monkeypatch, response):
    """OllamaClient mit gemocktem _post; Antwort und Payload werden aufgezeichnet."""
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)
    client = OllamaClient()
    captured = {}

    def fake_post(*args, **kwargs):
        captured["endpoint"] = kwargs.get("endpoint", args[0] if args else None)
        captured["payload"] = kwargs.get("payload", args[1] if len(args) > 1 else None)
        return dict(response)

    client._post = fake_post
    return client, captured


# --- ENV-Kette und Validierung ---


def test_default_when_env_missing(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)
    client = OllamaClient()
    assert client.num_ctx == 4096
    assert client.num_ctx == DEFAULT_NUM_CTX


def test_env_num_ctx_beats_num_cfg(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    monkeypatch.setenv("OLLAMA_NUM_CFG", "16384")
    client = OllamaClient()
    assert client.num_ctx == 8192


def test_env_num_cfg_fallback(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.setenv("OLLAMA_NUM_CFG", "16384")
    client = OllamaClient()
    assert client.num_ctx == 16384


def test_explicit_num_ctx_beats_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    monkeypatch.setenv("OLLAMA_NUM_CFG", "16384")
    client = OllamaClient(num_ctx=2048)
    assert client.num_ctx == 2048


def test_env_not_a_number(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "viele")
    with pytest.raises(ValueError, match="ganze Zahl"):
        OllamaClient()


def test_num_ctx_below_minimum(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)
    with pytest.raises(ValueError, match="zwischen 512 und 262144"):
        OllamaClient(num_ctx=256)


def test_num_ctx_above_maximum(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)
    with pytest.raises(ValueError, match="zwischen 512 und 262144"):
        OllamaClient(num_ctx=524288)


def test_boundaries_accepted(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)
    assert OllamaClient(num_ctx=512).num_ctx == 512
    assert OllamaClient(num_ctx=262144).num_ctx == 262144


# --- generate: options.num_ctx im Payload ---


def test_generate_success_and_default_num_ctx(monkeypatch):
    client, captured = _client_with_post(monkeypatch, GENERATE_OK)
    resp = client.generate("hallo", model="llama3.2")
    assert resp.success is True
    assert resp.text == "ok"
    assert resp.model == "llama3.2"
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 7
    assert resp.total_duration == 123
    assert captured["endpoint"] == "/api/generate"
    assert captured["payload"]["options"]["num_ctx"] == DEFAULT_NUM_CTX


def test_generate_explicit_num_ctx(monkeypatch):
    client, captured = _client_with_post(monkeypatch, GENERATE_OK)
    resp = client.generate("hallo", model="llama3.2", num_ctx=8192)
    assert resp.success is True
    assert captured["payload"]["options"]["num_ctx"] == 8192


def test_generate_options_num_ctx_not_overwritten(monkeypatch):
    client, captured = _client_with_post(monkeypatch, GENERATE_OK)
    client.generate("hallo", model="llama3.2", options={"num_ctx": 1024})
    assert captured["payload"]["options"]["num_ctx"] == 1024


def test_generate_options_merged_with_default(monkeypatch):
    client, captured = _client_with_post(monkeypatch, GENERATE_OK)
    client.generate("hallo", model="llama3.2", options={"temperature": 0.5})
    opts = captured["payload"]["options"]
    assert opts["num_ctx"] == DEFAULT_NUM_CTX
    assert opts["temperature"] == 0.5


def test_generate_env_reaches_payload(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CFG", raising=False)
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    client = OllamaClient()
    captured = {}

    def fake_post(*args, **kwargs):
        captured["payload"] = kwargs.get("payload", args[1] if len(args) > 1 else None)
        return dict(GENERATE_OK)

    client._post = fake_post
    resp = client.generate("hallo", model="llama3.2")
    assert resp.success is True
    assert captured["payload"]["options"]["num_ctx"] == 8192


def test_generate_post_exception_yields_failure(monkeypatch):
    client, _ = _client_with_post(monkeypatch, GENERATE_OK)

    def boom(*args, **kwargs):
        raise RuntimeError("netz kaputt")

    client._post = boom
    resp = client.generate("hallo", model="llama3.2")
    assert resp.success is False
    assert resp.error


# --- chat: options.num_ctx im Payload ---


def test_chat_success_and_default_num_ctx(monkeypatch):
    client, captured = _client_with_post(monkeypatch, CHAT_OK)
    resp = client.chat([{"role": "user", "content": "hallo"}], model="llama3.2")
    assert resp.success is True
    assert resp.text == "ok"
    assert captured["endpoint"] == "/api/chat"
    assert captured["payload"]["options"]["num_ctx"] == DEFAULT_NUM_CTX


def test_chat_explicit_num_ctx(monkeypatch):
    client, captured = _client_with_post(monkeypatch, CHAT_OK)
    resp = client.chat([{"role": "user", "content": "hallo"}], model="llama3.2", num_ctx=8192)
    assert resp.success is True
    assert captured["payload"]["options"]["num_ctx"] == 8192


def test_chat_options_num_ctx_not_overwritten(monkeypatch):
    client, captured = _client_with_post(monkeypatch, CHAT_OK)
    client.chat([{"role": "user", "content": "hallo"}], model="llama3.2", options={"num_ctx": 2048})
    assert captured["payload"]["options"]["num_ctx"] == 2048


def test_chat_without_message_key(monkeypatch):
    client, _ = _client_with_post(monkeypatch, {"model": "llama3.2"})
    resp = client.chat([{"role": "user", "content": "hallo"}], model="llama3.2")
    assert resp.success is False
    assert resp.error == "Keine Antwort"