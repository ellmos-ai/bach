# -*- coding: utf-8 -*-
"""Kleiner Besetzungs-Seam für den ersten agents-heart-Pfad.

Dieses Modul entscheidet weder Modelle noch Backends. Es prüft nur den
Vertrag des ausführenden Pfads und schreibt die korrelierbaren Start-/Ende-
Ereignisse einer Besetzung. Dadurch kann der produktive Worker später aus
BACH herausgelöst werden, ohne die Fachlogik der Aufgabenbearbeitung
mitzunehmen.

Produktneutral (v1.0):
    * Kein direkter Import aus hub._services.chat.slots_config.
    * Event-Sink über injizierbares Protocol AssignmentEventSink entkoppelt.
    * Default-Sink ist ein dünner BACH-Adapter (lazy-import), der
      record_activity() aufruft und die bestehenden flachen
      activity_history-Felder beibehält.
    * Alternative Sinks (Trithon-Transport, Noop, JSON-Lines) können
      injiziert werden, ohne BACH zu berühren.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid
from typing import Any, Dict, Optional, Protocol, runtime_checkable


# ── Neutrales Event-Sink-Interface (v1) ───────────────────────────────────
@runtime_checkable
class AssignmentEventSink(Protocol):
    """Produktneutrale Schnittstelle für das Ablegen von
    Besetzungsereignissen. Implementierungen können in BACH (record_activity),
    Trithon (LedgerEntry/ExecutionReceipt), Noop oder JSON-Lines-Zeile lauten.
    """

    def record(
        self,
        slot_id: str,
        activity: str,
        status: str,
        details: Dict[str, Any],
        path: Optional[str] = None,
    ) -> None:
        """Schreibt ein Besetzungsereignis in den hinterlegten Speicher."""
        ...


# ── BACH-Adapter (dünne Wrapper, lazy Import) ─────────────────────────────
class _BachActivitySink:
    """Default-Sink für BACH: ruft record_activity() aus slots_config auf,
    damit die bestehenden activity_history-Einträge und /api/activity-Reader
    unverändert funktionieren.
    """

    def record(
        self,
        slot_id: str,
        activity: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        path: Optional[str] = None,
    ) -> None:
        from hub._services.chat.slots_config import record_activity  # lazy
        record_activity(
            source=slot_id,
            activity=activity,
            status=status,
            details=details,
            path=path,
        )


# ── Ausnahmen ─────────────────────────────────────────────────────────────
class AssignmentDenied(RuntimeError):
    """Die Rolle besitzt den angeforderten Ausführungszugriff nicht."""


# ── Versionierte Rechteverträge ───────────────────────────────────────────
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


# ── Assignment-Datensatz ──────────────────────────────────────────────────
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


# ── Autorisierung ─────────────────────────────────────────────────────────
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


# ── Hilfsfunktionen ───────────────────────────────────────────────────────
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


# ── Besetzungslebenszyklus mit injizierbarem Sink ────────────────────────
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
    sink: AssignmentEventSink | None = None,
) -> Assignment:
    """Prüft die Rolle, erzeugt die ID und schreibt den Startnachweis.

    sink: Optionaler Event-Sink. Default = _BachActivitySink (lazy-import
    record_activity aus BACH slots_config). Für produktneutrale Nutzung
    einen eigenen Sink injizieren (Trithon, Noop, JSON-Lines).
    """
    contract = authorize_role(role_id, mode)
    if task_id is None:
        raise ValueError("Besetzungsfeld task_id fehlt")

    if sink is None:
        sink = _BachActivitySink()

    assignment = Assignment(
        assignment_id=f"asgn-{uuid.uuid4().hex}",
        role_id=contract.role_id,
        role_revision=contract.revision,
        agent_instance_id=_require_text("agent_instance_id", agent_instance_id),
        backend_id=_require_text("backend_id", backend_id),
        model_id=_require_text("model_id", model_id),
        slot_id=_require_text("slot_id", slot_id),
        task_id=task_id,
        session_id=_require_text("session_id", session_id),
        initiated_by=_require_text("initiated_by", initiated_by),
        started_at=_utc_now(),
    )
    details = _event_details(
        assignment,
        event="assignment_started",
        status="running",
    )
    sink.record(
        slot_id=assignment.slot_id,
        activity=f"Task #{assignment.task_id} Besetzung gestartet",
        status="running",
        details=details,
        path=path,
    )
    return assignment


def finish_assignment(
    assignment: Assignment,
    *,
    status: str,
    result: str = "",
    reason: str = "",
    path: str | None = None,
    sink: AssignmentEventSink | None = None,
) -> None:
    """Schreibt genau den korrelierten Endnachweis einer Besetzung.

    sink: Optionaler Event-Sink. Default = _BachActivitySink.
    """
    if status not in {"completed", "released", "error", "interrupted"}:
        raise ValueError(f"ungültiger Besetzungsstatus: {status!r}")

    if sink is None:
        sink = _BachActivitySink()

    details = _event_details(
        assignment,
        event="assignment_ended",
        status=status,
        ended_at=_utc_now(),
        result=result,
        reason=reason,
    )
    sink.record(
        slot_id=assignment.slot_id,
        activity=f"Task #{assignment.task_id} Besetzung beendet",
        status=status,
        details=details,
        path=path,
    )
