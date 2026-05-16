# SPDX-License-Identifier: MIT
"""
BACH Trash Handler
==================
CLI-Handler fuer das Papierkorb-System (Soft-Delete).

Befehle:
    bach trash list              Alle Eintraege im Papierkorb
    bach trash delete PATH       Datei in Papierkorb verschieben
    bach trash restore ID        Datei wiederherstellen
    bach trash purge             Abgelaufene Dateien loeschen
    bach trash info ID           Details zu einem Eintrag
"""

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from .base import BaseHandler


class TrashHandler(BaseHandler):
    """Handler fuer --trash Befehle"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db
        self.trash_dir = base_path / "data" / "trash"
        self.trash_dir.mkdir(exist_ok=True)
    
    @property
    def profile_name(self) -> str:
        return "trash"
    
    @property
    def target_file(self) -> Path:
        return self.trash_dir
    
    def get_operations(self) -> dict:
        return {
            "list": "Alle Eintraege im Papierkorb anzeigen",
            "delete": "Datei in Papierkorb verschieben (soft delete)",
            "restore": "Datei aus Papierkorb wiederherstellen",
            "purge": "Abgelaufene Dateien endgueltig loeschen",
            "info": "Details zu einem Papierkorb-Eintrag",
            "help": "Diese Hilfe anzeigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not operation or operation in ["list", "ls"]:
            return self._list_trash()
        
        op = operation.lower()
        
        if op == "delete":
            if not args:
                return False, "[FEHLER] Pfad zur Datei erforderlich"
            return self._soft_delete(args[0], dry_run)
        elif op == "restore":
            if not args:
                return False, "[FEHLER] Trash-ID erforderlich"
            return self._restore(args[0], dry_run)
        elif op == "purge":
            return self._purge_expired(dry_run)
        elif op == "info":
            if not args:
                return False, "[FEHLER] Trash-ID erforderlich"
            return self._get_info(args[0])
        elif op in ["help", "-h", "?"]:
            return self._show_help()
        else:
            return False, f"[FEHLER] Unbekannte Operation: {op}"
    
    def _list_trash(self) -> tuple:
        """Zeigt alle Eintraege im Papierkorb"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT id, original_path, size, deleted_at, expires_at, status
            FROM files_trash
            WHERE status = 'active'
            ORDER BY deleted_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return True, "[PAPIERKORB] Leer - keine geloeschten Dateien"
        
        lines = [f"[PAPIERKORB] {len(rows)} Eintraege:\n"]
        for row in rows:
            id_, path, size, deleted, expires, status = row
            size_str = f"{size/1024:.1f}KB" if size else "?"
            lines.append(f"  [{id_}] {Path(path).name}")
            lines.append(f"      Pfad: {path}")
            lines.append(f"      Groesse: {size_str} | Geloescht: {deleted[:16]}")
            lines.append(f"      Ablauf: {expires[:16] if expires else 'nie'}")
            lines.append("")
        
        lines.append("--> bach trash restore ID zum Wiederherstellen")
        return True, "\n".join(lines)
    
    def _soft_delete(self, file_path: str, dry_run: bool) -> tuple:
        """Verschiebt Datei in den Papierkorb"""
        source = Path(file_path)
        if not source.exists():
            return False, f"[FEHLER] Datei existiert nicht: {file_path}"
        
        # Eindeutigen Namen im Trash erzeugen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trash_name = f"{timestamp}_{source.name}"
        trash_path = self.trash_dir / trash_name
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde verschieben: {source} -> {trash_path}"
        
        # Datei verschieben
        try:
            shutil.move(str(source), str(trash_path))
        except Exception as e:
            return False, f"[FEHLER] Verschieben fehlgeschlagen: {e}"
        
        # In DB eintragen
        now = datetime.now()
        expires = now + timedelta(days=30)
        
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO files_trash 
            (original_path, trash_path, size, deleted_at, deleted_by, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, (
            str(source.absolute()),
            str(trash_path),
            trash_path.stat().st_size,
            now.isoformat(),
            "claude",
            expires.isoformat()
        ))
        conn.commit()
        last_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        
        return True, f"[TRASH] Datei in Papierkorb verschoben (ID: {last_id})\n  --> bach trash restore {last_id} zum Wiederherstellen"
    
    def _restore(self, trash_id: str, dry_run: bool) -> tuple:
        """Stellt Datei aus Papierkorb wieder her"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT id, original_path, trash_path, status
            FROM files_trash WHERE id = ?
        """, (trash_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return False, f"[FEHLER] Kein Eintrag mit ID {trash_id}"
        
        id_, original, trash, status = row
        
        if status != 'active':
            conn.close()
            return False, f"[FEHLER] Eintrag nicht aktiv (Status: {status})"
        
        trash_path = Path(trash)
        original_path = Path(original)
        
        if not trash_path.exists():
            conn.close()
            return False, f"[FEHLER] Trash-Datei existiert nicht mehr: {trash_path}"
        
        if dry_run:
            conn.close()
            return True, f"[DRY-RUN] Wuerde wiederherstellen: {trash_path} -> {original_path}"
        
        # Zielverzeichnis erstellen falls noetig
        original_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Falls Ziel existiert, umbenennen
        if original_path.exists():
            backup = original_path.with_suffix(f".backup{original_path.suffix}")
            original_path.rename(backup)
        
        # Wiederherstellen
        try:
            shutil.move(str(trash_path), str(original_path))
        except Exception as e:
            conn.close()
            return False, f"[FEHLER] Wiederherstellen fehlgeschlagen: {e}"
        
        # Status aktualisieren
        conn.execute("""
            UPDATE files_trash 
            SET status = 'restored', restored_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), trash_id))
        conn.commit()
        conn.close()
        
        return True, f"[RESTORE] Datei wiederhergestellt:\n  {original_path}"
    
    def _purge_expired(self, dry_run: bool) -> tuple:
        """Loescht abgelaufene Dateien endgueltig"""
        now = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT id, original_path, trash_path
            FROM files_trash
            WHERE status = 'active' AND expires_at < ?
        """, (now,))
        rows = cursor.fetchall()
        
        if not rows:
            conn.close()
            return True, "[PURGE] Keine abgelaufenen Dateien"
        
        if dry_run:
            lines = [f"[DRY-RUN] Wuerde {len(rows)} Dateien loeschen:"]
            for id_, orig, trash in rows:
                lines.append(f"  [{id_}] {Path(orig).name}")
            conn.close()
            return True, "\n".join(lines)
        
        purged = 0
        for id_, orig, trash in rows:
            trash_path = Path(trash)
            if trash_path.exists():
                try:
                    trash_path.unlink()
                    purged += 1
                except OSError:
                    pass
            
            conn.execute("""
                UPDATE files_trash 
                SET status = 'purged', purged_at = ?
                WHERE id = ?
            """, (now, id_))
        
        conn.commit()
        conn.close()
        
        return True, f"[PURGE] {purged} Dateien endgueltig geloescht"
    
    def _get_info(self, trash_id: str) -> tuple:
        """Zeigt Details zu einem Eintrag"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT * FROM files_trash WHERE id = ?
        """, (trash_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return False, f"[FEHLER] Kein Eintrag mit ID {trash_id}"
        
        cols = ["id", "original_path", "trash_path", "size", "deleted_at", 
                "deleted_by", "retention_days", "expires_at", "status", 
                "restored_at", "purged_at"]
        
        lines = [f"[TRASH INFO] ID {trash_id}:\n"]
        for i, col in enumerate(cols):
            if row[i]:
                lines.append(f"  {col}: {row[i]}")
        
        return True, "\n".join(lines)
    
    def _show_help(self) -> tuple:
        """Zeigt Hilfe"""
        help_text = """
[TRASH] Papierkorb-System

BEFEHLE:
  bach trash list          Alle Eintraege anzeigen
  bach trash delete PATH   Datei in Papierkorb verschieben
  bach trash restore ID    Datei wiederherstellen
  bach trash purge         Abgelaufene Dateien loeschen
  bach trash info ID       Details zu einem Eintrag

OPTIONEN:
  --dry-run               Aenderungen nur simulieren

BEISPIELE:
  bach trash delete ./alte_datei.txt
  bach trash list
  bach trash restore 5
  bach trash purge --dry-run

HINWEISE:
  - Dateien bleiben 30 Tage im Papierkorb
  - Automatische Bereinigung bei --startup (geplant)
"""
        return True, help_text
