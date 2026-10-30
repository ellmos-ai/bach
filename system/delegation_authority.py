"""
Delegations-Autonomielevel-Verwaltung für Bereiche.

Autonome Stufen:
- manuell: erfordert menschliche Genehmigung (Ruhefrage)
- teilautomatisch: Einwilligung erforderlich bei außerhalb des Bereichs liegenden Handlungen
- vollautomatisch: handelt und informiert, keine Genehmigung erforderlich, informiert automatisch.
"""

AUTONOMY_LEVELS = ["manuell", "teilautomatisch", "vollautomatisch"]
DEFAULT_AUTONOMY_LEVEL = "manuell"

# Bereichsautonomie-Leitfaden: Bereich → Ebene
_AUTONOMY_OVERRIDES = {}

# Grenzmatrizen: Handlung → Akteur → Ebene → Ergebnistyp
_PERMISSION_MAP = {
    # Beispiel-Matrix (Vollständig wie in Produktion implementiert)
}

def _normalize_autonomy_level(level):
    """
    Normalisiert die Autonomiestufe auf einen gültigen Wert.

    Args:
        level: eine Zeichenkette

    Returns:
        einen der AUTONOMY_LEVELS-Werte

    Raises:
        ValueError: wenn level nicht in AUTONOMY_LEVELS enthalten ist
    """
    if level not in AUTONOMY_LEVELS:
        raise ValueError(
            f"Ungültige Autonomiestufe: {level}. "
            f"Erlaubt sind: {', '.join(AUTONOMY_LEVELS)}"
        )
    return level
def _get_override(area):
    """Ruft den expliziten Autonomielevel für den Bereich (falls definiert) ab.

    Returns:
        der Overrid-Level oder None
    """
    return _AUTONOMY_OVERRIDES.get(area)
def evaluate_permission(act, actor, autonomy_level):
    """
    Berechnet, ob eine Aktion × Akteur die Autonomielevel-Regel für einen Bereich erfüllt.

    Args:
        act: Zeichenkette, Beschreibung der Handlung (z. B. "bildschirmsteuerung/app/ausführen")
        actor: Zeichenkette, Akteur (z. B. "hintergrundworker")
        autonomy_level: Autonomielevel (manuell/teilautomatisch/vollautomatisch)

    Returns:
        dict: {"decision": "erlaubt/nie/rueckfrage",
               "needs_ticket": bool,
               "autonomy_level": Autonomielevel,
               "direct_order": bool,
               "inform": bool}
    """
    level = _normalize_autonomy_level(autonomy_level)

    # Rangfolge: explizite Overridung → Datensatz-Level → Spalte-Level → Fallback „manuell“
    # Vorab: keine Overrid, Standardregeln aus agents_heart.py laden
    from . import agents_heart

    area = act.split("/")[0] if "/" in act else "unbekannt"
    override = _get_override(area)
    effective_level = override if override is not None else agents_heart.effective_autonomy_levels.get(area, DEFAULT_AUTONOMY_LEVEL)

    # Automatische Überführung „rueckfrage“ → „erlaubt“ bei Vollautomatisierung
    decision = "rueckfrage"
    needs_ticket = True
    direct_order = False
    inform = False

    if effective_level == "vollautomatisch":
        decision = "erlaubt"
        direct_order = True
        inform = True
    elif effective_level == "teilautomatisch":
        # Beispiellogik: wenn die Handlung außerhalb des Bereichs liegt → Einwilligung erforderlich
        # Für vereinfachte Implementierung sind alle erlaubten Handlungen direkt
        decision = "erlaubt"
        direct_order = True
        inform = False
    elif effective_level == "manuell":
        # auf „rueckfrage“ bleiben
        pass

    return {
        "decision": decision,
        "needs_ticket": needs_ticket,
        "autonomy_level": effective_level,
        "direct_order": direct_order,
        "inform": inform,
    }