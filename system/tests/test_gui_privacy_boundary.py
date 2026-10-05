"""Private GUI APIs cannot be read by browser origins or local anonymous clients."""
import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.websockets import WebSocketDisconnect

from gui import server
from gui.api import unified_api


def _request(path, headers=(), method="GET", query=b""):
    return Request({"type": "http", "method": method, "path": path,
                    "scheme": "http", "server": ("127.0.0.1", 8000),
                    "client": ("127.0.0.1", 12345),
                    "headers": [(b"host", b"127.0.0.1:8000"), *headers],
                    "query_string": query})


@pytest.mark.parametrize("path", ["/api/tasks", "/api/status", "/api/capabilities",
                                   "/api/artifacts/content", "/api/artifacts/download",
                                   "/api/devices", "/api/marblerun/chains"])
@pytest.mark.parametrize("configured", [True, False])
def test_private_api_denies_loopback_without_credentials(path, configured):
    called = []

    async def handler(request):
        called.append(request)
        return PlainTextResponse("private")

    with patch.object(server, "has_active_devices", return_value=configured):
        result = asyncio.run(server.DeviceAuthMiddleware(server.app).dispatch(_request(path), handler))
    assert result.status_code == 401
    assert not called


def test_origin_and_query_token_cannot_authorize_api():
    called = []

    async def handler(request):
        called.append(request)
        return PlainTextResponse("private")

    middleware = server.DeviceAuthMiddleware(server.app)
    with patch.object(server, "validate_token", return_value={"id": 1}) as validator:
        result = asyncio.run(middleware.dispatch(_request(
            "/api/artifacts/content", [(b"origin", b"https://example.invalid"),
                                       (b"authorization", b"Bearer fixture")]), handler))
        assert result.status_code == 403
        validator.assert_not_called()
        result = asyncio.run(middleware.dispatch(_request(
            "/api/tasks", query=b"token=fixture"), handler))
        assert result.status_code == 401
        validator.assert_not_called()
        assert not called
        result = asyncio.run(middleware.dispatch(_request(
            "/api/tasks", [(b"origin", b"http://127.0.0.1:8000"),
                           (b"authorization", b"Bearer fixture")]), handler))
        assert result.status_code == 200
        assert len(called) == 1


def test_cors_never_exposes_private_content():
    with TestClient(server.app) as client:
        response = client.get("/api/artifacts/content", params={"path": "ignored"},
                              headers={"Origin": "https://example.invalid"})
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers


def test_artifact_catalog_rejects_databases_keys_and_runtime(tmp_path, monkeypatch):
    from gui.api import artifact_catalog

    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(artifact_catalog, "ARTIFACT_ROOT", exports)
    (exports / "report.md").write_text("ok", encoding="utf-8")
    for name in ("bach.db", "user.sqlite", "server.pem", "bach_secrets.json", "token.txt", ".hidden.md"):
        (exports / name).write_text("secret", encoding="utf-8")
    (tmp_path / "private.md").write_text("outside", encoding="utf-8")
    names = {item["name"] for item in artifact_catalog.catalog()["artifacts"]}
    assert names == {"report.md"}
    # Opaque ids only: paths and names cannot address files outside the catalog.
    for bad in ("../private.md", str(tmp_path / "private.md"), "bach.db", "0" * 32):
        with pytest.raises(FileNotFoundError):
            artifact_catalog.resolve_artifact(bad)


def test_device_fetch_keeps_credentials_on_own_api_and_preserves_control_auth():
    script = Path(server.GUI_DIR) / "static" / "js" / "device-fetch.js"
    driver = r"""
const fs = require('fs'), vm = require('vm');
const seen = [];
const window = {fetch: async (input, options = {}) => {
  seen.push({url: input instanceof Request ? input.url : input,
             auth: new Headers(options.headers).get('Authorization')});
  return {status: 200};
}};
const location = {href: 'http://gui.invalid/unified', origin: 'http://gui.invalid'};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  window, URL, Request, Headers, location, document: {},
  localStorage: {getItem: () => 'fixture-device'},
});
(async () => {
  await window.fetch('/api/tasks');
  await window.fetch(new Request('http://gui.invalid/api/tasks'));
  await window.fetch('/api/chat-control/history', {headers: {authorization: 'Bearer control-fixture'}});
  await window.fetch('https://other.invalid/api/tasks');
  await window.fetch('/static/example.js');
  process.stdout.write(JSON.stringify(seen));
})();
"""
    result = subprocess.run(["node", "-e", driver, str(script)], check=True,
                            capture_output=True, text=True, timeout=15)
    seen = json.loads(result.stdout)
    assert [item["auth"] for item in seen] == [
        "Bearer fixture-device", "Bearer fixture-device", "Bearer control-fixture", None, None,
    ]

