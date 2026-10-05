# -*- coding: utf-8 -*-
"""Rückwärtskompatibler Alias-Wrapper für ``transport_contract``.

Dieses Modul existiert nur noch, um bestehenden Code, der das alte
``routing_contract``-Interface aus dem ``ticket-master``-Kontext erwartet,
weiterhin funktionsfähig zu halten. Alle Implementierungsdetails leben in
``transport_contract``; hier werden lediglich die historischen Namen
bereitgestellt und ``ticket_id``-Parameter transparent auf ``work_item_id``
abgebildet.

Neuer Code sollte direkt ``hub._services.trithon.transport_contract``
importieren.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from hub._services.trithon import transport_contract

#: Historische Basisfehlerklasse – Alias für den neutrale Basisfehler.
RoutingError = transport_contract.TransportContractError

#: Spezifische Exceptions werden unverändert durchgereicht.
ContractAlreadyClaimed = transport_contract.ContractAlreadyClaimed
ContractNotFound = transport_contract.ContractNotFound
InvalidReceipt = transport_contract.InvalidReceipt


class LedgerEntry(transport_contract.LedgerEntry):
    """Ledger-Zeile mit historischem ``ticket_id``-Attribut."""

    def __init__(
        self,
        *,
        ticket_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        if ticket_id is not None and work_item_id is None:
            work_item_id = ticket_id
        if work_item_id is None:
            raise TypeError("LedgerEntry erwartet ticket_id oder work_item_id")
        super().__init__(work_item_id=work_item_id, **kwargs)

    @property
    def ticket_id(self) -> str:
        return self.work_item_id


class ExecutionReceipt(transport_contract.ExecutionReceipt):
    """ExecutionReceipt mit historischem ``ticket_id``-Attribut."""

    def __init__(
        self,
        *,
        ticket_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        if ticket_id is not None and work_item_id is None:
            work_item_id = ticket_id
        super().__init__(work_item_id=work_item_id, **kwargs)

    @property
    def ticket_id(self) -> Optional[str]:
        return self.work_item_id


def _wrap_entry(entry: transport_contract.LedgerEntry) -> LedgerEntry:
    data = asdict(entry)
    data["ticket_id"] = data.pop("work_item_id", entry.work_item_id)
    return LedgerEntry(**data)


def read_ledger(
    path: str | Path,
    ticket_id: str,
) -> List[LedgerEntry]:
    """Liest alle Ledger-Einträge eines Tickets (Alias für ein Work item)."""
    raw_entries = transport_contract.read_ledger(path, work_item_id=ticket_id)
    return [_wrap_entry(e) for e in raw_entries]


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
    """Beansprucht ein Ticket exklusiv im Ledger (Alias für ein Work item)."""
    entry = transport_contract.claim_contract(
        path,
        work_item_id=ticket_id,
        host=host,
        runner=runner,
        assignment_id=assignment_id,
        run_id=run_id,
        now=now,
    )
    return _wrap_entry(entry)


def record_receipt(
    path: str | Path,
    ticket_id: str,
    receipt: transport_contract.ExecutionReceipt,
) -> LedgerEntry:
    """Schließt ein Ticket mit einem ExecutionReceipt ab (Alias für ein Work item)."""
    entry = transport_contract.record_receipt(
        path,
        work_item_id=ticket_id,
        receipt=receipt,
    )
    return _wrap_entry(entry)


def create_pending_contract(
    path: str | Path,
    ticket_id: str,
    host: str = "*",
    runner: str = "*",
    *,
    now: Optional[str] = None,
) -> LedgerEntry:
    """Erzeugt einen neuen ``pending`` Ledger-Eintrag für ein Ticket."""
    entry = transport_contract.create_pending_contract(
        path,
        work_item_id=ticket_id,
        host=host,
        runner=runner,
        now=now,
    )
    return _wrap_entry(entry)
