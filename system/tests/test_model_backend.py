# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Truthful result handling for local Ollama chat responses."""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm.model_backend import (  # noqa: E402
    AnthropicBackend,
    CLIBackend,
    LMStudioBackend,
    HermesBackend,
    OllamaBackend,
    OpenAIBackend,
    backend_identifier,
    create_backend,
)


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


def test_ollama_availability_requires_reachable_selected_model(monkeypatch):
    response = _FakeResponse({"models": [{"name": "qwen3:4b"}]})
    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: response)
    backend = OllamaBackend(default_model="qwen3:4b")

    assert backend.availability() == (True, "bereit")

    available, status = backend.availability(model="anderes:latest")
    assert available is False
    assert status == "Modell fehlt: anderes:latest"


def test_ollama_availability_reports_unreachable_without_raising(monkeypatch):
    request = httpx.Request("GET", "http://127.0.0.1:11434/api/tags")

    def fail(*_args, **_kwargs):
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(httpx, "get", fail)

    assert OllamaBackend().availability() == (False, "nicht erreichbar")


def test_configured_api_and_cli_availability_is_truthful(monkeypatch, tmp_path):
    missing_cli = tmp_path / "nicht-installiert.exe"
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert CLIBackend(cli_name="codex", cli_path=str(missing_cli)).availability() == (
        False,
        "nicht gefunden",
    )
    assert OpenAIBackend(api_key="").availability() == (False, "Key fehlt")
    assert OpenAIBackend(api_key="   ").availability() == (False, "Key fehlt")


@pytest.mark.parametrize(
    "backend",
    [
        OpenAIBackend(api_key="test-openai-key", default_model="gpt-test"),
        AnthropicBackend(api_key="test-anthropic-key", default_model="claude-test"),
    ],
)
def test_api_availability_fails_closed_when_readiness_probe_fails(
    monkeypatch,
    backend,
):
    request = httpx.Request("GET", "https://provider.invalid/v1/models")
    probe = MagicMock(side_effect=httpx.ConnectError("offline", request=request))
    monkeypatch.setattr(httpx, "get", probe)

    available, status = backend.availability(timeout=0.25)

    assert available is False
    assert status == "nicht erreichbar"
    assert backend.api_key not in status
    probe.assert_called_once()


@pytest.mark.parametrize(
    ("backend", "expected_url", "expected_header"),
    [
        (
            OpenAIBackend(api_key="test-openai-key", default_model="gpt-test"),
            "https://api.openai.com/v1/models",
            ("Authorization", "Bearer test-openai-key"),
        ),
        (
            AnthropicBackend(api_key="test-anthropic-key", default_model="claude-test"),
            "https://api.anthropic.com/v1/models",
            ("x-api-key", "test-anthropic-key"),
        ),
    ],
)
def test_api_availability_requires_successful_model_probe(
    monkeypatch,
    backend,
    expected_url,
    expected_header,
):
    probe = MagicMock(
        return_value=_FakeResponse({"data": [{"id": backend.default_model}]})
    )
    monkeypatch.setattr(httpx, "get", probe)

    assert backend.availability(timeout=0.25) == (True, "bereit")

    probe.assert_called_once()
    args, kwargs = probe.call_args
    assert args == (expected_url,)
    assert kwargs["headers"][expected_header[0]] == expected_header[1]
    assert kwargs["timeout"] == 0.25


@pytest.mark.parametrize(
    ("cli_name", "readiness_args"),
    [
        ("claude", ["auth", "status"]),
        ("codex", ["login", "status"]),
    ],
)
def test_cli_availability_requires_successful_auth_probe(
    monkeypatch,
    tmp_path,
    cli_name,
    readiness_args,
):
    cli_path = tmp_path / f"{cli_name}.exe"
    cli_path.write_text("test executable placeholder", encoding="utf-8")
    probe = MagicMock(return_value=SimpleNamespace(returncode=1))
    monkeypatch.setattr(subprocess, "run", probe)
    backend = CLIBackend(cli_name=cli_name, cli_path=str(cli_path))

    available, status = backend.availability(timeout=0.25)

    assert available is False
    assert status == "Anmeldung nicht bestätigt"
    args, kwargs = probe.call_args
    assert args[0] == [str(cli_path), *readiness_args]
    assert kwargs["timeout"] == 0.25
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE

    probe.return_value = SimpleNamespace(returncode=0)
    assert backend.availability(timeout=0.25) == (True, "bereit")


@pytest.mark.parametrize(
    ("backend", "expected"),
    [
        (LMStudioBackend(), "lmstudio"),
        (HermesBackend(), "hermes"),
        (OllamaBackend(), "ollama"),
        (CLIBackend(cli_name="claude", cli_path="claude"), "claude"),
        (CLIBackend(cli_name="codex", cli_path="codex"), "codex"),
        (OpenAIBackend(api_key="gesetzt"), "openai"),
        (AnthropicBackend(api_key="gesetzt"), "claude-api"),
    ],
)
def test_backend_identifier_matches_control_api_keys(backend, expected):
    assert backend_identifier(backend) == expected


