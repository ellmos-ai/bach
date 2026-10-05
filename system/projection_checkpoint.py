# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Lightweight per-session SQLite checkpoint store.

Used by callers of ``sqlite_transit_sync.verify_projection_database`` to supply
a ``previous_checkpoint`` and to advance it after successful verification.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Checkpoint:
    module: str
    checkpoint: int
    updated_at: str

    def __int__(self) -> int:
        return self.checkpoint


class CheckpointStore:
    """Thread-safe(through sqlite) persistent checkpoint store."""

    _SCHEMA = (
        "CREATE TABLE IF NOT EXISTS session_checkpoints ("
        "module TEXT PRIMARY KEY, "
        "checkpoint INTEGER NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(self._SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get(self, module: str) -> Checkpoint | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT module, checkpoint, updated_at FROM session_checkpoints WHERE module = ?",
                (module,),
            ).fetchone()
        if row is None:
            return None
        return Checkpoint(module=row[0], checkpoint=row[1], updated_at=row[2])

    def set(self, module: str, checkpoint: int) -> Checkpoint:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session_checkpoints(module, checkpoint, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(module) DO UPDATE SET checkpoint=excluded.checkpoint, updated_at=excluded.updated_at",
                (module, int(checkpoint), now),
            )
            conn.commit()
        return Checkpoint(module=module, checkpoint=int(checkpoint), updated_at=now)

    def advance(self, module: str, checkpoint: int) -> Checkpoint:
        current = self.get(module)
        if current is not None and int(checkpoint) < current.checkpoint:
            raise ValueError(
                f"Checkpoint regression refused for {module!r}: "
                f"{int(checkpoint)} < {current.checkpoint}"
            )
        return self.set(module, int(checkpoint))

    def list(self) -> list[Checkpoint]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT module, checkpoint, updated_at FROM session_checkpoints ORDER BY module"
            ).fetchall()
        return [Checkpoint(module=r[0], checkpoint=r[1], updated_at=r[2]) for r in rows]

    def delete(self, module: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM session_checkpoints WHERE module = ?", (module,))
            conn.commit()
            return cur.rowcount > 0
