#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Telemetry - Low-cardinality, privacy-first, lokal
=======================================================
OPS-TELEM-001 (ROADMAP Security-Prio-1, OpenTelemetry-inspiriert)

Design-Ziele:
  - LOKAL: SQLite in der kanonischen BACH-DB (BACH_DB), kein Export.
  - PRIVACY-FIRST: Es werden NUR Zaehler mit Low-Cardinality-Labels
    gespeichert -- niemals Prompts, Payloads, Pfade, Antworten oder
    Nutzerdaten. Labels werden streng validiert (Regex + Fallback "other").
  - LOW-CARDINALITY: Feste Counter-Allowlist, feste Label-Sets pro Counter,
    Tages-Aggregation (UPSERT), Serien-Cap pro Tag (MAX_SERIES) mit
    Overflow-Bucket.
  - FAIL-SILENT: Telemetrie darf Kernpfade NIE beeinflussen -- jede
    Ausnahme wird geschluckt (inkl. abgeschalteter/unerreichbarer DB).
  - OPT-OUT: BACH_TELEMETRY_DISABLED=1 schaltet die Erfassung ab.

Counter (feste Allowlist, siehe COUNTERS):
  - agent_starts  {agent, outcome}   -> Agentenstarts (AgentRuntime)
  - model_calls   {model, outcome}    -> Modell-Aufrufe (z.B. Ollama)
  - tool_calls    {tool, outcome}     -> geroutete Befehle (Launcher)

outcome-Menge (fix): ok | error | dummy | timeout (Alles andere -> "other").

Usage:
    from core.telemetry import increment, report, status, reset
    increment("tool_calls", outcome="ok", tool="task")
    success, text = report(days=7)

