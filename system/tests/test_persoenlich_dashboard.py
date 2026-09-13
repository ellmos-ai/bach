# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tests for the Persönlicher-Assistent-Dashboard (/agents/persoenlich).
"""

import sys
from pathlib import Path
import sqlite3
import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


@pytest.fixture
def test_db(tmp_path):
    """Creates minimal DBs for testing."""
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'open',
            category TEXT DEFAULT 'general',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY,
            name TEXT,
            category TEXT,
            interval_type TEXT,
            is_active INTEGER DEFAULT 1,
            next_due_at TEXT,
            priority INTEGER DEFAULT 3
        );
    """)
    conn.commit()
    conn.close()
    return tmp_path


@pytest.fixture
def client(test_db, monkeypatch):
    """Creates a TestClient with TEMPLATES_DIR pointing to real gui/templates."""
    db_path = test_db / "data" / "bach.db"

    import gui.server as srv
    monkeypatch.setattr(srv, "BACH_DB", db_path)
    monkeypatch.setattr(srv, "USER_DB", db_path)
    monkeypatch.setattr(srv, "TEMPLATES_DIR", SYSTEM_ROOT / "gui" / "templates")

    return TestClient(srv.app, raise_server_exceptions=False)


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="FastAPI not installed")
class TestPersoenlichDashboard:
    """Dashboard-Tests für Persönlicher Assistent."""

    def test_persoenlich_dashboard_renders(self, client):
        resp = client.get("/agents/persoenlich")
        assert resp.status_code == 200
        html = resp.text

        # 6 Schnellzugriff-Links vorhanden
        assert '/chat' in html
        assert '/prompt-library' in html
        assert '/routinen?tab=personal' in html
        assert '/kontakte' in html
        assert '/denkarium' in html
        assert '/wiki' in html

        # Veraltete Entwurfs-/Fantasie-Blöcke entfernt
        assert "In Entwicklung" not in html
        assert "Geplante Features" not in html
        assert "Nächste Schritte" not in html

        # Verlinkte Agenten
        assert '/financial' in html
        assert '/agents/gesundheit' in html
        assert '/agents/foerderplaner' in html

        # Kennzahlen-Elemente vorhanden
        assert 'id="stat-calendar"' in html
        assert 'id="stat-tasks"' in html
        assert 'id="stat-agents"' in html
        assert 'id="stat-routines"' in html

    def test_persoenlich_redirect(self, client):
        resp = client.get("/persoenlich", follow_redirects=False)
        assert resp.status_code in (301, 302, 307, 308)
        assert resp.headers["location"] == "/agents/persoenlich"
