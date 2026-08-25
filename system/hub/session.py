#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
SessionHandler - Session-Verwaltung fuer BACH
==============================================

Implementiert SESSION_001-006 aus ROADMAP_ADVANCED.md

Operationen:
  start            Session starten (alias fuer --startup)
  status           Session-Status mit Denkanstoessen
  end              Session beenden (alias fuer --shutdown)
  check            Zeitberechnung und Status-Check
  next             Naechster Task mit Between-Task-Checks

Autor: Claude
Stand: 2026-01-24
"""

import sqlite3
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional
from .base import BaseHandler
from ._services.user_config_store import load_user_config, update_user_config


class SessionHandler(BaseHandler):
    """Handler fuer Session-Verwaltung (SESSION_001-006)"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        self.user_config_path = base_path / "data" / "user_config.json"

    @property
    def profile_name(self) -> str:
        return "session"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "start": "Session starten (wie --startup)",
            "status": "Session-Status mit Denkanstoessen",
            "end": "Session beenden (wie --shutdown)",
            "check": "Zeitberechnung (--duration fuer verbleibende Zeit)",
            "next": "Naechster Task mit Between-Task-Checks",
            "help": "Hilfe anzeigen"
        }

    def _get_db(self):
        """Datenbankverbindung holen"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _load_user_config(self) -> dict:
        """Laedt User-Config."""
        return load_user_config(
            self.user_config_path,
            {"session_duration_minutes": 120},
        )

    def _save_user_config(self, config: dict):
        """Speichert User-Config."""
        patch = dict(config)
        patch["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return update_user_config(
            self.user_config_path,
            lambda current: {**current, **patch},
        )

    def _get_current_session(self) -> Optional[dict]:
        """Holt aktuelle Session (nicht beendet)."""
        with self._get_db() as conn:
            row = conn.execute("""
                SELECT * FROM memory_sessions
                WHERE ended_at IS NULL
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            return dict(row) if row else None

    def _get_last_session(self) -> Optional[dict]:
        """Holt letzte beendete Session."""
        with self._get_db() as conn:
            row = conn.execute("""
                SELECT * FROM memory_sessions
                WHERE ended_at IS NOT NULL
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            return dict(row) if row else None

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        """Haupteinstiegspunkt"""

        if operation in ["start", ""]:
            return self._start(args, dry_run)
        elif operation == "status":
            return self._status(args)
        elif operation == "end":
            return self._end(args, dry_run)
        elif operation == "check":
            return self._check(args)
        elif operation == "next":
            return self._next(args)
        elif operation == "help":
            return self._help()
        else:
            return False, f"Unbekannte Operation: {operation}\nNutze: bach session help"

    # =========================================================================
    # SESSION_001: start/status/end Befehle
    # =========================================================================

    def _start(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Session starten - delegiert an StartupHandler"""
        # Pruefen ob bereits Session aktiv
        current = self._get_current_session()
        if current:
            return True, f"[INFO] Session bereits aktiv: {current['session_id']}\n" + \
                        f"       Gestartet: {current['started_at']}\n" + \
                        f"       --> bach session status fuer Details"

        # An StartupHandler delegieren
        from .startup import StartupHandler
        startup = StartupHandler(self.base_path)
        return startup.handle("run", args, dry_run)

    def _end(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Session beenden - delegiert an ShutdownHandler"""
        from .shutdown import ShutdownHandler
        shutdown = ShutdownHandler(self.base_path)
        return shutdown.handle("", args, dry_run)

    # =========================================================================
    # SESSION_002/003: Status mit Denkanstoessen
    # =========================================================================

    def _status(self, args: List[str]) -> Tuple[bool, str]:
        """Session-Status mit Denkanstoessen anzeigen"""
        results = []

        # Header
        results.append("\n" + "=" * 50)
        results.append("         SESSION STATUS")
        results.append("=" * 50)

        # Aktuelle Session
        current = self._get_current_session()
        if current:
            started = current['started_at']
            session_id = current['session_id']

            # Laufzeit berechnen
            try:
                start_dt = datetime.fromisoformat(started)
                elapsed = datetime.now() - start_dt
                hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            except (ValueError, TypeError):
                runtime_str = "?"

            results.append(f"\n[AKTIVE SESSION]")
            results.append(f" ID:       {session_id}")
            results.append(f" Start:    {started}")
            results.append(f" Laufzeit: {runtime_str}")
            results.append(f" Tasks:    +{current.get('tasks_created', 0)} erstellt, "
                          f"{current.get('tasks_completed', 0)} erledigt")
        else:
            results.append("\n[KEINE AKTIVE SESSION]")
            results.append(" --> bach session start zum Starten")

            # Letzte Session anzeigen
            last = self._get_last_session()
            if last:
                results.append("")
                results.append("[LETZTE SESSION]")
                results.append(f" ID:      {last['session_id']}")
                results.append(f" Beendet: {last['ended_at']}")
                if last.get('summary'):
                    results.append(f" Thema:   {last['summary'][:50]}...")

        # SESSION_003: Denkanstoesse
        results.append("")
        results.append("[DENKANSTOESSE]")
        prompts = self._get_thought_prompts()
        for prompt in prompts[:3]:
            results.append(f" * {prompt}")

        # Offene Tasks Zusammenfassung
        results.append("")
        results.append("[AUFGABEN-STATUS]")
        task_summary = self._get_task_summary()
        results.append(f" Offen: {task_summary['open']} | "
                      f"Blockiert: {task_summary['blocked']} | "
                      f"Heute erledigt: {task_summary['done_today']}")

        if task_summary['high_priority']:
            results.append(f" Top-Prioritaet: {task_summary['high_priority'][:40]}...")

        results.append("")
        results.append("=" * 50)

        return True, "\n".join(results)

    def _get_thought_prompts(self) -> List[str]:
        """Generiert kontextbasierte Denkanstoesse (SESSION_003)"""
        prompts = []

        # Zeitbasierte Prompts
        hour = datetime.now().hour
        if hour >= 16:
            prompts.append("Session-Ende naht - wichtige Erkenntnisse notieren?")
        if hour >= 11 and hour <= 13:
            prompts.append("Mittagspause? Kurze Pause verbessert die Produktivitaet.")

        # Task-basierte Prompts
        with self._get_db() as conn:
            # Lange offene Tasks
            old_tasks = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE status IN ('pending', 'open')
                AND created_at < date('now', '-7 days')
            """).fetchone()[0]
            if old_tasks > 5:
                prompts.append(f"{old_tasks} Tasks aelter als 7 Tage - Review noetig?")

            # Blockierte Tasks
            blocked = conn.execute("""
                SELECT COUNT(*) FROM tasks WHERE status = 'blocked'
            """).fetchone()[0]
            if blocked > 0:
                prompts.append(f"{blocked} blockierte Tasks - Blocker aufloesen?")

            # Keine Tasks heute erledigt
            done_today = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE status = 'done' AND date(completed_at) = date('now')
            """).fetchone()[0]
            if done_today == 0 and hour > 10:
                prompts.append("Noch keine Tasks heute erledigt - Quick Win starten?")

        # Allgemeine Prompts (Fallback)
        general_prompts = [
            "Dokumentation aktuell? README/CHANGELOG pruefen.",
            "Between-Task: Gibt es Abhaengigkeiten zu pruefen?",
            "Lessons Learned: Wichtige Erkenntnisse festhalten?",
            "Code-Review faellig? Qualitaet sichern.",
            "Backups aktuell? bach backup create",
        ]

        # Zufaellig ergaenzen falls zu wenig
        while len(prompts) < 3:
            prompt = random.choice(general_prompts)
            if prompt not in prompts:
                prompts.append(prompt)

        return prompts[:3]

    def _get_task_summary(self) -> dict:
        """Holt Task-Zusammenfassung"""
        with self._get_db() as conn:
            open_count = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE status IN ('pending', 'open', 'in_progress')
            """).fetchone()[0]

            blocked_count = conn.execute("""
                SELECT COUNT(*) FROM tasks WHERE status = 'blocked'
            """).fetchone()[0]

            done_today = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE status = 'done' AND date(completed_at) = date('now')
            """).fetchone()[0]

            # Hoechste Prioritaet Task
            top_task = conn.execute("""
                SELECT title FROM tasks
                WHERE status IN ('pending', 'open', 'in_progress')
                ORDER BY
                    CASE WHEN title LIKE 'P1%' THEN 1
                         WHEN title LIKE 'P2%' THEN 2
                         WHEN title LIKE 'P3%' THEN 3
                         ELSE 4 END,
                    created_at
                LIMIT 1
            """).fetchone()

            return {
                "open": open_count,
                "blocked": blocked_count,
                "done_today": done_today,
                "high_priority": top_task[0] if top_task else None
            }

    # =========================================================================
    # SESSION_004: Duration-Check
    # =========================================================================

    def _check(self, args: List[str]) -> Tuple[bool, str]:
        """Zeitberechnung und Status-Check"""
        results = []

        # --duration Flag pruefen
        show_duration = "--duration" in args or "-d" in args

        # Geplante Sitzungsdauer holen/setzen
        duration_minutes = 120  # Default: 2 Stunden
        for i, arg in enumerate(args):
            if arg.startswith("--set-duration="):
                try:
                    duration_minutes = int(arg.split("=")[1])
                    self._save_user_config({"session_duration_minutes": duration_minutes})
                    results.append(f"[OK] Sitzungsdauer auf {duration_minutes} Minuten gesetzt")
                except (ValueError, IndexError, OSError):
                    pass

        config = self._load_user_config()
        duration_minutes = config.get("session_duration_minutes", 120)

        current = self._get_current_session()
        if not current:
            return True, "[INFO] Keine aktive Session\n--> bach session start zum Starten"

        # Zeitberechnungen
        try:
            start_dt = datetime.fromisoformat(current['started_at'])
            now = datetime.now()
            elapsed = now - start_dt
            elapsed_minutes = int(elapsed.total_seconds() / 60)

            # Geplantes Ende
            planned_end = start_dt + timedelta(minutes=duration_minutes)
            remaining = planned_end - now
            remaining_minutes = int(remaining.total_seconds() / 60)

            results.append("\n[SESSION-ZEIT]")
            results.append(f" Start:     {start_dt.strftime('%H:%M')}")
            results.append(f" Laufzeit:  {elapsed_minutes} Minuten")
            results.append(f" Geplant:   {duration_minutes} Minuten")
            results.append(f" Ende:      {planned_end.strftime('%H:%M')}")

            if remaining_minutes > 0:
                results.append(f" Verbleibend: {remaining_minutes} Minuten")

                # Warnung bei wenig Zeit
                if remaining_minutes <= 15:
                    results.append("")
                    results.append(" *** ACHTUNG: Weniger als 15 Minuten verbleibend! ***")
                    results.append(" --> Wichtige Erkenntnisse jetzt festhalten")
                    results.append(" --> bach --memory session \"...\" fuer Bericht")
            else:
                overrun = abs(remaining_minutes)
                results.append(f" UEBERZOGEN: {overrun} Minuten!")
                results.append("")
                results.append(" *** SESSION SOLLTE BEENDET WERDEN ***")
                results.append(" --> bach session end")

            # Progress-Balken
            progress = min(100, int((elapsed_minutes / duration_minutes) * 100))
            bar_filled = int(progress / 5)
            bar_empty = 20 - bar_filled
            progress_bar = "[" + "=" * bar_filled + " " * bar_empty + f"] {progress}%"
            results.append(f"\n {progress_bar}")

        except Exception as e:
            results.append(f"[ERROR] Zeitberechnung: {e}")

        return True, "\n".join(results)

    # =========================================================================
    # SESSION_006: task next mit Between-Task-Checks
    # =========================================================================

    def _next(self, args: List[str]) -> Tuple[bool, str]:
        """Naechster Task mit Between-Task-Checks"""
        results = []

        # Between-Task-Checks (von CHIAH/BATCH)
        results.append("\n[BETWEEN-TASK CHECK]")

        checks_passed = True

        # 1. Gibt es blockierte Tasks die entblockt werden koennten?
        with self._get_db() as conn:
            blocked_with_deps = conn.execute("""
                SELECT t.id, t.title, t.depends_on
                FROM tasks t
                WHERE t.status = 'blocked' AND t.depends_on IS NOT NULL
            """).fetchall()

            for task in blocked_with_deps:
                deps = [int(x) for x in task['depends_on'].split(',') if x.strip()]
                # Pruefen ob alle Dependencies done sind
                done_deps = conn.execute(f"""
                    SELECT COUNT(*) FROM tasks
                    WHERE id IN ({','.join('?' * len(deps))}) AND status = 'done'
                """, deps).fetchone()[0]

                if done_deps == len(deps):
                    results.append(f" [!] Task {task['id']} kann entblockt werden!")
                    results.append(f"     \"{task['title'][:40]}...\"")
                    results.append(f"     --> bach task unblock {task['id']}")
                    checks_passed = False

        # 2. Gibt es in_progress Tasks die nicht abgeschlossen wurden?
        with self._get_db() as conn:
            in_progress = conn.execute("""
                SELECT id, title, updated_at FROM tasks
                WHERE status = 'in_progress'
                ORDER BY updated_at DESC
            """).fetchall()

            if in_progress:
                results.append(f" [!] {len(in_progress)} Task(s) noch 'in_progress':")
                for task in in_progress[:2]:
                    results.append(f"     [{task['id']}] {task['title'][:35]}...")
                results.append("     --> Erst abschliessen oder zuruecksetzen?")
                checks_passed = False

        # 3. Lessons Learned Erinnerung (alle 5 erledigte Tasks)
        with self._get_db() as conn:
            done_since_lesson = conn.execute("""
                SELECT COUNT(*) FROM tasks
                WHERE status = 'done'
                AND completed_at > COALESCE(
                    (SELECT created_at FROM memory_lessons ORDER BY created_at DESC LIMIT 1),
                    '2000-01-01'
                )
            """).fetchone()[0]

            if done_since_lesson >= 5:
                results.append(f" [?] {done_since_lesson} Tasks erledigt seit letzter Lesson")
                results.append("     --> Erkenntnisse festhalten: bach lesson add \"...\"")

        if checks_passed:
            results.append(" [OK] Alle Checks bestanden")

        # Naechsten Task empfehlen
        results.append("")
        results.append("[NAECHSTER TASK]")

        with self._get_db() as conn:
            # Prioritaet: P1 > P2 > P3 > P4, dann aelteste zuerst
            next_task = conn.execute("""
                SELECT id, title, priority, category, created_at, depends_on
                FROM tasks
                WHERE status IN ('pending', 'open')
                ORDER BY
                    CASE WHEN title LIKE 'P1%' THEN 1
                         WHEN title LIKE 'P2%' THEN 2
                         WHEN title LIKE 'P3%' THEN 3
                         ELSE 4 END,
                    created_at ASC
                LIMIT 1
            """).fetchone()

            if next_task:
                results.append(f" [{next_task['id']}] {next_task['title']}")
                if next_task['category']:
                    results.append(f"     Kategorie: {next_task['category']}")
                if next_task['depends_on']:
                    results.append(f"     Abhaengig von: {next_task['depends_on']}")
                results.append("")
                results.append(f" --> bach task show {next_task['id']} fuer Details")
            else:
                results.append(" Keine offenen Tasks! Neue Aufgaben anlegen:")
                results.append(" --> bach task add \"...\"")

        return True, "\n".join(results)

    def _help(self) -> Tuple[bool, str]:
        """Hilfe anzeigen"""
        return True, """
SESSION-VERWALTUNG
==================

Befehle:
  bach session start           Session starten (wie --startup)
  bach session status          Status mit Denkanstoessen
  bach session end             Session beenden (wie --shutdown)
  bach session check           Zeitberechnung anzeigen
  bach session check --duration  Mit verbleibender Zeit
  bach session next            Naechster Task mit Between-Checks

Optionen:
  --set-duration=MINUTEN       Geplante Sitzungsdauer setzen

Beispiele:
  bach session start
  bach session status
  bach session check --duration
  bach session check --set-duration=180
  bach session next
  bach session end

Features:
  - Denkanstoesse basierend auf Kontext (offene Tasks, Zeit, etc.)
  - Zeitberechnung mit Warnung bei Session-Ende
  - Between-Task-Checks vor neuem Task
  - Automatische Entblockierungs-Erkennung

Siehe auch:
  bach --help session
  bach task help
"""
