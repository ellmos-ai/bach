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
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

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
_MEM_LOCK = Lock()


def _memory_snapshot():
    with _MEM_LOCK:
        return dict(_MEM_COUNTERS)


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
    res = {"outcome": outcome if outcome in OUTCOMES else OTHER}
    expected = COUNTERS.get(counter, set())
    for k in sorted(expected):
        if k in kwargs:
            res[k] = _sanitize_label_value(kwargs[k])
    # Preserve the exact key format used by existing core.telemetry producers.
    return json.dumps(res, sort_keys=True, ensure_ascii=True)


def _db_path(db_path):
    if db_path is not None:
        return Path(db_path)
    value = os.environ.get("BACH_DB")
    return Path(value) if value else None


def _connect(path, *, write=False):
    # A selected store is authoritative: never create a new DB or silently use RAM.
    return sqlite3.connect(
        path.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro"),
        uri=True, timeout=5.0,
    )


def _overflow(outcome):
    return '{"overflow":"true","outcome":"' + outcome + '"}'


def increment(
    counter: str,
    outcome: str = "ok",
    db_path: Path | str | None = None,
    **labels,
) -> bool:
    """Fail-silent increment of a telemetry counter."""
    try:
        if not is_enabled() or counter not in COUNTERS:
            return False
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        labels_str = _build_labels_json(counter, outcome, **labels)
        outcome = outcome if outcome in OUTCOMES else OTHER
        p = _db_path(db_path)
        if p is not None:
            with closing(_connect(p, write=True)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_SCHEMA)
                count = conn.execute(
                    f"SELECT COUNT(DISTINCT labels) FROM {_TABLE} WHERE counter=? AND day=?",
                    (counter, day),
                ).fetchone()[0]
                exists = conn.execute(
                    f"SELECT 1 FROM {_TABLE} WHERE counter=? AND day=? AND labels=?",
                    (counter, day, labels_str),
                ).fetchone()
                if count >= MAX_SERIES_PER_DAY and exists is None:
                    labels_str = _overflow(outcome)
                conn.execute(
                    f"""
                    INSERT INTO {_TABLE} (counter, labels, day, value, updated_at)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(counter, labels, day)
                    DO UPDATE SET value = value + 1, updated_at = excluded.updated_at
                    """,
                    (counter, labels_str, day, now.isoformat()),
                )
                conn.commit()
                return True
        key = (counter, labels_str, day)
        with _MEM_LOCK:
            count = sum(1 for c, _, d in _MEM_COUNTERS if c == counter and d == day)
            if count >= MAX_SERIES_PER_DAY and key not in _MEM_COUNTERS:
                key = (counter, _overflow(outcome), day)
            _MEM_COUNTERS[key] = _MEM_COUNTERS.get(key, 0) + 1
        return True
    except Exception:
        return False


def report(days: int = 7, db_path: Path | str | None = None) -> tuple[bool, str]:
    """Report aggregated counters over the last N days."""
    if days <= 0:
        days = 7
    lines = [
        f"[TELEMETRIE REPORT - Letzte {days} Tage]",
        "=" * 50,
    ]

    try:
        p = _db_path(db_path)
        if p is not None:
            with closing(_connect(p)) as conn:
                rows = conn.execute(
                    f"SELECT counter, labels, SUM(value) FROM {_TABLE} "
                    "WHERE day >= date('now', ?) GROUP BY counter, labels "
                    "ORDER BY counter, SUM(value) DESC", (f"-{days} days",),
                ).fetchall()
        else:
            cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
            totals = {}
            for (counter, labels, day), value in _memory_snapshot().items():
                if day >= cutoff:
                    key = (counter, labels)
                    totals[key] = totals.get(key, 0) + value
            rows = [(counter, labels, value) for (counter, labels), value in sorted(
                totals.items(), key=lambda item: (item[0][0], -item[1]))]
        if not rows:
            lines.append("Keine Telemetrie-Daten erfasst.")
        for counter, labels, value in rows:
            lines.append(f"  {counter:<14} {labels} : {value}")
        return True, "\n".join(lines)
    except Exception:
        return False, "Telemetrie-DB nicht verfügbar"


def status(db_path: Path | str | None = None) -> tuple[bool, str]:
    """Status der Telemetrie-Erfassung und Zähler."""
    try:
        p = _db_path(db_path)
        if p is not None:
            with closing(_connect(p)) as conn:
                series, total = conn.execute(
                    f"SELECT COUNT(*), COALESCE(SUM(value), 0) FROM {_TABLE}"
                ).fetchone()
        else:
            snapshot = _memory_snapshot()
            series, total = len(snapshot), sum(snapshot.values())
    except Exception:
        return False, "Telemetrie-DB nicht verfügbar"
    enabled = is_enabled()
    lines = [
        "[TELEMETRIE STATUS]",
        "=" * 50,
        f"Aktiviert:        {'JA' if enabled else 'NEIN (Opt-Out)'}",
        f"Erlaubte Counter: {', '.join(sorted(COUNTERS.keys()))}",
        f"Erlaubte Outcomes:{', '.join(sorted(OUTCOMES))}",
        f"Serien (Label-Sets): {series}",
        f"Ereignisse gesamt: {total}",
        f"Serien-Cap/Tag: {MAX_SERIES_PER_DAY}",
    ]
    return True, "\n".join(lines)


def reset(confirm: bool = False, db_path: Path | str | None = None) -> tuple[bool, str]:
    """Reset telemetry counters."""
    if not confirm:
        return False, "Zur Bestätigung bitte confirm=True oder --confirm angeben."
    try:
        p = _db_path(db_path)
        if p is not None:
            with closing(_connect(p, write=True)) as conn:
                conn.execute(f"DELETE FROM {_TABLE}")
                conn.commit()
        else:
            with _MEM_LOCK:
                _MEM_COUNTERS.clear()
    except Exception:
        return False, "Telemetrie-DB nicht verfügbar; keine Resetbestätigung"
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
