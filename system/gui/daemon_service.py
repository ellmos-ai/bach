#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Daemon Service v1.0
========================
Hintergrund-Service fuer automatische Job-Ausfuehrung

Features:
- Cron-basierte Zeitplanung
- Interval-Jobs
- Event-basierte Trigger
- Logging und Fehlerbehandlung
- Graceful Shutdown
"""

import sys
import os
import time
import signal
import sqlite3
import subprocess
import threading
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass
import json
import shlex

# Recurring Tasks Integration
try:
    # Relativer Import innerhalb BACH
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from hub._services.recurring.recurring_tasks import check_recurring_tasks
    HAS_RECURRING = True
except ImportError:
    HAS_RECURRING = False

# Optional: croniter fuer erweiterte Cron-Ausdruecke
try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False

# Pfade
DAEMON_DIR = Path(__file__).parent
BACH_DIR = DAEMON_DIR.parent
DATA_DIR = BACH_DIR / "data"
USER_DB = DATA_DIR / "bach.db"
LOG_DIR = BACH_DIR / "data" / "logs"
DAEMON_PID_FILE = DATA_DIR / "daemon.pid"

# Logging konfigurieren
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "daemon.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BACH-Daemon")


@dataclass
class DaemonJob:
    """Repraesentiert einen Daemon-Job."""
    id: int
    name: str
    description: str
    job_type: str  # 'cron', 'interval', 'event', 'manual', 'chain'
    schedule: str
    command: str
    script_path: Optional[str]
    arguments: Optional[str]
    is_active: bool
    timeout_seconds: int
    retry_on_fail: bool
    max_retries: int
    last_run: Optional[datetime]
    next_run: Optional[datetime]
    

class DaemonService:
    """
    Hauptklasse fuer den Daemon-Service.
    
    Verwaltet Jobs, fuehrt sie nach Zeitplan aus
    und protokolliert Ergebnisse.
    """
    
    def __init__(self, db_path: Path = USER_DB):
        self.db_path = db_path
        self.running = False
        self.jobs: Dict[int, DaemonJob] = {}
        self.lock = threading.Lock()
        self._shutdown_event = threading.Event()
        
        # Signal-Handler registrieren
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Behandelt Shutdown-Signale."""
        logger.info(f"Signal {signum} empfangen - Shutdown eingeleitet")
        self.stop()
    
    def _get_db(self) -> sqlite3.Connection:
        """Erstellt DB-Verbindung."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def load_jobs(self):
        """Laedt aktive Jobs aus der Datenbank."""
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT * FROM scheduler_jobs WHERE is_active = 1
            """).fetchall()
            
            with self.lock:
                self.jobs.clear()
                for row in rows:
                    job = DaemonJob(
                        id=row['id'],
                        name=row['name'],
                        description=row['description'] or '',
                        job_type=row['job_type'],
                        schedule=row['schedule'] or '',
                        command=row['command'],
                        script_path=row['script_path'],
                        arguments=row['arguments'],
                        is_active=bool(row['is_active']),
                        timeout_seconds=row['timeout_seconds'] or 300,
                        retry_on_fail=bool(row['retry_on_fail']),
                        max_retries=row['max_retries'] or 3,
                        last_run=self._parse_datetime(row['last_run']),
                        next_run=self._parse_datetime(row['next_run'])
                    )
                    self.jobs[job.id] = job
                    self._calculate_next_run(job)
            
            logger.info(f"{len(self.jobs)} aktive Jobs geladen")
            
        finally:
            conn.close()
    
    def _parse_datetime(self, value) -> Optional[datetime]:
        """Parst Datetime aus DB-String."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
    
    def _calculate_next_run(self, job: DaemonJob):
        """Berechnet naechsten Ausfuehrungszeitpunkt."""
        now = datetime.now()
        
        if job.job_type == 'interval':
            # Format: "30m", "1h", "24h"
            interval = self._parse_interval(job.schedule)
            if interval:
                if job.last_run:
                    job.next_run = job.last_run + interval
                    if job.next_run < now:
                        job.next_run = now + interval
                else:
                    job.next_run = now + interval
                    
        elif job.job_type == 'cron' and HAS_CRONITER:
            # Cron-Ausdruck: "0 3 * * *" = 03:00 taeglich
            try:
                cron = croniter(job.schedule, now)
                job.next_run = cron.get_next(datetime)
            except Exception:
                logger.warning(f"Ungueltiger Cron-Ausdruck fuer Job {job.name}: {job.schedule}")
                
        elif job.job_type == 'manual':
            # Manuelle Jobs haben keinen automatischen Zeitplan
            job.next_run = None
    
    def _parse_interval(self, schedule: str) -> Optional[timedelta]:
        """Parst Interval-String (z.B. '30m', '1h', '24h')."""
        if not schedule:
            return None
        
        try:
            value = int(schedule[:-1])
            unit = schedule[-1].lower()

            if unit == 's':
                return timedelta(seconds=value)
            elif unit == 'm':
                return timedelta(minutes=value)
            elif unit == 'h':
                return timedelta(hours=value)
            elif unit == 'd':
                return timedelta(days=value)
        except (ValueError, IndexError):
            pass
        
        return None
    
    def run_job(self, job_id: int, triggered_by: str = 'schedule') -> dict:
        """Fuehrt einen Job aus."""
        job = self.jobs.get(job_id)
        if not job:
            return {"success": False, "error": "Job nicht gefunden"}
        
        logger.info(f"Starte Job '{job.name}' (ID: {job_id})")
        
        start_time = datetime.now()
        result = {
            "job_id": job_id,
            "job_name": job.name,
            "started_at": start_time.isoformat(),
            "triggered_by": triggered_by,
            "success": False,
            "output": "",
            "error": None,
            "duration_seconds": 0
        }
        
        try:
            # Command zusammenbauen
            cmd = job.command
            
            # Special handling for Chain jobs (B16: ChainHandler-Integration)
            if job.job_type == 'chain':
                return self._run_chain_job(job, result, start_time, triggered_by)

            if job.script_path:
                cmd_list = [sys.executable, str(job.script_path)]
                if job.arguments:
                    cmd_list.extend(shlex.split(job.arguments, posix=(os.name != 'nt')))
                process = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    encoding='utf-8', errors='replace',
                    timeout=job.timeout_seconds,
                    cwd=str(BACH_DIR)
                )
            else:
                if not cmd:
                    raise ValueError("Kein Command konfiguriert")
                if job.arguments:
                    cmd = f"{cmd} {job.arguments}"
                process = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8', errors='replace',
                    timeout=job.timeout_seconds,
                    cwd=str(BACH_DIR)
                )
            
            result["output"] = process.stdout
            result["success"] = process.returncode == 0
            
            if process.returncode != 0:
                result["error"] = process.stderr or f"Exit code: {process.returncode}"
                
        except subprocess.TimeoutExpired:
            result["error"] = f"Timeout nach {job.timeout_seconds}s"
            logger.error(f"Job '{job.name}' Timeout")
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Job '{job.name}' Fehler: {e}")
        
        # Dauer berechnen
        end_time = datetime.now()
        result["duration_seconds"] = (end_time - start_time).total_seconds()
        result["finished_at"] = end_time.isoformat()
        
        # In DB loggen
        self._log_run(job_id, result, triggered_by)
        
        # Job aktualisieren
        job.last_run = end_time
        self._calculate_next_run(job)
        self._update_job_in_db(job)
        
        status = "OK" if result["success"] else "FAILED"
        logger.info(f"Job '{job.name}' beendet [{status}] ({result['duration_seconds']:.1f}s)")
        
        return result
    
    def _run_chain_job(self, job, result: dict, start_time, triggered_by: str) -> dict:
        """Fuehrt einen Chain-Job via ChainHandler aus (B16).

        Command-Formate:
          - "llmauto:<name>"    -> ChainHandler.handle('start', [name])
          - "toolchain:<id>"    -> ChainHandler.handle('run', [id])
          - "<name>"            -> ChainHandler.handle('start', [name])  (Default: llmauto)
        """
        try:
            from hub.chain import ChainHandler
            chain_handler = ChainHandler(BACH_DIR)

            cmd_str = job.command.strip()

            if cmd_str.startswith("llmauto:"):
                chain_name = cmd_str[len("llmauto:"):]
                success, output = chain_handler.handle('start', [chain_name])
            elif cmd_str.startswith("toolchain:"):
                chain_id = cmd_str[len("toolchain:"):]
                success, output = chain_handler.handle('run', [chain_id])
            else:
                # Default: als llmauto-Chain-Name interpretieren
                success, output = chain_handler.handle('start', [cmd_str])

            result["success"] = success
            result["output"] = output
            if not success:
                result["error"] = output

        except ImportError as e:
            result["success"] = False
            result["error"] = f"ChainHandler Import fehlgeschlagen: {e}"
            logger.error(f"Chain-Job '{job.name}': {e}")
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            logger.error(f"Chain-Job '{job.name}' Fehler: {e}")

        end_time = datetime.now()
        result["duration_seconds"] = (end_time - start_time).total_seconds()
        result["finished_at"] = end_time.isoformat()

        self._log_run(job.id, result, triggered_by)

        job.last_run = end_time
        self._calculate_next_run(job)
        self._update_job_in_db(job)

        status = "OK" if result["success"] else "FAILED"
        logger.info(f"Chain-Job '{job.name}' beendet [{status}] ({result['duration_seconds']:.1f}s)")

        return result

    def _log_run(self, job_id: int, result: dict, triggered_by: str):
        """Protokolliert Job-Lauf in DB."""
        conn = self._get_db()
        try:
            conn.execute("""
                INSERT INTO scheduler_runs 
                (job_id, started_at, finished_at, duration_seconds, result, output, error, triggered_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                result["started_at"],
                result.get("finished_at"),
                result["duration_seconds"],
                "success" if result["success"] else "failed",
                result["output"][:10000] if result["output"] else None,  # Limitieren
                result.get("error"),
                triggered_by
            ))
            conn.commit()
        finally:
            conn.close()
    
    def _update_job_in_db(self, job: DaemonJob):
        """Aktualisiert Job in DB nach Ausfuehrung."""
        conn = self._get_db()
        try:
            conn.execute("""
                UPDATE scheduler_jobs 
                SET last_run = ?,
                    next_run = ?,
                    run_count = run_count + 1,
                    updated_at = ?
                WHERE id = ?
            """, (
                job.last_run.isoformat() if job.last_run else None,
                job.next_run.isoformat() if job.next_run else None,
                datetime.now().isoformat(),
                job.id
            ))
            conn.commit()
        finally:
            conn.close()
    
    def get_pending_jobs(self) -> List[DaemonJob]:
        """Gibt Jobs zurueck, die in den naechsten 60 Sekunden faellig sind."""
        now = datetime.now()
        cutoff = now + timedelta(seconds=60)
        with self.lock:
            return [
                job for job in self.jobs.values()
                if job.next_run and job.next_run <= cutoff
            ]

    def check_and_run_due_jobs(self):
        """Prueft und fuehrt faellige Jobs aus."""
        now = datetime.now()

        with self.lock:
            for job in list(self.jobs.values()):
                if job.next_run and job.next_run <= now:
                    # Job in eigenem Thread ausfuehren
                    thread = threading.Thread(
                        target=self.run_job,
                        args=(job.id, 'schedule'),
                        daemon=True
                    )
                    thread.start()
    
    def run(self, pause_onedrive: bool = True):
        """
        Startet den Daemon-Loop.

        Args:
            pause_onedrive: Wenn True, wird OneDrive waehrend des Daemon-Betriebs pausiert
        """
        self.running = True

        # PID-File erstellen
        DAEMON_PID_FILE.parent.mkdir(exist_ok=True)
        DAEMON_PID_FILE.write_text(str(os.getpid()))

        logger.info("BACH Daemon Service gestartet")

        # OneDrive pausieren wenn gewuenscht
        onedrive_paused = False
        if pause_onedrive:
            onedrive_paused = self.pause_onedrive()

        self.load_jobs()

        try:
            while self.running and not self._shutdown_event.is_set():
                self.check_and_run_due_jobs()

                # Warte 10 Sekunden oder bis Shutdown
                self._shutdown_event.wait(timeout=10)

                # Alle 5 Minuten Jobs neu laden und recurring Tasks pruefen
                if not self._shutdown_event.is_set():
                    if datetime.now().minute % 5 == 0 and datetime.now().second < 10:
                        self.load_jobs()
                        # Recurring Tasks pruefen (falls verfuegbar)
                        if HAS_RECURRING:
                            try:
                                created = check_recurring_tasks()
                                if created:
                                    logger.info(f"[RECURRING] {len(created)} faellige Tasks erstellt")
                            except Exception as e:
                                logger.error(f"[RECURRING] Fehler: {e}")

        finally:
            # OneDrive fortsetzen
            if onedrive_paused:
                self.resume_onedrive()

            # PID-File entfernen
            if DAEMON_PID_FILE.exists():
                DAEMON_PID_FILE.unlink()
            logger.info("BACH Daemon Service beendet")
    
    def stop(self):
        """Stoppt den Daemon gracefully."""
        logger.info("Stopping daemon...")
        self.running = False
        self._shutdown_event.set()

    @staticmethod
    def kill_all_daemons() -> dict:
        """
        Beendet alle laufenden Daemon-Prozesse (Zombie-Praevention).

        Returns:
            dict mit killed, errors, pid_file_removed
        """
        import psutil

        result = {
            "killed": [],
            "errors": [],
            "pid_file_removed": False
        }

        # 1. PID-File pruefen und Prozess beenden
        if DAEMON_PID_FILE.exists():
            try:
                pid_content = DAEMON_PID_FILE.read_text().strip()
                if pid_content:
                    # Thread-ID ist keine PID, aber wir koennen nach Prozessen suchen
                    logger.info(f"PID-File gefunden: {pid_content}")
                DAEMON_PID_FILE.unlink()
                result["pid_file_removed"] = True
                logger.info("PID-File entfernt")
            except Exception as e:
                result["errors"].append(f"PID-File Fehler: {e}")

        # 2. Alle Python-Prozesse finden die daemon_service.py ausfuehren
        try:
            current_pid = os.getpid()
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline') or []
                    cmdline_str = ' '.join(cmdline).lower()

                    # Daemon-Prozesse identifizieren
                    is_daemon = (
                        'daemon_service.py' in cmdline_str or
                        ('daemon' in cmdline_str and 'bach' in cmdline_str)
                    )

                    if is_daemon and proc.pid != current_pid:
                        logger.info(f"Beende Daemon-Prozess: PID {proc.pid}")
                        proc.terminate()

                        # Warte kurz und force-kill wenn noetig
                        try:
                            proc.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            proc.kill()
                            logger.warning(f"Force-kill fuer PID {proc.pid}")

                        result["killed"].append(proc.pid)

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except ImportError:
            result["errors"].append("psutil nicht installiert - manuelle Prozess-Suche nicht moeglich")
        except Exception as e:
            result["errors"].append(f"Prozess-Suche Fehler: {e}")

        # 3. Lock-Files aufräumen
        lock_files = list(DATA_DIR.glob("*.lock")) + list(DATA_DIR.glob("daemon*.pid"))
        for lock_file in lock_files:
            try:
                lock_file.unlink()
                logger.info(f"Lock-File entfernt: {lock_file.name}")
            except Exception as e:
                result["errors"].append(f"Lock-File {lock_file.name}: {e}")

        logger.info(f"kill_all_daemons: {len(result['killed'])} Prozesse beendet")
        return result

    @staticmethod
    def pause_onedrive() -> bool:
        """
        Pausiert OneDrive-Sync (Windows).
        Verhindert Sync-Konflikte waehrend Daemon-Operationen.

        Returns:
            True wenn erfolgreich oder nicht noetig
        """
        if sys.platform != 'win32':
            return True  # Nicht Windows, nicht noetig

        try:
            # OneDrive-Prozess finden und pausieren
            import psutil

            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and 'onedrive' in proc.info['name'].lower():
                    proc.suspend()
                    logger.info(f"OneDrive pausiert (PID: {proc.pid})")
                    return True

            logger.info("OneDrive nicht gefunden - kein Pausieren noetig")
            return True

        except ImportError:
            logger.warning("psutil nicht installiert - OneDrive-Pause nicht moeglich")
            return False
        except Exception as e:
            logger.error(f"OneDrive pausieren fehlgeschlagen: {e}")
            return False

    @staticmethod
    def resume_onedrive() -> bool:
        """
        Setzt OneDrive-Sync fort (Windows).

        Returns:
            True wenn erfolgreich oder nicht noetig
        """
        if sys.platform != 'win32':
            return True

        try:
            import psutil

            for proc in psutil.process_iter(['pid', 'name', 'status']):
                if proc.info['name'] and 'onedrive' in proc.info['name'].lower():
                    if proc.status() == psutil.STATUS_STOPPED:
                        proc.resume()
                        logger.info(f"OneDrive fortgesetzt (PID: {proc.pid})")
                    return True

            return True

        except ImportError:
            return False
        except Exception as e:
            logger.error(f"OneDrive fortsetzen fehlgeschlagen: {e}")
            return False

    def get_status(self) -> dict:
        """Liefert aktuellen Daemon-Status."""
        conn = self._get_db()
        try:
            total_jobs = conn.execute("SELECT COUNT(*) FROM scheduler_jobs").fetchone()[0]
            active_jobs = conn.execute("SELECT COUNT(*) FROM scheduler_jobs WHERE is_active = 1").fetchone()[0]
            
            last_runs = conn.execute("""
                SELECT j.name, r.result, r.finished_at 
                FROM scheduler_runs r 
                JOIN scheduler_jobs j ON r.job_id = j.id
                ORDER BY r.id DESC LIMIT 5
            """).fetchall()
            
            return {
                "running": self.running,
                "pid_file": str(DAEMON_PID_FILE),
                "pid_exists": DAEMON_PID_FILE.exists(),
                "total_jobs": total_jobs,
                "active_jobs": active_jobs,
                "loaded_jobs": len(self.jobs),
                "last_runs": [dict(r) for r in last_runs]
            }
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════
# CLI INTERFACE
# ═══════════════════════════════════════════════════════════════

