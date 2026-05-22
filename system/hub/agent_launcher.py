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
import shutil
import re
from pathlib import Path
from datetime import datetime
from .base import BaseHandler
from .lang import t

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None


class AgentLauncherHandler(BaseHandler):
    """Handler fuer Agent-Operationen (list, start, stop, steer, status)."""

    DEFAULT_ALLOWED_TOOLS = "Read,Grep,Glob,Bash,WebFetch,WebSearch"
    VALID_PERMISSION_MODES = {"restricted", "full"}

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
            "doctor": t(
                "agent_doctor_desc",
                default="Agent-Preflight und Recovery-Hinweise anzeigen (bach agent doctor [name])",
            ),
            "steer": t(
                "agent_steer_desc",
                default='Operator-Hinweis fuer laufenden Agenten vormerken (bach agent steer <name> "Hinweis")',
            ),
            "pause": t(
                "agent_pause_desc",
                default="Kooperative Pause fuer laufenden Agenten vormerken (bach agent pause <name> [Grund])",
            ),
            "resume": t(
                "agent_resume_desc",
                default="Kooperative Pause fuer einen Agenten aufheben (bach agent resume <name>)",
            ),
            "clear-steer": t(
                "agent_clear_steer_desc",
                default="Operator-Hinweise fuer einen Agenten loeschen (bach agent clear-steer <name>)",
            ),
            "rename": t("agent_rename_desc", default="Display-Name aendern (bach agent rename <name> <neuer-name>)")
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        json_output = self._has_flag(args, "--json")
        filtered_args = [arg for arg in args if arg != "--json"]

        if operation == "list":
            if json_output:
                return self._list_agents_json()
            return self._list_agents()
        elif operation == "start":
            if not filtered_args:
                message = f"[ERROR] {t('agent_name_required', default='Agent-Name erforderlich')}: bach agent start <name>"
                return self._action_response(
                    "start",
                    None,
                    None,
                    False,
                    message,
                    json_output=json_output,
                )
            name = filtered_args[0]
            return self._start_agent(name, filtered_args[1:], dry_run, json_output=json_output)
        elif operation == "stop":
            if not filtered_args:
                message = f"[ERROR] {t('agent_name_required', default='Agent-Name erforderlich')}: bach agent stop <name>"
                return self._action_response(
                    "stop",
                    None,
                    None,
                    False,
                    message,
                    json_output=json_output,
                )
            return self._stop_agent(filtered_args[0], dry_run, json_output=json_output)
        elif operation == "status":
            if json_output:
                return self._show_status_json()
            return self._show_status()
        elif operation == "doctor":
            query = next((arg for arg in filtered_args if not arg.startswith("-")), None)
            return self._doctor_agent(query, json_output=json_output)
        elif operation == "steer":
            if len(filtered_args) < 2:
                return self._action_response(
                    "steer",
                    None,
                    None,
                    False,
                    '[ERROR] Syntax: bach agent steer <name> "Hinweis"',
                    json_output=json_output,
                )
            return self._steer_agent(
                filtered_args[0],
                " ".join(filtered_args[1:]),
                dry_run,
                json_output=json_output,
            )
        elif operation == "pause":
            if not filtered_args:
                return self._action_response(
                    "pause",
                    None,
                    None,
                    False,
                    "[ERROR] Syntax: bach agent pause <name> [Grund]",
                    json_output=json_output,
                )
            return self._pause_agent(
                filtered_args[0],
                " ".join(filtered_args[1:]).strip() or "Manuell pausiert",
                dry_run,
                json_output=json_output,
            )
        elif operation == "resume":
            if not filtered_args:
                return self._action_response(
                    "resume",
                    None,
                    None,
                    False,
                    "[ERROR] Syntax: bach agent resume <name>",
                    json_output=json_output,
                )
            return self._resume_agent(
                filtered_args[0],
                dry_run,
                json_output=json_output,
            )
        elif operation == "clear-steer":
            if not filtered_args:
                return self._action_response(
                    "clear-steer",
                    None,
                    None,
                    False,
                    "[ERROR] Syntax: bach agent clear-steer <name>",
                    json_output=json_output,
                )
            return self._clear_steer_agent(
                filtered_args[0],
                dry_run,
                json_output=json_output,
            )
        elif operation == "rename":
            if len(filtered_args) < 2:
                return (False, t("agent_rename_syntax", default="[ERROR] Syntax: bach agent rename <name> <neuer-display-name>"))
            return self._rename_agent(filtered_args[0], ' '.join(filtered_args[1:]), dry_run)
        else:
            return self._list_agents()

    def _has_flag(self, args: list, *flags: str) -> bool:
        """Prueft ob ein Flag in den CLI-Argumenten gesetzt wurde."""
        return any(arg in flags for arg in args)

    def _json_dump(self, payload: dict) -> str:
        """Formatiert JSON konsistent fuer CLI-Ausgabe."""
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _action_response(
        self,
        action: str,
        requested_name: str | None,
        resolved_name: str | None,
        ok: bool,
        message: str,
        *,
        json_output: bool = False,
        agent: dict | None = None,
    ) -> tuple:
        """Formatiert mutierende Aktionen optional maschinenlesbar."""
        if not json_output:
            return ok, message

        payload = {
            "generated_at": datetime.now().isoformat(),
            "action": action,
            "requested_name": requested_name,
            "resolved_name": resolved_name,
            "ok": ok,
            "message": message,
        }
        if agent is not None:
            payload["agent"] = agent
        return ok, self._json_dump(payload)

    def _build_agent_payload(
        self,
        name: str,
        display_name: str | None,
        agent_type: str | None,
        *,
        running: bool,
        status: str,
        pid: int | None,
        model: str | None,
        mode: str | None,
        started_at: str | None,
        temp_dir: str | None,
        window_title: str | None,
        pid_file: str | None,
        available_actions: list[str] | None,
        dry_run: bool = False,
        notes: list[dict] | None = None,
        permission_mode: str | None = None,
        allowed_tools: str | None = None,
        max_turns: int | None = None,
        runtime_defaults: dict | None = None,
    ) -> dict:
        """Erzeugt ein konsistentes Agent-Payload fuer JSON-Kontrollantworten."""
        note_entries = notes if notes is not None else self._read_operator_notes(name, temp_dir=temp_dir)
        actions = list(available_actions or self._available_actions(running, len(note_entries)))
        if len(note_entries) and "clear-steer" not in actions:
            actions.append("clear-steer")
        resolved_defaults = runtime_defaults or self._runtime_defaults_for_name(name)
        active_permission_mode = permission_mode or resolved_defaults["permission_mode"]
        active_allowed_tools = allowed_tools
        if active_permission_mode != "full" and active_allowed_tools is None:
            active_allowed_tools = resolved_defaults["allowed_tools"]
        payload = {
            "name": name,
            "display_name": display_name or None,
            "type": agent_type,
            "running": running,
            "status": status,
            "pid": pid,
            "model": model,
            "mode": mode,
            "started_at": started_at,
            "runtime_seconds": self._compute_runtime_seconds(started_at) if running else None,
            "temp_dir": temp_dir,
            "window_title": window_title,
            "pid_file": pid_file,
            "permission_mode": active_permission_mode,
            "allowed_tools": None if active_permission_mode == "full" else active_allowed_tools,
            "max_turns": max_turns if max_turns is not None else resolved_defaults["max_turns"],
            "runtime_defaults": resolved_defaults,
            "available_actions": actions,
            "pending_operator_notes": len(note_entries),
            "queued_for_next_start": bool(note_entries) and not running,
            "latest_operator_note": note_entries[-1]["message"] if note_entries else None,
            "latest_operator_note_at": note_entries[-1].get("requested_at") if note_entries else None,
            "operator_notes_file": str(self._agent_operator_notes_path(name, temp_dir=temp_dir, markdown=True)),
        }
        payload["operator_control"] = self._agent_control_snapshot(
            name,
            running=running,
            notes=note_entries,
            temp_dir=temp_dir,
        )
        if dry_run:
            payload["dry_run"] = True
        return payload

    def _compute_runtime_seconds(self, started_at: str | None) -> int | None:
        """Berechnet die Laufzeit eines Agenten fuer JSON-Statusflaechen."""
        if not started_at:
            return None
        try:
            delta = datetime.now() - datetime.fromisoformat(str(started_at))
        except (TypeError, ValueError):
            return None
        return max(0, int(delta.total_seconds()))

    def _resolved_agent_temp_dir(self, name: str, *, temp_dir: str | None = None) -> str:
        """Liefert das kanonische Laufzeitverzeichnis eines Agenten."""
        if temp_dir:
            return str(Path(temp_dir))
        pid_temp_dir = self._load_pid_data(name).get("temp_dir")
        if pid_temp_dir:
            return str(Path(pid_temp_dir))
        return str(self.temp_dir / f"agent_{name}")

    def _agent_operator_notes_path(self, name: str, *, temp_dir: str | None = None, markdown: bool = False) -> Path:
        """Liefert den Operator-Notizpfad fuer einen Agenten."""
        base_dir = Path(self._resolved_agent_temp_dir(name, temp_dir=temp_dir))
        filename = "OPERATOR_NOTES.md" if markdown else "operator_notes.json"
        return base_dir / filename

    def _agent_pause_request_path(self, name: str, *, temp_dir: str | None = None) -> Path:
        """Liefert den Dateipfad fuer kooperative Pause-Anforderungen."""
        base_dir = Path(self._resolved_agent_temp_dir(name, temp_dir=temp_dir))
        return base_dir / "operator_pause.json"

    def _read_operator_notes(self, name: str, *, temp_dir: str | None = None) -> list[dict]:
        """Liest vorgemerkte Operator-Hinweise."""
        path = self._agent_operator_notes_path(name, temp_dir=temp_dir)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, list):
            return [
                item for item in payload
                if isinstance(item, dict) and item.get("message")
            ]
        return []

    def _read_pause_request(self, name: str, *, temp_dir: str | None = None) -> dict | None:
        """Liest eine kooperative Pause-Anforderung fuer einen Agenten."""
        path = self._agent_pause_request_path(name, temp_dir=temp_dir)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(payload, dict) and payload.get("reason"):
            return payload
        return None

    def _agent_control_actions(self, *, running: bool, pause_requested: bool, note_count: int) -> list[str]:
        """Leitet verfuegbare kooperative Kontrollaktionen ab."""
        actions = []
        if pause_requested:
            actions.append("resume")
        elif running:
            actions.append("pause")
        actions.append("steer")
        if note_count:
            actions.append("clear-steer")
        return actions

    def _agent_control_snapshot(
        self,
        name: str,
        *,
        running: bool,
        notes: list[dict] | None = None,
        temp_dir: str | None = None,
    ) -> dict:
        """Erzeugt einen maschinenlesbaren Snapshot der Agenten-Steuerung."""
        note_entries = notes if notes is not None else self._read_operator_notes(name, temp_dir=temp_dir)
        pause_request = self._read_pause_request(name, temp_dir=temp_dir)
        latest = note_entries[-1] if note_entries else None
        snapshot = {
            "scope": "agent",
            "pause_requested": bool(pause_request),
            "pause_reason": pause_request.get("reason") if pause_request else None,
            "pause_requested_at": pause_request.get("requested_at") if pause_request else None,
            "pending_steer_count": len(note_entries),
            "latest_steer_message": latest.get("message") if latest else None,
            "latest_steer_requested_at": latest.get("requested_at") if latest else None,
            "pause_file": str(self._agent_pause_request_path(name, temp_dir=temp_dir)),
            "notes_file": str(self._agent_operator_notes_path(name, temp_dir=temp_dir)),
            "notes_markdown_file": str(self._agent_operator_notes_path(name, temp_dir=temp_dir, markdown=True)),
        }
        snapshot["available_actions"] = self._agent_control_actions(
            running=running,
            pause_requested=snapshot["pause_requested"],
            note_count=len(note_entries),
        )
        return snapshot

    def _available_actions(self, running: bool, note_count: int) -> list[str]:
        """Leitet die sinnvollen Kontrollaktionen aus Status und Queue ab."""
        actions = ["stop", "steer"] if running else ["start", "steer"]
        if note_count:
            actions.append("clear-steer")
        return actions

    def _inactive_status(self, note_count: int) -> str:
        """Leitet den Nicht-Live-Status eines Agenten aus der Hinweis-Queue ab."""
        return "queued" if note_count else "stopped"

    def _running_status(self, *, pause_requested: bool) -> str:
        """Leitet den Live-Status eines Agenten aus dem Kontrollzustand ab."""
        return "pause-requested" if pause_requested else "running"

    def _refresh_operator_markdown(self, name: str, notes: list[dict], *, temp_dir: str | None = None):
        """Aktualisiert die menschenlesbare Operator-Datei inklusive Pause-Status."""
        markdown_path = self._agent_operator_notes_path(name, temp_dir=temp_dir, markdown=True)
        pause_request = self._read_pause_request(name, temp_dir=temp_dir)

        if not notes and not pause_request:
            markdown_path.unlink(missing_ok=True)
            return

        markdown_lines = [
            "# Operator Notes",
            "",
        ]
        if pause_request:
            requested_at = pause_request.get("requested_at") or "ohne Zeitstempel"
            markdown_lines.extend(
                [
                    "## Pause Request",
                    "",
                    f"- [{requested_at}] {pause_request.get('reason', 'Manuell pausiert')}",
                    "Bitte am naechsten sicheren Checkpoint anhalten, kurz den aktuellen Stand sichern und auf `bach agent resume` warten.",
                    "",
                ]
            )

        markdown_lines.extend(
            [
                "## Steering Notes",
                "",
                "Diese Hinweise gelten fuer diese Agenten-Session.",
                "Bereits vorgemerkte Hinweise werden beim naechsten Start in die initiale CLAUDE.md injiziert.",
                "Bei laengeren Laeufen regelmaessig pruefen und an sicheren Checkpoints einarbeiten.",
                "",
            ]
        )
        if notes:
            for note in notes:
                requested_at = note.get("requested_at") or "ohne Zeitstempel"
                markdown_lines.append(f"- [{requested_at}] {note['message']}")
        else:
            markdown_lines.append("- Keine vorgemerkten Steering-Hinweise.")
        markdown_lines.append("")
        markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    def _clear_operator_notes(self, name: str, *, temp_dir: str | None = None) -> int:
        """Entfernt alle vorgemerkten oder veralteten Operator-Hinweise fuer einen Agenten."""
        notes = self._read_operator_notes(name, temp_dir=temp_dir)
        self._agent_operator_notes_path(name, temp_dir=temp_dir).unlink(missing_ok=True)
        self._refresh_operator_markdown(name, [], temp_dir=temp_dir)
        return len(notes)

    def _write_pause_request(self, name: str, payload: dict, *, temp_dir: str | None = None):
        """Schreibt eine kooperative Pause-Anforderung."""
        pause_path = self._agent_pause_request_path(name, temp_dir=temp_dir)
        pause_path.parent.mkdir(parents=True, exist_ok=True)
        pause_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._refresh_operator_markdown(
            name,
            self._read_operator_notes(name, temp_dir=temp_dir),
            temp_dir=temp_dir,
        )

    def _clear_pause_request(self, name: str, *, temp_dir: str | None = None) -> bool:
        """Entfernt eine kooperative Pause-Anforderung."""
        pause_path = self._agent_pause_request_path(name, temp_dir=temp_dir)
        existed = pause_path.exists()
        pause_path.unlink(missing_ok=True)
        self._refresh_operator_markdown(
            name,
            self._read_operator_notes(name, temp_dir=temp_dir),
            temp_dir=temp_dir,
        )
        return existed

    def _write_operator_notes(self, name: str, notes: list[dict], *, temp_dir: str | None = None):
        """Schreibt Operator-Hinweise als JSON und Markdown-Spiegel."""
        json_path = self._agent_operator_notes_path(name, temp_dir=temp_dir)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(notes, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._refresh_operator_markdown(name, notes, temp_dir=temp_dir)

    def _render_operator_prompt_block(self, operator_notes_path: Path, notes: list[dict]) -> str:
        """Erzeugt den Operator-Block fuer die generierte CLAUDE.md eines Agenten."""
        lines = [
            "\n## Operator Notes",
            (
                f"Pruefe die Datei `{operator_notes_path.name}` im aktuellen Arbeitsverzeichnis "
                "regelmaessig an sicheren Checkpoints, besonders nach groesseren Tool-Runden, "
                "vor Statusmeldungen und vor dem Abschluss. Die Datei kann neben Steering-Hinweisen "
                "auch kooperative Pause-Anforderungen enthalten."
            ),
        ]
        if notes:
            lines.extend(
                [
                    "",
                    "Diese Hinweise waren bereits vor diesem Start vorgemerkt und gelten sofort:",
                ]
            )
            for note in notes:
                requested_at = note.get("requested_at") or "ohne Zeitstempel"
                lines.append(f"- [{requested_at}] {note['message']}")
        else:
            lines.extend(
                [
                    "",
                    "Aktuell sind keine vorgemerkten Hinweise vorhanden.",
                ]
            )
        lines.append("")
        return "\n".join(lines) + "\n"

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
        started_at = pid_data.get("started")
        running = bool(running_pid)
        temp_dir = self._resolved_agent_temp_dir(agent["name"], temp_dir=pid_data.get("temp_dir"))
        notes = self._read_operator_notes(agent["name"], temp_dir=temp_dir)
        payload = self._build_agent_payload(
            agent["name"],
            persona_info.get("display_name") or None,
            agent["type"],
            running=running,
            status="running" if running else self._inactive_status(len(notes)),
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=started_at,
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{agent['name']}.pid"),
            available_actions=self._available_actions(running, len(notes)),
            notes=notes,
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
            runtime_defaults=self._load_agent_runtime_defaults(agent["skill_file"]),
        )
        payload["path"] = str(agent["path"])
        payload["skill_file"] = str(agent["skill_file"])
        return payload

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
            notes = self._read_operator_notes(ag["name"])
            if pid:
                status = f"[RUNNING:{pid}]"
            elif notes:
                status = f"[QUEUED:{len(notes)}]"
            else:
                status = "[STOPPED]"
            output.append(f"{ag['name']:25} {ag['type']:8} {status}")

        output.extend([
            "",
            f"--- {t('commands_label', default='Befehle')} ---",
            "bach agent start <name>    " + t("agent_start_desc", default="Agent starten"),
            "bach agent stop <name>     " + t("agent_stop_desc", default="Agent stoppen"),
            "bach agent status          " + t("agent_status_desc", default="Laufende Agents anzeigen"),
            "bach agent steer <n> ...   " + t("agent_steer_desc", default="Operator-Hinweis vormerken"),
            "bach agent pause <n> ...   " + t("agent_pause_desc", default="Kooperative Pause vormerken"),
            "bach agent resume <n>      " + t("agent_resume_desc", default="Kooperative Pause aufheben"),
            "bach agent clear-steer <n> " + t("agent_clear_steer_desc", default="Operator-Hinweise loeschen"),
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

    def _read_skill_frontmatter(self, skill_file: Path) -> dict:
        """Liest YAML-Frontmatter aus einer SKILL.md-Datei."""
        if yaml is None:
            return {}
        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError:
            return {}

        match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
        if not match:
            return {}

        try:
            payload = yaml.safe_load(match.group(1)) or {}
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _normalize_runtime_defaults(self, payload: dict | None) -> dict:
        """Normalisiert Agent-Runtime-Defaults aus Frontmatter oder Laufzeitdaten."""
        payload = payload or {}
        permission_mode = str(payload.get("permission_mode") or "restricted").strip().lower()
        if permission_mode not in self.VALID_PERMISSION_MODES:
            permission_mode = "restricted"

        allowed_tools = payload.get("allowed_tools")
        if isinstance(allowed_tools, (list, tuple, set)):
            allowed_tools = ",".join(str(item).strip() for item in allowed_tools if str(item).strip())
        elif allowed_tools is not None:
            allowed_tools = str(allowed_tools).strip()
        if not allowed_tools:
            allowed_tools = self.DEFAULT_ALLOWED_TOOLS

        max_turns = payload.get("max_turns")
        try:
            max_turns = int(max_turns) if max_turns not in (None, "", False) else None
        except (TypeError, ValueError):
            max_turns = None
        if max_turns is not None and max_turns <= 0:
            max_turns = None

        return {
            "permission_mode": permission_mode,
            "allowed_tools": None if permission_mode == "full" else allowed_tools,
            "max_turns": max_turns,
        }

    def _load_agent_runtime_defaults(self, skill_file: Path) -> dict:
        """Lädt optionale Agent-Startdefaults aus der SKILL.md."""
        metadata = self._read_skill_frontmatter(skill_file)
        runtime = metadata.get("agent_runtime") or metadata.get("runtime") or {}
        if not isinstance(runtime, dict):
            runtime = {}
        merged = {
            "permission_mode": runtime.get("permission_mode", metadata.get("permission_mode")),
            "allowed_tools": runtime.get("allowed_tools", metadata.get("allowed_tools")),
            "max_turns": runtime.get("max_turns", metadata.get("max_turns")),
        }
        return self._normalize_runtime_defaults(merged)

    def _runtime_defaults_for_name(self, name: str) -> dict:
        """Lädt Runtime-Defaults eines bekannten Agenten anhand seines Namens."""
        agent_entry = next((item for item in self._scan_agents() if item["name"] == name), None)
        if not agent_entry:
            return self._normalize_runtime_defaults({})
        return self._load_agent_runtime_defaults(agent_entry["skill_file"])

    def _parse_max_turns(self, value) -> int | None:
        """Validiert eine optionale Max-Turns-Angabe."""
        if value in (None, "", False):
            return None
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("Max-Turns muss eine positive Ganzzahl sein.") from exc
        if parsed <= 0:
            raise ValueError("Max-Turns muss groesser als 0 sein.")
        return parsed

    def _check_runtime_dir(self, name: str, path: Path, label: str) -> dict:
        """Prueft ob ein Laufzeit-Verzeichnis verfuegbar und beschreibbar ist."""
        details = {"path": str(path)}
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".agent_doctor_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {
                "name": name,
                "status": "ok",
                "message": f"{label} ist verfuegbar und beschreibbar.",
                "details": details,
            }
        except Exception as exc:
            return {
                "name": name,
                "status": "error",
                "message": f"{label} ist nicht beschreibbar: {exc}",
                "details": details,
            }

    def _check_claude_cli(self) -> dict:
        """Prueft ob die Claude CLI fuer Agent-Starts verfuegbar ist."""
        cli_path = shutil.which("claude")
        if not cli_path:
            return {
                "name": "claude_cli",
                "status": "error",
                "message": "Claude Code CLI wurde nicht gefunden.",
                "details": {"expected_command": "claude"},
            }

        details = {"path": cli_path}
        status = "ok"
        message = f"Claude Code CLI gefunden: {cli_path}"
        try:
            result = subprocess.run(
                [cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
            version_text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
            version_line = version_text.splitlines()[0].strip() if version_text else ""
            if version_line:
                details["version"] = version_line
                message = f"{message} ({version_line})"
            elif result.returncode != 0:
                status = "warn"
                details["returncode"] = result.returncode
                message = "Claude Code CLI gefunden, aber die Versionspruefung blieb leer."
        except Exception as exc:
            status = "warn"
            details["version_check_error"] = str(exc)
            message = "Claude Code CLI gefunden, aber die Versionspruefung ist fehlgeschlagen."

        return {
            "name": "claude_cli",
            "status": status,
            "message": message,
            "details": details,
        }

    def _find_agent_record(self, query: str | None) -> tuple[str | None, dict | None]:
        """Liefert den aufgeloesten technischen Agent-Namen und den Scan-Eintrag."""
        if not query:
            return None, None

        resolved_name = self._resolve_to_technical_name(query)
        for agent in self._scan_agents():
            if agent["name"] == resolved_name:
                return resolved_name, agent
        return resolved_name, None

    def _summarize_checks(self, checks: list[dict]) -> dict:
        """Reduziert Diagnosen auf einen kompakten Status-Block."""
        counts = {"ok": 0, "warn": 0, "error": 0}
        for check in checks:
            status = check.get("status", "warn")
            counts[status] = counts.get(status, 0) + 1

        if counts["error"]:
            overall = "error"
        elif counts["warn"]:
            overall = "warn"
        else:
            overall = "ok"

        return {
            "ok": counts.get("ok", 0),
            "warn": counts.get("warn", 0),
            "error": counts.get("error", 0),
            "overall_status": overall,
        }

    def _doctor_payload(self, query: str | None) -> dict:
        """Erstellt einen strukturierten Agent-Preflight-Report."""
        checks = [
            self._check_runtime_dir("data_dir", self.data_dir, "BACH-Datenverzeichnis"),
            self._check_runtime_dir("pid_dir", self.pid_dir, "PID-Verzeichnis"),
            self._check_runtime_dir("temp_dir", self.temp_dir, "Temp-Verzeichnis"),
            self._check_claude_cli(),
        ]

        resolved_name, agent = self._find_agent_record(query)
        payload = {
            "generated_at": datetime.now().isoformat(),
            "requested_name": query,
            "resolved_name": resolved_name,
            "agent": None,
            "checks": checks,
            "next_steps": [],
        }

        can_start = None

        if query:
            if not agent:
                checks.append(
                    {
                        "name": "agent_exists",
                        "status": "error",
                        "message": f"Agent '{query}' wurde nicht gefunden.",
                        "details": {"requested_name": query, "resolved_name": resolved_name},
                    }
                )
                can_start = False
            else:
                persona_info = self._get_persona_info(resolved_name)
                payload["agent"] = {
                    "name": resolved_name,
                    "display_name": persona_info.get("display_name") or None,
                    "type": agent["type"],
                    "path": str(agent["path"]),
                    "skill_file": str(agent["skill_file"]),
                }
                checks.append(
                    {
                        "name": "agent_exists",
                        "status": "ok",
                        "message": f"Agent '{resolved_name}' wurde gefunden.",
                        "details": payload["agent"],
                    }
                )
                try:
                    skill_preview = agent["skill_file"].read_text(encoding="utf-8")[:120]
                    checks.append(
                        {
                            "name": "skill_file",
                            "status": "ok",
                            "message": "SKILL.md ist lesbar.",
                            "details": {
                                "path": str(agent["skill_file"]),
                                "preview": skill_preview,
                            },
                        }
                    )
                except Exception as exc:
                    checks.append(
                        {
                            "name": "skill_file",
                            "status": "error",
                            "message": f"SKILL.md ist nicht lesbar: {exc}",
                            "details": {"path": str(agent["skill_file"])},
                        }
                    )

                pid_file = self.pid_dir / f"{resolved_name}.pid"
                had_pid_file = pid_file.exists()
                pid_data = self._load_pid_data(resolved_name)
                running_pid = self._is_agent_running(resolved_name)
                stale_pid = had_pid_file and not running_pid and not pid_file.exists()

                if running_pid:
                    checks.append(
                        {
                            "name": "runtime_state",
                            "status": "warn",
                            "message": f"Agent laeuft bereits (PID {running_pid}).",
                            "details": {"pid": running_pid, "pid_file": str(pid_file)},
                        }
                    )
                    can_start = False
                elif stale_pid:
                    checks.append(
                        {
                            "name": "runtime_state",
                            "status": "warn",
                            "message": "Eine veraltete PID-Datei wurde bereinigt.",
                            "details": {"previous_pid": pid_data.get("pid"), "pid_file": str(pid_file)},
                        }
                    )
                else:
                    checks.append(
                        {
                            "name": "runtime_state",
                            "status": "ok",
                            "message": "Kein laufender Agent-Prozess erkannt.",
                            "details": {"pid_file": str(pid_file)},
                        }
                    )

        summary = self._summarize_checks(checks)
        ready = summary["error"] == 0
        if can_start is None:
            can_start = ready
        elif can_start is False:
            can_start = False
        else:
            can_start = ready

        summary["ready"] = ready
        summary["can_start"] = can_start
        payload["summary"] = summary

        next_steps = []
        if any(check["name"] == "claude_cli" and check["status"] == "error" for check in checks):
            next_steps.append("Claude Code CLI installieren oder den PATH fuer `claude` korrigieren.")
        if query and any(check["name"] == "agent_exists" and check["status"] == "error" for check in checks):
            next_steps.append("Mit `bach agent list` verfuegbare Agenten pruefen und die SKILL.md-Pfade kontrollieren.")
        if query and any(check["name"] == "skill_file" and check["status"] == "error" for check in checks):
            next_steps.append("Die betroffene SKILL.md reparieren oder Datei-/Ordnerrechte pruefen.")
        if query and any(check["name"] == "runtime_state" and check["message"].startswith("Agent laeuft bereits") for check in checks):
            next_steps.append(f"`bach agent status --json` pruefen oder `{resolved_name}` gezielt stoppen.")
        elif query and can_start:
            next_steps.append(f"`bach agent start {resolved_name} --dry-run` als sicherer Vorabtest.")
            next_steps.append(f"`bach agent start {resolved_name}` fuer den echten Start.")

        if not next_steps:
            next_steps.append("Keine Aktion noetig. Agent-Preflight ist bereits gruen.")

        payload["next_steps"] = next_steps
        return payload

    def _format_doctor_text(self, payload: dict) -> str:
        """Formatiert den Agent-Doctor-Report fuer die CLI."""
        status_map = {"ok": "OK", "warn": "WARN", "error": "ERROR"}
        summary = payload["summary"]
        agent = payload.get("agent") or {}

        if payload.get("requested_name"):
            target = payload.get("resolved_name") or payload["requested_name"]
            if agent.get("display_name"):
                target = f"{agent['display_name']} ({target})"
        else:
            target = "Globaler Agent-Preflight"

        lines = [
            "=== AGENT DOCTOR ===",
            "",
            f"Ziel:    {target}",
            f"Zeit:    {payload['generated_at'][:19]}",
            f"Status:  {summary['overall_status'].upper()}",
            f"Ready:   {'ja' if summary['ready'] else 'nein'}",
        ]

        if payload.get("requested_name"):
            lines.append(f"Startbar:{' ja' if summary['can_start'] else ' nein'}")

        lines.extend(["", "Checks:"])
        for check in payload["checks"]:
            lines.append(f"  [{status_map.get(check['status'], check['status'].upper())}] {check['message']}")
            details = check.get("details") or {}
            if details.get("path"):
                lines.append(f"      Pfad: {details['path']}")
            if details.get("version"):
                lines.append(f"      Version: {details['version']}")

        lines.extend(["", "Naechste Schritte:"])
        for step in payload["next_steps"]:
            lines.append(f"  - {step}")

        return "\n".join(lines)

    def _doctor_agent(self, query: str | None, json_output: bool = False) -> tuple:
        """Diagnostiziert Agent-Voraussetzungen und liefert Recovery-Hinweise."""
        payload = self._doctor_payload(query)
        if json_output:
            return True, self._json_dump(payload)
        return True, self._format_doctor_text(payload)

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

    def _start_agent(self, name: str, args: list, dry_run: bool, json_output: bool = False) -> tuple:
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
            message = f"[ERROR] Agent '{name}' {t('agent_not_found', default='nicht gefunden oder hat keine SKILL.md')}"
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
            )

        # Bereits laufend?
        pid = self._is_agent_running(resolved_name)
        if pid:
            pid_data = self._load_pid_data(resolved_name)
            message = f"[WARN] Agent '{resolved_name}' {t('agent_already_running', default='laeuft bereits')} (PID {pid})"
            payload = self._build_agent_payload(
                resolved_name,
                pid_data.get("display_name") or self._get_persona_info(resolved_name).get("display_name"),
                agent["type"],
                running=True,
                status="running",
                pid=pid,
                model=pid_data.get("model"),
                mode=pid_data.get("mode"),
                started_at=pid_data.get("started"),
                temp_dir=pid_data.get("temp_dir") or str(self.temp_dir / f"agent_{resolved_name}"),
                window_title=pid_data.get("window_title"),
                pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
                available_actions=["stop", "steer"],
                permission_mode=pid_data.get("permission_mode"),
                allowed_tools=pid_data.get("allowed_tools"),
                max_turns=pid_data.get("max_turns"),
            )
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
                agent=payload,
            )

        mode = self._parse_flag(args, "--mode", "default")
        model = self._parse_flag(args, "--model", "sonnet")

        if mode not in ("plan", "default"):
            message = f"[ERROR] {t('agent_invalid_mode', default='Ungueltiger Modus')}: {mode} (plan, default)"
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
            )
        if model not in ("sonnet", "opus", "haiku"):
            message = f"[ERROR] {t('agent_invalid_model', default='Ungueltiges Modell')}: {model} (sonnet, opus, haiku)"
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
            )

        persona_info = self._get_persona_info(resolved_name)
        display_name = persona_info.get('display_name', '')
        agent_temp_dir = Path(self._resolved_agent_temp_dir(resolved_name))
        pid_file = self.pid_dir / f"{resolved_name}.pid"
        runtime_defaults = self._load_agent_runtime_defaults(agent["skill_file"])
        permission_mode = self._parse_flag(
            args,
            "--permission-mode",
            runtime_defaults["permission_mode"],
        ).strip().lower()
        allowed_tools = self._parse_flag(
            args,
            "--allowed-tools",
            runtime_defaults["allowed_tools"] or self.DEFAULT_ALLOWED_TOOLS,
        ).strip()
        max_turns_raw = self._parse_flag(
            args,
            "--max-turns",
            str(runtime_defaults["max_turns"]) if runtime_defaults["max_turns"] else "",
        )

        if permission_mode not in self.VALID_PERMISSION_MODES:
            message = (
                f"[ERROR] Ungueltiger Permission-Modus: {permission_mode} "
                "(restricted, full)"
            )
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
            )
        if permission_mode != "full" and not allowed_tools:
            message = "[ERROR] --allowed-tools darf im restricted-Modus nicht leer sein."
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
            )
        try:
            max_turns = self._parse_max_turns(max_turns_raw)
        except ValueError as exc:
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                f"[ERROR] {exc}",
                json_output=json_output,
            )

        if dry_run:
            message = (
                f"[DRY-RUN] Wuerde Agent '{resolved_name}' starten "
                f"(mode={mode}, model={model}, permission={permission_mode})"
            )
            payload = self._build_agent_payload(
                resolved_name,
                display_name,
                agent["type"],
                running=False,
                status="planned",
                pid=None,
                model=model,
                mode=mode,
                started_at=None,
                temp_dir=str(agent_temp_dir),
                window_title=f"BACH: {display_name or resolved_name}" if sys.platform == 'win32' else None,
                pid_file=str(pid_file),
                available_actions=["start"],
                dry_run=True,
                permission_mode=permission_mode,
                allowed_tools=None if permission_mode == "full" else allowed_tools,
                max_turns=max_turns,
                runtime_defaults=runtime_defaults,
            )
            return self._action_response(
                "start",
                name,
                resolved_name,
                True,
                message,
                json_output=json_output,
                agent=payload,
            )

        # Verzeichnisse sicherstellen
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Temporaere CLAUDE.md erstellen
        agent_temp_dir.mkdir(parents=True, exist_ok=True)
        claude_md = agent_temp_dir / "CLAUDE.md"

        try:
            skill_content = agent["skill_file"].read_text(encoding='utf-8')
        except Exception as e:
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                f"[ERROR] SKILL.md nicht lesbar: {e}",
                json_output=json_output,
            )

        persona = persona_info.get('persona', '')

        persona_block = ""
        if display_name or persona:
            persona_block = "\n## Persona\n"
            if display_name:
                persona_block += f"Dein Name ist \"{display_name}\".\n"
            if persona:
                persona_block += f"Dein Charakter: {persona}\n"
            persona_block += "\n"

        operator_notes_path = self._agent_operator_notes_path(
            resolved_name,
            temp_dir=str(agent_temp_dir),
            markdown=True,
        )
        existing_notes = self._read_operator_notes(
            resolved_name,
            temp_dir=str(agent_temp_dir),
        )
        operator_block = self._render_operator_prompt_block(operator_notes_path, existing_notes)

        claude_md_content = (
            f"# BACH Agent: {resolved_name}\n\n"
            f"Du bist der BACH Agent \"{resolved_name}\". Befolge die folgende SKILL.md\n"
            f"als deine Identitaet und Arbeitsanweisung.\n\n"
            f"BACH System-Pfad: {self.base_path}\n"
            f"Nutze die Tools und Dateien im BACH-System unter diesem Pfad.\n"
            f"Antworte auf Deutsch.\n"
            f"{persona_block}\n"
            f"{operator_block}"
            f"---\n\n"
            f"{skill_content}"
        )

        try:
            claude_md.write_text(claude_md_content, encoding='utf-8')
            self._clear_pause_request(
                resolved_name,
                temp_dir=str(agent_temp_dir),
            )
            self._write_operator_notes(
                resolved_name,
                existing_notes,
                temp_dir=str(agent_temp_dir),
            )
        except Exception as e:
            message = f"[ERROR] CLAUDE.md konnte nicht geschrieben werden: {e}"
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
            )

        # Claude-Prozess starten
        cmd = ["claude", "--model", model]
        if max_turns is not None:
            cmd.extend(["--max-turns", str(max_turns)])
        if permission_mode == "full":
            cmd.append("--dangerously-skip-permissions")
        else:
            cmd.extend(["--allowedTools", allowed_tools])

        if mode == "plan":
            cmd.extend(["--plan-mode", "plan"])

        try:
            if sys.platform == 'win32':
                # Windows: eigenes Konsolenfenster direkt ueber cmd.exe starten.
                # So bleibt die getrackte PID ueber die gesamte Agenten-Session
                # stabil, statt nur den kurzlebigen `start`-Launcher zu sehen.
                agent_label = display_name or resolved_name
                title = f"BACH: {agent_label}"
                # start.bat im Temp-Verzeichnis erstellen
                start_bat = agent_temp_dir / "start.bat"
                headless = self._has_flag(args, "--headless")
                bat_lines = [
                    f"@echo off",
                    f"title {title}",
                    f'cd /d "{agent_temp_dir}"',
                    f"echo === BACH Agent: {agent_label} ({resolved_name}) ===",
                    f"echo Modell: {model} ^| Modus: {mode}",
                    f"echo.",
                    f"{' '.join(cmd)}",
                ]
                if not headless:
                    bat_lines.append('if not defined BACH_AUTO pause')
                bat_content = "\n".join(bat_lines) + "\n"
                start_bat.write_text(bat_content, encoding='utf-8')

                if headless:
                    creation_flags = subprocess.CREATE_NO_WINDOW
                else:
                    creation_flags = subprocess.CREATE_NEW_CONSOLE
                proc = subprocess.Popen(
                    ["cmd", "/c", str(start_bat)],
                    cwd=str(agent_temp_dir),
                    creationflags=creation_flags
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
                "temp_dir": str(agent_temp_dir),
                "window_title": title if sys.platform == 'win32' else None,
                "permission_mode": permission_mode,
                "allowed_tools": None if permission_mode == "full" else allowed_tools,
                "max_turns": max_turns,
            }
            pid_file.write_text(json.dumps(pid_data, indent=2), encoding='utf-8')

            agent_label = display_name or resolved_name
            message = (
                f"[OK] Agent '{agent_label}' ({resolved_name}) gestartet\n"
                f"     PID:    {proc.pid}\n"
                f"     Typ:    {agent['type']}\n"
                f"     Modell: {model}\n"
                f"     Modus:  {mode}\n"
                f"     Rechte: {permission_mode}\n"
                f"     Hinweise: {len(existing_notes)} vorgemerkt\n"
                f"     Temp:   {agent_temp_dir}"
            )
            payload = self._build_agent_payload(
                resolved_name,
                display_name,
                agent["type"],
                running=True,
                status="running",
                pid=proc.pid,
                model=model,
                mode=mode,
                started_at=pid_data["started"],
                temp_dir=str(agent_temp_dir),
                window_title=pid_data.get("window_title"),
                pid_file=str(pid_file),
                available_actions=self._available_actions(True, len(existing_notes)),
                notes=existing_notes,
                permission_mode=permission_mode,
                allowed_tools=None if permission_mode == "full" else allowed_tools,
                max_turns=max_turns,
                runtime_defaults=runtime_defaults,
            )
            return self._action_response(
                "start",
                name,
                resolved_name,
                True,
                message,
                json_output=json_output,
                agent=payload,
            )

        except FileNotFoundError:
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                "[ERROR] 'claude' CLI nicht gefunden. Ist Claude Code installiert?",
                json_output=json_output,
            )
        except Exception as e:
            return self._action_response(
                "start",
                name,
                resolved_name,
                False,
                f"[ERROR] Start fehlgeschlagen: {e}",
                json_output=json_output,
            )

    # ------------------------------------------------------------------
    # stop
    # ------------------------------------------------------------------

    def _stop_agent(self, name: str, dry_run: bool, json_output: bool = False) -> tuple:
        """Stoppt einen laufenden Agent."""
        resolved_name = self._resolve_to_technical_name(name)
        pid_file = self.pid_dir / f"{resolved_name}.pid"
        persona_info = self._get_persona_info(resolved_name)
        display_name = persona_info.get("display_name")

        if not pid_file.exists():
            temp_dir = self._resolved_agent_temp_dir(resolved_name)
            notes = self._read_operator_notes(resolved_name, temp_dir=temp_dir)
            message = f"[WARN] Agent '{name}' hat kein PID-File (laeuft nicht)"
            payload = self._build_agent_payload(
                resolved_name,
                display_name,
                None,
                running=False,
                status=self._inactive_status(len(notes)),
                pid=None,
                model=None,
                mode=None,
                started_at=None,
                temp_dir=temp_dir,
                window_title=None,
                pid_file=str(pid_file),
                available_actions=self._available_actions(False, len(notes)),
                notes=notes,
            )
            return self._action_response(
                "stop",
                name,
                resolved_name,
                False,
                message,
                json_output=json_output,
                agent=payload,
            )

        try:
            data = json.loads(pid_file.read_text(encoding='utf-8'))
            pid = data.get("pid", 0)
        except (json.JSONDecodeError, ValueError):
            pid_file.unlink(missing_ok=True)
            return self._action_response(
                "stop",
                name,
                resolved_name,
                False,
                f"[ERROR] PID-File fuer '{name}' ist ungueltig (entfernt)",
                json_output=json_output,
            )

        if not pid:
            pid_file.unlink(missing_ok=True)
            return self._action_response(
                "stop",
                name,
                resolved_name,
                False,
                f"[ERROR] Keine PID fuer Agent '{name}' (PID-File entfernt)",
                json_output=json_output,
            )

        agent_payload = self._build_agent_payload(
            resolved_name,
            data.get("display_name") or display_name,
            data.get("type"),
            running=False,
            status=self._inactive_status(
                len(self._read_operator_notes(resolved_name, temp_dir=data.get("temp_dir")))
            ),
            pid=pid,
            model=data.get("model"),
            mode=data.get("mode"),
            started_at=data.get("started"),
            temp_dir=data.get("temp_dir"),
            window_title=data.get("window_title"),
            pid_file=str(pid_file),
            available_actions=self._available_actions(
                False,
                len(self._read_operator_notes(resolved_name, temp_dir=data.get("temp_dir"))),
            ),
            dry_run=dry_run,
            notes=self._read_operator_notes(resolved_name, temp_dir=data.get("temp_dir")),
            permission_mode=data.get("permission_mode"),
            allowed_tools=data.get("allowed_tools"),
            max_turns=data.get("max_turns"),
        )

        if dry_run:
            return self._action_response(
                "stop",
                name,
                resolved_name,
                True,
                f"[DRY-RUN] Wuerde Agent '{name}' (PID {pid}) stoppen",
                json_output=json_output,
                agent=agent_payload,
            )

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
            self._clear_pause_request(resolved_name, temp_dir=data.get("temp_dir"))

            return self._action_response(
                "stop",
                name,
                resolved_name,
                True,
                f"[OK] Agent '{name}' (PID {pid}) gestoppt",
                json_output=json_output,
                agent=agent_payload,
            )

        except Exception as e:
            pid_file.unlink(missing_ok=True)
            return self._action_response(
                "stop",
                name,
                resolved_name,
                False,
                f"[ERROR] Stoppen fehlgeschlagen: {e}",
                json_output=json_output,
                agent=agent_payload,
            )

    def _pause_agent(self, name: str, reason: str, dry_run: bool, json_output: bool = False) -> tuple:
        """Merkt eine kooperative Pause fuer einen laufenden Agenten vor."""
        resolved_name = self._resolve_to_technical_name(name)
        agent_entry = next((item for item in self._scan_agents() if item["name"] == resolved_name), None)
        if not agent_entry:
            return self._action_response(
                "pause",
                name,
                resolved_name,
                False,
                f"[ERROR] Agent '{name}' nicht gefunden.",
                json_output=json_output,
            )

        pid_data = self._load_pid_data(resolved_name)
        running_pid = self._is_agent_running(resolved_name)
        running = bool(running_pid)
        display_name = pid_data.get("display_name") or self._get_persona_info(resolved_name).get("display_name") or None
        temp_dir = self._resolved_agent_temp_dir(resolved_name, temp_dir=pid_data.get("temp_dir"))
        notes = self._read_operator_notes(resolved_name, temp_dir=temp_dir)
        pause_request = self._read_pause_request(resolved_name, temp_dir=temp_dir)

        agent_payload = self._build_agent_payload(
            resolved_name,
            display_name,
            pid_data.get("type") or agent_entry["type"],
            running=running,
            status="running" if running else self._inactive_status(len(notes)),
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=self._available_actions(running, len(notes)),
            dry_run=dry_run,
            notes=notes,
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
        )

        if not running:
            return self._action_response(
                "pause",
                name,
                resolved_name,
                False,
                f"[WARN] Agent '{display_name or resolved_name}' laeuft nicht. Pause ist nur fuer aktive Laeufe verfuegbar.",
                json_output=json_output,
                agent=agent_payload,
            )

        if pause_request:
            return self._action_response(
                "pause",
                name,
                resolved_name,
                True,
                f"[OK] Fuer '{display_name or resolved_name}' ist bereits eine Pause vorgemerkt.",
                json_output=json_output,
                agent=agent_payload,
            )

        if dry_run:
            return self._action_response(
                "pause",
                name,
                resolved_name,
                True,
                f"[DRY-RUN] Wuerde kooperative Pause fuer '{display_name or resolved_name}' vormerken: {reason}",
                json_output=json_output,
                agent=agent_payload,
            )

        self._write_pause_request(
            resolved_name,
            {
                "reason": reason,
                "requested_at": datetime.now().isoformat(),
            },
            temp_dir=temp_dir,
        )
        refreshed = self._build_agent_payload(
            resolved_name,
            display_name,
            pid_data.get("type") or agent_entry["type"],
            running=running,
            status="running",
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=self._available_actions(running, len(notes)),
            notes=notes,
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
        )
        return self._action_response(
            "pause",
            name,
            resolved_name,
            True,
            f"[OK] Kooperative Pause fuer '{display_name or resolved_name}' vorgemerkt: {reason}",
            json_output=json_output,
            agent=refreshed,
        )

    def _resume_agent(self, name: str, dry_run: bool, json_output: bool = False) -> tuple:
        """Hebt eine kooperative Pause eines Agenten auf."""
        resolved_name = self._resolve_to_technical_name(name)
        agent_entry = next((item for item in self._scan_agents() if item["name"] == resolved_name), None)
        if not agent_entry:
            return self._action_response(
                "resume",
                name,
                resolved_name,
                False,
                f"[ERROR] Agent '{name}' nicht gefunden.",
                json_output=json_output,
            )

        pid_data = self._load_pid_data(resolved_name)
        running_pid = self._is_agent_running(resolved_name)
        running = bool(running_pid)
        display_name = pid_data.get("display_name") or self._get_persona_info(resolved_name).get("display_name") or None
        temp_dir = self._resolved_agent_temp_dir(resolved_name, temp_dir=pid_data.get("temp_dir"))
        notes = self._read_operator_notes(resolved_name, temp_dir=temp_dir)
        pause_request = self._read_pause_request(resolved_name, temp_dir=temp_dir)

        agent_payload = self._build_agent_payload(
            resolved_name,
            display_name,
            pid_data.get("type") or agent_entry["type"],
            running=running,
            status="running" if running else self._inactive_status(len(notes)),
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=self._available_actions(running, len(notes)),
            dry_run=dry_run,
            notes=notes,
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
        )

        if not pause_request:
            return self._action_response(
                "resume",
                name,
                resolved_name,
                True,
                f"[OK] Fuer '{display_name or resolved_name}' ist keine Pause vorgemerkt.",
                json_output=json_output,
                agent=agent_payload,
            )

        if dry_run:
            return self._action_response(
                "resume",
                name,
                resolved_name,
                True,
                f"[DRY-RUN] Wuerde kooperative Pause fuer '{display_name or resolved_name}' aufheben.",
                json_output=json_output,
                agent=agent_payload,
            )

        self._clear_pause_request(resolved_name, temp_dir=temp_dir)
        refreshed = self._build_agent_payload(
            resolved_name,
            display_name,
            pid_data.get("type") or agent_entry["type"],
            running=running,
            status="running" if running else self._inactive_status(len(notes)),
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=self._available_actions(running, len(notes)),
            notes=notes,
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
        )
        return self._action_response(
            "resume",
            name,
            resolved_name,
            True,
            f"[OK] Kooperative Pause fuer '{display_name or resolved_name}' aufgehoben.",
            json_output=json_output,
            agent=refreshed,
        )

    def _clear_steer_agent(self, name: str, dry_run: bool, json_output: bool = False) -> tuple:
        """Leert die Operator-Hinweis-Queue eines Agenten."""
        resolved_name = self._resolve_to_technical_name(name)
        pid_data = self._load_pid_data(resolved_name)
        running_pid = self._is_agent_running(resolved_name)
        running = bool(running_pid)
        display_name = pid_data.get("display_name") or self._get_persona_info(resolved_name).get("display_name") or None
        temp_dir = self._resolved_agent_temp_dir(resolved_name, temp_dir=pid_data.get("temp_dir"))

        agent_entry = next((item for item in self._scan_agents() if item["name"] == resolved_name), None)
        agent_type = pid_data.get("type") or (agent_entry["type"] if agent_entry else None)
        notes = self._read_operator_notes(resolved_name, temp_dir=temp_dir)
        note_count = len(notes)
        json_path = self._agent_operator_notes_path(resolved_name, temp_dir=temp_dir)
        markdown_path = self._agent_operator_notes_path(resolved_name, temp_dir=temp_dir, markdown=True)
        has_queue_files = json_path.exists() or markdown_path.exists()

        agent_payload = self._build_agent_payload(
            resolved_name,
            display_name,
            agent_type,
            running=running,
            status="running" if running else self._inactive_status(note_count),
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=self._available_actions(running, note_count),
            dry_run=dry_run,
            notes=notes,
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
        )

        if note_count == 0 and not has_queue_files:
            return self._action_response(
                "clear-steer",
                name,
                resolved_name,
                True,
                f"Keine Operator-Hinweise für '{display_name or resolved_name}' vorgemerkt.",
                json_output=json_output,
                agent=agent_payload,
            )

        if dry_run:
            if note_count:
                message = (
                    f"[DRY-RUN] Würde {note_count} Operator-Hinweis(e) "
                    f"für '{display_name or resolved_name}' löschen."
                )
            else:
                message = (
                    f"[DRY-RUN] Würde veraltete Operator-Hinweisdateien "
                    f"für '{display_name or resolved_name}' bereinigen."
                )
            agent_payload["dry_run"] = True
            return self._action_response(
                "clear-steer",
                name,
                resolved_name,
                True,
                message,
                json_output=json_output,
                agent=agent_payload,
            )

        try:
            cleared = self._clear_operator_notes(resolved_name, temp_dir=temp_dir)
        except Exception as exc:
            return self._action_response(
                "clear-steer",
                name,
                resolved_name,
                False,
                f"[ERROR] Operator-Hinweise konnten nicht gelöscht werden: {exc}",
                json_output=json_output,
                agent=agent_payload,
            )

        cleared_payload = self._build_agent_payload(
            resolved_name,
            display_name,
            agent_type,
            running=running,
            status="running" if running else self._inactive_status(0),
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=self._available_actions(running, 0),
            notes=[],
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
        )

        if cleared:
            message = f"[OK] {cleared} Operator-Hinweis(e) für '{display_name or resolved_name}' gelöscht."
        else:
            message = f"[OK] Veraltete Operator-Hinweisdateien für '{display_name or resolved_name}' bereinigt."
        return self._action_response(
            "clear-steer",
            name,
            resolved_name,
            True,
            message,
            json_output=json_output,
            agent=cleared_payload,
        )

    def _steer_agent(self, name: str, message: str, dry_run: bool, json_output: bool = False) -> tuple:
        """Merkt einen Operator-Hinweis fuer einen Agenten oder dessen naechsten Start vor."""
        resolved_name = self._resolve_to_technical_name(name)
        agent_entry = next((item for item in self._scan_agents() if item["name"] == resolved_name), None)
        if not agent_entry:
            return self._action_response(
                "steer",
                name,
                resolved_name,
                False,
                f"[ERROR] Agent '{name}' nicht gefunden.",
                json_output=json_output,
            )

        pid_data = self._load_pid_data(resolved_name)
        running_pid = self._is_agent_running(resolved_name)
        running = bool(running_pid)
        display_name = pid_data.get("display_name") or self._get_persona_info(resolved_name).get("display_name") or None
        temp_dir = self._resolved_agent_temp_dir(resolved_name, temp_dir=pid_data.get("temp_dir"))

        notes = self._read_operator_notes(resolved_name, temp_dir=temp_dir)
        notes.append(
            {
                "message": message,
                "requested_at": datetime.now().isoformat(),
            }
        )

        if dry_run:
            preview = (
                f"[DRY-RUN] Wuerde Operator-Hinweis fuer '{display_name or resolved_name}' "
                f"vormerken ({len(notes)} Nachricht(en))."
            )
            agent_payload = self._build_agent_payload(
                resolved_name,
                display_name,
                pid_data.get("type") or agent_entry["type"],
                running=running,
                status="running" if running else self._inactive_status(len(notes)),
                pid=running_pid or pid_data.get("pid") or None,
                model=pid_data.get("model"),
                mode=pid_data.get("mode"),
                started_at=pid_data.get("started"),
                temp_dir=temp_dir,
                window_title=pid_data.get("window_title"),
                pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
                available_actions=self._available_actions(running, len(notes)),
                dry_run=True,
                notes=notes,
                permission_mode=pid_data.get("permission_mode"),
                allowed_tools=pid_data.get("allowed_tools"),
                max_turns=pid_data.get("max_turns"),
            )
            return self._action_response(
                "steer",
                name,
                resolved_name,
                True,
                preview,
                json_output=json_output,
                agent=agent_payload,
            )

        try:
            self._write_operator_notes(resolved_name, notes, temp_dir=temp_dir)
        except Exception as exc:
            agent_payload = self._build_agent_payload(
                resolved_name,
                display_name,
                pid_data.get("type") or agent_entry["type"],
                running=running,
                status="running" if running else self._inactive_status(len(notes)),
                pid=running_pid or pid_data.get("pid") or None,
                model=pid_data.get("model"),
                mode=pid_data.get("mode"),
                started_at=pid_data.get("started"),
                temp_dir=temp_dir,
                window_title=pid_data.get("window_title"),
                pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
                available_actions=self._available_actions(running, len(notes)),
                notes=notes,
                permission_mode=pid_data.get("permission_mode"),
                allowed_tools=pid_data.get("allowed_tools"),
                max_turns=pid_data.get("max_turns"),
            )
            return self._action_response(
                "steer",
                name,
                resolved_name,
                False,
                f"[ERROR] Operator-Hinweis konnte nicht gespeichert werden: {exc}",
                json_output=json_output,
                agent=agent_payload,
            )

        agent_payload = self._build_agent_payload(
            resolved_name,
            display_name,
            pid_data.get("type") or agent_entry["type"],
            running=running,
            status="running" if running else self._inactive_status(len(notes)),
            pid=running_pid or pid_data.get("pid") or None,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=self._available_actions(running, len(notes)),
            notes=notes,
            permission_mode=pid_data.get("permission_mode"),
            allowed_tools=pid_data.get("allowed_tools"),
            max_turns=pid_data.get("max_turns"),
        )
        if running:
            success_message = (
                f"[OK] Operator-Hinweis fuer '{display_name or resolved_name}' vorgemerkt "
                f"({len(notes)} Nachricht(en) in Queue)."
            )
        else:
            success_message = (
                f"[OK] Operator-Hinweis fuer '{display_name or resolved_name}' vorgemerkt "
                f"und fuer den naechsten Start gespeichert ({len(notes)} Nachricht(en) in Queue)."
            )
        return self._action_response(
            "steer",
            name,
            resolved_name,
            True,
            success_message,
            json_output=json_output,
            agent=agent_payload,
        )

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
            f"{'Name':25} {'PID':>7}  {'Modell':8} {'Modus':8} {'Gestartet':20} {'Status':10} {'Notes':>5}",
            "-" * 92
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

                note_count = len(self._read_operator_notes(name, temp_dir=data.get("temp_dir")))
                output.append(f"{name:25} {pid:>7}  {model:8} {mode:8} {started:20} {status:10} {note_count:>5}")

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
                started_at = data.get("started")
                if running:
                    active += 1
                else:
                    pf.unlink(missing_ok=True)

                temp_dir = data.get("temp_dir")
                notes = self._read_operator_notes(name, temp_dir=temp_dir)

                agents.append(
                    self._build_agent_payload(
                        name,
                        display_name,
                        data.get("type"),
                        running=running,
                        status="running" if running else "dead",
                        pid=running_pid or data.get("pid") or None,
                        model=data.get("model"),
                        mode=data.get("mode"),
                        started_at=started_at,
                        temp_dir=temp_dir,
                        window_title=data.get("window_title"),
                        pid_file=str(pf),
                        available_actions=self._available_actions(running, len(notes)),
                        notes=notes,
                        permission_mode=data.get("permission_mode"),
                        allowed_tools=data.get("allowed_tools"),
                        max_turns=data.get("max_turns"),
                    )
                )
            except (json.JSONDecodeError, ValueError):
                agents.append(
                    self._build_agent_payload(
                        pf.stem,
                        None,
                        None,
                        running=False,
                        status="invalid",
                        pid=None,
                        model=None,
                        mode=None,
                        started_at=None,
                        temp_dir=None,
                        window_title=None,
                        pid_file=str(pf),
                        available_actions=["start"],
                    )
                )
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