def test_lmstudio_factory_and_defaults():
    backend = create_backend({"type": "lmstudio"})
    assert isinstance(backend, LMStudioBackend)
    assert backend.base_url == "http://localhost:1234/v1"
    assert backend.api_key == "lm-studio"
    assert backend.default_model == "auto"

    backend2 = create_backend({"type": "lm-studio", "base_url": "http://127.0.0.1:1234/v1"})
    assert isinstance(backend2, LMStudioBackend)
    assert backend2.base_url == "http://127.0.0.1:1234/v1"


def test_lmstudio_model_autodetection_and_chat(monkeypatch):
    class FakeSyncResponse:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._payload

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/models"):
            return FakeSyncResponse({
                "data": [
                    {"id": "qwen2.5-coder-7b", "state": "loaded"},
                    {"id": "deepseek-coder-6.7b"},
                ]
            })
        raise ValueError(f"Unexpected GET URL: {url}")

    captured_requests = []
    fake_client = _FakeClient(
        _FakeResponse({
            "choices": [{"message": {"role": "assistant", "content": "Antwort von LM Studio"}}]
        }),
        requests=captured_requests,
    )

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "AsyncClient", lambda: fake_client)

    backend = LMStudioBackend()
    models = backend.list_models()
    assert models == ["qwen2.5-coder-7b", "deepseek-coder-6.7b"]
    assert backend.get_default_model() == "qwen2.5-coder-7b"

    result = asyncio.run(backend.chat([{"role": "user", "content": "Hallo LM"}]))
    assert result["content"] == "Antwort von LM Studio"
    assert captured_requests[0]["json"]["model"] == "qwen2.5-coder-7b"


def test_lmstudio_availability(monkeypatch):
    backend = LMStudioBackend()

    # Fall 1: Bereit mit Modellen
    monkeypatch.setattr(
        httpx,
        "get",
        lambda _url, headers=None, timeout=None: _FakeResponse({
            "data": [{"id": "qwen2.5-coder-7b"}]
        }),
    )
    ok, msg = backend.availability()
    assert ok is True
    assert msg == "bereit"

    # Fall 2: Spezielles Modell fehlt
    ok, msg = backend.availability(model="llama-3")
    assert ok is False
    assert "Modell fehlt: llama-3" in msg

    # Fall 3: Keine Modelle in LM Studio
    monkeypatch.setattr(
        httpx,
        "get",
        lambda _url, headers=None, timeout=None: _FakeResponse({"data": []}),
    )
    ok, msg = backend.availability()
    assert ok is False
    assert "keine Modelle" in msg

    # Fall 4: Server nicht erreichbar
    def fake_error(_url, headers=None, timeout=None):
        raise httpx.ConnectError("LM Studio nicht erreichbar")

    monkeypatch.setattr(httpx, "get", fake_error)
    ok, msg = backend.availability()
    assert ok is False
    assert msg == "nicht erreichbar"


def test_hermes_factory_and_defaults():
    backend = create_backend({"type": "hermes", "api_key": "sk-or-test"})
    assert isinstance(backend, HermesBackend)
    assert backend.base_url == "https://openrouter.ai/api/v1"
    assert backend.default_model == "nousresearch/hermes-3-llama-3.1-8b"
    headers = backend._get_headers()
    assert headers["Authorization"] == "Bearer sk-or-test"
    assert headers["HTTP-Referer"] == "https://github.com/ellmos-ai/bach"
    assert headers["X-Title"] == "BACH Agent"


def test_hermes_xml_tool_call_fallback(monkeypatch):
    raw_xml_reply = (
        "Ich prüfe den Status:\n"
        "<tool_call>\n"
        '{"name": "system_status", "arguments": {}}\n'
        "</tool_call>\n"
        "Ergebnis folgt."
    )
    fake_client = _FakeClient(
        _FakeResponse({
            "choices": [{"message": {"role": "assistant", "content": raw_xml_reply}}]
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda: fake_client)

    backend = HermesBackend(api_key="test-key")
    res = asyncio.run(backend.chat([{"role": "user", "content": "status"}]))
    assert res["tool_calls"] is not None
    assert len(res["tool_calls"]) == 1
    assert res["tool_calls"][0]["function"]["name"] == "system_status"
    assert "<tool_call>" not in res["content"]
    assert "Ich prüfe den Status:" in res["content"]


def test_hermes_thought_handling(monkeypatch):
    thought_reply = (
        "<thought>\n"
        "Plan: Zuerst Information abrufen, dann zusammenfassen.\n"
        "</thought>\n"
        "Hier ist das Ergebnis."
    )
    fake_client = _FakeClient(
        _FakeResponse({
            "choices": [{"message": {"role": "assistant", "content": thought_reply}}]
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda: fake_client)

    backend = HermesBackend(api_key="test-key")
    res = asyncio.run(backend.chat([{"role": "user", "content": "frage"}], think=False))
    assert "<thought>" not in res["content"]
    assert res["content"] == "Hier ist das Ergebnis."
    assert "Zuerst Information abrufen" in res["raw_message"]["thought"]
