"""
Teste die Delegationsautonomie-Logik (delegation_authority.py).

Prüft:
- evaluate_permission mit Standard-Levels (manuell, teilautomatisch, vollautomatisch)
- _normalize_autonomy_level mit ungültigen Werten (ValueError)
- Integration mit agents_heart.py (effektive Level-Abfrage)
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

# Importiere delegation_authority.py und agents_heart.py dynamisch
# (unabhängig vom CWD).
def _import_module(name, file_path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Pfade relativ zum Task-Worktree
BASE = Path(__file__).resolve().parent.parent
DELEGATION_PATH = BASE / "delegation_authority.py"
AGENTS_HEART_PATH = BASE / "agents_heart.py"
AUTOMATION_MASTER_PATH = BASE / "automation_master.py"

# Modul-Instanzen laden
delegation = _import_module("delegation_authority", DELEGATION_PATH)
agents_heart = _import_module("agents_heart", AGENTS_HEART_PATH)
automation_master = _import_module("automation_master", AUTOMATION_MASTER_PATH)

def test_normalize_autonomy_level():
    # Gültige Stufen
    assert delegation._normalize_autonomy_level("manuell") == "manuell"
    assert delegation._normalize_autonomy_level("teilautomatisch") == "teilautomatisch"
    assert delegation._normalize_autonomy_level("vollautomatisch") == "vollautomatisch"
    # Ungültige Stufe
    try:
        delegation._normalize_autonomy_level("unbekannt")
        assert False, "ValueError erwartet"
    except ValueError:
        pass

def test_evaluate_permission_default_manuell():
    # Standard: manuell → rueckfrage, needs_ticket=True
    result = delegation.evaluate_permission("bildschirmsteuerung/app/ausführen", "hintergrundworker", "manuell")
    assert result["decision"] == "rueckfrage"
    assert result["needs_ticket"] is True
    assert result["autonomy_level"] == "manuell"
    assert result["direct_order"] is False
    assert result["inform"] is False

def test_evaluate_permission_vollautomatisch():
    # Vollautomatisch → erlaubt, direct_order=True, inform=True
    result = delegation.evaluate_permission("bildschirmsteuerung/app/ausführen", "hintergrundworker", "vollautomatisch")
    assert result["decision"] == "erlaubt"
    assert result["needs_ticket"] is False
    assert result["autonomy_level"] == "vollautomatisch"
    assert result["direct_order"] is True
    assert result["inform"] is True

def test_evaluate_permission_teilautomatisch():
    # Teilautomatisch → erlaubt, direct_order=True, inform=False
    result = delegation.evaluate_permission("linkedin/post/hintergrund", "task_worker", "teilautomatisch")
    assert result["decision"] == "erlaubt"
    assert result["needs_ticket"] is False
    assert result["autonomy_level"] == "teilautomatisch"
    assert result["direct_order"] is True
    assert result["inform"] is False

def test_evaluate_permission_invalid_level():
    try:
        delegation.evaluate_permission("test", "actor", "invalid")
        assert False, "ValueError erwartet"
    except ValueError:
        pass

def test_agents_heart_effective_autonomy_levels():
    # agents_heart.py sollte effektive Autonomielevel aus der Konfiguration laden.
    levels = agents_heart.effective_autonomy_levels()
    # Standardkonfiguration: alle Bereiche auf "manuell"
    for area in ["bildschirmsteuerung", "linkedin", "youtube", "mail"]:
        assert area in levels
        assert levels[area] == "manuell"

def test_agents_heart_evaluate_permission_for_area():
    # agents_heart.py: evaluate_permission_for_area
    result = agents_heart.evaluate_permission_for_area("bildschirmsteuerung/app/ausführen", "hintergrundworker")
    assert result["decision"] == "rueckfrage"
    assert result["needs_ticket"] is True
    assert result["autonomy_level"] == "manuell"

def test_automation_master_set_autonomy():
    # automation_master.py: set_autonomy(area, level)
    # Setze Bereich auf "vollautomatisch"
    automation_master.set_autonomy("linkedin", "vollautomatisch")
    assert automation_master.get_autonomy("linkedin") == "vollautomatisch"
    # Setze zurück auf "manuell"
    automation_master.set_autonomy("linkedin", "manuell")
    assert automation_master.get_autonomy("linkedin") == "manuell"

def test_automation_master_test_mode():
    automation_master.enable_test_mode(True)
    assert automation_master._load_config()["test_mode"] is True
    automation_master.enable_test_mode(False)
    assert automation_master._load_config()["test_mode"] is False

def test_automation_master_invalid_level():
    try:
        automation_master.set_autonomy("linkedin", "invalid")
        assert False, "AutomationSettingsError erwartet"
    except automation_master.AutomationSettingsError:
        pass