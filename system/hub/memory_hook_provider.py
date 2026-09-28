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
(ChatRuntime._get_bach_context) bleibt bestehen; er ueberspringt nur die
Injektoren, die dieser Seam nachweislich uebernimmt (handled_injectors, S3 von
T-20260920-823767362): Strategy (source='strategy', Seed: Migration 044),
Context (alle uebrigen Quellen als eine Gruppe, nur mit
BACH_CONTEXT_TRIGGERS_DB=1, Sichtung: Migration 045) und Tool-Warn
(source='tool_warn', Seed: Migration 046); im CLI (bach.py _run_injectors)
zusaetzlich Between (source='between', Seed: Migration 047, geprueft gegen
'<command> <operation>'). Die BACH-Schalter
(bach inject toggle, config.json "injectors") gelten weiter: ChatRuntime
reicht abgeschaltete Injektoren als disabled durch. Rueckweg je Injektor:
BACH_LEGACY_INJECTORS=strategy,context,tool_warn,between (kommagetrennt) oder der
Gesamtschalter oben.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import re
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

#: Rueckweg je Injektor (S3): diese Injektoren bleiben im BACH-Altpfad.
LEGACY_INJECTORS_ENV = "BACH_LEGACY_INJECTORS"

#: Injektoren, die der Seam uebernimmt, mit BACHs bisherigem Cooldown in
#: Sekunden (tools/injectors.py CooldownManager.DEFAULT_COOLDOWNS).
HOOKER_INJECTORS = {"strategy": 120, "context": 60, "tool_warn": 300, "between": 180}

#: Nur im CLI-Pfad: Between prueft den Befehl ("task done"), nie einen Prompt.
CLI_ONLY_INJECTORS = frozenset({"between"})

#: Sitzungszustand des CLI-Pfads (jeder bach-Aufruf ist ein neuer Prozess;
#: wie data/.injector_cooldowns im Altpfad muessen Cooldowns ueberdauern).
_CLI_STATE_FILENAME = "memoryhooker_cli_state.json"

#: BACH-Konfigurationsschalter je Injektor (tools/injectors.py InjectorConfig);
#: Tool-Warn haengt dort am context_injector-Schalter.
INJECTOR_SWITCHES = {"strategy": "strategy_injector", "context": "context_injector",
                     "tool_warn": "context_injector", "between": "between_injector"}

#: Context liest context_triggers nur mit diesem Schalter (wie der
#: ContextInjector in tools/injectors.py, S3 Einheit 2a).
CONTEXT_TRIGGERS_DB_ENV = "BACH_CONTEXT_TRIGGERS_DB"
_ON_VALUES = {"1", "true", "yes", "on"}

#: Tabellenquellen, die der ContextInjector als eine Liste las.
CONTEXT_SOURCES = ["manual", "theme", "lesson", "tool", "workflow", "skill"]

#: CLI-Hinweise, die der Chat im api-Modus nicht zeigt (gleich
#: bach_api._CLI_PATTERN, dort filtert der Altpfad nach der Auswahl).
_CLI_PATTERN = re.compile(r'bach\s+\w+|--\w+|python\s+\w+\.py')


def _context_triggers_db_on() -> bool:
    return os.environ.get(CONTEXT_TRIGGERS_DB_ENV, "").strip().lower() in _ON_VALUES


