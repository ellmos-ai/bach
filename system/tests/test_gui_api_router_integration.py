"""Integration test: stub routers installer_profile_preview and catalog_projection mount correctly.

The production FastAPI app is not available in this worktree, so this test builds a
minimal app, includes both routers, and verifies the endpoints resolve with the
expected response keys.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from gui.api import catalog_projection, installer_profile_preview


@pytest.fixture
def client(monkeypatch):
    """Build a test app with both routers and bypass device authentication."""
    monkeypatch.setattr(
        "gui.api.unified_api._require_memory_device",
        lambda request: 1,
    )
    app = FastAPI()
    app.include_router(installer_profile_preview.router, prefix="/api")
    app.include_router(catalog_projection.router)
    return TestClient(app)


def test_installer_profile_preview_router_mounted(client):
    """GET /api/installer/profiles/{profile_id}/preview returns a preview document."""
    response = client.get("/api/installer/profiles/test-profile/preview")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["schema"] == "bach.installer.profile-preview.v1"
    assert body["profile_id"] == "test-profile"
    assert body["status"] == "unavailable"
    assert "reason_code" in body
    assert body["apply_allowed"] is False
    assert body["deployable"] is False


def test_catalog_projection_router_mounted(client):
    """GET /api/capabilities/catalog returns a bach.catalog.v1 projection."""
    response = client.get("/api/capabilities/catalog")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["schema"] == "bach.catalog.v1"
    assert "generated_at" in body
    assert "host" in body
    assert "sources" in body
    assert "items" in body
    assert "counts" in body
    assert "count" in body
    assert "errors" in body
    assert "truncated" in body
    assert "architecture" in body
    assert "redactions" in body