TOKEN = "perimeter-fixture-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == TOKEN else None)
    return TestClient(server.app)


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _rejected(client, **kwargs):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", **kwargs):
            pass
    return exc.value.code


# ── WebSocket ────────────────────────────────────────────────────────────

def test_ws_without_token_is_rejected_before_any_event(client):
    before = len(server.ws_manager.active_connections)
    assert _rejected(client) == 1008
    assert len(server.ws_manager.active_connections) == before


def test_ws_with_invalid_token_is_rejected(client):
    assert _rejected(client, headers={"Authorization": "Bearer nope"}) == 1008


def test_ws_token_in_query_string_is_ignored(client):
    assert _rejected(client, params={"token": TOKEN}) == 1008


def test_ws_foreign_origin_is_rejected_even_with_token(client):
    assert _rejected(client, headers={**AUTH, "Origin": "https://evil.example"}) == 1008


def test_ws_foreign_host_is_rejected_even_with_token(client):
    assert _rejected(client, headers={**AUTH, "Host": "evil.example"}) == 1008


def test_ws_accepts_token_with_loopback_origin(client):
    headers = {**AUTH, "Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
    with client.websocket_connect("/ws", headers=headers) as ws:
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"


def test_ws_accepts_browser_subprotocol_token(client):
    with client.websocket_connect("/ws", subprotocols=["bach.v1", "bach.token." + TOKEN]) as ws:
        assert ws.accepted_subprotocol == "bach.v1"
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"


def test_ws_token_subprotocol_without_version_protocol_is_rejected(client):
    assert _rejected(client, subprotocols=["bach.token." + TOKEN]) == 1008


def test_only_the_known_websocket_route_exists():
    """A new WebSocket route must be reviewed: the HTTP middleware does not cover it."""
    paths = {r.path for r in server.app.routes if type(r).__name__ == "APIWebSocketRoute"}
    assert paths == {"/ws"}


# ── Default-deny ─────────────────────────────────────────────────────────

@pytest.fixture
def dummy_routes():
    async def dummy():
        return {"ok": True}

    server.app.add_api_route("/api/_perimeter_dummy", dummy, methods=["GET", "POST"])
    server.app.add_api_route("/_perimeter_dummy_page", dummy, methods=["GET"])
    yield
    server.app.router.routes[:] = [
        r for r in server.app.router.routes if "_perimeter_dummy" not in getattr(r, "path", "")
    ]


@pytest.mark.parametrize("path", ["/api/_perimeter_dummy", "/_perimeter_dummy_page"])
def test_newly_registered_route_is_denied_without_token(client, dummy_routes, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer nope"}).status_code in (401, 403)
    assert client.get(path, headers=AUTH).status_code == 200


def test_cookie_token_also_passes_the_gate(client, dummy_routes):
    client.cookies.set("bach_device_token", TOKEN)
    assert client.get("/_perimeter_dummy_page").status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/control/", "/ws-not-a-page"])
def test_docs_mounts_and_unknown_paths_need_a_token(client, path):
    assert client.get(path).status_code in (401, 403)


def test_mutating_methods_on_page_paths_need_a_token(client):
    assert client.post("/").status_code == 401


def test_public_allowlist_is_explicit_and_unauthenticated_shells_load(client):
    assert "/token-dashboard" in server.DeviceAuthMiddleware.PUBLIC_PAGE_PATHS
    assert client.get("/token-dashboard").status_code not in (401, 403)
    assert client.get("/api/health").status_code not in (401, 403)


def test_every_registered_non_api_route_is_classified():
    """Fails when a route is added without deciding whether it may be public."""
    public = server.DeviceAuthMiddleware.PUBLIC_PAGE_PATHS
    protected = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/ws", "/control", "/static"}
    for route in server.app.routes:
        path = getattr(route, "path", None)
        if path and not path.startswith("/api/") and "_perimeter_dummy" not in path:
            assert path in public or path in protected, f"unclassified route {path}"


# ── Host allowlist (DNS rebinding) ───────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/health", "/", "/token-dashboard"])
def test_unknown_host_is_rejected_even_when_origin_matches(client, path):
    headers = {"Host": "rebound.example", "Origin": "http://rebound.example"}
    assert client.get(path, headers=headers).status_code == 403
    assert client.get(path, headers={**headers, **AUTH}).status_code == 403


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
def test_loopback_hosts_are_allowed(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code != 403


def test_configured_host_is_allowed_and_others_still_are_not(client, monkeypatch):
    monkeypatch.setenv("BACH_GUI_ALLOWED_HOSTS", "testserver, bach.tailnet.example:8000")
    assert client.get("/api/health", headers={"Host": "bach.tailnet.example:8000"}).status_code != 403
    assert client.get("/api/health", headers={"Host": "other.example"}).status_code == 403


def test_host_lookalikes_are_not_loopback(client):
    for host in ("localhost.evil.example", "127.0.0.1.evil.example", "evil.example:80@localhost"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 403


# ── Codex review follow-ups ──────────────────────────────────────────────

def test_anonymous_financial_page_does_not_touch_the_database(client, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "init_financial_tables", lambda: calls.append(1))
    client.get("/financial")
    assert calls == []


@pytest.mark.parametrize("origin, host, scheme, expected", [
    ("http://127.0.0.1:8000", "127.0.0.1:8000", "ws", True),
    ("https://gui.example", "gui.example", "wss", True),
    ("https://gui.example:443", "gui.example", "wss", True),
    ("http://localhost", "localhost:80", "ws", True),
    ("http://[::1]:8000", "[::1]:8000", "ws", True),
    ("https://127.0.0.1:8000", "127.0.0.1:8000", "ws", False),   # scheme
    ("http://127.0.0.1:9999", "127.0.0.1:8000", "ws", False),    # port
    ("http://127.0.0.1", "127.0.0.1:8000", "ws", False),         # implied default port
    ("http://evil.example:8000", "127.0.0.1:8000", "ws", False),  # host
    ("null", "127.0.0.1:8000", "ws", False),
    ("http://user@127.0.0.1:8000", "127.0.0.1:8000", "ws", False),
    ("http://127.0.0.1:8000/path", "127.0.0.1:8000", "ws", False),
    ("ftp://127.0.0.1:8000", "127.0.0.1:8000", "ws", False),
    ("", "127.0.0.1:8000", "ws", False),
])
def test_origin_must_be_this_servers_own_origin(origin, host, scheme, expected):
    assert server.origin_matches_host(origin, host, scheme) is expected


def test_ws_origin_with_foreign_port_is_rejected(client):
    headers = {**AUTH, "Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:9999"}
    assert _rejected(client, headers=headers) == 1008
    assert _rejected(client, headers={**AUTH, "Origin": "null"}) == 1008


@pytest.mark.parametrize("host", [
    "[::1]x", "[::1]:80x", "[::1", "[::1]]", "[::1]:", "::1", "localhost:", "localhost:abc",
    "localhost:99999", "localhost:0", "local host", "a@localhost", "localhost/", "[zz]",
    "[::1]:8000:1", "", "[::1]/x",
])
def test_malformed_host_headers_are_rejected(host):
    assert server._hostname(host) == ""
    assert not server.host_is_allowed(host)


@pytest.mark.parametrize("host", ["[::1]", "[::1]:8000", "[0:0:0:0:0:0:0:1]:8000", "LOCALHOST.:8000"])
def test_wellformed_loopback_hosts_are_allowed(host):
    assert server.host_is_allowed(host)


def test_websocket_token_subprotocol_is_never_logged(caplog):
    import logging
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("websockets.server").debug("< Sec-WebSocket-Protocol: bach.v1, bach.token.SECRETVALUE_1")
        logging.getLogger("uvicorn.error").info("headers %s", ["bach.token.SECRETVALUE_2"])
    text = caplog.text
    assert "SECRETVALUE" not in text
    assert "bach.token.[redacted]" in text


def test_nav_config_error_does_not_leak_details(client, monkeypatch, tmp_path):
    from gui.api import unified_api
    broken = tmp_path / "nav_config.json"
    broken.write_text("{ broken C:/secret/path", encoding="utf-8")
    monkeypatch.setattr(unified_api, "_find_existing_path", lambda candidates: broken)
    body = client.get("/api/nav/config").json()
    assert body == {"error": "nav_config_unreadable", "areas": []}
