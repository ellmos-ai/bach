#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Small memory decay helper used by MemHandler and ActivityTracker."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable


class MemoryDecay:
    """Apply conservative decay to memory records when the schema supports it."""

    def __init__(
        self,
        db_path: str | Path,
        fact_decay_rate: float = 0.98,
        minimum_confidence: float = 0.1,
    ):
        self.db_path = Path(db_path)
        self.fact_decay_rate = fact_decay_rate
        self.minimum_confidence = minimum_confidence

    def apply_decay_to_facts(self, dry_run: bool = False) -> dict:
        """Lower memory_facts.confidence slightly without deleting rows."""
        if not self.db_path.exists():
            return {"decayed_facts": 0, "skipped": "database missing"}

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if not self._table_exists(conn, "memory_facts"):
                return {"decayed_facts": 0, "skipped": "memory_facts missing"}

            columns = self._columns(conn, "memory_facts")
            if not {"id", "confidence"}.issubset(columns):
                return {"decayed_facts": 0, "skipped": "confidence column missing"}

            rows = conn.execute(
                """
                SELECT id, confidence
                FROM memory_facts
                WHERE confidence IS NOT NULL AND confidence > ?
                """,
                (self.minimum_confidence,),
            ).fetchall()

            updates = []
            for row in rows:
                current = float(row["confidence"])
                new_value = max(
                    self.minimum_confidence,
                    min(1.0, current * self.fact_decay_rate),
                )
                if new_value < current:
                    updates.append((new_value, row["id"]))

            if updates and not dry_run:
                if "updated_at" in columns:
                    now = datetime.now().isoformat()
                    conn.executemany(
                        "UPDATE memory_facts SET confidence = ?, updated_at = ? WHERE id = ?",
                        [(value, now, fact_id) for value, fact_id in updates],
                    )
                else:
                    conn.executemany(
                        "UPDATE memory_facts SET confidence = ? WHERE id = ?",
                        updates,
                    )
                conn.commit()

        return {"decayed_facts": len(updates), "dry_run": dry_run}

    def run_decay(
        self,
        facts: bool = True,
        lessons: bool = True,
        working: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Run available decay steps and report unsupported surfaces as no-ops."""
        parts = []
        if facts:
            result = self.apply_decay_to_facts(dry_run=dry_run)
            parts.append(f"Facts: {result.get('decayed_facts', 0)} decayed")
        if lessons:
            parts.append("Lessons: 0 decayed (no confidence surface)")
        if working:
            parts.append("Working: 0 decayed (handled by working cleanup)")

        prefix = "[DRY-RUN] " if dry_run else ""
        return prefix + "Memory Decay: " + ", ".join(parts)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


__all__: Iterable[str] = ("MemoryDecay",)
