# -*- coding: utf-8 -*-
"""Trithon Dispatch-Layer — Folgestufe 3.

Dieses Modul verbindet die interne Task-Infrastruktur (agents-heart für
Besetzungsnachweise, task_audit für atomares Claiming) mit dem synthetischen
ticket-master-Vertrag (routing_contract). Es implementiert einen No-op-Executor,
also eine reine Durchlauf-Pipeline, die den vollständigen E2E-Pfad ohne echte
Modellausführung validiert.

Öffentliche Funktionen
----------------------
* ``execute_intent_v1`` – Orchestriert atomares Claim, Besetzung, simulierte
  Ausführung, Receipt-Erzeugung und Ticket-Master-Abschluss.
* ``route_intent_v1`` – Wählt einen Executor und Ticket-Identität für einen Intent.
* ``propose_outcome`` – Baut aus Evidence ein deterministisches Outcome-Dict.
* ``generate_receipt`` – Erzeugt einen gültigen ``ExecutionReceipt``.
* ``dispatch_to_ticket_master`` – Ruft ``record_receipt`` im Ledger auf.

Datenklassen
------------
* ``SyntheticTicket`` – Test-Transportauftrag mit lokalem Ledger + DB.
* ``Run`` – Eine einzelne simulierte Ausführungsinstanz.
* ``NoopExecutor`` – Sammelt Evidence ohne externen Aufruf.
"""
from __future__ import annotations

import sqlite3
import threading
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
from hub._services.trithon.routing_contract import (
    ContractAlreadyClaimed,
    ExecutionReceipt,
    claim_contract,
    record_receipt,
)
from hub._services.task_lease_client import TaskLeaseClient, LeaseDeniedError


