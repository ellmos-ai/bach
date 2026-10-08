"""Public fixed GUI auth bootstrap; API device protection remains active."""
import asyncio
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient


def test_shared_bootstrap_is_public_and_comes_from_configured_dist(tmp_path, monkeypatch):
    from gui import server
    script = tmp_path / "device-fetch.js"
    script.write_text("window.__deviceFetchInstalled=true;", encoding="utf-8")
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    with TestClient(server.app, base_url="http://testserver") as client:
        response = client.get("/device-fetch.js")
        assert response.status_code == 200 and response.text == script.read_text()
        assert response.headers["content-type"].startswith("application/javascript")
        assert response.headers["cache-control"] == "no-cache"
    assert "/api/task-assignees" not in server.DeviceAuthMiddleware.EXEMPT_API_PATHS
    assert "/api/governance/policy-registry" not in server.DeviceAuthMiddleware.EXEMPT_API_PATHS


def test_missing_bootstrap_fails_visibly(tmp_path, monkeypatch):
    from gui import server
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(server.get_device_fetch_script())
    assert denied.value.status_code == 404


@pytest.mark.parametrize("route", ["/", "/agenten/fabrika", "/skills", "/tasks"])
def test_explicit_missing_release_never_uses_legacy_templates(tmp_path, monkeypatch, route):
    from gui import server
    legacy = tmp_path / "templates"
    legacy.mkdir()
    (legacy / "index.html").write_text("legacy must not be served", encoding="utf-8")
    monkeypatch.setattr(server, "TEMPLATES_DIR", legacy)
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path / "missing-release")
    monkeypatch.setenv("ELLMOS_SYSTEM_GUI_DIST", str(tmp_path / "missing-release"))
    with TestClient(server.app, base_url="http://testserver") as client:
        response = client.get(route)
        assert response.status_code == 503
        assert response.json()["reason_code"] == "shared_gui_page_missing"
        assert "legacy must not be served" not in response.text


def test_explicit_release_serves_its_present_page_and_keeps_auth(tmp_path, monkeypatch):
    from gui import server
    (tmp_path / "index.html").write_text("<h1>Verified release</h1>", encoding="utf-8")
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    monkeypatch.setenv("ELLMOS_SYSTEM_GUI_DIST", str(tmp_path))
    with TestClient(server.app, base_url="http://testserver") as client:
        response = client.get("/")
        assert response.status_code == 200 and response.text == "<h1>Verified release</h1>"
    assert "/api/task-assignees" not in server.DeviceAuthMiddleware.EXEMPT_API_PATHS
