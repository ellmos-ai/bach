# SPDX-License-Identifier: MIT
"""Vertragstests fuer die modulare Astro v5 GUI-Integration in BACH."""

import pytest
from fastapi.testclient import TestClient
from gui.server import app

client = TestClient(app)


def test_astro_index_page():
    """Startseite (/) liefert die neue modulare Astro-Oberflaeche."""
    response = client.get("/")
    assert response.status_code == 200
    assert "BACH & OCEAN" in response.text
    assert "Dashboard" in response.text
    assert "theme-switcher" in response.text


def test_astro_tasks_page():
    """Aufgaben-Seite (/tasks) liefert das neue modulare Aufgabenboard."""
    response = client.get("/tasks")
    assert response.status_code == 200
    assert "Aufgaben & Taskboard" in response.text
    assert "modal-new-task" in response.text


def test_astro_agenten_fabrika():
    """Agenten-Fabrik (/agenten/fabrika) liefert den Schablonen-Baukasten und Teambuilding."""
    response = client.get("/agenten/fabrika")
    assert response.status_code == 200
    assert "Agenten-Fabrik" in response.text
    assert "Persona & Rolle" in response.text
    assert "Contractus & Modus" in response.text



def test_astro_agenten_running():
    """Living & Running (/agenten/running) liefert die aktiven Beseelungen."""
    response = client.get("/agenten/running")
    assert response.status_code == 200
    assert "Living & Running" in response.text
    assert "Avatar-Agenten" in response.text


def test_astro_agenten_marblerun():
    """MarbleRun (/agenten/marblerun) liefert den visuellen Ketten-Editor."""
    response = client.get("/agenten/marblerun")
    assert response.status_code == 200
    assert "Agenten-Staffel" in response.text
    assert "MarbleRun" in response.text
    assert "Ketten-Designer" in response.text


def test_astro_governance():
    """Governance (/governance) liefert Decision-Clicker und Lock-Monitor."""
    response = client.get("/governance")
    assert response.status_code == 200
    assert "Governance CONTROL Room" in response.text
    assert "Decision-Clicker" in response.text
    assert "Lock-Master" in response.text


def test_astro_memory():
    """Deep Memory (/memory) liefert den Kognitiven Memory-Schaltplan nach Baddeley."""
    response = client.get("/memory")
    assert response.status_code == 200
    assert "Kognitiver Memory-Schaltplan" in response.text
    assert "Arbeitsgedächtnismodell" in response.text


def test_astro_skills():
    """Skills & Capabilities (/skills) liefert Steckdosenleiste, Cookbooks und Versionierung."""
    response = client.get("/skills")
    assert response.status_code == 200
    assert "Capabilities- & Skills-Zentrale" in response.text
    assert "Steckdosenleiste" in response.text
    assert "MCP Cookbooks" in response.text
