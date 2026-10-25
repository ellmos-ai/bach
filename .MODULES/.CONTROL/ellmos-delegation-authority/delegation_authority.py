"""ellmos-delegation-authority — Außenwirkungs-Erlaubnisse für Ocean/BACH.

NOTICE: Grundidee und Matrixstruktur (permission_matrix: Handlung × Akteur
→ erlaubt/Rückfrage/nie mit Rangfolge aus Zellenwerten und Standardwerten)
wurden aus SentinelFleet (AGPL-3.0) übernommen. Lukas ist alleiniger
Rechteinhaber von SentinelFleet und hat die übernommenen Teile mit
Zustimmung unter MIT neu lizenziert (siehe NOTICE und MANIFEST.json in
diesem Ordner).

Aufgabentrennung (Q6):
  - LOCK.permissions.json / Lock-Master  = Datei- und Projektrechte.
  - Dieses Modul (delegation-authority)  = Außenwirkung von Handlungen
    (Bildschirmsteuerung, LinkedIn, YouTube, Mail) je Akteur.
  - Beide Bereiche werden über die gemeinsame Prüfschnittstelle
    controlcenter_evaluate_permission geprüft.
  - Rückfragen (decision "rueckfrage") laufen als Freigabekarte über
    ticket-master.

Bauart wie agents-heart: reine, deterministische Prüfbibliothek —
kein hub-Import, keine Datenbank, kein Netzwerk; Audit-Events werden
optional über einen event_recorder-Callback ausgeliefert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

MODULE_NAME = "ellmos-delegation-authority"

ACTIONS: Tuple[str, ...] = (
    "bildschirmsteuerung",
    "linkedin",
    "youtube",
    "mail",
)

ACTORS: Tuple[str, ...] = (
    "buddha",
    "claude-konsole",
    "codex",
    "hintergrundworker",
)

DECISIONS: Tuple[str, ...] = (
    "erlaubt",
    "rueckfrage",
    "nie",
)

# Hintergrundworker ist kein Operator; die Operatoren tragen Ränge.
OPERATOR_RANK: Dict[str, int] = {
    "buddha": 3,
    "claude-konsole": 2,
    "codex": 1,
}

# Eskalationsleiter für Rückfragen (Freigabekarte über ticket-master).
ESCALATION_LADDER: Tuple[str, ...] = ("buddha", "claude-konsole", "codex")

ESCALATION_HINT = (
    "Freigabekarte über ticket-master an Eskalationsleiter "
    "buddha → claude-konsole → codex"
)

NOTICE_TEXT = (
    "Grundidee und Matrixstruktur aus SentinelFleet (AGPL-3.0) übernommen; "
    "mit Zustimmung des alleinigen Rechteinhabers Lukas unter MIT neu "
    "lizenziert (siehe NOTICE)."
)

MATRIX_REVISION = "v1"

# Raster: Handlung × Akteur → Entscheidung.
# - cells: action -> actor -> decision (explizite Zellen, initial leer)
# - row_defaults: Standard je Akteur (Standard ist Rückfrage,
#   Hintergrundworker nie)
# - column_defaults: Standard je Handlung (alle vier: Rückfrage)
# - fallback: letzte Instanz der Rangfolge (Rückfrage)
DEFAULT_MATRIX: Dict[str, Any] = {
    "revision": MATRIX_REVISION,
    "cells": {action: {} for action in ACTIONS},
    "row_defaults": {
        "buddha": "rueckfrage",
        "claude-konsole": "rueckfrage",
        "codex": "rueckfrage",
        "hintergrundworker": "nie",
    },
    "column_defaults": {action: "rueckfrage" for action in ACTIONS},
    "fallback": "rueckfrage",
}


@dataclass(frozen=True)
class PermissionDecision:
    """Unveränderliches Prüfergebnis für eine Handlung-×-Akteur-Kombination."""

    action: str
    actor: str
    decision: str
    reason: str
    source: str
    needs_ticket: bool
    escalation_hint: str
    revision: str


class PermissionDenied(RuntimeError):
    """Fail-closed: ungültige oder unbekannte Werte verweigern die Prüfung."""


def _utc_now() -> str:
    """ISO-8601-Zeitstempel in UTC."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_matrix(matrix: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Matrix prüfen und vervollständigen (fail-closed).

    Fehlende Teile werden aus DEFAULT_MATRIX ergänzt. Ungültige Strukturen,
    unbekannte Handlungen/Akteure oder ungültige Entscheidungen lösen
    PermissionDenied aus statt stillschweigend zu erlauben.
    """
    if matrix is None:
        return DEFAULT_MATRIX
    if not isinstance(matrix, dict):
        raise PermissionDenied("Permission-Matrix muss ein dict sein")

    cells = matrix.get("cells", DEFAULT_MATRIX["cells"])
    row_defaults = matrix.get("row_defaults", DEFAULT_MATRIX["row_defaults"])
    column_defaults = matrix.get(
        "column_defaults", DEFAULT_MATRIX["column_defaults"]
    )
    fallback = matrix.get("fallback", DEFAULT_MATRIX["fallback"])

    if not isinstance(cells, dict):
        raise PermissionDenied("Permission-Matrix: 'cells' muss ein dict sein")
    if not isinstance(row_defaults, dict) or not isinstance(column_defaults, dict):
        raise PermissionDenied(
            "Permission-Matrix: Standardwerte müssen dicts sein"
        )
    if fallback not in DECISIONS:
        raise PermissionDenied(
            f"Permission-Matrix: ungültiger Fallback {fallback!r}"
        )

    for action, row in cells.items():
        if action not in ACTIONS:
            raise PermissionDenied(f"Unbekannte Handlung in Matrix: {action!r}")
        if not isinstance(row, dict):
            raise PermissionDenied(f"Zellen für {action!r} müssen ein dict sein")
        for actor, decision in row.items():
            if actor not in ACTORS:
                raise PermissionDenied(
                    f"Unbekannter Akteur in Matrix: {actor!r}"
                )
            if decision not in DECISIONS:
                raise PermissionDenied(
                    f"Ungültige Entscheidung {decision!r} "
                    f"für {action!r}/{actor!r}"
                )

    return {
        "revision": matrix.get("revision", MATRIX_REVISION),
        "cells": cells,
        "row_defaults": row_defaults,
        "column_defaults": column_defaults,
        "fallback": fallback,
    }


def evaluate_permission(
    action: str,
    actor: str,
    matrix: Optional[Dict[str, Any]] = None,
    event_recorder: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> PermissionDecision:
    """Entscheidung für eine Handlung-×-Akteur-Kombination bestimmen.

    Rangfolge (erste Übereinstimmung gewinnt):
      1. explizite Zelle   cells[action][actor]
      2. Zeilen-Standard   row_defaults[actor]
                           (Akteur-Standard; im SentinelFleet-Original
                           sind Akteure die Zeilen)
      3. Spalten-Standard  column_defaults[action] (Handlungs-Standard)
      4. Fallback          matrix["fallback"]

    Fail-closed: unbekannte Handlungen oder Akteure sowie ungültige
    Entscheidungen lösen PermissionDenied aus — nichts wird stillschweigend
    erlaubt.

    Bei "rueckfrage" wird needs_ticket=True gesetzt und ein
    Eskalations-Hinweis für die Freigabekarte über ticket-master
    mitgegeben. Wenn event_recorder gegeben ist, wird ein Audit-Event
    (dict mit ISO-UTC-Zeitstempel) ausgeliefert.
    """
    if action not in ACTIONS:
        raise PermissionDenied(f"Unbekannte Handlung: {action!r}")
    if actor not in ACTORS:
        raise PermissionDenied(f"Unbekannter Akteur: {actor!r}")

    resolved = _normalize_matrix(matrix)

    cell_value = resolved["cells"].get(action, {}).get(actor)
    if cell_value is not None:
        decision_value = cell_value
        source = "explicit cell"
        reason = (
            f"Explizite Zelle {action!r}/{actor!r} = {cell_value!r} "
            "(Rang 1 der Rangfolge)."
        )
    else:
        row_value = resolved["row_defaults"].get(actor)
        if row_value is not None:
            decision_value = row_value
            source = "row default (Akteur-Standard)"
            reason = (
                f"Keine explizite Zelle; Akteur-Standard für {actor!r} "
                f"= {row_value!r} (Rang 2 der Rangfolge)."
            )
        else:
            column_value = resolved["column_defaults"].get(action)
            if column_value is not None:
                decision_value = column_value
                source = "column default (Handlungs-Standard)"
                reason = (
                    f"Keine Zelle und kein Akteur-Standard; Handlungs-Standard "
                    f"für {action!r} = {column_value!r} (Rang 3 der Rangfolge)."
                )
            else:
                decision_value = resolved["fallback"]
                source = "fallback"
                reason = (
                    f"Keine Zelle und keine Standards; Fallback "
                    f"= {decision_value!r} (Rang 4 der Rangfolge)."
                )

    if decision_value not in DECISIONS:
        raise PermissionDenied(
            f"Ungültige Entscheidung {decision_value!r} für "
            f"{action!r}/{actor!r}"
        )

    needs_ticket = decision_value == "rueckfrage"
    escalation_hint = ESCALATION_HINT if needs_ticket else ""

    result = PermissionDecision(
        action=action,
        actor=actor,
        decision=decision_value,
        reason=reason,
        source=source,
        needs_ticket=needs_ticket,
        escalation_hint=escalation_hint,
        revision=resolved["revision"],
    )

    if event_recorder is not None:
        event_recorder(
            {
                "module": MODULE_NAME,
                "event": "permission_evaluated",
                "action": action,
                "actor": actor,
                "decision": decision_value,
                "reason": reason,
                "source": source,
                "timestamp": _utc_now(),
                "revision": resolved["revision"],
            }
        )

    return result


def controlcenter_evaluate_permission(
    action: str,
    actor: str,
    matrix: Optional[Dict[str, Any]] = None,
    event_recorder: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> PermissionDecision:
    """Gemeinsame Control-Center-Prüfschnittstelle (Q6).

    Aufgabentrennung:
      - LOCK.permissions.json / Lock-Master = Datei- und Projektrechte.
      - ellmos-delegation-authority (dieses Modul) = Außenwirkung.
      - Beide Bereiche werden über diese gemeinsame evaluate-Schnittstelle
        geprüft; dieser Aufruf entscheidet über die Außenwirkung.

    Dünner Wrapper auf evaluate_permission, damit Aufrufer (BACH, Ocean,
    Control-Center) eine einzige, stabile Prüfadresse haben.
    """
    return evaluate_permission(
        action=action,
        actor=actor,
        matrix=matrix,
        event_recorder=event_recorder,
    )


def get_permission_matrix_overview() -> Dict[str, Any]:
    """Übersicht der Berechtigungs-Matrix für die GUI (Governance & Control)."""
    matrix = DEFAULT_MATRIX
    return {
        "actions": list(ACTIONS),
        "actors": list(ACTORS),
        "decisions": list(DECISIONS),
        "row_defaults": dict(matrix["row_defaults"]),
        "column_defaults": dict(matrix["column_defaults"]),
        "fallback": matrix["fallback"],
        "cells": {
            action: dict(matrix["cells"].get(action, {}))
            for action in ACTIONS
        },
        "operators": [
            {"actor": actor, "rank": OPERATOR_RANK[actor]}
            for actor in ESCALATION_LADDER
        ],
        "escalation_ladder": list(ESCALATION_LADDER),
        "revision": matrix["revision"],
        "notice": NOTICE_TEXT,
    }