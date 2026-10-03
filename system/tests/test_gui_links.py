# SPDX-License-Identifier: MIT
"""Vertragstest fuer Link-Integritaet und Navigation in der modularen BACH & OCEAN GUI.

Prueft alle Eintraege aus nav_config.json gegen FastAPI, um tote Links, 404s und
fehlende Templates vollautomatisch auszuschliessen.
"""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from gui.server import app
from gui import server


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "nav-fixture" else None)
    return TestClient(app, headers={"Authorization": "Bearer nav-fixture"})

NAV_CONFIG_PATH = Path(__file__).resolve().parent.parent / "gui" / "web" / "src" / "config" / "nav_config.json"


def load_all_nav_routes():
    """Extrahiert alle Routen aus nav_config.json."""
    if not NAV_CONFIG_PATH.exists():
        pytest.fail(f"nav_config.json nicht gefunden unter: {NAV_CONFIG_PATH}")

    with open(NAV_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    routes = set()
    for item in data:
        if "href" in item and item["href"]:
            routes.add(item["href"].split("?")[0])
        if "children" in item:
            for child in item["children"]:
                if "href" in child and child["href"]:
                    routes.add(child["href"].split("?")[0])

    # Schnellzugriffe hinzufuegen
    routes.add("/kontakte")
    return sorted(list(routes))


@pytest.mark.parametrize("route", load_all_nav_routes())
def test_all_nav_links_valid(route, client):
    """Jede definierte Route in der Hauptnavigation muss HTTP 200 (oder gueltigen Redirect) liefern."""
    response = client.get(route, follow_redirects=True)
    assert response.status_code == 200, f"Route {route} schlug fehl mit Status {response.status_code}"


def test_api_domains_installed(client):
    """GET /api/domains/installed liefert die installierten Fachmodule."""
    res = client.get("/api/domains/installed")
    assert res.status_code == 200
    data = res.json()
    assert "domains" in data
    assert data["total"] > 0


def test_api_artefakte(client):
    """GET /api/artefakte liefert generierte Artefakte."""
    res = client.get("/api/artefakte")
    assert res.status_code == 200
    data = res.json()
    assert "artefakte" in data


def test_api_agent_teams(client):
    """GET /api/agenten/teams liefert Multi-Agenten-Teams."""
    res = client.get("/api/agenten/teams")
    assert res.status_code == 200
    data = res.json()
    assert "teams" in data


def test_api_ocean_map(client):
    """GET /api/setup/ocean-map liefert den Modulschaltplan."""
    res = client.get("/api/setup/ocean-map")
    assert res.status_code == 200
    data = res.json()
    assert "core_components" in data
    assert len(data["core_components"]) >= 3
