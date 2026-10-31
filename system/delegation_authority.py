"""
Delegations-Autonomielevel-Verwaltung für Bereiche.

Autonome Stufen:
- manuell: erfordert menschliche Genehmigung (Ruhefrage)
- teilautomatisch: Einwilligung erforderlich bei außerhalb des Bereichs liegenden Handlungen
- vollautomatisch: handelt und informiert, keine Genehmigung erforderlich, informiert automatisch.
"""

AUTONOMY_LEVELS = ["manuell", "teilautomatisch", "vollautomatisch"]
DEFAULT_AUTONOMY_LEVEL = "manuell"

# Bekannte Bereiche, für die Autonomiestufen konfiguriert werden können.
ACTIONS = ["bildschirmsteuerung", "linkedin", "youtube", "mail"]


class PermissionDenied(Exception):
    """Ausnahme, wenn eine Handlung aufgrund ungültiger Autonomie abgelehnt wird."""
    pass


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
        der Override-Level oder None
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

    Raises:
        PermissionDenied: wenn autonomy_level kein gültiger Autonomielevel ist
    """
    try:
        level = _normalize_autonomy_level(autonomy_level)
    except ValueError as exc:
        raise PermissionDenied(
            f"Ungültige Autonomiestufe: {autonomy_level}. "
            f"Erlaubt sind: {', '.join(AUTONOMY_LEVELS)}"
        ) from exc

    area = act.split("/")[0] if "/" in act else "unbekannt"
    override = _get_override(area)
    effective_level = _normalize_autonomy_level(override) if override is not None else level

    decision = "rueckfrage"
    needs_ticket = True
    direct_order = False
    inform = False

    if effective_level == "vollautomatisch":
        decision = "erlaubt"
        needs_ticket = False
        direct_order = True
        inform = True
    elif effective_level == "teilautomatisch":
        decision = "erlaubt"
        needs_ticket = False
        direct_order = True
        inform = False
    elif effective_level == "manuell":
        pass

    return {
        "decision": decision,
        "needs_ticket": needs_ticket,
        "autonomy_level": effective_level,
        "direct_order": direct_order,
        "inform": inform,
    }
