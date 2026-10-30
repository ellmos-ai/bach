"""
Agenten-Herde – Rechte, Budgets und Autonomie-Level pro Bereich.

Verwaltet:
- effektive Autonomielevel pro Bereich (aus der Konfiguration gelesen)
- Berechtigungen (rollenbasierte Verfügbarkeit)
- Ausgabenbudgets, die vom Automatisierungssystem definiert werden
"""

from pathlib import Path
from .delegation_authority import evaluate_permission, AUTONOMY_LEVELS
from .automation_master import (
    get_autonomy,
    set_autonomy,
    enable_test_mode,
    record_metric,
    set_budget,
    use_budget,
)

# Externe Einfuhr: Definiere hier die Aktionen × Akteure des Systems.
# Im vollständigen System wird dies aus der Fächerdatei importiert.
# Für die Selbstprüfung definieren wir ein Miniaturverzeichnis.
_ACTIONS = {
    "bildschirmsteuerung/app/ausführen",
    "linkedin/post/hintergrund",
    "youtube/video/abspielen",
    "mail/senden",
    "test/zufällig",
}

_ACTORS = {
    "hintergrundworker",
    "task_worker",
    "boss_routing",
    "expertenrolle",
}

# Anfangsrechte: Akteur → Menge von Handlungen, die er ausführen kann
_DEFAULT_PERMISSIONS = {
    "hintergrundworker": {"bildschirmsteuerung/app/ausführen", "youtube/video/abspielen"},
    "task_worker": {"bildschirmsteuerung/app/ausführen", "linkedin/post/hintergrund", "mail/senden"},
    "boss_routing": set(_ACTIONS),  # alles
    "expertenrolle": {"mail/senden"},
}

# Pro Bereich definierte Autonome-Stufen (in der Konfiguration gespeichert).
# Dieses Mapping wird dynamisch geladen, wenn nötig.
# Der effektive Level für einen Bereich ist:
#   Übergeordnet → Konfiguration → Überführung über evaluate_permission

_effective_autonomy_levels_cache = {}
def _load_areas_from_filesystem():
    """
    Suchen nach Bereichsverzeichnis unter system/areas/ oder ähnlich.
    Gibt eine Liste von Bereichs-IDs zurück.
    """
    # Platzhalter: In der Hauptumgebung besteht dies aus einem Scan der Agentenkonfigurationsdateien.
    # Für den Testbetrieb definieren wir statische Bereiche.
    return ["bildschirmsteuerung", "linkedin", "youtube", "mail"]
def _ensure_cached():
    if not _effective_autonomy_levels_cache:
        for area in _load_areas_from_filesystem():
            lvl = get_autonomy(area)
            if lvl is None:
                # Standardkonfiguration, falls nicht festgelegt
                lvl = "manuell"
                set_autonomy(area, lvl)
            _effective_autonomy_levels_cache[area] = lvl

# Berechtigungen pro Akteur (rollenbasiert)
_permissions = {actor: set(actions) for actor, actions in _DEFAULT_PERMISSIONS.items()}
def _record_action_metric(act, actor, area, success: bool, intervention: bool = False):
    if area:
        record_metric(area, "inputs_processed", 1)
        if not success:
            record_metric(area, "errors", 1)
        if intervention:
            record_metric(area, "interventions", 1)
def has_permission(actor, act):
    """Gibt True zurück, wenn Akteur die Handlung gemäß den Rollenregeln ausführen darf."""
    return actor in _permissions and act in _permissions[actor]
def grant_permission(actor, act):
    _permissions.setdefault(actor, set()).add(act)
def revoke_permission(actor, act):
    _permissions.get(actor, set()).discard(act)
def effective_autonomy_levels():
    """Gibt ein dict Bereich→level zurück (dient dem externen Import)."""
    _ensure_cached()
    return _effective_autonomy_levels_cache.copy()
def evaluate_permission_for_area(act, actor):
    """
    Vollständige Evaluate-Pipeline: prüft, ob Akteur die Handlung ausführen darf und ruft
    dann die Autonomielevel-Regel für diesen Bereich ab.

    Returns: dict mit decision, needs_ticket, autonomy_level, direct_order, inform.
    """
    area = act.split("/")[0] if "/" in act else "unbekannt"
    if not has_permission(actor, act):
        # Keine Rechte: als "nie" behandeln
        return {
            "decision": "nie",
            "needs_ticket": False,
            "autonomy_level": effective_autonomy_levels().get(area, "manuell"),
            "direct_order": False,
            "inform": False,
        }
    level = effective_autonomy_levels().get(area, "manuell")
    return evaluate_permission(act, actor, level)
def get_agent_capability_summary():
    """
    Nützliche Debug-Funktion, die Rollen und Berechtigungen zusammenfasst.
    """
    summary = {}
    for actor in _permissions:
        summary[actor] = list(sorted(_permissions[actor]))
    return summary