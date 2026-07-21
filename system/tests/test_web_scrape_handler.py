# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for WebScrapeHandler (hub/web_scrape.py)."""

import sys
import types
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.web_scrape import WebScrapeHandler


class FakeResponse:
    def __init__(self, url, status_code=200, headers=None, body=b"", is_redirect=False):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.is_redirect = is_redirect
        self.closed = False
        self._content = None
        self._content_consumed = False
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        for idx in range(0, len(self._body), chunk_size):
            yield self._body[idx:idx + chunk_size]

    def close(self):
        self.closed = True

    @property
    def text(self):
        content = self._content if self._content is not None else self._body
        return content.decode(self.encoding)


class FakeHTTPAdapter:
    def __init__(self, *args, **kwargs):
        self.pool_kwargs = {}
        self.init_poolmanager(10, 10)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.pool_kwargs = pool_kwargs


class FakeSession:
    def __init__(self, owner):
        self.owner = owner
        self.trust_env = True
        self.mounts = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def mount(self, prefix, adapter):
        self.mounts[prefix] = adapter

    def get(self, url, **kwargs):
        return self.owner.get(url, **kwargs)


class FakeChromeOptions:
    def __init__(self):
        self.arguments = []
        self.experimental_options = {}

    def add_argument(self, argument):
        self.arguments.append(argument)

    def add_experimental_option(self, name, value):
        self.experimental_options[name] = value


class FakeChromeDriver:
    def __init__(self):
        self.cdp_calls = []
        self.navigations = []
        self.saved_path = None
        self.quit_called = False

    def execute_cdp_cmd(self, command, params):
        self.cdp_calls.append((command, params))
        if command == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "frame-1"}}}
        return {}

    def get(self, url):
        self.navigations.append(url)

    def save_screenshot(self, path):
        self.saved_path = path
        Path(path).write_bytes(b"fake-png")
        return True

    def quit(self):
        self.quit_called = True


class FakeRequests:
    class exceptions:
        class SSLError(Exception):
            pass

    class adapters:
        HTTPAdapter = FakeHTTPAdapter

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.sessions = []

    def Session(self):
        session = FakeSession(self)
        self.sessions.append(session)
        return session

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("Keine Fake-Responses mehr vorhanden")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        response.url = url
        return response


@pytest.fixture
def ws_env(tmp_path):
    base = tmp_path / "bach" / "system"
    data = base / "data"
    scrape = data / "cache" / "scrape"
    scrape.mkdir(parents=True)
    (data / "bach.db").write_bytes(b"")
    return WebScrapeHandler(base)


