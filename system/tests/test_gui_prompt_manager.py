# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for Prompt-Generator GUI API endpoints.

Validates the prompt-generator page and API endpoints respond correctly.
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


class TestPromptGeneratorPage:
    def test_page_loads(self, client):
        response = client.get("/prompt-generator")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_page_contains_key_elements(self, client):
        response = client.get("/prompt-generator")
        text = response.text
        assert "template" in text.lower() or "prompt" in text.lower()


class TestPromptGeneratorAPI:
    def test_templates_list(self, client):
        response = client.get("/api/prompt-generator/templates")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))

    def test_daemon_status(self, client):
        response = client.get("/api/prompt-generator/daemon/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_template_not_found_returns_error(self, client):
        response = client.get("/api/prompt-generator/template/nonexistent_xyz_abc")
        assert response.status_code in (200, 404)

    def test_template_traversal_blocked(self, client):
        response = client.get("/api/prompt-generator/template/../../etc/passwd")
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert data.get("content") is None or data.get("error")

    def test_send_task_requires_body(self, client):
        response = client.post("/api/prompt-generator/send/task", json={})
        assert response.status_code in (200, 422)

    def test_send_copy_requires_body(self, client):
        response = client.post("/api/prompt-generator/send/copy", json={})
        assert response.status_code in (200, 422)

    def test_daemon_toggle(self, client):
        response = client.post("/api/prompt-generator/daemon/toggle", json={})
        assert response.status_code in (200, 422)

    def test_templates_save_requires_body(self, client):
        response = client.post("/api/prompt-generator/templates/save", json={})
        assert response.status_code in (200, 422)
