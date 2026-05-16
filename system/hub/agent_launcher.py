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
            "doctor": t(
                "agent_doctor_desc",
                default="Agent-Preflight und Recovery-Hinweise anzeigen (bach agent doctor [name])",
            ),
            "steer": t(
                "agent_steer_desc",
                default='Operator-Hinweis fuer laufenden Agenten vormerken (bach agent steer <name> "Hinweis")',
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
        available_actions: list[str],
        dry_run: bool = False,
    ) -> dict:
        """Erzeugt ein konsistentes Agent-Payload fuer JSON-Kontrollantworten."""
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
            "available_actions": available_actions,
            "pending_operator_notes": len(self._read_operator_notes(name, temp_dir=temp_dir)),
            "operator_notes_file": str(self._agent_operator_notes_path(name, temp_dir=temp_dir, markdown=True)),
        }
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

    def _agent_operator_notes_path(self, name: str, *, temp_dir: str | None = None, markdown: bool = False) -> Path:
        """Liefert den Operator-Notizpfad fuer einen Agenten."""
        base_dir = Path(temp_dir) if temp_dir else Path(
            self._load_pid_data(name).get("temp_dir") or (self.temp_dir / f"agent_{name}")
        )
        filename = "OPERATOR_NOTES.md" if markdown else "operator_notes.json"
        return base_dir / filename

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

    def _write_operator_notes(self, name: str, notes: list[dict], *, temp_dir: str | None = None):
        """Schreibt Operator-Hinweise als JSON und Markdown-Spiegel."""
        json_path = self._agent_operator_notes_path(name, temp_dir=temp_dir)
        markdown_path = self._agent_operator_notes_path(name, temp_dir=temp_dir, markdown=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(notes, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        markdown_lines = [
            "# Operator Notes",
            "",
            "Diese Hinweise wurden nach dem Agent-Start vorgemerkt.",
            "Bei laengeren Laeufen regelmaessig pruefen und einarbeiten.",
            "",
        ]
        for note in notes:
            requested_at = note.get("requested_at") or "ohne Zeitstempel"
            markdown_lines.append(f"- [{requested_at}] {note['message']}")
        markdown_lines.append("")
        markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")

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
        temp_dir = pid_data.get("temp_dir")
        notes = self._read_operator_notes(agent["name"], temp_dir=temp_dir)

        return {
            "name": agent["name"],
            "display_name": persona_info.get("display_name") or None,
            "type": agent["type"],
            "path": str(agent["path"]),
            "skill_file": str(agent["skill_file"]),
            "running": running,
            "status": "running" if running else "stopped",
            "pid": running_pid or pid_data.get("pid") or None,
            "mode": pid_data.get("mode"),
            "model": pid_data.get("model"),
            "started_at": started_at,
            "runtime_seconds": self._compute_runtime_seconds(started_at) if running else None,
            "temp_dir": temp_dir,
            "pending_operator_notes": len(notes),
            "operator_notes_file": str(self._agent_operator_notes_path(agent["name"], temp_dir=temp_dir, markdown=True)),
            "available_actions": ["stop", "steer"] if running else ["start"],
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
            "bach agent steer <n> ...   " + t("agent_steer_desc", default="Operator-Hinweis vormerken"),
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
            message = f"[WARN] Agent '{resolved_name}' {t('agent_already_running', default='laeuft bereits')} (PID {pid})"
            payload = self._build_agent_payload(
                resolved_name,
                self._get_persona_info(resolved_name).get("display_name"),
                agent["type"],
                running=True,
                status="running",
                pid=pid,
                model=None,
                mode=None,
                started_at=None,
                temp_dir=str(self.temp_dir / f"agent_{resolved_name}"),
                window_title=None,
                pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
                available_actions=["stop", "steer"],
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
        agent_temp_dir = self.temp_dir / f"agent_{resolved_name}"
        pid_file = self.pid_dir / f"{resolved_name}.pid"

        if dry_run:
            message = f"[DRY-RUN] Wuerde Agent '{resolved_name}' starten (mode={mode}, model={model})"
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
        operator_block = (
            "\n## Operator Notes\n"
            f"Pruefe bei laengeren Laeufen regelmaessig die Datei `{operator_notes_path.name}` "
            "im aktuellen Arbeitsverzeichnis. Dort koennen spaetere Operator-Hinweise fuer diese Session auftauchen.\n\n"
        )

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
            self._write_operator_notes(resolved_name, [], temp_dir=str(agent_temp_dir))
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
            }
            pid_file.write_text(json.dumps(pid_data, indent=2), encoding='utf-8')

            agent_label = display_name or resolved_name
            message = (
                f"[OK] Agent '{agent_label}' ({resolved_name}) gestartet\n"
                f"     PID:    {proc.pid}\n"
                f"     Typ:    {agent['type']}\n"
                f"     Modell: {model}\n"
                f"     Modus:  {mode}\n"
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
                available_actions=["stop", "steer"],
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
            message = f"[WARN] Agent '{name}' hat kein PID-File (laeuft nicht)"
            payload = self._build_agent_payload(
                resolved_name,
                display_name,
                None,
                running=False,
                status="stopped",
                pid=None,
                model=None,
                mode=None,
                started_at=None,
                temp_dir=None,
                window_title=None,
                pid_file=str(pid_file),
                available_actions=["start"],
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
            status="stopped",
            pid=pid,
            model=data.get("model"),
            mode=data.get("mode"),
            started_at=data.get("started"),
            temp_dir=data.get("temp_dir"),
            window_title=data.get("window_title"),
            pid_file=str(pid_file),
            available_actions=["start"],
            dry_run=dry_run,
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

    def _steer_agent(self, name: str, message: str, dry_run: bool, json_output: bool = False) -> tuple:
        """Merkt einen Operator-Hinweis fuer einen laufenden Agenten vor."""
        resolved_name = self._resolve_to_technical_name(name)
        pid_data = self._load_pid_data(resolved_name)
        running_pid = self._is_agent_running(resolved_name)
        display_name = pid_data.get("display_name") or self._get_persona_info(resolved_name).get("display_name") or None
        temp_dir = pid_data.get("temp_dir")

        if not running_pid or not temp_dir:
            message_text = f"[WARN] Agent '{name}' laeuft nicht oder hat kein Laufzeitverzeichnis."
            agent_payload = self._build_agent_payload(
                resolved_name,
                display_name,
                pid_data.get("type"),
                running=False,
                status="stopped",
                pid=None,
                model=pid_data.get("model"),
                mode=pid_data.get("mode"),
                started_at=pid_data.get("started"),
                temp_dir=temp_dir,
                window_title=pid_data.get("window_title"),
                pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
                available_actions=["start"],
            )
            return self._action_response(
                "steer",
                name,
                resolved_name,
                False,
                message_text,
                json_output=json_output,
                agent=agent_payload,
            )

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
                pid_data.get("type"),
                running=True,
                status="running",
                pid=running_pid,
                model=pid_data.get("model"),
                mode=pid_data.get("mode"),
                started_at=pid_data.get("started"),
                temp_dir=temp_dir,
                window_title=pid_data.get("window_title"),
                pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
                available_actions=["stop", "steer"],
                dry_run=True,
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
                pid_data.get("type"),
                running=True,
                status="running",
                pid=running_pid,
                model=pid_data.get("model"),
                mode=pid_data.get("mode"),
                started_at=pid_data.get("started"),
                temp_dir=temp_dir,
                window_title=pid_data.get("window_title"),
                pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
                available_actions=["stop", "steer"],
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
            pid_data.get("type"),
            running=True,
            status="running",
            pid=running_pid,
            model=pid_data.get("model"),
            mode=pid_data.get("mode"),
            started_at=pid_data.get("started"),
            temp_dir=temp_dir,
            window_title=pid_data.get("window_title"),
            pid_file=str(self.pid_dir / f"{resolved_name}.pid"),
            available_actions=["stop", "steer"],
        )
        return self._action_response(
            "steer",
            name,
            resolved_name,
            True,
            (
                f"[OK] Operator-Hinweis fuer '{display_name or resolved_name}' vorgemerkt "
                f"({len(notes)} Nachricht(en) in Queue)."
            ),
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

                agents.append({
                    "name": name,
                    "display_name": display_name,
                    "type": data.get("type"),
                    "running": running,
                    "status": "running" if running else "dead",
                    "pid": running_pid or data.get("pid") or None,
                    "model": data.get("model"),
                    "mode": data.get("mode"),
                    "started_at": started_at,
                    "runtime_seconds": self._compute_runtime_seconds(started_at) if running else None,
                    "temp_dir": temp_dir,
                    "window_title": data.get("window_title"),
                    "pid_file": str(pf),
                    "pending_operator_notes": len(notes),
                    "operator_notes_file": str(self._agent_operator_notes_path(name, temp_dir=temp_dir, markdown=True)),
                    "available_actions": ["stop", "steer"] if running else ["start"],
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
                    "runtime_seconds": None,
                    "temp_dir": None,
                    "window_title": None,
                    "pid_file": str(pf),
                    "pending_operator_notes": 0,
                    "operator_notes_file": str(self._agent_operator_notes_path(pf.stem, markdown=True)),
                    "available_actions": ["start"],
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
