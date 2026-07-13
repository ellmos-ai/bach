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
BACH Session Daemon v1.1 [DEPRECATED]
======================================
⚠️  DEPRECATED seit 2026-05-17.
    Grund: Nutzt pyautogui-basierte GUI-Automation um Prompts in aktive
    Claude-Sessions zu injizieren. Erzeugt "Zombie-Prompt"-Verhalten.

    ERSATZ: Browser-basierte Task-Delegation über:
    - BACH GUI Dashboard (:8000) → Daemon-Tab für Task-Management
    - Buddha Control API (:8081/api/chat) für Background-Delegation
    - Claude Code /loop oder /schedule für wiederkehrende Tasks

    Dieser Daemon sollte NICHT mehr gestartet werden.
    Config (config.json) ist auf enabled=false gesetzt.

EHEMALIGER ZWECK:
  System-Service fuer automatische Claude-Sessions via pyautogui.

Usage (DEPRECATED):
  python session_daemon.py                    # Startet mit default Profil
  python session_daemon.py --profile ati      # ATI-Profil
  python session_daemon.py --profile wartung  # Wartungs-Profil
  python session_daemon.py --interval 30      # Alle 30 Minuten
  python session_daemon.py --stop             # Beendet Daemon
  python session_daemon.py --status           # Zeigt Status

Prompt-Profile:
  Profile werden in hub/_services/daemon/profiles/ definiert.
  Jedes Profil hat eigene Tasks, Prompts und Konfiguration.
"""

import time
import sys
import os
import json
import subprocess
import signal
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread, Event

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# ============ PFADE ============

DAEMON_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = DAEMON_DIR.parent
SKILLS_DIR = SERVICES_DIR.parent
BACH_DIR = SKILLS_DIR.parent

# Konfiguration
CONFIG_FILE = DAEMON_DIR / "config.json"
PROFILES_DIR = DAEMON_DIR / "profiles"
CONTROL_DIR = DAEMON_DIR / "control"
PID_FILE = DAEMON_DIR / "daemon.pid"
LOG_FILE = BACH_DIR / "data" / "logs" / "session_daemon.log"

# Datenbanken
USER_DB = BACH_DB

# Defaults
DEFAULT_INTERVAL = 30
DEFAULT_QUIET_START = "22:00"
DEFAULT_QUIET_END = "08:00"
DEFAULT_PROFILE = "ati"
DEFAULT_MAX_SESSIONS = 0  # 0 = unbegrenzt

# Session-Counter (v1.1.45)
sessions_generated = 0

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
    except OSError:
        pass

# ============ CONFIG ============

def load_config() -> dict:
    """Laedt Daemon-Konfiguration."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "enabled": True,
        "quiet_start": DEFAULT_QUIET_START,
        "quiet_end": DEFAULT_QUIET_END,
        "ignore_quiet": False,
        "jobs": [
            {
                "profile": DEFAULT_PROFILE,
                "interval_minutes": DEFAULT_INTERVAL,
                "enabled": True,
                "last_run": None
            }
        ]
    }

