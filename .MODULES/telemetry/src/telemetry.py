# SPDX-License-Identifier: MIT
"""
Telemetry Provider - Low-cardinality, privacy-first Zaehler (OPS-TELEM-001)
===========================================================================

Self-contained standalone module for low-cardinality local telemetry.
Operates fail-silent with local SQLite persistence or in-memory fallback.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

__version__ = "1.0.0"

COUNTERS: dict[str, set] = {
    "agent_starts": {"agent"},
    "model_calls": {"model"},
    "tool_calls": {"tool"},
}

OUTCOMES = {"ok", "error", "dummy", "timeout"}
_LABEL_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
MAX_LABEL_VALUE_LEN = 40
MAX_SERIES_PER_DAY = 200
OTHER = "other"

_TABLE = "telemetry_counters"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    counter    TEXT NOT NULL,
    labels     TEXT NOT NULL,
    day        TEXT NOT NULL,
    value      INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (counter, labels, day)
)
"""

_DISABLE_ENV_VALUES = {"1", "true", "yes", "on"}

# In-memory fallback if no DB path is supplied
_MEM_COUNTERS: dict[tuple[str, str, str], int] = {}


def is_enabled() -> bool:
    val = os.environ.get("BACH_TELEMETRY_DISABLED", "").strip().lower()
    if not val:
        val = os.environ.get("TELEMETRY_DISABLED", "").strip().lower()
    return val not in _DISABLE_ENV_VALUES


def _sanitize_label_value(val: Any) -> str:
    if not isinstance(val, str):
        return OTHER
    v = val.strip().lower()
    if not v or len(v) > MAX_LABEL_VALUE_LEN or not _LABEL_VALUE_RE.match(v):
        return OTHER
    return v


def _build_labels_json(counter: str, outcome: str, **kwargs) -> str:
    out = _sanitize_label_value(outcome)
    if out not in OUTCOMES:
        out = OTHER
    res = {"outcome": out}
    expected = COUNTERS.get(counter, set())
    for k in sorted(expected):
        res[k] = _sanitize_label_value(kwargs.get(k))
    return json.dumps(res, sort_keys=True, separators=(",", ":"))


def increment(
    counter: str,
    outcome: str = "ok",
    db_path: Path | str | None = None,
    **labels,
) -> bool:
    """Fail-silent increment of a telemetry counter."""
    if not is_enabled():
        return False
    if counter not in COUNTERS:
        return False
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    labels_str = _build_labels_json(counter, outcome, **labels)
    updated_at = now.isoformat()

    if db_path is not None:
        p = Path(db_path)
    else:
        env_db = os.environ.get("BACH_DB")
        p = Path(env_db) if env_db else None

    if p and p.is_file():
        try:
            with sqlite3.connect(p, timeout=5.0) as conn:
                conn.execute(_SCHEMA)
                conn.execute(
                    f"""
                    INSERT INTO {_TABLE} (counter, labels, day, value, updated_at)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(counter, labels, day)
                    DO UPDATE SET value = value + 1, updated_at = excluded.updated_at
                    """,
                    (counter, labels_str, day, updated_at),
                )
                conn.commit()
                return True
        except Exception:
            pass

    key = (counter, labels_str, day)
    _MEM_COUNTERS[key] = _MEM_COUNTERS.get(key, 0) + 1
    return True


def report(days: int = 7, db_path: Path | str | None = None) -> tuple[bool, str]:
    """Report aggregated counters over the last N days."""
    if not is_enabled():
        return True, "[TELEMETRIE] Erfassung ist deaktiviert (OPT-OUT)."

    lines = [
        f"[TELEMETRIE REPORT - Letzte {days} Tage]",
        "=" * 50,
    ]

    p = Path(db_path) if db_path else (Path(os.environ["BACH_DB"]) if os.environ.get("BACH_DB") else None)
    found_db = False
    if p and p.is_file():
        try:
            with sqlite3.connect(p, timeout=5.0) as conn:
                rows = conn.execute(
                    f"SELECT counter, labels, day, value FROM {_TABLE} ORDER BY day DESC, counter ASC"
                ).fetchall()
                found_db = True
                if not rows:
                    lines.append("Keine Einträge in der Telemetrie-Tabelle.")
                else:
                    for c, l, d, v in rows:
                        lines.append(f"  [{d}] {c:<14} {l} : {v}")
        except Exception as exc:
            lines.append(f"DB-Hinweis: {exc}")

    if not found_db or _MEM_COUNTERS:
        if _MEM_COUNTERS:
            lines.append("In-Memory Zähler:")
            for (c, l, d), v in sorted(_MEM_COUNTERS.items()):
                lines.append(f"  [{d}] {c:<14} {l} : {v}")
        elif not found_db:
            lines.append("Keine aktiven Telemetrie-Zähler erfasst.")

    return True, "\n".join(lines)


def status(db_path: Path | str | None = None) -> tuple[bool, str]:
    """Status der Telemetrie-Erfassung und Zähler."""
    enabled = is_enabled()
    lines = [
        "[TELEMETRIE STATUS]",
        "=" * 50,
        f"Aktiviert:        {'JA' if enabled else 'NEIN (Opt-Out)'}",
        f"Erlaubte Counter: {', '.join(sorted(COUNTERS.keys()))}",
        f"Erlaubte Outcomes:{', '.join(sorted(OUTCOMES))}",
        f"In-Memory Zähler: {len(_MEM_COUNTERS)} Serien aktiv",
    ]
    return True, "\n".join(lines)


def reset(confirm: bool = False, db_path: Path | str | None = None) -> tuple[bool, str]:
    """Reset telemetry counters."""
    if not confirm:
        return False, "Zur Bestätigung bitte confirm=True oder --confirm angeben."
    _MEM_COUNTERS.clear()
    p = Path(db_path) if db_path else (Path(os.environ["BACH_DB"]) if os.environ.get("BACH_DB") else None)
    if p and p.is_file():
        try:
            with sqlite3.connect(p, timeout=5.0) as conn:
                conn.execute(f"DELETE FROM {_TABLE}")
                conn.commit()
        except Exception as exc:
            return False, f"Fehler beim Leeren der DB-Tabelle: {exc}"
    return True, "[OK] Alle Telemetrie-Zähler zurückgesetzt."


class TelemetryHandler:
    """CLI/Hub adapter for bach telemetry."""

    def __init__(self, base_path: Path | None = None):
        self.base_path = Path(base_path) if base_path else Path.cwd()

    @property
    def profile_name(self) -> str:
        return "telemetry"

    def get_operations(self) -> dict:
        return {
            "report": "Zaehler der letzten N Tage anzeigen (Default 7)",
            "status": "Erfassungs-/Schema-Status anzeigen",
            "reset": "Alle Zaehler loeschen (erfordert --confirm)",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple[bool, str]:
        if operation == "report" or not operation:
            days = 7
            for arg in args:
                if arg.isdigit():
                    days = int(arg)
                    break
            if dry_run:
                return True, f"[DRY-RUN] Wuerde Telemetrie-Report ({days} Tage) zeigen"
            return report(days=days)
        elif operation == "status":
            if dry_run:
                return True, "[DRY-RUN] Wuerde Telemetrie-Status zeigen"
            return status()
        elif operation == "reset":
            if dry_run:
                return True, "[DRY-RUN] Wuerde alle Telemetrie-Zaehler loeschen"
            return reset(confirm="--confirm" in args)
        return False, f"Unbekannte Operation: {operation}"
