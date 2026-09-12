# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the web-scrape provider seam (T-20260818-903104603, unit 4a).

The contract under test comes from ellmos-homebase-mcp/MODE-CONTRACT.md:

    mode = canonical + target unreachable  =>  clear error.
    NEVER a silent switch back to the legacy path.

The silent-fallback case is the one that matters. A fallback would report success
while a different implementation answered, so an intended migration could sit broken
for months without anyone noticing. These tests therefore assert not just *that* it
fails, but that the legacy path is not reached.

No network: the canonical module is stubbed, and the legacy path is asserted through
a sentinel rather than by making a request.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.web_scrape import (  # noqa: E402
    ENGINE_BUNDLED,
    ENGINE_CANONICAL,
    ENGINE_DEFAULT,
    ENGINE_ENV,
    CanonicalEngineUnavailable,
    CanonicalResponse,
    EngineConfigError,
    WebScrapeHandler,
    resolve_engine,
)


@pytest.fixture
def handler(tmp_path):
    return WebScrapeHandler(tmp_path)


# --- engine resolution ---------------------------------------------------------------

def test_default_is_the_canonical_module():
    """The default moved only after the last limit could be aligned.

    Equivalence in the success case was not enough: the module used to follow up to
    10 redirects against MAX_REDIRECTS = 5 here, with no way to pass the caller's
    limit. That gap was closed in the module (web-scraper PR #2) rather than by
    relaxing this side, and only then did the default move.
    """
    assert ENGINE_DEFAULT == ENGINE_CANONICAL
    assert resolve_engine({}) == ENGINE_CANONICAL


def test_all_limits_of_this_handler_are_passed_to_the_module(handler, monkeypatch):
    """The reason the default may be canonical at all.

    If any of the three stopped being forwarded, this handler's declared boundaries
    would silently become the module's defaults.
    """
    monkeypatch.setenv(ENGINE_ENV, ENGINE_CANONICAL)
    seen = {}

    class _Scraper:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def get(self, url):
            return {"operation": "get", "url": url, "status": 200,
                    "content_type": "text/plain", "body": ""}

    module = MagicMock()
    module.WebScraper = _Scraper
    monkeypatch.setitem(sys.modules, "web_scraper", module)

    handler.handle("get", ["https://example.org/"])

    assert seen["timeout"] == handler.REQUEST_TIMEOUT
    assert seen["max_bytes"] == handler.MAX_RESPONSE_BYTES
    assert seen["max_redirects"] == handler.MAX_REDIRECTS


def test_empty_value_falls_back_to_the_default():
    assert resolve_engine({ENGINE_ENV: "  "}) == ENGINE_DEFAULT


def test_legacy_path_stays_explicitly_selectable():
    """The BACH-internal path is a full fallback, not a retired branch."""
    assert resolve_engine({ENGINE_ENV: ENGINE_BUNDLED}) == ENGINE_BUNDLED


def test_canonical_is_selectable_case_insensitively():
    assert resolve_engine({ENGINE_ENV: "CANONICAL"}) == ENGINE_CANONICAL


def test_unknown_value_fails_closed():
    """A typo must not quietly read as 'legacy path'.

    Otherwise a deliberate `canonical` and a misspelled one are indistinguishable from
    the outside -- both would just keep using the old code.
    """
    with pytest.raises(EngineConfigError) as excinfo:
        resolve_engine({ENGINE_ENV: "canonicle"})
    assert "canonicle" in str(excinfo.value)
    assert ENGINE_CANONICAL in str(excinfo.value)


# --- the fail-closed contract --------------------------------------------------------

