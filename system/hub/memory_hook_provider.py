# SPDX-License-Identifier: MIT
"""
memoryhooker Provider-Seam (MODULRUECKTRANSFER Stufe 6)
=======================================================

In-process-Anbindung des externen Moduls `memoryhooker` an ChatRuntime.process.

Rollen (Schnittstellenmatrix MODULRUECKTRANSFER-PLAN.md, Nr. 6):
- BACH liefert die "documented read-only API", auf die memoryhookers reservierter
  `bach`-Backend-Slot wartet (memoryhooker/backends/bach.py): BachMemoryBackend
  implementiert das MemoryBackend-Protocol (search/available) read-only gegen
  BACH_DB (SQLite `mode=ro`).
- memoryhooker liefert die Hook-Logik: `evaluate_prompt` (Modi remember/clue/
  remember+search) erzwingt zentral max_injections_per_session + Cooldown;
  `session_start_message` den einmaligen Session-Hinweis.

Rollback (Plan-Regel 4.1): BACH_USE_EXTERNAL_MEMORYHOOKS=0/false/no/off
stellt sofort auf den internen Pfad (keine Injektion) zurueck -- live gelesen,
ohne Neustart. Fehlt das Modul oder verletzt es den Contract, failt der Seam
geschlossen: keine Injektion, eine Log-Warnung.

Audit-Trail (Plan Stufe 6): Jede Kontextinjektion wird als JSONL-Zeile neben
der BACH_DB protokolliert (memoryhooker_audit.jsonl).

WICHTIG: Hooks != Injektoren (core/hooks.py). Der Injector-Pfad
(ChatRuntime._get_bach_context) bleibt unberuehrt; dieser Seam ist reiner
Hook-Transport.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

#: Name des externen Python-Moduls (requirements.txt-Pin).
MEMORYHOOKER_MODULE = "memoryhooker"

#: Rollback-Schalter (Plan-Regel 4.1).
ROLLBACK_ENV = "BACH_USE_EXTERNAL_MEMORYHOOKS"
_OFF_VALUES = {"0", "false", "no", "off"}

#: BACH-Default: aktive Modusvorgabe fuer den Seam (memoryhooker-Default
#: waere der zurueckhaltendste "remember"-Modus). Ueber eine optionale
#: memoryhooker.toml im Datenverzeichnis ueberschreibbar.
DEFAULT_MODE = "remember+search"

#: Contract-Symbole (Submodul.Attribut), die das externe Modul bereitstellen
#: muss (fail-closed). Die Symbole liegen bewusst in Submodulen -- der
#: Top-Level-Namespace des Moduls ist minimal gehalten.
_REQUIRED_SYMBOLS = {
    "evaluate_prompt": ("modes", "evaluate_prompt"),
    "session_start_message": ("modes", "session_start_message"),
    "SessionState": ("state", "SessionState"),
    "Hit": ("protocol", "Hit"),
    "load_config": ("config", "load_config"),
    "default_config": ("config", "default_config"),
}

_AUDIT_FILENAME = "memoryhooker_audit.jsonl"


def external_memoryhooker_available() -> bool:
    """True, wenn das Modul installiert ist UND kein Rollback-Schalter gesetzt ist."""
    if os.environ.get(ROLLBACK_ENV, "").strip().lower() in _OFF_VALUES:
        return False
    try:
        return importlib.util.find_spec(MEMORYHOOKER_MODULE) is not None
    except (ImportError, ValueError):
        return False


def _bach_db_path(db_path: Optional[str | Path] = None) -> Path:
    """Kanonische BACH-DB (hub/bach_paths.py), falls nichts anderes vorgegeben."""
    if db_path:
        return Path(db_path).expanduser()
    try:
        from .bach_paths import BACH_DB
        return Path(BACH_DB)
    except Exception:
        return Path.home() / ".bach" / "bach.db"


class BachMemoryBackend:
    """Read-only-MemoryBackend-Adapter gegen BACHs Memory-Tabellen.

    Erfuellt memoryhookers MemoryBackend-Protocol (search/available) gegen
    BACH_DB -- geoeffnet ausschliesslich via `mode=ro` (gardener/usmc-Contract
    des Moduls: "never write"). Ranking uebernimmt BACHs assoziative
    Termmatch-Semantik (hub/memory.py::_calculate_relevance) kombiniert mit
    dem Curation-Signal der Zeile (Fakt-Konfidenz, Lesson-Severity,
    Working-Note-Basiswert), normalisiert auf (0, 1] wie Hit.rank verlangt.
    """

    _WORKING_BASE = 0.4  # Working-Notes sind unkuratiert

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = _bach_db_path(db_path)

    # -- MemoryBackend-Protocol ------------------------------------------

    def available(self) -> bool:
        """True, wenn mind. eine Memory-Tabelle existiert und Zeilen hat."""
        if not self.db_path.exists():
            return False
        try:
            conn = self._ro_conn()
        except sqlite3.Error:
            return False
        try:
            for table in ("memory_facts", "memory_lessons", "memory_working"):
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                except sqlite3.Error:
                    continue
                if row and row[0]:
                    return True
            return False
        finally:
            conn.close()

    def search(self, query: str, limit: int = 5) -> list:
        """Assoziative Termmatch-Suche ueber alle Memory-Tabellen (read-only).

        Liefert memoryhooker.Hit-Objekte mit rank in (0, 1].
        """
        try:
            from memoryhooker.protocol import Hit  # Symbol im Seam-Contract geprueft
        except ImportError:
            return []
        keywords = [k.lower() for k in query.split() if len(k) >= 3]
        if not keywords:
            return []
        if not self.db_path.exists():
            return []
        try:
            conn = self._ro_conn()
        except sqlite3.Error:
            return []
        try:
            scored: list[tuple[float, str, str, dict[str, Any]]] = []
            scored.extend(self._score_facts(conn, keywords))
            scored.extend(self._score_lessons(conn, keywords))
            scored.extend(self._score_working(conn, keywords))
        finally:
            conn.close()
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for rank, text, source, meta in scored[:max(1, limit)]:
            try:
                hits.append(Hit(text=text, source=source, rank=rank, meta=meta))
            except TypeError:
                continue
        return hits

    # -- interne Scoring-Helfer ------------------------------------------

    def _ro_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5.0)

    @staticmethod
    def _term_ratio(text: str, keywords: list[str]) -> float:
        low = text.lower()
        matched = sum(1 for kw in keywords if kw in low)
        return matched / len(keywords) if matched else 0.0

    def _rank(self, term_ratio: float, curation: float) -> float:
        """Termmatch x Curation, normalisiert auf (0, 1] (usmc-Backend-Muster)."""
        if term_ratio <= 0.0:
            return 0.0
        raw = 0.4 * term_ratio + 0.6 * max(0.0, min(1.0, curation))
        return max(0.05, min(1.0, raw))

    def _score_facts(self, conn, keywords):
        rows = []
        try:
            for rowid, key, value, conf in conn.execute(
                "SELECT rowid, key, value, COALESCE(confidence, 0.5) FROM memory_facts"
            ):
                text = f"{key}: {value}"
                ratio = self._term_ratio(text, keywords)
                if ratio <= 0.0:
                    continue
                try:
                    curation = float(conf)
                except (TypeError, ValueError):
                    curation = 0.5
                rows.append((self._rank(ratio, curation), text, "bach:fact",
                             {"table": "memory_facts", "rowid": rowid}))
        except sqlite3.Error:
            pass
        return rows

    def _score_lessons(self, conn, keywords):
        rows = []
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_lessons)")}
            if not cols:
                return rows
            sql = "SELECT rowid, title, solution"
            if "severity" in cols:
                sql += ", COALESCE(severity, 'medium')"
            else:
                sql += ", 'medium'"
            if "is_active" in cols:
                sql += " FROM memory_lessons WHERE COALESCE(is_active, 1) = 1"
            else:
                sql += " FROM memory_lessons"
            sev_rank = {"critical": 1.0, "high": 0.9, "medium": 0.7, "low": 0.5, "info": 0.4}
            for rowid, title, solution, severity in conn.execute(sql):
                text = f"{title}: {solution}"
                ratio = self._term_ratio(text, keywords)
                if ratio <= 0.0:
                    continue
                curation = sev_rank.get(str(severity).lower(), 0.7)
                rows.append((self._rank(ratio, curation), text, "bach:lesson",
                             {"table": "memory_lessons", "rowid": rowid, "severity": severity}))
        except sqlite3.Error:
            pass
        return rows

    def _score_working(self, conn, keywords):
        rows = []
        try:
            sql = "SELECT rowid, content FROM memory_working"
            if self._has_column(conn, "memory_working", "is_active"):
                sql += " WHERE COALESCE(is_active, 1) = 1"
            for rowid, content in conn.execute(sql):
                ratio = self._term_ratio(content, keywords)
                if ratio <= 0.0:
                    continue
                rows.append((self._rank(ratio, self._WORKING_BASE), content, "bach:working",
                             {"table": "memory_working", "rowid": rowid}))
        except sqlite3.Error:
            pass
        return rows

    @staticmethod
    def _has_column(conn, table: str, column: str) -> bool:
        try:
            return column in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            return False


class ExternalMemoryHook:
    """In-process-Adapter: haengt memoryhooker an ChatRuntime.process.

    - SessionStates pro chat_id (in-memory; ChatRuntime-Prozesse sind
      sitzungslokal, der Cap/Cooldown-Guard wirkt pro Prozesslaufzeit).
    - Fail-soft: jede Exception in hook_context fuehrt zu None (keine
      Injektion), niemals zu einem Chat-Abbruch.
    - Fail-closed beim Laden: fehlt ein Contract-Symbol, bleibt der Adapter
      dauerhaft deaktiviert (eine Warnung).
    """

    def __init__(self, db_path: Optional[str | Path] = None,
                 config_path: Optional[str | Path] = None,
                 mode: Optional[str] = DEFAULT_MODE):
        resolved = {}
        missing = []
        for logical, (submodule, attr) in _REQUIRED_SYMBOLS.items():
            try:
                sub = importlib.import_module(f"{MEMORYHOOKER_MODULE}.{submodule}")
                resolved[logical] = getattr(sub, attr)
            except (ImportError, AttributeError):
                missing.append(f"{submodule}.{attr}")
        if missing:
            raise RuntimeError(
                f"memoryhooker-Contract verletzt, fehlende Symbole: {missing}"
            )
        self._mod = resolved

        cfg = None
        path = Path(config_path).expanduser() if config_path else self._default_config_path(db_path)
        if path and path.exists():
            try:
                cfg = self._mod["load_config"](path)
            except Exception as e:  # kaputte Nutzer-TOML -> Defaults
                log.warning("memoryhooker.toml unlesbar (%s), nutze Defaults", e)
                cfg = None
        if cfg is None:
            cfg = self._mod["default_config"]()
        if mode:
            cfg = replace(cfg, mode=replace(cfg.mode, active=mode))
        try:
            cfg.validate()
        except Exception as e:
            log.warning("memoryhooker-Config ungueltig (%s), nutze Defaults", e)
            cfg = self._mod["default_config"]()
        self._config = cfg

        self.backend = BachMemoryBackend(db_path=db_path)
        self._states: dict[str, Any] = {}
        self.audit_path = self.backend.db_path.parent / _AUDIT_FILENAME

    @staticmethod
    def _default_config_path(db_path) -> Optional[Path]:
        base = _bach_db_path(db_path).parent
        return base / "memoryhooker.toml"

    # -- Hook-Pfad ---------------------------------------------------------

    def hook_context(self, prompt: str, chat_id: str) -> Optional[str]:
        """Liefert MemoryHooker-Kontext fuer einen Prompt oder None.

        Ruft session_start_message (einmalig) + evaluate_prompt auf und
        schreibt den Audit-Trail fuer jede tatsaechliche Injektion.
        """
        if not external_memoryhooker_available():
            return None
        state = self._states.get(chat_id)
        if state is None:
            state = self._states[chat_id] = self._mod["SessionState"]()
        parts = []
        try:
            start = self._mod["session_start_message"](self.backend, state)
            if start:
                parts.append(start)
            evaluated = self._mod["evaluate_prompt"](prompt, self._config, self.backend, state)
            if evaluated:
                parts.append(evaluated)
        except Exception as e:
            log.warning("memoryhooker hook fehlgeschlagen (fail-soft): %s", e)
            return None
        if not parts:
            return None
        message = "\n\n".join(parts)
        self._audit(chat_id, message)
        return message

    def _audit(self, chat_id: str, message: str) -> None:
        """JSONL-Audit-Trail fuer jede Kontextinjektion (Plan Stufe 6)."""
        try:
            entry = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "chat_id": chat_id,
                "mode": self._config.mode.active,
                "chars": len(message),
                "message": message[:200],
            }
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("memoryhooker-Audit nicht schreibbar: %s", e)


_shared_hook: Optional["ExternalMemoryHook"] = None
_shared_lock = threading.Lock()


def get_shared_memory_hook(db_path: Optional[str | Path] = None
                           ) -> Optional["ExternalMemoryHook"]:
    """Prozessweit geteilte Adapter-Instanz (Guard gegen Doppelinstanziierung)."""
    global _shared_hook
    if _shared_hook is not None:
        return _shared_hook
    with _shared_lock:
        if _shared_hook is not None:
            return _shared_hook
        if not external_memoryhooker_available():
            return None
        try:
            _shared_hook = ExternalMemoryHook(db_path=db_path)
        except Exception as e:
            log.warning("memoryhooker-Seam fail-closed: %s", e)
            return None
        return _shared_hook


def reset_shared_memory_hook() -> None:
    """Nur fuer Tests: geteilten Adapter verwerfen."""
    global _shared_hook
    with _shared_lock:
        _shared_hook = None