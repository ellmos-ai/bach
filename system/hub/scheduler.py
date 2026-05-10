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
        self.user_db = self.data_dir / "bach.db"  # Unified DB seit v1.1.84

        # Session System (System-Service)
        self.session_dir = base_path / "skills" / "_services" / "daemon"
        self.session_daemon = self.session_dir / "session_daemon.py"
        self.session_pid_file = self.session_dir / "daemon.pid"
        self.session_profiles_dir = self.session_dir / "profiles"

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
        elif operation == "status":
            return self._show_status(json_output=json_output)
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
                except:
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
            pid = int(self.pid_file.read_text().strip())
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True, text=True
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

            import time
            time.sleep(1)  # Kurz warten

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
            pid = int(self.pid_file.read_text().strip())

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
                },
                "jobs": {
                    "total": 0,
                    "active": 0,
                },
                "recent_runs": [],
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
                    conn.close()
                except Exception as e:
                    payload["warning"] = str(e)
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

                conn.close()
            except Exception as e:
                output.append(f"\n[WARN] DB-Fehler: {e}")
        else:
            output.append(f"\n[WARN] User-DB nicht gefunden: {self.user_db}")

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

            conn.close()

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
        elif sub_cmd == "trigger":
            return self._session_trigger(sub_args, dry_run)
        elif sub_cmd == "profiles":
            return self._session_profiles()
        else:
            return self._session_help()

    def _session_help(self) -> tuple:
        """Zeigt Session-Hilfe."""
        output = [
            "=== SESSION SYSTEM (System-Service) ===",
            "",
            "Befehle:",
            "  bach scheduler session start [--profile NAME]   Scheduler starten",
            "  bach scheduler session stop                      Scheduler stoppen",
            "  bach scheduler session status                    Status anzeigen",
            "  bach scheduler session trigger [--profile NAME]  Session manuell",
            "  bach scheduler session profiles                  Profile auflisten",
            "",
            "Optionen:",
            "  --profile NAME    Profil waehlen (default: ati)",
            "  --dry-run         Nur simulieren"
        ]
        return (True, "\n".join(output))

    def _get_profile_from_args(self, args: list, default: str = "ati") -> str:
        """Extrahiert Profilname aus Argumenten."""
        for i, arg in enumerate(args):
            if arg == "--profile" and i + 1 < len(args):
                return args[i + 1]
        return default

    def _session_is_running(self) -> int:
        """Prueft ob Session-Scheduler laeuft. Gibt PID oder 0 zurueck."""
        if not self.session_pid_file.exists():
            return 0
        try:
            pid = int(self.session_pid_file.read_text().strip())
            if sys.platform == 'win32':
                result = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}'],
                    capture_output=True, text=True
                )
                if str(pid) in result.stdout:
                    return pid
                return 0
            else:
                os.kill(pid, 0)
                return pid
        except:
            return 0

    def _session_start(self, args: list, dry_run: bool) -> tuple:
        """Startet Session-Scheduler."""
        if not self.session_daemon.exists():
            return (False, f"[ERROR] Session-Scheduler nicht gefunden: {self.session_daemon}")

        pid = self._session_is_running()
        if pid:
            return (False, f"[WARN] Session-Scheduler laeuft bereits (PID {pid})")

        profile = self._get_profile_from_args(args)

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

    def _session_status(self, json_output: bool = False) -> tuple:
        """Zeigt Session-Status."""
        import json

        pid = self._session_is_running()

        if json_output:
            payload = {
                "generated_at": datetime.now().isoformat(),
                "service": {
                    "running": bool(pid),
                    "pid": pid or None,
                    "script": str(self.session_daemon),
                    "pid_file": str(self.session_pid_file),
                },
                "config": {},
                "profiles": [],
                "log_tail": [],
            }

            config_file = self.session_dir / "config.json"
            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text(encoding='utf-8'))
                    payload["config"] = {
                        "enabled": config.get("enabled", True),
                        "quiet_start": config.get("quiet_start", "22:00"),
                        "quiet_end": config.get("quiet_end", "08:00"),
                        "jobs": config.get("jobs", []),
                    }
                except Exception as e:
                    payload["config_error"] = str(e)

            if self.session_profiles_dir.exists():
                payload["profiles"] = sorted(p.stem for p in self.session_profiles_dir.glob("*.json"))

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

        # Config laden
        config_file = self.session_dir / "config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding='utf-8'))
                output.extend([
                    "",
                    "--- Config ---",
                    f"Global Enabled: {config.get('enabled', True)}",
                    f"Ruhezeit:       {config.get('quiet_start', '22:00')} - {config.get('quiet_end', '08:00')}",
                    "",
                    "--- AI Jobs ---"
                ])
                for job in config.get("jobs", []):
                    status = "[ON]" if job.get("enabled", True) else "[OFF]"
                    last = job.get("last_run", "nie")
                    if last and last != "nie":
                        last = last[11:16] # Nur Zeit
                    output.append(f"  {status} {job.get('profile', '?'):12} (Alle {job.get('interval_minutes', '?')} Min, Last: {last})")
            except:
                pass

        # Profile auflisten
        output.extend(["", "--- Profile ---"])
        if self.session_profiles_dir.exists():
            profiles = list(self.session_profiles_dir.glob("*.json"))
            if profiles:
                for p in profiles:
                    output.append(f"  - {p.stem}")
            else:
                output.append("  (keine Profile definiert)")
        else:
            output.append("  (Profilordner nicht gefunden)")

        # Log-Preview
        log_file = self.log_dir / "session_daemon.log"
        if log_file.exists():
            try:
                lines = log_file.read_text(encoding='utf-8').strip().split("\n")
                output.extend(["", "--- Letzte Logs ---"])
                for line in lines[-5:]:
                    output.append(f"  {line[:80]}")
            except:
                pass

        return (True, "\n".join(output))

    def _session_trigger(self, args: list, dry_run: bool) -> tuple:
        """Triggert Session manuell."""
        auto_session = self.session_dir / "auto_session.py"
        if not auto_session.exists():
            return (False, f"[ERROR] auto_session.py nicht gefunden: {auto_session}")

        profile = self._get_profile_from_args(args)

        cmd = [sys.executable, str(auto_session), "--profile", profile]
        if dry_run or "--dry-run" in args:
            cmd.append("--dry-run")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.session_dir),
                capture_output=True,
                text=True,
                timeout=60
            )

            output = [f"[OK] Session getriggert (Profil: {profile})", ""]
            if result.stdout:
                output.extend(result.stdout.strip().split("\n")[-15:])
            if result.stderr:
                output.extend(["", "--- Errors ---", result.stderr[:500]])

            return (True, "\n".join(output))

        except subprocess.TimeoutExpired:
            return (False, "[ERROR] Timeout (>60s)")
        except Exception as e:
            return (False, f"[ERROR] Trigger fehlgeschlagen: {e}")

    def _session_profiles(self) -> tuple:
        """Listet verfuegbare Profile."""
        import json

        if not self.session_profiles_dir.exists():
            return (False, f"[ERROR] Profilordner nicht gefunden: {self.session_profiles_dir}")

        profiles = list(self.session_profiles_dir.glob("*.json"))

        if not profiles:
            return (True, "Keine Profile definiert.\n\nErstelle Profile in: " + str(self.session_profiles_dir))

        output = [
            "=== SESSION PROFILE ===",
            ""
        ]

        for pf in profiles:
            try:
                data = json.loads(pf.read_text(encoding='utf-8'))
                name = pf.stem
                desc = data.get('description', '-')
                source = data.get('task_source', 'ati_tasks')
                max_tasks = data.get('max_tasks', 3)
                timeout = data.get('timeout_minutes', 15)

                output.extend([
                    f"[{name}]",
                    f"  Beschreibung: {desc[:50]}",
                    f"  Task-Quelle:  {source}",
                    f"  Max Tasks:    {max_tasks}",
                    f"  Timeout:      {timeout} Min",
                    ""
                ])
            except:
                output.append(f"[{pf.stem}] (Fehler beim Laden)")

        output.extend([
            "--- Verwendung ---",
            "bach scheduler session start --profile NAME",
            "bach scheduler session trigger --profile NAME"
        ])

        return (True, "\n".join(output))


# Rueckwaertskompatibilitaet: DaemonHandler ist ein Alias fuer SchedulerHandler
DaemonHandler = SchedulerHandler