def main():
    """CLI-Einstiegspunkt."""
    import argparse
    
    parser = argparse.ArgumentParser(description="BACH Daemon Service")
    parser.add_argument("action", choices=['start', 'status', 'run-job'],
                       help="Aktion: start, status, run-job")
    parser.add_argument("--job-id", type=int, help="Job-ID fuer run-job")
    parser.add_argument("--foreground", "-f", action="store_true",
                       help="Im Vordergrund laufen (nicht daemonisieren)")
    
    args = parser.parse_args()
    
    daemon = DaemonService()
    
    if args.action == "start":
        print("[BACH] Daemon Service wird gestartet...")
        print(f"       PID-File: {DAEMON_PID_FILE}")
        print(f"       Log: {LOG_DIR / 'daemon.log'}")
        print("")
        print("       Ctrl+C zum Beenden")
        daemon.run()
        
    elif args.action == "status":
        status = daemon.get_status()
        print("=== DAEMON STATUS ===")
        print(f"Running:     {status['running']}")
        print(f"PID exists:  {status['pid_exists']}")
        print(f"Total Jobs:  {status['total_jobs']}")
        print(f"Active Jobs: {status['active_jobs']}")
        if status['last_runs']:
            print("\n--- Letzte Laeufe ---")
            for run in status['last_runs']:
                print(f"  {run['name']}: {run['result']} ({run['finished_at']})")
                
    elif args.action == "run-job":
        if not args.job_id:
            print("[ERROR] --job-id erforderlich")
            sys.exit(1)
        daemon.load_jobs()
        result = daemon.run_job(args.job_id, triggered_by='manual')
        if result['success']:
            print(f"[OK] Job erfolgreich ausgefuehrt")
            if result['output']:
                print(f"\n{result['output']}")
        else:
            print(f"[ERROR] Job fehlgeschlagen: {result['error']}")


if __name__ == "__main__":
    main()
