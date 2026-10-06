# -*- coding: utf-8 -*-
"""Dateibasierte Transportzustandsmaschine für Routing-Tickets.

Dieses Modul ist ein synthetisches Nachbild des externen ``routing_contract``-
Interfaces aus dem ``ticket-master``-Repo. Es speichert den Ticket-Transport-
Ledger als JSON-Lines-Datei und stellt die beiden zentralen Operationen bereit:

* ``claim_contract``  – Ticket auf einem Host/Runner exklusiv beanspruchen.
* ``record_receipt``   – Ausführung abschließen und Receipt persistieren.

Ledger-Zustände
---------------
``pending``  – Ticket wurde dem Ledger hinzugefügt, aber noch nicht claimed.
``claimed``  – Ticket wurde von einem Host/Runner übernommen.
``done``     – Ticket wurde erfolgreich ausgeführt und abgeschlossen.
``blocked``  – Ticket wurde abgelehnt oder blockiert abgeschlossen.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Kanonische Felder eines ``ExecutionReceipt``.
_RECEIPT_FIELDS = (
    "signature",
    "status",
    "executed_by",
    "actual_provider",
    "actual_model",
    "occurred_at",
    "evidence",
)

#: Zulässige Ledger-Endzustände.
_FINAL_STATUSES = {"done", "blocked"}

#: Zulässige Ledger-Transportzustände.
_VALID_STATUSES = {"pending", "claimed"} | _FINAL_STATUSES


class RoutingError(RuntimeError):
    """Basisfehler für Routing-Vertragsoperationen."""


class ContractAlreadyClaimed(RoutingError):
    """Das Ticket wurde bereits von einem anderen Host/Runner beansprucht."""


class ContractNotFound(RoutingError):
    """Ticket nicht im Ledger vorhanden."""


class InvalidReceipt(RoutingError):
    """Receipt hat ungültige oder fehlende Felder."""


@dataclass
class LedgerEntry:
    """Eine Zeile im Transport-Ledger."""

    ticket_id: str
    status: str
    host: str
    runner: str
    assignment_id: Optional[str] = None
    run_id: Optional[str] = None
    occurred_at: Optional[str] = None
    signature: Optional[str] = None
    executed_by: Optional[str] = None
    actual_provider: Optional[str] = None
    actual_model: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    line_number: int = 0


@dataclass
class ExecutionReceipt:
    """Versionierter Abschlussnachweis einer Task-Ausführung.

    Korreliert Transport (``ticket_id``) und Besetzung (``assignment_id``,
    ``run_id``).
    """

    signature: str
    status: str  # "done" | "blocked"
    executed_by: str
    actual_provider: str
    actual_model: str
    occurred_at: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    assignment_id: Optional[str] = None
    run_id: Optional[str] = None
    ticket_id: Optional[str] = None

# Neutral-API-Aliase (open-ocean / ticket-master Kompatibilität)
TaskTransportContract = LedgerEntry
WorkItem = LedgerEntry
ExecutorReceipt = ExecutionReceipt


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger_path(path: str | Path, ticket_id: str) -> Path:
    base = Path(path)
    if base.is_dir():
        return base / f"{ticket_id}.ledger"
    return base


def _ensure_dir(path: Path) -> None:
    directory = path.parent
    if directory and not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)


def _load_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _parse_entry(line: str, line_number: int) -> Optional[LedgerEntry]:
    line = line.strip()
    if not line:
        return None
    data = json.loads(line)
    data.pop("line_number", None)
    return LedgerEntry(line_number=line_number, **data)


def read_ledger(path: str | Path, ticket_id: str) -> List[LedgerEntry]:
    """Liest alle Ledger-Einträge eines Tickets."""
    ledger_file = _ledger_path(path, ticket_id)
    entries: List[LedgerEntry] = []
    for idx, line in enumerate(_load_lines(ledger_file), start=1):
        try:
            entry = _parse_entry(line, idx)
            if entry is not None and entry.ticket_id == ticket_id:
                entries.append(entry)
        except json.JSONDecodeError:
            continue
    return entries


def _last_non_final(entries: List[LedgerEntry]) -> Optional[LedgerEntry]:
    for entry in reversed(entries):
        if entry.status not in _FINAL_STATUSES:
            return entry
    return None


def _append_line(path: Path, data: Dict[str, Any]) -> None:
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, sort_keys=True, ensure_ascii=False) + "\n")


def claim_contract(
    path: str | Path,
    ticket_id: str,
    host: str,
    runner: str,
    *,
    assignment_id: Optional[str] = None,
    run_id: Optional[str] = None,
    now: Optional[str] = None,
) -> LedgerEntry:
    """Beansprucht ein Ticket exklusiv im Ledger.

    Ist das Ticket bereits ``claimed`` und nicht finalisiert, wird
    ``ContractAlreadyClaimed`` geworfen. Fehlt das Ticket, wird
    ``ContractNotFound`` geworfen.

    Args:
        path: Basisverzeichnis oder konkrete Ledger-Datei.
        ticket_id: ID des zu beanspruchenden Tickets.
        host: Host, der das Ticket übernimmt.
        runner: Runner-Identität, die das Ticket ausführt.
        assignment_id: Korrelations-ID zur Besetzung (agents-heart).
        run_id: Korrelations-ID zum konkreten Lauf.
        now: Zeitstempel (ISO-8601); default jetzt.

    Returns:
        Der neu geschriebene ``LedgerEntry`` mit Status ``claimed``.
    """
    ledger_file = _ledger_path(path, ticket_id)
    entries = read_ledger(path, ticket_id)

    if not entries:
        raise ContractNotFound(f"Kein Ledger-Eintrag für Ticket {ticket_id!r}")

    latest = entries[-1]
    if latest.status in _FINAL_STATUSES:
        raise ContractAlreadyClaimed(
            f"Ticket {ticket_id!r} ist bereits finalisiert ({latest.status})"
        )
    if latest.status == "claimed":
        if latest.host != host or latest.runner != runner:
            raise ContractAlreadyClaimed(
                f"Ticket {ticket_id!r} bereits von {latest.host}/{latest.runner} claimed"
            )
        # Idempotenter Re-Claim mit gleicher Identität.
        return latest

    if latest.status != "pending":
        raise RoutingError(
            f"Ticket {ticket_id!r} hat unerwarteten Status {latest.status!r}"
        )

    now = now or _utc_now()
    entry = LedgerEntry(
        ticket_id=ticket_id,
        status="claimed",
        host=host,
        runner=runner,
        assignment_id=assignment_id,
        run_id=run_id,
        occurred_at=now,
    )
    _append_line(ledger_file, asdict(entry))
    return entry


def _validate_receipt(receipt: ExecutionReceipt) -> None:
    missing = [f for f in _RECEIPT_FIELDS if not getattr(receipt, f, None)]
    if receipt.status not in _FINAL_STATUSES:
        raise InvalidReceipt(
            f"Receipt.status muss 'done' oder 'blocked' sein, nicht {receipt.status!r}"
        )
    if missing:
        raise InvalidReceipt(f"Receipt fehlt Pflichtfelder: {missing}")


def record_receipt(
    path: str | Path,
    ticket_id: str,
    receipt: ExecutionReceipt,
) -> LedgerEntry:
    """Schließt ein Ticket mit einem ExecutionReceipt ab.

    Das Ticket muss vorher ``claimed`` sein; der Receipt-Status muss ``done``
    oder ``blocked`` sein.

    Args:
        path: Basisverzeichnis oder konkrete Ledger-Datei.
        ticket_id: ID des Tickets.
        receipt: Vollständiger Abschlussnachweis.

    Returns:
        Der neu geschriebene ``LedgerEntry`` im Endzustand.
    """
    ledger_file = _ledger_path(path, ticket_id)
    entries = read_ledger(path, ticket_id)

    if not entries:
        raise ContractNotFound(f"Kein Ledger-Eintrag für Ticket {ticket_id!r}")

    latest = entries[-1]
    if latest.status in _FINAL_STATUSES:
        raise ContractAlreadyClaimed(
            f"Ticket {ticket_id!r} bereits finalisiert ({latest.status})"
        )
    if latest.status != "claimed":
        raise RoutingError(
            f"Ticket {ticket_id!r} muss 'claimed' sein, ist aber {latest.status!r}"
        )

    _validate_receipt(receipt)
    receipt.ticket_id = ticket_id
    receipt.assignment_id = receipt.assignment_id or latest.assignment_id
    receipt.run_id = receipt.run_id or latest.run_id

    entry = LedgerEntry(
        ticket_id=ticket_id,
        status=receipt.status,
        host=latest.host,
        runner=latest.runner,
        assignment_id=receipt.assignment_id,
        run_id=receipt.run_id,
        occurred_at=receipt.occurred_at,
        signature=receipt.signature,
        executed_by=receipt.executed_by,
        actual_provider=receipt.actual_provider,
        actual_model=receipt.actual_model,
        evidence=receipt.evidence,
    )
    _append_line(ledger_file, asdict(entry))
    return entry


def create_pending_contract(
    path: str | Path,
    ticket_id: str,
    host: str = "*",
    runner: str = "*",
    *,
    now: Optional[str] = None,
) -> LedgerEntry:
    """Erzeugt einen neuen ``pending`` Ledger-Eintrag (synthetisch).

    Im echten ``ticket-master`` kommt das Ticket aus einer externen Quelle;
    hier wird es für E2E-Tests und lokale Bootstrapping bereitgestellt.
    """
    ledger_file = _ledger_path(path, ticket_id)
    now = now or _utc_now()
    entry = LedgerEntry(
        ticket_id=ticket_id,
        status="pending",
        host=host,
        runner=runner,
        occurred_at=now,
    )
    _append_line(ledger_file, asdict(entry))
    return entry
