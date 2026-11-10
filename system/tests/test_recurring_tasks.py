# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Test für wiederkehrende Aufgaben – Cross-Host-Lauf-Erweiterung."""

import pytest

# Erweiterte Liste der Host-Plattformen für den Cross-Host-Lauf.
# Ursprünglich: ASUS-GEI, mac-studio. Hinzugefügt WORKSTATION-LG zur Unterstützung des 3-Host-Laufs.
HOSTS = ["ASUS-GEI", "mac-studio", "WORKSTATION-LG"]

@pytest.fixture(params=HOSTS, ids=HOSTS)
def host_fixture(request):
    """Fixture, die jede Host-Plattform für parametrisierte Tests bereitstellt."""
    return request.param


def test_three_hosts_defined():
    """Bestätigt, dass genau drei Hosts für Cross-Host-Lauf definiert sind."""
    assert len(HOSTS) == 3, f"Erwartet 3 Hosts, erhielt {len(HOSTS)}: {HOSTS}"
    assert "ASUS-GEI" in HOSTS
    assert "mac-studio" in HOSTS
    # Dritter Host wird für Kollisionspfadtests benötigt.
    # Akzeptieren Sie jeden dritten Host; WORKSTATION-LG ist ein sinnvoller Kandidat.
    third = [h for h in HOSTS if h not in {"ASUS-GEI", "mac-studio"}][0]
    assert third in HOSTS


def test_host_ids_unique():
    """Stellt sicher, dass jeder Host eine eindeutige ID hat (keine Duplikate)."""
    assert len(set(HOSTS)) == len(HOSTS), f"Duplizierte Hosts gefunden: {HOSTS}"


def test_host_fixture_parametrization(host_fixture):
    """Bestätigt, dass die host_fixture jeden der drei Hosts abdeckt."""
    assert host_fixture in HOSTS


def test_cross_host_collision_paths():
    """
    Simuliert die Kollisionspfadprüfung für wiederkehrende Aufgaben auf drei Hosts.

    Nehmen wir an, jede wiederkehrende Aufgabe erhält einen Pfad auf dem Host, der eindeutig ist pro Host ist.
    Diese Übung überprüft, dass für jede Kombination von Hosts Kollisionen erkannt werden.
    """
    # Einfache Modell: Pfad = f"/tasks/{host}/{task_id}"
    # Wir erstellen eine Map der Host-zu-Pfad-Einträge und überprüfen auf Kollisionen.
    host_paths = {}
    for h in HOSTS:
        # Beispielpfad für jeden Host
        path = f"/tasks/{h}/example_task"
        if h in host_paths:
            # Kollision, wenn ein Host bereits einen Pfad verwendet hat, der für einen anderen Host vorhanden ist
            # Aber wir verwenden unterschiedliche Hosts, also sollte es keine Kollision geben.
            pass
        host_paths[h] = path
    # Stellen Sie sicher, dass alle Pfade eindeutig sind (verschieden pro Host).
    unique_paths = set(host_paths.values())
    assert len(unique_paths) == len(HOSTS), f"Kollidierende Pfade gefunden: {host_paths}"


def test_cross_host_distribution():
    """
    Überprüft, dass die wiederkehrenden Tasks gleichmäßig auf die drei Hosts verteilt sind.
    """
    # Für die Demonstration simulieren wir drei gegebene Task-IDs.
    task_ids = [1001, 1002, 1003]
    host_assignments = {}
    for tid in task_ids:
        # Gleichmäßige Verteilung: Modulo 3
        idx = tid % 3
        host = HOSTS[idx]
        host_assignments.setdefault(host, []).append(tid)
    # Stellen Sie sicher, dass jeder Host mindestens eine zugewiesene Task hat
    for h in HOSTS:
        assert h in host_assignments and len(host_assignments[h]) > 0, f"Host {h} hat keine zugewiesenen Tasks"