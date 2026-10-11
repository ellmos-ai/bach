# SPDX-License-Identifier: MIT
"""Vertragstests für die modulare Astro v5 GUI-Integration in BACH."""

import pytest
from fastapi.testclient import TestClient
from gui.server import app

client = TestClient(app, base_url="http://localhost")


def test_astro_index_page():
    """Startseite (/) liefert die neue modulare Astro-Oberfläche."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Willkommen in der" in response.text
    assert "data-gui-brand-product" in response.text
    assert ">System GUI</span>" in response.text
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
    assert "/agenten/blueprints?new=1" in response.text
    assert "location.replace" in response.text
    studio = client.get("/agenten/blueprints?new=1")
    assert studio.status_code == 200
    for element in ("studio-new", "bp-persona", "bp-contractus-preset", "bp-save"):
        assert element in studio.text



def test_astro_agenten_running():
    """Living & Running (/agenten/running) liefert die aktiven Beseelungen."""
    response = client.get("/agenten/running")
    assert response.status_code == 200
    assert "Living & Running" in response.text
    assert "System-Agenten" in response.text
    assert "worker-blueprint-sub-mode" in response.text
    assert "worker-blueprint-task-id" in response.text
    assert "worker-blueprint-allow-tools" in response.text
    assert "worker-blueprint-run-mode" in response.text
    assert "Fortlaufend bis Stopp" in response.text


def test_astro_agenten_marblerun():
    """MarbleRun (/agenten/marblerun) liefert den visuellen Ketten-Editor."""
    response = client.get("/agenten/marblerun")
    assert response.status_code == 200
    assert "Ketten · MarbleRun" in response.text
    for element in ("chain-new", "chain-form", "chain-add-step", "chain-save", "chain-start-submit"):
        assert element in response.text


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
    assert "Skill-Zentrale" in response.text
    for element in ("capability-board", "board-search", "board-items", "skill-create", "skill-save"):
        assert element in response.text
    assert "/skills/mcp" in response.text
