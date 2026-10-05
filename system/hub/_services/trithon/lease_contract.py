# -*- coding: utf-8 -*-
"""SALT-Lease-Contract über dem Transport-Contract.

Erweitert das JSONL-Ledger um Fencing (monotoner Fence), TTL-Profile,
und Salt-Referenzen. Fail-closed bei abgelaufenen oder fremden Leases.

Task #1722: Roshambo/TaskDB Salt-Lease für BACH-Client und Trithon.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .transport_contract import (
    ContractAlreadyClaimed,
    ContractNotFound,
    LedgerEntry,
    TransportContractError,
    _append_line,
    _ensure_dir,
    _ledger_path,
    read_ledger,
    _utc_now,
)

#: TTL-Profil → Sekunden.
TTL_PROFILE_SECONDS: dict[str, int] = {
    "S": 300,
    "M": 1800,
    "L": 7200,
    "XL": 28800,
}

_FINAL_STATUSES = frozenset({"done", "blocked"})


@dataclass
class LeaseEntry:
    """SALT-Lease-Eintrag mit Fencing und TTL.

    Alle Felder sind explizit (keine Defaults außer heartbeat_at, salt_ref,
    status, line_number) damit das Dataclass klar dokumentiert, was ein
    vollständiger Lease enthält.
    """

    lease_id: str
    task_id: str
    host: str
    runner: str
    fence: int
    ttl_profile: str
    issued_at: str
    expires_at: str
    heartbeat_at: Optional[str] = None
    salt_ref: Optional[str] = None
    status: str = "claimed"
    line_number: int = 0


# ------------------------------------------------------------------ #
#  interne Helfer
# ------------------------------------------------------------------ #

def _to_epoch(s: str) -> float:
    """ISO-8601-Zeichenkette → epoch seconds."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _expires_for(ttl_profile: str, now: str) -> str:
    """Berechnet expires_at aus TTL-Profil und now."""
    seconds = TTL_PROFILE_SECONDS.get(ttl_profile, TTL_PROFILE_SECONDS["M"])
    dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(seconds=seconds)).isoformat()


def _count_lines(path: Path) -> int:
    """Zählt Zeilen in der Ledger-Datei (für line_number)."""
    if not path.exists():
        return 0
    return sum(1 for _ in path.open(encoding="utf-8"))


# ------------------------------------------------------------------ #
#  Öffentliche API
# ------------------------------------------------------------------ #

def claim_lease(
    path: str | Path,
    task_id: str,
    host: str,
    runner: str,
    *,
    lease_id: str,
    fence: int,
    ttl_profile: str = "M",
    salt_ref: Optional[str] = None,
    now: Optional[str] = None,
) -> LeaseEntry:
    """Beantragt einen SALT-Lease für *task_id*.

    Fail-closed Semantik:
    * Fremder Host/Runner bei aktuellem Claim  →  ``ContractAlreadyClaimed``
    * Abgelaufener fremder Claim                →  ``ContractAlreadyClaimed``
    * Gleicher Host/Runner, Fence ≤ letzter     →  ``ContractAlreadyClaimed``
    * Finalisierter Status (done/blocked)       →  ``ContractAlreadyClaimed``

    Erlaubt:
    * Kein Eintrag / pending                    →  neuer Claim
    * Eigen, abgelaufen, Fence > letzter        →  Fencing-Aufstieg
    * Eigen, nicht abgelaufen, Fence > letzter  →  Fencing-Aufstieg
    """
    ledger_path = _ledger_path(path, task_id)
    _ensure_dir(ledger_path)
    entries: List[LedgerEntry] = read_ledger(str(path), task_id)
    now = now or _utc_now()

    if entries:
        latest = entries[-1]
        status = latest.status

        # --- finalisiert? ---
        if status in _FINAL_STATUSES:
            raise ContractAlreadyClaimed(
                f"Task {task_id} ist finalisiert ({status})"
            )

        if status == "claimed":
            # --- abgelaufen? ---
            expired = bool(latest.expires_at) and _to_epoch(latest.expires_at) < _to_epoch(now)

            if expired:
                if latest.host == host and latest.runner == runner:
                    # eigen + abgelaufen → Fencing-Aufstieg nötig
                    last_fence = latest.fence if latest.fence is not None else 0
                    if fence <= last_fence:
                        raise ContractAlreadyClaimed(
                            f"Fence {fence} ≤ letzter Fence {last_fence}; "
                            "monotone Erhöhung nötig"
                        )
                    # OK → durchfallen
                else:
                    # fremd + abgelaufen → fail-closed
                    raise ContractAlreadyClaimed(
                        f"Task {task_id} abgelaufen von "
                        f"{latest.host}/{latest.runner}; fail-closed"
                    )
            else:
                # nicht abgelaufen
                if latest.host != host or latest.runner != runner:
                    raise ContractAlreadyClaimed(
                        f"Task {task_id} aktiv von "
                        f"{latest.host}/{latest.runner}; "
                        f"{host}/{runner} blockiert"
                    )
                last_fence = latest.fence if latest.fence is not None else 0
                if fence <= last_fence:
                    raise ContractAlreadyClaimed(
                        f"Fence {fence} ≤ letzter Fence {last_fence}; "
                        "monotone Erhöhung nötig"
                    )
                # eigen + höherer Fence → OK

        # status == "pending" oder "released" → freier Claim

    expires_at = _expires_for(ttl_profile, now)
    entry = LedgerEntry(
        work_item_id=task_id,
        status="claimed",
        host=host,
        runner=runner,
        occurred_at=now,
        lease_id=lease_id,
        fence=fence,
        ttl_profile=ttl_profile,
        salt_ref=salt_ref,
        issued_at=now,
        expires_at=expires_at,
        heartbeat_at=None,
    )
    _append_line(ledger_path, entry)
    line_number = _count_lines(ledger_path)
    return LeaseEntry(
        lease_id=lease_id,
        task_id=task_id,
        host=host,
        runner=runner,
        fence=fence,
        ttl_profile=ttl_profile,
        issued_at=now,
        expires_at=expires_at,
        heartbeat_at=None,
        salt_ref=salt_ref,
        status="claimed",
        line_number=line_number,
    )


