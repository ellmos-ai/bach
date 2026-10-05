# SPDX-License-Identifier: MIT
"""Failure Trails – negatives Gedächtnis für fehlgeschlagene Werkzeugpfade.

Ocean-konformer Shadow (runtime_authority=false): Der Store protokolliert
Fehler, berechnet exponentielles Backoff und signalisiert Blockaden. Caller
(z.B. Subagenten-Scheduler oder Memory-Hook) entscheiden, ob sie
``is_blocked()`` / ``should_skip()`` respektieren.

Ein Trail-Eintrag ist eindeutig durch (tool_path, failure_signature,
context_hash). ``failure_signature`` leitet sich aus dem Exception-Typ und
einer normalisierten Fehlermeldung ab; ``context_hash`` aus optionalen
Kontextdaten, damit derselbe Aufruf unter unterschiedlichen Bedingungen
unterschiedlich bewertet wird.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_BACKOFF_SECONDS = 60
DEFAULT_MAX_BACKOFF_SECONDS = 3600
DEFAULT_AGE_OUT_MINUTES = 30


@dataclass(frozen=True, slots=True)
class TrailEntry:
    """Immutable Snapshot eines Failure-Trail-Eintrags."""

    tool_path: str
    failure_signature: str
    context_hash: str
    first_seen_at: datetime
    last_seen_at: datetime
    retry_count: int
    backoff_until: datetime

    def is_blocked(self, now: datetime | None = None) -> bool:
        """True, wenn der Eintrag aktuell im Backoff liegt."""
        if now is None:
            now = datetime.now()
        return self.backoff_until > now

    def to_row(self) -> tuple[str, str, str, str, str, int, str]:
        return (
            self.tool_path,
            self.failure_signature,
            self.context_hash,
            self.first_seen_at.isoformat(),
            self.last_seen_at.isoformat(),
            self.retry_count,
            self.backoff_until.isoformat(),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "TrailEntry":
        return cls(
            tool_path=row["tool_path"],
            failure_signature=row["failure_signature"],
            context_hash=row["context_hash"],
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            retry_count=row["retry_count"],
            backoff_until=datetime.fromisoformat(row["backoff_until"]),
        )


class FailureTrailStore:
    """In-Memory-Store für Failure Trails mit optionalem SQLite-Write-Through."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_backoff_seconds: int = DEFAULT_BASE_BACKOFF_SECONDS,
        max_backoff_seconds: int = DEFAULT_MAX_BACKOFF_SECONDS,
    ):
        self._trails: dict[tuple[str, str, str], TrailEntry] = {}
        self.db_path = Path(db_path) if db_path else None
        self.max_retries = max(1, max_retries)
        self.base_backoff_seconds = max(1, base_backoff_seconds)
        self.max_backoff_seconds = max(self.base_backoff_seconds, max_backoff_seconds)

        if self.db_path:
            self._ensure_table()
            self._load_from_db()

    # ── Public API ────────────────────────────────────────────────────

    def record_failure(
        self,
        tool_path: str,
        exc: BaseException,
        context: dict[str, Any] | None = None,
        *,
        max_retries: int | None = None,
        base_backoff_seconds: int | None = None,
        max_backoff_seconds: int | None = None,
    ) -> TrailEntry:
        """Einen Fehler protokollieren und Backoff berechnen.

        Existiert bereits ein Trail für den gleichen Schlüssel, wird
        ``retry_count`` inkrementiert und ``backoff_until`` neu gesetzt.
        Andernfalls entsteht ein neuer Eintrag mit ``retry_count=1``.
        """
        now = datetime.now()
        key = self._make_key(tool_path, exc, context)
        existing = self._trails.get(key)

        if existing is not None:
            retry_count = existing.retry_count + 1
            first_seen_at = existing.first_seen_at
        else:
            retry_count = 1
            first_seen_at = now

        max_retries = self.max_retries if max_retries is None else max(1, max_retries)
        base = self.base_backoff_seconds if base_backoff_seconds is None else max(1, base_backoff_seconds)
        max_backoff = (
            self.max_backoff_seconds
            if max_backoff_seconds is None
            else max(base, max_backoff_seconds)
        )

        # Exponentielles Backoff: 60s, 120s, 240s, ... mit Cap.
        backoff_seconds = min(base * (2 ** (retry_count - 1)), max_backoff)
        # Ab Max-Retries verlängern wir das Backoff bis ca. 24h (Hard-Cap),
        # damit der Pfad nicht für immer gesperrt erscheint, aber deutlich
        # als verbrannt markiert ist.
        if retry_count >= max_retries:
            backoff_seconds = max(backoff_seconds, min(max_backoff * 2, 86400))

        entry = TrailEntry(
            tool_path=key[0],
            failure_signature=key[1],
            context_hash=key[2],
            first_seen_at=first_seen_at,
            last_seen_at=now,
            retry_count=retry_count,
            backoff_until=now + timedelta(seconds=backoff_seconds),
        )

        self._trails[key] = entry
        if self.db_path:
            self._upsert(entry)
        return entry

    def is_blocked(
        self,
        tool_path: str,
        context: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> bool:
        """True, wenn ein Trail für *tool_path* aktuell blockiert ist.

        Ohne *context* wird jeder passende Trail für den Tool-Pfad
        berücksichtigt (broad block). Mit *context* nur der exakt
        passende Kontext.
        """
        if now is None:
            now = datetime.now()
        for entry in self._matching(tool_path, context):
            if entry.is_blocked(now):
                return True
        return False

    def should_skip(
        self,
        tool_path: str,
        context: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Scheduler-Hinweis: diesen Werkzeugpfad vorerst überspringen."""
        return self.is_blocked(tool_path, context, now=now)

    def age_out(self, max_age_minutes: int = DEFAULT_AGE_OUT_MINUTES) -> list[TrailEntry]:
        """Trails entfernen, deren letzter Fehler älter als *max_age_minutes* ist.

        Gibt die entfernten Einträge zurück.
        """
        cutoff = datetime.now() - timedelta(minutes=max_age_minutes)
        removed: list[TrailEntry] = []
        for key, entry in list(self._trails.items()):
            if entry.last_seen_at < cutoff:
                removed.append(entry)
                del self._trails[key]
        if removed and self.db_path:
            self._delete_aged(cutoff)
        return removed

    def list_trails(
        self,
        tool_path: str | None = None,
    ) -> list[TrailEntry]:
        """Alle Trails (oder nur für *tool_path*) als sortierte Liste."""
        entries = list(self._trails.values())
        if tool_path is not None:
            entries = [e for e in entries if e.tool_path == tool_path]
        return sorted(entries, key=lambda e: e.last_seen_at, reverse=True)

    def clear(self) -> None:
        """Alle Trails im Speicher und – falls vorhanden – in der DB löschen."""
        self._trails.clear()
        if self.db_path:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("DELETE FROM working_memory_failure_trails")
                    conn.commit()
            except sqlite3.Error as exc:
                log.warning("failure_trails clear failed: %s", exc)

    # ── Internal helpers ──────────────────────────────────────────────

    def _make_key(
        self,
        tool_path: str,
        exc: BaseException,
        context: dict[str, Any] | None,
    ) -> tuple[str, str, str]:
        return (
            self._normalize_tool_path(tool_path),
            self._failure_signature(exc),
            self._context_hash(context),
        )

    @staticmethod
    def _normalize_tool_path(tool_path: str) -> str:
        return str(tool_path).strip().lower()

    @staticmethod
    def _failure_signature(exc: BaseException) -> str:
        """Stabile Signatur aus Exception-Typ und normalisierter Meldung."""
        type_name = exc.__class__.__name__
        message = str(exc).strip()
        # Lange Pfade/UUIDs rausnormalisieren, damit ähnliche Fehler zusammenfallen.
        normalized = message[:240].replace(str(Path.home()), "~").replace("\n", " ")
        return f"{type_name}: {normalized}"

    @staticmethod
    def _context_hash(context: dict[str, Any] | None) -> str:
        if not context:
            return ""
        try:
            payload = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            payload = repr(context)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _matching(
        self,
        tool_path: str,
        context: dict[str, Any] | None,
    ) -> Iterable[TrailEntry]:
        normalized_tool = self._normalize_tool_path(tool_path)
        if context is None:
            return (e for e in self._trails.values() if e.tool_path == normalized_tool)
        ctx_hash = self._context_hash(context)
        return (
            e
            for e in self._trails.values()
            if e.tool_path == normalized_tool and e.context_hash == ctx_hash
        )

    # ── SQLite persistence ────────────────────────────────────────────

    def _ensure_table(self) -> None:
        if not self.db_path:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS working_memory_failure_trails (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tool_path TEXT NOT NULL,
                        failure_signature TEXT NOT NULL,
                        context_hash TEXT NOT NULL DEFAULT '',
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        backoff_until TEXT NOT NULL,
                        UNIQUE(tool_path, failure_signature, context_hash)
                    )
                    """
                )
                conn.commit()
        except sqlite3.Error as exc:
            log.warning("failure_trails table creation failed: %s", exc)

    def _load_from_db(self) -> None:
        if not self.db_path or not self.db_path.exists():
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM working_memory_failure_trails"
                ).fetchall()
                for row in rows:
                    entry = TrailEntry.from_row(row)
                    self._trails[(entry.tool_path, entry.failure_signature, entry.context_hash)] = entry
        except sqlite3.Error as exc:
            log.warning("failure_trails load failed: %s", exc)

    def _upsert(self, entry: TrailEntry) -> None:
        if not self.db_path:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO working_memory_failure_trails
                        (tool_path, failure_signature, context_hash,
                         first_seen_at, last_seen_at, retry_count, backoff_until)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tool_path, failure_signature, context_hash)
                    DO UPDATE SET
                        last_seen_at = excluded.last_seen_at,
                        retry_count = excluded.retry_count,
                        backoff_until = excluded.backoff_until
                    """,
                    entry.to_row(),
                )
                conn.commit()
        except sqlite3.Error as exc:
            log.warning("failure_trails upsert failed: %s", exc)

    def _delete_aged(self, cutoff: datetime) -> None:
        if not self.db_path:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM working_memory_failure_trails WHERE last_seen_at < ?",
                    (cutoff.isoformat(),),
                )
                conn.commit()
        except sqlite3.Error as exc:
            log.warning("failure_trails aged delete failed: %s", exc)
