# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
BACH Library API - Programmatischer Zugriff ohne CLI
=====================================================

Drei Zugriffsmodi:
  1. Bibliothek-Modus:  from bach_api import task; task.list()
  2. Gemischter Modus:  session.startup() + API + session.shutdown()
  3. Session-Modus:     python bach.py --startup (klassische CLI)

Nutzung:
    from bach_api import session, task, memory, agent, prompt, partner, tools, injector

    # Session-Lifecycle (optional -- Modus 2)
    session.startup(partner="claude", mode="silent")
    # ... arbeiten ...
    session.shutdown("Zusammenfassung")

    # Kern-Handler
    task.add("Aufgabe", "--priority", "P3")
    task.list()
    task.done(42)
    memory.write("Notiz")
    memory.status()

    # Domain-Handler
    steuer.status()
    agent.list()
    prompt.list()
    partner.list()
    partner.delegate("Recherche", "--to=gemini")
    tools.list()
    tools.search("ocr")

    # Kognitive Injektoren
    injector.process("ich bin blockiert")
    injector.check_between("task done 42")
    injector.set_mode("api")                 # CLI-Hinweise filtern

    # Raw-Zugriff (beliebiger der 109+ Handler)
    app().execute("gesundheit", "termine", ["--upcoming"])

Verfuegbare Module:
    session, task, memory, backup, steuer, lesson, status,
    agent, agents, prompt, partner, logs, msg, tools, help, update,
    injector, db, app
