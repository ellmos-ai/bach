# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
ClaudeBridgeHandler - Claude Telegram Bridge CLI
==================================================
bach claude-bridge start       Bridge-Daemon starten
bach claude-bridge stop        Bridge-Daemon stoppen
bach claude-bridge status      Status anzeigen
bach claude-bridge mode        Aktuellen Permission-Modus anzeigen
bach claude-bridge test "msg"  Test-Nachricht simulieren
bach claude-bridge logs [N]    Letzte N Log-Zeilen anzeigen
bach claude-bridge workers     Worker-Status anzeigen
bach claude-bridge password    Passwort aendern
bach claude-bridge setup       Interaktiver Setup-Wizard
bach claude-bridge challenge   Security Challenge generieren
bach claude-bridge verify      Challenge-Antwort verifizieren

Version: 1.1.0
Erstellt: 2026-02-11
Erweitert: 2026-02-16 (Setup-Wizard, Security Layer)
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Tuple, List

from .base import BaseHandler


class ClaudeBridgeHandler(BaseHandler):
    """CLI-Handler fuer den Claude Telegram Bridge Daemon."""

    @property
    def profile_name(self) -> str:
        return "claude-bridge"

    @property
    def target_file(self) -> Path:
        return self.base_path / "hub" / "_services" / "claude_bridge"

    def get_operations(self) -> dict:
        return {
            "start": "Bridge-Daemon starten",
            "stop": "Bridge-Daemon stoppen",
            "status": "Status anzeigen (Daemon, Workers, Budget)",
            "mode": "Aktuellen Permission-Modus anzeigen",
            "test": "Test-Nachricht simulieren",
            "logs": "Letzte Bridge-Logs anzeigen",
            "workers": "Worker-Status anzeigen",
            "password": "Passwort fuer Vollzugriff aendern",
            "setup": "Interaktiver Setup-Wizard fuer neue Nutzer",
            "challenge": "Security Challenge generieren",
            "verify": "Challenge-Antwort verifizieren",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "start": self._start,
            "stop": self._stop,
            "status": self._status,
            "mode": self._mode,
            "test": self._test,
            "logs": self._logs,
            "workers": self._workers,
            "password": self._password,
            "setup": self._setup,
            "challenge": self._challenge,
            "verify": self._verify,
            "help": self._help,
        }

        if not operation or operation == "help":
            return self._help(args)

        func = ops.get(operation)
        if not func:
            return False, f"Unbekannte Operation: {operation}. Verfuegbar: {', '.join(ops.keys())}"

        return func(args)

    def _start(self, args: List[str]) -> Tuple[bool, str]:
        """Startet den Bridge-Daemon im Hintergrund."""
        daemon_script = self.target_file / "bridge_daemon.py"
        if not daemon_script.exists():
            return False, f"bridge_daemon.py nicht gefunden: {daemon_script}"

        creation_flags = 0x08000000 if sys.platform == "win32" else 0
        try:
            env = dict(__import__('os').environ)
            env['PYTHONIOENCODING'] = 'utf-8'
            proc = subprocess.Popen(
                [sys.executable, str(daemon_script)],
                cwd=str(self.target_file),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
                env=env,
                encoding='utf-8', errors='replace'
            )
            return True, f"Claude Bridge Daemon gestartet (PID {proc.pid})"
        except Exception as e:
            return False, f"Start fehlgeschlagen: {e}"

    def _stop(self, args: List[str]) -> Tuple[bool, str]:
        daemon_script = self.target_file / "bridge_daemon.py"
        try:
            result = subprocess.run(
                [sys.executable, str(daemon_script), "--stop"],
                capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace'
            )
            return True, result.stdout.strip() or "Bridge-Daemon gestoppt"
        except Exception as e:
            return False, f"Stop fehlgeschlagen: {e}"

    def _status(self, args: List[str]) -> Tuple[bool, str]:
        daemon_script = self.target_file / "bridge_daemon.py"
        try:
            result = subprocess.run(
                [sys.executable, str(daemon_script), "--status"],
                capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace'
            )
            return True, result.stdout.strip()
        except Exception as e:
            return False, f"Status-Abfrage fehlgeschlagen: {e}"

    def _mode(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt den aktuellen Modus aus der Config."""
        config_file = self.target_file / "config.json"
        if not config_file.exists():
            return False, "config.json nicht gefunden"
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            mode = config.get("permissions", {}).get("default_mode", "restricted")
            return True, f"Default-Modus: {mode}\n(Laufzeit-Modus kann via Telegram 'mode' abgefragt werden)"
        except Exception as e:
            return False, f"Fehler: {e}"

    def _test(self, args: List[str]) -> Tuple[bool, str]:
        """Simuliert eine Telegram-Nachricht."""
        if not args:
            return False, "Usage: bach claude-bridge test 'deine Nachricht'"
        text = " ".join(args)
        daemon_script = self.target_file / "bridge_daemon.py"
        try:
            result = subprocess.run(
                [sys.executable, str(daemon_script), "--test", text],
                capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace'
            )
            return True, result.stdout.strip()
        except Exception as e:
            return False, f"Test fehlgeschlagen: {e}"

    def _logs(self, args: List[str]) -> Tuple[bool, str]:
        log_file = self.base_path / "data" / "logs" / "claude_bridge.log"
        if not log_file.exists():
            return True, "Keine Bridge-Logs vorhanden."
        try:
            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            count = int(args[0]) if args else 20
            return True, "\n".join(lines[-count:])
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"

    def _workers(self, args: List[str]) -> Tuple[bool, str]:
        db_path = self.base_path / "data" / "bach.db"
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM claude_bridge_workers ORDER BY id DESC LIMIT 10"
            ).fetchall()
        except Exception as e:
            return False, f"Fehler: {e}"
        finally:
            if conn:
                conn.close()

        try:

            if not rows:
                return True, "Keine Worker vorhanden."

            lines = ["Letzte Worker:\n"]
            for r in rows:
                status = r["status"].upper()
                task = r["task_description"][:60]
                started = r["started_at"][:16] if r["started_at"] else "?"
                ended = r["ended_at"][:16] if r["ended_at"] else "-"
                lines.append(f"  [W{r['id']}] {status:10} {started} - {ended}  {task}")
                if r["error_message"]:
                    lines.append(f"           Fehler: {r['error_message'][:80]}")
                if r["result_summary"]:
                    lines.append(f"           Ergebnis: {r['result_summary'][:80]}")

            return True, "\n".join(lines)
        except Exception as e:
            return False, f"Fehler: {e}"

    def _password(self, args: List[str]) -> Tuple[bool, str]:
        """Aendert das Passwort in config.json."""
        if not args:
            return False, "Usage: bach claude-bridge password <neues-passwort>"
        new_pw = args[0]
        config_file = self.target_file / "config.json"
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            config["permissions"]["password"] = new_pw
            config_file.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding="utf-8")
            return True, f"Passwort geaendert. Daemon muss neu gestartet werden fuer Aenderung."
        except Exception as e:
            return False, f"Fehler: {e}"

    def _setup(self, args: List[str]) -> Tuple[bool, str]:
        """Startet den interaktiven Setup-Wizard."""
        try:
            from hub._services.claude_bridge.setup_wizard import run_wizard
            result = run_wizard(self.base_path)
            if result:
                return True, "Setup abgeschlossen."
            return False, "Setup abgebrochen."
        except Exception as e:
            return False, f"Setup-Fehler: {e}"

    def _challenge(self, args: List[str]) -> Tuple[bool, str]:
        """Generiert eine Security Challenge."""
        user_id = args[0] if args else "default"
        try:
            from hub._services.claude_bridge.security import SecurityChallenge
            sec = SecurityChallenge(self.base_path / "data" / "bach.db")
            result = sec.generate_challenge(user_id)
            if result["ok"]:
                return True, f"Challenge: {result['challenge']}"
            return False, result["error"]
        except Exception as e:
            return False, f"Fehler: {e}"

    def _verify(self, args: List[str]) -> Tuple[bool, str]:
        """Verifiziert eine Challenge-Antwort."""
        if not args:
            return False, "Usage: bach claude-bridge verify <antwort> [--user=ID]"
        user_id = "default"
        answer_parts = []
        for a in args:
            if a.startswith("--user="):
                user_id = a.split("=", 1)[1]
            else:
                answer_parts.append(a)
        answer = " ".join(answer_parts)
        try:
            from hub._services.claude_bridge.security import SecurityChallenge
            sec = SecurityChallenge(self.base_path / "data" / "bach.db")
            result = sec.verify_challenge(user_id, answer)
            if result["ok"]:
                return True, result["message"]
            return False, result["error"]
        except Exception as e:
            return False, f"Fehler: {e}"

    def _help(self, args: List[str]) -> Tuple[bool, str]:
        lines = [
            "BACH Claude Bridge - Telegram <-> Claude Code CLI",
            "=" * 50,
            "",
            "Befehle:",
            "  bach claude-bridge start              Daemon starten",
            "  bach claude-bridge stop               Daemon stoppen",
            "  bach claude-bridge status             Status + Workers + Budget",
            "  bach claude-bridge mode               Permission-Modus anzeigen",
            "  bach claude-bridge test 'text'        Test-Nachricht simulieren",
            "  bach claude-bridge logs [N]           Letzte N Log-Zeilen (default: 20)",
            "  bach claude-bridge workers            Worker-Uebersicht",
            "  bach claude-bridge password <pw>      Passwort aendern",
            "",
            "Telegram-Befehle (im Chat):",
            "  toggle               Vollzugriff ein/aus (1h Auto-Lock)",
            "  mode                 Aktuellen Modus anzeigen",
            "  budget               Budget-Status",
            "  workers              Worker-Uebersicht",
            "  stop                 Laufende Worker stoppen",
            "",
            "Architektur:",
            "  Jede Telegram-Nachricht startet einen frischen Chat-Claude.",
            "  Chat-Claude liest History + Worker-Ergebnisse + BACH-Kontext.",
            "  Laengere Aufgaben werden an Worker-Claude delegiert.",
            "  Workers arbeiten autonom und senden Status via Telegram.",
            "",
            "Config: hub/_services/claude_bridge/config.json",
            "Logs:   data/logs/claude_bridge.log",
        ]
        return True, "\n".join(lines)
