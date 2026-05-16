#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: time_system
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version time_system

Description:
    [Beschreibung hinzufügen]

Usage:
    python time_system.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
Time System - Unified Zeit-Funktionen fuer BACH
=================================================

Module:
- ClockModule: Uhrzeit-Anzeige mit Intervall
- TimerModule: Stoppuhr (mehrere parallel)
- CountdownModule: Countdown mit Trigger
- BetweenManager: Profile-basierte Zwischen-Checks

v1.1.83: Initial Implementation (TIME-01 bis TIME-05)
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ClockModule:
    """
    Uhrzeit-Anzeige mit konfigurierbarem Intervall.

    CLI: bach clock on|off|status|interval
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.state_file = base_path / "data" / ".clock_state"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Laedt Zustand aus Datei."""
        default = {
            "enabled": True,
            "interval": 60,
            "last_shown": None
        }
        if self.state_file.exists():
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                default.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def _save_state(self) -> None:
        """Speichert Zustand."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self.state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError:
            pass

    def enable(self, enabled: bool = True) -> str:
        """Aktiviert/deaktiviert Clock."""
        self.state["enabled"] = enabled
        self._save_state()
        status = "aktiviert" if enabled else "deaktiviert"
        return f"[CLOCK] Uhrzeit-Anzeige {status}"

    def set_interval(self, seconds: int) -> str:
        """Setzt Intervall in Sekunden."""
        self.state["interval"] = max(0, seconds)
        self._save_state()
        if seconds == 0:
            return "[CLOCK] Intervall: Bei JEDER Ausgabe"
        return f"[CLOCK] Intervall: {seconds} Sekunden"

    def check(self) -> Optional[str]:
        """
        Prueft ob Uhrzeit angezeigt werden soll.

        Returns:
            Uhrzeit-String oder None
        """
        if not self.state["enabled"]:
            return None

        now = datetime.now()
        last_shown = self.state.get("last_shown")
        interval = self.state.get("interval", 60)

        # Bei interval=0 immer anzeigen
        if interval == 0:
            self.state["last_shown"] = now.isoformat()
            self._save_state()
            return f"[CLOCK] {now.strftime('%H:%M')}"

        # Intervall pruefen
        if last_shown:
            try:
                last_dt = datetime.fromisoformat(last_shown)
                if (now - last_dt).total_seconds() < interval:
                    return None
            except (ValueError, TypeError):
                pass

        self.state["last_shown"] = now.isoformat()
        self._save_state()
        return f"[CLOCK] {now.strftime('%H:%M')}"

    def status(self) -> str:
        """Gibt Status-String zurueck."""
        enabled = "AN" if self.state["enabled"] else "AUS"
        interval = self.state.get("interval", 60)
        last = "nie"
        if self.state.get("last_shown"):
            try:
                last_dt = datetime.fromisoformat(self.state["last_shown"])
                last = last_dt.strftime("%H:%M")
            except (ValueError, TypeError):
                pass
        return f"Clock: {enabled} | Intervall: {interval}s | Letzte: {last}"


class TimerModule:
    """
    Stoppuhr - mehrere Timer parallel moeglich.

    CLI: bach timer start|stop|list|clear
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.state_file = base_path / "data" / ".timer_state"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Laedt Zustand aus Datei."""
        default = {"timers": {}}
        if self.state_file.exists():
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                default.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def _save_state(self) -> None:
        """Speichert Zustand."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self.state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError:
            pass

    def _format_duration(self, seconds: float) -> str:
        """Formatiert Sekunden als HH:MM:SS oder MM:SS."""
        total_sec = int(seconds)
        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        secs = total_sec % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def start(self, name: str = "default") -> str:
        """Startet einen Timer."""
        if name in self.state["timers"]:
            return f"[TIMER] '{name}' laeuft bereits"

        self.state["timers"][name] = datetime.now().isoformat()
        self._save_state()
        return f"[TIMER] '{name}' gestartet"

    def stop(self, name: str = None) -> str:
        """Stoppt einen Timer."""
        timers = self.state["timers"]

        if not timers:
            return "[TIMER] Kein Timer aktiv"

        # Wenn kein Name: letzten/einzigen stoppen
        if name is None:
            if len(timers) == 1:
                name = list(timers.keys())[0]
            else:
                return f"[TIMER] Mehrere aktiv: {', '.join(timers.keys())} - bitte Name angeben"

        if name not in timers:
            return f"[TIMER] '{name}' nicht gefunden"

        # Dauer berechnen
        start_time = datetime.fromisoformat(timers[name])
        duration = (datetime.now() - start_time).total_seconds()
        formatted = self._format_duration(duration)

        del self.state["timers"][name]
        self._save_state()

        return f"[TIMER] '{name}' gestoppt: {formatted}"

    def list_timers(self) -> str:
        """Listet alle aktiven Timer."""
        timers = self.state["timers"]

        if not timers:
            return "[TIMER] Keine aktiven Timer"

        lines = ["[TIMER] Aktive Timer:"]
        now = datetime.now()

        for name, start_iso in timers.items():
            try:
                start_time = datetime.fromisoformat(start_iso)
                duration = (now - start_time).total_seconds()
                formatted = self._format_duration(duration)
                lines.append(f"  {name}: {formatted}")
            except (ValueError, TypeError):
                lines.append(f"  {name}: (Fehler)")

        return "\n".join(lines)

    def clear(self) -> str:
        """Loescht alle Timer."""
        count = len(self.state["timers"])
        self.state["timers"] = {}
        self._save_state()
        return f"[TIMER] {count} Timer geloescht"

    def get_display(self) -> Optional[str]:
        """
        Gibt kompakte Timer-Anzeige fuer CLI-Output zurueck.

        Returns:
            String wie "Session 45:12 | Recherche 05:23" oder None
        """
        timers = self.state["timers"]
        if not timers:
            return None

        now = datetime.now()
        parts = []

        for name, start_iso in timers.items():
            try:
                start_time = datetime.fromisoformat(start_iso)
                duration = (now - start_time).total_seconds()
                formatted = self._format_duration(duration)
                parts.append(f"{name} {formatted}")
            except (ValueError, TypeError):
                pass

        return " | ".join(parts) if parts else None


