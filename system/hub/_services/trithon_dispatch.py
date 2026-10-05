# -*- coding: utf-8 -*-
"""Trithon Dispatch-Layer — Folgestufe 3.

Dieses Modul verbindet die interne Task-Infrastruktur (agents-heart für
Besetzungsnachweise, task_audit für atomares Claiming) mit dem neutralen
Transportvertrag (transport_contract). Es implementiert einen No-op-Executor,
also eine reine Durchlauf-Pipeline, die den vollständigen E2E-Pfad ohne echte
Modellausführung validiert.

Öffentliche Funktionen
----------------------
* ``execute_intent_v1`` – Orchestriert atomares Claim, Besetzung, simulierte
  Ausführung, Receipt-Erzeugung und Transport-Abschluss.
* ``route_intent_v1`` – Wählt einen Executor und Work-Item-Identität für einen Intent.
* ``propose_outcome`` – Baut aus Evidence ein deterministisches Outcome-Dict.
* ``generate_receipt`` – Erzeugt einen gültigen ``ExecutionReceipt``.
* ``dispatch_to_transport_contract`` – Ruft ``record_receipt`` im Ledger auf.

Datenklassen
------------
* ``SyntheticTicket`` – Test-Transportauftrag mit lokalem Ledger + DB.
* ``Run`` – Eine einzelne simulierte Ausführungsinstanz.
* ``NoopExecutor`` – Sammelt Evidence ohne externen Aufruf.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from hub._services.agents_heart import (
    Assignment,
    AssignmentDenied,
    begin_assignment,
    finish_assignment,
)
from hub._services.trithon.transport_contract import (
    ContractAlreadyClaimed,
    ExecutionReceipt,
    claim_contract,
    record_receipt,
)
from hub.task_audit import claim_task_atomic


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SyntheticTicket:
    """Transportauftrag für synthetische E2E-Tests."""

    work_item_id: str
    task_id: int
    ledger_path: Path
    db_path: Path
    slots_path: Path
    intent: Dict[str, Any] = field(default_factory=dict)
    host: str = "synthetic-host"
    runner: str = "noop-runner"

    def __post_init__(self) -> None:
        self.ledger_path = Path(self.ledger_path)
        self.db_path = Path(self.db_path)
        self.slots_path = Path(self.slots_path)


@dataclass
class Run:
    """Eine einzelne simulierte Ausführung."""

    run_id: str
    work_item_id: str
    started_at: str
    executor_type: str
    intent_summary: str
    ended_at: Optional[str] = None


class NoopExecutor:
    """Simulierter Executor, der nur Evidence sammelt.

    Echte Modellausführung ist absichtlich nicht implementiert; dadurch bleibt
    der Test deterministisch und frei von Backend-Anmeldedaten.
    """

    def __init__(self, executor_type: str = "noop") -> None:
        self.executor_type = executor_type

    def execute(self, run: Run, ticket: SyntheticTicket) -> Dict[str, Any]:
        """Führt einen simulierten Schritt aus und liefert Evidence."""
        evidence: Dict[str, Any] = {
            "run_id": run.run_id,
            "work_item_id": ticket.work_item_id,
            "task_id": ticket.task_id,
            "executor_type": self.executor_type,
            "host": ticket.host,
            "runner": ticket.runner,
            "started_at": run.started_at,
            "intent_keys": sorted(ticket.intent.keys()),
            "simulated": True,
            "timestamp": _utc_now(),
        }
        return evidence


def route_intent_v1(intent: Dict[str, Any]) -> tuple[str, NoopExecutor]:
    """Wählt anhand eines Intents den Executor und eine Work-Item-ID.

    In dieser Stufe wird jeder Intent auf den NoopExecutor geroutet.
    """
    executor = NoopExecutor(executor_type="noop")
    work_item_id = f"WIT-{uuid.uuid4().hex[:12].upper()}"
    return work_item_id, executor


def propose_outcome(run: Run, evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Erzeugt ein deterministisches Outcome aus Evidence.

    Regeln (fail-closed):
    * Evidence fehlt -> ``blocked``
    * ``simulated=True`` -> ``done``
    * alles andere -> ``blocked``
    """
    if not evidence:
        return {"status": "blocked", "reason": "no_evidence", "run_id": run.run_id}
    if evidence.get("simulated") is True:
        return {"status": "done", "reason": "simulated_ok", "run_id": run.run_id}
    return {"status": "blocked", "reason": "unexpected_evidence", "run_id": run.run_id}


def generate_receipt(
    run: Run,
    assignment: Assignment,
    outcome: Dict[str, Any],
    evidence: Dict[str, Any],
) -> ExecutionReceipt:
    """Erzeugt einen gültigen ExecutionReceipt und korreliert ihn mit Assignment/Run."""
    status = outcome.get("status")
    if status not in {"done", "blocked"}:
        raise ValueError(f"Receipt-Status muss 'done' oder 'blocked' sein, war {status!r}")

    return ExecutionReceipt(
        signature=f"sig-{uuid.uuid4().hex}",
        status=status,
        executed_by=assignment.agent_instance_id,
        actual_provider=assignment.backend_id,
        actual_model=assignment.model_id,
        occurred_at=_utc_now(),
        evidence=dict(evidence),
        assignment_id=assignment.assignment_id,
        run_id=run.run_id,
        work_item_id=run.work_item_id,
    )


