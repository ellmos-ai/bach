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
DailyAgentHandler - Tagesagent mit persistenter Session
========================================================
bach daily-agent start          Agent starten (Claude Code --continue)
bach daily-agent stop           Agent stoppen + Summary
bach daily-agent status         Status anzeigen
bach daily-agent briefing       Morgen-Briefing generieren
bach daily-agent summary        Abend-Zusammenfassung
bach daily-agent config         Briefing-Module konfigurieren
bach daily-agent modules        Aktive Module anzeigen
bach daily-agent toggle <modul> Modul ein-/ausschalten

Task: 989
"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Tuple

from .base import BaseHandler

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class DailyAgentHandler(BaseHandler):

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db
        self.pid_file = self.base_path / "data" / "daily_agent.pid"

    @property
    def profile_name(self) -> str:
        return "daily-agent"

    @property
    def target_file(self) -> Path:
        return self.base_path

    # Briefing-Module: Name -> (Methode, Default-Aktiv)
    BRIEFING_MODULES = {
        "task_briefing": ("Offene Tasks", True),
        "message_briefing": ("Ungelesene Nachrichten", True),
        "news_briefing": ("News-Ueberblick", True),
        "session_briefing": ("Letzte Session", True),
        "weather_briefing": ("Wetter", False),
        "calendar_briefing": ("Kalender", False),
    }

    def get_operations(self) -> dict:
        return {
            "start": "Tagesagent starten",
            "stop": "Tagesagent stoppen + Summary in Memory",
            "status": "Status anzeigen",
            "briefing": "Morgen-Briefing generieren",
            "summary": "Abend-Zusammenfassung generieren",
            "config": "Briefing-Module konfigurieren",
            "modules": "Aktive Module anzeigen",
            "toggle": "Modul ein-/ausschalten: toggle <modul>",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if dry_run:
            return True, f"[DRY-RUN] daily-agent {operation}"

        if operation == "start":
            return self._start(args)
        elif operation == "stop":
            return self._stop(args)
        elif operation == "status":
            return self._status(args)
        elif operation == "briefing":
            return self._briefing(args)
        elif operation == "summary":
            return self._summary(args)
        elif operation == "config":
            return self._config(args)
        elif operation == "modules":
            return self._modules(args)
        elif operation == "toggle":
            return self._toggle(args)
        else:
            ops = "\n".join(f"  {k}: {v}" for k, v in self.get_operations().items())
            return False, f"Nutzung:\n{ops}"

    def _find_claude_cli(self) -> str:
        """Sucht Claude CLI."""
        import shutil
        path = shutil.which("claude")
        if path:
            return path

        # Windows WinGet Pfad
        winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if winget.exists():
            for match in winget.rglob("claude.exe"):
                return str(match)
        return ""

    def _is_running(self) -> dict:
        """Prueft ob Agent laeuft."""
        if not self.pid_file.exists():
            return {"running": False}

        try:
            data = json.loads(self.pid_file.read_text(encoding='utf-8'))
            pid = data.get("pid")
            # Pruefe ob Prozess existiert
            if sys.platform == "win32":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=5
                )
                if str(pid) in result.stdout:
                    return {"running": True, **data}
            else:
                os.kill(pid, 0)
                return {"running": True, **data}
        except (ProcessLookupError, PermissionError, json.JSONDecodeError):
            pass
        except Exception:
            pass

        return {"running": False}

    def _start(self, args: List[str]) -> Tuple[bool, str]:
        """Startet den Tagesagent."""
        status = self._is_running()
        if status["running"]:
            return False, f"Agent laeuft bereits (PID {status.get('pid')}). Stoppe zuerst mit: bach daily-agent stop"

        claude = self._find_claude_cli()
        if not claude:
            return False, "Claude CLI nicht gefunden. Installiere Claude Code oder setze PATH."

        # Claude Code mit --continue starten
        model = "sonnet"
        for a in args:
            if a.startswith("--model="):
                model = a.split("=", 1)[1]

        today = date.today().strftime("%Y-%m-%d")
        initial_prompt = f"Starte BACH Tagesagent fuer {today}. Fuehre bach --startup durch und arbeite die Task-Queue ab."

        try:
            kwargs = {
                "cwd": str(self.base_path),
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                [claude, "--model", model, "--continue", "-p", initial_prompt],
                **kwargs,
            )

            # PID speichern
            pid_data = {
                "pid": proc.pid,
                "started": datetime.now().isoformat(),
                "date": today,
                "model": model,
            }
            self.pid_file.write_text(json.dumps(pid_data, indent=2), encoding='utf-8')

            return True, f"Tagesagent gestartet (PID {proc.pid}, Modell: {model})"
        except Exception as e:
            return False, f"Start fehlgeschlagen: {e}"

    def _stop(self, args: List[str]) -> Tuple[bool, str]:
        """Stoppt den Tagesagent und erstellt Summary."""
        status = self._is_running()
        if not status["running"]:
            return True, "Agent laeuft nicht."

        pid = status.get("pid")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
            else:
                os.kill(pid, 15)  # SIGTERM
        except Exception as e:
            return False, f"Stop fehlgeschlagen: {e}"

        # PID-File entfernen
        if self.pid_file.exists():
            self.pid_file.unlink()

        # Summary in Memory schreiben
        started = status.get("started", "?")
        today = date.today().strftime("%Y-%m-%d")
        summary = f"Tagesagent {today}: Gestartet {started}, gestoppt {datetime.now().isoformat()}"

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                INSERT INTO memory_working (content, category, is_active, created_at)
                VALUES (?, 'daily_agent', 1, datetime('now'))
            """, (summary,))
            conn.commit()
            conn.close()
        except Exception:
            pass

        return True, f"Agent gestoppt (PID {pid}). Summary in Memory."

    def _status(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt Agent-Status."""
        status = self._is_running()

        lines = ["DAILY AGENT STATUS", "=" * 35]
        if status["running"]:
            lines.append(f"  Status:   AKTIV")
            lines.append(f"  PID:      {status.get('pid')}")
            lines.append(f"  Gestartet: {status.get('started', '?')}")
            lines.append(f"  Modell:   {status.get('model', '?')}")
            lines.append(f"  Datum:    {status.get('date', '?')}")
        else:
            lines.append(f"  Status:   INAKTIV")
            lines.append(f"  Starten:  bach daily-agent start")

        return True, "\n".join(lines)

    def _ensure_briefing_config(self, conn):
        """Stellt sicher dass die briefing_config Tabelle existiert und befuellt ist."""
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS briefing_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module_name TEXT UNIQUE NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 50,
                    settings_json TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    dist_type INTEGER DEFAULT 0
                )
            """)
            for mod_name, (desc, default_active) in self.BRIEFING_MODULES.items():
                conn.execute("""
                    INSERT OR IGNORE INTO briefing_config (module_name, is_active, priority)
                    VALUES (?, ?, ?)
                """, (mod_name, 1 if default_active else 0,
                      list(self.BRIEFING_MODULES.keys()).index(mod_name) * 10 + 10))
            conn.commit()
        except Exception:
            pass

    def _get_active_modules(self, conn) -> list:
        """Gibt aktive Briefing-Module sortiert nach Prioritaet zurueck."""
        self._ensure_briefing_config(conn)
        try:
            rows = conn.execute("""
                SELECT module_name FROM briefing_config
                WHERE is_active = 1 ORDER BY priority ASC
            """).fetchall()
            return [r['module_name'] if isinstance(r, sqlite3.Row) else r[0] for r in rows]
        except Exception:
            return ["task_briefing", "message_briefing", "session_briefing"]

    def _briefing(self, args: List[str]) -> Tuple[bool, str]:
        """Generiert ein modulares Morgen-Briefing."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row

            lines = [f"MORGEN-BRIEFING ({date.today().strftime('%d.%m.%Y')})", "=" * 45]

            active_modules = self._get_active_modules(conn)

            module_methods = {
                "task_briefing": self._mod_task_briefing,
                "message_briefing": self._mod_message_briefing,
                "news_briefing": self._mod_news_briefing,
                "session_briefing": self._mod_session_briefing,
                "weather_briefing": self._mod_weather_briefing,
                "calendar_briefing": self._mod_calendar_briefing,
            }

            for mod_name in active_modules:
                method = module_methods.get(mod_name)
                if method:
                    try:
                        block = method(conn)
                        if block:
                            lines.append(block)
                    except Exception as e:
                        lines.append(f"\n[{mod_name}] Fehler: {e}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Briefing-Module (jedes liefert einen Textblock)
    # ------------------------------------------------------------------

    def _mod_task_briefing(self, conn) -> str:
        """Modul: Offene Tasks."""
        tasks = conn.execute("""
            SELECT id, title, priority FROM tasks
            WHERE status = 'pending' ORDER BY priority, id LIMIT 10
        """).fetchall()
        parts = [f"\nOFFENE TASKS ({len(tasks)}):"]
        for t in tasks:
            parts.append(f"  [{t['id']}] {t['priority'] or 'P4'} {t['title'][:60]}")
        # Faellige periodische Tasks
        try:
            recurring = conn.execute("""
                SELECT id, name FROM scheduler_jobs
                WHERE is_active = 1 LIMIT 5
            """).fetchall()
            if recurring:
                parts.append(f"\nPERIODISCHE TASKS:")
                for r in recurring:
                    parts.append(f"  [{r['id']}] {r['name']}")
        except Exception:
            pass
        return "\n".join(parts)

    def _mod_message_briefing(self, conn) -> str:
        """Modul: Ungelesene Nachrichten."""
        unread = conn.execute("""
            SELECT COUNT(*) as cnt FROM messages WHERE status = 'unread'
        """).fetchone()
        return f"\nNACHRICHTEN: {unread['cnt']} ungelesen"

    def _mod_news_briefing(self, conn) -> str:
        """Modul: News-Ueberblick (aus news_items)."""
        try:
            unread = conn.execute("""
                SELECT COUNT(*) as cnt FROM news_items WHERE is_read = 0
            """).fetchone()
            total = unread['cnt']
            if total == 0:
                return "\nNEWS: Keine ungelesenen Artikel"

            # Top-Kategorien
            cats = conn.execute("""
                SELECT category, COUNT(*) as cnt FROM news_items
                WHERE is_read = 0 GROUP BY category ORDER BY cnt DESC LIMIT 5
            """).fetchall()
            parts = [f"\nNEWS: {total} ungelesene Artikel"]
            for c in cats:
                parts.append(f"  {c['category']}: {c['cnt']}")

            # Neueste 3 Titel
            latest = conn.execute("""
                SELECT title FROM news_items
                WHERE is_read = 0 ORDER BY fetched_at DESC LIMIT 3
            """).fetchall()
            if latest:
                parts.append("  Aktuell:")
                for l in latest:
                    parts.append(f"    - {l['title'][:55]}")
            return "\n".join(parts)
        except Exception:
            return ""  # news_items Tabelle existiert noch nicht

    def _mod_session_briefing(self, conn) -> str:
        """Modul: Letzte Session."""
        try:
            last = conn.execute("""
                SELECT summary FROM memory_sessions
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            if last and last['summary']:
                return f"\nLETZTE SESSION:\n  {last['summary'][:120]}..."
        except Exception:
            pass
        return ""

    def _mod_weather_briefing(self, conn) -> str:
        """Modul: Wetter (optional, benoetigt weather_service)."""
        try:
            from hub._services.weather.weather_service import get_weather_text
            weather = get_weather_text(52.6786, 13.5874)  # Bernau bei Berlin
            if weather:
                return f"\nWETTER:\n  {weather[:150]}"
        except Exception:
            pass
        return ""

    def _mod_calendar_briefing(self, conn) -> str:
        """Modul: Kalender-Events (optional)."""
        try:
            today_str = date.today().strftime("%Y-%m-%d")
            events = conn.execute("""
                SELECT title, start_datetime FROM assistant_calendar
                WHERE date(start_datetime) = ? ORDER BY start_datetime LIMIT 5
            """, (today_str,)).fetchall()
            if events:
                parts = [f"\nKALENDER ({len(events)} Termine):"]
                for e in events:
                    start = e['start_datetime'] or ''
                    time_text = start[11:16] if len(start) >= 16 else '--:--'
                    parts.append(f"  {time_text} {e['title'][:50]}")
                return "\n".join(parts)
        except Exception:
            pass
        return ""

    def _summary(self, args: List[str]) -> Tuple[bool, str]:
        """Generiert eine Abend-Zusammenfassung."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row

            today = date.today().strftime("%Y-%m-%d")
            lines = [f"ABEND-SUMMARY ({today})", "=" * 45]

            # Heute erledigte Tasks
            done = conn.execute("""
                SELECT id, title FROM tasks
                WHERE status = 'done' AND completed_at LIKE ?
                ORDER BY completed_at
            """, (f"{today}%",)).fetchall()
            lines.append(f"\nERLEDIGT HEUTE: {len(done)}")
            for t in done:
                lines.append(f"  [{t['id']}] {t['title'][:60]}")

            # Noch offen
            pending = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending'").fetchone()
            lines.append(f"\nNOCH OFFEN: {pending['cnt']}")

            # Heutige Memory-Eintraege
            memos = conn.execute("""
                SELECT content FROM memory_working
                WHERE created_at LIKE ? AND is_active = 1
            """, (f"{today}%",)).fetchall()
            if memos:
                lines.append(f"\nNOTIZEN HEUTE: {len(memos)}")
                for m in memos[:5]:
                    lines.append(f"  - {m['content'][:80]}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Briefing-Konfiguration
    # ------------------------------------------------------------------

    def _config(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt Briefing-Konfiguration."""
        return self._modules(args)

    def _modules(self, args: List[str]) -> Tuple[bool, str]:
        """Zeigt aktive und inaktive Briefing-Module."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            self._ensure_briefing_config(conn)

            rows = conn.execute("""
                SELECT module_name, is_active, priority FROM briefing_config
                ORDER BY priority ASC
            """).fetchall()
        finally:
            conn.close()

        if not rows:
            return True, "Keine Briefing-Module konfiguriert."

        lines = ["Briefing-Module", "=" * 50]
        for r in rows:
            status = "AN" if r['is_active'] else "AUS"
            desc = self.BRIEFING_MODULES.get(r['module_name'], ("?",))[0]
            lines.append(f"  [{status:>3}] {r['module_name']} (Prio {r['priority']}) - {desc}")
        lines.append(f"\nUmschalten: bach daily-agent toggle <modul>")
        return True, "\n".join(lines)

    def _toggle(self, args: List[str]) -> Tuple[bool, str]:
        """Schaltet ein Briefing-Modul ein oder aus."""
        if not args:
            return False, f"Verwendung: bach daily-agent toggle <modul>\nModule: {', '.join(self.BRIEFING_MODULES.keys())}"

        mod_name = args[0]
        if mod_name not in self.BRIEFING_MODULES:
            return False, f"Unbekanntes Modul: {mod_name}\nVerfuegbar: {', '.join(self.BRIEFING_MODULES.keys())}"

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            self._ensure_briefing_config(conn)

            row = conn.execute(
                "SELECT is_active FROM briefing_config WHERE module_name = ?",
                (mod_name,)
            ).fetchone()

            if row:
                new_state = 0 if row['is_active'] else 1
                conn.execute(
                    "UPDATE briefing_config SET is_active = ? WHERE module_name = ?",
                    (new_state, mod_name)
                )
            else:
                new_state = 1
                conn.execute(
                    "INSERT INTO briefing_config (module_name, is_active, priority) VALUES (?, 1, 50)",
                    (mod_name,)
                )

            conn.commit()
        finally:
            conn.close()

        status = "aktiviert" if new_state else "deaktiviert"
        desc = self.BRIEFING_MODULES.get(mod_name, ("?",))[0]
        return True, f"[OK] Modul '{mod_name}' ({desc}) {status}"
