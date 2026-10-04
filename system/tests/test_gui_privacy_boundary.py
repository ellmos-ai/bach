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
