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
BACH Prompt-Generator Service
=============================
Systemweites Prompt-Management fuer Claude-Sessions.

Features:
- Template-System (System/Agenten/Custom)
- 4 Sendeoptionen (Task, Session, Copy, Daemon)
- Variable Substitution in Templates
- Daemon-Steuerung fuer automatisierte Sessions

Status: In Entwicklung (PROMPT_GEN_001-007)
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

# Pfade
SERVICE_DIR = Path(__file__).parent
TEMPLATES_DIR = SERVICE_DIR / "templates"
PROFILES_DIR = SERVICE_DIR / "profiles"
CONFIG_FILE = SERVICE_DIR / "config.json"

# BACH Root
BACH_DIR = SERVICE_DIR.parent.parent.parent


class PromptGenerator:
    """Hauptklasse fuer Prompt-Generierung und -Management."""

    def __init__(self):
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Laedt Konfiguration aus config.json."""
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            except Exception as e:
                print(f"[WARN] Config laden fehlgeschlagen: {e}")
        return {
            "enabled": False,
            "default_template": "system/minimal",
            "daemon": {
                "enabled": False,
                "interval_minutes": 30,
                "max_sessions": 0,
                "quiet_start": "22:00",
                "quiet_end": "08:00"
            }
        }

    def save_config(self):
        """Speichert Konfiguration."""
        CONFIG_FILE.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    # =========================================================================
    # TEMPLATE MANAGEMENT
    # =========================================================================

    def list_templates(self) -> Dict[str, List[dict]]:
        """Listet alle verfuegbaren Templates nach Kategorie.

        Returns:
            Dict mit Kategorien: system, agents, custom
        """
        result = {"system": [], "agents": [], "custom": []}

        # System-Templates
        system_dir = TEMPLATES_DIR / "system"
        if system_dir.exists():
            for f in system_dir.glob("*.txt"):
                result["system"].append({
                    "name": f.stem,
                    "path": f"system/{f.stem}",
                    "editable": False,
                    "description": self._get_template_description(f)
                })

        # Agenten-Templates
        agents_dir = TEMPLATES_DIR / "agents"
        if agents_dir.exists():
            for f in agents_dir.glob("*.txt"):
                result["agents"].append({
                    "name": f.stem,
                    "path": f"agents/{f.stem}",
                    "editable": True,
                    "description": self._get_template_description(f)
                })

        # Custom-Templates (aus Dateisystem)
        custom_dir = TEMPLATES_DIR / "custom"
        if custom_dir.exists():
            for f in custom_dir.glob("*.txt"):
                result["custom"].append({
                    "name": f.stem,
                    "path": f"custom/{f.stem}",
                    "editable": True,
                    "description": self._get_template_description(f)
                })

        return result

    def _get_template_description(self, file_path: Path) -> str:
        """Extrahiert Beschreibung aus Template-Header."""
        try:
            lines = file_path.read_text(encoding='utf-8').split('\n')
            for line in lines[:5]:
                if line.startswith('#') and not line.startswith('# '):
                    continue
                if line.startswith('# '):
                    return line[2:].strip()
            return ""
        except (OSError, UnicodeDecodeError):
            return ""

    def get_template(self, template_path: str) -> Optional[str]:
        """Laedt ein Template.

        Args:
            template_path: z.B. "system/minimal" oder "agents/ati"

        Returns:
            Template-Inhalt oder None
        """
        # Pfad normalisieren
        if not template_path.endswith('.txt'):
            template_path += '.txt'

        file_path = (TEMPLATES_DIR / template_path).resolve()
        try:
            file_path.relative_to(TEMPLATES_DIR.resolve())
        except ValueError:
            return None
        if file_path.exists():
            try:
                content = file_path.read_text(encoding='utf-8')
                # Kommentarzeilen am Anfang entfernen
                lines = content.split('\n')
                result_lines = []
                in_header = True
                for line in lines:
                    if in_header and line.startswith('#'):
                        continue
                    in_header = False
                    result_lines.append(line)
                return '\n'.join(result_lines).strip()
            except Exception as e:
                print(f"[ERROR] Template laden: {e}")
        return None

    def get_template_raw(self, template_path: str) -> Optional[str]:
        """Laedt ein Template inkl. Header-Kommentare."""
        if not template_path.endswith('.txt'):
            template_path += '.txt'

        file_path = (TEMPLATES_DIR / template_path).resolve()
        try:
            file_path.relative_to(TEMPLATES_DIR.resolve())
        except ValueError:
            return None
        if file_path.exists():
            return file_path.read_text(encoding='utf-8')
        return None

    # =========================================================================
    # PROMPT GENERATION
    # =========================================================================

    def generate_prompt(
        self,
        template_path: str,
        variables: Optional[Dict[str, str]] = None,
        append_text: Optional[str] = None
    ) -> str:
        """Generiert einen Prompt aus Template mit Variablen.

        Args:
            template_path: Pfad zum Template (z.B. "system/task")
            variables: Dict mit Variablen (z.B. {"TASK_ID": "123"})
            append_text: Optionaler Text zum Anhaengen

        Returns:
            Fertiger Prompt-String
        """
        template = self.get_template(template_path)
        if not template:
            template = self.get_template(self.config.get("default_template", "system/minimal"))

        if not template:
            return "Lies SKILL.md und beginne mit der Arbeit."

        # Variablen ersetzen: {{VAR_NAME}}
        if variables:
            for key, value in variables.items():
                template = template.replace(f"{{{{{key}}}}}", str(value))

        # Nicht ersetzte Variablen entfernen oder markieren
        template = re.sub(r'\{\{[A-Z_]+\}\}', '[NICHT DEFINIERT]', template)

        # Optionalen Text anhaengen
        if append_text:
            template = f"{template}\n\n{append_text}"

        return template.strip()

    # =========================================================================
    # CONTEXTUAL PROMPT GENERATION (aus ATI auto_session.py portiert)
    # =========================================================================

    def generate_session_prompt(self, agent: str = "ati", expertise: str = None, max_tasks: int = 3, timeout_min: int = 15) -> str:
        """Generiert einen kontextbasierten Session-Prompt (PROMPT_GEN_006).

        Portiert von ATI auto_session.py fuer allgemeine Wiederverwendung.

        Args:
            agent: Agent-Name (ati, wartung, steuer, specialist)
            expertise: Fachgebiet fuer specialist Agent (optional)
            max_tasks: Max. Tasks in Prompt
            timeout_min: Zeitrahmen in Minuten

        Returns:
            Fertiger Prompt-String mit Kontext
        """
        import sqlite3
        from datetime import datetime

        db_path = BACH_DIR / "data" / "bach.db"
        user_db_path = BACH_DIR / "data" / "bach.db"
        skill_file = BACH_DIR / "SKILL.md"

        # Tasks laden
        tasks_text = "(keine offenen Tasks)"
        task_count = 0
        try:
            conn = sqlite3.connect(str(user_db_path))
            tasks = conn.execute("""
                SELECT tool_name, task_text, aufwand, priority_score
                FROM ati_tasks
                WHERE status = 'offen'
                ORDER BY priority_score DESC
                LIMIT ?
            """, (max_tasks + 2,)).fetchall()
            task_count = conn.execute(
                "SELECT COUNT(*) FROM ati_tasks WHERE status = 'offen'"
            ).fetchone()[0]
            conn.close()

            if tasks:
                task_lines = []
                for i, (tool, text, aufwand, prio) in enumerate(tasks[:max_tasks], 1):
                    short = text[:60] + "..." if len(text) > 60 else text
                    task_lines.append(f"{i}. [{tool}] {short} (Aufwand: {aufwand or 'mittel'})")
                tasks_text = "\n".join(task_lines)
        except Exception:
            pass

        # Memory laden
        memory_text = "(keine)"
        try:
            conn = sqlite3.connect(str(db_path))
            notes = conn.execute("""
                SELECT content FROM memory_working
                ORDER BY created_at DESC LIMIT 3
            """).fetchall()
            conn.close()
            if notes:
                memory_text = "\n".join(f"- {n[0][:100]}" for n in notes)
        except (sqlite3.Error, OSError):
            pass

        # Profil laden (USER-PROFIL Block fuer Kontext)
        profile_text = ""
        try:
            import sys
            profile_svc_dir = str(SERVICE_DIR.parent / "profile")
            if profile_svc_dir not in sys.path:
                sys.path.insert(0, profile_svc_dir)
            from profile_service import ProfileService
            # profile.json liegt im PROJECT ROOT (eine Ebene ueber system/)
            project_root = BACH_DIR.parent
            ps = ProfileService(
                profile_path=project_root / "user" / "profile.json",
                db_path=db_path
            )
            profile_text = ps.get_prompt_context()
        except Exception:
            pass

        # Spezialfall: Specialist-Template
        if agent == "specialist" and expertise:
            template = self.get_template("agents/specialist")
            if template:
                # Expertise-Variablen setzen
                context_template = template.replace("{{ ROLE_NAME }}", f"{expertise} Specialist")
                context_template = context_template.replace("{{ EXPERTISE_AREA }}", expertise)
                context_template = context_template.replace("{{ EXPERTISE_INSTRUCTIONS }}", f"Handle strictly as an expert in {expertise}.")
                context_template = context_template.replace("{{ TASK_DESCRIPTION }}", tasks_text)
                
                # Standard-Prompt mit Specialist-Prompt kombinieren oder ersetzen
                # Hier: Ersetzen des Headers und der Anweisung durch Specialist-Template
                context_parts = [f"Memory: {memory_text[:200]}..."]
                if profile_text:
                    context_parts.append(profile_text)
                prompt = context_template + "\n\n=== CONTEXT ===\n" + "\n".join(context_parts)
                return prompt

        # Standard Prompt (Fallback oder normale Agenten)
        prompt = f"""# BACH AUTO-SESSION [{agent.upper()}]

