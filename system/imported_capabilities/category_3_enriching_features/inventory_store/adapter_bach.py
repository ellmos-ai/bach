# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Household Inventory & Expiration Tracking (from FolderHome).

Provides append-only inventory item logs, storage locations, minimum stock limits,
expiration dates, and automatic replenishment triggers for Bach.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class InventoryItem:
    id: Optional[int]
    name: str
    category: str
    location: str
    quantity: float
    unit: str
    min_quantity: float
    expiration_date: Optional[str]
    notes: str


def ensure_inventory_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            quantity REAL DEFAULT 1.0,
            unit TEXT DEFAULT 'pcs',
            min_quantity REAL DEFAULT 1.0,
            expiration_date TEXT,
            notes TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


class BachInventoryService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextlib.contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            ensure_inventory_schema(conn)
            with conn:
                yield conn
        finally:
            conn.close()

    def upsert_item(self, item: InventoryItem) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if item.id:
                cursor.execute(
                    """
                    UPDATE inventory_items
                       SET name = ?, category = ?, location = ?, quantity = ?,
                           unit = ?, min_quantity = ?, expiration_date = ?, notes = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (
                        item.name, item.category, item.location, item.quantity,
                        item.unit, item.min_quantity, item.expiration_date, item.notes, now, item.id,
                    ),
                )
                return item.id
            else:
                cursor.execute(
                    """
                    INSERT INTO inventory_items
                        (name, category, location, quantity, unit, min_quantity, expiration_date, notes, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.name, item.category, item.location, item.quantity,
                        item.unit, item.min_quantity, item.expiration_date, item.notes, now,
                    ),
                )
                return cursor.lastrowid

    def list_restock_candidates(self) -> List[InventoryItem]:
        """Returns items where current quantity is below minimum stock threshold."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, category, location, quantity, unit, min_quantity, expiration_date, notes
                  FROM inventory_items
                 WHERE quantity <= min_quantity
                 ORDER BY (min_quantity - quantity) DESC
                """
            )
            return [
                InventoryItem(
                    id=row[0], name=row[1], category=row[2], location=row[3],
                    quantity=row[4], unit=row[5], min_quantity=row[6],
                    expiration_date=row[7], notes=row[8] or "",
                )
                for row in cursor.fetchall()
            ]
