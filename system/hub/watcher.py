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
WatcherHandler - Mistral Always-On Watcher CLI
=================================================
bach watcher start       Watcher-Daemon starten
bach watcher stop        Watcher-Daemon stoppen
bach watcher status      Status anzeigen
bach watcher classify    Text manuell klassifizieren (Test)
bach watcher logs        Letzte Watcher-Logs anzeigen
bach watcher events      Letzte klassifizierte Events anzeigen

Version: 1.0.0
Erstellt: 2026-02-10
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Tuple, List

from .base import BaseHandler


class WatcherHandler(BaseHandler):
    """CLI-Handler fuer den Mistral Watcher Daemon."""

    @property
    def profile_name(self) -> str:
        return "watcher"

    @property
    def target_file(self) -> Path:
        return self.base_path / "hub" / "_services" / "watcher"

    def get_operations(self) -> dict:
        return {
            "start": "Watcher-Daemon starten",
            "stop": "Watcher-Daemon stoppen",
            "status": "Status anzeigen (Events, Ollama, Statistiken)",
            "classify": "Text manuell klassifizieren (Test)",
            "logs": "Letzte Watcher-Logs anzeigen",
            "events": "Letzte klassifizierte Events anzeigen",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """Fuehrt Operation aus."""
        ops = {
            "start": self._start,
            "stop": self._stop,
            "status": self._status,
            "classify": self._classify,
            "logs": self._logs,
            "events": self._events,
            "help": self._help,
        }

        if not operation or operation == "help":
            return self._help(args)

        func = ops.get(operation)
        if not func:
            return False, f"Unbekannte Operation: {operation}. Verfuegbar: {', '.join(ops.keys())}"

        return func(args)

    def _start(self, args: List[str]) -> Tuple[bool, str]:
        """Startet den Watcher-Daemon im Hintergrund."""
        daemon_script = self.target_file / "watcher_daemon.py"
        if not daemon_script.exists():
            return False, f"watcher_daemon.py nicht gefunden: {daemon_script}"

        # Im Hintergrund starten
        try:
            kwargs = {
                "cwd": str(self.target_file),
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                [sys.executable, str(daemon_script)], **kwargs
            )
            return True, f"Watcher-Daemon gestartet (PID {proc.pid})"
        except Exception as e:
            return False, f"Start fehlgeschlagen: {e}"

    def _stop(self, args: List[str]) -> Tuple[bool, str]:
        """Stoppt den Watcher-Daemon."""
        daemon_script = self.target_file / "watcher_daemon.py"
        try:
            result = subprocess.run(
                [sys.executable, str(daemon_script), "--stop"],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=10
            )
            return True, result.stdout.strip() or "Watcher-Daemon gestoppt"
        except Exception as e:
            return False, f"Stop fehlgeschlagen: {e}"

    def _status(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt Watcher-Status."""
        daemon_script = self.target_file / "watcher_daemon.py"
        try:
            result = subprocess.run(
                [sys.executable, str(daemon_script), "--status"],
                capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=10
            )
            return True, result.stdout.strip()
        except Exception as e:
            return False, f"Status-Abfrage fehlgeschlagen: {e}"

    def _classify(self, args: List[str]) -> Tuple[bool, str]:
        """Klassifiziert einen Text manuell (Test)."""
        if not args:
            return False, "Usage: bach watcher classify 'text zum klassifizieren'"

        text = " ".join(args)

        try:
            sys.path.insert(0, str(self.target_file))
            from hub._services.watcher.classifier import MistralClassifier, WatcherEvent

            classifier = MistralClassifier(self.base_path)
            if not classifier.is_available():
                return False, "Mistral/Ollama nicht verfuegbar. Ist Ollama gestartet?"

            event = WatcherEvent(
                source="manual",
                event_type="test",
                content=text,
                sender="user",
            )
            result = classifier.classify(event)

            lines = [
                f"Aktion:    {result.action.value}",
                f"Konfidenz: {result.confidence:.2f}",
                f"Reasoning: {result.reasoning}",
                f"Zeit:      {result.processing_time_ms}ms",
            ]
            if result.direct_response:
                lines.append(f"Antwort:   {result.direct_response}")
            if result.escalation_profile:
                lines.append(f"Profil:    {result.escalation_profile}")

            return True, "\n".join(lines)
        except Exception as e:
            return False, f"Klassifikation fehlgeschlagen: {e}"

    def _logs(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt letzte Watcher-Logs."""
        log_file = self.base_path / "data" / "logs" / "watcher_daemon.log"
        if not log_file.exists():
            return True, "Keine Watcher-Logs vorhanden."

        try:
            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            count = int(args[0]) if args else 20
            return True, "\n".join(lines[-count:])
        except Exception as e:
            return False, f"Fehler beim Lesen: {e}"

    def _events(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt letzte klassifizierte Events."""
        db_path = self._canonical_db
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            count = int(args[0]) if args else 20

            rows = conn.execute(
                "SELECT * FROM watcher_event_log ORDER BY id DESC LIMIT ?",
                (count,)
            ).fetchall()
            conn.close()

            if not rows:
                return True, "Keine Events vorhanden."

            lines = [f"Letzte {len(rows)} Events:\n"]
            for row in rows:
                action = row["action"].upper()
                conf = row["confidence"]
                src = row["source"]
                sender = row["sender"]
                preview = row["content_preview"][:50]
                time_ms = row["processing_time_ms"]
                lines.append(
                    f"  [{action:18}] conf={conf:.2f} {time_ms:5}ms "
                    f"{src}/{sender}: {preview}"
                )

            return True, "\n".join(lines)
        except Exception as e:
            return False, f"Fehler: {e}"

    def _help(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt Hilfe."""
        lines = [
            "BACH Watcher Daemon - Mistral Always-On",
            "=" * 40,
            "",
            "Befehle:",
            "  bach watcher start              Daemon starten",
            "  bach watcher stop               Daemon stoppen",
            "  bach watcher status             Status + Statistiken",
            "  bach watcher classify 'text'    Text manuell klassifizieren",
            "  bach watcher logs [N]           Letzte N Log-Zeilen (default: 20)",
            "  bach watcher events [N]         Letzte N Events (default: 20)",
            "",
            "Architektur:",
            "  Mistral (lokal via Ollama) laeuft als always-on Waechter.",
            "  Er klassifiziert Events in 4 Kategorien:",
            "    RESPOND_DIRECT  -> Mistral antwortet direkt via Connector",
            "    ESCALATE_CLAUDE -> Claude Code Session wird gestartet",
            "    LOG_ONLY        -> Nur loggen",
            "    IGNORE          -> Verwerfen",
            "",
            "Config: hub/_services/watcher/config.json",
            "Logs:   data/logs/watcher_daemon.log",
        ]
        return True, "\n".join(lines)
