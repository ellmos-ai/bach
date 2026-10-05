# -*- coding: utf-8 -*-
"""Dateibasierte Transportzustandsmaschine für Work Items.

Dieses Modul stellt ein neutrales, wiederverwendbares Transportvertrags-
Interface bereit. Es speichert den Transport-Ledger als JSON-Lines-Datei
und stellt die beiden zentralen Operationen bereit:

* ``claim_contract``   – Work item auf einem Host/Runner exklusiv beanspruchen.
* ``record_receipt``   – Ausführung abschließen und Receipt persistieren.

Ledger-Zustände
---------------
``pending``  – Work item wurde dem Ledger hinzugefügt, aber noch nicht claimed.
``claimed``  – Work item wurde von einem Host/Runner übernommen.
``done``     – Work item wurde erfolgreich ausgeführt und abgeschlossen.
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


class TransportContractError(RuntimeError):
    """Basisfehler für Transportvertragsoperationen."""


class ContractError(TransportContractError):
    """Kurzform für TransportContractError; aus Kompatibilitätsgründen."""


class ContractAlreadyClaimed(TransportContractError):
    """Das Work item wurde bereits von einem anderen Host/Runner beansprucht."""


class ContractNotFound(TransportContractError):
    """Work item nicht im Ledger vorhanden."""


class InvalidReceipt(TransportContractError):
    """Receipt hat ungültige oder fehlende Felder."""


@dataclass
class LedgerEntry:
    """Eine Zeile im Transport-Ledger."""

    work_item_id: str
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
    lease_id: Optional[str] = None
    fence: Optional[int] = None
    ttl_profile: Optional[str] = None
    salt_ref: Optional[str] = None
    issued_at: Optional[str] = None
    expires_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    line_number: int = 0


@dataclass
class ExecutionReceipt:
    """Versionierter Abschlussnachweis einer Task-Ausführung.

    Korreliert Transport (``work_item_id``) und Besetzung (``assignment_id``,
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
    work_item_id: Optional[str] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger_path(path: str | Path, work_item_id: str) -> Path:
    base = Path(path)
    if base.is_dir():
        return base / f"{work_item_id}.ledger"
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


def read_ledger(path: str | Path, work_item_id: str) -> List[LedgerEntry]:
    """Liest alle Ledger-Einträge eines Work items."""
    ledger_file = _ledger_path(path, work_item_id)
    entries: List[LedgerEntry] = []
    for idx, line in enumerate(_load_lines(ledger_file), start=1):
        try:
            entry = _parse_entry(line, idx)
            if entry is not None and entry.work_item_id == work_item_id:
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
    work_item_id: str,
    host: str,
    runner: str,
    *,
    assignment_id: Optional[str] = None,
    run_id: Optional[str] = None,
    now: Optional[str] = None,
) -> LedgerEntry:
    """Beansprucht ein Work item exklusiv im Ledger.

    Ist das Work item bereits ``claimed`` und nicht finalisiert, wird
    ``ContractAlreadyClaimed`` geworfen. Fehlt das Work item, wird
    ``ContractNotFound`` geworfen.

    Args:
        path: Basisverzeichnis oder konkrete Ledger-Datei.
        work_item_id: ID des zu beanspruchenden Work items.
        host: Host, der das Work item übernimmt.
        runner: Runner-Identität, die das Work item ausführt.
        assignment_id: Korrelations-ID zur Besetzung.
        run_id: Korrelations-ID zum konkreten Lauf.
        now: Zeitstempel (ISO-8601); default jetzt.

    Returns:
        Der neu geschriebene ``LedgerEntry`` mit Status ``claimed``.
    """
    ledger_file = _ledger_path(path, work_item_id)
    entries = read_ledger(path, work_item_id)

    if not entries:
        raise ContractNotFound(
            f"Kein Ledger-Eintrag für Work item {work_item_id!r}"
        )

    latest = entries[-1]
    if latest.status in _FINAL_STATUSES:
        raise ContractAlreadyClaimed(
            f"Work item {work_item_id!r} bereits finalisiert ({latest.status})"
        )

    if latest.status == "claimed":
        if latest.host != host or latest.runner != runner:
            raise ContractAlreadyClaimed(
                f"Work item {work_item_id!r} bereits von "
                f"{latest.host}/{latest.runner} claimed"
            )
        # Idempotenter Re-Claim mit gleicher Identität.
        return latest

    if latest.status != "pending":
        raise TransportContractError(
            f"Work item {work_item_id!r} hat unerwarteten Status {latest.status!r}"
        )

    now = now or _utc_now()
    entry = LedgerEntry(
        work_item_id=work_item_id,
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
    work_item_id: str,
    receipt: ExecutionReceipt,
) -> LedgerEntry:
    """Schließt ein Work item mit einem ExecutionReceipt ab.

    Das Work item muss vorher ``claimed`` sein; der Receipt-Status muss ``done``
    oder ``blocked`` sein.

    Args:
        path: Basisverzeichnis oder konkrete Ledger-Datei.
        work_item_id: ID des Work items.
        receipt: Vollständiger Abschlussnachweis.

    Returns:
        Der neu geschriebene ``LedgerEntry`` im Endzustand.
    """
    ledger_file = _ledger_path(path, work_item_id)
    entries = read_ledger(path, work_item_id)

    if not entries:
        raise ContractNotFound(
            f"Kein Ledger-Eintrag für Work item {work_item_id!r}"
        )

    latest = entries[-1]
    if latest.status in _FINAL_STATUSES:
        raise ContractAlreadyClaimed(
            f"Work item {work_item_id!r} bereits finalisiert ({latest.status})"
        )
    if latest.status != "claimed":
        raise TransportContractError(
            f"Work item {work_item_id!r} muss 'claimed' sein, ist aber {latest.status!r}"
        )

    _validate_receipt(receipt)
    receipt.work_item_id = work_item_id
    receipt.assignment_id = receipt.assignment_id or latest.assignment_id
    receipt.run_id = receipt.run_id or latest.run_id

    entry = LedgerEntry(
        work_item_id=work_item_id,
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
    work_item_id: str,
    host: str = "*",
    runner: str = "*",
    *,
    now: Optional[str] = None,
) -> LedgerEntry:
    """Erzeugt einen neuen ``pending`` Ledger-Eintrag.

    Diese Hilfsfunktion dient E2E-Tests und lokalem Bootstrapping, wenn Work
    items nicht aus einer externen Quelle stammen.
    """
    ledger_file = _ledger_path(path, work_item_id)
    now = now or _utc_now()
    entry = LedgerEntry(
        work_item_id=work_item_id,
        status="pending",
        host=host,
        runner=runner,
        occurred_at=now,
    )
    _append_line(ledger_file, asdict(entry))
    return entry