## 1. ERSTE AKTION (Automatischer Modus)

```bash
cd "{BACH_DIR}"
python bach.py --startup --partner=claude --mode=silent
bach countdown {timeout_min} --name="Session-Ende" --notify
bach between use autosession
```

## 2. SKILL.md (ab Abschnitt 2)

Lies {skill_file} und springe direkt zu Abschnitt **(2) SYSTEM**.
Nur Punkt (1) EINLEITUNG wurde bereits durchgefuehrt.

## 3. ARBEITSPHASE

**Top-Tasks ({task_count} offen):**
{tasks_text}

**Memory-Kontext:**
{memory_text}

{profile_text if profile_text else ""}

### AUFGABEN-WORKFLOW:
```
(A) bach beat           # Startzeit merken
(B) Aufgabe erledigen
(C) bach beat           # Endzeit = Dauer berechnen
```

### BETWEEN-TASK CHECK (nach jeder Aufgabe):
1. ZEIT-CHECK: `bach countdown status` - Restzeit pruefen
2. ENTSCHEIDUNG:
   - Restzeit > Aufgabendauer + 3min Sicherheit? -> Naechste Aufgabe
   - Sonst -> Weiter zu SESSION-ENDE

**DENKANSTOSS:**
- Planen und Zerlegen kann deine Aufgabe sein!
- Du musst nicht fertig werden, nur dokumentieren wo du warst!

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
```
"""
        return prompt

    # =========================================================================
    # SEND OPTIONS
    # =========================================================================

    def send_as_task(self, prompt: str, priority: str = "P2", project: str = "BACH") -> dict:
        """Erstellt einen Task mit dem Prompt.

        Args:
            prompt: Der Prompt-Text
            priority: Prioritaet (P1-P4)
            project: Projekt-Name

        Returns:
            Dict mit task_id und status
        """
        import sqlite3
        from datetime import datetime

        db_path = BACH_DIR / "data" / "bach.db"
        if not db_path.exists():
            return {"status": "error", "message": "Datenbank nicht gefunden"}

        try:
            # Task-Titel aus erstem Satz generieren
            lines = prompt.strip().split('\n')
            first_line = lines[0][:80] if lines else "Prompt-Task"
            if first_line.startswith('#'):
                first_line = first_line.lstrip('#').strip()

            title = f"[{priority}] {first_line}"

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO tasks (title, description, priority, category, status, created_at, created_by)
                VALUES (?, ?, ?, ?, 'pending', ?, 'prompt_generator')
            """, (title, prompt, priority, project, datetime.now().isoformat()))

            task_id = cursor.lastrowid
            conn.commit()
            conn.close()

            return {
                "status": "created",
                "task_id": task_id,
                "title": title,
                "message": f"Task #{task_id} erstellt"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _is_screen_locked(self) -> bool:
        """Prueft ob Windows-Bildschirm gesperrt ist (Screen-Lock-Detection)."""
        import sys
        if sys.platform != "win32":
            return False

        try:
            import ctypes
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

        except Exception:
            return False

    def send_direct_session(self, prompt: str, force: bool = False) -> dict:
        """Startet sofort eine Claude-Session mit dem Prompt.

        Nutzt Quick-Entry (Ctrl+Alt+Space) via pyautogui.
        Portiert von ATI auto_session.py (PROMPT_GEN_006).

        Args:
            prompt: Der Prompt-Text
            force: Ignoriere Screen-Lock-Check

        Returns:
            Dict mit status und Fehler falls vorhanden
        """
        # Screen-Lock-Check
        if not force and self._is_screen_locked():
            return {
                "status": "blocked",
                "message": "Bildschirm ist gesperrt. Verwende force=True zum Ueberspringen."
            }

        try:
            # Import hier um Abhaengigkeit optional zu halten
            import pyautogui
            import pyperclip
            import time

            # Prompt in Zwischenablage
            pyperclip.copy(prompt)

            # Quick-Entry triggern (aus auto_session.py)
            time.sleep(0.3)
            pyautogui.hotkey('ctrl', 'alt', 'space')
            time.sleep(1.0)  # WAIT_AFTER_HOTKEY aus auto_session.py

            # Prompt einfuegen
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.3)  # WAIT_AFTER_PASTE aus auto_session.py

            # Enter zum Senden
            pyautogui.press('enter')

            # Log Session-Start
            self._log_session_start(prompt)

            return {"status": "sent", "message": "Session gestartet", "prompt_length": len(prompt)}

        except ImportError:
            return {
                "status": "error",
                "message": "pyautogui/pyperclip nicht installiert (pip install pyautogui pyperclip)"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _log_session_start(self, prompt: str):
        """Loggt Session-Start (aus auto_session.py portiert)."""
        from datetime import datetime
        log_file = BACH_DIR / "data" / "logs" / "prompt_generator_sessions.log"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_line = f"{timestamp} - Session gestartet ({len(prompt)} Zeichen)\n"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
        except (OSError, ValueError):
            pass

    def copy_to_clipboard(self, prompt: str) -> dict:
        """Kopiert Prompt in Zwischenablage.

        Returns:
            Dict mit status
        """
        try:
            import pyperclip
            pyperclip.copy(prompt)
            return {"status": "copied", "length": len(prompt)}
        except ImportError:
            pass

        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(prompt)
            root.update()
            root.destroy()
            return {"status": "copied", "length": len(prompt)}
        except (ImportError, RuntimeError):
            pass

        import sys
        import subprocess
        import shutil
        data = prompt.encode("utf-8")
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["powershell", "-Command", f"Set-Clipboard -Value '{prompt.replace(chr(39), chr(39)+chr(39))}'"],
                    capture_output=True, creationflags=0x08000000
                )
            elif sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=data, capture_output=True)
            elif shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=data, capture_output=True)
            elif shutil.which("xsel"):
                subprocess.run(["xsel", "-b", "-i"], input=data, capture_output=True)
            elif shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=data, capture_output=True)
            else:
                return {"status": "error", "message": "Clipboard nicht verfuegbar"}
            return {"status": "copied", "length": len(prompt)}
        except (OSError, FileNotFoundError):
            return {"status": "error", "message": "Clipboard nicht verfuegbar"}

    # =========================================================================
    # DAEMON CONTROL (Stub fuer GUI-Integration)
    # =========================================================================

    def get_daemon_status(self) -> dict:
        """Gibt Daemon-Status zurueck."""
        return {
            "enabled": self.config.get("daemon", {}).get("enabled", False),
            "interval_minutes": self.config.get("daemon", {}).get("interval_minutes", 30),
            "max_sessions": self.config.get("daemon", {}).get("max_sessions", 0),
            "quiet_start": self.config.get("daemon", {}).get("quiet_start", "22:00"),
            "quiet_end": self.config.get("daemon", {}).get("quiet_end", "08:00"),
            "running": False,  # TODO: PID-Check
            "sessions_generated": 0  # TODO: Aus State laden
        }

    def update_daemon_config(self, **kwargs) -> dict:
        """Aktualisiert Daemon-Konfiguration.

        Args:
            interval_minutes: Intervall zwischen Sessions
            max_sessions: Maximale Sessions (0 = unbegrenzt)
            quiet_start: Beginn Ruhezeit (HH:MM)
            quiet_end: Ende Ruhezeit (HH:MM)
            enabled: Daemon aktivieren/deaktivieren
        """
        if "daemon" not in self.config:
            self.config["daemon"] = {}

        for key, value in kwargs.items():
            if key in ["interval_minutes", "max_sessions", "quiet_start", "quiet_end", "enabled"]:
                self.config["daemon"][key] = value

        self.save_config()
        return {"status": "updated", "config": self.config["daemon"]}


# CLI Interface
def main():
    """CLI fuer Prompt-Generator."""
    import sys

    pg = PromptGenerator()

    if len(sys.argv) < 2:
        print("BACH Prompt-Generator")
        print("=" * 40)
        print()
        print("Befehle:")
        print("  list              Templates auflisten")
        print("  get <path>        Template anzeigen")
        print("  generate <path>   Prompt generieren")
        print("  copy <path>       In Zwischenablage kopieren")
        print("  session [agent]   Session-Prompt generieren (ati/wartung/steuer)")
        print("  start [agent]     Claude-Session direkt starten")
        print("  status            Daemon-Status anzeigen")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        templates = pg.list_templates()
        for category, items in templates.items():
            if items:
                print(f"\n{category.upper()}:")
                for item in items:
                    edit = "" if item["editable"] else " (read-only)"
                    print(f"  {item['path']}{edit}")
                    if item["description"]:
                        print(f"    {item['description']}")

    elif cmd == "get" and len(sys.argv) > 2:
        content = pg.get_template_raw(sys.argv[2])
        if content:
            print(content)
        else:
            print(f"Template nicht gefunden: {sys.argv[2]}")

    elif cmd == "generate" and len(sys.argv) > 2:
        prompt = pg.generate_prompt(sys.argv[2])
        print(prompt)

    elif cmd == "copy" and len(sys.argv) > 2:
        prompt = pg.generate_prompt(sys.argv[2])
        result = pg.copy_to_clipboard(prompt)
        print(f"Status: {result['status']}")
        if result['status'] == 'copied':
            print(f"Laenge: {result['length']} Zeichen")

    elif cmd == "status":
        status = pg.get_daemon_status()
        print("Daemon-Status:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    elif cmd == "session":
        # Session-Prompt generieren (aus auto_session.py portiert)
        # Session-Prompt generieren (aus auto_session.py portiert)
        agent = "ati"
        expertise = None
        
        # Args parsen (sehr simpel)
        if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
            agent = sys.argv[2]
        
        for arg in sys.argv:
            if arg.startswith("--expertise="):
                expertise = arg.split("=", 1)[1]

        prompt = pg.generate_session_prompt(agent=agent, expertise=expertise)
        try:
            print(prompt)
        except UnicodeEncodeError:
            # Fallback fuer Windows-Konsolen
            safe = prompt.encode('ascii', 'replace').decode('ascii')
            print(safe)

    elif cmd == "start":
        # Claude-Session direkt starten
        agent = "ati"
        expertise = None
        if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
            agent = sys.argv[2]
            
        for arg in sys.argv:
            if arg.startswith("--expertise="):
                expertise = arg.split("=", 1)[1]

        prompt = pg.generate_session_prompt(agent=agent, expertise=expertise)
        print(f"Starte {agent.upper()} Session...")
        result = pg.send_direct_session(prompt)
        print(f"Status: {result['status']}")
        if result.get('message'):
            print(f"Message: {result['message']}")

    else:
        print(f"Unbekannter Befehl: {cmd}")
        print("Nutze ohne Argumente fuer Hilfe.")


if __name__ == "__main__":
    main()
