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
            "load": "Snapshot laden + echter Restore (Working Memory & Tasks; display = nur anzeigen)",
            "list": "Alle Snapshots auflisten",
            "delete": "Snapshot loeschen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "create":
            name = args[0] if args else None
            return self._create(name, dry_run)
        elif operation == "load":
            return self._load(args, dry_run)
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

        Fuegt den VOLLSTAENDIGEN Zustand in ALLE Schema-Spalten ein:
           - session_id, snapshot_type, name, created_at
           - snapshot_data (JSON: session_id, open_tasks, recent_memory,
            active_files, token_usage, created_at)
           - working_memory (JSON-Liste der letzten aktiven Working-Memory-Eintraege)
           - open_tasks      (JSON-Liste {id, title})
           - active_files    (JSON-Liste zuletzt geaenderter Dateien aus files_truth)
           - token_usage     (letzte Gesamt-Token-Zahl aus monitor_tokens, falls vorhanden)
           - context_hash    (Kurz-Hash der Snapshot-Daten, sha256[:16])
           - notes           (optional, = Name)
        """
        import json, hashlib, sqlite3
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

            # Working Memory (letzte 5 aktive)
            cursor.execute(
                "SELECT content FROM memory_working WHERE is_active = 1 "
                "ORDER BY created_at DESC LIMIT 5")
            recent_memory = [r[0] for r in cursor.fetchall()]

            # Active Files (zuletzt geaendert, files_truth; kann leer sein)
            active_files = []
            try:
                cursor.execute(
                    "SELECT path FROM files_truth WHERE file_exists = 1 "
                    "ORDER BY modified_at DESC LIMIT 10")
                active_files = [r[0] for r in cursor.fetchall()]
            except sqlite3.OperationalError:
                active_files = []

            # Token-Usage (letzte Gesamtzahl, falls vorhanden)
            token_usage = None
            try:
                row = cursor.execute(
                    "SELECT tokens_total FROM monitor_tokens ORDER BY id DESC LIMIT 1"
                ).fetchone()
                token_usage = row[0] if row else None
            except sqlite3.OperationalError:
                token_usage = None

            # Zentrale Snapshot-Daten als JSON
            snapshot_data = json.dumps({
                "session_id": session_id,
                "open_tasks": open_tasks,
                "recent_memory": recent_memory,
                "active_files": active_files,
                "token_usage": token_usage,
                "created_at": timestamp,
            })
            context_hash = hashlib.sha256(snapshot_data.encode("utf-8")).hexdigest()[:16]

            # In session_snapshots speichern (ALLE Schema-Spalten befuellen)
            cursor.execute(
                """
                INSERT INTO session_snapshots
                (session_id, snapshot_type, name, snapshot_data,
                 working_memory, open_tasks, active_files,
                 token_usage, context_hash, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, "manual", snapshot_name, snapshot_data,
                    json.dumps(recent_memory),
                    json.dumps(open_tasks),
                    json.dumps(active_files),
                    token_usage,
                    context_hash,
                    snapshot_name,
                    timestamp,
                ))

            conn.commit()
            conn.close()

            out = [
                "[OK] Snapshot '" + snapshot_name + "' erstellt",
                "  Session: " + str(session_id),
                "  Tasks: " + str(len(open_tasks)) + " offen | "
                "Memory: " + str(len(recent_memory)) + " | "
                "Files: " + str(len(active_files)),
                "  context_hash: " + str(context_hash) + " | tokens: " + str(token_usage),
            ]
            return True, "\n".join(out)

        except Exception as e:
            conn.close()
            return False, "[FEHLER] Snapshot erstellen: " + str(e)

    def _get_current_session_id(self, cursor) -> str:
        """Aktuelle Session-ID aus system_config holen."""
        cursor.execute("SELECT value FROM system_config WHERE key = 'current_session'")
        row = cursor.fetchone()
        return row[0] if row else "unknown"
    
    def _load(self, args: list, dry_run: bool = False) -> tuple:
        """Snapshot laden und ECHTEN RESTORE in das Live-System einfuehren.

        Semantik (nicht-destruktiv, idempotent):
            - Working Memory: fehlende Eintraege aus dem Snapshot werden als neue,
            aktive memory_working-Rows (type='restore_snapshot') zurueckgeschrieben.
            Identische aktive Eintraege werden uebersprungen (kein Duplikat).
            - Tasks: vorhandene Tasks mit der gesicherten ID, die NICHT mehr offen
            sind, werden reaktiviert (status='pending'); fehlende Tasks werden als
            neue pending-Tasks (source='snapshot-restore') angelegt. Bereits offene
            Tasks = No-Op.
            - current_session wird NICHT ueberschrieben (Sicherheitsabstand).

        Modus:
            - `load`                         -> Restore des letzten Snapshots
            - `load <id>`                    -> Restore des Snapshots mit ID
            - `load <id> display` / `load display` -> Nur anzeigen (kein Restore)
        """
        import json, sqlite3
        NL = chr(10)
        if dry_run:
            return True, "[DRY-RUN] Wuerde Snapshot laden"

        # Argumente parsen
        display_only = False
        snapshot_id = None
        for a in (args or []):
            al = str(a).lower()
            if al in ("display", "show", "--display", "only"):
                display_only = True
            elif str(a).lstrip("-").isdigit():
                snapshot_id = str(a).lstrip("-")

        conn, err = self._get_db_connection()
        if err:
            return False, err

        try:
            cursor = conn.cursor()

            cols = ("id, session_id, name, snapshot_data, working_memory, "
                    "open_tasks, created_at")
            if snapshot_id:
                cursor.execute(
                    f"SELECT {cols} FROM session_snapshots WHERE id = ?",
                    (snapshot_id,))
            else:
                cursor.execute(
                    f"SELECT {cols} FROM session_snapshots "
                    "ORDER BY created_at DESC LIMIT 1")

            row = cursor.fetchone()
            if not row:
                conn.close()
                return False, "[INFO] Kein Snapshot gefunden"

            snap_id, session_id, name, data_blob, wm_col, ot_col, created_at = row

            # Datenquellen: separate Spalten bevorzugen, sonst aus snapshot_data
            try:
                data = json.loads(data_blob) if data_blob else {}
            except (ValueError, TypeError):
                data = {}

            try:
                open_tasks = json.loads(ot_col) if ot_col else data.get("open_tasks", []) or []
            except (ValueError, TypeError):
                open_tasks = data.get("open_tasks", []) or []
            try:
                if wm_col:
                    working_memory = json.loads(wm_col)
                else:
                    working_memory = data.get("recent_memory", data.get("working_memory", [])) or []
            except (ValueError, TypeError):
                working_memory = data.get("recent_memory", []) or []

            # Anzeigemodus (Rueckwaerts-kompatibel)
            if display_only:
                out = [f"[SNAPSHOT] {name} (ID: {snap_id})",
                       f"  Session: {session_id}",
                       f"  Erstellt: {created_at}"]
                if open_tasks:
                    out.append("")
                    out.append(f"  Offene Tasks ({len(open_tasks)}):")
                    for t in open_tasks[:5]:
                        out.append(f"       [{t.get('id')}] {str(t.get('title', ''))[:50]}")
                if working_memory:
                    out.append("")
                    out.append(f"  Letzte Notizen ({len(working_memory)}):")
                    for m in working_memory[:3]:
                        out.append(f"       - {str(m)[:60]}...")
                out.append("")
                out.append("[INFO] Display-Modus - kein Restore ausgefuehrt.")
                conn.close()
                return True, NL.join(out)

            # ---- ECHTER RESTORE (nicht-destruktiv, idempotent) ----
            now = datetime.now().isoformat()

            # 1) Working Memory: fehlende, aktive Eintraege zurueckschreiben
            wm_restored = 0
            wm_skipped = 0
            for content in working_memory:
                if not content:
                    continue
                exists = cursor.execute(
                    "SELECT 1 FROM memory_working WHERE content = ? "
                    "AND is_active = 1 LIMIT 1", (content,)).fetchone()
                if exists:
                    wm_skipped += 1
                    continue
                cursor.execute(
                    "INSERT INTO memory_working "
                    "(type, content, priority, is_active, "
                    "created_by_session_id, created_at) "
                    "VALUES (?, ?, ?, 1, ?, ?)",
                    ("note", content, 3, session_id, now))
                wm_restored += 1

            # 2) Tasks: vorhandene reaktivieren, fehlende anlegen
            tasks_reactivated = 0
            tasks_created = 0
            tasks_skipped = 0
            for t in open_tasks:
                tid = t.get("id")
                title = t.get("title", "")
                if tid is not None:
                    status_row = cursor.execute(
                        "SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()
                    if status_row:
                        if status_row[0] in ("pending", "in_progress"):
                            tasks_skipped += 1
                        else:
                            cursor.execute(
                                "UPDATE tasks SET status = 'pending', "
                                "updated_at = ? WHERE id = ?", (now, tid))
                            tasks_reactivated += 1
                        continue
                # id nicht vorhanden -> neuen Task anlegen (mit Duplikat-Gwaeht)
                dup = cursor.execute(
                    "SELECT 1 FROM tasks WHERE title = ? AND status = 'pending' "
                    "AND source = 'snapshot-restore' LIMIT 1", (title,)).fetchone()
                if dup:
                    tasks_skipped += 1
                    continue
                cursor.execute(
                    "INSERT INTO tasks (title, status, priority, source, "
                    "created_at) VALUES (?, 'pending', 'P3', 'snapshot-restore', ?)",
                    (title, now))
                tasks_created += 1

            conn.commit()
            conn.close()

            out = [f"[OK] Snapshot {name} (ID: {snap_id}) RESTORIERT",
                   f"  Session (Info): {session_id}",
                   f"  Erstellt: {created_at}",
                   f"  Working Memory: {wm_restored} zurueckgeschrieben, "
                   f"{wm_skipped} uebersprungen",
                   f"  Tasks: {tasks_reactivated} reaktiviert, "
                   f"{tasks_created} neu angelegt, {tasks_skipped} bereits offen"]
            return True, NL.join(out)

        except Exception as e:
            conn.close()
            return False, "[FEHLER] Snapshot laden: " + str(e)

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
