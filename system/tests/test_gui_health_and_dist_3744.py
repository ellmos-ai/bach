"""Regressions-Tests zu Task #3744: /api/health und /dist-manifest.json in system/gui/server.py.

Geprüft wird:
- GET /api/health -> 200 und exakt {"status": "ok"} (minimaler Liveness-Probe, EXEMPT).
- GET /dist-manifest.json ohne vorhandene Manifest-Datei -> 404 "Gui dist manifest unavailable".
- GET /dist-manifest.json bei ASTRO_DIST_DIR=None -> 404 (defensive Ab deckung des Fix).
- GET /dist-manifest.json mit vorhandener dist-manifest.json -> 200, exakter Dateiinhalt,
  media_type application/json (FileResponse, kein PAGE_READ).
"""

import json

import pytest
from fastapi.testclient import TestClient

from gui import server


@pytest.fixture(autouse=True)
def _device_auth(monkeypatch):
    # DeviceAuthMiddleware verlangt einen gültigen Bearer (ohne Header 401,
    # ungültiges Token 403); server.validate_token wie in
    # test_agent_history_delivery.py mocken, Bearer im Client setzen.
    monkeypatch.setattr(
        server, "validate_token",
        lambda token: {"id": 1} if token == "gui-fixture" else None,
    )


def _client() -> TestClient:
    return TestClient(server.app, headers={"Authorization": "Bearer gui-fixture"})


def test_api_health_returns_ok():
    response = _client().get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dist_manifest_404_when_manifest_file_missing(tmp_path, monkeypatch):
    # ASTRO_DIST_DIR zeigt auf einen leeren Ordner: Dist-Ordner da, Manifest fehlt.
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    response = _client().get("/dist-manifest.json")
    assert response.status_code == 404
    assert response.json()["detail"] == "Gui dist manifest unavailable"


def test_dist_manifest_404_when_no_dist_dir(monkeypatch):
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", None)
    response = _client().get("/dist-manifest.json")
    assert response.status_code == 404
    assert response.json()["detail"] == "Gui dist manifest unavailable"


def test_dist_manifest_served_from_installed_dist(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ASTRO_DIST_DIR", tmp_path)
    payload = json.dumps(
        {"schema": "ellmos.gui.dist.v1", "source_commit": "test"}
    ).encode("utf-8")
    (tmp_path / "dist-manifest.json").write_bytes(payload)

    response = _client().get("/dist-manifest.json")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["schema"] == "ellmos.gui.dist.v1"