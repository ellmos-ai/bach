# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for Workflow-TÜV GUI API endpoints.

Validates the workflow-tuev page, list, check, sync, and content endpoints.
"""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


@pytest.fixture
def client():
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("starlette not available")
    from gui.server import app
    return TestClient(app, raise_server_exceptions=False)


class TestWorkflowTuevPage:
    def test_page_loads(self, client):
        response = client.get("/workflow-tuev")
        assert response.status_code == 200

    def test_page_is_html(self, client):
        response = client.get("/workflow-tuev")
        assert "text/html" in response.headers.get("content-type", "")


class TestWorkflowTuevAPI:
    def test_list_returns_json(self, client):
        response = client.get("/api/workflow-tuev")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert "stats" in data
        assert isinstance(data["workflows"], list)

    def test_stats_structure(self, client):
        response = client.get("/api/workflow-tuev")
        data = response.json()
        stats = data.get("stats", {})
        if stats:
            for key in ("total", "valid", "expired", "pending"):
                assert key in stats

    def test_check_requires_valid_id(self, client):
        response = client.post(
            "/api/workflow-tuev/99999/check",
            json={"result": "pass", "validity_days": 90}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data or "error" in data or "updated" in data

    def test_sync_endpoint(self, client):
        response = client.post("/api/workflow-tuev/sync")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_check_all_endpoint(self, client):
        response = client.post("/api/workflow-tuev/check-all")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_content_valid_file(self, client):
        response = client.get(
            "/api/workflow-tuev/content",
            params={"path": "hub/__init__.py"}
        )
        assert response.status_code in (200, 404)

    def test_content_traversal_blocked(self, client):
        response = client.get(
            "/api/workflow-tuev/content",
            params={"path": "../../etc/passwd"}
        )
        assert response.status_code == 403

    def test_content_backslash_traversal_blocked(self, client):
        response = client.get(
            "/api/workflow-tuev/content",
            params={"path": "..\\..\\etc\\passwd"}
        )
        assert response.status_code == 403
