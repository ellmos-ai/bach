# SPDX-License-Identifier: MIT
"""
Snapshot Handler - Session-Snapshot-Verwaltung
===============================================

--snapshot create [name]   Aktuellen Session-Zustand speichern
--snapshot load [id]       Snapshot laden/fortsetzen
--snapshot list            Alle Snapshots auflisten
--snapshot delete <id>     Snapshot loeschen

KONZEPT:
- Snapshot = Vollstaendiger Zustand fuer Session-Wiederherstellung
- Unterschied zu Memory: Memory = Zusammenfassung, Snapshot = Zustand
- Unterschied zu Autolog: Autolog = WAS gemacht, Snapshot = WO man war
"""
import sys
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class SnapshotHandler(BaseHandler):
    """Handler fuer --snapshot Operationen (Session-Wiederherstellung)"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
    
    @property
    def profile_name(self) -> str:
        return "snapshot"
    
    @property
    def target_file(self) -> Path:
        return self.db_path
    
    def get_operations(self) -> dict:
        return {
            "create": "Session-Snapshot erstellen",
            "load": "Snapshot laden (letzten oder per ID)",
            "list": "Alle Snapshots auflisten",
            "delete": "Snapshot loeschen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "create":
            name = args[0] if args else None
            return self._create(name, dry_run)
        elif operation == "load":
            snapshot_id = args[0] if args else None
            return self._load(snapshot_id, dry_run)
        elif operation == "list":
            return self._list()
        elif operation == "delete" and args:
            return self._delete(args[0], dry_run)
        else:
            return self._list()
    
    def _get_db_connection(self):
        """SQLite-Verbindung herstellen."""
        import sqlite3
        if not self.db_path.exists():
            return None, "DB nicht gefunden"
        return sqlite3.connect(self.db_path), None
    
    def _create(self, name: str = None, dry_run: bool = False) -> tuple:
        """Session-Snapshot erstellen.
        
        Speichert:
        - Aktuelle Session-ID
        - Offene Tasks
        - Working Memory
        - Aktueller Ordner-Zustand (files_truth Hash)
        - Timestamp
        """
        if dry_run:
            return True, "[DRY-RUN] Wuerde Snapshot erstellen"
        
        conn, err = self._get_db_connection()
        if err:
            return False, err
        
        try:
            cursor = conn.cursor()
            
            # Aktuellen Zustand sammeln
            timestamp = datetime.now().isoformat()
            session_id = self._get_current_session_id(cursor)
            
            # Snapshot-Name generieren
            snapshot_name = name or f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Offene Tasks sammeln
            cursor.execute("SELECT id, title FROM tasks WHERE status = 'pending' LIMIT 10")
            open_tasks = [{"id": r[0], "title": r[1]} for r in cursor.fetchall()]
            
            # Working Memory (letzte 5)
            cursor.execute("SELECT content FROM memory_working ORDER BY created_at DESC LIMIT 5")
            recent_memory = [r[0] for r in cursor.fetchall()]
            
            # Snapshot-Daten als JSON
            import json
            snapshot_data = json.dumps({
                "session_id": session_id,
                "open_tasks": open_tasks,
                "recent_memory": recent_memory,
                "created_at": timestamp
            })
            
            # In session_snapshots speichern
            cursor.execute("""
                INSERT INTO session_snapshots (session_id, snapshot_type, name, snapshot_data, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, "manual", snapshot_name, snapshot_data, timestamp))
            
            conn.commit()
            conn.close()
            
            return True, f"[OK] Snapshot '{snapshot_name}' erstellt\n  Session: {session_id}\n  Tasks: {len(open_tasks)} offen"
            
        except Exception as e:
            conn.close()
            return False, f"[FEHLER] Snapshot erstellen: {e}"
    
    def _get_current_session_id(self, cursor) -> str:
        """Aktuelle Session-ID aus system_config holen."""
        cursor.execute("SELECT value FROM system_config WHERE key = 'current_session'")
        row = cursor.fetchone()
        return row[0] if row else "unknown"
    
    def _load(self, snapshot_id: str = None, dry_run: bool = False) -> tuple:
        """Snapshot laden und Kontext wiederherstellen.
        
        Bei --startup kann dies aufgerufen werden, um letzten Snapshot zu laden.
        """
        if dry_run:
            return True, "[DRY-RUN] Wuerde Snapshot laden"
        
        conn, err = self._get_db_connection()
        if err:
            return False, err
        
        try:
            import json
            cursor = conn.cursor()
            
            if snapshot_id:
                cursor.execute("SELECT id, session_id, name, snapshot_data, created_at FROM session_snapshots WHERE id = ?", (snapshot_id,))
            else:
                # Letzten Snapshot laden
                cursor.execute("SELECT id, session_id, name, snapshot_data, created_at FROM session_snapshots ORDER BY created_at DESC LIMIT 1")
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return False, "[INFO] Kein Snapshot gefunden"
            
            # Snapshot-Daten parsen
            snapshot_data = json.loads(row[3]) if row[3] else {}
            
            output = []
            output.append(f"[SNAPSHOT] {row[2]} (ID: {row[0]})")
            output.append(f"  Session: {snapshot_data.get('session_id', 'unbekannt')}")
            output.append(f"  Erstellt: {row[4]}")
            
            open_tasks = snapshot_data.get("open_tasks", [])
            if open_tasks:
                output.append(f"\n  Offene Tasks ({len(open_tasks)}):")
                for t in open_tasks[:5]:
                    output.append(f"    [{t['id']}] {t['title'][:50]}")
            
            recent_memory = snapshot_data.get("recent_memory", [])
            if recent_memory:
                output.append(f"\n  Letzte Notizen ({len(recent_memory)}):")
                for m in recent_memory[:3]:
                    output.append(f"    - {m[:60]}...")
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[FEHLER] Snapshot laden: {e}"
    
    def _list(self) -> tuple:
        """Alle Snapshots auflisten."""
        conn, err = self._get_db_connection()
        if err:
            return False, err
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, session_id, name, created_at 
                FROM session_snapshots 
                ORDER BY created_at DESC 
                LIMIT 20
            """)
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return True, "[INFO] Keine Snapshots vorhanden"
            
            output = ["[SNAPSHOTS]", ""]
            for r in rows:
                output.append(f"  [{r[0]}] {r[2]}")
                output.append(f"      Session: {r[1]} | {r[3]}")
            
            return True, "\n".join(output)
            
        except Exception as e:
            return False, f"[FEHLER] Snapshots auflisten: {e}"
    
    def _delete(self, snapshot_id: str, dry_run: bool = False) -> tuple:
        """Snapshot loeschen."""
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Snapshot {snapshot_id} loeschen"
        
        conn, err = self._get_db_connection()
        if err:
            return False, err
        
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM session_snapshots WHERE id = ?", (snapshot_id,))
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted:
                return True, f"[OK] Snapshot {snapshot_id} geloescht"
            else:
                return False, f"[FEHLER] Snapshot {snapshot_id} nicht gefunden"
                
        except Exception as e:
            return False, f"[FEHLER] Snapshot loeschen: {e}"
