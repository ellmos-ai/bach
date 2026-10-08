# -*- coding: utf-8 -*-
"""Kleiner Besetzungs-Seam für den ersten agents-heart-Pfad.

Dieses Modul entscheidet weder Modelle noch Backends. Es prüft nur den
Vertrag des ausführenden Pfads und schreibt die korrelierbaren Start-/Ende-
Ereignisse einer Besetzung. Dadurch kann der produktive Worker später aus
BACH herausgelöst werden, ohne die Fachlogik der Aufgabenbearbeitung
mitzunehmen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid
from typing import Any, Callable, Dict


class AssignmentDenied(RuntimeError):
    """Die Rolle besitzt den angeforderten Ausführungszugriff nicht."""


@dataclass(frozen=True)
class RoleContract:
    """Minimaler, versionierter Rechtevertrag für einen produktiven Pfad."""

    role_id: str
    revision: str
    rights: frozenset[str]


ROLE_CONTRACTS: Dict[str, RoleContract] = {
    "hintergrund_worker": RoleContract(
        role_id="hintergrund_worker",
        revision="v1",
        rights=frozenset({"task.claim", "task.execute"}),
    ),
    "task_worker": RoleContract(
        role_id="task_worker",
        revision="v1",
        rights=frozenset({"task.claim", "task.execute"}),
    ),
    "boss_routing": RoleContract(
        role_id="boss_routing",
        revision="v1",
        rights=frozenset({"task.claim", "task.execute"}),
    ),
    "expert_role": RoleContract(
        role_id="expert_role",
        revision="v1",
        rights=frozenset({"task.claim", "task.execute"}),
    ),
}

_REQUIRED_RIGHTS = frozenset({"task.claim", "task.execute"})


@dataclass(frozen=True)
class Assignment:
    """Unveränderliche Identität einer einzelnen Task-Besetzung."""

    assignment_id: str
    role_id: str
    role_revision: str
    agent_instance_id: str
    backend_id: str
    model_id: str
    slot_id: str
    task_id: int | str
    session_id: str
    initiated_by: str
    started_at: str


def authorize_role(role_id: str, mode: str) -> RoleContract:
    """Prüft den Rechtevertrag fail-closed, bevor der Executor startet."""
    normalized = str(role_id or "").strip()
    contract = ROLE_CONTRACTS.get(normalized)
    if contract is None:
        raise AssignmentDenied(f"unbekannte Rolle: {normalized or '(leer)'}")
    if mode not in {"safe", "full"}:
        raise AssignmentDenied(f"unbekannter Ausführungsmodus: {mode!r}")
    if not _REQUIRED_RIGHTS.issubset(contract.rights):
        raise AssignmentDenied(
            f"Rolle {contract.role_id!r} besitzt nicht alle Rechte für Task-Ausführung"
        )
    return contract


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Besetzungsfeld {name} fehlt")
    return text


def _event_details(
    assignment: Assignment,
    *,
    event: str,
    status: str,
    ended_at: str | None = None,
    result: str = "",
    reason: str = "",
) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "assignment_id": assignment.assignment_id,
        "event": event,
        "role_id": assignment.role_id,
        "role_revision": assignment.role_revision,
        "agent_instance_id": assignment.agent_instance_id,
        "backend_id": assignment.backend_id,
        "model_id": assignment.model_id,
        "slot_id": assignment.slot_id,
        "task_id": assignment.task_id,
        "session_id": assignment.session_id,
        "initiated_by": assignment.initiated_by,
        "started_at": assignment.started_at,
        "status": status,
    }
    if ended_at:
        details["ended_at"] = ended_at
    if result:
        details["result"] = result
    if reason:
        details["reason"] = reason
    return details


def begin_assignment(
    *,
    role_id: str,
    mode: str,
    agent_instance_id: str,
    backend_id: str,
    model_id: str,
    slot_id: str,
    task_id: int | str,
    session_id: str | None = None,
    initiated_by: str | None = None,
    event_recorder: Callable[[Dict[str, Any]], None],
) -> Assignment:
    """Beginnt eine Task-Besetzung und zeichnet den Startnachweis auf.

    ``session_id`` und ``initiated_by`` sind optional: Fehlen sie, erzeugt
    das Modul selbst eine Session-ID bzw. fällt auf ``agent_instance_id``
    zurück (BACH-Adapter reicht beide immer durch).
    """
    contract = authorize_role(role_id, mode)

    assignment_id = str(uuid.uuid4())
    agent_instance_id = _require_text("agent_instance_id", agent_instance_id)
    backend_id = _require_text("backend_id", backend_id)
    model_id = _require_text("model_id", model_id)
    slot_id = _require_text("slot_id", slot_id)
    session_id = session_id or str(uuid.uuid4())
    started_at = _utc_now()

    assignment = Assignment(
        assignment_id=assignment_id,
        role_id=role_id,
        role_revision=contract.revision,
        agent_instance_id=agent_instance_id,
        backend_id=backend_id,
        model_id=model_id,
        slot_id=slot_id,
        task_id=task_id,
        session_id=session_id,
        initiated_by=initiated_by or agent_instance_id,  # Fallback auf Instanz-ID
        started_at=started_at,
    )

    details = _event_details(
        assignment,
        event="assignment.started",
        status="started",
    )
    event_recorder(details)

    return assignment


def finish_assignment(
    *,
    assignment: Assignment,
    status: str,
    event_recorder: Callable[[Dict[str, Any]], None],
    result: str = "",
    reason: str = "",
) -> None:
    """Beendet eine Task-Besetzung und zeichnet den Endnachweis auf."""
    if status not in {"completed", "released", "error", "interrupted"}:
        raise ValueError(f"ungültiger Status: {status!r}")

    ended_at = _utc_now()
    details = _event_details(
        assignment,
        event="assignment.ended",
        status=status,
        ended_at=ended_at,
        result=result,
        reason=reason,
    )
    event_recorder(details)