def test_canonical_without_the_module_raises_and_does_not_touch_the_legacy_path(
    handler, monkeypatch
):
    """The core of the contract: loud failure, no silent fallback."""
    monkeypatch.setenv(ENGINE_ENV, ENGINE_CANONICAL)

    def _legacy_must_not_run(*_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("the legacy path ran although canonical was selected")

    monkeypatch.setattr(handler, "_request_bundled", _legacy_must_not_run)
    monkeypatch.setitem(sys.modules, "web_scraper", None)  # forces ImportError

    with pytest.raises(CanonicalEngineUnavailable) as excinfo:
        handler._request("https://example.invalid/")

    message = str(excinfo.value)
    assert "web-scraper" in message
    assert ENGINE_ENV in message, "the message must name the switch that caused this"


def test_handle_turns_the_unavailable_engine_into_a_clear_failure(handler, monkeypatch):
    """Per the contract the failure surfaces on the call, not at import time."""
    monkeypatch.setenv(ENGINE_ENV, ENGINE_CANONICAL)
    monkeypatch.setitem(sys.modules, "web_scraper", None)

    ok, message = handler.handle("get", ["https://example.invalid/"])

    assert ok is False
    assert "web-scraper" in message
    assert ENGINE_BUNDLED in message, "the message must say how to get back to a working state"


def test_operations_are_still_listed_when_the_engine_is_unavailable(handler, monkeypatch):
    """The handler keeps loading; only the actual call fails."""
    monkeypatch.setenv(ENGINE_ENV, ENGINE_CANONICAL)
    monkeypatch.setitem(sys.modules, "web_scraper", None)

    assert set(handler.get_operations()) == {"get", "links", "forms", "screenshot", "headers"}


def test_unknown_engine_value_fails_the_call_too(handler, monkeypatch):
    monkeypatch.setenv(ENGINE_ENV, "nonsense")

    ok, message = handler.handle("get", ["https://example.invalid/"])

    assert ok is False
    assert "nonsense" in message


# --- the adapter ---------------------------------------------------------------------

def test_canonical_response_maps_the_modules_get_dict():
    """The module returns a **dict**, not a response object.

    This is recorded from a real call. An earlier version of the adapter assumed
    attributes and passed its tests against a MagicMock -- a mock takes any shape,
    including one that does not exist. Against a real page it raised AttributeError.
    Hence a recorded payload here instead of a mock.
    """
    payload = {
        "operation": "get",
        "url": "https://example.org/x",
        "status": 200,
        "content_type": "text/plain; charset=utf-8",
        "length": 13,
        "truncated": False,
        "body": "<html></html>",
    }

    adapted = CanonicalResponse(payload)

    assert adapted.status_code == 200
    assert adapted.url == "https://example.org/x"
    assert adapted.text == "<html></html>"
    assert adapted.headers == {"content-type": "text/plain; charset=utf-8"}


def test_canonical_response_maps_the_modules_headers_dict():
    """`get` carries only the content type, so `headers` uses its own operation."""
    payload = {
        "operation": "headers",
        "url": "https://example.org/x",
        "status": 200,
        "headers": {"Connection": "keep-alive", "Content-Type": "text/plain"},
    }

    adapted = CanonicalResponse(payload)

    assert adapted.status_code == 200
    assert adapted.headers == {"Connection": "keep-alive", "Content-Type": "text/plain"}
    assert adapted.text == ""


def test_canonical_response_rejects_a_non_dict():
    """Guards the assumption that broke the first adapter."""
    with pytest.raises(TypeError) as excinfo:
        CanonicalResponse(MagicMock())
    assert "dict" in str(excinfo.value)


def test_canonical_path_feeds_the_existing_operations(handler, monkeypatch):
    """With the module present, the untouched operations work on the adapted response."""
    monkeypatch.setenv(ENGINE_ENV, ENGINE_CANONICAL)

    scraper = MagicMock()
    scraper.get.return_value = {
        "operation": "get",
        "url": "https://example.org/",
        "status": 200,
        "content_type": "text/html",
        "body": '<a href="/a">A</a><a href="/b">B</a>',
    }
    fake_module = MagicMock()
    fake_module.WebScraper.return_value = scraper
    monkeypatch.setitem(sys.modules, "web_scraper", fake_module)

    ok, body = handler.handle("links", ["https://example.org/"])

    assert ok is True
    assert "/a" in body and "/b" in body
    scraper.get.assert_called_once_with("https://example.org/")


def test_legacy_path_is_used_when_explicitly_selected(handler, monkeypatch):
    """Choosing the fallback really reaches the BACH-internal implementation."""
    monkeypatch.setenv(ENGINE_ENV, ENGINE_BUNDLED)
    sentinel = object()
    monkeypatch.setattr(handler, "_request_bundled", lambda url: (sentinel, ""))

    response, error = handler._request("https://example.org/")

    assert response is sentinel
    assert error == ""


# --- equivalence between the two engines ---------------------------------------------

RECORDED_GET = {
    "operation": "get",
    "url": "https://raw.githubusercontent.com/ellmos-ai/web-scraper/main/README.md",
    "status": 200,
    "content_type": "text/plain; charset=utf-8",
    "length": 6467,
    "truncated": False,
    "body": "# web-scraper\n\n[English](README.md) | [Deutsch](README_de.md)\n",
}


def test_recorded_canonical_payload_produces_the_expected_output(handler, monkeypatch):
    """Offline half of the equivalence proof, recorded from a real call.

    Keeps the mapping honest without needing the network on every run: the payload is
    what the module actually returned, and the assertions are what the untouched BACH
    operation makes of it.
    """
    monkeypatch.setenv(ENGINE_ENV, ENGINE_CANONICAL)
    scraper = MagicMock()
    scraper.get.return_value = RECORDED_GET
    module = MagicMock()
    module.WebScraper.return_value = scraper
    monkeypatch.setitem(sys.modules, "web_scraper", module)

    ok, body = handler.handle("get", [RECORDED_GET["url"]])

    assert ok is True
    assert f"Status: {RECORDED_GET['status']}" in body
    assert RECORDED_GET["content_type"] in body
    assert "# web-scraper" in body


def _network_available() -> bool:
    import socket
    try:
        socket.create_connection(("raw.githubusercontent.com", 443), timeout=5).close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _network_available(), reason="no network")
def test_both_engines_agree_against_a_real_page(handler, monkeypatch):
    """The measurement behind the default switch, repeatable.

    One small idempotent GET per engine against our own raw README. Compared after
    normalising the two things that legitimately differ between two fetches: the byte
    count and the volatile response headers.
    """
    import re

    url = RECORDED_GET["url"]

    def fetch(engine: str, operation: str) -> str:
        monkeypatch.setenv(ENGINE_ENV, engine)
        ok, body = handler.handle(operation, [url])
        assert ok, f"{engine}/{operation} failed: {body}"
        return body

    def normalise(text: str) -> str:
        text = re.sub(r"Größe: \d+ Zeichen", "Größe: <n> Zeichen", text)
        text = re.sub(
            r"(?im)^\s*(date|age|x-[a-z-]+|via|expires|last-modified|etag|cache-control|"
            r"content-length|accept-ranges|vary|server|strict-transport-security|"
            r"cross-origin-[a-z-]+|source-age|content-security-policy)\s*:.*$",
            "", text,
        )
        return re.sub(r"\n{2,}", "\n", text).strip()

    for operation in ("get", "links", "forms", "headers"):
        bundled = normalise(fetch(ENGINE_BUNDLED, operation))
        canonical = normalise(fetch(ENGINE_CANONICAL, operation))
        assert bundled == canonical, f"engines disagree on {operation}"
