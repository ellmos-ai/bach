#!/usr/bin/env python3
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
BACH Mistral Watcher Daemon v1.0
=================================
Always-on Hintergrund-Prozess der Events via Mistral klassifiziert
und bei Bedarf Claude Code Sessions startet.

Usage:
  python watcher_daemon.py                # Starten
  python watcher_daemon.py --stop         # Stoppen
  python watcher_daemon.py --status       # Status anzeigen

Erstellt: 2026-02-10
"""

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path
from threading import Event

# ============ PFADE ============

WATCHER_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = WATCHER_DIR.parent
HUB_DIR = SERVICES_DIR.parent
BACH_DIR = HUB_DIR.parent

CONFIG_FILE = WATCHER_DIR / "config.json"
PID_FILE = WATCHER_DIR / "watcher.pid"
LOG_FILE = BACH_DIR / "data" / "logs" / "watcher_daemon.log"
DB_PATH = BACH_DIR / "data" / "bach.db"

# Daemon-Pfade (fuer Claude-Trigger)
DAEMON_DIR = SERVICES_DIR / "daemon"
AUTO_SESSION = DAEMON_DIR / "auto_session.py"

# ============ LOGGING ============

def log(msg: str, level: str = "INFO"):
    """Logging in Datei und Console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ============ CONFIG ============

def load_config() -> dict:
    """Laedt Watcher-Konfiguration."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"enabled": True, "poll_interval_seconds": 15}

# ============ PID MANAGEMENT ============

def _is_process_running(pid: int) -> bool:
    """Prueft ob ein Prozess laeuft (Windows-kompatibel)."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

def get_running_pid() -> int:
    """Gibt PID des laufenden Daemons zurueck, oder 0."""
    if not PID_FILE.exists():
        return 0
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        if _is_process_running(pid):
            return pid
        PID_FILE.unlink()
        return 0
    except (ValueError, Exception):
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        return 0

def stop_daemon() -> bool:
    """Stoppt laufende Instanz."""
    pid = get_running_pid()
    if pid == 0:
        print("Kein Watcher-Daemon laeuft.")
        return True

    if pid == os.getpid():
        return True

    log(f"Stoppe Watcher-Daemon (PID {pid})...")
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if _is_process_running(pid):
                os.kill(pid, signal.SIGKILL)
        log("Watcher-Daemon gestoppt")
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        return True
    except Exception as e:
        log(f"Fehler beim Stoppen: {e}", "ERROR")
        return False

def write_pid():
    """Schreibt PID-Datei."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

# ============ QUIET HOURS ============

def is_quiet_time(config: dict) -> bool:
    """Prueft ob Ruhezeit aktiv ist."""
    if not config.get("respect_quiet_hours", True):
        return False
    quiet_start = config.get("quiet_start", "23:00")
    quiet_end = config.get("quiet_end", "07:00")
    try:
        now = datetime.now()
        start_h, start_m = map(int, quiet_start.split(":"))
        end_h, end_m = map(int, quiet_end.split(":"))
        start = now.replace(hour=start_h, minute=start_m, second=0)
        end = now.replace(hour=end_h, minute=end_m, second=0)
        if start > end:
            return now >= start or now < end
        return start <= now < end
    except Exception:
        return False

# ============ CLAUDE SESSION ============

def is_claude_online() -> bool:
    """Prueft ob Claude bereits eine aktive Session hat."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT COUNT(*) FROM partner_presence "
            "WHERE partner_name='claude' AND status='online'"
        ).fetchone()
        conn.close()
        return row and row[0] > 0
    except Exception:
        return False

