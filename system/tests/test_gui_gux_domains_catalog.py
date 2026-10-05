# SPDX-License-Identifier: MIT
"""Vertragstests fuer GUX-068 bis GUX-071: Domaenenkatalog und Fachmenues.

Prueft:
- GUX-068: Manifestgetriebener Katalog (.DOMAINS + Repositories)
- GUX-069: Strikte Trennung von 4 Zustaenden (Definition, Installation, Probe, Runtime)
  sowie Sichtbarkeit privater und zusaetzlicher Repositories
- GUX-070: Domaenen sind Wissens-/Datenraeume (keine Agenten), Steuer-Assistent Name,
  Foerderplaner-Fachseite (/foerderplaner, nie /agents/foerderplaner)
- GUX-071: Persistente Domaenen-Pins, stabile IDs, Autorisierung/Readback, Fallback
"""

import pytest
from fastapi.testclient import TestClient
from gui import server
from gui.api.domain_catalog import (
    discover_domains,
    get_domain_pins,
    save_domain_pins,
    toggle_domain_pin,
)
from gui.server import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "gux-fixture" else None)
    return TestClient(app, headers={"Authorization": "Bearer gux-fixture"})


@pytest.fixture
def temp_pin_file(monkeypatch, tmp_path):
    pin_file = tmp_path / "domain_pins.json"
    import gui.api.domain_catalog as dc
    monkeypatch.setattr(dc, "PIN_STORAGE_FILE", pin_file)
    return pin_file


# =========================================================================
# GUX-068: Echte Manifests / Provider im Domaenenkatalog
# =========================================================================

def test_gux_068_discover_domains_reads_real_manifests():
    """GUX-068: Katalog liest echte ellmos-module Manifeste dynamisch ein."""
    result = discover_domains(scope="all", probe=True, include_repos=True)
    assert result["source_available"] is True
    assert result["total"] > 0
    domains = result["domains"]
    ids = {d["id"] for d in domains}

    # Bekannte reale Fachmodule muessen vorhanden sein
    assert "ati" in ids or "foerderplaner" in ids or "steuer-suite" in ids

    # Jedes Modul traegt deklarierte Manifest-Eigenschaften
    for d in domains:
        assert "id" in d and len(d["id"]) > 0
        assert "name" in d and len(d["name"]) > 0
        assert "capabilities" in d and isinstance(d["capabilities"], list)
        assert "states" in d and isinstance(d["states"], dict)
        assert "evidence_type" in d


def test_gux_068_manifest_capabilities_and_boundaries():
    """GUX-068: Deklarierte Faehigkeiten und Grenzen/Datenisolierung werden transportiert."""
    result = discover_domains(scope="all", probe=True, include_repos=True)
    foerderplaner = next((d for d in result["domains"] if d["id"] == "foerderplaner"), None)
    if foerderplaner:
        assert isinstance(foerderplaner["capabilities"], list)
        assert len(foerderplaner["capabilities"]) > 0
        assert "boundaries" in foerderplaner
        assert foerderplaner["evidence_type"] == "manifest_present"


# =========================================================================
# GUX-069: 4 Zustaende getrennt & private/Repo-Domaenen
# =========================================================================

def test_gux_069_four_states_strictly_separated():
    """GUX-069: Definition, Installation, Probe und Runtime sind 4 strikt getrennte Zustaende."""
    result = discover_domains(scope="all", probe=True, include_repos=True)
    for d in result["domains"]:
        states = d["states"]
        assert "defined" in states, f"{d['id']} fehlt states.defined"
        assert "installed" in states, f"{d['id']} fehlt states.installed"
        assert "probe" in states, f"{d['id']} fehlt states.probe"
        assert "runtime" in states, f"{d['id']} fehlt states.runtime"

        # Typ- und Werte-Garantien
        assert isinstance(states["defined"], bool)
        assert isinstance(states["installed"], bool)
        assert states["probe"] in ("healthy", "available", "unprobed", "offline", "unresponsive", "missing_files", "untested")
        assert states["runtime"] in ("ready", "running", "active", "idle", "inert", "stopped", "untracked")

        # Definition darf NIE Installation implizieren
        if not states["installed"]:
            assert states["defined"] is True  # Manifest existiert, aber Code muss nicht installiert sein


def test_gux_069_private_domains_and_additional_repos():
    """GUX-069: Private Domaenen (foerderplaner, steuer-suite, ai-media-editor) und Repos sichtbar."""
    result = discover_domains(scope="all", probe=True, include_repos=True)
    ids = {d["id"] for d in result["domains"]}

    # Pruefen, dass private/fachliche Module geladen werden
    found_private = [d for d in result["domains"] if d.get("is_private") or d.get("visibility") == "private"]
    assert len(found_private) > 0, "Private Module muessen mit scope='all' enthalten sein"

    # Spezifische Domaenen aus GUX-069 Anforderung
    for expected in ("foerderplaner", "steuer-suite"):
        assert expected in ids, f"GUX-069 fordert Einbindung von '{expected}'"