def renew_lease(
    path: str | Path,
    task_id: str,
    lease_id: str,
    *,
    now: Optional[str] = None,
) -> LeaseEntry:
    """Erneuert einen bestehenden Lease (Heartbeat).

    Die TTL wird **nie** verkürzt: ``expires_at`` bleibt unverändert.
    Ein abgelaufener Lease kann nicht erneuert werden → ``ContractAlreadyClaimed``.
    """
    ledger_path = _ledger_path(path, task_id)
    entries: List[LedgerEntry] = read_ledger(str(path), task_id)
    now = now or _utc_now()

    matching = [e for e in entries if e.status == "claimed" and e.lease_id == lease_id]
    if not matching:
        raise ContractNotFound(f"Lease {lease_id} für {task_id} nicht gefunden")

    latest = matching[-1]

    # abgelaufen → fail-closed
    if latest.expires_at and _to_epoch(latest.expires_at) < _to_epoch(now):
        raise ContractAlreadyClaimed(
            f"Lease {lease_id} abgelaufen ({latest.expires_at} < {now})"
        )

    # Heartbeat – expires_at UNVERÄNDERT
    entry = LedgerEntry(
        work_item_id=task_id,
        status="claimed",
        host=latest.host,
        runner=latest.runner,
        occurred_at=now,
        lease_id=lease_id,
        fence=latest.fence,
        ttl_profile=latest.ttl_profile,
        salt_ref=latest.salt_ref,
        issued_at=latest.issued_at,
        expires_at=latest.expires_at,
        heartbeat_at=now,
    )
    _append_line(ledger_path, entry)
    line_number = _count_lines(ledger_path)
    return LeaseEntry(
        lease_id=lease_id,
        task_id=task_id,
        host=latest.host,
        runner=latest.runner,
        fence=latest.fence or 0,
        ttl_profile=latest.ttl_profile or "M",
        issued_at=latest.issued_at or now,
        expires_at=latest.expires_at or now,
        heartbeat_at=now,
        salt_ref=latest.salt_ref,
        status="claimed",
        line_number=line_number,
    )


def release_lease(
    path: str | Path,
    task_id: str,
    lease_id: str,
    *,
    now: Optional[str] = None,
) -> LeaseEntry:
    """Gibt einen Lease frei (status → ``released`` im Ledger)."""
    ledger_path = _ledger_path(path, task_id)
    entries: List[LedgerEntry] = read_ledger(str(path), task_id)
    now = now or _utc_now()

    matching = [e for e in entries if e.status == "claimed" and e.lease_id == lease_id]
    if not matching:
        raise ContractNotFound(f"Lease {lease_id} für {task_id} nicht gefunden")

    latest = matching[-1]

    entry = LedgerEntry(
        work_item_id=task_id,
        status="released",
        host=latest.host,
        runner=latest.runner,
        occurred_at=now,
        lease_id=lease_id,
        fence=latest.fence,
        ttl_profile=latest.ttl_profile,
        salt_ref=latest.salt_ref,
        issued_at=latest.issued_at,
        expires_at=latest.expires_at,
        heartbeat_at=now,
    )
    _append_line(ledger_path, entry)
    line_number = _count_lines(ledger_path)
    return LeaseEntry(
        lease_id=lease_id,
        task_id=task_id,
        host=latest.host,
        runner=latest.runner,
        fence=latest.fence or 0,
        ttl_profile=latest.ttl_profile or "M",
        issued_at=latest.issued_at or now,
        expires_at=latest.expires_at or now,
        heartbeat_at=now,
        salt_ref=latest.salt_ref,
        status="released",
        line_number=line_number,
    )
