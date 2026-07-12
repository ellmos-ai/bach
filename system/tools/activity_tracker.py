#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Activity Tracker - Inaktivitäts-Erkennung für automatische Finalisierung (SQ022)
=================================================================================

Implementiert Variante B (Lazy Checking ohne Daemon):
- Aktualisiert last_activity bei jedem CLI-Befehl
- Prüft bei jedem Befehl ob Idle-Schwelle überschritten
- Ruft shutdown._complete() bei Inaktivität (30 Min)

Referenz: BACH_Dev/SQ022_IDLE_TIMER_KONZEPT.md
Datum: 2026-02-20
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict


class ActivityTracker:
    """Verwaltet last_activity Timestamp und Idle-Checking."""

    def __init__(self, db_path: Path, idle_threshold_minutes: int = 30):
        """
        Args:
            db_path: Pfad zur bach.db
            idle_threshold_minutes: Schwelle für Inaktivität (default: 30 Min)
        """
        self.db_path = Path(db_path)
        self.idle_threshold = timedelta(minutes=idle_threshold_minutes)

    def init_if_needed(self, bach_root: Path) -> bool:
        """
        Lazy Initialisierung: Prüft ob Session-Init nötig ist.

        Wird beim ersten CLI-Befehl aufgerufen. Initialisiert:
        - system_activity Singleton-Zeile
        - session_id falls nicht gesetzt

        Args:
            bach_root: BACH Root-Verzeichnis

        Returns:
            True wenn initialisiert wurde, False wenn bereits initialisiert
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # 1. Prüfen ob system_activity Tabelle existiert
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='system_activity'
                """)
                if not cursor.fetchone():
                    # Tabelle fehlt - Migration nötig, aber nicht hier crashen
                    print("[INFO] system_activity Tabelle fehlt - Migration empfohlen")
                    return False

                # 2. Prüfen ob Singleton-Zeile existiert
                cursor = conn.execute("SELECT id, session_id FROM system_activity WHERE id = 1")
                row = cursor.fetchone()

                if not row:
                    # Singleton-Zeile erstellen
                    now = datetime.now().isoformat()
                    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

                    conn.execute("""
                        INSERT INTO system_activity (id, session_id, last_activity, created_at, updated_at)
                        VALUES (1, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (session_id, now))
                    conn.commit()

                    print(f"[INFO] Session initialisiert: {session_id}")
                    return True

                # 3. Bereits initialisiert
                session_id = row[1]
                if session_id:
                    # Session läuft bereits
                    return False
                else:
                    # session_id fehlt - setzen
                    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    conn.execute("""
                        UPDATE system_activity
                        SET session_id = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                    """, (session_id,))
                    conn.commit()

                    print(f"[INFO] Session-ID gesetzt: {session_id}")
                    return True

            finally:
                conn.close()
        except Exception as e:
            # Graceful Degradation: Bei Fehlern nicht crashen
            print(f"[WARN] init_if_needed() fehlgeschlagen: {e}")
            return False

    def tick(self, session_id: Optional[str] = None):
        """
        Activity-Tick: Aktualisiert last_activity Timestamp.

        Wird bei jedem CLI-Befehl aufgerufen.

        Args:
            session_id: Aktuelle Session-ID (optional)
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Graceful Degradation: Prüfen ob Tabelle existiert
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='system_activity'
                """)
                if not cursor.fetchone():
                    # Tabelle fehlt - nichts tun, kein Crash
                    return

                now = datetime.now().isoformat()
                conn.execute("""
                    UPDATE system_activity
                    SET last_activity = ?, session_id = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (now, session_id))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            # Graceful Degradation: Bei DB-Fehlern nicht crashen
            pass

    def check_idle_and_finalize(self, bach_root: Path) -> bool:
        """
        Prüft ob Idle-Schwelle überschritten und finalisiert bei Bedarf.

        Returns:
            True wenn finalisiert wurde, False sonst
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Graceful Degradation: Prüfen ob Tabelle existiert
                check_cursor = conn.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='system_activity'
                """)
                if not check_cursor.fetchone():
                    # Tabelle fehlt - nichts tun
                    return False

                cursor = conn.execute("SELECT last_activity FROM system_activity WHERE id = 1")
                row = cursor.fetchone()

                if not row:
                    return False

                last_activity = datetime.fromisoformat(row[0])
                now = datetime.now()
                idle_time = now - last_activity

                if idle_time > self.idle_threshold:
                    # Idle-Schwelle überschritten → Finalisieren
                    print(f"\n[INFO] Inaktivität erkannt ({idle_time.seconds // 60} Min)")
                    print("[INFO] Finalisiere Session...")

                    try:
                        # SQ022: Directory-Truth vor Finalisierung aktualisieren
                        self.update_directory_truth(bach_root)

                        from hub.shutdown import ShutdownHandler
                        # ShutdownHandler erwartet SYSTEM_ROOT
                        system_root = bach_root / "system" if (bach_root / "system").exists() else bach_root
                        shutdown = ShutdownHandler(system_root)
                        success, msg = shutdown._complete("Auto-Finalize (Inaktivität)", dry_run=False)

                        if success:
                            print("[OK] Session finalisiert")

                            # SQ071: Spiegel-Dateien exportieren
                            self._export_mirrors(bach_root)

                            # SQ065: Tages-Log erstellen
                            self._write_daily_log(bach_root)
                            return True
                        else:
                            print(f"[WARN] Finalisierung fehlgeschlagen: {msg}")
                            return False
                    except Exception as e:
                        print(f"[ERROR] Finalisierung fehlgeschlagen: {e}")
                        return False

                return False
            finally:
                conn.close()
        except Exception:
            # Graceful Degradation: Bei DB-Fehlern nicht crashen
            return False

    def check_eod_and_finalize(self, bach_root: Path, eod_hour: int = 23) -> bool:
        """
        Prüft ob EOD-Zeit (End-of-Day) erreicht ist und finalisiert bei Bedarf.

        EOD-Timer: Finalisiert automatisch um 23:00 Uhr (oder custom eod_hour).
        Finalisierung erfolgt nur einmal pro Tag (via eod_finalized_today Flag).

        Args:
            bach_root: BACH Root-Verzeichnis
            eod_hour: Stunde für EOD-Finalisierung (0-23, default: 23)

        Returns:
            True wenn finalisiert wurde, False sonst
        """
        try:
            now = datetime.now()

            # Prüfen ob EOD-Zeit erreicht (nach eod_hour:00 Uhr)
            if now.hour < eod_hour:
                return False

            conn = sqlite3.connect(str(self.db_path))
            try:
                # Graceful Degradation: Prüfen ob Tabelle existiert
                check_cursor = conn.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='system_activity'
                """)
                if not check_cursor.fetchone():
                    return False

                # Prüfen ob heute bereits finalisiert wurde
                cursor = conn.execute("""
                    SELECT eod_finalized_today, last_eod_finalize
                    FROM system_activity
                    WHERE id = 1
                """)
                row = cursor.fetchone()

                if not row:
                    return False

                eod_finalized_today = row[0] if row[0] is not None else 0
                last_eod_finalize = row[1]

                # Wenn bereits heute finalisiert, nichts tun
                if eod_finalized_today == 1 and last_eod_finalize:
                    last_eod_date = datetime.fromisoformat(last_eod_finalize).date()
                    if last_eod_date == now.date():
                        # Bereits heute finalisiert
                        return False

                # EOD-Finalisierung durchführen
                print(f"\n[INFO] EOD-Zeit erreicht ({eod_hour}:00 Uhr)")
                print("[INFO] Finalisiere Tages-Session...")

                try:
                    # SQ043: Memory-Decay Hook (Auto-Cleanup bei EOD)
                    try:
                        from tools.memory_decay import MemoryDecay
                        decay = MemoryDecay(self.db_path)
                        # Nur facts decay (lessons/working haben längere Intervalle)
                        result = decay.apply_decay_to_facts(dry_run=False)
                        decay_count = result.get('decayed_facts', 0)
                        if decay_count > 0:
                            print(f"[INFO] Memory-Decay: {decay_count} Facts verblasst")
                    except Exception as e:
                        print(f"[WARNUNG] Memory-Decay Hook fehlgeschlagen: {e}")

                    # SQ022: Directory-Truth vor Finalisierung aktualisieren
                    self.update_directory_truth(bach_root)

                    from hub.shutdown import ShutdownHandler
                    # ShutdownHandler erwartet SYSTEM_ROOT
                    system_root = bach_root / "system" if (bach_root / "system").exists() else bach_root
                    shutdown = ShutdownHandler(system_root)
                    success, msg = shutdown._complete(f"Auto-Finalize (EOD {eod_hour}:00)", dry_run=False)

                    if success:
                        print("[OK] EOD-Finalisierung erfolgreich")

                        # Flag setzen + Timestamp aktualisieren
                        conn.execute("""
                            UPDATE system_activity
                            SET eod_finalized_today = 1,
                                last_eod_finalize = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        """, (now.isoformat(),))
                        conn.commit()

                        # Tages-Log schreiben
                        self._write_daily_log(bach_root)
                        return True
                    else:
                        print(f"[WARN] EOD-Finalisierung fehlgeschlagen: {msg}")
                        return False
                except Exception as e:
                    print(f"[ERROR] EOD-Finalisierung fehlgeschlagen: {e}")
                    return False

            finally:
                conn.close()
        except Exception:
            # Graceful Degradation
            return False

    def _write_daily_log(self, bach_root: Path):
        """
        Schreibt Tages-Log YYYY-MM-DD.md (SQ065).

        Format: Append-only Log mit Session-Zusammenfassung.
        Speicherort: system/data/logs/daily/YYYY-MM-DD.md
        """
        try:
            # Log-Verzeichnis erstellen
            daily_log_dir = bach_root / "system" / "data" / "logs" / "daily"
            daily_log_dir.mkdir(parents=True, exist_ok=True)

            # Dateiname: YYYY-MM-DD.md
            today = datetime.now().strftime("%Y-%m-%d")
            log_file = daily_log_dir / f"{today}.md"

            # Session-Informationen aus DB holen
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute("""
                    SELECT session_id, started_at, ended_at, summary,
                           tasks_created, tasks_completed
                    FROM memory_sessions
                    WHERE DATE(started_at) = DATE('now', 'localtime')
                      AND ended_at IS NOT NULL
                    ORDER BY id DESC
                """)
                sessions = cursor.fetchall()
            finally:
                conn.close()

            # Log-Eintrag erstellen
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"\n## Session finalisiert: {timestamp}\n\n"

            if sessions:
                for session_id, started_at, ended_at, summary, tasks_created, tasks_completed in sessions:
                    entry += f"- **Session**: {session_id}\n"
                    entry += f"- **Zeitraum**: {started_at} bis {ended_at}\n"
                    entry += f"- **Tasks**: {tasks_completed}/{tasks_created} erledigt\n"
                    if summary:
                        entry += f"- **Zusammenfassung**: {summary}\n"
                    entry += "\n"
            else:
                entry += "- Keine Sessions heute gefunden\n\n"

            # Append-only: An Log-Datei anhängen
            with log_file.open('a', encoding='utf-8') as f:
                # Header nur bei neuer Datei
                if log_file.stat().st_size == 0:
                    f.write(f"# Tages-Log: {today}\n\n")
                    f.write("Auto-generiertes Log der Session-Finalisierungen.\n\n")

                f.write(entry)

            print(f"[TAGES-LOG] {log_file.name} aktualisiert")

        except Exception as e:
            # Nicht kritisch, nur loggen
            print(f"[WARN] Tages-Log konnte nicht geschrieben werden: {e}")

    def carry_over(self, from_session_id: str, to_session_id: str) -> bool:
        """
        Session-Carry-Over: Übergibt wichtige Daten von alter zu neuer Session (SQ022).

        Übergibt:
        - Offene Tasks (status != 'done')
        - Continuation Context aus memory_sessions
        - Aktive Warnungen (notifications mit severity >= warning)
        - Lessons mit hoher Severity (severity >= critical)

        Args:
            from_session_id: Vorherige Session-ID
            to_session_id: Neue Session-ID

        Returns:
            True wenn Carry-Over erfolgreich, False bei Fehler
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # 1. Hole Continuation Context aus vorheriger Session
                cursor = conn.execute("""
                    SELECT continuation_context
                    FROM memory_sessions
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                """, (from_session_id,))
                row = cursor.fetchone()
                continuation_context = row[0] if row and row[0] else ""

                # 2. Hole offene Tasks
                cursor = conn.execute("""
                    SELECT id, title, description, priority
                    FROM tasks
                    WHERE session_id = ?
                      AND status != 'done'
                      AND status != 'cancelled'
                """, (from_session_id,))
                open_tasks = cursor.fetchall()

                # 3. Hole aktive Warnungen
                cursor = conn.execute("""
                    SELECT id, title, message, severity
                    FROM notifications
                    WHERE session_id = ?
                      AND severity IN ('warning', 'critical', 'error')
                      AND dismissed_at IS NULL
                """, (from_session_id,))
                active_warnings = cursor.fetchall()

                # 4. Hole kritische Lessons
                cursor = conn.execute("""
                    SELECT id, content, category, severity
                    FROM memory_lessons
                    WHERE session_id = ?
                      AND severity IN ('critical', 'high')
                """, (from_session_id,))
                critical_lessons = cursor.fetchall()

                # 5. Carry-Over-Bericht erstellen
                carryover_report = []
                carryover_report.append(f"# Session Carry-Over Report")
                carryover_report.append(f"")
                carryover_report.append(f"**Von Session**: {from_session_id}")
                carryover_report.append(f"**Zu Session**: {to_session_id}")
                carryover_report.append(f"**Zeitpunkt**: {datetime.now().isoformat()}")
                carryover_report.append(f"")

                if open_tasks:
                    carryover_report.append(f"## Offene Tasks ({len(open_tasks)})")
                    carryover_report.append(f"")
                    for task_id, title, description, priority in open_tasks:
                        carryover_report.append(f"- **Task #{task_id}**: {title} (Priorität: {priority})")
                    carryover_report.append(f"")
                    # Tasks zu neuer Session übertragen
                    conn.execute("""
                        UPDATE tasks
                        SET session_id = ?
                        WHERE session_id = ?
                          AND status != 'done'
                          AND status != 'cancelled'
                    """, (to_session_id, from_session_id))

                if active_warnings:
                    carryover_report.append(f"## Aktive Warnungen ({len(active_warnings)})")
                    carryover_report.append(f"")
                    for notif_id, title, message, severity in active_warnings:
                        carryover_report.append(f"- **{severity.upper()}**: {title}")
                    carryover_report.append(f"")
                    # Warnungen zu neuer Session übertragen
                    conn.execute("""
                        UPDATE notifications
                        SET session_id = ?
                        WHERE session_id = ?
                          AND severity IN ('warning', 'critical', 'error')
                          AND dismissed_at IS NULL
                    """, (to_session_id, from_session_id))

                if critical_lessons:
                    carryover_report.append(f"## Kritische Lessons ({len(critical_lessons)})")
                    carryover_report.append(f"")
                    for lesson_id, content, category, severity in critical_lessons:
                        carryover_report.append(f"- **{severity}** ({category}): {content[:80]}...")
                    carryover_report.append(f"")

                if continuation_context:
                    carryover_report.append(f"## Continuation Context")
                    carryover_report.append(f"")
                    carryover_report.append(continuation_context)
                    carryover_report.append(f"")

                # 6. Carry-Over-Bericht speichern als Notiz in neuer Session
                report_text = "\n".join(carryover_report)
                conn.execute("""
                    INSERT INTO memory_working (partner, priority, content, context_type, created_at)
                    VALUES ('system', 0, ?, 'carryover', CURRENT_TIMESTAMP)
                """, (report_text,))

                # 7. Commit
                conn.commit()

                print(f"\n[CARRY-OVER] Session-Übergabe erfolgreich")
                print(f"  Offene Tasks: {len(open_tasks)}")
                print(f"  Aktive Warnungen: {len(active_warnings)}")
                print(f"  Kritische Lessons: {len(critical_lessons)}")
                print(f"  Continuation Context: {'Ja' if continuation_context else 'Nein'}")

                return True

            finally:
                conn.close()

        except Exception as e:
            print(f"[ERROR] Session-Carry-Over fehlgeschlagen: {e}")
            return False

    def apply_healing(self, bach_root: Path) -> bool:
        """
        Wendet Heilungsmodus auf System an (SQ022 Pfadfreiheit & Heilung).

        Liest healing.mode aus system_config und führt entsprechende Heilung aus:
        - 'adapt': System passt sich an neue Pfade an (Standard)
        - 'restore_paths': System versucht Pfade wiederherzustellen
        - 'restore_full': Vollständige Wiederherstellung aus Backup
        - 'ask': Fragt User vor Heilung (Default)
        - 'off': Keine automatische Heilung

        Args:
            bach_root: BACH Root-Verzeichnis

        Returns:
            True wenn Heilung erfolgreich, False sonst
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # 1. Healing-Modus aus system_config lesen
                cursor = conn.execute(
                    "SELECT value FROM system_config WHERE key = 'healing.mode'"
                )
                row = cursor.fetchone()
                healing_mode = row[0] if row else 'ask'

                if healing_mode == 'off':
                    return True  # Keine Heilung gewünscht

                # 2. Auto-Detect-Moves prüfen
                cursor = conn.execute(
                    "SELECT value FROM system_config WHERE key = 'healing.auto_detect_moves'"
                )
                row = cursor.fetchone()
                auto_detect = row[0] if row and row[0] == '1' else False

                # 3. Path Healer aufrufen (wenn nicht 'ask' oder User bestätigt)
                should_heal = healing_mode != 'ask'

                if healing_mode == 'ask':
                    # TODO: User-Dialog (für jetzt: automatisch heilen)
                    should_heal = True
                    print("[HEALING] Modus 'ask' - Auto-Healing aktiviert (Dialog TODO)")

                if should_heal:
                    print(f"[HEALING] Modus '{healing_mode}' - Starte Heilung...")

                    # Path Healer importieren und ausführen
                    try:
                        import sys
                        maintenance_path = bach_root / "system" / "tools" / "maintenance"
                        if str(maintenance_path) not in sys.path:
                            sys.path.insert(0, str(maintenance_path))

                        from path_healer import BachPathHealer

                        healer = BachPathHealer(str(bach_root))

                        # Je nach Modus: dry-run oder echte Heilung
                        dry_run = healing_mode == 'ask'
                        report = healer.heal_all(dry_run=dry_run, skip_backup=False)

                        print(f"[HEALING] Fertig - {report['files_healed']} Dateien geheilt")

                        # Backup aufräumen bei Erfolg
                        if report['files_healed'] > 0 and report['errors'] == 0:
                            healer.cleanup_safety_backup()

                        return True

                    except ImportError as e:
                        print(f"[WARN] Path Healer nicht verfügbar: {e}")
                        return False

                return True

            finally:
                conn.close()

        except Exception as e:
            print(f"[ERROR] Healing fehlgeschlagen: {e}")
            return False

    def update_directory_truth(self, bach_root: Path) -> bool:
        """
        Aktualisiert directory_truth.json mit aktuellen Pfaden (SQ022 Pfadfreiheit).

        Diese Datei dient als "Wahrheitsquelle" für korrekte Pfade. Bei finalize()
        werden alle aktuellen Pfade erfasst und gespeichert. Bei restore_paths kann
        das System auf diese Wahrheit zurückgreifen.

        Args:
            bach_root: BACH Root-Verzeichnis

        Returns:
            True wenn Update erfolgreich, False sonst
        """
        try:
            truth_file = bach_root / "system" / "data" / "config" / "directory_truth.json"

            # 1. Bestehende Truth laden (oder Template)
            if truth_file.exists():
                with open(truth_file, 'r', encoding='utf-8') as f:
                    truth = json.load(f)
            else:
                truth = {
                    "_comment": "BACH Directory Truth - Referenz für korrekte Pfade (SQ022)",
                    "_version": "1.0.0",
                    "_auto_generated": True,
                    "paths": {},
                    "absolute_paths": {},
                    "last_finalize": None
                }

            # 2. Aktuelle Pfade erfassen (relativ zu bach_root)
            key_paths = {
                "bach_root": bach_root,
                "system": bach_root / "system",
                "data": bach_root / "system" / "data",
                "config": bach_root / "system" / "data" / "config",
                "backups": bach_root / "system" / "data" / "backups",
                "logs": bach_root / "system" / "data" / "logs",
                "exports": bach_root / "system" / "exports",
                "hub": bach_root / "system" / "hub",
                "tools": bach_root / "system" / "tools",
                "agents": bach_root / "system" / "agents",
                "connectors": bach_root / "system" / "connectors",
                "partners": bach_root / "system" / "partners",
                "skills": bach_root / "system" / "skills",
                "docs": bach_root / "system" / "docs",
                "help": bach_root / "system" / "docs" / "help",
                "wiki": bach_root / "system" / "wiki",
                "user": bach_root / "user",
                "workspace": bach_root / "workspace"
            }

            # 3. Relative Pfade (zu bach_root) speichern
            truth["paths"] = {}
            truth["absolute_paths"] = {}

            for key, path in key_paths.items():
                try:
                    # Relativ zu bach_root
                    if key == "bach_root":
                        truth["paths"][key] = "."
                    else:
                        rel_path = path.relative_to(bach_root)
                        truth["paths"][key] = str(rel_path).replace("\\", "/")

                    # Absolut
                    truth["absolute_paths"][key] = str(path.resolve()).replace("\\", "/")

                except ValueError:
                    # Pfad ist nicht relativ zu bach_root (sollte nicht passieren)
                    truth["absolute_paths"][key] = str(path.resolve()).replace("\\", "/")

            # 4. Metadaten aktualisieren
            truth["_updated_at"] = datetime.now().isoformat()
            truth["last_finalize"] = datetime.now().isoformat()

            # 5. Speichern
            truth_file.parent.mkdir(parents=True, exist_ok=True)
            with open(truth_file, 'w', encoding='utf-8') as f:
                json.dump(truth, f, indent=2, ensure_ascii=False)

            print(f"[DIRECTORY-TRUTH] Updated: {truth_file.name}")
            return True

        except Exception as e:
            print(f"[ERROR] Directory-Truth-Update fehlgeschlagen: {e}")
            return False

    def _export_mirrors(self, bach_root: Path) -> bool:
        """
        Exportiert Spiegel-Dateien (SQ071).

        5 Spiegel-Dateien werden aus DB generiert:
        - AGENTS.md
        - PARTNERS.md
        - USECASES.md
        - CHAINS.md
        - WORKFLOWS.md

        Args:
            bach_root: BACH Root-Verzeichnis

        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        try:
            import importlib
            import sys

            system_root = bach_root / "system" if (bach_root / "system").exists() else bach_root
            root_path = system_root.parent if system_root.name == "system" else bach_root
            tools_dir = system_root / "tools"
            if str(tools_dir) not in sys.path:
                sys.path.insert(0, str(tools_dir))

            exporters = [
                ("agents_export", "AgentsExporter"),
                ("partners_export", "PartnersExporter"),
                ("usecases_export", "UsecasesExporter"),
                ("chains_export", "ChainsExporter"),
                ("workflows_export", "WorkflowsExporter"),
            ]

            success_count = 0
            for module_name, class_name in exporters:
                try:
                    module = importlib.import_module(module_name)
                    exporter_cls = getattr(module, class_name)
                    success, _msg = exporter_cls(root_path).generate()
                    if success:
                        success_count += 1
                except Exception:
                    # Export-Fehler ignorieren
                    pass  # Graceful Degradation

            print(f"[MIRRORS] {success_count}/5 Spiegel-Dateien exportiert")
            return success_count > 0

        except Exception as e:
            print(f"[ERROR] Spiegel-Export fehlgeschlagen: {e}")
            # Graceful Degradation: Export-Fehler nicht crashen lassen
            return False


# ═══════════════════════════════════════════════════════════════════════════
# Integration in bach.py
# ═══════════════════════════════════════════════════════════════════════════
#
# Hinzufügen VOR Handler-Dispatch (nach Argument-Parsing):
#
#   from tools.activity_tracker import ActivityTracker
#
#   # Lazy Init + Idle-Check + Activity-Tick (außer bei --startup/--shutdown)
#   if not args.startup and not args.shutdown:
#       tracker = ActivityTracker(DB_PATH, idle_threshold_minutes=30)
#       tracker.init_if_needed(BACH_ROOT)  # Lazy Start (SQ022)
#       tracker.check_idle_and_finalize(BACH_ROOT)
#       tracker.tick(session_id=None)  # TODO: session_id aus startup.py holen
#
# ═══════════════════════════════════════════════════════════════════════════
