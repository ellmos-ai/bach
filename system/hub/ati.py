# SPDX-License-Identifier: MIT
"""
ATI Handler - Advanced Tool Integration Agent
=============================================

ATI ist das Software-Entwickler-Plugin fuer BACH.
ATI = BATCHI - BACH (das Delta, was BACH noch fehlt)

BEFEHLE:
  ati status              ATI-Status anzeigen
  ati start               Headless-Daemon starten
  ati stop                Daemon stoppen
  ati onboard PATH        Neues Projekt onboarden
  ati check               Between-Task-Checkliste
  ati problems            Problems First anzeigen
  ati context KEYWORD     Kontext-Trigger testen
  ati task list           ATI-Tasks anzeigen
  ati task add "TITEL"    ATI-Task hinzufuegen
  ati scan                Software-Scanner starten
  ati scan status         Letzten Scan anzeigen
  ati scan tasks          Gescannte Tasks anzeigen
  ati sync                DB-Status zurueck zu AUFGABEN.txt schreiben
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class ATIHandler(BaseHandler):
    """Handler fuer ATI Agent-Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.ati_dir = base_path / "agents" / "ati"
        self.ati_data_dir = base_path / "data" / "ati"
        self.config_path = self.ati_dir / "data" / "config.json"
        self.db_path = self._canonical_db
        self.session_service_dir = base_path / "hub" / "_services" / "daemon"
        # user_db entfernt - alle Daten jetzt in bach.db (v1.3.0)
    
    @property
    def profile_name(self) -> str:
        return "ati"
    
    @property
    def target_file(self) -> Path:
        return self.ati_dir
    
    def get_operations(self) -> dict:
        return {
            "status": "ATI-Status anzeigen",
            "start": "Headless-Daemon starten",
            "stop": "Daemon stoppen",
            "session": "Session-Verwaltung (session, session --dry-run)",
            "onboard": "Neues Projekt onboarden (onboard PATH)",
            "check": "Between-Task-Checkliste anzeigen",
            "problems": "Problems First - Fehler anzeigen",
            "context": "Kontext-Trigger testen (context KEYWORD)",
            "task": "ATI-Tasks verwalten (list, add, done)",
            "scan": "Software-Scanner (scan, scan status, scan tasks)",
            "sync": "DB-Status zurueck zu AUFGABEN.txt synchronisieren",
            "path": "Tool-Pfad anzeigen (path NAME oder path --list)",
            "export": "ATI-Agent exportieren (export, export --dry-run)",
            "install": "ATI-Export installieren (install PFAD.zip)",
            "bootstrap": "Neues Projekt mit BACH-Policies erstellen (bootstrap NAME --template TYPE)",
            "migrate": "Bestehendes Projekt migrieren (migrate PATH --template TYPE)",
            "modules": "Module verwalten (modules list)"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        """Hauptmethode - delegiert an Unteroperationen"""
        if operation == "help":
            return self._show_help()
        elif operation == "status":
            return self._status(args)
        elif operation == "start":
            return self._start_daemon(args, dry_run)
        elif operation == "stop":
            return self._stop_daemon(args)
        elif operation == "session":
            return self._handle_session(args, dry_run)
        elif operation == "onboard":
            return self._onboard(args)
        elif operation == "check":
            return self._between_checks(args)
        elif operation == "problems":
            return self._problems_first(args)
        elif operation == "context":
            return self._context_trigger(args)
        elif operation == "task":
            return self._handle_task(args)
        elif operation == "scan":
            return self._handle_scan(args, dry_run)
        elif operation == "sync":
            return self._handle_sync(args)
        elif operation == "path":
            return self._get_tool_path(args)
        elif operation == "export":
            return self._handle_export(args, dry_run)
        elif operation == "install":
            return self._handle_install(args, dry_run)
        elif operation == "bootstrap":
            return self._handle_bootstrap(args, dry_run)
        elif operation == "migrate":
            return self._handle_migrate(args, dry_run)
        elif operation == "modules":
            return self._handle_modules(args)
        else:
            return False, f"Unbekannte ATI-Operation: {operation}\n\nVerfuegbare Operationen:\n" + \
                   "\n".join(f"  {k}: {v}" for k, v in self.get_operations().items())
    
    def _show_help(self) -> tuple:
        """Zeigt ATI-Hilfe an"""
        help_path = self.base_path / "help" / "ati.txt"
        if help_path.exists():
            return True, help_path.read_text(encoding='utf-8')
        
        # Fallback: Inline-Hilfe
        help_text = """
ATI - ADVANCED TOOL INTEGRATION AGENT
=====================================

ATI ist das Software-Entwickler-Plugin fuer BACH.
Formel: ATI = BATCHI - BACH (das Delta)

BEFEHLE:
--------
  bach ati status         ATI-Status anzeigen
  bach ati start          Headless-Daemon starten
  bach ati stop           Daemon stoppen
  bach ati onboard PATH   Neues Projekt onboarden
  bach ati check          Between-Task-Checkliste
  bach ati problems       Problems First - Fehler anzeigen
  bach ati context KEY    Kontext-Trigger testen
  bach ati task list      ATI-Tasks anzeigen
  bach ati task add "T"   ATI-Task hinzufuegen

FEATURES (Delta zu BACH):
-------------------------
  - Headless AI-Sessions (autonom)
  - Automatisches Projekt-Onboarding
  - Between-Task-Checks
  - Problems First
  - Context Sources

Mehr Info: agents/ati/ATI.md
"""
        return True, help_text
    
    def _status(self, args: list) -> tuple:
        """Zeigt ATI-Status"""
        output = []
        output.append("\n[ATI STATUS]")
        output.append("=" * 50)
        
        # Ordner-Check
        output.append("\n[Struktur]")
        if self.ati_dir.exists():
            output.append(f"  ATI-Ordner: {self.ati_dir} [OK]")
        else:
            output.append(f"  ATI-Ordner: {self.ati_dir} [FEHLT]")
        
        if self.ati_data_dir.exists():
            output.append(f"  Daten-Ordner: {self.ati_data_dir} [OK]")
        else:
            output.append(f"  Daten-Ordner: {self.ati_data_dir} [FEHLT]")
        
        # Config laden
        config = self._load_config()
        output.append("\n[Konfiguration]")
        output.append(f"  Enabled: {config.get('enabled', False)}")
        
        session_cfg = config.get('session', {})
        output.append(f"  Session-Intervall: {session_cfg.get('interval_minutes', 30)} min")
        output.append(f"  Max Tasks/Session: {session_cfg.get('max_tasks_per_session', 3)}")
        
        # Daemon-Status (nutzt System-Service)
        output.append("\n[Session Daemon]")
        pid_file = self.base_path / "skills" / "_services" / "daemon" / "daemon.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
                import os
                import subprocess
                if sys.platform == 'win32':
                    result = subprocess.run(
                        ['tasklist', '/FI', f'PID eq {pid}'],
                        capture_output=True, text=True
                    )
                    is_running = str(pid) in result.stdout
                else:
                    try:
                        os.kill(pid, 0)
                        is_running = True
                    except (ProcessLookupError, PermissionError, OSError):
                        is_running = False

                if is_running:
                    output.append(f"  Status: AKTIV (PID {pid})")
                else:
                    output.append("  Status: INAKTIV (PID-Datei veraltet)")
            except (ProcessLookupError, ValueError):
                output.append("  Status: INAKTIV (PID-Datei veraltet)")
        else:
            output.append("  Status: INAKTIV")
        output.append("  Starten: bach ati start")
        output.append("  Alternativ: bach daemon session start --profile ati")

        # Feature-Status
        output.append("\n[Features]")
        features = [
            ("Headless Sessions", "BEREIT"),
            ("Onboarding", "GEPLANT"),
            ("Between-Checks", "BEREIT"),
            ("Problems First", "GEPLANT"),
            ("Context Sources", "GEPLANT")
        ]
        for name, status in features:
            output.append(f"  {name}: {status}")
        
        output.append("\n" + "=" * 50)
        return True, "\n".join(output)
    
    def _start_daemon(self, args: list, dry_run: bool = False) -> tuple:
        """Startet Session-Daemon mit ATI-Profil (nutzt System-Service)"""
        # System-Service nutzen
        daemon_script = self.session_service_dir / "session_daemon.py"

        if not daemon_script.exists():
            return False, f"[ATI DAEMON] System-Service nicht gefunden: {daemon_script}"

        if dry_run:
            return True, "[DRY-RUN] Wuerde Session-Daemon mit ATI-Profil starten"

        import subprocess

        # ATI-Profil als Default
        cmd = [sys.executable, str(daemon_script), "--profile", "ati"]
        for i, arg in enumerate(args):
            if arg == "--interval" and i + 1 < len(args):
                cmd.extend(["--interval", args[i + 1]])

        try:
            creation_flags = 0x08000000 if sys.platform == "win32" else 0
            subprocess.Popen(
                cmd,
                cwd=str(daemon_script.parent),
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True, "[ATI] Session-Daemon gestartet (Profil: ati)\n\nStatus: bach daemon status"
        except Exception as e:
            return False, f"[ATI DAEMON] Start fehlgeschlagen: {e}"

    def _stop_daemon(self, args: list) -> tuple:
        """Stoppt Session-Daemon (System-Service)"""
        daemon_script = self.session_service_dir / "session_daemon.py"

        if not daemon_script.exists():
            return False, "[ATI DAEMON] System-Service nicht gefunden"

        import subprocess
        try:
            result = subprocess.run(
                [sys.executable, str(daemon_script), "--stop"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return True, result.stdout or "[ATI] Session-Daemon gestoppt"
        except Exception as e:
            return False, f"[ATI DAEMON] Stop fehlgeschlagen: {e}"

    def _handle_session(self, args: list, dry_run: bool = False) -> tuple:
        """Manuelle Session mit ATI-Profil starten (nutzt System-Service)"""
        auto_session = self.session_service_dir / "auto_session.py"

        if not auto_session.exists():
            return False, f"[ATI SESSION] System-Service nicht gefunden: {auto_session}"

        import subprocess

        # ATI-Profil als Default
        cmd = [sys.executable, str(auto_session), "--profile", "ati"]
        if dry_run or "--dry-run" in args:
            cmd.append("--dry-run")
        if "--force" in args:
            cmd.append("--force")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(auto_session.parent),
                capture_output=True,
                text=True,
                timeout=120
            )
            output = result.stdout or result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "[ATI SESSION] Timeout (>120s)"
        except Exception as e:
            return False, f"[ATI SESSION] Fehler: {e}"
    
    def _onboard(self, args: list) -> tuple:
        """Onboardet neues Projekt"""
        if not args:
            return False, """
[ATI ONBOARD]
Verwendung: bach ati onboard PATH

Optionen:
  bach ati onboard PATH        Einzelnes Projekt onboarden
  bach ati onboard --check     Alle neuen Projekte pruefen

Onboarding erstellt automatisch:
  1. Feature-Analyse Task
  2. Code-Qualitaetspruefung Task
  3. AUFGABEN.txt Task
"""

        # --check: Automatische Erkennung neuer Tools
        if args[0] == "--check":
            try:
                sys.path.insert(0, str(self.base_path))
                from agents.ati.onboarding.tool_discovery import check_new_tools
                new_tools = check_new_tools()

                if new_tools:
                    return True, f"[ATI ONBOARD] {len(new_tools)} neue Tools gefunden:\n  " + \
                           "\n  ".join(new_tools) + "\n\nOnboarding-Tasks wurden erstellt."
                else:
                    return True, "[ATI ONBOARD] Keine neuen Tools gefunden"

            except Exception as e:
                return False, f"[ATI ONBOARD] Check fehlgeschlagen: {e}"

        # Einzelnes Projekt onboarden
        path = Path(args[0])
        if not path.exists():
            return False, f"[ATI ONBOARD] Pfad existiert nicht: {path}"

        try:
            sys.path.insert(0, str(self.base_path))
            from agents.ati.onboarding.tool_discovery import onboard_project
            result = onboard_project(str(path))

            if result['success']:
                return True, f"""
[ATI ONBOARD] Erfolgreich
Projekt: {result['tool_name']}
Pfad: {result['path']}
Tasks erstellt: {result['tasks_created']}

Tasks anzeigen: bach ati task list
"""
            else:
                return False, f"[ATI ONBOARD] Fehler: {result.get('error', 'Unbekannt')}"

        except Exception as e:
            return False, f"[ATI ONBOARD] Fehler: {e}"
    
    def _between_checks(self, args: list) -> tuple:
        """Zeigt Between-Task-Checkliste"""
        config = self._load_config()
        checks = config.get('between_checks', {}).get('items', [
            "Memory aktualisiert?",
            "Aenderungen dokumentiert?",
            "Tests ausgefuehrt?",
            "Naechster Task klar?"
        ])
        
        output = ["\n[BETWEEN-TASK-CHECKS]", "=" * 40]
        output.append("Vor dem naechsten Task pruefen:\n")
        
        for i, check in enumerate(checks, 1):
            output.append(f"  [ ] {check}")
        
        output.append("\n" + "=" * 40)
        output.append("Tipp: bach mem write 'Check: Alles geprueft'")
        
        return True, "\n".join(output)
    
    def _problems_first(self, args: list) -> tuple:
        """Zeigt Problems First - Fehler aus Auto-Log (Stub)"""
        return True, """
[PROBLEMS FIRST] (STUB)
Keine Fehler in letzter Session gefunden.

TODO:
  - Auto-Log nach ERROR filtern
  - Letzte Exceptions anzeigen
  - Kontext zu Fehlern laden

Siehe: agents/ati/ATI.md
"""
    
    def _context_trigger(self, args: list) -> tuple:
        """Testet Kontext-Trigger (Stub)"""
        if not args:
            return False, """
[ATI CONTEXT]
Verwendung: bach ati context KEYWORD

Keywords und ihre Trigger:
  fehler      -> lessons_learned laden
  blockiert   -> strategies laden
  startup     -> best_practices laden
"""
        
        keyword = args[0].lower()
        triggers = {
            "fehler": "lessons_learned",
            "blockiert": "strategies",
            "startup": "best_practices"
        }
        
        if keyword in triggers:
            return True, f"""
[ATI CONTEXT]
Keyword: {keyword}
Trigger: {triggers[keyword]}

STUB - Kontext wuerde geladen werden.
TODO: context_sources.py implementieren
"""
        else:
            return False, f"[ATI CONTEXT] Unbekanntes Keyword: {keyword}"
    
    def _handle_task(self, args: list) -> tuple:
        """Verwaltet ATI-Tasks"""
        if not args:
            return False, """
[ATI TASK]
Verwendung:
  bach ati task list              ATI-Tasks anzeigen
  bach ati task add "TITEL"       Neuen Task erstellen
  bach ati task done ID           Task erledigen
  bach ati task depends ID DEP    Abhaengigkeit hinzufuegen
  bach ati task blocked           Blockierte Tasks anzeigen

Hinweis: ATI-Tasks sind Software-Entwicklungs-Tasks,
         getrennt von BACH System-Tasks.
"""

        subop = args[0]

        if subop == "list":
            return self._task_list()
        elif subop == "add":
            return self._task_add(args[1:])
        elif subop == "done":
            return self._task_done(args[1:])
        elif subop == "depends":
            return self._task_depends(args[1:])
        elif subop == "blocked":
            return self._task_blocked()
        else:
            return False, f"[ATI TASK] Unbekannte Operation: {subop}"

    def _task_add(self, args: list) -> tuple:
        """Fuegt neuen ATI-Task hinzu"""
        if not args:
            return False, "Verwendung: bach ati task add \"TITEL\" [--tool NAME] [--aufwand hoch|mittel|niedrig]"

        task_text = args[0]
        tool_name = "MANUAL"
        aufwand = "mittel"

        # Optionen parsen
        for i, arg in enumerate(args):
            if arg == "--tool" and i + 1 < len(args):
                tool_name = args[i + 1]
            elif arg == "--aufwand" and i + 1 < len(args):
                aufwand = args[i + 1]

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    INSERT INTO ati_tasks
                    (tool_name, tool_path, task_text, aufwand, status, priority_score,
                     source_file, synced_at, is_synced)
                    VALUES (?, '', ?, ?, 'offen', 50, 'manual', ?, 1)
                """, (tool_name, task_text, aufwand, datetime.now().isoformat()))

                task_id = cursor.lastrowid
                conn.commit()
            finally:
                conn.close()

            return True, f"[ATI TASK] Task #{task_id} erstellt: {task_text[:50]}"

        except Exception as e:
            return False, f"[ATI TASK] Fehler: {e}"

    def _task_done(self, args: list) -> tuple:
        """Markiert ATI-Task als erledigt"""
        if not args:
            return False, "Verwendung: bach ati task done ID"

        try:
            task_id = int(args[0])
        except ValueError:
            return False, f"[ATI TASK] Ungueltige ID: {args[0]}"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                task = conn.execute(
                    "SELECT task_text, status FROM ati_tasks WHERE id = ?",
                    (task_id,)
                ).fetchone()

                if not task:
                    return False, f"[ATI TASK] Task #{task_id} nicht gefunden"

                if task[1] == 'erledigt':
                    return False, f"[ATI TASK] Task #{task_id} bereits erledigt"

                conn.execute(
                    "UPDATE ati_tasks SET status = 'erledigt', synced_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), task_id)
                )
                conn.commit()
            finally:
                conn.close()

            try:
                from agents.ati.scanner.task_scanner import sync_db_to_aufgaben
                sync_result = sync_db_to_aufgaben(self.db_path, task_ids=[task_id])

                if sync_result['tasks_synced'] > 0:
                    return True, f"[ATI TASK] Task #{task_id} erledigt und in AUFGABEN.txt synchronisiert: {task[0][:50]}"
                else:
                    return True, f"[ATI TASK] Task #{task_id} erledigt: {task[0][:50]}"
            except Exception as sync_err:
                return True, f"[ATI TASK] Task #{task_id} erledigt (Sync-Warnung: {sync_err}): {task[0][:50]}"

        except Exception as e:
            return False, f"[ATI TASK] Fehler: {e}"

    def _task_depends(self, args: list) -> tuple:
        """Fuegt Abhaengigkeit hinzu"""
        if len(args) < 2:
            return False, "Verwendung: bach ati task depends TASK_ID DEPENDS_ON_ID"

        try:
            task_id = int(args[0])
            dep_id = int(args[1])
        except ValueError:
            return False, "[ATI TASK] Ungueltige IDs"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                task = conn.execute("SELECT depends_on FROM ati_tasks WHERE id = ?", (task_id,)).fetchone()
                dep = conn.execute("SELECT id FROM ati_tasks WHERE id = ?", (dep_id,)).fetchone()

                if not task:
                    return False, f"[ATI TASK] Task #{task_id} nicht gefunden"
                if not dep:
                    return False, f"[ATI TASK] Abhaengigkeit #{dep_id} nicht gefunden"

                existing = []
                if task[0]:
                    try:
                        existing = json.loads(task[0])
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass

                if dep_id in existing:
                    return False, f"[ATI TASK] Abhaengigkeit bereits vorhanden"

                existing.append(dep_id)

                conn.execute(
                    "UPDATE ati_tasks SET depends_on = ? WHERE id = ?",
                    (json.dumps(existing, ensure_ascii=False), task_id)
                )
                conn.commit()
            finally:
                conn.close()

            return True, f"[ATI TASK] Task #{task_id} haengt jetzt von #{dep_id} ab"

        except Exception as e:
            return False, f"[ATI TASK] Fehler: {e}"

    def _task_blocked(self) -> tuple:
        """Zeigt blockierte Tasks (mit unerfuellten Abhaengigkeiten)"""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                tasks = conn.execute("""
                    SELECT id, task_text, depends_on, tool_name
                    FROM ati_tasks
                    WHERE status = 'offen' AND depends_on IS NOT NULL AND depends_on != '[]'
                """).fetchall()

                if not tasks:
                    return True, "[ATI TASK] Keine blockierten Tasks"

                output = ["[ATI BLOCKED TASKS]", "-" * 60]
                blocked_count = 0

                for task_id, text, deps_json, tool in tasks:
                    try:
                        deps = json.loads(deps_json)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        continue

                    open_deps = []
                    for dep_id in deps:
                        dep_status = conn.execute(
                            "SELECT status FROM ati_tasks WHERE id = ?",
                            (dep_id,)
                        ).fetchone()
                        if dep_status and dep_status[0] != 'erledigt':
                            open_deps.append(dep_id)

                    if open_deps:
                        blocked_count += 1
                        short_text = text[:40] + "..." if len(text) > 40 else text
                        output.append(f"\n#{task_id} [{tool}] {short_text}")
                        output.append(f"  Wartet auf: {', '.join(f'#{d}' for d in open_deps)}")
            finally:
                conn.close()

            output.append("-" * 60)
            output.append(f"Gesamt: {blocked_count} blockierte Tasks")

            return True, "\n".join(output)

        except Exception as e:
            return False, f"[ATI TASK] Fehler: {e}"

    def _task_list(self) -> tuple:
        """Zeigt ATI-Tasks aus bach.db/ati_tasks"""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                total = conn.execute("SELECT COUNT(*) FROM ati_tasks").fetchone()[0]
                offen = conn.execute("SELECT COUNT(*) FROM ati_tasks WHERE status = 'offen'").fetchone()[0]
                erledigt = conn.execute("SELECT COUNT(*) FROM ati_tasks WHERE status = 'erledigt'").fetchone()[0]

                tasks = conn.execute("""
                    SELECT tool_name, task_text, aufwand, priority_score
                    FROM ati_tasks
                    WHERE status = 'offen'
                    ORDER BY priority_score DESC
                    LIMIT 15
                """).fetchall()
            finally:
                conn.close()

            output = [
                "[ATI TASKS]",
                f"Gesamt: {total} | Offen: {offen} | Erledigt: {erledigt}",
                "",
                "Top 15 offene Tasks (nach Prioritaet):",
                "-" * 60
            ]

            for tool, text, aufwand, prio in tasks:
                short_text = text[:45] + "..." if len(text) > 45 else text
                prio_str = f"{prio:.0f}" if prio else "-"
                output.append(f"  [{tool[:12]:12}] {short_text}")
                output.append(f"               Aufwand: {aufwand or '-':7} Prio: {prio_str}")

            output.append("-" * 60)
            output.append("Mehr: bach ati scan tasks")

            return True, "\n".join(output)

        except Exception as e:
            return False, f"[ATI TASK] Fehler: {e}"

    def _handle_scan(self, args: list, dry_run: bool = False) -> tuple:
        """ATI Scanner - Software-Projekte scannen"""
        scan_args = [arg for arg in args if arg not in ("--dry-run", "-n")]
        effective_dry_run = dry_run or len(scan_args) != len(args)

        if not scan_args:
            # bach ati scan -> Scanner starten
            return self._run_scan(effective_dry_run)
        
        subop = scan_args[0]
        if subop == "status":
            return self._scan_status()
        elif subop == "tasks":
            tool_filter = None
            if len(scan_args) > 1 and scan_args[1] == "--tool" and len(scan_args) > 2:
                tool_filter = scan_args[2]
            return self._scan_tasks(tool_filter)
        elif subop == "run":
            return self._run_scan(effective_dry_run)
        else:
            return False, f"""
[ATI SCAN] Unbekannte Operation: {subop}

Verwendung:
  bach ati scan              Scanner starten
  bach ati scan status       Letzten Scan anzeigen
  bach ati scan tasks        Gescannte Tasks anzeigen
  bach ati scan tasks --tool X  Nach Tool filtern
"""
    
    def _run_scan(self, dry_run: bool = False) -> tuple:
        """Fuehrt ATI Scanner aus"""
        if dry_run:
            return True, "[DRY-RUN] Wuerde ATI-Scanner starten"
        
        try:
            # ATI Scanner importieren
            sys.path.insert(0, str(self.base_path))
            from agents.ati.scanner.task_scanner import TaskScanner
            
            scanner = TaskScanner(self.db_path)
            result = scanner.scan_all()
            
            output = [
                "[ATI SCAN] Scan abgeschlossen",
                f"    Tools gescannt: {result['tools_scanned']}",
                f"    Tasks gefunden: {result['tasks_found']}",
                f"    Neu: {result['tasks_new']}",
                f"    Aktualisiert: {result['tasks_updated']}"
            ]
            
            if result.get('errors'):
                output.append(f"    Fehler: {len(result['errors'])}")
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[ATI SCAN] Scan fehlgeschlagen: {e}"
    
    def _scan_status(self) -> tuple:
        """Zeigt Status des letzten Scans"""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                last_scan = conn.execute("""
                    SELECT started_at, finished_at, duration_seconds,
                           tools_scanned, tasks_found, tasks_new, tasks_updated
                    FROM ati_scan_runs
                    ORDER BY id DESC LIMIT 1
                """).fetchone()

                if not last_scan:
                    return True, "[ATI SCAN] Noch kein Scan durchgefuehrt"

                total_tasks = conn.execute("SELECT COUNT(*) FROM ati_tasks").fetchone()[0]
                total_tools = conn.execute("SELECT COUNT(*) FROM ati_tool_registry").fetchone()[0]
                open_tasks = conn.execute(
                    "SELECT COUNT(*) FROM ati_tasks WHERE status IN ('offen', 'in_arbeit')"
                ).fetchone()[0]
            finally:
                conn.close()
            
            output = [
                "[ATI SCAN STATUS]",
                "=" * 40,
                "",
                f"Letzter Scan: {last_scan[0]}",
                f"Dauer: {last_scan[2]:.2f}s" if last_scan[2] else "Dauer: -",
                f"Tools gescannt: {last_scan[3]}",
                f"Tasks gefunden: {last_scan[4]}",
                "",
                "--- Gesamt ---",
                f"Registrierte Tools: {total_tools}",
                f"Gescannte Tasks: {total_tasks}",
                f"Offene Tasks: {open_tasks}"
            ]
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[ATI SCAN] Status-Abfrage fehlgeschlagen: {e}"
    
    def _scan_tasks(self, tool_filter: str = None) -> tuple:
        """Zeigt gescannte Tasks"""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                if tool_filter:
                    tasks = conn.execute("""
                        SELECT tool_name, task_text, aufwand, status, priority_score
                        FROM ati_tasks
                        WHERE tool_name LIKE ? AND status IN ('offen', 'in_arbeit')
                        ORDER BY priority_score DESC
                        LIMIT 20
                    """, (f"%{tool_filter}%",)).fetchall()
                else:
                    tasks = conn.execute("""
                        SELECT tool_name, task_text, aufwand, status, priority_score
                        FROM ati_tasks
                        WHERE status IN ('offen', 'in_arbeit')
                        ORDER BY priority_score DESC
                        LIMIT 20
                    """).fetchall()
            finally:
                conn.close()
            
            if not tasks:
                if tool_filter:
                    return True, f"[ATI SCAN] Keine offenen Tasks fuer Tool '{tool_filter}'"
                return True, "[ATI SCAN] Keine offenen Tasks gefunden"
            
            output = ["[ATI SCAN TASKS]", "=" * 60, ""]
            for tool, text, aufwand, status, prio in tasks:
                short_text = text[:50] + "..." if len(text) > 50 else text
                output.append(f"[{tool}] {short_text}")
                output.append(f"    Aufwand: {aufwand or '-'} | Status: {status} | Prio: {prio:.0f}")
                output.append("")
            
            output.append(f"Gesamt: {len(tasks)} Tasks angezeigt (max 20)")
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[ATI SCAN] Tasks-Abfrage fehlgeschlagen: {e}"

    def _handle_sync(self, args: list) -> tuple:
        """Synchronisiert DB-Status zurueck zu AUFGABEN.txt Dateien"""
        try:
            from agents.ati.scanner.task_scanner import sync_db_to_aufgaben

            # Optionale Task-IDs als Filter
            task_ids = None
            if args:
                try:
                    task_ids = [int(arg) for arg in args]
                except ValueError:
                    return False, "[ATI SYNC] Ungueltige Task-IDs. Verwendung: bach ati sync [ID1 ID2 ...]"

            # Sync durchfuehren
            result = sync_db_to_aufgaben(self.db_path, task_ids=task_ids)

            output = [
                "[ATI SYNC] Synchronisation abgeschlossen",
                f"    Dateien aktualisiert: {result['files_updated']}",
                f"    Tasks synchronisiert: {result['tasks_synced']}"
            ]

            if result.get('errors'):
                output.append(f"    Fehler: {len(result['errors'])}")
                for error in result['errors'][:3]:  # Max 3 Fehler anzeigen
                    output.append(f"      - {error}")

            return True, "\n".join(output)

        except Exception as e:
            return False, f"[ATI SYNC] Sync fehlgeschlagen: {e}"

    def _get_tool_path(self, args: list) -> tuple:
        """Zeigt Pfad eines Tools aus ati_tool_registry."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                if not args or args[0] == "--list":
                    tools = conn.execute(
                        "SELECT name, path FROM ati_tool_registry WHERE status = 'aktiv' ORDER BY name"
                    ).fetchall()

                    if not tools:
                        return True, "[ATI PATH] Keine Tools registriert.\nTipp: 'bach ati scan' zum Scannen ausfuehren."

                    output = ["[ATI TOOL PATHS]", "-" * 70]
                    for name, path in tools:
                        output.append(f"  {name:25} {path}")
                    output.append("-" * 70)
                    output.append(f"Gesamt: {len(tools)} Tools")
                    return True, "\n".join(output)

                tool_name = " ".join([a for a in args if not a.startswith("-")])

                result = conn.execute(
                    "SELECT name, path, status, task_count, last_scan FROM ati_tool_registry WHERE name LIKE ?",
                    (f"%{tool_name}%",)
                ).fetchone()
            finally:
                conn.close()

            if result:
                name, path, status, tasks, last_scan = result
                if "--verbose" in args or "-v" in args:
                    scan_str = last_scan[:19] if last_scan else "nie"
                    return True, f"Tool: {name}\nPfad: {path}\nStatus: {status}\nTasks: {tasks}\nLetzter Scan: {scan_str}"
                return True, path

            return False, f"[ATI PATH] Tool nicht gefunden: {tool_name}\nTipp: 'bach ati path --list' zeigt alle Tools"

        except Exception as e:
            return False, f"[ATI PATH] Fehler: {e}"

    def _handle_export(self, args: list, dry_run: bool = False) -> tuple:
        """Exportiert ATI-Agent als ZIP"""
        exporter_path = self.ati_dir / "export" / "ati_exporter.py"
        
        if not exporter_path.exists():
            return False, f"[ATI EXPORT] Exporter nicht gefunden: {exporter_path}"
        
        import subprocess
        
        # Optionen sammeln
        cmd = [sys.executable, str(exporter_path)]
        
        if dry_run or "--dry-run" in args:
            cmd.append("--dry-run")
        if "--verbose" in args or "-v" in args:
            cmd.append("--verbose")
        
        # Output-Pfad
        for i, arg in enumerate(args):
            if arg in ("--output", "-o") and i + 1 < len(args):
                cmd.extend(["--output", args[i + 1]])
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(exporter_path.parent),
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output = result.stdout or result.stderr
            if result.returncode == 0:
                return True, output
            else:
                return False, f"[ATI EXPORT] Fehler:\n{output}"
                
        except subprocess.TimeoutExpired:
            return False, "[ATI EXPORT] Timeout (>60s)"
        except Exception as e:
            return False, f"[ATI EXPORT] Fehler: {e}"
    
    def _handle_install(self, args: list, dry_run: bool = False) -> tuple:
        """Installiert ATI-Export aus ZIP in diese BACH-Instanz"""
        import zipfile
        import shutil
        
        if not args:
            return False, """
[ATI INSTALL]
Verwendung: bach ati install PFAD.zip [--dry-run] [--force]

Optionen:
  --dry-run    Nur anzeigen, was installiert wuerde
  --force      Existierende Dateien ueberschreiben ohne Nachfrage

Beispiel:
  bach ati install dist/system/exports/bach-ati-v1.0.0-20260121.zip

Das ZIP muss ein manifest.json mit type='bach-agent' enthalten.
"""
        
        zip_path = Path(args[0])
        force = "--force" in args
        
        if dry_run or "--dry-run" in args:
            dry_run = True
        
        # ZIP existiert?
        if not zip_path.exists():
            return False, f"[ATI INSTALL] Datei nicht gefunden: {zip_path}"
        
        if not zipfile.is_zipfile(zip_path):
            return False, f"[ATI INSTALL] Keine gueltige ZIP-Datei: {zip_path}"
        
        output = ["[ATI INSTALL]", "=" * 50]
        output.append(f" Quelle: {zip_path}")
        output.append(f" Ziel:   {self.base_path}")
        output.append("=" * 50)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Manifest laden
                if 'manifest.json' not in zf.namelist():
                    return False, "[ATI INSTALL] Kein manifest.json im ZIP gefunden"
                
                manifest_data = zf.read('manifest.json').decode('utf-8')
                manifest = json.loads(manifest_data)
                
                # Typ pruefen
                valid_types = ['agent', 'bach-agent']
                if manifest.get('type') not in valid_types:
                    return False, f"[ATI INSTALL] Falscher Typ: {manifest.get('type')} (erwartet: agent oder bach-agent)"
                
                output.append(f"\n[MANIFEST]")
                output.append(f"  Name:        {manifest.get('name')}")
                output.append(f"  Version:     {manifest.get('version')}")
                output.append(f"  Description: {manifest.get('description', '-')}")
                
                # Dateien auflisten
                files = [f for f in zf.namelist() if f != 'manifest.json' and not f.endswith('/')]
                
                output.append(f"\n[DATEIEN]")
                output.append(f"  Gesamt: {len(files)} Dateien")
                
                # Konflikte pruefen
                conflicts = []
                new_files = []
                
                for filepath in files:
                    target = self.base_path / filepath
                    if target.exists():
                        conflicts.append(filepath)
                    else:
                        new_files.append(filepath)
                
                output.append(f"  Neu:       {len(new_files)}")
                output.append(f"  Konflikte: {len(conflicts)}")
                
                if conflicts and not force and not dry_run:
                    output.append(f"\n[KONFLIKT] {len(conflicts)} Dateien existieren bereits:")
                    for f in conflicts[:10]:
                        output.append(f"    - {f}")
                    if len(conflicts) > 10:
                        output.append(f"    ... und {len(conflicts) - 10} weitere")
                    output.append(f"\nVerwende --force zum Ueberschreiben")
                    return False, "\n".join(output)
                
                if dry_run:
                    output.append(f"\n[DRY-RUN] Keine Aenderungen")
                    output.append(f"\nDateien die installiert wuerden:")
                    for f in sorted(files)[:20]:
                        marker = "[KONFLIKT]" if f in conflicts else "[NEU]"
                        output.append(f"  {marker} {f}")
                    if len(files) > 20:
                        output.append(f"  ... und {len(files) - 20} weitere")
                    return True, "\n".join(output)
                
                # Installation durchfuehren
                output.append(f"\n[INSTALLIERE]")
                installed = 0
                errors = []
                
                for filepath in files:
                    target = self.base_path / filepath
                    
                    try:
                        # Verzeichnis erstellen
                        target.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Datei extrahieren
                        data = zf.read(filepath)
                        target.write_bytes(data)
                        installed += 1
                        
                    except Exception as e:
                        errors.append(f"{filepath}: {e}")
                
                output.append(f"  Installiert: {installed}/{len(files)}")
                
                if errors:
                    output.append(f"\n[FEHLER]")
                    for err in errors[:5]:
                        output.append(f"  - {err}")
                
                output.append(f"\n[DONE]")
                output.append(f"  ATI {manifest.get('version')} erfolgreich installiert!")
                
                return True, "\n".join(output)
                
        except json.JSONDecodeError as e:
            return False, f"[ATI INSTALL] Manifest ungueltig: {e}"
        except Exception as e:
            return False, f"[ATI INSTALL] Fehler: {e}"
    
    def _load_config(self) -> dict:
        """Laedt ATI-Konfiguration"""
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        
        # Default-Config
        return {
            "enabled": False,
            "session": {
                "interval_minutes": 30,
                "quiet_start": "22:00",
                "quiet_end": "08:00",
                "timeout_minutes": 15,
                "max_tasks_per_session": 3
            },
            "between_checks": {
                "enabled": True,
                "items": [
                    "Memory aktualisiert?",
                    "Aenderungen dokumentiert?",
                    "Tests ausgefuehrt?",
                    "Naechster Task klar?"
                ]
            }
        }
    
    # =========================================================================
    # BOOTSTRAP, MIGRATE, MODULES (Task #189)
    # =========================================================================
    
    def _handle_bootstrap(self, args: list, dry_run: bool = False) -> tuple:
        """
        Neues Projekt mit BACH-Policies erstellen.
        
        Usage:
            bach ati bootstrap NAME
            bach ati bootstrap NAME --template python-cli
            bach ati bootstrap NAME --path /target/dir
            bach ati bootstrap NAME --modules path_healer encoding
        """
        output = []
        output.append("\n[ATI BOOTSTRAP]")
        
        if not args:
            output.append("Fehler: Projektname erforderlich")
            output.append("\nUsage:")
            output.append("  bach ati bootstrap my-project")
            output.append("  bach ati bootstrap my-project --template llm-skill")
            output.append("  bach ati bootstrap my-project --path C:\\Projects")
            output.append("\nVerfuegbare Templates:")
            output.append("  python-cli    Python CLI-Projekt")
            output.append("  python-api    Python API-Projekt")
            output.append("  llm-skill     LLM Skill (BACH-konform)")
            output.append("  llm-agent     LLM Agent (BACH-konform)")
            output.append("  generic       Universelles Projekt")
            return False, "\n".join(output)
        
        # Argumente parsen
        project_name = args[0]
        template = "python-cli"
        target_path = None
        modules = None
        
        # --dry-run aus args erkennen (Bug-Fix Task #200)
        if "--dry-run" in args:
            dry_run = True
        
        i = 1
        while i < len(args):
            if args[i] in ["--template", "-t"] and i + 1 < len(args):
                template = args[i + 1]
                i += 2
            elif args[i] in ["--path", "-p"] and i + 1 < len(args):
                target_path = Path(args[i + 1])
                i += 2
            elif args[i] in ["--modules", "-m"]:
                modules = []
                i += 1
                while i < len(args) and not args[i].startswith("-"):
                    modules.append(args[i])
                    i += 1
            else:
                i += 1
        
        try:
            # ProjectBootstrapper importieren
            sys.path.insert(0, str(self.ati_dir / "tools"))
            from project_bootstrapper import ProjectBootstrapper
            
            bootstrapper = ProjectBootstrapper()
            
            if dry_run:
                output.append(f"\n[DRY-RUN] Wuerde erstellen:")
                output.append(f"  Name: {project_name}")
                output.append(f"  Template: {template}")
                output.append(f"  Pfad: {target_path or 'aktuelles Verzeichnis'}")
                output.append(f"  Module: {modules or bootstrapper.config.default_modules}")
                return True, "\n".join(output)
            
            # Bootstrap ausfuehren
            result = bootstrapper.bootstrap(
                name=project_name,
                template=template,
                target_path=target_path,
                modules=modules
            )
            
            if result["status"] == "completed":
                output.append(f"\n[OK] Projekt '{project_name}' erfolgreich erstellt!")
                output.append(f"  Pfad: {result['project_path']}")
                output.append(f"  Template: {result['template']}")
                
                # Erstellte Verzeichnisse
                for step in result.get("steps", []):
                    if step["step"] == "structure":
                        dirs = step["result"].get("created_dirs", [])
                        files = step["result"].get("created_files", [])
                        output.append(f"  Verzeichnisse: {len(dirs)}")
                        output.append(f"  Dateien: {len(files)}")
                
                output.append(f"\n[NAECHSTE SCHRITTE]")
                output.append(f"  cd {result['project_path']}")
                output.append(f"  # SKILL.md anpassen")
                output.append(f"  # Erste Funktion implementieren")
                
                return True, "\n".join(output)
            else:
                output.append(f"\n[FEHLER] Bootstrap fehlgeschlagen")
                output.append(f"  Status: {result['status']}")
                if "error" in result:
                    output.append(f"  Error: {result['error']}")
                return False, "\n".join(output)
                
        except ImportError as e:
            output.append(f"\n[FEHLER] Bootstrapper nicht gefunden: {e}")
            return False, "\n".join(output)
        except Exception as e:
            output.append(f"\n[FEHLER] Bootstrap fehlgeschlagen: {e}")
            return False, "\n".join(output)
    
    def _handle_migrate(self, args: list, dry_run: bool = False) -> tuple:
        """
        Bestehendes Projekt migrieren.
        
        Usage:
            bach ati migrate /path/to/project
            bach ati migrate /path/to/project --template llm-skill
            bach ati migrate /path/to/project --dry-run
        """
        output = []
        output.append("\n[ATI MIGRATE]")
        
        if not args:
            output.append("Fehler: Projektpfad erforderlich")
            output.append("\nUsage:")
            output.append("  bach ati migrate /path/to/project")
            output.append("  bach ati migrate /path/to/project --template llm-skill")
            output.append("  bach ati migrate /path/to/project --analyze")
            return False, "\n".join(output)
        
        project_path = Path(args[0])
        template = "llm-skill"
        analyze_only = "--analyze" in args
        
        # --dry-run aus args erkennen (Bug-Fix Task #200)
        if "--dry-run" in args:
            dry_run = True
        
        if "--template" in args:
            idx = args.index("--template")
            if idx + 1 < len(args):
                template = args[idx + 1]
        
        try:
            sys.path.insert(0, str(self.ati_dir / "tools"))
            from project_bootstrapper import ProjectBootstrapper
            
            bootstrapper = ProjectBootstrapper()
            
            if analyze_only:
                result = bootstrapper.analyze(project_path, template)
                output.append(f"\n[ANALYSE] {project_path}")
                output.append(f"  Ziel-Template: {template}")
                output.append(f"  Status: {result.get('status', 'unknown')}")
                
                if result.get("missing_dirs"):
                    output.append(f"\n  Fehlende Verzeichnisse:")
                    for d in result["missing_dirs"]:
                        output.append(f"    - {d}")
                        
                if result.get("missing_files"):
                    output.append(f"\n  Fehlende Dateien:")
                    for f in result["missing_files"]:
                        output.append(f"    - {f}")
                
                return True, "\n".join(output)
            
            # Migration
            result = bootstrapper.migrate(
                project_path=project_path,
                target_template=template,
                dry_run=dry_run
            )
            
            output.append(f"\n[MIGRATE] {project_path}")
            output.append(f"  Template: {template}")
            output.append(f"  Dry-Run: {dry_run}")
            output.append(f"  Status: {result.get('status', 'unknown')}")
            
            return True, "\n".join(output)
            
        except Exception as e:
            output.append(f"\n[FEHLER] Migration fehlgeschlagen: {e}")
            return False, "\n".join(output)
    
    def _handle_modules(self, args: list) -> tuple:
        """
        Module verwalten.
        
        Usage:
            bach ati modules list
        """
        output = []
        output.append("\n[ATI MODULES]")
        
        if not args or args[0] == "list":
            try:
                sys.path.insert(0, str(self.ati_dir / "tools"))
                from project_bootstrapper import ProjectBootstrapper
                
                bootstrapper = ProjectBootstrapper()
                modules = bootstrapper.module_injector.list_modules()
                
                output.append("\nVerfuegbare Module:")
                for m in modules:
                    status = "[OK]" if m["available"] else "[--]"
                    output.append(f"  {status} {m['name']}")
                
                return True, "\n".join(output)
                
            except Exception as e:
                output.append(f"[FEHLER] Module auflisten fehlgeschlagen: {e}")
                return False, "\n".join(output)
        
        return False, "Unbekannte Module-Operation. Verfuegbar: list"


def handle_ati(base_path: Path, args: list, dry_run: bool = False) -> tuple:
    """Einstiegspunkt fuer ATI-Handler"""
    handler = ATIHandler(base_path)
    
    if not args:
        return handler._status([])
    
    operation = args[0]
    return handler.handle(operation, args[1:], dry_run)