def save_config(config: dict):
    """Speichert Config."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

def load_profile(name: str) -> dict:
    """Laedt ein Prompt-Profil."""
    profile_file = PROFILES_DIR / f"{name}.json"
    if profile_file.exists():
        try:
            return json.loads(profile_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: ATI-Profil
    return {
        "name": name,
        "description": f"Profil: {name}",
        "task_source": "ati_tasks",  # oder "tasks" fuer BACH-Tasks
        "task_filter": {"status": "offen"},
        "max_tasks": 3,
        "timeout_minutes": 15,
        "prompt_template": "default"
    }


def _profile_slug(name: str) -> str:
    """Normalisiert Profilnamen fuer Control-Dateien."""
    cleaned = []
    for char in (name or DEFAULT_PROFILE):
        if char.isalnum() or char in {"-", "_"}:
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned) or DEFAULT_PROFILE


def _pause_file(profile_name: str) -> Path:
    return CONTROL_DIR / f"{_profile_slug(profile_name)}.pause.json"


def _steer_file(profile_name: str) -> Path:
    return CONTROL_DIR / f"{_profile_slug(profile_name)}.steer.json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def request_pause(profile_name: str, reason: str = "Manuell pausiert") -> dict:
    """Merkt eine Pause fuer ein Profil vor."""
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": profile_name,
        "reason": reason,
        "requested_at": datetime.now().isoformat(),
    }
    _pause_file(profile_name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def clear_pause(profile_name: str):
    """Hebt eine vorgemerkte Pause fuer ein Profil auf."""
    _pause_file(profile_name).unlink(missing_ok=True)


def get_pause_request(profile_name: str) -> dict | None:
    """Liest eine vorgemerkte Pause fuer ein Profil."""
    payload = _read_json(_pause_file(profile_name), None)
    if isinstance(payload, dict) and payload.get("reason"):
        return payload
    return None


def peek_steer_requests(profile_name: str) -> list[dict]:
    """Zeigt vorgemerkte Operator-Hinweise, ohne sie zu verbrauchen."""
    payload = _read_json(_steer_file(profile_name), [])
    if isinstance(payload, list):
        normalized = []
        for item in payload:
            if isinstance(item, dict) and item.get("message"):
                normalized.append(item)
        return normalized
    return []


def request_steer(profile_name: str, message: str) -> list[dict]:
    """Haengt einen Operator-Hinweis an die Steuer-Queue eines Profils."""
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    requests = peek_steer_requests(profile_name)
    requests.append(
        {
            "profile": profile_name,
            "message": message,
            "requested_at": datetime.now().isoformat(),
        }
    )
    _steer_file(profile_name).write_text(
        json.dumps(requests, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return requests


def consume_steer_requests(profile_name: str) -> list[dict]:
    """Liest und leert Operator-Hinweise fuer ein Profil."""
    requests = peek_steer_requests(profile_name)
    _steer_file(profile_name).unlink(missing_ok=True)
    return requests


def clear_steer_requests(profile_name: str) -> int:
    """Loescht vorgemerkte Operator-Hinweise fuer ein Profil."""
    requests = peek_steer_requests(profile_name)
    _steer_file(profile_name).unlink(missing_ok=True)
    return len(requests)

# ============ DAEMON CONTROL ============

def get_running_pid() -> int:
    """Gibt PID des laufenden Daemons zurueck, oder 0."""
    if not PID_FILE.exists():
        return 0
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError, PermissionError):
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return 0

def stop_old_daemon() -> bool:
    """Stoppt alte Instanz falls vorhanden."""
    pid = get_running_pid()
    if pid == 0:
        return True

    if pid == os.getpid():
        return True

    log(f"Stoppe alte Instanz (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        log("Alte Instanz gestoppt")
        return True
    except Exception as e:
        log(f"Fehler beim Stoppen: {e}", "ERROR")
        return False

def write_pid():
    """Schreibt PID-Datei."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

def show_status():
    """Zeigt Daemon-Status."""
    pid = get_running_pid()
    config = load_config()

    print("\n" + "=" * 50)
    print("BACH SESSION DAEMON STATUS")
    print("=" * 50)

    if pid:
        print(f"[OK] Daemon laeuft (PID {pid})")
    else:
        print("[--] Daemon laeuft nicht")

    print(f"\nConfig:")
    print(f"  Enabled:      {config.get('enabled', True)}")
    print(f"  Ruhezeit:     {config.get('quiet_start', DEFAULT_QUIET_START)} - {config.get('quiet_end', DEFAULT_QUIET_END)}")
    print(f"  Ignore Quiet: {config.get('ignore_quiet', False)}")

    print(f"\nJobs:")
    for job in config.get("jobs", []):
        status = "[ON]" if job.get("enabled", True) else "[OFF]"
        last = job.get("last_run", "nie")
        if last and last != "nie":
            try:
                dt = datetime.fromisoformat(last)
                last = dt.strftime("%d.%m. %H:%M")
            except (ValueError, TypeError): pass
        profile_name = job.get("profile", "?")
        controls = []
        pause_request = get_pause_request(profile_name)
        steer_requests = peek_steer_requests(profile_name)
        if pause_request:
            controls.append(f"PAUSE: {pause_request.get('reason', 'Manuell pausiert')}")
        if steer_requests:
            controls.append(f"STEER: {len(steer_requests)}")
        suffix = f" | {'; '.join(controls)}" if controls else ""
        print(
            f"  {status} {profile_name:12} - Alle {job.get('interval_minutes', '?'):3} Min "
            f"(Zuletzt: {last}){suffix}"
        )

    # Profile auflisten
    print(f"\nVerfuegbare Profile Dateien:")
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    for p in PROFILES_DIR.glob("*.json"):
        print(f"  - {p.stem}")

    if LOG_FILE.exists():
        print(f"\nLetzte Log-Eintraege:")
        lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[-5:]:
            print(f"  {line}")

    print("=" * 50)

# ============ QUIET HOURS ============

def is_quiet_time(quiet_start: str, quiet_end: str) -> bool:
    """Prueft ob Ruhezeit aktiv ist."""
    if not quiet_start or not quiet_end:
        return False
    try:
        now = datetime.now()
        start_h, start_m = map(int, quiet_start.split(":"))
        end_h, end_m = map(int, quiet_end.split(":"))

        start = now.replace(hour=start_h, minute=start_m, second=0)
        end = now.replace(hour=end_h, minute=end_m, second=0)

        if start > end:
            return now >= start or now < end
        return start <= now < end
    except (ValueError, TypeError):
        return False