class CountdownModule:
    """
    Countdown-Timer mit optionalem Trigger-Befehl.

    CLI: bach countdown start|stop|list|pause|resume
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.state_file = base_path / "data" / ".countdown_state"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Laedt Zustand aus Datei."""
        default = {"countdowns": {}}
        if self.state_file.exists():
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                default.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def _save_state(self) -> None:
        """Speichert Zustand."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self.state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError:
            pass

    def _parse_duration(self, duration_str: str) -> int:
        """
        Parst Dauer-String zu Sekunden.

        Formate: HH:MM:SS, MM:SS, Xs, Xm, Xh
        """
        duration_str = duration_str.strip()

        # HH:MM:SS oder MM:SS
        if ":" in duration_str:
            parts = duration_str.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])

        # Xs, Xm, Xh
        if duration_str.endswith("s"):
            return int(duration_str[:-1])
        if duration_str.endswith("m"):
            return int(duration_str[:-1]) * 60
        if duration_str.endswith("h"):
            return int(duration_str[:-1]) * 3600

        # Fallback: Sekunden
        return int(duration_str)

    def _format_remaining(self, seconds: int) -> str:
        """Formatiert verbleibende Zeit."""
        if seconds < 0:
            return "ABGELAUFEN"

        hours = seconds / 3600
        minutes = (seconds % 3600) / 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def start(self, name: str, duration: str, after_command: str = None) -> str:
        """
        Startet Countdown.

        Args:
            name: Name des Countdowns
            duration: Dauer (HH:MM:SS, MM:SS, Xs, Xm, Xh)
            after_command: Optionaler Befehl bei Ablauf
        """
        try:
            seconds = self._parse_duration(duration)
        except (ValueError, TypeError):
            return f"[COUNTDOWN] Ungueltiges Format: {duration}"

        end_time = datetime.now() + timedelta(seconds=seconds)

        self.state["countdowns"][name] = {
            "end_time": end_time.isoformat(),
            "after_command": after_command,
            "paused": False,
            "remaining_on_pause": None
        }
        self._save_state()

        formatted = self._format_remaining(seconds)
        msg = f"[COUNTDOWN] '{name}' gestartet: {formatted}"
        if after_command:
            msg += f"\n  Bei Ablauf: {after_command}"
        return msg

    def stop(self, name: str) -> str:
        """Stoppt Countdown."""
        if name not in self.state["countdowns"]:
            return f"[COUNTDOWN] '{name}' nicht gefunden"

        del self.state["countdowns"][name]
        self._save_state()
        return f"[COUNTDOWN] '{name}' abgebrochen"

    def pause(self, name: str) -> str:
        """Pausiert Countdown."""
        if name not in self.state["countdowns"]:
            return f"[COUNTDOWN] '{name}' nicht gefunden"

        cd = self.state["countdowns"][name]
        if cd["paused"]:
            return f"[COUNTDOWN] '{name}' ist bereits pausiert"

        # Verbleibende Zeit speichern
        end_time = datetime.fromisoformat(cd["end_time"])
        remaining = (end_time - datetime.now()).total_seconds()

        cd["paused"] = True
        cd["remaining_on_pause"] = max(0, int(remaining))
        self._save_state()

        return f"[COUNTDOWN] '{name}' pausiert ({self._format_remaining(int(remaining))} verbleibend)"

    def resume(self, name: str) -> str:
        """Setzt Countdown fort."""
        if name not in self.state["countdowns"]:
            return f"[COUNTDOWN] '{name}' nicht gefunden"

        cd = self.state["countdowns"][name]
        if not cd["paused"]:
            return f"[COUNTDOWN] '{name}' ist nicht pausiert"

        # Neue End-Zeit berechnen
        remaining = cd.get("remaining_on_pause", 0)
        cd["end_time"] = (datetime.now() + timedelta(seconds=remaining)).isoformat()
        cd["paused"] = False
        cd["remaining_on_pause"] = None
        self._save_state()

        return f"[COUNTDOWN] '{name}' fortgesetzt ({self._format_remaining(remaining)} verbleibend)"

    def list_countdowns(self) -> str:
        """Listet alle Countdowns."""
        countdowns = self.state["countdowns"]

        if not countdowns:
            return "[COUNTDOWN] Keine aktiven Countdowns"

        lines = ["[COUNTDOWN] Aktive Countdowns:"]
        now = datetime.now()

        for name, cd in countdowns.items():
            if cd["paused"]:
                remaining = cd.get("remaining_on_pause", 0)
                formatted = self._format_remaining(remaining)
                lines.append(f"  {name}: {formatted} (PAUSIERT)")
            else:
                end_time = datetime.fromisoformat(cd["end_time"])
                remaining = int((end_time - now).total_seconds())
                formatted = self._format_remaining(remaining)

                if remaining < 0:
                    lines.append(f"  {name}: ABGELAUFEN!")
                elif remaining < 300:  # < 5 Min Warnung
                    lines.append(f"  {name}: {formatted} [!]")
                else:
                    lines.append(f"  {name}: {formatted}")

        return "\n".join(lines)

    def check_expired(self) -> List[Tuple[str, str]]:
        """
        Prueft auf abgelaufene Countdowns.

        Returns:
            Liste von (name, after_command) Tupeln
        """
        expired = []
        now = datetime.now()

        for name, cd in list(self.state["countdowns"].items()):
            if cd["paused"]:
                continue

            end_time = datetime.fromisoformat(cd["end_time"])
            if now >= end_time:
                expired.append((name, cd.get("after_command")))
                del self.state["countdowns"][name]

        if expired:
            self._save_state()

        return expired

    def get_display(self) -> Optional[str]:
        """
        Gibt kompakte Countdown-Anzeige fuer CLI-Output zurueck.

        Returns:
            String wie "focus 19:45 verbleibend" oder None
        """
        countdowns = self.state["countdowns"]
        if not countdowns:
            return None

        now = datetime.now()
        parts = []

        for name, cd in countdowns.items():
            if cd["paused"]:
                remaining = cd.get("remaining_on_pause", 0)
                formatted = self._format_remaining(remaining)
                parts.append(f"{name} {formatted} (PAUSE)")
            else:
                end_time = datetime.fromisoformat(cd["end_time"])
                remaining = int((end_time - now).total_seconds())
                formatted = self._format_remaining(remaining)

                if remaining < 0:
                    parts.append(f"{name} ABGELAUFEN!")
                elif remaining < 300:
                    parts.append(f"{name} {formatted} [!]")
                else:
                    parts.append(f"{name} {formatted} verbleibend")

        return " | ".join(parts) if parts else None


class BetweenManager:
    """
    Between-Checks mit Profilen.

    CLI: bach between on|off|status|use|profile
    """

    # Standard-Profile
    DEFAULT_PROFILES = {
        "default": {
            "name": "default",
            "description": "Generischer Between-Check",
            "message": "1. Zeit-Check: Noch im Limit?\n2. Memory OK? (--memory size)\n3. Naechste Aufgabe oder Shutdown?",
            "trigger_on": ["task done", "task complete"],
            "is_default": True
        },
        "focus": {
            "name": "focus",
            "description": "Minimaler Check fuer fokussierte Arbeit",
            "message": "Weitermachen oder Pause?",
            "trigger_on": ["task done"],
            "is_default": False
        },
        "review": {
            "name": "review",
            "description": "Ausfuehrlicher Check mit Code-Review Hinweisen",
            "message": "1. Code reviewen\n2. Tests laufen?\n3. Dokumentiert?",
            "trigger_on": ["task done", "commit"],
            "is_default": False
        },
        "learning": {
            "name": "learning",
            "description": "Check mit Reflexionsfragen",
            "message": "1. Was gelernt?\n2. Lesson anlegen?\n3. Verstanden?",
            "trigger_on": ["task done", "research done"],
            "is_default": False
        },
        "autosession": {
            "name": "autosession",
            "description": "Auto-Session Workflow mit Zeitkontrolle",
            "message": """--- BETWEEN-TASK CHECK ---
