# SPDX-License-Identifier: MIT
"""
Shutdown Handler - Session beenden (DB-basiert)
================================================

Speichert Session-Bericht in memory_sessions.
Kein Markdown-Dateisystem mehr!

Session-Auswahl und Ownership werden vor Seiteneffekten geprüft.
"""
import sqlite3
from contextlib import closing
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
        from ._services.session_scope import parse_scope, select_session
        try:
            summary, scope = parse_scope(args)
            with closing(self._get_conn()) as conn:
                active = select_session(conn, **scope)
            partner_id = scope.get("partner_id") or (active[4] if active else None) or "user"
        except (ValueError, sqlite3.Error) as exc:
            return False, str(exc)

        # Hook: before_shutdown
        try:
            from core.hooks import hooks
            if not dry_run:
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
            success, message = self._complete(
                summary, dry_run, _selected=active, _selection_checked=True, **scope
            )

        if success and not dry_run:
            try:
                if active and operation in ("quick", "emergency"):
                    self._clock_out_partner(partner_id, session_id=active[1])
                else:
                    self._clock_out_partner(partner_id)
            except sqlite3.Error as exc:
                # Session/note already committed. Report secondary failure without
                # telling callers to retry an already completed session write.
                message += f"\n[WARN] Session saved; clock-out failed: {exc}"

        # Hook: after_shutdown (re-import to avoid scope issue)
        try:
            from core.hooks import hooks as _hooks
            if not dry_run:
                _hooks.emit('after_shutdown', {
                    'partner': partner_id, 'mode': operation or 'complete',
                    'success': success
                })
        except Exception:
            pass

        return success, message
    
    def _get_conn(self):
        return sqlite3.connect(self.db_path)
    
    def _clock_out_partner(self, partner_id: str, session_id=None) -> bool:
        """Stempelt Partner aus (partner_presence Tabelle)."""
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            conn.execute("""
                UPDATE partner_presence
                SET status = 'offline', clocked_out = ?, updated_at = ?
                WHERE LOWER(partner_name) = ? AND status = 'online'
                AND NOT EXISTS (
                    SELECT 1 FROM memory_sessions
                    WHERE LOWER(partner_id) = ? AND ended_at IS NULL
                    AND (? IS NULL OR session_id != ?)
                )
            """, (now, now, partner_id.lower(), partner_id.lower(), session_id, session_id))
            conn.commit()
        finally:
            conn.close()
        return True
    
    def _get_active_session(self, conn) -> tuple:
        """Legacy reader; ambiguity is an error, never a newest-session guess."""
        from ._services.session_scope import select_session
        return select_session(conn)
    
    def _generate_fallback_summary(self, session_start: str) -> str:
        """
        Generiert automatische Zusammenfassung aus Autolog.
        
        Legacy-Hilfsfunktion; der aktuelle Abschluss wertet keine gemeinsamen
        Autologs mehr automatisch aus.
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
                return False, f"[ERROR] {e}"
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
                return False, f"[ERROR] {e}"
            finally:
                conn.close()
        
        results.append(" [OK] Session pausiert")
        results.append("=" * 55)
        
        return True, "\n".join(results)
    
    def _complete(self, summary: str, dry_run: bool, *, _selected=None,
                  _selection_checked=False, **scope) -> tuple:
        """Close one session; global maintenance is an explicit separate operation."""
        from ._services.session_scope import select_session, new_session_id
        # Validate before scans/snapshots or any other side effect.
        try:
            with closing(self._get_conn()) as conn:
                selected = _selected if _selection_checked else select_session(conn, **scope)
                if selected and conn.execute(
                    "SELECT 1 FROM memory_sessions WHERE id=? AND session_id=? "
                    "AND partner_id IS ? AND ended_at IS NULL",
                    (selected[0], selected[1], selected[4]),
                ).fetchone() is None:
                    raise ValueError("Selected session changed concurrently")
            if selected:
                scope = {"session_id": selected[1], "partner_id": selected[4]}
                # Legacy sessions can have no partner. Pin their internal row ID below.
        except (ValueError, sqlite3.Error) as exc:
            return False, str(exc)
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
        if not dry_run and change_count >= 3 and selected:
            try:
                from .snapshot import SnapshotHandler
                snap_handler = SnapshotHandler(self.base_path)
                snap_handler.db_path = self.db_path
                snap_name = f"auto_{now.strftime('%Y%m%d_%H%M%S')}"
                success, snap_msg = snap_handler._create(
                    snap_name, dry_run=False, session_id=selected[1]
                )
                if success:
                    results.append(f" [OK] Auto-Snapshot erstellt ({change_count} Aenderungen)")
                else:
                    results.append(f" [SKIP] {snap_msg}")
            except Exception as e:
                results.append(f" [SKIP] Auto-Snapshot: {e}")
        elif not dry_run and not selected:
            results.append(" [SKIP] Keine adressierte Session fuer Auto-Snapshot")
        elif not dry_run:
            results.append(f" [SKIP] Nur {change_count} Aenderungen (Schwelle: 3)")
        else:
            results.append(" [DRY-RUN] Wuerde Auto-Snapshot pruefen")
        
        if dry_run:
            results.append("[DRY-RUN] Wuerde Session speichern")
            return True, "\n".join(results)

        import json
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if selected:
                active = conn.execute(
                    "SELECT id, session_id, started_at, tasks_created, partner_id "
                    "FROM memory_sessions WHERE id=? AND session_id=? "
                    "AND partner_id IS ? AND ended_at IS NULL",
                    (selected[0], selected[1], selected[4]),
                ).fetchone()
                if active is None:
                    raise ValueError("Selected session was closed concurrently")
            else:
                active = None
            if active:
                session_id = active[1]
                started_at = active[2]
            elif summary:
                session_id = new_session_id(now)
                started_at = now.isoformat()
                conn.execute(
                    "INSERT INTO memory_sessions "
                    "(session_id, partner_id, started_at, summary) VALUES (?, ?, ?, '')",
                    (session_id, scope.get("partner_id"), started_at),
                )
            else:
                results.append("[SKIP] Keine aktive Session")
                session_id = None
                started_at = now.isoformat()

            tasks_created = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE created_at >= ? AND created_at <= ?",
                (started_at, now.isoformat()),
            ).fetchone()[0]
            tasks_completed = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('done','completed') "
                "AND completed_at >= ? AND completed_at <= ?",
                (started_at, now.isoformat()),
            ).fetchone()[0]
            if session_id:
                top_tasks = conn.execute(
                    "SELECT id,title,priority,status FROM tasks "
                    "WHERE status IN ('pending','in_progress') "
                    "ORDER BY CASE status WHEN 'in_progress' THEN 1 ELSE 2 END, "
                    "priority DESC, created_at DESC, id LIMIT 5"
                ).fetchall()
                continuation = {
                    "timestamp": now.isoformat(),
                    "top_tasks": [dict(zip(("id", "title", "priority", "status"), row)) for row in top_tasks],
                    "session_summary": summary or "Session beendet",
                    "tasks_created": tasks_created,
                    "tasks_completed": tasks_completed,
                }
                conn.execute(
                    "UPDATE memory_sessions SET ended_at=?, "
                    "summary=COALESCE(summary,'') || ?, tasks_created=?, "
                    "tasks_completed=?, continuation_context=? WHERE session_id=?",
                    (now.isoformat(), "\n" + summary if summary else "", tasks_created,
                     tasks_completed, json.dumps(continuation, ensure_ascii=False), session_id),
                )
                results.append(f"[OK] Session {session_id} abgeschlossen")
            working = conn.execute("SELECT COUNT(*) FROM memory_working WHERE is_active=1").fetchone()[0]
            facts = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM memory_sessions").fetchone()[0]
            results.append(f"Working: {working} | Facts: {facts} | Sessions: {sessions}")
            results.append(f"+{tasks_created} erstellt, {tasks_completed} erledigt (diese Session)")
            conn.commit()
        except (ValueError, sqlite3.Error) as exc:
            conn.rollback()
            return False, f"[ERROR] {exc}"
        finally:
            conn.close()
        results.append("Session BEENDET")
        return True, "\n".join(results)