# ============ TASK COUNTING ============

def count_tasks(profile: dict) -> int:
    """Zaehlt offene Tasks basierend auf Profil."""
    task_source = profile.get("task_source", "ati_tasks")

    try:
        import sqlite3

        if task_source == "ati_tasks":
            conn = sqlite3.connect(USER_DB)
            count = conn.execute(
                "SELECT COUNT(*) FROM ati_tasks WHERE status = 'offen'"
            ).fetchone()[0]
        else:
            conn = sqlite3.connect(BACH_DB)
            count = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'open'"
            ).fetchone()[0]

        conn.close()
        return count
    except Exception:
        return 0

# ============ SESSION TRIGGER ============

def trigger_session(profile_name: str, operator_steer: list[dict] | None = None) -> bool:
    """Triggert Claude-Session mit Profil."""
    auto_session = DAEMON_DIR / "auto_session.py"

    if not auto_session.exists():
        log("auto_session.py nicht gefunden!", "ERROR")
        return False

    log(f"Starte Session mit Profil '{profile_name}'...")
    try:
        creation_flags = 0x08000000 if sys.platform == "win32" else 0
        env = dict(os.environ)
        if operator_steer:
            env["BACH_SESSION_OPERATOR_STEER"] = json.dumps(
                operator_steer,
                ensure_ascii=False,
            )

        result = subprocess.run(
            [sys.executable, str(auto_session), "--profile", profile_name],
            cwd=str(DAEMON_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8', errors='replace',
            timeout=60,
            creationflags=creation_flags,
            env=env,
        )

        if result.returncode == 0:
            log("Session erfolgreich gestartet")
            for line in result.stdout.strip().split('\n')[-5:]:
                if line.strip():
                    log(f"  {line.strip()}")
            return True
        else:
            log(f"Session-Fehler: {result.stderr}", "ERROR")
            return False

    except subprocess.TimeoutExpired:
        log("Session Timeout (>60s)", "ERROR")
        return False
    except Exception as e:
        log(f"Trigger-Fehler: {e}", "ERROR")
        return False

# ============ COUNTDOWN POLLING ============

def check_countdown_expiry():
    """
    Prueft ob Countdowns abgelaufen sind und fuehrt --after Befehle aus.

    Wird alle 30 Sekunden aus dem Daemon-Loop aufgerufen.
    Importiert CountdownModule aus tools.time_system und prueft auf
    abgelaufene Countdowns. Wenn ein abgelaufener Countdown einen
    --after Befehl hat, wird dieser via subprocess ausgefuehrt.
    """
    try:
        # Sicherstellen dass tools importierbar ist
        if str(BACH_DIR) not in sys.path:
            sys.path.insert(0, str(BACH_DIR))

        from tools.time_system import CountdownModule

        countdown = CountdownModule(BACH_DIR)
        expired = countdown.check_expired()

        for name, after_command in expired:
            log(f"[COUNTDOWN] '{name}' abgelaufen!")
            if after_command:
                log(f"[COUNTDOWN] Fuehre aus: {after_command}")
                _execute_countdown_command(after_command)
            else:
                log(f"[COUNTDOWN] '{name}' ohne --after Befehl - nur Benachrichtigung")

    except ImportError:
        pass  # time_system nicht verfuegbar - kein Fehler
    except Exception as e:
        log(f"[COUNTDOWN] Pruefung fehlgeschlagen: {e}", "ERROR")


def _execute_countdown_command(command: str):
    """
    Fuehrt einen --after Befehl aus einem abgelaufenen Countdown aus.

    Args:
        command: Der BACH-Befehl (z.B. "--shutdown", "session end")
    """
    bach_py = BACH_DIR / "bach.py"
    if not bach_py.exists():
        log(f"[COUNTDOWN] bach.py nicht gefunden: {bach_py}", "ERROR")
        return

    try:
        cmd_parts = command.split()
        full_cmd = [sys.executable, str(bach_py)] + cmd_parts

        # Windows: CREATE_NO_WINDOW Flag
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = 0x08000000  # CREATE_NO_WINDOW

        result = subprocess.run(
            full_cmd,
            cwd=str(BACH_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8', errors='replace',
            timeout=120,
            creationflags=creation_flags
        )

        if result.returncode == 0:
            log(f"[COUNTDOWN] Befehl erfolgreich: {command}")
            # Letzte Zeilen der Ausgabe loggen
            for line in result.stdout.strip().split('\n')[-3:]:
                if line.strip():
                    log(f"  {line.strip()}")
        else:
            log(f"[COUNTDOWN] Befehl fehlgeschlagen (rc={result.returncode}): {command}", "ERROR")
            if result.stderr:
                log(f"  stderr: {result.stderr[:200]}", "ERROR")

    except subprocess.TimeoutExpired:
        log(f"[COUNTDOWN] Timeout bei Befehl: {command}", "ERROR")
    except Exception as e:
        log(f"[COUNTDOWN] Ausfuehrungsfehler: {e}", "ERROR")


# ============ MAIN LOOP ============

def daemon_loop(stop_event: Event):
    """Hauptschleife fuer Multi-Job Management."""
    global sessions_generated

    log("Daemon Loop gestartet (Multi-Job Mode)")

    while not stop_event.is_set():
        try:
            config = load_config()

            if not config.get("enabled", True):
                log("Daemon global deaktiviert - warte 60s")
                stop_event.wait(60)
                continue

            quiet_start = config.get("quiet_start", DEFAULT_QUIET_START)
            quiet_end = config.get("quiet_end", DEFAULT_QUIET_END)
            ignore_quiet = config.get("ignore_quiet", False)

            if not ignore_quiet and is_quiet_time(quiet_start, quiet_end):
                log(f"Ruhezeit ({quiet_start}-{quiet_end}) - warte 60s")
                stop_event.wait(60)
                continue

            # Countdown-Ablauf pruefen (alle 30s)
            check_countdown_expiry()

            # Jobs abarbeiten
            config_changed = False
            for job in config.get("jobs", []):
                if not job.get("enabled", True):
                    continue

                profile_name = job.get("profile")
                interval = job.get("interval_minutes", DEFAULT_INTERVAL)
                last_run_str = job.get("last_run")

                now = datetime.now()
                should_run = False

                if not last_run_str:
                    should_run = True
                else:
                    try:
                        last_run = datetime.fromisoformat(last_run_str)
                        if now >= last_run + timedelta(minutes=interval):
                            should_run = True
                    except (ValueError, TypeError):
                        should_run = True

                if should_run:
                    profile = load_profile(profile_name)
                    tasks = count_tasks(profile)

                    log(f"Pruefe Job [{profile_name}] - Offene Tasks: {tasks}")

                    pause_request = get_pause_request(profile_name)
                    if pause_request:
                        reason = pause_request.get("reason", "Manuell pausiert")
                        log(f"Job [{profile_name}] pausiert - ueberspringe Trigger ({reason})")
                        continue

                    if tasks > 0:
                        operator_steer = peek_steer_requests(profile_name)
                        if operator_steer:
                            log(
                                f"Operator-Steering fuer [{profile_name}] erkannt "
                                f"({len(operator_steer)} Hinweis(e))"
                            )
                        success = trigger_session(profile_name, operator_steer=operator_steer)
                        if success:
                            if operator_steer:
                                consume_steer_requests(profile_name)
                            sessions_generated += 1
                            log(f"Session fuer [{profile_name}] gestartet.")

                    # Last Run immer aktualisieren wenn fällig
                    job["last_run"] = now.isoformat()
                    config_changed = True

                if stop_event.is_set():
                    break

            if config_changed:
                save_config(config)

            # Kurze Pause bis zur nächsten Prüfung der Job-Liste
            stop_event.wait(30)

        except Exception as e:
            log(f"Loop-Fehler: {e}", "ERROR")
            stop_event.wait(60)

# ============ MAIN ============

def main():
    if "--status" in sys.argv:
        show_status()
        return

    if "--stop" in sys.argv:
        pid = get_running_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"[OK] Daemon (PID {pid}) gestoppt")
                PID_FILE.unlink()
            except Exception as e:
                print(f"[!!] Fehler: {e}")
        else:
            print("Kein Daemon laeuft")
        return

    stop_old_daemon()
    write_pid()

    config = load_config()

    # Profil aus CLI oder Config
    profile_name = config.get("default_profile", DEFAULT_PROFILE)
    for i, arg in enumerate(sys.argv):
        if arg == "--profile" and i + 1 < len(sys.argv):
            profile_name = sys.argv[i + 1]

    # Intervall aus CLI
    interval = config.get("interval_minutes", DEFAULT_INTERVAL)
    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1])
            config["interval_minutes"] = interval
            save_config(config)

    log("=" * 50)
    log("BACH SESSION DAEMON (System-Service)")
    log(f"Profil: {profile_name}")
    log(f"Intervall: {interval} Min")
    log(f"BACH: {BACH_DIR}")
    log("=" * 50)

    stop_event = Event()

    def signal_handler(sig, frame):
        log("Stop-Signal empfangen")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Main Loop starten
    daemon_loop(stop_event)

    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except OSError:
            pass

    log("Daemon beendet")

if __name__ == "__main__":
    main()
