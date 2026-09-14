# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Contract tests for the GUI mounts API and inbox response handling."""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

from gui import server
from hub.mount import MountHandler


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "user").mkdir()
    monkeypatch.setattr(server, "BACH_DIR", tmp_path)
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.mark.skipif(TestClient is None, reason="FastAPI not installed")
class TestGuiMountsContract:
    def test_list_mounts_includes_path_used_by_inbox(self, client, monkeypatch):
        monkeypatch.setattr(
            MountHandler,
            "_list_mounts",
            lambda self: (
                True,
                "Aktive Mounts:\n====================\n"
                "[OK] docs -> C:\\Pfad mit Leerzeichen [EXISTIERT]",
            ),
        )

        response = client.get("/api/mounts")

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "mounts": [
                {
                    "alias": "docs",
                    "path": "C:\\Pfad mit Leerzeichen",
                    "active": True,
                    "exists": True,
                }
            ],
        }

    def test_list_mounts_error_uses_error_field(self, client, monkeypatch):
        monkeypatch.setattr(
            MountHandler, "_list_mounts", lambda self: (False, "Lesefehler")
        )

        response = client.get("/api/mounts")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"]
        assert "output" not in data

    def test_restore_uses_message_on_success_and_error_on_failure(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            MountHandler, "_restore_mounts", lambda self, dry_run: (True, "erledigt")
        )

        success = client.post("/api/mounts/restore")

        assert success.status_code == 200
        assert success.json() == {
            "success": True,
            "message": "Mounts wiederhergestellt",
        }

        monkeypatch.setattr(
            MountHandler, "_restore_mounts", lambda self, dry_run: (False, "Fehler")
        )

        failure = client.post("/api/mounts/restore")

        assert failure.status_code == 200
        data = failure.json()
        assert data["success"] is False
        assert data["error"]
        assert "output" not in data


def test_inbox_mount_ui_prefers_authoritative_fields_with_output_fallback():
    template = (SYSTEM_ROOT / "gui" / "templates" / "inbox.html").read_text(
        encoding="utf-8"
    )

    assert 'escapeHtml(m.path)' in template
    assert 'data.error || data.output' in template
    assert 'data.message || data.output' in template