1. ZEIT-CHECK: bach beat (Restzeit pruefen)
2. DAUER: Wie lange hat letzte Aufgabe gedauert?
3. ENTSCHEIDUNG:
   - Restzeit > Aufgabendauer + 3min? -> Naechste Aufgabe
   - Sonst -> Weiter zu SESSION-ENDE

DENKANSTOSS:
- Planen und Zerlegen kann deine Aufgabe sein!
- Du musst nicht fertig werden, nur dokumentieren wo du warst!
---""",
            "trigger_on": ["task done", "task complete", "commit", "done"],
            "is_default": False
        }
    }

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.state_file = base_path / "data" / ".between_state"
        self.state = self._load_state()
        self._init_db_profiles()

    def _load_state(self) -> dict:
        """Laedt Zustand aus Datei."""
        default = {
            "enabled": True,
            "active_profile": "default"
        }
        if self.state_file.exists():
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                default.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def _save_state(self) -> None:
        """Speichert Zustand."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self.state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError:
            pass

    def _init_db_profiles(self) -> None:
        """Initialisiert Standard-Profile in DB falls nicht vorhanden."""
        try:
            import sqlite3
            db_path = self.base_path / "data" / "bach.db"
            if not db_path.exists():
                return

            conn = sqlite3.connect(str(db_path))

            # Tabelle erstellen falls nicht vorhanden
            conn.execute("""
                CREATE TABLE IF NOT EXISTS between_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    message TEXT NOT NULL,
                    trigger_on TEXT,
                    is_default INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)

            # Standard-Profile einfuegen
            for profile in self.DEFAULT_PROFILES.values():
                conn.execute("""
                    INSERT OR IGNORE INTO between_profiles
                    (name, description, message, trigger_on, is_default)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    profile["name"],
                    profile["description"],
                    profile["message"],
                    json.dumps(profile["trigger_on"]),
                    1 if profile["is_default"] else 0
                ))

            conn.commit()
            conn.close()
        except Exception:
            pass

    def enable(self, enabled: bool = True) -> str:
        """Aktiviert/deaktiviert Between-Checks."""
        self.state["enabled"] = enabled
        self._save_state()
        status = "aktiviert" if enabled else "deaktiviert"
        return f"[BETWEEN] Between-Checks {status}"

    def use_profile(self, profile_name: str) -> str:
        """Aktiviert ein Profil fuer die Session."""
        # Profil aus DB laden
        profile = self._get_profile(profile_name)
        if not profile:
            return f"[BETWEEN] Profil '{profile_name}' nicht gefunden"

        self.state["active_profile"] = profile_name
        self._save_state()
        return f"[BETWEEN] Profil '{profile_name}' aktiviert"

    def _get_profile(self, name: str) -> Optional[dict]:
        """Laedt Profil aus DB oder Fallback."""
        try:
            import sqlite3
            db_path = self.base_path / "data" / "bach.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM between_profiles WHERE name = ?", (name,)
                ).fetchone()
                conn.close()

                if row:
                    return {
                        "name": row["name"],
                        "description": row["description"],
                        "message": row["message"],
                        "trigger_on": json.loads(row["trigger_on"] or "[]"),
                        "is_default": bool(row["is_default"])
                    }
        except Exception:
            pass

        # Fallback auf DEFAULT_PROFILES
        return self.DEFAULT_PROFILES.get(name)

    def get_active_message(self) -> str:
        """Gibt die aktive Between-Message zurueck."""
        profile_name = self.state.get("active_profile", "default")
        profile = self._get_profile(profile_name)

        if profile:
            return profile["message"]
        return self.DEFAULT_PROFILES["default"]["message"]

    def check(self, last_command: str = "") -> Optional[str]:
        """
        Prueft ob Between-Check ausgegeben werden soll.

        Args:
            last_command: Letzter ausgefuehrter Befehl

        Returns:
            Between-Message oder None
        """
        if not self.state["enabled"]:
            return None

        profile_name = self.state.get("active_profile", "default")
        profile = self._get_profile(profile_name)

        if not profile:
            return None

        # Trigger pruefen
        triggers = profile.get("trigger_on", [])
        last_lower = last_command.lower()

        for trigger in triggers:
            if trigger.lower() in last_lower:
                return f"[BETWEEN-TASKS]\n{profile['message']}\n\nTipp: --status fuer Uebersicht"

        return None

    def list_profiles(self) -> str:
        """Listet alle verfuegbaren Profile."""
        lines = ["[BETWEEN] Verfuegbare Profile:"]

        try:
            import sqlite3
            db_path = self.base_path / "data" / "bach.db"
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT name, description, is_default FROM between_profiles").fetchall()
                conn.close()

                for row in rows:
                    default_marker = " [DEFAULT]" if row["is_default"] else ""
                    active_marker = " <-- AKTIV" if row["name"] == self.state.get("active_profile") else ""
                    lines.append(f"  {row['name']}: {row['description']}{default_marker}{active_marker}")

                return "\n".join(lines)
        except Exception:
            pass

        # Fallback
        for name, profile in self.DEFAULT_PROFILES.items():
            active_marker = " <-- AKTIV" if name == self.state.get("active_profile") else ""
            lines.append(f"  {name}: {profile['description']}{active_marker}")

        return "\n".join(lines)

    def status(self) -> str:
        """Gibt Status-String zurueck."""
        enabled = "AN" if self.state["enabled"] else "AUS"
        profile = self.state.get("active_profile", "default")
        return f"Between: {enabled} | Profil: {profile}"


