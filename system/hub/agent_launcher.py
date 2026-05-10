# SPDX-License-Identifier: MIT
"""
Agent Launcher Handler - Agent-Verwaltung
==========================================

bach agent list                          Verfuegbare Agents auflisten
bach agent start <name> [--mode MODE] [--model MODEL]   Agent starten
bach agent stop <name>                   Agent stoppen
bach agent status                        Laufende Agents anzeigen

Optionen:
  --mode plan|default     Modus (default: default)
  --model sonnet|opus|haiku   Modell (default: sonnet)
"""
import sys
import os
import signal
import subprocess
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from .base import BaseHandler
from .lang import t


class AgentLauncherHandler(BaseHandler):
    """Handler fuer Agent-Operationen (list, start, stop, status)."""

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.agents_dir = self.base_path / "agents"
        self.experts_dir = self.base_path / "agents" / "_experts"
        self.data_dir = self.base_path / "data"
        self.pid_dir = self.data_dir / "agent_pids"
        self.temp_dir = self.data_dir / "temp"

    @property
    def profile_name(self) -> str:
        return "agent"

    @property
    def target_file(self) -> Path:
        return self.agents_dir

    def get_operations(self) -> dict:
        return {
            "list": t("agent_list_desc", default="Verfuegbare Agents auflisten"),
            "start": t("agent_start_desc", default="Agent starten (bach agent start <name>)"),
            "stop": t("agent_stop_desc", default="Agent stoppen (bach agent stop <name>)"),
            "status": t("agent_status_desc", default="Laufende Agents anzeigen"),
            "rename": t("agent_rename_desc", default="Display-Name aendern (bach agent rename <name> <neuer-name>)")
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "list":
            if self._has_flag(args, "--json"):
                return self._list_agents_json()
            return self._list_agents()
        elif operation == "start":
            if not args:
                return (False, f"[ERROR] {t('agent_name_required', default='Agent-Name erforderlich')}: bach agent start <name>")
            name = args[0]
            return self._start_agent(name, args[1:], dry_run)
        elif operation == "stop":
            if not args:
                return (False, f"[ERROR] {t('agent_name_required', default='Agent-Name erforderlich')}: bach agent stop <name>")
            return self._stop_agent(args[0], dry_run)
        elif operation == "status":
            if self._has_flag(args, "--json"):
                return self._show_status_json()
            return self._show_status()
        elif operation == "rename":
            if len(args) < 2:
                return (False, t("agent_rename_syntax", default="[ERROR] Syntax: bach agent rename <name> <neuer-display-name>"))
            return self._rename_agent(args[0], ' '.join(args[1:]), dry_run)
        else:
            return self._list_agents()

    def _has_flag(self, args: list, *flags: str) -> bool:
        """Prueft ob ein Flag in den CLI-Argumenten gesetzt wurde."""
        return any(arg in flags for arg in args)

    def _json_dump(self, payload: dict) -> str:
        """Formatiert JSON konsistent fuer CLI-Ausgabe."""
        return json.dumps(payload, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------

    def _scan_agents(self) -> list:
        """Scannt agents/ und agents/_experts/ nach SKILL.md Dateien."""
        agents = []

        # Boss-Agents
        if self.agents_dir.exists():
            for entry in sorted(self.agents_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("_"):
                    continue
                skill_file = entry / "SKILL.md"
                if skill_file.exists():
                    agents.append({
                        "name": entry.name,
                        "type": "boss",
                        "path": entry,
                        "skill_file": skill_file
                    })

        # Experten
        if self.experts_dir.exists():
            for entry in sorted(self.experts_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("_"):
                    continue
                skill_file = entry / "SKILL.md"
                if skill_file.exists():
                    agents.append({
                        "name": entry.name,
                        "type": "expert",
                        "path": entry,
                        "skill_file": skill_file
                    })

        return agents

    def _is_agent_running(self, name: str) -> int:
        """Prueft ob Agent laeuft. Gibt PID oder 0 zurueck."""
        pid_file = self.pid_dir / f"{name}.pid"
        if not pid_file.exists():
            return 0
        try:
            data = json.loads(pid_file.read_text(encoding='utf-8'))
            pid = data.get("pid", 0)
            if not pid:
                return 0
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True, text=True, encoding='utf-8', errors='replace'
                )
                if str(pid) in result.stdout:
                    return pid
                # Prozess nicht mehr da, PID-File aufraeumen
                pid_file.unlink(missing_ok=True)
                return 0
            else:
                os.kill(pid, 0)
                return pid
        except (json.JSONDecodeError, ValueError, ProcessLookupError, PermissionError):
            return 0
        except OSError:
            pid_file.unlink(missing_ok=True)
            return 0

    def _load_pid_data(self, name: str) -> dict:
        """Liest optionale Laufzeit-Metadaten aus der PID-Datei."""
        pid_file = self.pid_dir / f"{name}.pid"
        if not pid_file.exists():
            return {}
        try:
            return json.loads(pid_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, ValueError):
            return {}

    def _agent_list_entry(self, agent: dict) -> dict:
        """Erzeugt maschinenlesbare Metadaten fuer `agent list --json`."""
        persona_info = self._get_persona_info(agent["name"])
        pid_data = self._load_pid_data(agent["name"])
        running_pid = self._is_agent_running(agent["name"])

        return {
            "name": agent["name"],
            "display_name": persona_info.get("display_name") or None,
            "type": agent["type"],
            "path": str(agent["path"]),
            "skill_file": str(agent["skill_file"]),
            "running": bool(running_pid),
            "status": "running" if running_pid else "stopped",
            "pid": running_pid or pid_data.get("pid") or None,
            "mode": pid_data.get("mode"),
            "model": pid_data.get("model"),
            "started_at": pid_data.get("started"),
            "temp_dir": pid_data.get("temp_dir"),
        }

    def _list_agents(self) -> tuple:
        """Listet alle verfuegbaren Agents."""
        agents = self._scan_agents()

        if not agents:
            return (True, t("no_agents_found", default="Keine Agents mit SKILL.md gefunden."))

        output = [
            "=== VERFUEGBARE AGENTS ===",
            "",
            f"{'Name':25} {'Typ':8} {'Status':10}",
            "-" * 45
        ]

        for ag in agents:
            pid = self._is_agent_running(ag["name"])
            status = f"[RUNNING:{pid}]" if pid else "[STOPPED]"
            output.append(f"{ag['name']:25} {ag['type']:8} {status}")

        output.extend([
            "",
            f"--- {t('commands_label', default='Befehle')} ---",
            "bach agent start <name>    " + t("agent_start_desc", default="Agent starten"),
            "bach agent stop <name>     " + t("agent_stop_desc", default="Agent stoppen"),
            "bach agent status          " + t("agent_status_desc", default="Laufende Agents anzeigen"),
            "bach agent rename <n> <n>  " + t("agent_rename_desc", default="Display-Name aendern")
        ])

        return (True, "\n".join(output))

    def _list_agents_json(self) -> tuple:
        """Listet alle verfuegbaren Agents als JSON."""
        entries = [self._agent_list_entry(agent) for agent in self._scan_agents()]
        payload = {
            "generated_at": datetime.now().isoformat(),
            "active_count": sum(1 for entry in entries if entry["running"]),
            "agents": entries,
        }
        return True, self._json_dump(payload)

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    def _parse_flag(self, args: list, flag: str, default: str) -> str:
        """Extrahiert --flag value aus args."""
        for i, arg in enumerate(args):
            if arg == flag and i + 1 < len(args):
                return args[i + 1]
        return default

    def _resolve_db_skill_dir_name(self, resolved: dict) -> str | None:
        """Leitet aus einer DB-Skill-Pfad-Angabe den aktuellen Verzeichnisnamen ab."""
        table = resolved.get("source_table")
        if table not in {"bach_agents", "bach_experts"}:
            return None

        db_path = self.data_dir / "bach.db"
        if not db_path.exists():
            return None

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT skill_path FROM {table} WHERE name = ?",
                (resolved["name"],),
            )
            row = cursor.fetchone()
            conn.close()
        except Exception:
            return None

        if not row or "skill_path" not in row.keys() or not row["skill_path"]:
            return None

        normalized = str(row["skill_path"]).replace("\\", "/").rstrip("/")
        directory_name = Path(normalized).name
        return directory_name or None

    def _resolve_to_technical_name(self, query: str) -> str:
        """Loest Display-Name/Rolle/Beschreibung zum technischen Namen auf."""
        # Erst direkt pruefen (schneller Pfad)
        agents = self._scan_agents()
        agent_names = {ag["name"] for ag in agents}
        for ag in agents:
            if ag["name"].lower() == query.lower():
                return ag["name"]

        # Dann ueber DB (display_name, description, persona)
        try:
            from .agents import resolve_agent_name
            db_path = self.data_dir / "bach.db"
            result = resolve_agent_name(db_path, query)
            if result:
                if result["name"] in agent_names:
                    return result["name"]
                skill_dir_name = self._resolve_db_skill_dir_name(result)
                if skill_dir_name and skill_dir_name in agent_names:
                    return skill_dir_name
                return result['name']
        except Exception:
            pass

        return query  # Unveraendert zurueckgeben

    def _get_persona_info(self, name: str) -> dict:
        """Laedt display_name und persona aus der DB."""
        db_path = self.data_dir / "bach.db"
        if not db_path.exists():
            return {}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            for table in ('bach_agents', 'bach_experts'):
                try:
                    cursor.execute(
                        f"SELECT display_name, persona FROM {table} WHERE name = ?",
                        (name,))
                    row = cursor.fetchone()
                    if row:
                        conn.close()
                        return {
                            'display_name': row['display_name'] or '',
                            'persona': row['persona'] or '',
                        }
                    cursor.execute(
                        f"SELECT display_name, persona, skill_path FROM {table} "
                        "WHERE skill_path IS NOT NULL AND skill_path != ''"
                    )
                    for candidate in cursor.fetchall():
                        normalized = str(candidate["skill_path"]).replace("\\", "/").rstrip("/")
                        if Path(normalized).name == name:
                            conn.close()
                            return {
                                'display_name': candidate['display_name'] or '',
                                'persona': candidate['persona'] or '',
                            }
                except sqlite3.OperationalError:
                    continue
            conn.close()
        except Exception:
            pass
        return {}

    def _start_agent(self, name: str, args: list, dry_run: bool) -> tuple:
        """Startet einen Agent."""
        # Name-Resolution: Display-Name, Rolle oder Beschreibung -> technischer Name
        resolved_name = self._resolve_to_technical_name(name)

        # Agent finden
        agents = self._scan_agents()
        agent = None
        for ag in agents:
            if ag["name"] == resolved_name:
                agent = ag
                break

        if not agent:
            return (False, f"[ERROR] Agent '{name}' {t('agent_not_found', default='nicht gefunden oder hat keine SKILL.md')}")

        # Bereits laufend?
        pid = self._is_agent_running(resolved_name)
        if pid:
            return (False, f"[WARN] Agent '{resolved_name}' {t('agent_already_running', default='laeuft bereits')} (PID {pid})")

        mode = self._parse_flag(args, "--mode", "default")
        model = self._parse_flag(args, "--model", "sonnet")

        if mode not in ("plan", "default"):
            return (False, f"[ERROR] {t('agent_invalid_mode', default='Ungueltiger Modus')}: {mode} (plan, default)")
        if model not in ("sonnet", "opus", "haiku"):
            return (False, f"[ERROR] {t('agent_invalid_model', default='Ungueltiges Modell')}: {model} (sonnet, opus, haiku)")

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Agent '{resolved_name}' starten (mode={mode}, model={model})")

        # Verzeichnisse sicherstellen
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Temporaere CLAUDE.md erstellen
        agent_temp_dir = self.temp_dir / f"agent_{resolved_name}"
        agent_temp_dir.mkdir(parents=True, exist_ok=True)
        claude_md = agent_temp_dir / "CLAUDE.md"

        try:
            skill_content = agent["skill_file"].read_text(encoding='utf-8')
        except Exception as e:
            return (False, f"[ERROR] SKILL.md nicht lesbar: {e}")

        # Persona aus DB laden
        persona_info = self._get_persona_info(resolved_name)
        display_name = persona_info.get('display_name', '')
        persona = persona_info.get('persona', '')

        persona_block = ""
        if display_name or persona:
            persona_block = "\n## Persona\n"
            if display_name:
                persona_block += f"Dein Name ist \"{display_name}\".\n"
            if persona:
                persona_block += f"Dein Charakter: {persona}\n"
            persona_block += "\n"

        claude_md_content = (
            f"# BACH Agent: {resolved_name}\n\n"
            f"Du bist der BACH Agent \"{resolved_name}\". Befolge die folgende SKILL.md\n"
            f"als deine Identitaet und Arbeitsanweisung.\n\n"
            f"BACH System-Pfad: {self.base_path}\n"
            f"Nutze die Tools und Dateien im BACH-System unter diesem Pfad.\n"
            f"Antworte auf Deutsch.\n"
            f"{persona_block}\n"
            f"---\n\n"
            f"{skill_content}"
        )

        try:
            claude_md.write_text(claude_md_content, encoding='utf-8')
        except Exception as e:
            return (False, f"[ERROR] CLAUDE.md konnte nicht geschrieben werden: {e}")

        # Claude-Prozess starten
        cmd = ["claude", "--model", model]

        if mode == "plan":
            cmd.extend(["--plan-mode", "plan"])

        try:
            if sys.platform == 'win32':
                # Windows: neues Fenster via cmd /c start
                agent_label = display_name or resolved_name
                title = f"BACH: {agent_label}"
                # start.bat im Temp-Verzeichnis erstellen
                start_bat = agent_temp_dir / "start.bat"
                bat_content = (
                    f"@echo off\n"
                    f"title {title}\n"
                    f"cd /d \"{agent_temp_dir}\"\n"
                    f"echo === BACH Agent: {agent_label} ({resolved_name}) ===\n"
                    f"echo Modell: {model} ^| Modus: {mode}\n"
                    f"echo.\n"
                    f"{' '.join(cmd)}\n"
                    f"echo.\n"
                    f"echo {t('session_ended', default='Session beendet. Druecke eine Taste...')}\n"
                    f"pause\n"
                )
                start_bat.write_text(bat_content, encoding='utf-8')

                proc = subprocess.Popen(
                    ["cmd", "/c", "start", title, "cmd", "/c", str(start_bat)],
                    cwd=str(agent_temp_dir),
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(agent_temp_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )

            # PID speichern
            pid_data = {
                "pid": proc.pid,
                "name": resolved_name,
                "display_name": display_name,
                "type": agent["type"],
                "model": model,
                "mode": mode,
                "started": datetime.now().isoformat(),
                "temp_dir": str(agent_temp_dir)
            }
            pid_file = self.pid_dir / f"{resolved_name}.pid"
            pid_file.write_text(json.dumps(pid_data, indent=2), encoding='utf-8')

            agent_label = display_name or resolved_name
            return (True, (
                f"[OK] Agent '{agent_label}' ({resolved_name}) gestartet\n"
                f"     PID:    {proc.pid}\n"
                f"     Typ:    {agent['type']}\n"
                f"     Modell: {model}\n"
                f"     Modus:  {mode}\n"
                f"     Temp:   {agent_temp_dir}"
            ))

        except FileNotFoundError:
            return (False, "[ERROR] 'claude' CLI nicht gefunden. Ist Claude Code installiert?")
        except Exception as e:
            return (False, f"[ERROR] Start fehlgeschlagen: {e}")

    # ------------------------------------------------------------------
    # stop
    # ------------------------------------------------------------------

    def _stop_agent(self, name: str, dry_run: bool) -> tuple:
        """Stoppt einen laufenden Agent."""
        resolved_name = self._resolve_to_technical_name(name)
        pid_file = self.pid_dir / f"{resolved_name}.pid"

        if not pid_file.exists():
            return (False, f"[WARN] Agent '{name}' hat kein PID-File (laeuft nicht)")

        try:
            data = json.loads(pid_file.read_text(encoding='utf-8'))
            pid = data.get("pid", 0)
        except (json.JSONDecodeError, ValueError):
            pid_file.unlink(missing_ok=True)
            return (False, f"[ERROR] PID-File fuer '{name}' ist ungueltig (entfernt)")

        if not pid:
            pid_file.unlink(missing_ok=True)
            return (False, f"[ERROR] Keine PID fuer Agent '{name}' (PID-File entfernt)")

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Agent '{name}' (PID {pid}) stoppen")

        try:
            if sys.platform == 'win32':
                subprocess.run(
                    ['taskkill', '/PID', str(pid), '/T', '/F'],
                    capture_output=True
                )
            else:
                os.kill(pid, signal.SIGTERM)

            # PID-File entfernen
            pid_file.unlink(missing_ok=True)

            return (True, f"[OK] Agent '{name}' (PID {pid}) gestoppt")

        except Exception as e:
            pid_file.unlink(missing_ok=True)
            return (False, f"[ERROR] Stoppen fehlgeschlagen: {e}")

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _show_status(self) -> tuple:
        """Zeigt alle laufenden Agents."""
        self.pid_dir.mkdir(parents=True, exist_ok=True)

        pid_files = list(self.pid_dir.glob("*.pid"))

        if not pid_files:
            return (True, f"=== AGENT STATUS ===\n\n{t('no_agents_registered', default='Keine Agents registriert.')}")

        output = [
            "=== AGENT STATUS ===",
            "",
            f"{'Name':25} {'PID':>7}  {'Modell':8} {'Modus':8} {'Gestartet':20} {'Status':10}",
            "-" * 85
        ]

        active = 0
        for pf in sorted(pid_files):
            try:
                data = json.loads(pf.read_text(encoding='utf-8'))
                name = data.get("name", pf.stem)
                pid = data.get("pid", 0)
                model = data.get("model", "?")
                mode = data.get("mode", "?")
                started = data.get("started", "?")
                if started and started != "?":
                    started = started[:19]  # ISO ohne Microseconds

                # Pruefen ob Prozess noch laeuft
                running = False
                if pid:
                    if sys.platform == 'win32':
                        result = subprocess.run(
                            ['tasklist', '/FI', f'PID eq {pid}'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace'
                        )
                        running = str(pid) in (result.stdout or '')
                    else:
                        try:
                            os.kill(pid, 0)
                            running = True
                        except OSError:
                            running = False

                status = "[RUNNING]" if running else "[DEAD]"
                if running:
                    active += 1
                else:
                    # Totes PID-File aufraeumen
                    pf.unlink(missing_ok=True)

                output.append(f"{name:25} {pid:>7}  {model:8} {mode:8} {started:20} {status}")

            except (json.JSONDecodeError, ValueError):
                output.append(f"{pf.stem:25} {'?':>7}  {'?':8} {'?':8} {'?':20} [INVALID]")
                pf.unlink(missing_ok=True)

        output.extend([
            "",
            f"Aktiv: {active} / {len(pid_files)}"
        ])

        return (True, "\n".join(output))

    def _show_status_json(self) -> tuple:
        """Zeigt laufende Agents als maschinenlesbaren JSON-Status."""
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        pid_files = list(self.pid_dir.glob("*.pid"))

        agents = []
        active = 0

        for pf in sorted(pid_files):
            try:
                data = json.loads(pf.read_text(encoding='utf-8'))
                name = data.get("name", pf.stem)
                running_pid = self._is_agent_running(name)
                running = bool(running_pid)
                display_name = data.get("display_name") or self._get_persona_info(name).get("display_name") or None
                if running:
                    active += 1
                else:
                    pf.unlink(missing_ok=True)

                agents.append({
                    "name": name,
                    "display_name": display_name,
                    "type": data.get("type"),
                    "running": running,
                    "status": "running" if running else "dead",
                    "pid": running_pid or data.get("pid") or None,
                    "model": data.get("model"),
                    "mode": data.get("mode"),
                    "started_at": data.get("started"),
                    "temp_dir": data.get("temp_dir"),
                    "pid_file": str(pf),
                })
            except (json.JSONDecodeError, ValueError):
                agents.append({
                    "name": pf.stem,
                    "display_name": None,
                    "type": None,
                    "running": False,
                    "status": "invalid",
                    "pid": None,
                    "model": None,
                    "mode": None,
                    "started_at": None,
                    "temp_dir": None,
                    "pid_file": str(pf),
                })
                pf.unlink(missing_ok=True)

        payload = {
            "generated_at": datetime.now().isoformat(),
            "registered_count": len(agents),
            "active_count": active,
            "agents": agents,
        }
        return True, self._json_dump(payload)

    # ------------------------------------------------------------------
    # rename
    # ------------------------------------------------------------------

    def _rename_agent(self, query: str, new_display_name: str, dry_run: bool) -> tuple:
        """Aendert den Display-Namen eines Agenten/Experten."""
        db_path = self.data_dir / "bach.db"
        if not db_path.exists():
            return (False, f"[ERROR] {t('db_not_found', default='Datenbank nicht gefunden')}")

        try:
            from .agents import resolve_agent_name
            result = resolve_agent_name(db_path, query)
        except Exception as e:
            return (False, f"[ERROR] {t('name_resolution_failed', default='Name-Resolution fehlgeschlagen')}: {e}")

        if not result:
            return (False, f"[ERROR] {t('not_found', default='nicht gefunden')}: {query}")

        table = result['source_table']
        tech_name = result['name']
        old_display = result['display_name']

        if dry_run:
            return (True, f"[DRY-RUN] {t('agent_rename_would', default='Wuerde umbenennen')}: '{tech_name}' '{old_display}' -> '{new_display_name}'")

        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                f"UPDATE {table} SET display_name = ? WHERE name = ?",
                (new_display_name, tech_name)
            )
            conn.commit()
            conn.close()
            return (True, (
                f"{t('display_name_changed', default='[OK] Display-Name geaendert')}\n"
                f"     Agent:  {tech_name}\n"
                f"     {t('previous_label', default='Vorher')}: {old_display}\n"
                f"     {t('now_label', default='Neu')}:    {new_display_name}"
            ))
        except Exception as e:
            return (False, f"[ERROR] {t('rename_failed', default='Umbenennung fehlgeschlagen')}: {e}")
