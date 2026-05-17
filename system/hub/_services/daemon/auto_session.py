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
BACH Auto-Session v1.1 [DEPRECATED]
====================================
⚠️  DEPRECATED seit 2026-05-17.
    Grund: Nutzt pyautogui um Tastatureingaben zu simulieren (Ctrl+Alt+Space,
    Paste, Enter). Erzeugt unkontrollierte Prompt-Injektionen in aktive Sessions.

    ERSATZ: Buddha Control API (:8081/api/chat) oder Claude Code /loop.
    Siehe session_daemon.py für Details.

EHEMALIGER ZWECK:
  System-Service fuer automatische Claude-Session-Starts via GUI-Automation.

Usage (DEPRECATED):
  python auto_session.py                    # Default-Profil
  python auto_session.py --profile ati      # ATI-Profil
  python auto_session.py --profile wartung  # Wartungs-Profil
  python auto_session.py --dry-run          # Nur Prompt anzeigen
  python auto_session.py --force            # Auch bei gesperrtem Screen

Abhaengigkeiten (NICHT MEHR NÖTIG):
  pip install pyautogui pyperclip
"""

import time
import sys
import os
import json
import ctypes
import sqlite3
from datetime import datetime
from pathlib import Path

# ============ PFADE ============

DAEMON_DIR = Path(__file__).parent.resolve()
SERVICES_DIR = DAEMON_DIR.parent
SKILLS_DIR = SERVICES_DIR.parent
BACH_DIR = SKILLS_DIR.parent

PROFILES_DIR = DAEMON_DIR / "profiles"
LOG_FILE = BACH_DIR / "logs" / "auto_session.log"
USER_DB = BACH_DIR / "data" / "bach.db"
BACH_DB = BACH_DIR / "data" / "bach.db"
SKILL_FILE = BACH_DIR / "SKILL.md"

# Wartezeiten
WAIT_AFTER_HOTKEY = 1.0
WAIT_AFTER_PASTE = 0.3
STARTUP_DELAY = 3

DEFAULT_PROFILE = "ati"
OPERATOR_STEER_ENV = "BACH_SESSION_OPERATOR_STEER"

# ============ LOGGING ============

def log(msg: str):
    """Logging in Datei und Console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} - {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

# ============ SCREEN LOCK CHECK ============

def is_screen_locked() -> bool:
    """Prueft ob Windows-Bildschirm gesperrt ist."""
    if sys.platform != "win32":
        return False

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()

        if hwnd == 0:
            return True

        try:
            import pyautogui
            pos = pyautogui.position()
            return False
        except Exception:
            return True

    except Exception as e:
        log(f"Screen-Lock-Check Fehler: {e}")
        return False

# ============ PROFILE LOADING ============

def load_profile(name: str) -> dict:
    """Laedt ein Prompt-Profil."""
    profile_file = PROFILES_DIR / f"{name}.json"
    if profile_file.exists():
        try:
            return json.loads(profile_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback
    return {
        "name": name,
        "description": f"Profil: {name}",
        "task_source": "ati_tasks",
        "task_filter": {"status": "offen"},
        "max_tasks": 3,
        "timeout_minutes": 15,
        "prompt_template": "default"
    }

# ============ TASK LOADING ============

def get_tasks(profile: dict, limit: int = 5) -> list:
    """Holt Tasks basierend auf Profil."""
    task_source = profile.get("task_source", "ati_tasks")

    try:
        if task_source == "ati_tasks":
            conn = sqlite3.connect(USER_DB)
            tasks = conn.execute("""
                SELECT tool_name, task_text, aufwand, priority_score
                FROM ati_tasks
                WHERE status = 'offen'
                ORDER BY priority_score DESC
                LIMIT ?
            """, (limit,)).fetchall()
        else:
            conn = sqlite3.connect(BACH_DB)
            tasks = conn.execute("""
                SELECT category, title, priority, id
                FROM tasks
                WHERE status = 'open'
                ORDER BY
                    CASE priority
                        WHEN 'P1' THEN 1
                        WHEN 'P2' THEN 2
                        WHEN 'P3' THEN 3
                        ELSE 4
                    END
                LIMIT ?
            """, (limit,)).fetchall()

        conn.close()
        return tasks
    except Exception as e:
        log(f"Task-Laden Fehler: {e}")
        return []

def count_tasks(profile: dict) -> int:
    """Zaehlt offene Tasks."""
    task_source = profile.get("task_source", "ati_tasks")

    try:
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

def get_recent_memory() -> str:
    """Holt letzte Memory-Eintraege."""
    try:
        conn = sqlite3.connect(BACH_DB)
        notes = conn.execute("""
            SELECT content FROM memory_working
            ORDER BY created_at DESC LIMIT 3
        """).fetchall()
        conn.close()

        if notes:
            return "\n".join(f"- {n[0][:100]}" for n in notes)
        return "(keine)"
    except Exception:
        return "(Fehler)"


def load_operator_steer() -> list[dict]:
    """Laedt optionale Operator-Hinweise aus der Umgebung."""
    raw = os.environ.get(OPERATOR_STEER_ENV, "").strip()
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [{"message": raw, "requested_at": None}]

    if isinstance(payload, list):
        normalized = []
        for item in payload:
            if isinstance(item, dict) and item.get("message"):
                normalized.append(
                    {
                        "message": str(item["message"]),
                        "requested_at": item.get("requested_at"),
                    }
                )
            elif isinstance(item, str) and item.strip():
                normalized.append({"message": item.strip(), "requested_at": None})
        return normalized

    if isinstance(payload, dict) and payload.get("message"):
        return [{"message": str(payload["message"]), "requested_at": payload.get("requested_at")}]

    return []

# ============ PROMPT GENERATION ============

def create_prompt(profile: dict, operator_steer: list[dict] | None = None) -> str:
    """Erstellt Prompt basierend auf Profil.

    Nutzt agent_prompt und start_command aus dem Profil falls vorhanden.
    Between-Tasks wird nicht mehr im Prompt eingefuegt (laeuft ueber Injektoren).
    """
    profile_name = profile.get("name", "default")
    timeout = profile.get("timeout_minutes", 15)

    # Prompt-Teile sammeln
    parts = []

    # ═══════════════════════════════════════════════════════════════
    # 1. AGENT-PROMPT (aus Profil oder generisch)
    # ═══════════════════════════════════════════════════════════════
    agent_prompt = profile.get("agent_prompt")
    if agent_prompt:
        parts.append(agent_prompt)
    else:
        # Generischer Agent-Header
        parts.append(f"# {profile_name.upper()} Agent Prompt")
        instruction = profile.get("instruction", f"Du bist der {profile_name} Agent im BACH-System.")
        parts.append(f"\n{instruction}")

    if operator_steer:
        lines = ["\n## Operator-Hinweise fuer diese Session"]
        lines.append("Beruecksichtige diese aktuellen Hinweise bei Priorisierung und Ausfuehrung:")
        for item in operator_steer:
            message = item.get("message", "").strip()
            if not message:
                continue
            requested_at = item.get("requested_at")
            prefix = f"[{requested_at}] " if requested_at else ""
            lines.append(f"- {prefix}{message}")
        parts.append("\n".join(lines))

    # ═══════════════════════════════════════════════════════════════
    # 2. ERSTE AKTION
    # ═══════════════════════════════════════════════════════════════
    startup_block = f"""
## 1. ERSTE AKTION (Automatischer Modus)

```bash
cd "{BACH_DIR}"
python bach.py --startup --partner=claude --mode=silent
python bach.py countdown start Session-Ende {timeout}m --after "--shutdown"
```"""
    parts.append(startup_block)

    # ═══════════════════════════════════════════════════════════════
    # 3. SKILL.md REFERENZ
    # ═══════════════════════════════════════════════════════════════
    skill_block = f"""
## 2. SKILL.md (ab Abschnitt 2)

Lies {SKILL_FILE} und springe direkt zu Abschnitt **(2) SYSTEM**."""
    parts.append(skill_block)

    # ═══════════════════════════════════════════════════════════════
    # 4. START-COMMAND (aus Profil)
    # ═══════════════════════════════════════════════════════════════
    start_command = profile.get("start_command")
    if start_command:
        parts.append(f"\n{start_command}")

    # ═══════════════════════════════════════════════════════════════
    # 5. AUFGABEN-WORKFLOW
    # ═══════════════════════════════════════════════════════════════
    workflow_block = """
### AUFGABEN-WORKFLOW:
```
(A) bach beat           # Startzeit merken
(B) Aufgabe erledigen
(C) bach beat           # Endzeit = Dauer berechnen
```"""
    parts.append(workflow_block)

    # ═══════════════════════════════════════════════════════════════
    # 6. SESSION-ENDE
    # ═══════════════════════════════════════════════════════════════
    end_block = """
## 4. SESSION-ENDE

### Kontinuitaetstests (max. 2 Min):
- Lessons learned? -> `bach memory add "..."`
- Tasks erledigt? -> Im Taskmanager dokumentieren
- Neue Folgeaufgaben? -> Als neue Tasks anlegen
- Grosse Aenderung? -> CHANGELOG.md + help aktualisieren

### Meta-Plan (max. 2 Min):
- ROADMAP-Aufgabe erledigt? -> ROADMAP.md aktualisieren
- Bug entdeckt? -> BUGLOG.md

### Abschliessen:
```bash
bach --memory session
bach --shutdown "Zusammenfassung der erledigten Arbeit"
```"""
    parts.append(end_block)

    return "\n".join(parts)

# ============ CLAUDE TRIGGER ============

def start_claude_session(prompt: str) -> bool:
    """Oeffnet Claude Quick-Entry und sendet Prompt."""
    try:
        import pyautogui
        import pyperclip
    except ImportError:
        log("FEHLER: pip install pyautogui pyperclip")
        return False

    log("Claude Quick-Entry oeffnen (Ctrl+Alt+Space)...")
    pyautogui.hotkey('ctrl', 'alt', 'space')
    time.sleep(WAIT_AFTER_HOTKEY)

    log(f"Prompt einfuegen ({len(prompt)} Zeichen)...")
    pyperclip.copy(prompt)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(WAIT_AFTER_PASTE)

    log("Absenden (Enter)...")
    pyautogui.press('enter')

    log("Session gestartet!")
    return True

# ============ MAIN ============

def main():
    dry_run = '--dry-run' in sys.argv
    force = '--force' in sys.argv

    # Profil aus CLI
    profile_name = DEFAULT_PROFILE
    for i, arg in enumerate(sys.argv):
        if arg == "--profile" and i + 1 < len(sys.argv):
            profile_name = sys.argv[i + 1]

    log("=" * 50)
    log(f"BACH AUTO-SESSION [{profile_name.upper()}]")

    # Screen-Lock-Check
    if not force and is_screen_locked():
        log("ABBRUCH: Bildschirm ist gesperrt!")
        log("Verwende --force um trotzdem fortzufahren.")
        return

    # Profil laden
    profile = load_profile(profile_name)
    operator_steer = load_operator_steer()
    if operator_steer:
        log(f"Operator-Steering erkannt: {len(operator_steer)} Hinweis(e)")

    # Tasks pruefen
    task_count = count_tasks(profile)
    log(f"Offene Tasks: {task_count}")

    if task_count == 0:
        log("Keine offenen Tasks - Session uebersprungen")
        return

    # Prompt generieren
    prompt = create_prompt(profile, operator_steer=operator_steer)

    # Claude starten
    if dry_run:
        log("DRY-RUN: Claude-Start uebersprungen")
        log("-" * 40)
        log("Prompt Preview:")
        log("-" * 40)
        try:
            print(prompt[:2000])
        except UnicodeEncodeError:
            safe = prompt[:2000].encode('ascii', 'ignore').decode('ascii')
            print(safe)
        if len(prompt) > 2000:
            print(f"\n... ({len(prompt) - 2000} weitere Zeichen)")
    else:
        log(f"Starte in {STARTUP_DELAY} Sekunden...")
        time.sleep(STARTUP_DELAY)
        start_claude_session(prompt)

    log("AUTO-SESSION ENDE")
    log("=" * 50)

if __name__ == "__main__":
    main()