_LEASE_RENEWAL_MAX_WAIT_SECONDS = 60.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SyntheticTicket:
    """Transportauftrag für synthetische E2E-Tests."""

    ticket_id: str
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
    ticket_id: str
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

    def execute(
        self,
        run: Run,
        ticket: SyntheticTicket,
        *,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Führt einen simulierten Schritt aus und liefert Evidence."""
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("execution cancelled after lease loss")
        evidence: Dict[str, Any] = {
            "run_id": run.run_id,
            "ticket_id": ticket.ticket_id,
            "task_id": ticket.task_id,
            "executor_type": self.executor_type,
            "host": ticket.host,
            "runner": ticket.runner,
            "started_at": run.started_at,
            "intent_keys": sorted(ticket.intent.keys()),
            "simulated": True,
            "timestamp": _utc_now(),
        }
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("execution cancelled after lease loss")
        return evidence


def _execute_with_lease(client, lease_ack, executor, run, ticket):
    """Renew the lease while executing and cancel work if it can no longer be held."""
    lease_ack.assert_locally_valid()
    cancelled = threading.Event()
    completed = threading.Event()
    result: Dict[str, Any] = {}

    def execute() -> None:
        try:
            result["evidence"] = executor.execute(
                run, ticket, cancel_event=cancelled
            )
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            completed.set()

    worker = threading.Thread(target=execute, daemon=True)
    worker.start()

    while not completed.is_set():
        try:
            lease_ack.assert_locally_valid()
            remaining = (
                lease_ack.local_deadline - datetime.now(timezone.utc)
            ).total_seconds()
            wait_seconds = min(
                _LEASE_RENEWAL_MAX_WAIT_SECONDS,
                lease_ack.ttl_seconds / 3,
                remaining / 2,
            )
            if completed.wait(max(0.05, wait_seconds)):
                break
            lease_ack.assert_locally_valid()
            lease_ack = client.renew(
                ticket.task_id,
                lease_id=lease_ack.lease_id,
                fence=lease_ack.fence,
                task_version=lease_ack.task_version,
            )
        except Exception:
            cancelled.set()
            completed.wait()
            raise

    lease_ack.assert_locally_valid()
    if "error" in result:
        raise result["error"]
    return result["evidence"], lease_ack


def route_intent_v1(intent: Dict[str, Any]) -> tuple[str, NoopExecutor]:
    """Wählt anhand eines Intents den Executor und eine Ticket-ID.

    In dieser Stufe wird jeder Intent auf den NoopExecutor geroutet.
    """
    executor = NoopExecutor(executor_type="noop")
    ticket_id = f"TKT-{uuid.uuid4().hex[:12].upper()}"
    return ticket_id, executor


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
        ticket_id=run.ticket_id,
    )


def dispatch_to_ticket_master(
    ticket: SyntheticTicket,
    receipt: ExecutionReceipt,
) -> None:
    """Persistiert das Receipt im Ticket-Ledger via ``record_receipt``."""
    record_receipt(
        path=ticket.ledger_path,
        ticket_id=ticket.ticket_id,
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
    6. Receipt im Ticket-Ledger recorden.
    7. Besetzung beenden (agents-heart ``finish_assignment``).

    Rückgabe ist ein Dict mit ``success``, ``status``, ``assignment_id``,
    ``run_id``, ``ticket_id`` und ggf. ``error``.
    """
    assignment: Optional[Assignment] = None
    run_id = f"run-{uuid.uuid4().hex}"
    run = Run(
        run_id=run_id,
        ticket_id=ticket.ticket_id,
        started_at=_utc_now(),
        executor_type="noop",
        intent_summary=str(ticket.intent)[:200],
    )

    client = None
    try:
        client = TaskLeaseClient.for_task_db(
            lambda: sqlite3.connect(str(ticket.db_path), timeout=10.0)
        )
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

        # 2. Gefenctes Claim des Tasks gemäss Salt-Lease-Vertrag (BACH #1722).
        worker_id = (
            assignment.agent_instance_id
            if "@" in assignment.agent_instance_id
            else f"{assignment.agent_instance_id}@{ticket.host}"
        )
        host = worker_id.rsplit("@", 1)[1]
        try:
            lease_ack = client.acquire(ticket.task_id, worker_id=worker_id, host=host,
                                       request_id=run_id, intent=str(ticket.intent)[:500])
        except LeaseDeniedError as exc:
            finish_assignment(assignment, status="interrupted",
                              reason=f"task_claim_failed_{exc.reason}", path=str(ticket.slots_path))
            return dict(success=False, status="claim_failed", reason=exc.reason,
                        ticket_id=ticket.ticket_id, task_id=ticket.task_id,
                        assignment_id=assignment.assignment_id, run_id=run_id)
        lease_id = lease_ack.lease_id
        fence = lease_ack.fence

        # 2b. Atomares Claim des Tickets im Ledger.
        try:
            claim_contract(
                ticket.ledger_path,
                ticket.ticket_id,
                ticket.host,
                ticket.runner,
                assignment_id=assignment.assignment_id,
                run_id=run_id,
            )
        except ContractAlreadyClaimed:
            pass
        except Exception as exc:
            finish_assignment(
                assignment,
                status="interrupted",
                reason=f"ledger_claim_failed: {exc}",
                path=str(ticket.slots_path),
            )
            return {
                "success": False,
                "status": "claim_failed",
                "ticket_id": ticket.ticket_id,
                "task_id": ticket.task_id,
                "assignment_id": assignment.assignment_id,
                "run_id": run_id,
                "error": str(exc),
            }

        # 4. Ausführen.
        _, executor = route_intent_v1(ticket.intent)
        evidence, lease_ack = _execute_with_lease(
            client, lease_ack, executor, run, ticket
        )
        run.ended_at = _utc_now()

        # 5. Outcome + Receipt (inklusive Fencing-Nachweis).
        outcome = propose_outcome(run, evidence)
        evidence_with_fence = dict(evidence)
        evidence_with_fence["lease_id"] = lease_id
        evidence_with_fence["claim_fence"] = fence
        evidence_with_fence["task_version"] = lease_ack.task_version
        evidence_with_fence["worker_id"] = worker_id
        evidence_with_fence["host"] = host
        receipt = generate_receipt(run, assignment, outcome, evidence_with_fence)

        # 6b. Task in DB via Lease-Release abschließen (Vertrag §5.4 / fail-closed)
        outcome_val = "done" if outcome.get("status") == "done" else "return"
        try:
            client.release(ticket.task_id, lease_id=lease_id, fence=fence,
                           task_version=lease_ack.task_version, outcome=outcome_val,
                           result_ref=f"run:{run_id}", note=f"Trithon dispatch receipt {receipt.signature}")
        except LeaseDeniedError as exc:
            finish_assignment(assignment, status="interrupted",
                              reason=f"lease_release_failed_{exc.reason}", path=str(ticket.slots_path))
            return dict(success=False, status="release_failed", reason=exc.reason,
                        ticket_id=ticket.ticket_id, task_id=ticket.task_id,
                        assignment_id=assignment.assignment_id, run_id=run_id)

        # Ledger is evidence only; terminal receipt follows authoritative release.
        dispatch_to_ticket_master(ticket, receipt)

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
            "ticket_id": ticket.ticket_id,
            "task_id": ticket.task_id,
            "assignment_id": assignment.assignment_id,
            "run_id": run_id,
            "receipt_signature": receipt.signature,
            "lease_id": lease_id,
            "fence": fence,
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
            "ticket_id": ticket.ticket_id,
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
            "ticket_id": ticket.ticket_id,
            "task_id": ticket.task_id,
            "run_id": run_id,
            "error": str(exc),
        }

    finally:
        if client is not None:
            client.__exit__(None, None, None)