# =========================================================================
# GUX-070: Fachmenues & Semantik (Wissens-/Datenraeume, nicht Agenten)
# =========================================================================

def test_gux_070_domains_are_not_agents():
    """GUX-070: Domaenen sind Wissens- und Datenraeume, keine Agenten."""
    result = discover_domains(scope="all", probe=True, include_repos=True)
    for d in result["domains"]:
        assert d.get("is_agent") is False
        assert d.get("kind") != "agent"
        assert d.get("kind") in ("service", "domain", "fachmodul", "suite", "workflow", "library", "runtime", "app", "unknown")


def test_gux_070_steuer_assistent_display_name_and_foerderplaner_link():
    """GUX-070: Steuer-Assistent Name und Foerderplaner linkt auf /foerderplaner (nie /agents/foerderplaner)."""
    result = discover_domains(scope="all", probe=True, include_repos=True)
    domain_map = {d["id"]: d for d in result["domains"]}

    # Foerderplaner
    assert "foerderplaner" in domain_map
    fp = domain_map["foerderplaner"]
    assert fp["workbench_url"] == "/foerderplaner"
    assert "/agents/" not in fp["workbench_url"], "GUX-070: Foerderplaner darf nie nach /agents/... verlinken"

    # Steuer-Assistent / Steuer-Suite
    steuer = domain_map.get("steuer-suite") or domain_map.get("theodor-steuer")
    assert steuer is not None
    assert "steuer" in steuer["name"].lower() or "steuer" in steuer["display_name"].lower()
    assert steuer["workbench_url"] in ("/steuer", "/steuer-assistent")


def test_gux_070_direct_fachseiten_http_200(client):
    """GUX-070: Direkte Fachseiten-Routen antworten mit 200."""
    res_fp = client.get("/foerderplaner")
    assert res_fp.status_code == 200

    res_steuer = client.get("/steuer-assistent")
    assert res_steuer.status_code == 200

    res_domains = client.get("/domains")
    assert res_domains.status_code == 200


# =========================================================================
# GUX-071: Domaenen-Pins, Stabile IDs, Readback und Fallback
# =========================================================================

def test_gux_071_pin_management_with_stable_ids(temp_pin_file):
    """GUX-071: Domaenen-Pins speichern, lesen und mit stabilen IDs validieren."""
    # Anfangs leer
    initial = get_domain_pins()
    assert isinstance(initial, list)

    # Pin hinzufuegen
    updated = save_domain_pins([
        {"id": "foerderplaner", "label": "Förderplaner", "icon": "📋", "url": "/foerderplaner"},
        {"id": "ati", "label": "ATI", "icon": "💼", "url": "/ati"},
    ])
    assert len(updated) == 2
    assert updated[0]["id"] == "foerderplaner"
    assert updated[1]["id"] == "ati"

    # Readback aus Speicher pruefen
    readback = get_domain_pins()
    assert len(readback) == 2
    assert {p["id"] for p in readback} == {"foerderplaner", "ati"}

    # Ungueltige / gefaehrliche IDs muessen abgelehnt/ignoriert werden
    saved = save_domain_pins([
        {"id": "../invalid-path", "label": "Hack"},
        {"id": "foerderplaner", "label": "Förderplaner"},
    ])
    assert len(saved) == 1
    assert saved[0]["id"] == "foerderplaner"


def test_gux_071_toggle_domain_pin(temp_pin_file):
    """GUX-071: Einzelnen Pin ein- und ausschalten (toggle)."""
    # Pin setzen
    p1 = toggle_domain_pin("foerderplaner", pinned=True)
    assert "foerderplaner" in p1["pins"]
    assert p1["pinned"] is True

    # Pin entfernen
    p2 = toggle_domain_pin("foerderplaner", pinned=False)
    assert "foerderplaner" not in p2["pins"]
    assert p2["pinned"] is False


def test_gux_071_fallback_on_missing_adapter(temp_pin_file):
    """GUX-071: Fehlender Adapter liefert Fallback-Konfiguration."""
    pins = save_domain_pins([
        {"id": "unbekanntes-modul", "label": "Unbekannt"},
    ])
    assert len(pins) == 1
    assert pins[0]["fallback"] is True
    assert pins[0]["fallback_url"] == "/domains"


def test_gux_071_api_endpoints(client, temp_pin_file):
    """GUX-071: REST-API fuer Pins /api/domains/pins und /api/domains/{id}/pin."""
    # 1. GET /api/domains/pins
    res = client.get("/api/domains/pins")
    assert res.status_code == 200
    assert "pins" in res.json()

    # 2. POST /api/domains/foerderplaner/pin
    res_post = client.post("/api/domains/foerderplaner/pin", json={"pinned": True})
    assert res_post.status_code == 200
    data = res_post.json()
    assert data["success"] is True
    assert "foerderplaner" in data["pins"]

    # 3. GET Detail /api/domains/foerderplaner
    res_detail = client.get("/api/domains/foerderplaner")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["domain"]["id"] == "foerderplaner"
    assert detail["domain"]["is_agent"] is False
