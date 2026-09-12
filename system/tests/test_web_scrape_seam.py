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

def test_default_is_the_legacy_path():
    """Without configuration nothing changes for existing installations."""
    assert resolve_engine({}) == ENGINE_BUNDLED


def test_empty_value_is_the_legacy_path():
    assert resolve_engine({ENGINE_ENV: "  "}) == ENGINE_BUNDLED


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

def test_canonical_response_maps_the_status_field():
    """The only naming difference between the two sides.

    The module calls it `status`, this handler reads `status_code`; everything else
    already matches. If that ever diverges further, this test is where it shows.
    """
    module_response = MagicMock()
    module_response.url = "https://example.org/x"
    module_response.status = 200
    module_response.headers = {"content-type": "text/html"}
    module_response.text = "<html></html>"

    adapted = CanonicalResponse(module_response)

    assert adapted.status_code == 200
    assert adapted.url == "https://example.org/x"
    assert adapted.headers == {"content-type": "text/html"}
    assert adapted.text == "<html></html>"


def test_canonical_path_feeds_the_existing_operations(handler, monkeypatch):
    """With the module present, the untouched operations work on the adapted response."""
    monkeypatch.setenv(ENGINE_ENV, ENGINE_CANONICAL)

    module_response = MagicMock()
    module_response.url = "https://example.org/"
    module_response.status = 200
    module_response.headers = {"content-type": "text/html"}
    module_response.text = '<a href="/a">A</a><a href="/b">B</a>'

    scraper = MagicMock()
    scraper.get.return_value = module_response
    fake_module = MagicMock()
    fake_module.WebScraper.return_value = scraper
    monkeypatch.setitem(sys.modules, "web_scraper", fake_module)

    ok, body = handler.handle("links", ["https://example.org/"])

    assert ok is True
    assert "/a" in body and "/b" in body
    scraper.get.assert_called_once_with("https://example.org/")


def test_legacy_path_is_used_when_nothing_is_configured(handler, monkeypatch):
    """Existing installations keep the old behaviour until equivalence is proven."""
    monkeypatch.delenv(ENGINE_ENV, raising=False)
    sentinel = object()
    monkeypatch.setattr(handler, "_request_bundled", lambda url: (sentinel, ""))

    response, error = handler._request("https://example.org/")

    assert response is sentinel
    assert error == ""