Autor: Buddha Worker-Agent (BACH)
Datum: 2026-09-16 (Task #1315 / OPS-TELEM-001)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

__version__ = "1.0.0"

# ── Konfiguration ───────────────────────────────────────────────────────────

#: Erlaubte Counter und ihre Low-Cardinality-Labels (outcome ist implizit).
COUNTERS: dict[str, set] = {
    "agent_starts": {"agent"},
    "model_calls": {"model"},
    "tool_calls": {"tool"},
}

#: Erlaubte outcome-Werte (fix, klein).
OUTCOMES = {"ok", "error", "dummy", "timeout"}

#: Label-Wert-Validierung: kleingeschriebene, kompakte, ASCII-sichere Token.
#: Schliesst Freitext, Prompts, Pfade, Umlaute und Injektionsversuche aus.
_LABEL_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")

#: Maximal zulaessige Label-Wert-Laenge (Redundanz zum Regex-Schutz).
MAX_LABEL_VALUE_LEN = 40

#: Maximal distinkte Label-Serien pro (Counter, Tag); danach Overflow-Bucket.
MAX_SERIES_PER_DAY = 200

#: Fallback-Label-Wert fuer ungueltige/hochkardinalitaetsgefaehrdete Werte.
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


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_db_path() -> Optional[Path]:
    """Liefert den kanonischen BACH-DB-Pfad (lazy import, fail-silent)."""
    try:
        from hub import bach_paths
        return Path(bach_paths.BACH_DB)
    except Exception:
        return None


def is_enabled() -> bool:
    """Telemetrie aktiv? (BACH_TELEMETRY_DISABLED=1 schaltet ab)."""
    return os.environ.get("BACH_TELEMETRY_DISABLED", "").strip().lower() not in _DISABLE_ENV_VALUES


def _normalize_label_value(value) -> str:
    """Validiert einen Label-Wert gegen die Low-Cardinality-Regeln."""
    if not isinstance(value, str):
        return OTHER
    value = value.strip().lower()
    if len(value) > MAX_LABEL_VALUE_LEN or not _LABEL_VALUE_RE.match(value):
        return OTHER
    return value


def _normalize_labels(counter: str, labels: dict) -> dict:
    """Filtert Labels auf das erlaubte Set und validiert die Werte."""
    allowed = COUNTERS.get(counter, set())
    normalized = {}
    for key in allowed:
        if key in labels:
            normalized[key] = _normalize_label_value(labels[key])
    return normalized


def _labels_key(counter: str, outcome: str, labels: dict) -> str:
    """Serialisiert die Label-Serie deterministisch (sortierte JSON-Keys)."""
    payload = dict(labels)
    payload["outcome"] = outcome
    return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def _today() -> str:
    """Aktueller UTC-Tag (Tagesaggregation, YYYY-MM-DD)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _connect(db_path: Optional[Path] = None) -> Optional[sqlite3.Connection]:
    """Oeffnet die DB und stellt das Schema idempotent sicher (fail-silent)."""
    path = Path(db_path) if db_path is not None else _get_db_path()
    if path is None:
        return None
    conn = sqlite3.connect(str(path), timeout=2)
    conn.execute(_SCHEMA)  # CREATE TABLE IF NOT EXISTS -> additiv/idempotent
    return conn


def ensure_schema(db_path: Optional[Path] = None,
                  conn: Optional[sqlite3.Connection] = None) -> bool:
    """Stellt die Telemetrie-Tabelle sicher (Migration/Handler-Status)."""
    try:
        if conn is not None:
            conn.execute(_SCHEMA)
            return True
        c = _connect(db_path)
        if c is None:
            return False
        c.close()
        return True
    except Exception:
        return False


# ── Kern-API ────────────────────────────────────────────────────────────────

def increment(counter: str,
              outcome: str = "ok",
              db_path: Optional[Path] = None,
              **labels) -> bool:
    """Erhoeht einen Low-Cardinality-Zaehler um 1 (UPSERT, fail-silent).

    Speichert ausschliesslich: counter, validierte Labels, Tag, Summe.
    Keine Payloads, keine Freitexte, keine Prompts, keine Nutzerdaten.
    """
    try:
        if not is_enabled():
            return False
        if counter not in COUNTERS:
            return False

        outcome = outcome if outcome in OUTCOMES else OTHER
        labels = _normalize_labels(counter, labels)
        key = _labels_key(counter, outcome, labels)
        day = _today()
        now = datetime.now(timezone.utc).isoformat()

        conn = _connect(db_path)
        if conn is None:
            return False
        try:
            cur = conn.cursor()

            # Serien-Cap: neue Serien landen nach MAX_SERIES im Overflow-Bucket.
            cur.execute(
                f"SELECT COUNT(DISTINCT labels) FROM {_TABLE} "
                "WHERE counter = ? AND day = ?",
                (counter, day),
            )
            row = cur.fetchone()
            if row and int(row[0] or 0) >= MAX_SERIES_PER_DAY:
                cur.execute(
                    f"SELECT 1 FROM {_TABLE} WHERE counter = ? AND day = ? AND labels = ?",
                    (counter, day, key),
                )
                if cur.fetchone() is None:
                    key = '{"overflow":"true","outcome":"' + outcome + '"}'

            conn.execute(
                f"INSERT INTO {_TABLE} (counter, labels, day, value, updated_at) "
                "VALUES (?, ?, ?, 1, ?) "
                f"ON CONFLICT(counter, labels, day) DO UPDATE SET "
                f"value = value + 1, updated_at = ?",
                (counter, key, day, now, now),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False


# ── Lese-/Verwaltungs-API (fuer Handler/Tests) ──────────────────────────────

def report(days: int = 7,
           db_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Aggregierter Telemetrie-Report der letzten N Tage (Default 7)."""
    try:
        if days <= 0:
            days = 7
        conn = _connect(db_path)
        if conn is None:
            return False, "Telemetrie-DB nicht verfuegbar"
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT counter, labels, SUM(value) FROM {_TABLE} "
                f"WHERE day >= date('now', ?) GROUP BY counter, labels "
                "ORDER BY counter, SUM(value) DESC",
                (f"-{days} days",),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        lines = [
            "",
            "[TELEMETRIE] Low-cardinality Zaehler (lokal, privacy-first)",
            "=" * 60,
            f"  Zeitraum: letzte {days} Tage (UTC)",
            "",
        ]
        if not rows:
            lines.append("  Keine Telemetrie-Daten erfasst.")
        else:
            current = None
            for counter, labels, value in rows:
                if counter != current:
                    current = counter
                    lines.append(f"  {counter}:")
                lines.append(f"    {labels}  ->  {value}")
            lines.append("")
            lines.append("  Privacy: Nur Zaehler mit validierten Labels.")
            lines.append("  Keine Payloads, Prompts oder Nutzerdaten gespeichert.")
        return True, "\n".join(lines)
    except Exception as e:
        return False, f"Telemetrie-Report fehlgeschlagen: {e}"


def status(db_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Betriebsstatus der Telemetrie (Schema, Serien, Opt-Out)."""
    try:
        enabled = is_enabled()
        schema_ok = ensure_schema(db_path=db_path)
        total = series = None
        if schema_ok:
            conn = _connect(db_path)
            if conn is not None:
                try:
                    cur = conn.cursor()
                    cur.execute(f"SELECT COUNT(*), COALESCE(SUM(value), 0) FROM {_TABLE}")
                    series, total = cur.fetchone()
                finally:
                    conn.close()

        lines = [
            "",
            "[TELEMETRIE] Status (OPS-TELEM-001)",
            "=" * 60,
            f"  Erfassung aktiv:      {'JA' if enabled else 'NEIN'}",
            "  Opt-Out:              BACH_TELEMETRY_DISABLED=1",
            f"  Schema vorhanden:     {'JA' if schema_ok else 'NEIN'}",
        ]
        if series is not None:
            lines.append(f"  Serien (Label-Sets):   {series}")
            lines.append(f"  Ereignisse gesamt:    {total}")
        lines += [
            "",
            "  Counter: " + ", ".join(sorted(COUNTERS)),
            "  Outcomes: " + ", ".join(sorted(OUTCOMES)),
            "  Serien-Cap/Tag: " + str(MAX_SERIES_PER_DAY),
            "",
            "  `bach telemetry report`  - Zaehler der letzten Tage",
            "  `bach telemetry reset --confirm`  - alle Zaehler loeschen",
        ]
        return True, "\n".join(lines)
    except Exception as e:
        return False, f"Telemetrie-Status fehlgeschlagen: {e}"


def reset(confirm: bool = False,
          db_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Loescht alle Telemetrie-Zaehler (Datensparsamkeit; nur --confirm)."""
    if not confirm:
        return False, (
            "Telemetrie-Reset erfordert --confirm\n"
            "Usage: bach telemetry reset --confirm"
        )
    try:
        conn = _connect(db_path)
        if conn is None:
            return False, "Telemetrie-DB nicht verfuegbar"
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {_TABLE}")
            deleted = int(cur.fetchone()[0] or 0)
            cur.execute(f"DELETE FROM {_TABLE}")
            conn.commit()
        finally:
            conn.close()
        return True, f"[TELEMETRIE] {deleted} Zaehler-Serien geloescht."
    except Exception as e:
        return False, f"Telemetrie-Reset fehlgeschlagen: {e}"