def is_screen_locked() -> bool:
    """Prueft ob Bildschirm gesperrt ist (Windows)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        return hwnd == 0
    except Exception:
        return False

def trigger_claude_session(profile: str = "ati") -> bool:
    """Triggert Claude-Session via auto_session.py."""
    if not AUTO_SESSION.exists():
        log("auto_session.py nicht gefunden!", "ERROR")
        return False

    log(f"Starte Claude-Session (Profil: {profile})...")
    try:
        creation_flags = 0x08000000 if sys.platform == "win32" else 0
        result = subprocess.run(
            [sys.executable, str(AUTO_SESSION), "--profile", profile],
            cwd=str(DAEMON_DIR),
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=creation_flags
        )
        if result.returncode == 0:
            log("Claude-Session gestartet")
            return True
        else:
            log(f"Session-Fehler: {result.stderr[:200]}", "ERROR")
            return False
    except subprocess.TimeoutExpired:
        log("Session-Trigger Timeout (>60s)", "ERROR")
        return False
    except Exception as e:
        log(f"Session-Trigger Fehler: {e}", "ERROR")
        return False

# ============ STATUS ============

def show_status():
    """Zeigt Watcher-Status."""
    pid = get_running_pid()
    config = load_config()

    print("\n" + "=" * 50)
    print("BACH WATCHER DAEMON STATUS")
    print("=" * 50)

    if pid:
        print(f"[OK] Daemon laeuft (PID {pid})")
    else:
        print("[--] Daemon laeuft nicht")

    print(f"\nConfig:")
    print(f"  Enabled:      {config.get('enabled', True)}")
    print(f"  Poll-Intervall: {config.get('poll_interval_seconds', 15)}s")
    print(f"  Ruhezeit:     {config.get('quiet_start', '23:00')} - {config.get('quiet_end', '07:00')}")
    print(f"  Modell:       {config.get('mistral_model', 'Mistral:latest')}")
    print(f"  Max Escalations/Tag: {config.get('max_daily_escalations', 20)}")

    sources = config.get("sources", {})
    print(f"\nEvent Sources:")
    for name, src in sources.items():
        status = "[ON]" if src.get("enabled", False) else "[OFF]"
        print(f"  {status} {name}")

    # Event-Log Statistik
    try:
        conn = sqlite3.connect(str(DB_PATH))
        today = date.today().isoformat()
        stats = conn.execute(
            "SELECT action, COUNT(*) FROM watcher_event_log "
            "WHERE created_at >= ? GROUP BY action",
            (today,)
        ).fetchall()
        conn.close()
        if stats:
            print(f"\nHeute klassifiziert:")
            for action, count in stats:
                print(f"  {action}: {count}")
    except Exception:
        pass

    # Letzte Logs
    if LOG_FILE.exists():
        print(f"\nLetzte Log-Eintraege:")
        try:
            lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
            for line in lines[-5:]:
                print(f"  {line}")
        except Exception:
            pass

    print("=" * 50)

# ============ MAIN DAEMON ============

class WatcherDaemon:
    """Haupt-Daemon-Klasse."""

    def __init__(self):
        self.config = load_config()
        self.stop_event = Event()
        self.classifier = None
        self.responder = None
        self.sources = []
        self._escalation_count_today = 0
        self._escalation_date = date.today()
        self._last_escalation_time = 0.0

    def _init_components(self):
        """Initialisiert Classifier, Responder und Event Sources."""
        # sys.path fuer Imports setzen (noetig wenn als Subprocess gestartet)
        import sys
        bach_str = str(BACH_DIR)
        if bach_str not in sys.path:
            sys.path.insert(0, bach_str)
        watcher_str = str(WATCHER_DIR)
        if watcher_str not in sys.path:
            sys.path.insert(0, watcher_str)

        from classifier import MistralClassifier
        from responder import DirectResponder
        from event_sources import (
            ConnectorEventSource, TaskQueueEventSource,
            FileSystemEventSource, ScheduledEventSource
        )

        self.classifier = MistralClassifier(BACH_DIR)
        self.responder = DirectResponder(DB_PATH)

        sources_config = self.config.get("sources", {})

        source_map = {
            "connector_messages": ConnectorEventSource,
            "task_queue": TaskQueueEventSource,
            "filesystem": FileSystemEventSource,
            "scheduled": ScheduledEventSource,
        }

        for name, cls in source_map.items():
            src_config = sources_config.get(name, {})
            source = cls(BACH_DIR, DB_PATH, src_config)
            if source.is_enabled():
                self.sources.append((name, source))
                log(f"Event Source aktiviert: {name}")

    def _check_escalation_limits(self) -> bool:
        """Prueft ob Escalation erlaubt ist."""
        now = time.time()
        today = date.today()

        # Tages-Reset
        if today > self._escalation_date:
            self._escalation_count_today = 0
            self._escalation_date = today

        # Tages-Limit
        max_daily = self.config.get("max_daily_escalations", 20)
        if self._escalation_count_today >= max_daily:
            log(f"Tages-Limit erreicht ({max_daily} Escalations)", "WARN")
            return False

        # Cooldown
        cooldown = self.config.get("escalation_cooldown_seconds", 300)
        if now - self._last_escalation_time < cooldown:
            remaining = int(cooldown - (now - self._last_escalation_time))
            log(f"Escalation-Cooldown aktiv (noch {remaining}s)", "INFO")
            return False

        return True

    def _handle_event(self, event, source_name: str):
        """Verarbeitet ein einzelnes Event."""
        from classifier import EventAction

        result = self.classifier.classify(event)
        response_sent = ""

        if result.action == EventAction.RESPOND_DIRECT:
            response_text = result.direct_response
            if not response_text:
                response_text = self.classifier.generate_response(event)
            if response_text and self.responder.respond(event, response_text):
                response_sent = response_text
                log(f"DIRECT: {event.sender} -> {response_text[:60]}")
            else:
                log(f"DIRECT: Konnte nicht antworten an {event.sender}")

        elif result.action == EventAction.ESCALATE_CLAUDE:
            if self._check_escalation_limits():
                escalation_config = self.config.get("escalation", {})
                check_running = escalation_config.get("check_claude_running", True)

                if check_running and is_claude_online():
                    log(f"ESCALATE: Claude bereits online - Event gequeued")
                elif is_screen_locked():
                    log(f"ESCALATE: Bildschirm gesperrt - Event gequeued")
                else:
                    profile = result.escalation_profile or escalation_config.get("default_profile", "ati")
                    if trigger_claude_session(profile):
                        self._escalation_count_today += 1
                        self._last_escalation_time = time.time()
                        log(f"ESCALATE: Claude-Session gestartet (Profil: {profile})")
                    else:
                        log(f"ESCALATE: Session-Start fehlgeschlagen", "ERROR")

        elif result.action == EventAction.LOG_ONLY:
            log(f"LOG: {event.source}/{event.sender}: {event.content[:60]}")

        elif result.action == EventAction.IGNORE:
            log(f"IGNORE: {event.source}/{event.sender}")

        # Event loggen
        self.responder.log_event(event, result, response_sent)

        # Connector-Nachricht als klassifiziert markieren
        if source_name == "connector_messages" and event.source_id:
            from event_sources import ConnectorEventSource
            for name, src in self.sources:
                if isinstance(src, ConnectorEventSource):
                    src.mark_classified(event.source_id)
                    break

    def run(self):
        """Hauptschleife des Daemons."""
        # Alte Instanz stoppen
        old_pid = get_running_pid()
        if old_pid and old_pid != os.getpid():
            stop_daemon()

        write_pid()
        log("=" * 40)
        log("BACH Watcher Daemon gestartet")
        log("=" * 40)

        # Signal-Handler
        def handle_signal(signum, frame):
            log("Shutdown-Signal empfangen")
            self.stop_event.set()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        # Komponenten initialisieren
        self._init_components()

        if not self.sources:
            log("Keine Event Sources aktiviert! Pruefe config.json", "WARN")

        # Ollama pruefen
        if self.classifier.is_available():
            log(f"Mistral verfuegbar ({self.classifier.MODEL})")
            warmup_dur = self.classifier.warmup()
            log(f"Warmup: {warmup_dur:.1f}s")
        else:
            log("WARNUNG: Mistral/Ollama nicht verfuegbar!", "WARN")

        poll_interval = self.config.get("poll_interval_seconds", 15)
        max_per_cycle = self.config.get("max_events_per_cycle", 10)

        log(f"Poll-Intervall: {poll_interval}s, Max Events/Zyklus: {max_per_cycle}")
        log(f"Aktive Sources: {[n for n, _ in self.sources]}")

        # Hauptschleife
        while not self.stop_event.is_set():
            try:
                # Quiet Hours pruefen
                if is_quiet_time(self.config):
                    self.stop_event.wait(60)
                    continue

                # Ollama-Check (einmal pro Zyklus)
                if not self.classifier.is_available():
                    log("Mistral nicht verfuegbar, warte...", "WARN")
                    self.stop_event.wait(30)
                    continue

                # Alle Sources pollen
                total_events = 0
                for source_name, source in self.sources:
                    if self.stop_event.is_set():
                        break

                    events = source.poll()
                    for event in events[:max_per_cycle - total_events]:
                        if self.stop_event.is_set():
                            break
                        self._handle_event(event, source_name)
                        total_events += 1

                    if total_events >= max_per_cycle:
                        break

                if total_events > 0:
                    log(f"Zyklus: {total_events} Events verarbeitet")

            except Exception as e:
                log(f"Fehler im Hauptloop: {e}", "ERROR")

            # Warten bis zum naechsten Zyklus
            self.stop_event.wait(poll_interval)

        # Aufraumen
        log("Watcher Daemon wird beendet...")
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        log("Watcher Daemon beendet")

# ============ CLI ============

def main():
    """CLI-Einstiegspunkt."""
    if "--stop" in sys.argv:
        stop_daemon()
        return

    if "--status" in sys.argv:
        show_status()
        return

    # Daemon starten
    daemon = WatcherDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
