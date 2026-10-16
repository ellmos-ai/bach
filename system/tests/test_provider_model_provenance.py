"""Behavioral checks for provider-reported model provenance."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.llm.model_backend import (  # noqa: E402
    AnthropicBackend,
    CLIBackend,
    HermesBackend,
    LMStudioBackend,
    OllamaBackend,
    OpenAIBackend,
    OpenRouterBackend,
)
from hub._services.model_provenance import reported_model  # noqa: E402


_MISSING = object()
_MESSAGES = [{"role": "user", "content": "Say hello."}]


class _JsonResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://fixture.invalid/chat")
            response = httpx.Response(
                self.status_code, request=request, json=self.payload
            )
            raise httpx.HTTPStatusError(
                "fixture HTTP failure", request=request, response=response
            )


class _StreamResponse:
    status_code = 200
    headers = {}

    def __init__(self, lines):
        self.lines = list(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self.lines:
            if isinstance(line, BaseException):
                raise line
            yield line if isinstance(line, str) else json.dumps(line)


class _FakeHTTPClient:
    """In-memory httpx transport; it never opens a socket."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def _next_response(self):
        assert self.responses, "unexpected extra HTTP request"
        return self.responses.pop(0)

    async def post(self, *args, **kwargs):
        self.calls.append({"method": "post", "args": args, "kwargs": kwargs})
        return self._next_response()

    def stream(self, *args, **kwargs):
        self.calls.append({"method": "stream", "args": args, "kwargs": kwargs})
        return self._next_response()


def _openai_reply(model=_MISSING):
    reply = {
        "choices": [{
            "message": {"role": "assistant", "content": "hello"}
        }]
    }
    if model is not _MISSING:
        reply["model"] = model
    return reply


def _anthropic_reply(model=_MISSING):
    reply = {"content": [{"type": "text", "text": "hello"}]}
    if model is not _MISSING:
        reply["model"] = model
    return reply


def _http_backend(provider):
    if provider == "openai":
        return OpenAIBackend(
            base_url="https://openai.fixture/v1",
            api_key="fixture-key",
            default_model="requested-model",
        ), "requested-model"
    if provider == "lmstudio":
        return LMStudioBackend(
            base_url="https://lmstudio.fixture/v1",
            api_key="fixture-key",
            default_model="requested-model",
        ), "requested-model"
    if provider == "hermes":
        return HermesBackend(
            base_url="https://hermes.fixture/v1",
            api_key="fixture-key",
            default_model="requested-model",
        ), "requested-model"
    if provider == "openrouter":
        return OpenRouterBackend(
            base_url="https://openrouter.ai/api/v1",
            api_key="fixture-key",
            default_model="openrouter/free",
        ), "openrouter/free"
    if provider == "anthropic":
        return AnthropicBackend(
            api_key="fixture-key", default_model="requested-model"
        ), "requested-model"
    raise AssertionError(f"unknown fixture provider: {provider}")


def _reply_for(provider, model=_MISSING):
    if provider == "anthropic":
        return _anthropic_reply(model)
    return _openai_reply(model)


@pytest.mark.parametrize(
    ("provider", "reported"),
    [
        ("openai", "vendor/served-model-1"),
        ("lmstudio", "local/loaded-model"),
        ("hermes", "nousresearch/served-model"),
        ("openrouter", "provider/selected-free-model"),
        ("anthropic", "claude-served-model"),
    ],
)
def test_http_chat_reports_the_current_response_model_without_changing_request(
    monkeypatch, provider, reported
):
    backend, requested = _http_backend(provider)
    client = _FakeHTTPClient([_JsonResponse(_reply_for(provider, reported))])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: client)

    result = asyncio.run(backend.chat(_MESSAGES, model=requested))

    assert result["provider_reported_model"] == reported
    assert result["model"] == reported
    call = client.calls[0]
    assert call["method"] == "post"
    assert call["kwargs"]["json"]["model"] == requested


@pytest.mark.parametrize(
    "provider", ["openai", "lmstudio", "hermes", "openrouter", "anthropic"]
)
@pytest.mark.parametrize(
    "second_model",
    [_MISSING, None, "", " model-with-padding ", "https://vendor.invalid/model"],
    ids=["missing", "null", "blank", "untrimmed", "url"],
)
def test_http_chat_does_not_reuse_a_previous_response_model(
    monkeypatch, provider, second_model
):
    backend, requested = _http_backend(provider)
    client = _FakeHTTPClient([
        _JsonResponse(_reply_for(provider, "vendor/first-response")),
        _JsonResponse(_reply_for(provider, second_model)),
    ])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: client)

    first = asyncio.run(backend.chat(_MESSAGES, model=requested))
    second = asyncio.run(backend.chat(_MESSAGES, model=requested))

    assert first["provider_reported_model"] == "vendor/first-response"
    assert second["provider_reported_model"] is None
    expected_display_model = (
        second_model
        if second_model is not _MISSING and second_model
        else requested
    )
    assert second["model"] == expected_display_model
    assert client.calls[0]["kwargs"]["json"]["model"] == requested
    assert client.calls[1]["kwargs"]["json"]["model"] == requested


