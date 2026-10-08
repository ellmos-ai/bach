"""BACH-Import-Adapter für das provider-/produktneutrale Modul agents-heart.

Task #1716: Die Besetzungs- und Autorisierungslogik (Role Contracts,
Assignment-Tracking, korrelierte Start-/Ende-Ereignisse, fail-closed
Autorisierung) lebt als versioniertes, produktneutrales Modul unter
``.MODULES/.CONTROL/agents-heart/`` (MANIFEST.json, SemVer v0.1.0, MIT,
dependencies = []). Diese Datei ist der dünne BACH-seitige Adapter:

- Lädt das neutrale Modul per ``importlib`` aus seinem Pfad (kein
  sys.path-Eingriff); die Umgebungsvariable ``BACH_AGENTS_HEART_MODULE``
  überschreibt den Pfad für Tests/Integration.
- Re-exportiert dessen Symbole 1:1 (inkl. ``_REQUIRED_RIGHTS``).
- Übersetzt die neutralen Ereignisse (``assignment.started`` /
  ``assignment.ended``) in BACH-Aktivitätseinträge über
  ``hub._services.chat.slots_config.record_activity`` mit dem flachen
  Legacy-Feld ``event`` (``assignment_started``/``assignment_ended``).

BACH-spezifisch ist ausschließlich dieser Adapter; das neutrale Modul
kommt mit Python-Stdlib allein aus. Migration: alle Aufrufer
(``telegram_chat.py``, ``worker.py``, ``trithon_dispatch.py``) bleiben
unverändert, weil die Adapter-Signatur dem bisherigen BACH-Original
entspricht (``session_id``/``initiated_by`` Pflicht-Keywords, ``path``
optional, ``finish_assignment`` mit positionalem ``assignment``).

Rollback: ``git checkout <HEAD> -- system/hub/_services/agents_heart.py``
stellt das eigenständige BACH-Original wieder her; das neutrale Modul
ist rein additiv und kann bleiben.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict

from hub._services.chat.slots_config import record_activity

_MODULE_NAME = "bach_agents_heart_core"
_DEFAULT_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / ".MODULES" / ".CONTROL" / "agents-heart" / "agents_heart.py"
)


def _load_agents_heart():
    """Lädt das neutrale agents-heart-Modul (Stdlib-only) via importlib."""
    override = os.environ.get("BACH_AGENTS_HEART_MODULE")
    module_path = Path(override) if override else _DEFAULT_MODULE_PATH
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"agents-heart-Modul nicht ladbar: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_agents_heart = _load_agents_heart()

# ------------------------------------------------------------- Re-Exports
RoleContract = _agents_heart.RoleContract
ROLE_CONTRACTS = _agents_heart.ROLE_CONTRACTS
_REQUIRED_RIGHTS = _agents_heart._REQUIRED_RIGHTS
Assignment = _agents_heart.Assignment
AssignmentDenied = _agents_heart.AssignmentDenied
authorize_role = _agents_heart.authorize_role


def _event_recorder(path: str | None) -> Callable[[Dict[str, Any]], None]:
    """Baut den BACH-Event-Recorder für genau diesen Aufruf (``path``-Scope).

    Das neutrale Modul liefert ein Ereignis-Details-Dict; der Recorder
    übersetzt es in einen ``record_activity``-Eintrag im flachen
    BACH-Legacy-Format (``event`` = ``assignment_started`` bzw.
    ``assignment_ended``). ``path`` kommt aus dem Aufruf-Scope, weil es
    nicht Teil der neutralen Details ist.
    """

    def record(details: Dict[str, Any]) -> None:
        event = details.get("event")
        if event == "assignment.started":
            record_activity(
                details["slot_id"],
                f"Task #{details['task_id']} Besetzung gestartet",
                status="running",
                details={**details, "event": "assignment_started", "status": "running"},
                path=path,
            )
        elif event == "assignment.ended":
            record_activity(
                details["slot_id"],
                f"Task #{details['task_id']} Besetzung beendet",
                status=str(details.get("status", "ok")),
                details={**details, "event": "assignment_ended"},
                path=path,
            )
        else:  # fail-closed: neutrales Modul kennt nur die zwei Ereignisse
            raise ValueError(f"unbekanntes Besetzungsereignis: {event!r}")

    return record


def begin_assignment(
    *,
    role_id: str,
    mode: str,
    agent_instance_id: str,
    backend_id: str,
    model_id: str,
    slot_id: str,
    task_id: int | str,
    session_id: str,
    initiated_by: str,
    path: str | None = None,
) -> Assignment:
    """Beginnt eine Task-Besetzung und zeichnet den Startnachweis auf."""
    return _agents_heart.begin_assignment(
        role_id=role_id,
        mode=mode,
        agent_instance_id=agent_instance_id,
        backend_id=backend_id,
        model_id=model_id,
        slot_id=slot_id,
        task_id=task_id,
        session_id=session_id,
        initiated_by=initiated_by,
        event_recorder=_event_recorder(path),
    )


def finish_assignment(
    assignment: Assignment,
    *,
    status: str,
    result: str = "",
    reason: str = "",
    path: str | None = None,
) -> None:
    """Beendet eine Task-Besetzung und zeichnet den Endnachweis auf."""
    _agents_heart.finish_assignment(
        assignment=assignment,
        status=status,
        event_recorder=_event_recorder(path),
        result=result,
        reason=reason,
    )