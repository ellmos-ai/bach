# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests for Startseite (index.html) cleanup and feature migration (T-20260913-660268706, P4).
"""

import sys
from pathlib import Path
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

TESTS_DIR = Path(__file__).parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_gui_server_smoke import test_db  # reuse test_db fixture


@pytest.fixture
def client(test_db, monkeypatch):
    db_path = test_db / "data" / "bach.db"

    gui_dir = test_db / "gui"
    gui_dir.mkdir(exist_ok=True)
    templates_dir = gui_dir / "templates"
    templates_dir.mkdir(exist_ok=True)
    static_dir = gui_dir / "static"
    static_dir.mkdir(exist_ok=True)

    # Copy real templates so server can serve them
    real_templates_dir = SYSTEM_ROOT / "gui" / "templates"
    for name in ("index.html", "inbox.html", "settings.html"):
        src = real_templates_dir / name
        if src.exists():
            (templates_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    import gui.server as srv
    monkeypatch.setattr(srv, "BACH_DB", db_path)
    monkeypatch.setattr(srv, "USER_DB", db_path)
    monkeypatch.setattr(srv, "DATA_DIR", test_db / "data")
    monkeypatch.setattr(srv, "BACH_DIR", test_db)
    monkeypatch.setattr(srv, "GUI_DIR", gui_dir)
    monkeypatch.setattr(srv, "TEMPLATES_DIR", templates_dir)
    monkeypatch.setattr(srv, "STATIC_DIR", static_dir)

    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestStartseiteCleanup:
    """Verifies Startseite cleanup, Verbindungen migration, and Ausbaustufen relocation."""

    def test_startseite_cleanup_get_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text

        # KEIN id="tab-tokens", KEIN id="tab-files", KEIN id="headless-prompt", KEIN Ausbaustufen
        assert 'id="tab-tokens"' not in html
        assert 'id="tab-files"' not in html
        assert 'id="headless-prompt"' not in html
        assert "Ausbaustufen" not in html

        # Bestätige: Aktive Agenten Kachel ist vorhanden
        assert "stat-agents-active" in html
        assert "Aktive Agenten" in html

    def test_inbox_has_verbindungen_tab(self, client):
        resp = client.get("/inbox")
        assert resp.status_code == 200
        html = resp.text

        # Enthält jetzt die Verbindungen-Tab-Kennung und mounts-list-body
        assert "Verbindungen" in html
        assert "tab-btn-connections" in html
        assert "tab-connections" in html
        assert "mounts-list-body" in html

    def test_settings_has_ausbaustufen(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        html = resp.text

        # Enthält jetzt Ausbaustufen
        assert "Ausbaustufen" in html
        assert "USMC" in html
        assert "Rinnsal" in html
        assert "BACH" in html