@pytest.mark.parametrize(
    "value",
    [
        None,
        7,
        True,
        "",
        " ",
        " padded ",
        "x" * 257,
        "provider\nmodel",
        "provider\x00model",
        "provider\x7fmodel",
        "https://provider.invalid/model",
        "www.provider.invalid/model",
    ],
)
def test_reported_model_rejects_unusable_provider_values(value):
    assert reported_model(value) is None


def test_reported_model_preserves_a_clean_literal_identifier():
    assert reported_model("provider/model:revision-2") == "provider/model:revision-2"


def _ollama_backend_and_client(monkeypatch, streams):
    client = _FakeHTTPClient([_StreamResponse(lines) for lines in streams])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: client)
    backend = OllamaBackend(
        base_url="http://ollama.fixture:11434", default_model="requested-model"
    )
    return backend, client


def test_ollama_reports_model_seen_in_any_chunk_and_ignores_missing_fields(
    monkeypatch,
):
    backend, client = _ollama_backend_and_client(monkeypatch, [[
        {"model": "ollama/served-model", "message": {"content": "hello "}},
        {"message": {"content": "world"}, "done": True},
    ]])

    result = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert result["content"] == "hello world"
    assert result["model"] == "requested-model"
    assert result["provider_reported_model"] == "ollama/served-model"
    call = client.calls[0]
    assert call["method"] == "stream"
    assert call["kwargs"]["json"]["model"] == "requested-model"


@pytest.mark.parametrize(
    "lines",
    [
        [
            {"model": "ollama/model-a", "message": {"content": "hello"}},
            {"model": "ollama/model-b", "done": True},
        ],
        [
            {"model": " padded-model ", "message": {"content": "hello"}},
            {"done": True},
        ],
        [
            {"model": 12, "message": {"content": "hello"}},
            {"done": True},
        ],
        ["not-json", {"message": {"content": "hello"}, "done": True}],
    ],
    ids=["conflicting-models", "untrimmed-model", "non-string-model", "malformed-chunk"],
)
def test_ollama_invalid_or_conflicting_stream_evidence_is_unavailable(
    monkeypatch, lines
):
    backend, _client = _ollama_backend_and_client(monkeypatch, [lines])

    result = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert result["provider_reported_model"] is None


def test_ollama_requires_at_least_one_reported_model_value(monkeypatch):
    backend, _client = _ollama_backend_and_client(monkeypatch, [[
        {"message": {"content": "hello"}, "done": True},
    ]])

    result = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert result["content"] == "hello"
    assert result["provider_reported_model"] is None


def test_ollama_does_not_report_a_model_from_an_incomplete_stream(monkeypatch):
    backend, _client = _ollama_backend_and_client(monkeypatch, [[
        {"model": "ollama/served-model", "message": {"content": "partial"}},
    ]])

    result = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert result["error"]
    assert result["provider_reported_model"] is None


def test_ollama_does_not_report_a_model_after_provider_stream_error(monkeypatch):
    backend, _client = _ollama_backend_and_client(monkeypatch, [[
        {
            "model": "ollama/served-model",
            "message": {"content": "partial"},
            "error": "fixture stream failure",
        },
    ]])

    result = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert result["error"]
    assert result["provider_reported_model"] is None


def test_ollama_does_not_reuse_a_model_from_an_earlier_stream(monkeypatch):
    backend, _client = _ollama_backend_and_client(monkeypatch, [
        [
            {"model": "ollama/first-model", "message": {"content": "first"}},
            {"done": True},
        ],
        [{"message": {"content": "second"}, "done": True}],
    ])

    first = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))
    second = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert first["provider_reported_model"] == "ollama/first-model"
    assert second["provider_reported_model"] is None


def test_ollama_stream_transport_exception_is_not_model_evidence(monkeypatch):
    backend, _client = _ollama_backend_and_client(monkeypatch, [[
        {"model": "ollama/served-model", "message": {"content": "partial"}},
        httpx.ReadError("fixture disconnect"),
    ]])

    result = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert result["error"]
    assert result["provider_reported_model"] is None


def test_cli_stdout_cannot_claim_provider_reported_model(monkeypatch):
    backend = CLIBackend(
        cli_name="claude",
        cli_path="fixture-cli",
        default_model="requested-model",
        cwd=".",
    )
    stdout = "Model: provider/served-model\nHello from fixture CLI"

    async def fake_cli_transport(_prompt, model=None):
        assert model == "requested-model"
        return stdout

    monkeypatch.setattr(backend, "_run_cli", fake_cli_transport)

    result = asyncio.run(backend.chat(_MESSAGES, model="requested-model"))

    assert result["content"] == stdout
    assert result["provider_reported_model"] is None
