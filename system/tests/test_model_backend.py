# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Truthful result handling for local Ollama chat responses."""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm.model_backend import OllamaBackend  # noqa: E402


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("Ollama HTTP error", request=request, response=response)

    def json(self):
        return self.payload


class _FakeClient:
    def __init__(self, response, requests=None):
        self.response = response
        self.requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **kwargs):
        if self.requests is not None:
            self.requests.append(kwargs)
        return self.response


def _run_chat(monkeypatch, payload, status_code=200):
    response = _FakeResponse(payload, status_code)
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeClient(response))
    backend = OllamaBackend(default_model="qwen3:4b")
    return asyncio.run(backend.chat([{"role": "user", "content": "Hallo"}]))


def test_ollama_chat_returns_nonempty_content(monkeypatch):
    result = _run_chat(monkeypatch, {"message": {"content": "Antwort"}})
    assert result["content"] == "Antwort"


def test_ollama_chat_hides_disabled_thinking(monkeypatch):
    response = _FakeResponse({"message": {"content": "interner Text\n</think>\n\nOK"}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeClient(response))
    backend = OllamaBackend(default_model="qwen3:4b")

    result = asyncio.run(
        backend.chat([{"role": "user", "content": "Hallo"}], think=False)
    )

    assert result["content"] == "OK"


@pytest.mark.parametrize("payload", [
    {"message": {"content": ""}},
    {"status": "ok"},
])
def test_ollama_chat_rejects_empty_success(monkeypatch, payload):
    with pytest.raises(RuntimeError, match="leere Antwort"):
        _run_chat(monkeypatch, payload)


def test_ollama_chat_propagates_api_error(monkeypatch):
    with pytest.raises(RuntimeError, match="Modell fehlt"):
        _run_chat(monkeypatch, {"error": "Modell fehlt"})


def test_ollama_chat_propagates_http_error(monkeypatch):
    with pytest.raises(httpx.HTTPStatusError):
        _run_chat(monkeypatch, {"error": "not found"}, status_code=404)


def test_ollama_chat_bounds_context_in_request(monkeypatch):
    requests = []
    response = _FakeResponse({"message": {"content": "Antwort"}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda: _FakeClient(response, requests))

    backend = OllamaBackend(default_model="qwen3:4b", num_ctx=8192)
    asyncio.run(backend.chat([{"role": "user", "content": "Hallo"}]))

    assert requests[0]["json"]["options"] == {"num_ctx": 8192}
    assert requests[0]["timeout"] == 900


def test_ollama_context_defaults_to_bounded_environment_value(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    assert OllamaBackend().num_ctx == 4096

    monkeypatch.setenv("OLLAMA_NUM_CTX", "6144")
    assert OllamaBackend().num_ctx == 6144


def test_ollama_timeout_is_configurable(monkeypatch):
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)
    assert OllamaBackend().request_timeout == 600

    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "45.5")
    assert OllamaBackend().request_timeout == 45.5


@pytest.mark.parametrize("num_ctx", ["kein-wert", 0, 262145])
def test_ollama_context_rejects_invalid_values(num_ctx):
    with pytest.raises(ValueError, match="num_ctx"):
        OllamaBackend(num_ctx=num_ctx)


@pytest.mark.parametrize("timeout", ["kein-wert", 0, 3601])
def test_ollama_timeout_rejects_invalid_values(timeout):
    with pytest.raises(ValueError, match="request_timeout"):
        OllamaBackend(request_timeout=timeout)


def test_ollama_timeout_has_clear_error(monkeypatch):
    class _TimeoutClient(_FakeClient):
        async def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", lambda: _TimeoutClient(None))
    backend = OllamaBackend(request_timeout=12)

    with pytest.raises(RuntimeError, match="12 Sekunden"):
        asyncio.run(backend.chat([{"role": "user", "content": "Hallo"}], think=False))