def _legacy_injectors() -> set:
    raw = os.environ.get(LEGACY_INJECTORS_ENV, "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


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
            has_consolidation = False
            try:
                has_consolidation = bool(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name='memory_consolidation'"
                    ).fetchone()
                )
            except sqlite3.Error:
                has_consolidation = False

            if has_consolidation:
                query = """
                    SELECT f.rowid, f.key, f.value, COALESCE(f.confidence, 0.5)
                    FROM memory_facts f
                    LEFT JOIN memory_consolidation mc
                      ON mc.source_table = 'memory_facts' AND mc.source_id = f.rowid
                    WHERE (mc.status IS NULL OR mc.status != 'forgotten')
                      AND (f.confidence IS NULL OR f.confidence > 0.0)
                """
            else:
                query = """
                    SELECT rowid, key, value, COALESCE(confidence, 0.5)
                    FROM memory_facts
                    WHERE (confidence IS NULL OR confidence > 0.0)
                """

            for rowid, key, value, conf in conn.execute(query):
                text = f"{key}: {value}"
                ratio = self._term_ratio(text, keywords)
                if ratio <= 0.0:
                    continue
                try:
                    curation = float(conf)
                except (TypeError, ValueError):
                    curation = 0.5
                if curation <= 0.0:
                    continue
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

    def triggers(self, sources: list, agent_id: str = "default") -> list:
        """context_triggers-Regeln der Quellen (read-only, Leseregel im Modul)."""
        try:
            from memoryhooker.triggers import read_context_triggers
        except ImportError:
            return []
        if not sources or not self.db_path.exists():
            return []
        try:
            conn = self._ro_conn()
        except sqlite3.Error:
            return []
        try:
            return read_context_triggers(conn, list(sources), agent_id)
        finally:
            conn.close()

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
        # Optional (memoryhooker mit Trigger-Injektor): fehlt es, uebernimmt
        # der Seam keinen Injektor und BACH bleibt beim Altpfad.
        try:
            self._evaluate_triggers = importlib.import_module(
                f"{MEMORYHOOKER_MODULE}.triggers").evaluate_triggers
        except (ImportError, AttributeError):
            self._evaluate_triggers = None

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
        triggers = getattr(cfg, "triggers", None)
        # Gruppen/Praefixe/accept kamen mit memoryhooker be9fefe; aeltere
        # Staende koennen Context nicht paritaetisch abbilden.
        self._groups_supported = triggers is not None and hasattr(triggers, "groups")
        if triggers is not None and not triggers.sources:
            extra = {}
            if self._groups_supported:
                extra = dict(
                    groups={"context": list(CONTEXT_SOURCES), **triggers.groups},
                    prefixes={"context": "[KONTEXT] ", **triggers.prefixes},
                    once_per_session=triggers.once_per_session or ["theme"],
                )
            cfg = replace(cfg, triggers=replace(
                triggers, sources=list(HOOKER_INJECTORS),
                cooldowns={**HOOKER_INJECTORS, **triggers.cooldowns}, **extra))
        self._config = cfg

        self.backend = BachMemoryBackend(db_path=db_path)
        self._warned: set = set()
        self._states: dict[str, Any] = {}
        self.audit_path = self.backend.db_path.parent / _AUDIT_FILENAME

    @staticmethod
    def _default_config_path(db_path) -> Optional[Path]:
        base = _bach_db_path(db_path).parent
        return base / "memoryhooker.toml"

    # -- Hook-Pfad ---------------------------------------------------------

    def handled_injectors(self) -> frozenset:
        """Injektoren, die dieser Seam gerade wirklich uebernimmt.

        Nur Quellen mit mindestens einer aktiven Regel in context_triggers --
        fehlt der Seed, bleibt BACH beim Altpfad statt stumm zu werden.
        """
        if self._evaluate_triggers is None or not external_memoryhooker_available():
            return frozenset()
        legacy = _legacy_injectors()
        cfg = self._config.triggers
        handled = set()
        for key in cfg.sources:
            if key in legacy:
                continue
            if key == "context" and not (self._groups_supported and _context_triggers_db_on()):
                continue
            table_sources = getattr(cfg, "groups", {}).get(key, [key])
            try:
                if self.backend.triggers(table_sources, agent_id=cfg.agent_id):
                    handled.add(key)
            except Exception as e:
                if key not in self._warned:
                    self._warned.add(key)
                    log.warning("memoryhooker-Seam: Regeln fuer %s nicht lesbar (%s: %s) -- Altpfad",
                                key, type(e).__name__, e)
        return frozenset(handled)

    def hook_context(self, prompt: str, chat_id: str,
                     cli_hints: bool = True,
                     disabled: frozenset = frozenset()) -> Optional[str]:
        """Liefert MemoryHooker-Kontext fuer einen Prompt oder None.

        Ruft session_start_message (einmalig) + evaluate_prompt auf und
        schreibt den Audit-Trail fuer jede tatsaechliche Injektion.
        cli_hints=False (Chat im api-Modus): Trigger-Hinweise mit CLI-Befehlen
        werden VOR der Auswahl uebersprungen -- bewusst anders als der
        Altpfad, der sie nach der Auswahl verwarf und dabei den Cooldown
        verbrauchte (Positivmessung 2026-09-26). Das gilt nur fuer Kontext-
        Hinweise; Strategy und Tool-Warn zeigte auch der Altpfad im Chat.
        disabled: in BACH abgeschaltete Injektoren -- auch hier stumm.
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
            handled = self.handled_injectors() - set(disabled) - CLI_ONLY_INJECTORS
            parts.extend(self._trigger_hints(prompt, state, handled, cli_hints=cli_hints))
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

    def _trigger_hints(self, text: str, state, keys, cli_hints: bool = True) -> list:
        """Trigger-Hinweise der Injektoren ``keys`` in Konfigurationsreihenfolge."""
        if not keys:
            return []
        cfg = replace(self._config, triggers=replace(
            self._config.triggers,
            sources=[s for s in self._config.triggers.sources if s in keys]))
        kwargs = {}
        fired = []
        if self._groups_supported:
            kwargs["fired"] = fired
            if not cli_hints:
                kwargs["accept"] = lambda rule: (
                    rule.source not in CONTEXT_SOURCES
                    or not _CLI_PATTERN.search(rule.hint))
        hints = self._evaluate_triggers(text, cfg, self.backend, state, **kwargs)
        # usage_count zaehlte der Altpfad nur fuer den ContextInjector.
        self._mark_usage([r.rule_id for r in fired
                          if r.source in CONTEXT_SOURCES and r.rule_id is not None])
        return list(hints)

    def cli_injections(self, output: str, last_command: str,
                       disabled: frozenset = frozenset()) -> tuple:
        """CLI-Pfad (bach.py _run_injectors): (Hinweise zur Ausgabe, Between).

        Wie der Altpfad: Strategy/Context/Tool-Warn pruefen die Befehls-
        AUSGABE, Between den Befehl selbst. Der Zustand liegt in einer Datei
        neben der BACH-DB, weil jeder Aufruf ein neuer Prozess ist. Fail-soft.
        """
        if not external_memoryhooker_available():
            return [], []
        handled = self.handled_injectors() - set(disabled)
        if not handled:
            return [], []
        path = self.backend.db_path.parent / _CLI_STATE_FILENAME
        try:
            state = self._mod["SessionState"].load(path)
            before = self._trigger_hints(output or "", state, handled - CLI_ONLY_INJECTORS)
            between = self._trigger_hints(last_command or "", state, handled & CLI_ONLY_INJECTORS)
            state.save(path)
        except Exception as e:
            log.warning("memoryhooker CLI-Pfad fehlgeschlagen (fail-soft): %s", e)
            return [], []
        return before, between

    def _mark_usage(self, rule_ids: list) -> None:
        """usage_count/last_used der gefeuerten Kontext-Regeln (wie der Altpfad).

        Der einzige Schreibzugriff dieses Seams; das Backend selbst bleibt
        read-only. Fehler sind nie ein Abbruch.
        """
        if not rule_ids:
            return
        try:
            conn = sqlite3.connect(str(self.backend.db_path), timeout=5.0)
            try:
                conn.executemany(
                    "UPDATE context_triggers SET usage_count = usage_count + 1,"
                    " last_used = datetime('now') WHERE id = ?",
                    [(rule_id,) for rule_id in rule_ids])
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as e:
            log.warning("context_triggers-Nutzung nicht gezaehlt: %s", e)

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