class TimeManager:
    """
    Zentraler Manager fuer alle Zeit-Funktionen.

    Vereint Clock, Timer, Countdown, Between.
    CLI: bach beat
    """

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.clock = ClockModule(base_path)
        self.timer = TimerModule(base_path)
        self.countdown = CountdownModule(base_path)
        self.between = BetweenManager(base_path)

    def get_beat(self) -> str:
        """
        Gibt unified Zeit-Anzeige zurueck.

        Format:
        [BEAT] 14:35
          Timer:     Session 45:12 | Recherche 05:23
          Countdown: focus 19:45 verbleibend
          Between:   Profil "default" aktiv
        """
        now = datetime.now()
        lines = [f"[BEAT] {now.strftime('%H:%M')}"]

        # Timer
        timer_display = self.timer.get_display()
        if timer_display:
            lines.append(f"  Timer:     {timer_display}")
        else:
            lines.append("  Timer:     -")

        # Countdown
        countdown_display = self.countdown.get_display()
        if countdown_display:
            lines.append(f"  Countdown: {countdown_display}")
        else:
            lines.append("  Countdown: -")

        # Between
        between_status = self.between.status()
        lines.append(f"  {between_status}")

        return "\n".join(lines)

    def enable_all(self) -> str:
        """Aktiviert alle Zeit-Anzeigen."""
        self.clock.enable(True)
        self.between.enable(True)
        return "[BEAT] Alle Zeit-Anzeigen aktiviert"

    def disable_all(self) -> str:
        """Deaktiviert alle Zeit-Anzeigen."""
        self.clock.enable(False)
        self.between.enable(False)
        return "[BEAT] Alle Zeit-Anzeigen deaktiviert"

    def set_interval(self, seconds: int) -> str:
        """Setzt globales Intervall."""
        self.clock.set_interval(seconds)
        return f"[BEAT] Globales Intervall: {seconds}s"

    def check_all(self) -> List[str]:
        """
        Prueft alle Zeit-Funktionen und gibt Ausgaben zurueck.

        Bei abgelaufenen Countdowns mit --after Befehl wird dieser
        automatisch via subprocess.Popen ausgefuehrt.

        Returns:
            Liste von Ausgabe-Strings
        """
        outputs = []

        # Clock
        clock_output = self.clock.check()
        if clock_output:
            outputs.append(clock_output)

        # Timer (immer anzeigen wenn aktiv)
        timer_display = self.timer.get_display()
        if timer_display:
            outputs.append(f"[TIMER] {timer_display}")

        # Countdown (pruefen auf Ablauf)
        expired = self.countdown.check_expired()
        for name, command in expired:
            outputs.append(f"[COUNTDOWN] '{name}' ABGELAUFEN!")
            if command:
                outputs.append(f"[COUNTDOWN] Timer abgelaufen - Fuehre aus: {command}")
                self._execute_after_command(command)

        # Aktive Countdowns mit Warnung
        countdown_display = self.countdown.get_display()
        if countdown_display and "[!]" in countdown_display:
            outputs.append(f"[!] {countdown_display}")

        return outputs

    def _execute_after_command(self, command: str) -> None:
        """
        Fuehrt einen --after Befehl asynchron aus.

        Der Befehl wird als 'python bach.py <command>' gestartet.
        Verwendet subprocess.Popen fuer nicht-blockierende Ausfuehrung.

        Args:
            command: Der auszufuehrende BACH-Befehl (z.B. "--shutdown")
        """
        import subprocess
        import sys

        try:
            bach_py = self.base_path / "bach.py"
            if not bach_py.exists():
                return

            cmd_parts = command.split()
            full_cmd = [sys.executable, str(bach_py)] + cmd_parts

            # Windows: CREATE_NO_WINDOW Flag um kein extra Fenster zu oeffnen
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = 0x08000000  # CREATE_NO_WINDOW

            subprocess.Popen(
                full_cmd,
                cwd=str(self.base_path),
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass  # Silent fail - Fehler nicht an den Aufrufer propagieren
