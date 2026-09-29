# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Medication Plan & Intake Logger (from FolderHome).

Tracks daily medication schedules and confirmed intake timestamps with strict non-diagnostic
safety boundaries (pure schedule tracking, never calculating dosages).
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MedicationSchedule:
    id: Optional[int]
    person: str
    medication_name: str
    dosage: str  # e.g. "1 tablet"
    time_of_day: str  # morning, noon, evening, night
    notes: str
    is_active: bool


@dataclass
class IntakeEvent:
    id: Optional[int]
    medication_id: int
    confirmed_at: str
    confirmed_by: str
    notes: str


def ensure_medication_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS medication_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person TEXT NOT NULL,
            medication_name TEXT NOT NULL,
            dosage TEXT NOT NULL,
            time_of_day TEXT NOT NULL,
            notes TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS medication_intakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medication_id INTEGER NOT NULL,
            confirmed_at TEXT NOT NULL,
            confirmed_by TEXT DEFAULT 'user',
            notes TEXT,
            FOREIGN KEY (medication_id) REFERENCES medication_schedules(id)
        )
        """
    )
    conn.commit()


class BachMedicationService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextlib.contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            ensure_medication_schema(conn)
            with conn:
                yield conn
        finally:
            conn.close()

    def add_schedule(self, schedule: MedicationSchedule) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO medication_schedules
                    (person, medication_name, dosage, time_of_day, notes, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule.person, schedule.medication_name, schedule.dosage,
                    schedule.time_of_day, schedule.notes, 1 if schedule.is_active else 0, now,
                ),
            )
            return cursor.lastrowid

    def record_intake(self, medication_id: int, confirmed_by: str = "user", notes: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO medication_intakes
                    (medication_id, confirmed_at, confirmed_by, notes)
                VALUES (?, ?, ?, ?)
                """,
                (medication_id, now, confirmed_by, notes),
            )
            return cursor.lastrowid
