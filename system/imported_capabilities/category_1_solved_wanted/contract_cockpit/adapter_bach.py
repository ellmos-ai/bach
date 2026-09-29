# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Contract & Insurance Cockpit (from FolderHome).

Provides unified tracking for contracts, insurance policies, terms, cancellation deadlines,
and recurring costs, linking them to Bach contacts and calendar reminders.
"""

from __future__ import annotations

import json
import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ContractRecord:
    id: Optional[int]
    name: str
    category: str  # insurance, subscription, utility, lease, telecommunication
    provider: str
    contract_number: str
    cost_monthly_cents: int
    renewal_period_months: int
    cancellation_deadline: Optional[str]
    document_path: Optional[str]
    is_active: bool
    notes: str


def ensure_contract_cockpit_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_cockpit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            provider TEXT NOT NULL,
            contract_number TEXT,
            cost_monthly_cents INTEGER DEFAULT 0,
            renewal_period_months INTEGER DEFAULT 12,
            cancellation_deadline TEXT,
            document_path TEXT,
            is_active INTEGER DEFAULT 1,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


class ContractCockpitService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextlib.contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            ensure_contract_cockpit_schema(conn)
            with conn:
                yield conn
        finally:
            conn.close()

    def add_contract(self, contract: ContractRecord) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO contract_cockpit
                    (name, category, provider, contract_number, cost_monthly_cents,
                     renewal_period_months, cancellation_deadline, document_path, is_active, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract.name,
                    contract.category,
                    contract.provider,
                    contract.contract_number,
                    contract.cost_monthly_cents,
                    contract.renewal_period_months,
                    contract.cancellation_deadline,
                    contract.document_path,
                    1 if contract.is_active else 0,
                    contract.notes,
                    now,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def list_upcoming_cancellations(self, within_days: int = 60) -> List[ContractRecord]:
        """Lists active contracts whose cancellation deadline falls within the given window."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, category, provider, contract_number, cost_monthly_cents,
                       renewal_period_months, cancellation_deadline, document_path, is_active, notes
                  FROM contract_cockpit
                 WHERE is_active = 1
                   AND cancellation_deadline IS NOT NULL
                   AND date(cancellation_deadline) >= date('now')
                   AND date(cancellation_deadline) <= date('now', '+' || ? || ' days')
                 ORDER BY date(cancellation_deadline) ASC
                """,
                (int(within_days),),
            )
            records = []
            for row in cursor.fetchall():
                records.append(
                    ContractRecord(
                        id=row[0],
                        name=row[1],
                        category=row[2],
                        provider=row[3],
                        contract_number=row[4],
                        cost_monthly_cents=row[5],
                        renewal_period_months=row[6],
                        cancellation_deadline=row[7],
                        document_path=row[8],
                        is_active=bool(row[9]),
                        notes=row[10] or "",
                    )
                )
            return records
