# SPDX-License-Identifier: MIT
"""
Shutdown Handler - Session beenden (DB-basiert)
================================================

Speichert Session-Bericht in memory_sessions.
Kein Markdown-Dateisystem mehr!

NEU v1.1.15: Auto-Memory Fallback - generiert Summary aus Autolog wenn Claude vergisst
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from .base import BaseHandler


class ShutdownHandler(BaseHandler):
    """Handler fuer --shutdown - DB-basiert"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "shutdown"
    
    @property
    def target_file(self) -> Path:
        return self.db_path
    
    def get_operations(self) -> dict:
        return {
            "complete": "Komplett mit Dir-Scan + Session-Speicherung (Standard)",
            "quick": "Schnell ohne Dir-Scan",
            "emergency": "Notfall - nur Working Memory sichern"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        # Partner aus Args extrahieren BEVOR Summary gebildet wird
        partner_id = "user"
        clean_args = []
        for arg in args:
            if arg.startswith("--partner="):
                partner_id = arg.split("=", 1)[1].lower()
            else:
                clean_args.append(arg)

        summary = " ".join(clean_args) if clean_args else None
        args = clean_args
        
        # Clock-Out bei Shutdown (v1.1.71)
        if not dry_run:
            try:
                self._clock_out_partner(partner_id)
            except Exception:
                pass  # Silent fail

        # Hook: before_shutdown
        try:
            from core.hooks import hooks
            hooks.emit('before_shutdown', {
                'partner': partner_id, 'mode': operation or 'complete'
            })
        except Exception:
            pass

        if operation == "emergency":
            success, message = self._emergency(summary, dry_run)
        elif operation == "quick":
            success, message = self._quick(summary, dry_run)
        else:
            success, message = self._complete(summary, dry_run)

        # Hook: after_shutdown (re-import to avoid scope issue)
        try:
            from core.hooks import hooks as _hooks
            _hooks.emit('after_shutdown', {
                'partner': partner_id, 'mode': operation or 'complete',
                'success': success
            })
        except Exception:
            pass

        return success, message
    
    def _get_conn(self):
        return sqlite3.connect(self.db_path)
    
    def _clock_out_partner(self, partner_id: str) -> bool:
        """Stempelt Partner aus (partner_presence Tabelle)."""
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute("""
                UPDATE partner_presence
                SET status = 'offline', clocked_out = ?, updated_at = ?
                WHERE partner_name = ? AND status = 'online'
            """, (now, now, partner_id))
            conn.commit()
        finally:
            conn.close()
        return True
    
    def _get_active_session(self, conn) -> tuple:
        """Findet aktive Session (ohne ended_at)."""
        row = conn.execute("""
            SELECT id, session_id, started_at, tasks_created 
            FROM memory_sessions 
            WHERE ended_at IS NULL 
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        return row
    
    def _generate_fallback_summary(self, session_start: str) -> str:
        """
        Generiert automatische Zusammenfassung aus Autolog.
        
        Wird aufgerufen wenn Claude keinen Session-Bericht mitgibt.
        Liest Autolog-Eintraege seit Session-Start und extrahiert Befehle.
        
        Returns:
            str: Automatisch generierte Zusammenfassung oder None
        """
        autolog_path = self.base_path / "data" / "logs" / "auto_log_extended.txt"
        
        if not autolog_path.exists():
            return None
        
        try:
            # Session-Start parsen
            start_time = datetime.fromisoformat(session_start.replace('Z', '+00:00'))
            
            # Autolog lesen
            with open(autolog_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            # Befehle sammeln seit Session-Start
            commands = []
            for line in lines:
                # Format: [HH:MM:SS] CMD: befehl
                if 'CMD:' in line:
                    # Zeit extrahieren (erste 10 Zeichen: [HH:MM:SS])
                    try:
                        time_str = line[1:9]  # HH:MM:SS
                        today = datetime.now().date()
                        line_time = datetime.strptime(f"{today} {time_str}", "%Y-%m-%d %H:%M:%S")
                        
                        if line_time >= start_time:
                            # Befehl extrahieren
                            cmd_part = line.split('CMD:')[1].strip()
                            if cmd_part and cmd_part not in ['startup', 'shutdown']:
                                commands.append(cmd_part)
                    except (ValueError, IndexError):
                        continue
            
            if not commands:
                return "[AUTO] Keine Befehle in dieser Session"
            
            # Zusammenfassung generieren
            unique_commands = list(dict.fromkeys(commands))  # Duplikate entfernen, Reihenfolge behalten
            summary_parts = []
            summary_parts.append("[AUTO-FALLBACK]")
            summary_parts.append(f"Befehle: {len(commands)} ({len(unique_commands)} unique)")
            
            # Top 5 Befehle zeigen
            for cmd in unique_commands[:5]:
                summary_parts.append(f"- {cmd[:60]}")
            
            if len(unique_commands) > 5:
                summary_parts.append(f"... und {len(unique_commands) - 5} weitere")
            
            return " | ".join(summary_parts[:2]) + " || " + ", ".join(unique_commands[:3])
            
        except Exception as e:
            return f"[AUTO-ERROR] {str(e)[:50]}"
    
    def _emergency(self, summary: str, dry_run: bool) -> tuple:
        """Notfall-Shutdown - nur Status sichern."""
        results = []
        results.append("=" * 55)
        results.append("         EMERGENCY SHUTDOWN")
        results.append("=" * 55)
        
        if not dry_run:
            conn = self._get_conn()
            try:
                now = datetime.now().isoformat()
                # Notiz in Working Memory
                conn.execute("""
                    INSERT INTO memory_working (type, content, priority, created_at, updated_at, is_active)
                    VALUES ('emergency', ?, 10, ?, ?, 1)
                """, (f"EMERGENCY SHUTDOWN: {summary or 'Keine Details'}", now, now))
                conn.commit()
                results.append(" [OK] Emergency-Notiz gespeichert")
            except Exception as e:
                results.append(f" [ERROR] {e}")
            finally:
                conn.close()
        else:
            results.append(" [DRY-RUN] Wuerde Emergency-Notiz speichern")
        
        results.append("")
        results.append(" Session ABGEBROCHEN")
        results.append("=" * 55)
        
        return True, "\n".join(results)
    
    def _quick(self, summary: str, dry_run: bool) -> tuple:
        """Schnell-Shutdown ohne Dir-Scan."""
        results = []
        results.append("=" * 55)
        results.append("            QUICK SHUTDOWN")
        results.append("=" * 55)
        
        if not dry_run and summary:
            conn = self._get_conn()
            try:
                now = datetime.now().isoformat()
                conn.execute("""
                    INSERT INTO memory_working (type, content, created_at, updated_at, is_active)
                    VALUES ('note', ?, ?, ?, 1)
                """, (f"Quick-Shutdown: {summary}", now, now))
                conn.commit()
                results.append(f" [OK] Notiz: {summary[:40]}...")
            except Exception as e:
                results.append(f" [WARN] {e}")
            finally:
                conn.close()
        
        results.append(" [OK] Session pausiert")
        results.append("=" * 55)
        
        return True, "\n".join(results)
    
    def _complete(self, summary: str, dry_run: bool) -> tuple:
        """Komplett-Shutdown mit Dir-Scan und Session-Speicherung."""
        results = []
        now = datetime.now()
        
        results.append("=" * 55)
        results.append("          COMPLETE SHUTDOWN")
        results.append("=" * 55)
        results.append(f" Zeit: {now.strftime('%Y-%m-%d %H:%M')}")
        results.append("=" * 55)
        
        # 1. Directory-Scan Update
        results.append("")
        results.append("[DIRECTORY SCAN]")
        change_count = 0
        if not dry_run:
            try:
                from tools.dirscan import DirectoryScanner
                scanner = DirectoryScanner(self.base_path)
                scan_result = scanner.shutdown_update()
                results.append(f" {scan_result}")
                # Aenderungen zaehlen fuer Auto-Snapshot
                if hasattr(scanner, 'last_change_count'):
                    change_count = scanner.last_change_count
                else:
                    # Fallback: Aus Text schaetzen
                    import re
                    # Suche nach "(X Änderungen" oder "X neu" oder "X geaendert"
                    match = re.search(r'(\d+)\s*(?:Änderung|aenderung|neu|geaendert|geloescht)', scan_result.lower())
                    if match:
                        change_count = int(match.group(1))
                    else:
                        # Alternative: Suche nach "X Änderungen übernommen"
                        match2 = re.search(r'\((\d+)\s*(?:Änderung|änderung)', scan_result)
                        if match2:
                            change_count = int(match2.group(1))
            except Exception as e:
                results.append(f" [SKIP] {e}")
        else:
            results.append(" [DRY-RUN] Wuerde SOLL-Zustand aktualisieren")
        
        # 1b. Auto-Snapshot bei grossen Aenderungen (NEU v1.1.17)
        results.append("")
        results.append("[AUTO-SNAPSHOT]")
        if not dry_run and change_count >= 3:
            try:
                from .snapshot import SnapshotHandler
                snap_handler = SnapshotHandler(self.base_path)
                snap_name = f"auto_{now.strftime('%Y%m%d_%H%M%S')}"
                success, snap_msg = snap_handler._create(snap_name, dry_run=False)
                if success:
                    results.append(f" [OK] Auto-Snapshot erstellt ({change_count} Aenderungen)")
                else:
                    results.append(f" [SKIP] {snap_msg}")
            except Exception as e:
                results.append(f" [SKIP] Auto-Snapshot: {e}")
        elif not dry_run:
            results.append(f" [SKIP] Nur {change_count} Aenderungen (Schwelle: 3)")
        else:
            results.append(" [DRY-RUN] Wuerde Auto-Snapshot pruefen")
        
        # 2. Session in DB speichern
        results.append("")
        results.append("[SESSION SPEICHERN]")
        if not dry_run:
            conn = self._get_conn()
            try:
                # Aktive Session finden oder neue erstellen
                active = self._get_active_session(conn)
                
                # NEU v1.1.15: Auto-Memory Fallback
                if not summary and active:
                    session_start = active[2] if active else now.isoformat()
                    summary = self._generate_fallback_summary(session_start)
                    if summary:
                        results.append(f" [FALLBACK] Auto-Summary aus Autolog generiert")
                
                if active:
                    # Bestehende Session abschliessen
                    session_id = active[1]
                    conn.execute("""
                        UPDATE memory_sessions 
                        SET ended_at = ?, summary = COALESCE(summary, '') || ?
                        WHERE session_id = ?
                    """, (now.isoformat(), f"\n{summary}" if summary else "", session_id))
                    results.append(f" [OK] Session {session_id} abgeschlossen")
                else:
                    # Falls keine aktive Session, trotzdem Notiz speichern
                    if summary:
                        session_id = f"session_{now.strftime('%Y%m%d_%H%M%S')}"
                        conn.execute("""
                            INSERT INTO memory_sessions 
                            (session_id, started_at, ended_at, summary, tasks_created, tasks_completed)
                            VALUES (?, ?, ?, ?, 0, 0)
                        """, (session_id, now.isoformat(), now.isoformat(), summary))
                        results.append(f" [OK] Session {session_id} erstellt")
                    else:
                        results.append(" [SKIP] Keine aktive Session")
                
                conn.commit()
            except Exception as e:
                results.append(f" [ERROR] {e}")
            finally:
                conn.close()
        else:
            results.append(" [DRY-RUN] Wuerde Session speichern")
        
        # 3. Working Memory Stats
        results.append("")
        results.append("[MEMORY STATUS]")
        if not dry_run:
            conn = self._get_conn()
            try:
                working = conn.execute("SELECT COUNT(*) FROM memory_working WHERE is_active=1").fetchone()[0]
                facts = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
                sessions = conn.execute("SELECT COUNT(*) FROM memory_sessions").fetchone()[0]
                results.append(f" Working: {working} | Facts: {facts} | Sessions: {sessions}")
            except Exception as e:
                results.append(f" [ERROR] {e}")
            finally:
                conn.close()
        
        # 4. Task-Statistik (NEU v1.1.8)
        results.append("")
        results.append("[TASK-STATISTIK]")
        tasks_created = 0
        tasks_completed = 0
        if not dry_run:
            conn = self._get_conn()
            try:
                # Aktive Session finden fuer Zeitraum
                active = self._get_active_session(conn)
                session_start = active[2] if active else now.replace(hour=0, minute=0).isoformat()
                
                # Tasks aus bach.db zaehlen (tasks-Tabelle)
                # Erstellt in dieser Session
                tasks_created = conn.execute("""
                    SELECT COUNT(*) FROM tasks 
                    WHERE created_at >= ?
                """, (session_start,)).fetchone()[0]
                
                # Erledigt in dieser Session
                tasks_completed = conn.execute("""
                    SELECT COUNT(*) FROM tasks 
                    WHERE status = 'done' AND completed_at >= ?
                """, (session_start,)).fetchone()[0]
                
                results.append(f" +{tasks_created} erstellt, {tasks_completed} erledigt (diese Session)")
                
                # Zaehler in memory_sessions aktualisieren
                if active:
                    conn.execute("""
                        UPDATE memory_sessions 
                        SET tasks_created = ?, tasks_completed = ?
                        WHERE session_id = ?
                    """, (tasks_created, tasks_completed, active[1]))
                    conn.commit()
            except Exception as e:
                results.append(f" [SKIP] {e}")
            finally:
                conn.close()
        else:
            results.append(" [DRY-RUN] Wuerde Task-Statistik zaehlen")
        
        # 5. Auto-Komprimierung (v2.0: cleanup + compress bei Shutdown)
        results.append("")
        results.append("[KONSOLIDIERUNG]")
        if not dry_run:
            conn = self._get_conn()
            try:
                # Leere Sessions zaehlen und aufraemen
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM memory_sessions
                    WHERE (summary IS NULL OR summary = '' OR summary LIKE '%AUTO-CLOSED%'
                           OR length(summary) <= 50)
                    AND (is_compressed = 0 OR is_compressed IS NULL)
                """)
                empty_count = cursor.fetchone()[0]

                if empty_count > 0:
                    conn.execute("""
                        UPDATE memory_sessions
                        SET is_compressed = 1,
                            summary = CASE
                                WHEN summary IS NULL OR summary = '' THEN '[CLEANUP: Leere Session]'
                                ELSE summary
                            END
                        WHERE (summary IS NULL OR summary = '' OR summary LIKE '%AUTO-CLOSED%'
                               OR length(summary) <= 50)
                        AND (is_compressed = 0 OR is_compressed IS NULL)
                    """)
                    conn.commit()
                    results.append(f" [CLEANUP] {empty_count} leere Sessions bereinigt")

                # Komprimierbare Sessions zaehlen
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM memory_sessions
                    WHERE (is_compressed = 0 OR is_compressed IS NULL)
                    AND summary IS NOT NULL AND summary != ''
                    AND length(summary) > 50
                    AND summary NOT LIKE '%AUTO-CLOSED%'
                    AND summary NOT LIKE '%CLEANUP%'
                """)
                compressible = cursor.fetchone()[0]

                if compressible > 0:
                    # Context Compressor ausfuehren
                    import sys
                    tools_dir = self.base_path / "tools"
                    if str(tools_dir) not in sys.path:
                        sys.path.insert(0, str(tools_dir))
                    try:
                        from context_compressor import SessionCompressor, CompressionRules
                        sc = SessionCompressor(self.db_path, CompressionRules())
                        success, msg = sc.compress_and_store(fmt="structured", dry_run=False)
                        results.append(f" [COMPRESS] {compressible} Sessions komprimiert")
                    except Exception as e:
                        results.append(f" [WARN] Komprimierung fehlgeschlagen: {e}")
                else:
                    results.append(" [OK] Keine offenen Sessions")
            except Exception as e:
                results.append(f" [SKIP] {e}")
            finally:
                conn.close()
        else:
            results.append(" [DRY-RUN] Wuerde Sessions komprimieren")

        # ══════════════════════════════════════════════════════════════
        # 5.5 MEMORY SYNC - MEMORY.md generieren (SQ065)
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            try:
                import sys
                tools_dir = str(self.base_path / "tools")
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from memory_sync import MemorySync

                bach_root = self.base_path.parent
                sync = MemorySync(bach_root)
                success, msg = sync.generate(partner="user", project="BACH")

                if success:
                    results.append("")
                    results.append("[MEMORY SYNC]")
                    results.append(f" {msg}")
            except Exception as e:
                pass  # Silent fail - nicht kritisch

        # ══════════════════════════════════════════════════════════════
        # 5.6 CLAUDE.md SYNC - BACH-Block pushen (SQ038 Stufe 2 Managed)
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            try:
                # Prüfe ob Integration-Level aktiviert
                conn = self._get_conn()
                level_row = conn.execute("""
                    SELECT value FROM system_config
                    WHERE key='integration.claude-code.level'
                """).fetchone()
                conn.close()

                level = level_row[0] if level_row else "off"

                if level in ("managed", "full"):
                    # Stufe 2+ aktiv: CLAUDE.md BACH-Block updaten
                    import sys
                    tools_dir = str(self.base_path / "tools")
                    if tools_dir not in sys.path:
                        sys.path.insert(0, tools_dir)
                    from claude_md_sync import ClaudeMdSync

                    bach_root = self.base_path.parent
                    syncer = ClaudeMdSync(bach_root)
                    success, msg = syncer.push()

                    if success:
                        results.append("")
                        results.append("[CLAUDE.md SYNC]")
                        results.append(f" {msg}")
            except Exception as e:
                pass  # Silent fail - nicht kritisch

        # ══════════════════════════════════════════════════════════════
        # 5.7 DAILY LOG - Tages-Log schreiben (SQ065)
        # ══════════════════════════════════════════════════════════════
        if not dry_run:
            try:
                import sys
                tools_dir = str(self.base_path / "tools")
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                from memory_sync import DailyLogGenerator

                bach_root = self.base_path.parent
                log_gen = DailyLogGenerator(bach_root)
                log_file = log_gen.write_log()

                results.append("")
                results.append("[DAILY LOG]")
                results.append(f" ✓ Tages-Log geschrieben: {log_file.name}")
            except Exception as e:
                pass  # Silent fail - nicht kritisch

        # ══════════════════════════════════════════════════════════════
        # 5.8 CONTINUATION CONTEXT - Naechster-Start-Anker (SQ065)
        # ══════════════════════════════════════════════════════════
        if not dry_run:
            conn = None
            try:
                import json
                conn = self._get_conn()

                active = self._get_active_session(conn)
                if active:
                    session_id = active[1]

                    cursor = conn.execute("""
                        SELECT id, title, priority, status
                        FROM tasks
                        WHERE status IN ('pending', 'in_progress')
                        ORDER BY
                            CASE status
                                WHEN 'in_progress' THEN 1
                                WHEN 'pending' THEN 2
                                ELSE 3
                            END,
                            priority DESC,
                            created_at DESC
                        LIMIT 5
                    """)

                    top_tasks = []
                    for row in cursor.fetchall():
                        top_tasks.append({
                            "id": row[0],
                            "title": row[1],
                            "priority": row[2],
                            "status": row[3]
                        })

                    continuation = {
                        "timestamp": now.isoformat(),
                        "top_tasks": top_tasks,
                        "session_summary": summary if summary else "Session beendet",
                        "tasks_created": tasks_created,
                        "tasks_completed": tasks_completed
                    }

                    conn.execute("""
                        UPDATE memory_sessions
                        SET continuation_context = ?
                        WHERE session_id = ?
                    """, (json.dumps(continuation, ensure_ascii=False), session_id))
                    conn.commit()

                    results.append("")
                    results.append("[CONTINUATION CONTEXT]")
                    results.append(f" ✓ Naechster-Start-Anker gesetzt ({len(top_tasks)} Tasks)")
            except Exception:
                pass
            finally:
                if conn:
                    conn.close()

        # 6. NUL-Cleaner - Windows NUL-Dateien aufräumen
        if not dry_run:
            try:
                from tools.nulcleaner import clean_nul_files_headless
                # BACH_ROOT (eine Ebene ueber system/) reinigen
                bach_root = self.base_path.parent
                nul_result = clean_nul_files_headless(str(bach_root), verbose=False)
                if nul_result['found'] > 0:
                    results.append("")
                    results.append("[NUL CLEANER]")
                    results.append(f" Gefunden: {nul_result['found']} | Geloescht: {nul_result['deleted']}")
                    if nul_result['errors']:
                        results.append(f" [!] {len(nul_result['errors'])} Fehler beim Loeschen")
            except Exception:
                pass  # Silent fail - nicht kritisch

        results.append("")
        results.append("=" * 55)
        results.append(" Session BEENDET")
        results.append("=" * 55)
        results.append("")
        results.append("HINWEIS FUER CLAUDE:")
        results.append("Session-Bericht gehoert in memory_sessions (DB)!")
        results.append("Format: bach --memory session \"Zusammenfassung\"")
        results.append("Oder direkt in DB: INSERT INTO memory_sessions (...)")

        return True, "\n".join(results)
