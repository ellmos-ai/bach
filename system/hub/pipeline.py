#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Pipeline-Handler für BACH
SQ011: Generisches Pipeline-Installations-Framework
Phase 1: Basis-Handler mit list-available, list, status

Zweck:
- Pipelines verwalten (install, list, status, start, stop)
- Pipeline-Definitionen aus pipelines/*.json lesen
- Pipeline-Runs tracken
"""

import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import sys
# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB


class PipelineHandler:
    """Handler für Pipeline-Management."""

    def __init__(self, db_path: str, pipelines_dir: str):
        """
        Initialisiert den PipelineHandler.

        Args:
            db_path: Pfad zur bach.db
            pipelines_dir: Pfad zum pipelines/ Verzeichnis
        """
        self.db_path = db_path
        self.pipelines_dir = Path(pipelines_dir)

    def _get_db(self) -> sqlite3.Connection:
        """Öffnet Datenbankverbindung."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_available(self) -> List[Dict]:
        """
        Listet alle verfügbaren Pipeline-Definitionen auf.

        Returns:
            Liste von Pipeline-Metadaten (id, name, type, description)
        """
        pipelines = []

        if not self.pipelines_dir.exists():
            return pipelines

        for json_file in self.pipelines_dir.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                pipelines.append({
                    'id': data.get('id'),
                    'name': data.get('name'),
                    'version': data.get('version'),
                    'type': data.get('type'),
                    'description': data.get('description'),
                    'schedule': data.get('schedule'),
                    'file': json_file.name
                })
            except (json.JSONDecodeError, KeyError, IOError) as e:
                print(f"Warnung: Fehlerhafte Pipeline-Definition {json_file.name}: {e}")

        return sorted(pipelines, key=lambda x: x['id'])

    def list_installed(self) -> List[Dict]:
        """
        Listet alle installierten Pipelines auf.

        Returns:
            Liste von installierten Pipelines aus pipeline_configs
        """
        conn = self._get_db()
        cursor = conn.execute("""
            SELECT
                pipeline_id,
                name,
                version,
                type,
                schedule,
                installed_at,
                last_run,
                status
            FROM pipeline_configs
            ORDER BY installed_at DESC
        """)

        pipelines = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return pipelines

    def get_status(self, pipeline_id: str) -> Optional[Dict]:
        """
        Zeigt Status einer installierten Pipeline.

        Args:
            pipeline_id: Pipeline-ID (z.B. "ati")

        Returns:
            Pipeline-Status dict oder None wenn nicht gefunden
        """
        conn = self._get_db()

        # Config abrufen
        cursor = conn.execute("""
            SELECT * FROM pipeline_configs
            WHERE pipeline_id = ?
        """, (pipeline_id,))

        config = cursor.fetchone()
        if not config:
            conn.close()
            return None

        # Letzte 5 Runs abrufen
        cursor = conn.execute("""
            SELECT * FROM pipeline_runs
            WHERE pipeline_id = ?
            ORDER BY started_at DESC
            LIMIT 5
        """, (pipeline_id,))

        runs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return {
            'config': dict(config),
            'runs': runs
        }

    def interactive_install(self, pipeline_id: str) -> bool:
        """
        Interaktive Installation einer Pipeline (Phase 2).

        Fragt User nach Konfiguration (config_questions) und installiert.

        Args:
            pipeline_id: Pipeline-ID (z.B. "ati")

        Returns:
            True wenn erfolgreich
        """
        # Pipeline-Definition laden
        definition_file = self.pipelines_dir / f"{pipeline_id}.json"
        if not definition_file.exists():
            print(f"Fehler: Pipeline-Definition {pipeline_id}.json nicht gefunden")
            return False

        with open(definition_file, 'r', encoding='utf-8') as f:
            definition = json.load(f)

        print(f"\n=== Installation: {definition['name']} ===")
        print(f"Beschreibung: {definition['description']}")
        print(f"Typ: {definition['type']}")
        print(f"Schedule: {definition.get('schedule', 'manual')}\n")

        # Config-Fragen abarbeiten
        config = {}
        config_questions = definition.get('config_questions', [])

        if not config_questions:
            # Keine Fragen -> leere Config
            print("Keine Konfiguration erforderlich")
        else:
            print("Konfiguration:")
            for question in config_questions:
                key = question['key']
                prompt = question['prompt']
                qtype = question.get('type', 'text')
                default = question.get('default')

                # Default als String formatieren
                default_str = ""
                if default is not None:
                    if isinstance(default, list):
                        default_str = f" [{', '.join(map(str, default))}]"
                    else:
                        default_str = f" [{default}]"

                # User fragen
                print(f"\n{prompt}{default_str}")
                user_input = input("> ").strip()

                # Wenn leer, Default nutzen
                if not user_input and default is not None:
                    config[key] = default
                    print(f"  → Verwende Default: {default}")
                elif qtype == 'list':
                    # Komma-separierte Liste
                    config[key] = [x.strip() for x in user_input.split(',') if x.strip()]
                else:
                    config[key] = user_input

        # Installation durchführen
        print(f"\n✓ Konfiguration abgeschlossen")
        print(f"Installiere Pipeline '{pipeline_id}'...")
        return self.install(pipeline_id, config)

    def install(self, pipeline_id: str, config: Dict) -> bool:
        """
        Installiert eine Pipeline (speichert Konfiguration in DB).

        Args:
            pipeline_id: Pipeline-ID (z.B. "ati")
            config: User-Konfiguration (aus config_questions)

        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        # Pipeline-Definition laden
        definition_file = self.pipelines_dir / f"{pipeline_id}.json"
        if not definition_file.exists():
            print(f"Fehler: Pipeline-Definition {pipeline_id}.json nicht gefunden")
            return False

        with open(definition_file, 'r', encoding='utf-8') as f:
            definition = json.load(f)

        # In DB speichern
        conn = self._get_db()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO pipeline_configs
                    (pipeline_id, name, version, type, schedule, config_json, installed_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pipeline_id,
                definition['name'],
                definition.get('version'),
                definition.get('type'),
                definition.get('schedule'),
                json.dumps(config, ensure_ascii=False),
                datetime.now().isoformat(),
                'active'
            ))
            conn.commit()
            print(f"✓ Pipeline '{pipeline_id}' installiert")
            return True
        except sqlite3.Error as e:
            print(f"Fehler beim Installieren: {e}")
            return False
        finally:
            conn.close()

    def uninstall(self, pipeline_id: str) -> bool:
        """
        Deinstalliert eine Pipeline (entfernt Config aus DB).

        Args:
            pipeline_id: Pipeline-ID

        Returns:
            True wenn erfolgreich
        """
        conn = self._get_db()
        try:
            conn.execute("DELETE FROM pipeline_configs WHERE pipeline_id = ?", (pipeline_id,))
            conn.commit()
            print(f"✓ Pipeline '{pipeline_id}' deinstalliert")
            return True
        except sqlite3.Error as e:
            print(f"Fehler beim Deinstallieren: {e}")
            return False
        finally:
            conn.close()

    def start_run(self, pipeline_id: str) -> Optional[int]:
        """
        Startet einen neuen Pipeline-Run (erstellt Eintrag in pipeline_runs).

        Args:
            pipeline_id: Pipeline-ID

        Returns:
            run_id wenn erfolgreich, None bei Fehler
        """
        conn = self._get_db()
        try:
            cursor = conn.execute("""
                INSERT INTO pipeline_runs (pipeline_id, started_at, status)
                VALUES (?, ?, 'running')
            """, (pipeline_id, datetime.now().isoformat()))
            conn.commit()
            run_id = cursor.lastrowid
            return run_id
        except sqlite3.Error as e:
            print(f"Fehler beim Run-Start: {e}")
            return None
        finally:
            conn.close()

    def finish_run(self, run_id: int, status: str, items_processed: int = 0,
                   errors_count: int = 0, log: str = ""):
        """
        Beendet einen Pipeline-Run.

        Args:
            run_id: Run-ID
            status: "completed" oder "failed"
            items_processed: Anzahl verarbeiteter Items
            errors_count: Anzahl Fehler
            log: Log-Text
        """
        conn = self._get_db()
        try:
            conn.execute("""
                UPDATE pipeline_runs
                SET finished_at = ?,
                    status = ?,
                    items_processed = ?,
                    errors_count = ?,
                    log = ?
                WHERE id = ?
            """, (
                datetime.now().isoformat(),
                status,
                items_processed,
                errors_count,
                log,
                run_id
            ))

            # last_run in pipeline_configs aktualisieren
            conn.execute("""
                UPDATE pipeline_configs
                SET last_run = ?
                WHERE pipeline_id = (
                    SELECT pipeline_id FROM pipeline_runs WHERE id = ?
                )
            """, (datetime.now().isoformat(), run_id))

            conn.commit()
        except sqlite3.Error as e:
            print(f"Fehler beim Run-Finish: {e}")
        finally:
            conn.close()

    def schedule(self, pipeline_id: str, enable: bool = True) -> bool:
        """
        Aktiviert/Deaktiviert Scheduler-Job für eine Pipeline.

        Erstellt daemon_job Eintrag basierend auf Pipeline.schedule.

        Args:
            pipeline_id: Pipeline-ID
            enable: True = Job aktivieren, False = deaktivieren

        Returns:
            True wenn erfolgreich
        """
        # Pipeline-Config laden
        conn = self._get_db()
        cursor = conn.execute("""
            SELECT name, schedule FROM pipeline_configs
            WHERE pipeline_id = ?
        """, (pipeline_id,))
        row = cursor.fetchone()

        if not row:
            print(f"Pipeline '{pipeline_id}' nicht gefunden")
            conn.close()
            return False

        pipeline_name = row['name']
        schedule = row['schedule']

        # Schedule in Cron-Expression umwandeln
        schedule_map = {
            'daily': '0 6 * * *',      # Täglich um 6 Uhr
            'hourly': '0 * * * *',      # Stündlich
            'weekly': '0 6 * * 1',      # Montags um 6 Uhr
            'monthly': '0 6 1 * *',     # Am 1. des Monats um 6 Uhr
        }

        cron_expr = schedule_map.get(schedule, schedule)  # Fallback: schedule direkt als Cron

        # daemon_job erstellen/aktualisieren
        try:
            conn.execute("""
                INSERT INTO scheduler_jobs
                    (name, description, job_type, schedule, command, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    schedule = excluded.schedule,
                    command = excluded.command,
                    is_active = excluded.is_active,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                f"pipeline_{pipeline_id}",
                f"Pipeline: {pipeline_name}",
                'cron',
                cron_expr,
                f"bach pipeline run {pipeline_id}",
                1 if enable else 0
            ))
            conn.commit()
            status = "aktiviert" if enable else "deaktiviert"
            print(f"✓ Scheduler-Job '{pipeline_id}' {status}")
            print(f"  Schedule: {schedule} ({cron_expr})")
            return True
        except sqlite3.Error as e:
            print(f"Fehler beim Scheduler-Setup: {e}")
            return False
        finally:
            conn.close()

    def run(self, pipeline_id: str) -> bool:
        """
        Führt eine Pipeline aus (Phase 3).

        Lädt entry_point, instantiiert class, ruft method auf.

        Args:
            pipeline_id: Pipeline-ID (z.B. "ati")

        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        import sys
        import importlib.util
        from pathlib import Path

        # Pipeline-Definition laden
        definition_file = self.pipelines_dir / f"{pipeline_id}.json"
        if not definition_file.exists():
            print(f"Fehler: Pipeline-Definition {pipeline_id}.json nicht gefunden")
            return False

        with open(definition_file, 'r', encoding='utf-8') as f:
            definition = json.load(f)

        # Config aus DB laden
        conn = self._get_db()
        cursor = conn.execute("""
            SELECT config_json FROM pipeline_configs
            WHERE pipeline_id = ? AND status = 'active'
        """, (pipeline_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            print(f"Fehler: Pipeline '{pipeline_id}' nicht installiert")
            print("Verwenden Sie: bach pipeline install " + pipeline_id)
            return False

        config = json.loads(row['config_json']) if row['config_json'] else {}

        # Run starten
        run_id = self.start_run(pipeline_id)
        if not run_id:
            return False

        print(f"\n=== Pipeline Run: {definition['name']} ===")
        print(f"Run ID: {run_id}")
        log_lines = []

        try:
            # entry_point Pfad auflösen (relativ zu BACH-Root, nicht system/)
            entry_point = definition.get('entry_point')
            if not entry_point:
                raise ValueError("Kein entry_point in Pipeline-Definition")

            # Pfad relativ zu system/ (entry_points beginnen mit agents/...)
            system_dir = Path(self.db_path).parent.parent  # system/data/ -> system/
            entry_path = system_dir / entry_point

            if not entry_path.exists():
                raise FileNotFoundError(f"entry_point nicht gefunden: {entry_path}")

            # Modul dynamisch laden
            spec = importlib.util.spec_from_file_location("pipeline_module", entry_path)
            if not spec or not spec.loader:
                raise ImportError(f"Konnte Modul nicht laden: {entry_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules['pipeline_module'] = module
            spec.loader.exec_module(module)

            # Klasse instantiieren
            class_name = definition.get('class')
            if not class_name or not hasattr(module, class_name):
                raise AttributeError(f"Klasse '{class_name}' nicht in Modul gefunden")

            cls = getattr(module, class_name)

            # Konstruktor-Argumente vorbereiten
            # Standard: db_path + config
            instance = cls(self.db_path, config)

            # Methode aufrufen
            method_name = definition.get('method', 'run')
            if not hasattr(instance, method_name):
                raise AttributeError(f"Methode '{method_name}' nicht in Klasse '{class_name}' gefunden")

            method = getattr(instance, method_name)
            result = method()

            # Result auswerten (erwartet dict mit Statistiken)
            if isinstance(result, dict):
                items = result.get('tasks_found', 0) or result.get('items_processed', 0)
                errors = result.get('errors', [])
                errors_count = len(errors) if isinstance(errors, list) else result.get('errors_count', 0)

                log_lines.append(f"Pipeline {definition['name']} erfolgreich ausgeführt")
                log_lines.append(f"Items processed: {items}")
                log_lines.append(f"Errors: {errors_count}")

                if errors and isinstance(errors, list) and errors:
                    log_lines.append("\nFehler:")
                    log_lines.extend([f"  - {e}" for e in errors[:10]])  # Max 10 Fehler

                self.finish_run(run_id, 'completed', items, errors_count, '\n'.join(log_lines))
                print("\n✓ Pipeline-Run erfolgreich")
                print(f"  Items: {items}, Fehler: {errors_count}")
                return True
            else:
                log_lines.append(f"Pipeline ausgeführt, aber kein Result-Dict zurückgegeben")
                self.finish_run(run_id, 'completed', 0, 0, '\n'.join(log_lines))
                print("\n✓ Pipeline-Run abgeschlossen")
                return True

        except Exception as e:
            import traceback
            error_msg = f"Fehler beim Pipeline-Run: {e}\n{traceback.format_exc()}"
            log_lines.append(error_msg)
            print(f"\n✗ {error_msg}")
            self.finish_run(run_id, 'failed', 0, 1, '\n'.join(log_lines))
            return False


def _handle_pipeline(argv):
    """
    CLI-Handler für bach pipeline ...

    Befehle:
    - bach pipeline list-available   # Alle verfügbaren Pipelines
    - bach pipeline list              # Installierte Pipelines
    - bach pipeline status <name>     # Status einer Pipeline
    - bach pipeline install <name>    # Pipeline installieren (interaktiv, Phase 2)
    - bach pipeline run <name>        # Pipeline ausführen (Phase 3)
    - bach pipeline schedule <name>   # Scheduler aktivieren (Phase 3)
    - bach pipeline unschedule <name> # Scheduler deaktivieren (Phase 3)
    """
    import sys

    # Pfade ermitteln
    script_dir = Path(__file__).parent.parent  # system/
    db_path = BACH_DB
    pipelines_dir = script_dir / "pipelines"

    handler = PipelineHandler(str(db_path), str(pipelines_dir))

    if not argv or argv[0] in ['--help', 'help']:
        print("Verwendung: bach pipeline <command> [args]")
        print("\nVerfügbare Befehle:")
        print("  list-available      Alle verfügbaren Pipeline-Definitionen")
        print("  list                Installierte Pipelines")
        print("  status <id>         Status einer Pipeline")
        print("  install <id>        Pipeline installieren (Phase 2)")
        print("  run <id>            Pipeline ausführen (Phase 3)")
        print("  schedule <id>       Scheduler aktivieren (Phase 3)")
        print("  unschedule <id>     Scheduler deaktivieren (Phase 3)")
        return

    command = argv[0]

    if command == 'list-available':
        pipelines = handler.list_available()
        if not pipelines:
            print("Keine Pipeline-Definitionen gefunden")
            print(f"Erwarteter Pfad: {pipelines_dir}")
            return

        print(f"\n{len(pipelines)} verfügbare Pipelines:\n")
        for p in pipelines:
            print(f"  {p['id']:15} {p['name']:30} ({p['type']}, {p['schedule']})")
            print(f"  {'':15} {p['description']}")
            print()

    elif command == 'list':
        pipelines = handler.list_installed()
        if not pipelines:
            print("Keine Pipelines installiert")
            print("Verwenden Sie: bach pipeline install <name>")
            return

        print(f"\n{len(pipelines)} installierte Pipelines:\n")
        for p in pipelines:
            print(f"  {p['pipeline_id']:15} {p['name']:30} [{p['status']}]")
            print(f"  {'':15} Installiert: {p['installed_at']}")
            if p['last_run']:
                print(f"  {'':15} Letzter Run: {p['last_run']}")
            print()

    elif command == 'status':
        if len(argv) < 2:
            print("Fehler: Pipeline-ID fehlt")
            print("Verwendung: bach pipeline status <pipeline_id>")
            return

        pipeline_id = argv[1]
        status = handler.get_status(pipeline_id)

        if not status:
            print(f"Pipeline '{pipeline_id}' nicht gefunden")
            return

        config = status['config']
        runs = status['runs']

        print(f"\nPipeline: {config['name']} (ID: {config['pipeline_id']})")
        print(f"Version:  {config['version']}")
        print(f"Typ:      {config['type']}")
        print(f"Schedule: {config['schedule']}")
        print(f"Status:   {config['status']}")
        print(f"\nInstalliert: {config['installed_at']}")
        if config['last_run']:
            print(f"Letzter Run: {config['last_run']}")

        if runs:
            print(f"\nLetzte {len(runs)} Runs:")
            for run in runs:
                print(f"  {run['started_at']:20} {run['status']:10} "
                      f"Items: {run['items_processed']}, Fehler: {run['errors_count']}")
        else:
            print("\nNoch keine Runs")

    elif command == 'install':
        if len(argv) < 2:
            print("Fehler: Pipeline-ID fehlt")
            print("Verwendung: bach pipeline install <pipeline_id>")
            print("\nVerfügbare Pipelines:")
            for p in handler.list_available():
                print(f"  {p['id']:15} {p['name']}")
            return

        pipeline_id = argv[1]

        # Prüfe ob Pipeline bereits installiert ist
        installed = handler.list_installed()
        if any(p['pipeline_id'] == pipeline_id for p in installed):
            print(f"Pipeline '{pipeline_id}' ist bereits installiert")
            print("Verwenden Sie: bach pipeline status " + pipeline_id)
            reinstall = input("Möchten Sie neu installieren? (j/n): ").strip().lower()
            if reinstall not in ['j', 'ja', 'y', 'yes']:
                print("Installation abgebrochen")
                return

        # Interaktive Installation
        success = handler.interactive_install(pipeline_id)
        if not success:
            print(f"✗ Installation fehlgeschlagen")
        else:
            print(f"\n✓ Pipeline '{pipeline_id}' erfolgreich installiert")
            print(f"Verwenden Sie: bach pipeline status {pipeline_id}")

    elif command == 'run':
        if len(argv) < 2:
            print("Fehler: Pipeline-ID fehlt")
            print("Verwendung: bach pipeline run <pipeline_id>")
            print("\nInstallierte Pipelines:")
            for p in handler.list_installed():
                print(f"  {p['pipeline_id']:15} {p['name']}")
            return

        pipeline_id = argv[1]

        # Pipeline ausführen (Phase 3)
        success = handler.run(pipeline_id)
        if not success:
            print(f"\n✗ Pipeline-Run fehlgeschlagen")
        else:
            print(f"\nVerwenden Sie: bach pipeline status {pipeline_id}")

    elif command == 'schedule':
        if len(argv) < 2:
            print("Fehler: Pipeline-ID fehlt")
            print("Verwendung: bach pipeline schedule <pipeline_id>")
            return

        pipeline_id = argv[1]
        handler.schedule(pipeline_id, enable=True)

    elif command == 'unschedule':
        if len(argv) < 2:
            print("Fehler: Pipeline-ID fehlt")
            print("Verwendung: bach pipeline unschedule <pipeline_id>")
            return

        pipeline_id = argv[1]
        handler.schedule(pipeline_id, enable=False)

    else:
        print(f"Unbekannter Befehl: {command}")
        print("Verwenden Sie: bach pipeline --help")


if __name__ == '__main__':
    import sys
    _handle_pipeline(sys.argv[1:])