"""

import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# system/ Verzeichnis ermitteln
_SYSTEM_DIR = Path(__file__).parent

# sys.path sicherstellen
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

# Lazy App-Singleton
_app = None


def get_app():
    """Gibt die App-Singleton-Instanz zurueck."""
    global _app
    if _app is None:
        from core.app import App
        _app = App(_SYSTEM_DIR)
    return _app


class _HandlerProxy:
    """Proxy fuer bequemen Zugriff auf Handler-Operationen.

    Ermoeglicht: task.add("...") statt app.execute("task", "add", ["..."])
    """

    def __init__(self, handler_name: str):
        self._name = handler_name

    def _execute(self, operation: str, *args) -> tuple[bool, Any]:
        app = get_app()
        str_args = [str(a) for a in args]
        return app.execute(self._name, operation, str_args)

    def raw(self, operation: str = "", *args) -> tuple[bool, Any]:
        """Fuehrt einen Handler-Aufruf im Legacy-Format aus."""
        return self._execute(operation, *args)

    def available_operations(self) -> list[str]:
        """Listet discoverbare Operationen fuer IDEs und Agenten auf."""
        handler = get_app().get_handler(self._name)
        if not handler or not hasattr(handler, "get_operations"):
            return []

        operations = []
        for operation in handler.get_operations().keys():
            if isinstance(operation, str) and operation and operation.isidentifier():
                operations.append(operation)
        return sorted(set(operations))

    def __dir__(self) -> list[str]:
        names = set(super().__dir__())
        names.update(self.available_operations())
        names.update({"available_operations", "raw"})
        return sorted(names)

    def __getattr__(self, operation: str):
        """Jeder Attributzugriff wird zu einem Handler-Aufruf."""
        def caller(*args):
            success, message = self._execute(operation, *args)
            if not success:
                print(f"[FEHLER] {message}")
            return message
        return caller

    def __call__(self, operation: str = "", *args):
        """Direkter Aufruf: task("list")"""
        return self.raw(operation, *args)


class BachAPIError(RuntimeError):
    """Fehler fuer die strukturierte bach_api."""


def _resolve_db_path() -> Path:
    """Fragt den DB-Pfad bei der zentralen Registry ab.

    Der Notfall-Fallback zeigt bewusst auf die kanonische lokale DB und NICHT
    mehr auf ``_SYSTEM_DIR/data/bach.db``: Letzteres ist die veraltete Kopie im
    OneDrive-Ordner. Wer sie oeffnet, arbeitet still auf altem Datenstand.
    """
    try:
        from hub.bach_paths import BACH_DB
        return BACH_DB
    except ImportError:
        return Path.home() / ".bach" / "bach.db"


class _DBBackedProxy(_HandlerProxy):
    """Hilfsbasis fuer strukturierte Wrapper mit direktem DB-Lesezugriff."""

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_resolve_db_path()))
        conn.row_factory = sqlite3.Row
        return conn


class _TaskProxy(_DBBackedProxy):
    """Strukturierter Zugriff auf Task-Operationen mit Raw-Fallback."""

    def add(
        self,
        title: str,
        *args,
        priority: str = "P3",
        description: str | None = None,
        category: str | None = "general",
    ) -> dict[str, Any]:
        cli_priority = priority
        cli_description = description
        cli_category = category

        i = 0
        while i < len(args):
            arg = str(args[i])
            if arg in ("--priority", "-p") and i + 1 < len(args):
                cli_priority = str(args[i + 1]).upper()
                i += 2
            elif arg.startswith("--priority="):
                cli_priority = arg.split("=", 1)[1].upper()
                i += 1
            elif arg in ("--description", "-d") and i + 1 < len(args):
                cli_description = str(args[i + 1])
                i += 2
            elif arg.startswith("--description="):
                cli_description = arg.split("=", 1)[1]
                i += 1
            elif arg in ("--category", "-c") and i + 1 < len(args):
                cli_category = str(args[i + 1])
                i += 2
            elif arg.startswith("--category="):
                cli_category = arg.split("=", 1)[1]
                i += 1
            else:
                i += 1

        raw_args = [title, "--priority", cli_priority]
        if cli_description:
            raw_args.extend(["--description", cli_description])
        if cli_category:
            raw_args.extend(["--category", cli_category])

        success, message = self.raw("add", *raw_args)
        if not success:
            raise BachAPIError(message)

        match = re.search(r"Task\s+(\d+)\s+erstellt", str(message))
        if match:
            task_data = self.show(int(match.group(1)))
        else:
            rows = self.list(status="all", filter_text=title, limit=1)
            if not rows:
                raise BachAPIError(f"Task erstellt, aber nicht wiedergefunden: {message}")
            task_data = rows[0]

        task_data["_message"] = str(message)
        return task_data

    def list(
        self,
        *args,
        status: str | None = "pending",
        filter_text: str | None = None,
        assigned_to: str | None = None,
        unassigned: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        status_filter = status
        title_filter = filter_text
        assigned_filter = assigned_to.upper() if assigned_to else None
        unassigned_only = unassigned

        i = 0
        while i < len(args):
            arg = str(args[i])
            if arg in ("all", "done", "pending", "open", "blocked"):
                status_filter = None if arg == "all" else arg
            elif arg.startswith("--filter="):
                title_filter = arg.split("=", 1)[1]
            elif arg == "--filter" and i + 1 < len(args):
                title_filter = str(args[i + 1])
                i += 1
            elif arg.startswith("--assigned="):
                assigned_filter = arg.split("=", 1)[1].upper()
            elif arg == "--assigned" and i + 1 < len(args):
                assigned_filter = str(args[i + 1]).upper()
                i += 1
            elif arg == "--unassigned":
                unassigned_only = True
            i += 1

        conditions = []
        params: list[Any] = []
        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        if title_filter:
            conditions.append("title LIKE ?")
            params.append(f"%{title_filter}%")
        if assigned_filter:
            conditions.append("(assigned_to = ? OR delegated_to = ?)")
            params.extend([assigned_filter, assigned_filter])
        if unassigned_only:
            conditions.append(
                "(assigned_to IS NULL OR assigned_to = '') "
                "AND (delegated_to IS NULL OR delegated_to = '')"
            )

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = (
            "SELECT id, priority, title, status, category, description, assigned_to, "
            "delegated_to, depends_on, created_at, completed_at, updated_at "
            "FROM tasks "
            f"WHERE {where_clause} "
            "ORDER BY priority, id"
        )
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_task(conn, row) for row in rows]

    def show(self, task_id: int | str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
            if not row:
                raise BachAPIError(f"Task {task_id} nicht gefunden")
            return self._row_to_task(conn, row)

    def _row_to_task(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        task_data = dict(row)
        task_data["partner"] = task_data.get("assigned_to") or task_data.get("delegated_to") or ""
        task_data["is_blocked_by_dep"] = self._is_blocked_by_dependency(
            conn,
            task_data.get("depends_on"),
        )
        return task_data

    def _is_blocked_by_dependency(
        self,
        conn: sqlite3.Connection,
        depends_on: str | None,
    ) -> bool:
        if not depends_on:
            return False

        dep_ids = [int(value.strip()) for value in str(depends_on).split(",") if value.strip()]
        if not dep_ids:
            return False

        placeholders = ",".join("?" for _ in dep_ids)
        unfinished = conn.execute(
            f"SELECT COUNT(*) FROM tasks WHERE id IN ({placeholders}) AND status != 'done'",
            dep_ids,
        ).fetchone()[0]
        return unfinished > 0


class _MemoryProxy(_DBBackedProxy):
    """Strukturierter Zugriff auf Working-Memory mit Raw-Fallback."""

    def write(
        self,
        text: str,
        *,
        entry_type: str = "note",
        priority: int | None = None,
        tags: str | list[str] | None = None,
        expires_at: str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat()
        tag_value: str | None
        if isinstance(tags, (list, tuple, set)):
            tag_value = ",".join(str(tag) for tag in tags)
        else:
            tag_value = tags

        payload = {
            "type": entry_type,
            "content": text,
            "created_at": now,
            "updated_at": now,
            "is_active": 1 if is_active else 0,
        }
        if priority is not None:
            payload["priority"] = priority
        if tag_value:
            payload["tags"] = tag_value
        if expires_at:
            payload["expires_at"] = expires_at

        row_id = db.insert("memory_working", payload)
        return self._get_entry(row_id)

    def read(
        self,
        limit: int = 10,
        *,
        entry_type: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: list[Any] = []

        if active_only:
            conditions.append("is_active = 1")
        if entry_type:
            conditions.append("type = ?")
            params.append(entry_type)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = (
            "SELECT id, type, content, priority, tags, created_at, updated_at, "
            "expires_at, is_active "
            "FROM memory_working "
            f"WHERE {where_clause} "
            "ORDER BY created_at DESC "
            "LIMIT ?"
        )
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def status(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "working": conn.execute(
                    "SELECT COUNT(*) FROM memory_working WHERE is_active = 1"
                ).fetchone()[0],
                "facts": conn.execute(
                    "SELECT COUNT(*) FROM memory_facts"
                ).fetchone()[0],
                "lessons": conn.execute(
                    "SELECT COUNT(*) FROM memory_lessons WHERE is_active = 1"
                ).fetchone()[0],
                "sessions": conn.execute(
                    "SELECT COUNT(*) FROM memory_sessions"
                ).fetchone()[0],
                "confidence_high": conn.execute(
                    "SELECT COUNT(*) FROM memory_facts WHERE confidence >= 0.8"
                ).fetchone()[0],
                "confidence_mid": conn.execute(
                    "SELECT COUNT(*) FROM memory_facts WHERE confidence >= 0.5 "
                    "AND confidence < 0.8"
                ).fetchone()[0],
                "confidence_low": conn.execute(
                    "SELECT COUNT(*) FROM memory_facts WHERE confidence < 0.5 "
                    "AND confidence IS NOT NULL"
                ).fetchone()[0],
            }

    def _get_entry(self, entry_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, type, content, priority, tags, created_at, updated_at, "
                "expires_at, is_active FROM memory_working WHERE id = ?",
                (entry_id,),
            ).fetchone()
            if not row:
                raise BachAPIError(f"Memory-Eintrag {entry_id} nicht gefunden")
            return dict(row)


# --- Session-Management ---

class _SessionProxy:
    """Ergonomische API fuer Session-Lifecycle (Startup/Shutdown).

    Ersetzt: python bach.py --startup --partner=claude --mode=silent
    Durch:   session.startup(partner="claude", mode="silent")
    """

    def startup(self, partner: str = "claude", mode: str = "silent",
                quick: bool = False) -> str:
        """Startet eine BACH-Session.

        Fuehrt das komplette Startprotokoll aus:
        - Partner ein-stempeln (Presence)
        - Vorherige Session des Partners auto-schliessen
        - Memory-Check, Task-Uebersicht, Nachrichten
        - Injektoren aktivieren

        Args:
            partner: Partner-ID (claude, gemini, user, ...)
            mode: Startup-Modus (silent, gui, text, dual)
            quick: True = ohne Directory-Scan (schneller)

        Returns:
            Startup-Report als String
        """
        a = get_app()
        operation = "quick" if quick else "run"
        args = [f"--partner={partner}", f"--mode={mode}"]
        success, message = a.execute("startup", operation, args)
        return message

    def shutdown(self, summary: str = None, partner: str = "claude",
                 mode: str = "complete") -> str:
        """Beendet eine BACH-Session.

        Fuehrt das Shutdown-Protokoll aus:
        - Directory-Scan (Aenderungen erkennen)
        - Session in DB speichern
        - Auto-Snapshot bei vielen Aenderungen
        - Memory-Konsolidierung
        - Partner aus-stempeln

        Args:
            summary: Session-Zusammenfassung (optional, Autolog-Fallback)
            partner: Partner-ID
            mode: complete, quick, oder emergency

        Returns:
            Shutdown-Report als String
        """
        a = get_app()
        # Partner-Flag muss VOR dem Summary stehen, da der Handler
        # args durchsucht und den Rest als Summary joined
        args = [f"--partner={partner}"]
        if summary:
            # Summary als separates Argument (Handler joined mit " ")
            args.extend(summary.split())
        success, message = a.execute("shutdown", mode, args)
        return message

    def shutdown_quick(self, summary: str = None,
                       partner: str = "claude") -> str:
        """Schneller Shutdown ohne Directory-Scan."""
        return self.shutdown(summary=summary, partner=partner, mode="quick")

    def shutdown_emergency(self, note: str = None,
                           partner: str = "claude") -> str:
        """Notfall-Shutdown - nur Working Memory sichern."""
        return self.shutdown(summary=note, partner=partner, mode="emergency")


# --- Convenience-Module ---

# Session-Lifecycle
session = _SessionProxy()

# Handler-Proxies (haeufigste)
task = _TaskProxy("task")
memory = _MemoryProxy("memory")
backup = _HandlerProxy("backup")
steuer = _HandlerProxy("steuer")
lesson = _HandlerProxy("lesson")
status = _HandlerProxy("status")
agent = _HandlerProxy("agent")
agents = _HandlerProxy("agents")
prompt = _HandlerProxy("prompt")
partner = _HandlerProxy("partner")
logs = _HandlerProxy("logs")
msg = _HandlerProxy("msg")
tools = _HandlerProxy("tools")
help = _HandlerProxy("help")
update = _HandlerProxy("update")
email = _HandlerProxy("email")

# App-Instanz fuer direkten Zugriff
app = get_app


# --- Safe DB Access Layer ---

class _DBProxy:
    """Validierter DB-Zugriff: fuehlt sich wie SQL an, ist aber sicher.

    Beispiel:
        from bach_api import db
        db.select("tasks", where={"status": "pending"})
        db.update("bach_experts", {"persona": "Neu"}, where={"name": "mr_tiktak"})
        db.insert("tasks", {"title": "Aufgabe", "priority": "high"})
        db.delete("tasks", where={"id": 42})
    """

    def __init__(self):
        self._safe_db = None

    def _get(self):
        if self._safe_db is None:
            from core.safe_db import SafeDB
            self._safe_db = SafeDB(_resolve_db_path(), partner="bach_api")
        return self._safe_db

    def set_partner(self, partner: str):
        """Setzt den Partner-Namen fuer Audit-Log."""
        self._get().partner = partner

    def select(self, table, columns=None, where=None, order_by=None, limit=None):
        return self._get().select(table, columns, where, order_by, limit)

    def insert(self, table, data):
        return self._get().insert(table, data)

    def update(self, table, data, where):
        return self._get().update(table, data, where)

    def delete(self, table, where):
        return self._get().delete(table, where)

    def count(self, table, where=None):
        return self._get().count(table, where)

    def exists(self, table, where):
        return self._get().exists(table, where)

    def tables(self):
        return self._get().tables()

    def schema(self, table):
        return self._get().schema(table)


db = _DBProxy()

# Hook-Framework (Lifecycle-Events)
try:
    from core.hooks import hooks
except ImportError:
    hooks = None

# Plugin-API (Dynamische Erweiterung)
try:
    from core.plugin_api import plugins
except ImportError:
    plugins = None


# --- Injector-Integration ---

# Pattern: "bach befehl" oder "--befehl" CLI-Hinweise erkennen
_CLI_PATTERN = re.compile(
    r'bach\s+\w+'           # "bach steuer status", "bach task list"
    r'|--\w+'               # "--help tasks", "--memory"
    r'|python\s+\w+\.py'    # "python injectors.py"
)


class _InjectorProxy:
    """Proxy fuer Injector-Zugriff ueber die Library API.

    Alle 6 Injektoren verfuegbar. Optional CLI-Hinweise filterbar.

    Beispiel:
        from bach_api import injector
        hints = injector.process("ich bin blockiert bei diesem bug")
        # → ['[STRATEGIE] Fehler sind wertvolle Informationen...']
    """

    def __init__(self):
        self._system = None
        self._mode = "cli"  # "cli" = alles, "api" = CLI-Hinweise gefiltert

    def _get_system(self):
        """Lazy-Init des InjectorSystem."""
        if self._system is None:
            sys.path.insert(0, str(_SYSTEM_DIR / "tools"))
            try:
                from injectors import InjectorSystem
                self._system = InjectorSystem(_SYSTEM_DIR)
            finally:
                sys.path.pop(0)
        return self._system

    def set_mode(self, mode: str):
        """Setzt den Modus: 'cli' (alles) oder 'api' (CLI-Hinweise gefiltert).

        Im API-Modus werden Kontext-Hinweise die CLI-Befehle enthalten
        (z.B. 'bach steuer status') herausgefiltert. Pfad-Hinweise und
        kognitive Strategien bleiben erhalten.
        """
        if mode in ("cli", "api"):
            self._mode = mode

    def _filter_cli(self, injections: list) -> list:
        """Filtert CLI-spezifische Hinweise im API-Modus."""
        if self._mode != "api":
            return injections
        result = []
        for inj in injections:
            # Strategy, Between, Time → immer behalten (kein CLI)
            if inj.startswith(("[STRATEGIE]", "[BETWEEN]", "[ZEIT]", "[AUFGABE")):
                result.append(inj)
            # Kontext-Hinweise: nur behalten wenn kein CLI-Befehl drin
            elif inj.startswith("[KONTEXT]"):
                if not _CLI_PATTERN.search(inj):
                    result.append(inj)
            # Tool-Hinweise: Pfade sind OK, CLI-Befehle rausfiltern
            elif inj.startswith("[TOOL"):
                # Tool-Reminder hat Pfade (tools/xyz.py) → behalten
                result.append(inj)
            else:
                result.append(inj)
        return result

    def process(self, text: str, context: dict = None) -> list:
        """Verarbeitet Text durch alle aktiven Injektoren.

        Args:
            text: Zu analysierender Text (z.B. User-Input, Task-Beschreibung)
            context: Optional - Zusaetzlicher Kontext

        Returns:
            Liste von Hinweisen (kann leer sein)
        """
        system = self._get_system()
        injections = system.process(text, context)
        return self._filter_cli(injections)

    def check_between(self, last_action: str, session_ending: bool = False):
        """Prueft ob Between-Task Quality-Check faellig ist.

        Gibt Erinnerung zurueck nach Task-Abschluss:
        'Testergebnis? Doku? Commit? Naechste Aufgabe?'

        Args:
            last_action: Beschreibung der letzten Aktion (z.B. "task done 42")
            session_ending: True wenn Session endet

        Returns:
            Reminder-String oder None
        """
        system = self._get_system()
        return system.check_between(last_action, session_ending)

    def tool_reminder(self):
        """Gibt einmalige Tool-Erinnerung fuer Session-Start zurueck.

        Listet verfuegbare Tool-Kategorien (OCR, Import, Domain-Handler, etc.)
        Wird nur beim ersten Aufruf zurueckgegeben, danach None.

        Returns:
            Tool-Uebersicht String oder None
        """
        system = self._get_system()
        return system.get_tool_reminder()

    def assign_task(self, max_minutes: int = 5):
        """Weist automatisch eine passende Aufgabe zu.

        Args:
            max_minutes: Maximale geschaetzte Dauer

        Returns:
            Tuple (success: bool, message: str)
        """
        system = self._get_system()
        return system.assign_task(max_minutes)

    def decompose(self, task_id: str):
        """Zerlegt grosse Aufgabe in Teilschritte.

        Args:
            task_id: ID der Aufgabe

        Returns:
            Tuple (success: bool, message: str)
        """
        system = self._get_system()
        return system.decompose_task(task_id)

    def time_check(self):
        """Gibt aktuelle Zeit + ungelesene Nachrichten zurueck.

        Returns:
            Zeit-Info String oder None (wenn Intervall nicht erreicht)
        """
        system = self._get_system()
        if system.config.is_enabled("time_injector"):
            return system.time_injector.check()
        return None

    def status(self):
        """Zeigt Status aller Injektoren (an/aus, Cooldown-Info).

        Returns:
            Status-String
        """
        system = self._get_system()
        return system.status()

    def toggle(self, injector_name: str):
        """Schaltet einzelnen Injektor an/aus.

        Args:
            injector_name: strategy_injector, context_injector,
                          time_injector, between_injector

        Returns:
            Tuple (success: bool, message: str)
        """
        system = self._get_system()
        return system.toggle(injector_name)


injector = _InjectorProxy()

__all__ = [
    "BachAPIError",
    "get_app",
    "session",
    "task",
    "memory",
    "backup",
    "steuer",
    "lesson",
    "status",
    "agent",
    "agents",
    "prompt",
    "partner",
    "logs",
    "msg",
    "tools",
    "help",
    "update",
    "email",
    "app",
    "db",
    "hooks",
    "plugins",
    "injector",
]
