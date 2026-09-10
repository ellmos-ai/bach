# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for Prompt-Generator GUI API endpoints.

Validates the prompt-generator page and API endpoints respond correctly.
"""

import json
import subprocess
import sys
import time
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

    def test_daemon_toggle(self, client, monkeypatch, tmp_path):
        from gui import server

        daemon_dir = tmp_path / "hub" / "_services" / "daemon"
        daemon_dir.mkdir(parents=True)
        daemon_script = daemon_dir / "session_daemon.py"
        daemon_script.write_text("# isolated test daemon\n", encoding="utf-8")
        config_file = daemon_dir / "config.json"
        config_file.write_text(
            json.dumps({"jobs": [{"profile": "ati", "last_run": "old"}]}),
            encoding="utf-8",
        )

        launched = []

        def fake_popen(args, **kwargs):
            launched.append((args, kwargs))
            return object()

        monkeypatch.setattr(server, "BACH_DIR", tmp_path)
        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        monkeypatch.setattr(time, "sleep", lambda _seconds: None)

        response = client.post("/api/prompt-generator/daemon/toggle", json={})

        assert response.status_code in (200, 422)
        assert len(launched) == 1
        assert launched[0][0] == [sys.executable, str(daemon_script)]
        assert json.loads(config_file.read_text(encoding="utf-8"))["jobs"][0]["last_run"] is None

    def test_templates_save_requires_body(self, client):
        response = client.post("/api/prompt-generator/templates/save", json={})
        assert response.status_code in (200, 422)
