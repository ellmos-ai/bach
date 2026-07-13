#!/usr/bin/env python3
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
BACH Launcher - Zentrales Command-Routing mit Multi-Access-Support
===================================================================

Der Launcher ist der zentrale Einstiegspunkt für ALLE Befehle:
  - CLI: python bach.py <cmd>
  - Telegram: Nachricht über Connector
  - Claude Code: Worker-Agent Task

Routing-Logik:
  1. Prüfe: Gibt es einen spezialisierten Agent für diesen Befehl?
     → JA: Delegate to Agent
     → NEIN: Direct Execute über Handler

  2. Source-Tracking: Merke woher der Befehl kam (CLI, Telegram, Claude)

  3. Response-Routing: Sende Antwort zurück über ursprünglichen Kanal

Usage:
    from core.launcher import Launcher

    launcher = Launcher(base_path)
    success, message = launcher.route(
        command="task",
        operation="add",
        args=["Neue Aufgabe"],
        source="telegram",
        user="YOUR_CHAT_ID"
    )

Autor: Claude Worker-Agent
Datum: 2026-02-14
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class Launcher:
    """Zentrales Command-Routing mit Multi-Access-Support."""

    # Agent-Delegation-Map: command → agent_name
    AGENT_DELEGATIONS = {
        "steuer": "steuer-agent",
        "research": "research-agent",
        "production": "production-agent",
        "entwickler": "entwickler-agent",
        "bewerbung": "bewerbungsexperte",
    }

    def __init__(self, base_path: Path = None):
        """
        Args:
            base_path: system/ Verzeichnis
        """
        if base_path is None:
            # Auto-detect: Dieses Modul liegt in system/core/launcher.py
            base_path = Path(__file__).parent.parent

        self.base_path = base_path
        self.db_path = BACH_DB

    def route(self,
              command: str,
              operation: str = "",
              args: List[str] = None,
              source: str = "cli",
              user: str = "user",
              dry_run: bool = False) -> Tuple[bool, str]:
        """
        Haupteinstiegspunkt: Routet Befehl an Agent oder Handler.

        Args:
            command: Handler-Name (z.B. "task", "steuer")
            operation: Operation (z.B. "add", "status")
            args: Argumente
            source: "cli", "telegram", "claude"
            user: User-ID oder "user"
            dry_run: Nur simulieren

        Returns:
            (success, message) Tuple
        """
        if args is None:
            args = []

        # Log the routing
        self._log_routing(command, operation, args, source, user)

        # 1. Prüfe: Gibt es Agent-Delegation?
        if command in self.AGENT_DELEGATIONS:
            agent_name = self.AGENT_DELEGATIONS[command]
            return self._delegate_to_agent(
                agent_name, operation, args, source, user, dry_run
            )

        # 2. Fallback: Direct Execute über Handler
        return self._execute_direct(command, operation, args, dry_run)

    def _delegate_to_agent(self,
                          agent_name: str,
                          operation: str,
                          args: List[str],
                          source: str,
                          user: str,
                          dry_run: bool) -> Tuple[bool, str]:
        """
        Delegiert an Agent-Instanz.

        Args:
            agent_name: Agent-Name (z.B. "steuer-agent")
            operation: Operation
            args: Argumente
            source: Zugangsquelle
            user: User-ID
            dry_run: Nur simulieren

        Returns:
            (success, message) Tuple
        """
        if dry_run:
            return True, f"[DRY] Würde delegieren an Agent '{agent_name}': {operation} {args}"

        try:
            from core.agent_runtime import get_agent

            # Agent-Instanz holen
            agent = get_agent(agent_name, self.base_path)
            if not agent:
                return False, f"[Launcher] Agent '{agent_name}' nicht gefunden oder nicht instanziierbar."

            # Agent verbinden (Dependencies laden)
            if not agent.connect():
                return False, f"[Launcher] Agent '{agent_name}' konnte nicht initialisiert werden."

            # Operation ausführen
            try:
                success, message = agent.execute(operation, args)

                # Source + User tracking in DB (wenn Task erstellt wurde)
                if success and "task" in operation.lower():
                    self._track_task_source(source, user)

                return success, message
            finally:
                agent.disconnect()

        except Exception as e:
            return False, f"[Launcher] Agent-Fehler: {e}"

    def _execute_direct(self,
                       command: str,
                       operation: str,
                       args: List[str],
                       dry_run: bool) -> Tuple[bool, str]:
        """
        Führt Befehl direkt über Handler aus (ohne Agent).

        Args:
            command: Handler-Name
            operation: Operation
            args: Argumente
            dry_run: Nur simulieren

        Returns:
            (success, message) Tuple
        """
        if dry_run:
            return True, f"[DRY] Direct Execute: {command} {operation} {args}"

        try:
            from core.app import App

            app = App(self.base_path)
            handler = app.get_handler(command)

            if not handler:
                suggestions = app.registry.suggest(command)
                msg = f"Unbekannter Befehl: {command}"
                if suggestions:
                    msg += f"\nMeintest du: {', '.join(suggestions)}?"
                return False, msg

            # Handler ausführen
            success, message = handler.handle(operation, args, dry_run)
            return success, message

        except Exception as e:
            return False, f"[Launcher] Handler-Fehler: {e}"

    def _log_routing(self,
                    command: str,
                    operation: str,
                    args: List[str],
                    source: str,
                    user: str):
        """Loggt Routing-Entscheidung."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        delegation = self.AGENT_DELEGATIONS.get(command)

        routing = f"[{timestamp}] ROUTE: {source}:{user} → {command} {operation}"
        if delegation:
            routing += f" → AGENT:{delegation}"
        else:
            routing += " → HANDLER"

        # In Datei loggen (optional)
        log_dir = self.base_path / "data" / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "launcher.log"

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(routing + "\n")
        except Exception:
            pass

        # Auch auf stderr ausgeben (für Debugging)
        print(routing, file=sys.stderr)

    def _track_task_source(self, source: str, user: str):
        """Markiert letzten Task mit Source + User."""
        if not self.db_path.exists():
            return

        try:
            conn = sqlite3.connect(str(self.db_path))

            # Prüfe ob Spalte 'source' existiert
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'source' in columns:
                # Letzten Task markieren
                conn.execute("""
                    UPDATE tasks
                    SET source = ?, assigned_agent = ?
                    WHERE id = (SELECT MAX(id) FROM tasks)
                """, (source, user))
                conn.commit()

            conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def route_command(command: str,
                 operation: str = "",
                 args: List[str] = None,
                 source: str = "cli",
                 user: str = "user",
                 base_path: Optional[Path] = None) -> Tuple[bool, str]:
    """
    Vereinfachter Einstiegspunkt für Command-Routing.

    Args:
        command: Handler-Name (z.B. "task", "steuer")
        operation: Operation (z.B. "add", "status")
        args: Argumente
        source: "cli", "telegram", "claude"
        user: User-ID oder "user"
        base_path: Optional base path

    Returns:
        (success, message) Tuple

    Example:
        success, msg = route_command("steuer", "status", source="telegram", user="123456")
    """
    launcher = Launcher(base_path)
    return launcher.route(command, operation, args or [], source, user)
