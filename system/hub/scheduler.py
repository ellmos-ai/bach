# SPDX-License-Identifier: MIT
"""
Scheduler Handler - Scheduler-Service Verwaltung
=================================================
(Ehemals: Daemon Handler)

=== GUI Jobs System ===
bach scheduler start      Scheduler-Service starten
bach scheduler stop       Scheduler-Service stoppen
bach scheduler status     Status anzeigen
bach scheduler jobs       Jobs auflisten
bach scheduler run ID     Job manuell ausfuehren
bach scheduler logs       Letzte Logs anzeigen

=== Session System (System-Service) ===
bach scheduler session start [--profile NAME]   Session-Scheduler starten
bach scheduler session stop                      Session-Scheduler stoppen
bach scheduler session status                    Session-Status anzeigen
bach scheduler session trigger [--profile NAME]  Session manuell ausloesen
bach scheduler session profiles                  Verfuegbare Profile auflisten

Hinweis: "bach daemon ..." ist ein Alias fuer Rueckwaertskompatibilitaet.
"""
import sys
import os
import signal
import subprocess
import json
import sqlite3
import time
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class SchedulerHandler(BaseHandler):
    """Handler fuer scheduler Operationen (ehemals DaemonHandler)."""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.gui_dir = base_path / "gui"
        self.data_dir = base_path / "data"
        self.log_dir = base_path / "data" / "logs"
        self.daemon_script = self.gui_dir / "daemon_service.py"
        self.pid_file = self.data_dir / "daemon.pid"
        # Scheduler-CLI und GUI-Service muessen dieselbe kanonische BACH-DB sehen.
        self.user_db = Path(self._canonical_db)
        self.scheduler_control_dir = self.data_dir / "scheduler_control"

        # Session System (System-Service)
        # Lives under hub/_services after the service migration.
        self.session_dir = base_path / "hub" / "_services" / "daemon"
        self.session_daemon = self.session_dir / "session_daemon.py"
        self.session_pid_file = self.session_dir / "daemon.pid"
        self.session_profiles_dir = self.session_dir / "profiles"
        self.session_control_dir = self.session_dir / "control"

    @property
    def profile_name(self) -> str:
        return "scheduler"

    @property
    def target_file(self) -> Path:
        return self.daemon_script

    def get_operations(self) -> dict:
        return {
            "start": "Scheduler-Service starten (GUI Jobs)",
            "stop": "Scheduler-Service stoppen (GUI Jobs)",
            "status": "Status anzeigen",
            "doctor": "Scheduler-Preflight und Recovery-Hinweise anzeigen",
            "pause": "Faellige Scheduler-Jobs pausieren",
            "resume": "Scheduler-Pause aufheben",
            "steer": "Operator-Hinweise fuer kommende Scheduler-Jobs vormerken",
            "clear-steer": "Scheduler-Steering-Hinweise loeschen",
            "jobs": "Aktive Jobs auflisten",
            "run": "Job manuell ausfuehren (bach scheduler run ID)",
            "logs": "Letzte Logs anzeigen",
            "session": "Session-System verwalten (bach scheduler session ...)"
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        json_output = self._has_flag(args, "--json")

        # Session System (System-Service)
        if operation == "session":
            return self._handle_session(args, dry_run)

        # Original GUI Jobs System
        if operation == "start":
            background = "--bg" in args or "--background" in args
            return self._start_daemon(background, dry_run)
        elif operation == "stop":
            return self._stop_daemon(dry_run)
        elif operation == "pause":
            return self._scheduler_pause(args, dry_run)
        elif operation == "resume":
            return self._scheduler_resume(args, dry_run)
        elif operation == "steer":
            return self._scheduler_steer(args, dry_run)
        elif operation == "clear-steer":
            return self._scheduler_clear_steer(args, dry_run)
        elif operation == "status":
            return self._show_status(json_output=json_output)
        elif operation == "doctor":
            return self._doctor_scheduler(json_output=json_output)
        elif operation == "jobs":
            return self._list_jobs(json_output=json_output)
        elif operation == "run":
            if args:
                try:
                    job_id = int(args[0])
                    return self._run_job(job_id, dry_run)
                except ValueError:
                    return (False, f"[ERROR] Ungueltige Job-ID: {args[0]}")
            return (False, "[ERROR] Job-ID erforderlich: bach scheduler run <ID>")
        elif operation == "logs":
            lines = 20
            if args:
                try:
                    lines = int(args[0])
                except (ValueError, TypeError):
                    pass
            return self._show_logs(lines)
        else:
            return self._show_status()

    def _has_flag(self, args: list, *flags: str) -> bool:
        """Prueft ob ein Flag in den CLI-Argumenten gesetzt wurde."""
        return any(arg in flags for arg in args)

    def _json_dump(self, payload: dict) -> str:
        """Formatiert JSON konsistent fuer CLI-Ausgabe."""
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _check_runtime_dir(self, name: str, path: Path, label: str) -> dict:
        """Prueft ob ein Laufzeit-Verzeichnis verfuegbar und beschreibbar ist."""
        details = {"path": str(path)}
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".scheduler_doctor_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {
                "name": name,
                "status": "ok",
                "message": f"{label} ist verfügbar und beschreibbar.",
                "details": details,
            }
        except Exception as exc:
            return {
                "name": name,
                "status": "error",
                "message": f"{label} ist nicht beschreibbar: {exc}",
                "details": details,
            }

    def _check_file_exists(self, name: str, path: Path, label: str, *, required: bool = True) -> dict:
        """Prueft das Vorhandensein einer Datei fuer Doctor-Reports."""
        if path.exists():
            return {
                "name": name,
                "status": "ok",
                "message": f"{label} wurde gefunden.",
                "details": {"path": str(path)},
            }
        return {
            "name": name,
            "status": "error" if required else "warn",
            "message": f"{label} fehlt.",
            "details": {"path": str(path)},
        }

    def _check_pid_state(self, name: str, pid_file: Path, running_pid: int, label: str) -> dict:
        """Prueft laufende/stale PID-Dateien und bereinigt Altlasten."""
        details = {"pid_file": str(pid_file)}

        if running_pid:
            details["pid"] = running_pid
            return {
                "name": name,
                "status": "ok",
                "message": f"{label} läuft (PID {running_pid}).",
                "details": details,
            }

        if not pid_file.exists():
            return {
                "name": name,
                "status": "ok",
                "message": f"Keine laufende {label}-Instanz erkannt.",
                "details": details,
            }

        raw_pid = None
        status = "warn"
        message = "Veraltete PID-Datei wurde entfernt."
        try:
            raw_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            status = "warn"
            message = "Ungültige PID-Datei wurde entfernt."

        pid_file.unlink(missing_ok=True)
        if raw_pid:
            details["previous_pid"] = raw_pid
        return {
            "name": name,
            "status": status,
            "message": message,
            "details": details,
        }

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

    def _format_doctor_text(self, payload: dict, title: str) -> str:
        """Formatiert Doctor-Reports fuer die CLI."""
        status_map = {"ok": "OK", "warn": "WARN", "error": "ERROR"}
        summary = payload["summary"]
        service = payload["service"]

        lines = [
            f"=== {title} DOCTOR ===",
            "",
            f"Ziel:    {service['label']}",
            f"Zeit:    {payload['generated_at'][:19]}",
            f"Status:  {summary['overall_status'].upper()}",
            f"Ready:   {'ja' if summary['ready'] else 'nein'}",
            f"Läuft:   {'ja' if summary['running'] else 'nein'}",
            f"Startbar:{' ja' if summary['can_start'] else ' nein'}",
            "",
            "Checks:",
        ]

        for check in payload["checks"]:
            lines.append(f"  [{status_map.get(check['status'], check['status'].upper())}] {check['message']}")
            details = check.get("details") or {}
            if details.get("path"):
                lines.append(f"      Pfad: {details['path']}")
            elif details.get("pid_file"):
                lines.append(f"      PID-Datei: {details['pid_file']}")

        lines.extend(["", "Nächste Schritte:"])
        for step in payload["next_steps"]:
            lines.append(f"  - {step}")

        return "\n".join(lines)

    def _check_scheduler_db(self) -> dict:
        """Prueft Scheduler-DB, Job-Zaehlungen und letzte Lauf-Ergebnisse."""
        details = {"path": str(self.user_db)}
        if not self.user_db.exists():
            return {
                "name": "database",
                "status": "error",
                "message": "Scheduler-Datenbank wurde nicht gefunden.",
                "details": details,
            }

        try:
            conn = sqlite3.connect(self.user_db)
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) AS count FROM scheduler_jobs").fetchone()["count"]
            active = conn.execute(
                "SELECT COUNT(*) AS count FROM scheduler_jobs WHERE is_active = 1"
            ).fetchone()["count"]
            latest_run = conn.execute(
                """
                SELECT j.name, r.result, r.finished_at, r.triggered_by
                FROM scheduler_runs r
                JOIN scheduler_jobs j ON r.job_id = j.id
                ORDER BY r.id DESC
                LIMIT 1
                """
            ).fetchone()
        except Exception as exc:
            details["error"] = str(exc)
            return {
                "name": "database",
                "status": "error",
                "message": f"Scheduler-Datenbank ist nicht lesbar: {exc}",
                "details": details,
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass

        details["jobs_total"] = total
        details["jobs_active"] = active
        if latest_run:
            details["latest_run"] = {
                "name": latest_run["name"],
                "result": latest_run["result"],
                "finished_at": latest_run["finished_at"],
                "triggered_by": latest_run["triggered_by"],
            }

        if total == 0:
            return {
                "name": "database",
                "status": "warn",
                "message": "Scheduler-Datenbank ist erreichbar, aber es sind keine Jobs definiert.",
                "details": details,
            }

        latest_result = (latest_run["result"] or "").lower() if latest_run else ""
        if latest_result in {"failed", "timeout", "cancelled"}:
            return {
                "name": "database",
                "status": "warn",
                "message": f"Letzter Scheduler-Lauf endete mit {latest_result}.",
                "details": details,
            }

        return {
            "name": "database",
            "status": "ok",
            "message": f"Scheduler-Datenbank ist erreichbar ({active}/{total} Jobs aktiv).",
            "details": details,
        }

    def _scheduler_doctor_payload(self) -> dict:
        """Erstellt einen strukturierten Preflight-Report fuer den GUI-Scheduler."""
        running_pid = self._get_daemon_pid()
        checks = [
            self._check_file_exists("script", self.daemon_script, "Scheduler-Script"),
            self._check_runtime_dir("data_dir", self.data_dir, "Scheduler-Datenverzeichnis"),
            self._check_runtime_dir("log_dir", self.log_dir, "Scheduler-Logverzeichnis"),
            self._check_pid_state("runtime_state", self.pid_file, running_pid, "Scheduler-Service"),
            self._check_scheduler_db(),
        ]

        payload = {
            "generated_at": datetime.now().isoformat(),
            "service": {
                "kind": "scheduler",
                "label": "Scheduler-Service",
                "running": bool(running_pid),
                "pid": running_pid or None,
                "script": str(self.daemon_script),
                "pid_file": str(self.pid_file),
                "log_file": str(self.log_dir / "daemon.log"),
            },
            "checks": checks,
            "next_steps": [],
        }

        summary = self._summarize_checks(checks)
        summary["ready"] = summary["error"] == 0
        summary["running"] = bool(running_pid)
        summary["can_start"] = summary["ready"] and not running_pid
        payload["summary"] = summary

        next_steps = []
        if any(check["name"] == "script" and check["status"] == "error" for check in checks):
            next_steps.append("Den Scheduler-Pfad bzw. die Installation prüfen und fehlende Dateien wiederherstellen.")
        if any(check["name"] == "database" and check["status"] == "error" for check in checks):
            next_steps.append("Die Scheduler-DB oder das Schema reparieren und danach `bach scheduler status --json` erneut prüfen.")
        elif any(
            check["name"] == "database"
            and check["status"] == "warn"
            and "keine Jobs definiert" in check["message"]
            for check in checks
        ):
            next_steps.append("Mit `bach scheduler jobs --json` oder der GUI Jobs anlegen bzw. aktivieren.")
        elif any(
            check["name"] == "database"
            and check["status"] == "warn"
            and "Letzter Scheduler-Lauf endete" in check["message"]
            for check in checks
        ):
            next_steps.append("Mit `bach scheduler logs 50` die letzte Fehlerspur lesen und betroffene Jobs gezielt neu starten.")

        runtime_check = next((check for check in checks if check["name"] == "runtime_state"), None)
        if runtime_check and runtime_check["message"].startswith("Scheduler-Service läuft"):
            next_steps.append("Mit `bach scheduler status --json` den Live-Status prüfen oder den Dienst gezielt stoppen.")
        elif summary["can_start"]:
            next_steps.append("Mit `bach scheduler start --bg` einen sicheren Hintergrundstart testen.")
            next_steps.append("Danach `bach scheduler status --json` zur Verifikation ausführen.")

        if not next_steps:
            next_steps.append("Keine Aktion nötig. Der Scheduler-Preflight ist bereits grün.")

        payload["next_steps"] = next_steps
        return payload

    def _doctor_scheduler(self, json_output: bool = False) -> tuple:
        """Diagnostiziert Scheduler-Voraussetzungen und liefert Recovery-Hinweise."""
        payload = self._scheduler_doctor_payload()
        if json_output:
            return True, self._json_dump(payload)
        return True, self._format_doctor_text(payload, "SCHEDULER")

    def _check_session_config(self, config_file: Path) -> dict:
        """Prueft Session-Config auf Lesbarkeit und Profil-Jobs."""
        details = {"path": str(config_file)}
        if not config_file.exists():
            return {
                "name": "config",
                "status": "warn",
                "message": "Session-Config fehlt; der Session-Scheduler hätte keine explizite Job-Konfiguration.",
                "details": details,
            }

        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception as exc:
            details["error"] = str(exc)
            return {
                "name": "config",
                "status": "error",
                "message": f"Session-Config ist nicht lesbar: {exc}",
                "details": details,
            }

        jobs = config.get("jobs", [])
        details["enabled"] = config.get("enabled", True)
        details["job_count"] = len(jobs)
        details["quiet_start"] = config.get("quiet_start")
        details["quiet_end"] = config.get("quiet_end")

        if not jobs:
            return {
                "name": "config",
                "status": "warn",
                "message": "Session-Config ist lesbar, enthält aber keine Jobs.",
                "details": details,
            }

        return {
            "name": "config",
            "status": "ok",
            "message": f"Session-Config ist lesbar ({len(jobs)} Job(s) konfiguriert).",
            "details": details,
        }

    def _check_session_profiles(self) -> dict:
        """Prueft den Profil-Ordner des Session-Schedulers."""
        details = {"path": str(self.session_profiles_dir)}
        if not self.session_profiles_dir.exists():
            return {
                "name": "profiles",
                "status": "error",
                "message": "Der Session-Profilordner fehlt.",
                "details": details,
            }

        profiles = sorted(path.stem for path in self.session_profiles_dir.glob("*.json"))
        details["profiles"] = profiles
        if not profiles:
            return {
                "name": "profiles",
                "status": "warn",
                "message": "Keine Session-Profile gefunden.",
                "details": details,
            }

        return {
            "name": "profiles",
            "status": "ok",
            "message": f"{len(profiles)} Session-Profil(e) gefunden.",
            "details": details,
        }

    def _session_doctor_payload(self) -> dict:
        """Erstellt einen strukturierten Preflight-Report fuer den Session-Scheduler."""
        running_pid = self._session_is_running()
        config_file = self.session_dir / "config.json"
        auto_session = self.session_dir / "auto_session.py"

        checks = [
            self._check_file_exists("script", self.session_daemon, "Session-Scheduler-Script"),
            self._check_runtime_dir("session_dir", self.session_dir, "Session-Service-Verzeichnis"),
            self._check_pid_state("runtime_state", self.session_pid_file, running_pid, "Session-Scheduler"),
            self._check_session_config(config_file),
            self._check_session_runtime_policy(),
            self._check_session_profiles(),
            self._check_file_exists("trigger_script", auto_session, "Auto-Session-Trigger", required=False),
        ]

        payload = {
            "generated_at": datetime.now().isoformat(),
            "service": {
                "kind": "session_scheduler",
                "label": "Session-Scheduler",
                "running": bool(running_pid),
                "pid": running_pid or None,
                "script": str(self.session_daemon),
                "pid_file": str(self.session_pid_file),
                "config_file": str(config_file),
            },
            "checks": checks,
            "next_steps": [],
        }

        summary = self._summarize_checks(checks)
        policy_check = next((check for check in checks if check["name"] == "policy"), None)
        policy_details = policy_check.get("details") if policy_check else {}
        summary["ready"] = summary["error"] == 0
        summary["running"] = bool(running_pid)
        summary["can_start"] = (
            summary["ready"]
            and not running_pid
            and not bool(policy_details.get("deprecated"))
        )
        payload["summary"] = summary

        next_steps = []
        if any(check["name"] == "script" and check["status"] == "error" for check in checks):
            next_steps.append("Den Pfad `hub/_services/daemon/session_daemon.py` bzw. die Installation reparieren.")
        if any(check["name"] == "config" and check["status"] == "error" for check in checks):
            next_steps.append("`hub/_services/daemon/config.json` reparieren und JSON-Syntax erneut validieren.")
        elif any(
            check["name"] == "config"
            and check["status"] == "warn"
            and "keine Jobs" in check["message"]
            for check in checks
        ):
            next_steps.append("In `hub/_services/daemon/config.json` mindestens einen Session-Job konfigurieren.")
        if policy_check and policy_check["status"] == "warn":
            if policy_details.get("deprecated"):
                next_steps.append(
                    "Die Legacy-Session-Automation nicht mehr regulär starten; stattdessen Buddha Control API (:8081/api/chat), BACH GUI Dashboard (:8000) oder Claude Code /loop bzw. /schedule nutzen."
                )
                next_steps.append(
                    "Legacy-Tests nur bewusst mit `bach scheduler session start --profile ati --force` oder `bach scheduler session trigger --profile ati --force` ausführen."
                )
            elif policy_details.get("config_enabled") is False:
                next_steps.append("Falls die Session-Automation wieder gebraucht wird, `hub/_services/daemon/config.json` gezielt reaktivieren.")
        if any(check["name"] == "profiles" and check["status"] == "error" for check in checks):
            next_steps.append("Den Profilordner `hub/_services/daemon/profiles/` wiederherstellen.")
        elif any(check["name"] == "profiles" and check["status"] == "warn" for check in checks):
            next_steps.append("Mindestens ein Profil unter `hub/_services/daemon/profiles/*.json` anlegen.")
        if any(check["name"] == "trigger_script" and check["status"] == "warn" for check in checks):
            next_steps.append("Falls manuelle Trigger benötigt werden, `hub/_services/daemon/auto_session.py` wiederherstellen.")

        runtime_check = next((check for check in checks if check["name"] == "runtime_state"), None)
        profile_check = next((check for check in checks if check["name"] == "profiles"), None)
        default_profile = "ati"
        if profile_check:
            profiles = (profile_check.get("details") or {}).get("profiles") or []
            if profiles:
                default_profile = profiles[0]

        if runtime_check and runtime_check["message"].startswith("Session-Scheduler läuft"):
            next_steps.append("Mit `bach scheduler session status --json` den Live-Status prüfen oder den Dienst gezielt stoppen.")
        elif summary["can_start"]:
            next_steps.append(f"Mit `bach scheduler session start --profile {default_profile}` einen Starttest ausführen.")
            next_steps.append("Danach `bach scheduler session status --json` zur Verifikation ausführen.")

        if not next_steps:
            next_steps.append("Keine Aktion nötig. Der Session-Preflight ist bereits grün.")

        payload["next_steps"] = next_steps
        return payload

    def _session_doctor(self, json_output: bool = False) -> tuple:
        """Diagnostiziert Session-Scheduler-Voraussetzungen und Recovery-Schritte."""
        payload = self._session_doctor_payload()
        if json_output:
            return True, self._json_dump(payload)
        return True, self._format_doctor_text(payload, "SESSION SCHEDULER")

    def _parse_datetime_value(self, value):
        """Parst ISO-Zeitstempel robust fuer Statusberechnungen."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    def _get_daemon_pid(self) -> int:
        """Prueft ob Scheduler laeuft und liefert PID oder 0."""
        if not self.pid_file.exists():
            return 0

        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace"
                )
                return pid if str(pid) in result.stdout else 0
            os.kill(pid, 0)
            return pid
        except Exception:
            return 0

    def _is_running(self) -> bool:
        """Prueft ob Scheduler laeuft."""
        return bool(self._get_daemon_pid())

    def _start_daemon(self, background: bool, dry_run: bool) -> tuple:
        """Startet den Scheduler-Service."""
        if not self.daemon_script.exists():
            return (False, f"[ERROR] Scheduler-Script nicht gefunden: {self.daemon_script}")

        if self._is_running():
            return (False, "[WARN] Scheduler laeuft bereits!")

        if dry_run:
            mode = "Hintergrund" if background else "Vordergrund"
            return (True, f"[DRY-RUN] Wuerde Scheduler starten im {mode}")

        if background:
            # Im Hintergrund starten
            if sys.platform == 'win32':
                # Windows: START /B verwenden
                subprocess.Popen(
                    ['pythonw', str(self.daemon_script), 'start'],
                    cwd=str(self.base_path),
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Unix: nohup verwenden
                subprocess.Popen(
                    ['python3', str(self.daemon_script), 'start'],
                    cwd=str(self.base_path),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )

            # Windows-/OneDrive-Setups koennen den PID-Moment leicht verzoegern.
            for _ in range(20):
                time.sleep(0.25)
                if self._is_running():
                    return (True, "[OK] Scheduler im Hintergrund gestartet")

            if self._is_running():
                return (True, "[OK] Scheduler im Hintergrund gestartet")
            else:
                return (False, "[ERROR] Scheduler konnte nicht gestartet werden")
        else:
            # Im Vordergrund starten (blockiert)
            output = [
                "[OK] Starte BACH Scheduler Service...",
                f"     PID-File: {self.pid_file}",
                f"     Log: {self.log_dir / 'daemon.log'}",
                "",
                "     Ctrl+C zum Beenden"
            ]
            print("\n".join(output))

            try:
                sys.path.insert(0, str(self.gui_dir))
                from daemon_service import DaemonService
                daemon = DaemonService()
                daemon.run()
                return (True, "\n[OK] Scheduler beendet.")
            except KeyboardInterrupt:
                return (True, "\n[OK] Scheduler durch User beendet.")
            except Exception as e:
                return (False, f"[ERROR] Scheduler-Fehler: {e}")

    def _stop_daemon(self, dry_run: bool) -> tuple:
        """Stoppt den Scheduler-Service."""
        if not self._is_running():
            return (False, "[WARN] Scheduler laeuft nicht")

        if dry_run:
            return (True, "[DRY-RUN] Wuerde Scheduler stoppen")

        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())

            if sys.platform == 'win32':
                # Windows: taskkill verwenden
                subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
            else:
                # Unix: SIGTERM senden
                os.kill(pid, signal.SIGTERM)

            # PID-File entfernen falls noch vorhanden
            import time
            time.sleep(1)
            if self.pid_file.exists():
                self.pid_file.unlink()

            return (True, "[OK] Scheduler gestoppt")

        except Exception as e:
            return (False, f"[ERROR] Stoppen fehlgeschlagen: {e}")

    def _show_status(self, json_output: bool = False) -> tuple:
        """Zeigt Scheduler-Status."""
        import sqlite3

        pid = self._get_daemon_pid()
        running = bool(pid)

        if json_output:
            payload = {
                "generated_at": datetime.now().isoformat(),
                "service": {
                    "running": running,
                    "pid": pid or None,
                    "pid_file": str(self.pid_file),
                    "script": str(self.daemon_script),
                    "log_file": str(self.log_dir / "daemon.log"),
                    "available_actions": ["stop"] if running else ["start"],
                    "control_actions": ["pause", "resume", "steer", "clear-steer"],
                },
                "jobs": {
                    "total": 0,
                    "active": 0,
                },
                "recent_runs": [],
                "operator_control": self._scheduler_control_snapshot(),
            }

            if self.user_db.exists():
                try:
                    conn = sqlite3.connect(self.user_db)
                    conn.row_factory = sqlite3.Row
                    payload["jobs"]["total"] = conn.execute("SELECT COUNT(*) FROM scheduler_jobs").fetchone()[0]
                    payload["jobs"]["active"] = conn.execute(
                        "SELECT COUNT(*) FROM scheduler_jobs WHERE is_active = 1"
                    ).fetchone()[0]
                    runs = conn.execute("""
                        SELECT j.name, r.result, r.finished_at, r.duration_seconds, r.triggered_by
                        FROM scheduler_runs r
                        JOIN scheduler_jobs j ON r.job_id = j.id
                        ORDER BY r.id DESC LIMIT 5
                    """).fetchall()
                    payload["recent_runs"] = [
                        {
                            "name": row["name"],
                            "result": row["result"],
                            "finished_at": row["finished_at"],
                            "duration_seconds": row["duration_seconds"],
                            "triggered_by": row["triggered_by"],
                        }
                        for row in runs
                    ]
                except Exception as e:
                    payload["warning"] = str(e)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            else:
                payload["warning"] = f"User-DB nicht gefunden: {self.user_db}"

            return True, self._json_dump(payload)

        output = [
            "=== SCHEDULER STATUS ===",
            "",
            f"Status:      {'[RUNNING]' if running else '[STOPPED]'}",
            f"PID-File:    {self.pid_file}",
            f"Script:      {self.daemon_script}",
        ]
        controls = self._scheduler_control_snapshot()

        # DB-Infos laden
        if self.user_db.exists():
            try:
                conn = sqlite3.connect(self.user_db)
                conn.row_factory = sqlite3.Row

                total = conn.execute("SELECT COUNT(*) FROM scheduler_jobs").fetchone()[0]
                active = conn.execute("SELECT COUNT(*) FROM scheduler_jobs WHERE is_active = 1").fetchone()[0]

                output.extend([
                    "",
                    "--- Jobs ---",
                    f"Total:       {total}",
                    f"Aktiv:       {active}",
                ])

                # Letzte Laeufe
                runs = conn.execute("""
                    SELECT j.name, r.result, r.finished_at, r.duration_seconds
                    FROM scheduler_runs r
                    JOIN scheduler_jobs j ON r.job_id = j.id
                    ORDER BY r.id DESC LIMIT 3
                """).fetchall()

                if runs:
                    output.extend(["", "--- Letzte Laeufe ---"])
                    for r in runs:
                        status = "[OK]" if r['result'] == 'success' else "[FAIL]"
                        output.append(f"  {status} {r['name']} ({r['duration_seconds']:.1f}s)")
            except Exception as e:
                output.append(f"\n[WARN] DB-Fehler: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            output.append(f"\n[WARN] User-DB nicht gefunden: {self.user_db}")

        output.extend([
            "",
            "--- Operator Control ---",
            f"Pause:       {controls['pause_reason'] if controls['pause_requested'] else '-'}",
            f"Steer-Queue: {controls['pending_steer_count']}",
        ])
        if controls["latest_steer_message"]:
            output.append(f"Letzter Hinweis: {controls['latest_steer_message'][:80]}")

        return (True, "\n".join(output))

    def _compute_job_status(self, row, now: datetime) -> str:
        """Leitet einen maschinenlesbaren Status fuer einen Scheduler-Job ab."""
        if not row["is_active"]:
            return "disabled"

        next_run = self._parse_datetime_value(row["next_run"])
        last_result = (row["last_result"] or "").lower()

        if last_result in {"failed", "timeout", "cancelled"}:
            return "error"
        if next_run and next_run <= now:
            return "due"
        if next_run:
            return "scheduled"
        if last_result == "success":
            return "ok"
        return "idle"

    def _serialize_job_row(self, row, now: datetime) -> dict:
        """Serialisiert einen Scheduler-Job fuer JSON-Ausgaben."""
        next_run = self._parse_datetime_value(row["next_run"])
        due_in_seconds = None
        overdue_seconds = None
        if next_run:
            delta = int((next_run - now).total_seconds())
            if delta >= 0:
                due_in_seconds = delta
            else:
                overdue_seconds = abs(delta)

        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "job_type": row["job_type"],
            "schedule": row["schedule"],
            "command": row["command"],
            "script_path": row["script_path"],
            "arguments": row["arguments"],
            "is_active": bool(row["is_active"]),
            "status": self._compute_job_status(row, now),
            "last_run": row["last_run"],
            "next_run": row["next_run"],
            "last_result": row["last_result"],
            "run_count": row["run_count"],
            "success_count": row["success_count"],
            "fail_count": row["fail_count"],
            "timeout_seconds": row["timeout_seconds"],
            "retry_on_fail": bool(row["retry_on_fail"]),
            "max_retries": row["max_retries"],
            "due_in_seconds": due_in_seconds,
            "overdue_seconds": overdue_seconds,
        }

    def _list_jobs(self, json_output: bool = False) -> tuple:
        """Listet alle Scheduler-Jobs."""
        import sqlite3

        if not self.user_db.exists():
            return (False, f"[ERROR] User-DB nicht gefunden: {self.user_db}")

        try:
            conn = sqlite3.connect(self.user_db)
            conn.row_factory = sqlite3.Row

            jobs = conn.execute("""
                SELECT id, name, description, job_type, schedule, command, script_path,
                       arguments, is_active, last_run, next_run, run_count, success_count,
                       fail_count, last_result, timeout_seconds, retry_on_fail, max_retries
                FROM scheduler_jobs
                ORDER BY is_active DESC, name
            """).fetchall()
        except Exception as e:
            return (False, f"[ERROR] DB-Fehler: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        try:
            if json_output:
                now = datetime.now()
                payload = {
                    "generated_at": now.isoformat(),
                    "jobs": [self._serialize_job_row(job, now) for job in jobs],
                }
                return True, self._json_dump(payload)

            if not jobs:
                return (True, "Keine Scheduler-Jobs definiert.\n\nErstelle Jobs via GUI oder API.")

            output = [
                "=== SCHEDULER JOBS ===",
                "",
                f"{'ID':>4}  {'Status':8}  {'Typ':8}  {'Schedule':12}  Name",
                "-" * 60
            ]

            for j in jobs:
                status = "[ON]" if j['is_active'] else "[OFF]"
                schedule = j['schedule'][:12] if j['schedule'] else '-'
                output.append(f"{j['id']:>4}  {status:8}  {j['job_type']:8}  {schedule:12}  {j['name']}")

            output.extend([
                "",
                "--- Befehle ---",
                "bach scheduler run <ID>    Job manuell starten",
                "bach scheduler status      Status anzeigen"
            ])

            return (True, "\n".join(output))

        except Exception as e:
            return (False, f"[ERROR] DB-Fehler: {e}")

    def _run_job(self, job_id: int, dry_run: bool) -> tuple:
        """Fuehrt Job manuell aus."""
        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Job {job_id} ausfuehren")

        try:
            sys.path.insert(0, str(self.gui_dir))
            from daemon_service import DaemonService

            daemon = DaemonService()
            daemon.load_jobs()

            if job_id not in daemon.jobs:
                return (False, f"[ERROR] Job {job_id} nicht gefunden oder nicht aktiv")

            job = daemon.jobs[job_id]
            print(f"[OK] Starte Job '{job.name}'...")

            result = daemon.run_job(job_id, triggered_by='manual')

            if result['success']:
                output = [
                    f"[OK] Job '{job.name}' erfolgreich",
                    f"     Dauer: {result['duration_seconds']:.1f}s"
                ]
                if result['output']:
                    output.extend(["", "--- Output ---", result['output'][:1000]])
                return (True, "\n".join(output))
            else:
                return (False, f"[ERROR] Job fehlgeschlagen: {result['error']}")

        except Exception as e:
            return (False, f"[ERROR] Ausfuehrung fehlgeschlagen: {e}")

    def _show_logs(self, lines: int = 20) -> tuple:
        """Zeigt letzte Log-Eintraege."""
        log_file = self.log_dir / "daemon.log"

        if not log_file.exists():
            return (False, f"[WARN] Log-Datei nicht gefunden: {log_file}")

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                last_lines = all_lines[-lines:]

            output = [
                f"=== SCHEDULER LOGS (letzte {lines} Zeilen) ===",
                ""
            ]
            output.extend([l.rstrip() for l in last_lines])

            return (True, "\n".join(output))

        except Exception as e:
            return (False, f"[ERROR] Log-Fehler: {e}")

    def _strip_scheduler_control_flags(self, args: list) -> list[str]:
        """Entfernt Steuer-Flags und liefert den eigentlichen Text-/Grund-Teil."""
        return [arg for arg in args if arg not in {"--dry-run", "-n", "--json"}]

    def _scheduler_pause_file(self) -> Path:
        return self.scheduler_control_dir / "scheduler.pause.json"

    def _scheduler_steer_file(self) -> Path:
        return self.scheduler_control_dir / "scheduler.steer.json"

    def _scheduler_read_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _scheduler_get_pause_request(self) -> dict | None:
        payload = self._scheduler_read_json(self._scheduler_pause_file(), None)
        if isinstance(payload, dict) and payload.get("reason"):
            return payload
        return None

    def _scheduler_peek_steer_requests(self) -> list[dict]:
        payload = self._scheduler_read_json(self._scheduler_steer_file(), [])
        if isinstance(payload, list):
            return [
                item
                for item in payload
                if isinstance(item, dict) and item.get("message")
            ]
        return []

    def _scheduler_control_actions(self, snapshot: dict) -> list[str]:
        actions = ["resume"] if snapshot.get("pause_requested") else ["pause"]
        actions.append("steer")
        if snapshot.get("pending_steer_count"):
            actions.append("clear-steer")
        return actions

    def _scheduler_control_snapshot(self) -> dict:
        pause_request = self._scheduler_get_pause_request()
        steer_requests = self._scheduler_peek_steer_requests()
        latest = steer_requests[-1] if steer_requests else None
        snapshot = {
            "scope": "scheduler",
            "pause_requested": bool(pause_request),
            "pause_reason": pause_request.get("reason") if pause_request else None,
            "pause_requested_at": pause_request.get("requested_at") if pause_request else None,
            "pending_steer_count": len(steer_requests),
            "latest_steer_message": latest.get("message") if latest else None,
            "latest_steer_requested_at": latest.get("requested_at") if latest else None,
            "pause_file": str(self._scheduler_pause_file()),
            "steer_file": str(self._scheduler_steer_file()),
        }
        snapshot["available_actions"] = self._scheduler_control_actions(snapshot)
        return snapshot

    def _scheduler_control_response(
        self,
        action: str,
        ok: bool,
        message: str,
        *,
        json_output: bool = False,
        dry_run: bool = False,
    ) -> tuple:
        if not json_output:
            return ok, message

        payload = {
            "generated_at": datetime.now().isoformat(),
            "action": action,
            "ok": ok,
            "message": message,
            "control": self._scheduler_control_snapshot(),
        }
        payload["control"]["dry_run"] = dry_run
        return ok, self._json_dump(payload)

    def _scheduler_pause(self, args: list, dry_run: bool) -> tuple:
        """Pausiert fällige Scheduler-Jobs global."""
        json_output = self._has_flag(args, "--json")
        reason = " ".join(self._strip_scheduler_control_flags(args)).strip() or "Manuell pausiert"
        pause_file = self._scheduler_pause_file()

        if dry_run:
            return self._scheduler_control_response(
                "pause",
                True,
                f"[DRY-RUN] Würde Scheduler pausieren ({reason}) -> {pause_file}",
                json_output=json_output,
                dry_run=True,
            )

        self.scheduler_control_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "reason": reason,
            "requested_at": datetime.now().isoformat(),
        }
        pause_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self._scheduler_control_response(
            "pause",
            True,
            f"[OK] Scheduler pausiert. Grund: {reason}",
            json_output=json_output,
        )

    def _scheduler_resume(self, args: list, dry_run: bool) -> tuple:
        """Hebt eine globale Scheduler-Pause auf."""
        json_output = self._has_flag(args, "--json")
        pause_request = self._scheduler_get_pause_request()
        pause_file = self._scheduler_pause_file()

        if not pause_request:
            return self._scheduler_control_response(
                "resume",
                True,
                "Keine Scheduler-Pause vorgemerkt.",
                json_output=json_output,
            )

        if dry_run:
            return self._scheduler_control_response(
                "resume",
                True,
                f"[DRY-RUN] Würde Scheduler-Pause aufheben -> {pause_file}",
                json_output=json_output,
                dry_run=True,
            )

        pause_file.unlink(missing_ok=True)
        return self._scheduler_control_response(
            "resume",
            True,
            "[OK] Scheduler-Pause aufgehoben.",
            json_output=json_output,
        )

    def _scheduler_steer(self, args: list, dry_run: bool) -> tuple:
        """Hinterlegt Operator-Hinweise für kommende Scheduler-Jobs."""
        json_output = self._has_flag(args, "--json")
        message = " ".join(self._strip_scheduler_control_flags(args)).strip()
        if not message:
            return self._scheduler_control_response(
                "steer",
                False,
                '[ERROR] Hinweis erforderlich: bach scheduler steer "Hinweis"',
                json_output=json_output,
            )

        steer_file = self._scheduler_steer_file()
        current = self._scheduler_peek_steer_requests()
        payload = current + [
            {
                "message": message,
                "requested_at": datetime.now().isoformat(),
            }
        ]

        if dry_run:
            return self._scheduler_control_response(
                "steer",
                True,
                f"[DRY-RUN] Würde Scheduler-Steering vormerken ({len(payload)} Nachricht(en)) -> {steer_file}",
                json_output=json_output,
                dry_run=True,
            )

        self.scheduler_control_dir.mkdir(parents=True, exist_ok=True)
        steer_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self._scheduler_control_response(
            "steer",
            True,
            f"[OK] Scheduler-Steering vorgemerkt ({len(payload)} Nachricht(en) in Queue).",
            json_output=json_output,
        )

    def _scheduler_clear_steer(self, args: list, dry_run: bool) -> tuple:
        """Leert die globale Scheduler-Steering-Queue."""
        json_output = self._has_flag(args, "--json")
        pending = self._scheduler_peek_steer_requests()
        steer_file = self._scheduler_steer_file()

        if not pending:
            return self._scheduler_control_response(
                "clear-steer",
                True,
                "Keine Scheduler-Steering-Hinweise vorgemerkt.",
                json_output=json_output,
            )

        if dry_run:
            return self._scheduler_control_response(
                "clear-steer",
                True,
                f"[DRY-RUN] Würde {len(pending)} Scheduler-Steering-Hinweis(e) löschen -> {steer_file}",
                json_output=json_output,
                dry_run=True,
            )

        steer_file.unlink(missing_ok=True)
        return self._scheduler_control_response(
            "clear-steer",
            True,
            f"[OK] {len(pending)} Scheduler-Steering-Hinweis(e) gelöscht.",
            json_output=json_output,
        )

    # =====================================================
    # SESSION SYSTEM (System-Service)
    # =====================================================

    def _handle_session(self, args: list, dry_run: bool) -> tuple:
        """Verwaltet das Session-System (System-Service)."""
        if not args:
            return self._session_status()

        if args[0] == "--json":
            return self._session_status(json_output=True)

        sub_cmd = args[0].lower()
        sub_args = args[1:] if len(args) > 1 else []

        if sub_cmd == "start":
            return self._session_start(sub_args, dry_run)
        elif sub_cmd == "stop":
            return self._session_stop(dry_run)
        elif sub_cmd == "status":
            return self._session_status(json_output=self._has_flag(sub_args, "--json"))
        elif sub_cmd == "doctor":
            return self._session_doctor(json_output=self._has_flag(sub_args, "--json"))
        elif sub_cmd == "pause":
            return self._session_pause(sub_args, dry_run)
        elif sub_cmd == "resume":
            return self._session_resume(sub_args, dry_run)
        elif sub_cmd == "steer":
            return self._session_steer(sub_args, dry_run)
        elif sub_cmd == "clear-steer":
            return self._session_clear_steer(sub_args, dry_run)
        elif sub_cmd == "trigger":
            return self._session_trigger(sub_args, dry_run)
        elif sub_cmd == "profiles":
            return self._session_profiles_v2()
        else:
            return self._session_help_v2()

    def _session_help(self) -> tuple:
        """Zeigt Session-Hilfe."""
        output = [
            "=== SESSION SYSTEM (System-Service) ===",
            "",
            "Befehle:",
            "  bach scheduler session start [--profile NAME]   Scheduler starten",
            "  bach scheduler session stop                      Scheduler stoppen",
            "  bach scheduler session status                    Status anzeigen",
            "  bach scheduler session doctor                    Preflight und Recovery-Hinweise",
            "  bach scheduler session pause [--profile NAME] [Grund]   Trigger fuer Profil pausieren",
            "  bach scheduler session resume [--profile NAME]          Pause fuer Profil aufheben",
            "  bach scheduler session steer [--profile NAME] \"Hinweis\"  Hinweis fuer naechste Session vormerken",
            "  bach scheduler session clear-steer [--profile NAME]     Hinweis-Queue für Profil leeren",
            "  bach scheduler session trigger [--profile NAME]  Session manuell",
            "  bach scheduler session profiles                  Profile auflisten",
            "",
            "Optionen:",
            "  --profile NAME    Profil waehlen (default: ati)",
            "  --dry-run         Nur simulieren"
        ]
        return (True, "\n".join(output))

    def _session_help_v2(self) -> tuple:
        """Zeigt die Session-Hilfe mit Policy-Hinweisen."""
        policy = self._session_runtime_policy()
        output = [
            "=== SESSION SYSTEM (System-Service) ===",
            "",
            "Befehle:",
            "  bach scheduler session start [--profile NAME]   Scheduler starten (Legacy)",
            "  bach scheduler session stop                      Scheduler stoppen",
            "  bach scheduler session status                    Status anzeigen",
            "  bach scheduler session doctor                    Preflight und Recovery-Hinweise",
            "  bach scheduler session pause [--profile NAME] [Grund]   Trigger fuer Profil pausieren",
            "  bach scheduler session resume [--profile NAME]          Pause fuer Profil aufheben",
            "  bach scheduler session steer [--profile NAME] \"Hinweis\"  Hinweis fuer naechste Session vormerken",
            "  bach scheduler session clear-steer [--profile NAME]     Hinweis-Queue für Profil leeren",
            "  bach scheduler session trigger [--profile NAME]  Session manuell (Legacy)",
            "  bach scheduler session profiles                  Profile auflisten",
            "",
            "Optionen:",
            "  --profile NAME    Profil waehlen (default: ati)",
            "  --dry-run         Nur simulieren",
            "  --force           Deprecated Legacy-Pfade bewusst trotzdem nutzen",
        ]
        if policy["deprecated"]:
            output.extend([
                "",
                "Hinweis:",
                f"  {policy['message']}",
                "  Empfohlene Alternativen:",
            ])
            for replacement in policy["recommended_replacements"]:
                output.append(f"  - {replacement}")
        return (True, "\n".join(output))

    def _session_profiles_v2(self) -> tuple:
        """Listet verfügbare Profile ohne doppelte Verwendungsblöcke."""
        if not self.session_profiles_dir.exists():
            return (False, f"[ERROR] Profilordner nicht gefunden: {self.session_profiles_dir}")

        profiles = list(self.session_profiles_dir.glob("*.json"))
        if not profiles:
            return (True, "Keine Profile definiert.\n\nErstelle Profile in: " + str(self.session_profiles_dir))

        policy = self._session_runtime_policy()
        output = [
            "=== SESSION PROFILE ===",
            ""
        ]

        for pf in profiles:
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                name = pf.stem
                desc = data.get("description", "-")
                source = data.get("task_source", "ati_tasks")
                max_tasks = data.get("max_tasks", 3)
                timeout = data.get("timeout_minutes", 15)

                output.extend([
                    f"[{name}]",
                    f"  Beschreibung: {desc[:50]}",
                    f"  Task-Quelle:  {source}",
                    f"  Max Tasks:    {max_tasks}",
                    f"  Timeout:      {timeout} Min",
                    ""
                ])
            except Exception:
                output.append(f"[{pf.stem}] (Fehler beim Laden)")

        output.extend([
            "--- Verwendung ---",
            "bach scheduler session start --profile NAME",
            "bach scheduler session trigger --profile NAME",
            "bach scheduler session steer --profile NAME \"Hinweis\"",
            "bach scheduler session clear-steer --profile NAME"
        ])

        if policy["deprecated"]:
            output.extend([
                "",
                "--- Legacy-Hinweis ---",
                policy["message"],
                f"Legacy-Start/Trigger nur bewusst mit {policy['legacy_override_flag']}.",
            ])
            for replacement in policy["recommended_replacements"]:
                output.append(f"- {replacement}")

        return (True, "\n".join(output))

    def _get_profile_from_args(self, args: list, default: str = "ati") -> str:
        """Extrahiert Profilname aus Argumenten."""
        for i, arg in enumerate(args):
            if arg == "--profile" and i + 1 < len(args):
                return args[i + 1]
        return default

    def _strip_profile_and_flags(self, args: list) -> list[str]:
        """Entfernt Profil-/Dry-Run-Flags und liefert die Restargumente."""
        cleaned = []
        skip_next = False
        for index, arg in enumerate(args):
            if skip_next:
                skip_next = False
                continue
            if arg == "--profile" and index + 1 < len(args):
                skip_next = True
                continue
            if arg in {"--dry-run", "-n", "--json"}:
                continue
            cleaned.append(arg)
        return cleaned

    def _session_profile_slug(self, profile: str) -> str:
        """Normalisiert Profilnamen fuer Session-Control-Dateien."""
        cleaned = []
        for char in (profile or "ati"):
            if char.isalnum() or char in {"-", "_"}:
                cleaned.append(char)
            else:
                cleaned.append("_")
        return "".join(cleaned) or "ati"

    def _session_pause_file(self, profile: str) -> Path:
        return self.session_control_dir / f"{self._session_profile_slug(profile)}.pause.json"

    def _session_steer_file(self, profile: str) -> Path:
        return self.session_control_dir / f"{self._session_profile_slug(profile)}.steer.json"

    def _session_read_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _session_get_pause_request(self, profile: str) -> dict | None:
        payload = self._session_read_json(self._session_pause_file(profile), None)
        if isinstance(payload, dict) and payload.get("reason"):
            return payload
        return None

    def _session_peek_steer_requests(self, profile: str) -> list[dict]:
        payload = self._session_read_json(self._session_steer_file(profile), [])
        if isinstance(payload, list):
            return [
                item
                for item in payload
                if isinstance(item, dict) and item.get("message")
            ]
        return []

    def _session_control_snapshot(self, profile: str) -> dict:
        pause_request = self._session_get_pause_request(profile)
        steer_requests = self._session_peek_steer_requests(profile)
        latest = steer_requests[-1] if steer_requests else None
        snapshot = {
            "profile": profile,
            "pause_requested": bool(pause_request),
            "pause_reason": pause_request.get("reason") if pause_request else None,
            "pause_requested_at": pause_request.get("requested_at") if pause_request else None,
            "pending_steer_count": len(steer_requests),
            "latest_steer_message": latest.get("message") if latest else None,
            "latest_steer_requested_at": latest.get("requested_at") if latest else None,
            "pause_file": str(self._session_pause_file(profile)),
            "steer_file": str(self._session_steer_file(profile)),
        }
        snapshot["available_actions"] = self._session_control_actions(snapshot)
        return snapshot

    def _session_control_actions(self, snapshot: dict) -> list[str]:
        """Leitet verfügbare Steueraktionen aus dem aktuellen Session-Snapshot ab."""
        actions = ["resume"] if snapshot.get("pause_requested") else ["pause"]
        actions.append("steer")
        if snapshot.get("pending_steer_count"):
            actions.append("clear-steer")
        return actions

    def _session_control_response(
        self,
        action: str,
        profile: str,
        ok: bool,
        message: str,
        *,
        json_output: bool = False,
        dry_run: bool = False,
    ) -> tuple:
        """Formatiert Session-Control-Antworten optional als JSON."""
        if not json_output:
            return ok, message

        payload = {
            "generated_at": datetime.now().isoformat(),
            "action": action,
            "ok": ok,
            "message": message,
            "control": self._session_control_snapshot(profile),
        }
        payload["control"]["dry_run"] = dry_run
        return ok, self._json_dump(payload)

    def _session_read_config(self) -> dict:
        """Liest die Session-Config robust für Policy-/Status-Entscheidungen."""
        config_file = self.session_dir / "config.json"
        payload = self._session_read_json(config_file, {})
        return payload if isinstance(payload, dict) else {}

    def _has_deprecation_marker(self, path: Path) -> bool:
        """Prüft, ob eine Datei als deprecated markiert ist."""
        if not path.exists():
            return False
        try:
            preview = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            return False
        return "DEPRECATED" in preview.upper()

    def _session_runtime_policy(self) -> dict:
        """Ermittelt, ob die Legacy-Session-Automation regulär nutzbar ist."""
        config = self._session_read_config()
        replacements = [
            "Buddha Control API (:8081/api/chat)",
            "BACH GUI Dashboard (:8000)",
            "Claude Code /loop oder /schedule",
        ]
        daemon_deprecated = self._has_deprecation_marker(self.session_daemon)
        trigger_script = self.session_dir / "auto_session.py"
        trigger_deprecated = self._has_deprecation_marker(trigger_script)
        deprecated = daemon_deprecated or trigger_deprecated
        config_enabled = bool(config.get("enabled", True))

        if deprecated:
            message = (
                "Die pyautogui-basierte Legacy-Session-Automation ist deprecated "
                "und sollte nicht mehr regulär gestartet werden."
            )
            if not config_enabled:
                message += " `config.json` hält sie zusätzlich bewusst deaktiviert."
        elif not config_enabled:
            message = "Die Session-Automation ist in `config.json` derzeit deaktiviert."
        else:
            message = "Die Session-Automation ist nicht als deprecated markiert."

        return {
            "deprecated": deprecated,
            "daemon_deprecated": daemon_deprecated,
            "trigger_deprecated": trigger_deprecated,
            "config_enabled": config_enabled,
            "message": message,
            "recommended_replacements": replacements,
            "legacy_override_flag": "--force",
        }

    def _check_session_runtime_policy(self) -> dict:
        """Bewertet die Legacy-/Deaktivierungs-Policy des Session-Systems."""
        policy = self._session_runtime_policy()
        details = {
            "script": str(self.session_daemon),
            "trigger_script": str(self.session_dir / "auto_session.py"),
            "config_file": str(self.session_dir / "config.json"),
            "deprecated": policy["deprecated"],
            "daemon_deprecated": policy["daemon_deprecated"],
            "trigger_deprecated": policy["trigger_deprecated"],
            "config_enabled": policy["config_enabled"],
            "recommended_replacements": policy["recommended_replacements"],
            "legacy_override_flag": policy["legacy_override_flag"],
        }

        if policy["deprecated"] or not policy["config_enabled"]:
            return {
                "name": "policy",
                "status": "warn",
                "message": policy["message"],
                "details": details,
            }

        return {
            "name": "policy",
            "status": "ok",
            "message": policy["message"],
            "details": details,
        }

    def _session_is_running(self) -> int:
        """Prueft ob Session-Scheduler laeuft. Gibt PID oder 0 zurueck."""
        if not self.session_pid_file.exists():
            return 0
        try:
            pid = int(self.session_pid_file.read_text(encoding="utf-8").strip())
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace"
                )
                if str(pid) in result.stdout:
                    return pid
                return 0
            else:
                os.kill(pid, 0)
                return pid
        except (OSError, subprocess.SubprocessError):
            return 0

    def _session_start(self, args: list, dry_run: bool) -> tuple:
        """Startet Session-Scheduler."""
        if not self.session_daemon.exists():
            return (False, f"[ERROR] Session-Scheduler nicht gefunden: {self.session_daemon}")

        pid = self._session_is_running()
        if pid:
            return (False, f"[WARN] Session-Scheduler laeuft bereits (PID {pid})")

        profile = self._get_profile_from_args(args)
        policy = self._session_runtime_policy()
        force = "--force" in args

        if policy["deprecated"] and not force:
            replacements = "; ".join(policy["recommended_replacements"])
            return (
                False,
                f"[WARN] {policy['message']} Nutze stattdessen: {replacements}. "
                f"Nur fuer bewusste Legacy-Tests mit {policy['legacy_override_flag']} fortfahren.",
            )

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Session-Scheduler mit Profil '{profile}' starten")

        try:
            # Im Hintergrund starten
            cmd = [sys.executable, str(self.session_daemon), "--profile", profile]

            if sys.platform == 'win32':
                subprocess.Popen(
                    cmd,
                    cwd=str(self.session_dir),
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                )
            else:
                subprocess.Popen(
                    cmd,
                    cwd=str(self.session_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )

            import time
            time.sleep(1)

            pid = self._session_is_running()
            if pid:
                return (True, f"[OK] Session-Scheduler gestartet (PID {pid}, Profil: {profile})")
            else:
                return (False, "[ERROR] Session-Scheduler konnte nicht gestartet werden")

        except Exception as e:
            return (False, f"[ERROR] Start fehlgeschlagen: {e}")

    def _session_stop(self, dry_run: bool) -> tuple:
        """Stoppt Session-Scheduler."""
        pid = self._session_is_running()
        if not pid:
            return (False, "[WARN] Session-Scheduler laeuft nicht")

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde Session-Scheduler (PID {pid}) stoppen")

        try:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)

            import time
            time.sleep(1)

            if self.session_pid_file.exists():
                self.session_pid_file.unlink()

            return (True, f"[OK] Session-Scheduler (PID {pid}) gestoppt")

        except Exception as e:
            return (False, f"[ERROR] Stop fehlgeschlagen: {e}")

    def _session_pause(self, args: list, dry_run: bool) -> tuple:
        """Pausiert die Trigger eines Session-Profils."""
        json_output = self._has_flag(args, "--json")
        profile = self._get_profile_from_args(args)
        reason_tokens = self._strip_profile_and_flags(args)
        reason = " ".join(reason_tokens).strip() or "Manuell pausiert"
        pause_file = self._session_pause_file(profile)

        if dry_run:
            return self._session_control_response(
                "pause",
                profile,
                True,
                f"[DRY-RUN] Wuerde Session-Profil '{profile}' pausieren ({reason}) -> {pause_file}",
                json_output=json_output,
                dry_run=True,
            )

        self.session_control_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "profile": profile,
            "reason": reason,
            "requested_at": datetime.now().isoformat(),
        }
        pause_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self._session_control_response(
            "pause",
            profile,
            True,
            f"[OK] Session-Profil '{profile}' pausiert. Grund: {reason}",
            json_output=json_output,
        )

    def _session_resume(self, args: list, dry_run: bool) -> tuple:
        """Hebt eine Session-Pause fuer ein Profil auf."""
        json_output = self._has_flag(args, "--json")
        profile = self._get_profile_from_args(args)
        pause_file = self._session_pause_file(profile)
        pause_request = self._session_get_pause_request(profile)

        if not pause_request:
            return self._session_control_response(
                "resume",
                profile,
                True,
                f"Keine Pause für Session-Profil '{profile}' vorgemerkt.",
                json_output=json_output,
            )

        if dry_run:
            return self._session_control_response(
                "resume",
                profile,
                True,
                f"[DRY-RUN] Wuerde Session-Pause fuer '{profile}' aufheben -> {pause_file}",
                json_output=json_output,
                dry_run=True,
            )

        pause_file.unlink(missing_ok=True)
        return self._session_control_response(
            "resume",
            profile,
            True,
            f"[OK] Session-Pause fuer '{profile}' aufgehoben.",
            json_output=json_output,
        )

    def _session_steer(self, args: list, dry_run: bool) -> tuple:
        """Hinterlegt Operator-Hinweise fuer die naechste Session eines Profils."""
        json_output = self._has_flag(args, "--json")
        profile = self._get_profile_from_args(args)
        message = " ".join(self._strip_profile_and_flags(args)).strip()
        if not message:
            return self._session_control_response(
                "steer",
                profile,
                False,
                '[ERROR] Hinweis erforderlich: bach scheduler session steer [--profile NAME] "Hinweis"',
                json_output=json_output,
            )

        steer_file = self._session_steer_file(profile)
        current = self._session_peek_steer_requests(profile)
        payload = current + [
            {
                "profile": profile,
                "message": message,
                "requested_at": datetime.now().isoformat(),
            }
        ]

        if dry_run:
            return self._session_control_response(
                "steer",
                profile,
                True,
                f"[DRY-RUN] Wuerde Session-Steering fuer '{profile}' vormerken ({len(payload)} Nachricht(en)) -> {steer_file}",
                json_output=json_output,
                dry_run=True,
            )

        self.session_control_dir.mkdir(parents=True, exist_ok=True)
        steer_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self._session_control_response(
            "steer",
            profile,
            True,
            f"[OK] Session-Steering für '{profile}' vorgemerkt ({len(payload)} Nachricht(en) in Queue).",
            json_output=json_output,
        )

    def _session_clear_steer(self, args: list, dry_run: bool) -> tuple:
        """Leert die vorgemerkte Steering-Queue eines Profils."""
        json_output = self._has_flag(args, "--json")
        profile = self._get_profile_from_args(args)
        steer_file = self._session_steer_file(profile)
        pending = self._session_peek_steer_requests(profile)

        if not pending:
            return self._session_control_response(
                "clear-steer",
                profile,
                True,
                f"Keine Session-Steering-Hinweise für '{profile}' vorgemerkt.",
                json_output=json_output,
            )

        if dry_run:
            return self._session_control_response(
                "clear-steer",
                profile,
                True,
                f"[DRY-RUN] Würde {len(pending)} Session-Steering-Hinweis(e) für '{profile}' löschen -> {steer_file}",
                json_output=json_output,
                dry_run=True,
            )

        steer_file.unlink(missing_ok=True)
        return self._session_control_response(
            "clear-steer",
            profile,
            True,
            f"[OK] {len(pending)} Session-Steering-Hinweis(e) für '{profile}' gelöscht.",
            json_output=json_output,
        )

    def _session_status(self, json_output: bool = False) -> tuple:
        """Zeigt Session-Status."""
        import json

        pid = self._session_is_running()
        profile_names = set()
        config_jobs = []
        policy = self._session_runtime_policy()

        if json_output:
            available_actions = ["stop", "trigger"] if pid else ["start", "trigger"]
            if policy["deprecated"] and not pid:
                available_actions = []
            payload = {
                "generated_at": datetime.now().isoformat(),
                "service": {
                    "running": bool(pid),
                    "pid": pid or None,
                    "script": str(self.session_daemon),
                    "pid_file": str(self.session_pid_file),
                    "available_actions": available_actions,
                    "control_actions": ["pause", "resume", "steer", "clear-steer"],
                    "deprecated": policy["deprecated"],
                    "config_enabled": policy["config_enabled"],
                    "deprecation_message": policy["message"] if policy["deprecated"] else None,
                    "recommended_replacements": policy["recommended_replacements"] if policy["deprecated"] else [],
                    "legacy_override_flag": policy["legacy_override_flag"],
                },
                "config": {},
                "profiles": [],
                "operator_controls": [],
                "log_tail": [],
            }

            config_file = self.session_dir / "config.json"
            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text(encoding='utf-8'))
                    config_jobs = config.get("jobs", [])
                    profile_names.update(
                        job.get("profile", "ati") for job in config_jobs if job.get("profile")
                    )
                    payload["config"] = {
                        "enabled": config.get("enabled", True),
                        "quiet_start": config.get("quiet_start", "22:00"),
                        "quiet_end": config.get("quiet_end", "08:00"),
                        "jobs": config_jobs,
                    }
                except Exception as e:
                    payload["config_error"] = str(e)

            if self.session_profiles_dir.exists():
                payload["profiles"] = sorted(p.stem for p in self.session_profiles_dir.glob("*.json"))
                profile_names.update(payload["profiles"])

            payload["operator_controls"] = [
                self._session_control_snapshot(profile)
                for profile in sorted(profile_names)
            ]

            log_file = self.log_dir / "session_daemon.log"
            if log_file.exists():
                try:
                    payload["log_tail"] = log_file.read_text(encoding='utf-8').strip().split("\n")[-5:]
                except Exception as e:
                    payload["log_error"] = str(e)

            return True, self._json_dump(payload)

        output = [
            "=== SESSION SCHEDULER STATUS ===",
            "",
            f"Status:      {'[RUNNING]' if pid else '[STOPPED]'}",
        ]

        if pid:
            output.append(f"PID:         {pid}")

        output.extend([
            f"Script:      {self.session_daemon}",
            f"PID-File:    {self.session_pid_file}",
        ])

        if policy["deprecated"]:
            output.extend([
                "",
                "--- Policy ---",
                f"Status:       [DEPRECATED]",
                f"Hinweis:      {policy['message']}",
                "Alternativen:",
            ])
            for replacement in policy["recommended_replacements"]:
                output.append(f"  - {replacement}")
            output.append(f"Legacy-Override: {policy['legacy_override_flag']}")

        # Config laden
        config_file = self.session_dir / "config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding='utf-8'))
                config_jobs = config.get("jobs", [])
                profile_names.update(
                    job.get("profile", "ati") for job in config_jobs if job.get("profile")
                )
                output.extend([
                    "",
                    "--- Config ---",
                    f"Global Enabled: {config.get('enabled', True)}",
                    f"Ruhezeit:       {config.get('quiet_start', '22:00')} - {config.get('quiet_end', '08:00')}",
                    "",
                    "--- AI Jobs ---"
                ])
                for job in config_jobs:
                    status = "[ON]" if job.get("enabled", True) else "[OFF]"
                    last = job.get("last_run", "nie")
                    if last and last != "nie":
                        last = last[11:16] # Nur Zeit
                    profile = job.get("profile", "?")
                    controls = self._session_control_snapshot(profile)
                    markers = []
                    if controls["pause_requested"]:
                        markers.append(f"PAUSE: {controls['pause_reason']}")
                    if controls["pending_steer_count"]:
                        markers.append(f"STEER: {controls['pending_steer_count']}")
                    suffix = f" | {'; '.join(markers)}" if markers else ""
                    output.append(
                        f"  {status} {profile:12} (Alle {job.get('interval_minutes', '?')} Min, Last: {last}){suffix}"
                    )
            except Exception:
                pass

        # Profile auflisten
        output.extend(["", "--- Profile ---"])
        if self.session_profiles_dir.exists():
            profiles = list(self.session_profiles_dir.glob("*.json"))
            if profiles:
                for p in profiles:
                    profile_names.add(p.stem)
                    output.append(f"  - {p.stem}")
            else:
                output.append("  (keine Profile definiert)")
        else:
            output.append("  (Profilordner nicht gefunden)")

        control_profiles = sorted(profile_names)
        if control_profiles:
            output.extend(["", "--- Operator Controls ---"])
            for profile in control_profiles:
                controls = self._session_control_snapshot(profile)
                pause_text = controls["pause_reason"] if controls["pause_requested"] else "-"
                steer_text = str(controls["pending_steer_count"])
                line = f"  {profile:12} Pause: {pause_text} | Steer-Queue: {steer_text}"
                if controls["latest_steer_message"]:
                    line += f" | Letzter Hinweis: {controls['latest_steer_message'][:60]}"
                output.append(line)

        # Log-Preview
        log_file = self.log_dir / "session_daemon.log"
        if log_file.exists():
            try:
                lines = log_file.read_text(encoding='utf-8').strip().split("\n")
                output.extend(["", "--- Letzte Logs ---"])
                for line in lines[-5:]:
                    output.append(f"  {line[:80]}")
            except (OSError, UnicodeDecodeError):
                pass

        return (True, "\n".join(output))

    def _session_trigger(self, args: list, dry_run: bool) -> tuple:
        """Triggert Session manuell."""
        auto_session = self.session_dir / "auto_session.py"
        if not auto_session.exists():
            return (False, f"[ERROR] auto_session.py nicht gefunden: {auto_session}")

        profile = self._get_profile_from_args(args)
        policy = self._session_runtime_policy()
        force = "--force" in args

        if policy["deprecated"] and not force:
            replacements = "; ".join(policy["recommended_replacements"])
            return (
                False,
                f"[WARN] {policy['message']} Nutze stattdessen: {replacements}. "
                f"Nur fuer bewusste Legacy-Tests mit {policy['legacy_override_flag']} fortfahren.",
            )

        cmd = [sys.executable, str(auto_session), "--profile", profile]
        if dry_run or "--dry-run" in args:
            cmd.append("--dry-run")
        env = dict(os.environ)
        steer_requests = self._session_peek_steer_requests(profile)
        if steer_requests:
            env["BACH_SESSION_OPERATOR_STEER"] = json.dumps(
                steer_requests,
                ensure_ascii=False,
            )

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.session_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                env=env,
            )

            if result.returncode == 0 and steer_requests and not (dry_run or "--dry-run" in args):
                self._session_steer_file(profile).unlink(missing_ok=True)

            output = [f"[OK] Session getriggert (Profil: {profile})", ""]
            if steer_requests:
                output.append(f"[INFO] Operator-Steering mitgegeben: {len(steer_requests)} Hinweis(e)")
                output.append("")
            if result.stdout:
                output.extend(result.stdout.strip().split("\n")[-15:])
            if result.stderr:
                output.extend(["", "--- Errors ---", result.stderr[:500]])

            if result.returncode != 0:
                output[0] = f"[ERROR] Session-Trigger fehlgeschlagen (Profil: {profile}, rc={result.returncode})"
                return (False, "\n".join(output))

            return (True, "\n".join(output))

        except subprocess.TimeoutExpired:
            return (False, "[ERROR] Timeout (>60s)")
        except Exception as e:
            return (False, f"[ERROR] Trigger fehlgeschlagen: {e}")

    def _session_profiles(self) -> tuple:
        """Listet verfuegbare Profile."""
        return self._session_profiles_v2()


# Rueckwaertskompatibilitaet: DaemonHandler ist ein Alias fuer SchedulerHandler
DaemonHandler = SchedulerHandler
