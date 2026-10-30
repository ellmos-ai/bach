"""
Automatismusteuerung – zentrale Verwaltung der Autonomielevel-Einstellung pro Bereich.

Verwaltet eine JSON-Konfiguration in _state/areas_autonomy.json:
- levels: Bereich → Autonomiestufe (manuell/teilautomatisch/vollautomatisch)
- test_mode: bool, ob Qualität und Fehler protokolliert werden, ohne Genehmigungen zu ändern
- metrics: Bereich → {errors, interventions, inputs_processed}
- budgets: Bereich → {limit, used} für Ausgaben (z. B. Marketing-Buchungen)
"""

import json
import os
import sys
from pathlib import Path

try:  # Regulärer Paketimport (z. B. system.automation_master)
    from .delegation_authority import (
        AUTONOMY_LEVELS,
        DEFAULT_AUTONOMY_LEVEL,
        _normalize_autonomy_level,
    )
except ImportError:  # Direktimport bzw. dynamisches Laden als Top-Level-Modul
    _MODULE_DIR = str(Path(__file__).resolve().parent)
    if _MODULE_DIR not in sys.path:
        sys.path.insert(0, _MODULE_DIR)
    from delegation_authority import (  # type: ignore[no-redef]
        AUTONOMY_LEVELS,
        DEFAULT_AUTONOMY_LEVEL,
        _normalize_autonomy_level,
    )

_STATE_DIR = Path(__file__).parent / "_state"
_STATE_DIR.mkdir(exist_ok=True)
_CONFIG_PATH = _STATE_DIR / "areas_autonomy.json"

DEFAULT_CONFIG = {
    "levels": {},  # Bereich → "manuell"/"teilautomatisch"/"vollautomatisch"
    "test_mode": False,
    "metrics": {},  # Bereich → {errors: int, interventions: int, inputs_processed: int}
    "budgets": {},  # Bereich → {limit: float, used: float}
    "areas": [],   # Liste der definierten Bereiche (entspricht AREAS in agents_heart.py)
    "spending_areas": [],  # Bereiche, die Ausgaben erfassen (z. B. Marketing)
    "default_autonomy": DEFAULT_AUTONOMY_LEVEL,
}
class AutomationSettingsError(Exception):
    """Fehler innerhalb der Automatisierungs-Konfiguration."""
    pass
def _load_config():
    if not _CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Stelle sicher, dass alle erforderlichen Schlüssel vorhanden sind (Kompatibilität)
        for key in DEFAULT_CONFIG:
            cfg.setdefault(key, DEFAULT_CONFIG[key])
        return cfg
    except json.JSONDecodeError as e:
        raise AutomationSettingsError(f"Ungültiges JSON in der Automatisierungs-Konfiguration: {e}") from e
def _save_config(cfg):
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise AutomationSettingsError(f"Konnte Automatisierungs-Konfiguration nicht speichern: {e}") from e
def _validate_level(level):
    """Sicherstellen, dass der übergebene Level AUTONOMY_LEVELS ist."""
    try:
        _normalize_autonomy_level(level)
    except ValueError as e:
        raise AutomationSettingsError(str(e)) from e
def register_areas(areas):
    """
    Bereiche idempotent in der Konfiguration bekannt machen.

    set_autonomy() akzeptiert nur Bereiche, die in cfg["areas"] stehen. Diese
    Funktion synchronisiert die Bereichsliste, ohne bestehende Einträge zu
    verändern, und liefert die aktuelle Liste zurück.
    """
    cfg = _load_config()
    known = cfg.setdefault("areas", [])
    changed = False
    for area in areas:
        if area and area not in known:
            known.append(area)
            changed = True
    if changed:
        _save_config(cfg)
    return list(known)
def set_autonomy(area, level):
    """
    Konfiguriere die Autonomiestufe für einen Bereich.

    Args:
        area: Bereichsname (muss in system/areas/ definiert sein)
        level: einstellbare Stufe (manuell/teilautomatisch/vollautomatisch)

    Raises:
        AutomationSettingsError: wenn level ungültig ist oder area unbekannt ist
    """
    _validate_level(level)
    cfg = _load_config()
    if area not in cfg.get("areas", []):
        raise AutomationSettingsError(f"Unbekannter Bereich: {area}")
    cfg["levels"][area] = level
    _save_config(cfg)
    # Optional: Event-Emission für Ändermodelle (hier ignoriert)
    return True
def get_autonomy(area):
    cfg = _load_config()
    return cfg["levels"].get(area)
def enable_test_mode(enabled: bool):
    cfg = _load_config()
    cfg["test_mode"] = bool(enabled)
    _save_config(cfg)
    return cfg["test_mode"]
def record_metric(area, metric_type: str, value: int = 1):
    cfg = _load_config()
    m = cfg["metrics"].setdefault(area, {})
    m[metric_type] = m.get(metric_type, 0) + value
    _save_config(cfg)
def set_budget(area, limit: float):
    cfg = _load_config()
    cfg["budgets"][area] = {"limit": limit, "used": 0.0}
    _save_config(cfg)
def use_budget(area, amount: float):
    cfg = _load_config()
    b = cfg["budgets"].get(area)
    if not b:
        raise AutomationSettingsError(f"Kein Budget für den Bereich {area} definiert")
    if b["used"] + amount > b["limit"]:
        raise AutomationSettingsError(f"Überschreitung des Budgets für den Bereich {area}")
    b["used"] += amount
    cfg["budgets"][area] = b
    _save_config(cfg)
    return True