class TestWebScrapeSecurity:
    def test_request_blocks_localhost_before_fetch(self, ws_env, monkeypatch):
        fake_requests = FakeRequests([])
        monkeypatch.setitem(sys.modules, "requests", fake_requests)

        resp, err = ws_env._request("http://localhost:8000/secret")

        assert resp is None
        assert "nicht erlaubt" in err
        assert fake_requests.calls == []

    def test_request_rejects_embedded_credentials_before_fetch(self, ws_env, monkeypatch):
        fake_requests = FakeRequests([])
        monkeypatch.setitem(sys.modules, "requests", fake_requests)

        resp, err = ws_env._request("https://user:secret@example.com/")

        assert resp is None
        assert "Zugangsdaten" in err
        assert fake_requests.calls == []

    def test_request_blocks_private_redirect_target(self, ws_env, monkeypatch):
        fake_requests = FakeRequests([
            FakeResponse(
                "https://example.com/start",
                status_code=302,
                headers={"Location": "http://127.0.0.1:8000/admin"},
                is_redirect=True,
            )
        ])
        monkeypatch.setitem(sys.modules, "requests", fake_requests)

        def fake_getaddrinfo(hostname, port, proto=0):
            if hostname == "example.com":
                return [(None, None, None, None, ("93.184.216.34", port))]
            raise AssertionError(f"Unerwartete DNS-Auflösung: {hostname}")

        monkeypatch.setattr("hub.web_scrape.socket.getaddrinfo", fake_getaddrinfo)

        resp, err = ws_env._request("https://example.com/start")

        assert resp is None
        assert "Unsicheres Redirect-Ziel" in err
        assert len(fake_requests.calls) == 1
        assert fake_requests.calls[0]["allow_redirects"] is False
        assert fake_requests.calls[0]["url"] == "https://93.184.216.34/start"
        assert fake_requests.calls[0]["headers"]["Host"] == "example.com"
        assert fake_requests.sessions[0].trust_env is False
        adapter = fake_requests.sessions[0].mounts["https://"]
        assert adapter.pool_kwargs["assert_hostname"] == "example.com"
        assert adapter.pool_kwargs["server_hostname"] == "example.com"

    def test_request_allows_public_redirect_chain(self, ws_env, monkeypatch):
        final_body = b"<html>ok</html>"
        fake_requests = FakeRequests([
            FakeResponse(
                "https://example.com/start",
                status_code=302,
                headers={"Location": "https://example.org/final"},
                is_redirect=True,
            ),
            FakeResponse(
                "https://example.org/final",
                status_code=200,
                headers={"Content-Length": str(len(final_body))},
                body=final_body,
            ),
        ])
        monkeypatch.setitem(sys.modules, "requests", fake_requests)

        def fake_getaddrinfo(hostname, port, proto=0):
            mapping = {
                "example.com": "93.184.216.34",
                "example.org": "93.184.216.35",
            }
            return [(None, None, None, None, (mapping[hostname], port))]

        monkeypatch.setattr("hub.web_scrape.socket.getaddrinfo", fake_getaddrinfo)

        resp, err = ws_env._request("https://example.com/start")

        assert err == ""
        assert resp is not None
        assert resp.url == "https://example.org/final"
        assert resp.text == final_body.decode("utf-8")
        assert [call["url"] for call in fake_requests.calls] == [
            "https://93.184.216.34/start",
            "https://93.184.216.35/final",
        ]

    def test_request_fails_closed_on_tls_error(self, ws_env, monkeypatch):
        tls_error = FakeRequests.exceptions.SSLError("certificate verify failed")
        fake_requests = FakeRequests([tls_error])
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        monkeypatch.setattr(
            "hub.web_scrape.socket.getaddrinfo",
            lambda hostname, port, proto=0: [(None, None, None, None, ("93.184.216.34", port))],
        )

        resp, err = ws_env._request("https://example.com")

        assert resp is None
        assert "certificate verify failed" in err
        assert len(fake_requests.calls) == 1
        assert fake_requests.calls[0]["verify"] is True

    def test_request_rejects_more_than_max_redirects(self, ws_env, monkeypatch):
        responses = [
            FakeResponse(
                f"https://example.com/{index}",
                status_code=302,
                headers={"Location": f"/{index + 1}"},
                is_redirect=True,
            )
            for index in range(ws_env.MAX_REDIRECTS + 1)
        ]
        fake_requests = FakeRequests(responses)
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        monkeypatch.setattr(
            "hub.web_scrape.socket.getaddrinfo",
            lambda hostname, port, proto=0: [(None, None, None, None, ("93.184.216.34", port))],
        )

        resp, err = ws_env._request("https://example.com/0")

        assert resp is None
        assert err == f"Zu viele Redirects (>{ws_env.MAX_REDIRECTS})"
        assert len(fake_requests.calls) == ws_env.MAX_REDIRECTS + 1
        assert all(call["verify"] is True for call in fake_requests.calls)

    def test_request_rejects_oversized_response(self, ws_env, monkeypatch):
        fake_requests = FakeRequests([
            FakeResponse(
                "https://example.com/file",
                status_code=200,
                headers={"Content-Length": str(ws_env.MAX_RESPONSE_BYTES + 1)},
                body=b"x",
            )
        ])
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        monkeypatch.setattr(
            "hub.web_scrape.socket.getaddrinfo",
            lambda hostname, port, proto=0: [(None, None, None, None, ("93.184.216.34", port))],
        )

        resp, err = ws_env._request("https://example.com/file")

        assert resp is None
        assert "Antwort zu groß" in err

    def test_screenshot_rejects_non_http_target_before_browser_start(self, ws_env):
        ok, message = ws_env._screenshot("file:///C:/Windows/win.ini")

        assert ok is False
        assert "Nur http/https URLs" in message

    def test_screenshot_renders_fetched_body_without_target_navigation(
        self,
        ws_env,
        monkeypatch,
    ):
        body = b"<html><body>safe</body></html>"
        fake_requests = FakeRequests([
            FakeResponse(
                "https://example.com/",
                headers={"Content-Length": str(len(body))},
                body=body,
            )
        ])
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        monkeypatch.setattr(
            "hub.web_scrape.socket.getaddrinfo",
            lambda hostname, port, proto=0: [(None, None, None, None, ("93.184.216.34", port))],
        )

        driver = FakeChromeDriver()
        selenium_module = types.ModuleType("selenium")
        webdriver_module = types.ModuleType("selenium.webdriver")
        chrome_module = types.ModuleType("selenium.webdriver.chrome")
        options_module = types.ModuleType("selenium.webdriver.chrome.options")
        options_module.Options = FakeChromeOptions
        webdriver_module.Chrome = lambda options: driver
        selenium_module.webdriver = webdriver_module
        monkeypatch.setitem(sys.modules, "selenium", selenium_module)
        monkeypatch.setitem(sys.modules, "selenium.webdriver", webdriver_module)
        monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome", chrome_module)
        monkeypatch.setitem(sys.modules, "selenium.webdriver.chrome.options", options_module)

        ok, message = ws_env._screenshot("https://example.com/")

        assert ok is True
        assert "Screenshot gespeichert" in message
        assert driver.navigations == ["about:blank"]
        assert ("Network.setBlockedURLs", {"urls": ["*"]}) in driver.cdp_calls
        assert (
            "Page.setDocumentContent",
            {"frameId": "frame-1", "html": body.decode("utf-8")},
        ) in driver.cdp_calls
        assert driver.quit_called is True