def dispatch_to_transport_contract(
    ticket: SyntheticTicket,
    receipt: ExecutionReceipt,
) -> None:
    """Persistiert das Receipt im Transport-Ledger via ``record_receipt``."""
    record_receipt(
        path=ticket.ledger_path,
        work_item_id=ticket.work_item_id,
        receipt=receipt,
    )


def execute_intent_v1(
    ticket: SyntheticTicket,
    *,
    role_id: str = "hintergrund_worker",
    mode: str = "safe",
    agent_instance_id: str,
    backend_id: str,
    model_id: str,
    slot_id: str,
    session_id: str,
    initiated_by: str,
    lease_seconds: int = 1800,
) -> Dict[str, Any]:
    """End-to-End-Orchestrator: atomar claimen, ausführen, receipten, abschließen.

    Ablauf:
    1. Rechteprüfung via ``authorize_role`` (passiert implizit in
       ``begin_assignment``).
    2. Atomares Claimen des Tasks in der lokalen DB.
    3. Besetzung starten (agents-heart ``begin_assignment``).
    4. Intent routen und NoopExecutor ausführen.
    5. Outcome vorschlagen und Receipt erzeugen.
    6. Receipt im Transport-Ledger recorden.
    7. Besetzung beenden (agents-heart ``finish_assignment``).

    Rückgabe ist ein Dict mit ``success``, ``status``, ``assignment_id``,
    ``run_id``, ``ticket_id`` (legacy) und ggf. ``error``.
    """
    assignment: Optional[Assignment] = None
    run_id = f"run-{uuid.uuid4().hex}"
    run = Run(
        run_id=run_id,
        work_item_id=ticket.work_item_id,
        started_at=_utc_now(),
        executor_type="noop",
        intent_summary=str(ticket.intent)[:200],
    )

    conn = sqlite3.connect(str(ticket.db_path), timeout=10.0)
    try:
        # 1 + 3. Rechteprüfung + Besetzung starten (begin_assignment ruft
        # authorize_role intern auf).
        assignment = begin_assignment(
            role_id=role_id,
            mode=mode,
            agent_instance_id=agent_instance_id,
            backend_id=backend_id,
            model_id=model_id,
            slot_id=slot_id,
            task_id=ticket.task_id,
            session_id=session_id,
            initiated_by=initiated_by,
            path=str(ticket.slots_path),
        )

        # 2. Atomares Claim des Tasks.
        claimed = claim_task_atomic(
            conn,
            ticket.task_id,
            assignment.agent_instance_id,
            lease_seconds=lease_seconds,
        )
        if not claimed:
            finish_assignment(
                assignment,
                status="interrupted",
                reason="task_claim_failed_or_task_terminal",
                path=str(ticket.slots_path),
            )
            return {
                "success": False,
                "status": "claim_failed",
                "ticket_id": ticket.work_item_id,
                "task_id": ticket.task_id,
                "assignment_id": assignment.assignment_id,
                "run_id": run_id,
            }
        conn.commit()

        # 4. Transportvertrag claimen.
        claim_contract(
            ticket.ledger_path,
            work_item_id=ticket.work_item_id,
            host=ticket.host,
            runner=ticket.runner,
            assignment_id=assignment.assignment_id,
            run_id=run_id,
        )

        # 5. Executor ausführen.
        executor = NoopExecutor(executor_type="noop")
        evidence = executor.execute(run, ticket)
        outcome = propose_outcome(run, evidence)

        # 6. Receipt erzeugen.
        receipt = generate_receipt(run, assignment, outcome, evidence)

        # 6. Im Ledger recorden.
        dispatch_to_transport_contract(ticket, receipt)

        # 6b. Task in DB auf done setzen wenn erfolgreich
        if outcome.get("status") == "done":
            now_iso = _utc_now()
            conn.execute(
                "UPDATE tasks SET status = 'done', completed_at = ?, updated_at = ? WHERE id = ?",
                (now_iso, now_iso, ticket.task_id),
            )
            conn.execute(
                """INSERT INTO task_history
                   (task_id, action, field_changed, old_value, new_value, changed_by, changed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (ticket.task_id, "status_change", "status", "in_progress", "done", assignment.agent_instance_id, now_iso),
            )
            conn.commit()

        # 7. Besetzung beenden.
        assignment_status = "completed" if outcome["status"] == "done" else "error"
        finish_assignment(
            assignment,
            status=assignment_status,
            result=outcome["status"],
            reason=outcome.get("reason", ""),
            path=str(ticket.slots_path),
        )

        return {
            "success": True,
            "status": outcome["status"],
            "ticket_id": ticket.work_item_id,
            "task_id": ticket.task_id,
            "assignment_id": assignment.assignment_id,
            "run_id": run_id,
            "receipt_signature": receipt.signature,
        }

    except AssignmentDenied as exc:
        if assignment is not None:
            finish_assignment(
                assignment,
                status="error",
                reason=f"role_denied_after_begin: {exc}",
                path=str(ticket.slots_path),
            )
        return {
            "success": False,
            "status": "role_denied",
            "ticket_id": ticket.work_item_id,
            "task_id": ticket.task_id,
            "run_id": run_id,
            "error": str(exc),
        }

    except Exception as exc:  # noqa: BLE001
        if assignment is not None:
            finish_assignment(
                assignment,
                status="error",
                reason=f"dispatch_exception: {exc}",
                path=str(ticket.slots_path),
            )
        return {
            "success": False,
            "status": "error",
            "ticket_id": ticket.work_item_id,
            "task_id": ticket.task_id,
            "run_id": run_id,
            "error": str(exc),
        }

    finally:
        conn.close()
