# SPDX-License-Identifier: MIT
"""
BACH Mount Handler
==================
Handler fuer die Anbindung externer Ordner (SYS_001).
"""

from pathlib import Path
from typing import List, Tuple
from .base import BaseHandler
import subprocess
import os
import sqlite3

class MountHandler(BaseHandler):
    """Handler fuer --mount Befehle"""
    
    @property
    def profile_name(self) -> str:
        return "mount"
    
    @property
    def target_file(self) -> Path:
        return self.base_path / "user"
    
    def get_operations(self) -> dict:
        return {
            "add": "Externen Ordner anbinden: bach mount add <pfad> <alias>",
            "remove": "Anbindung entfernen: bach mount remove <alias>",
            "list": "Aktive Mounts anzeigen",
            "restore": "Mounts (Symlinks/Junctions) wiederherstellen"
        }
    
    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        if not operation or operation == "list":
            return self._list_mounts()
        
        op = operation.lower()
        if op == "add":
            return self._add_mount(args, dry_run)
        elif op == "remove":
            return self._remove_mount(args, dry_run)
        elif op == "restore":
            return self._restore_mounts(dry_run)
        else:
            return False, f"Unbekannte Operation: {op}"

    def _get_db_conn(self):
        """Datenbank-Verbindung herstellen (bach.db)."""
        db_path = self.base_path / "data" / "bach.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _list_mounts(self) -> Tuple[bool, str]:
        """Listet aktive Mounts aus der DB."""
        try:
            conn = self._get_db_conn()
            rows = conn.execute("SELECT name, endpoint, is_active FROM connections WHERE type='mount'").fetchall()
            conn.close()
            
            if not rows:
                return True, "Keine Mounts definiert."
            
            lines = ["Aktive Mounts:", "="*20]
            for row in rows:
                status = "[OK]" if row['is_active'] else "[--]"
                target_path = self.target_file / row['name']
                exists = "[EXISTIERT]" if target_path.exists() else "[FEHLT]"
                lines.append(f"{status} {row['name']} -> {row['endpoint']} {exists}")
                
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"Fehler beim Lesen der DB: {e}"

    def _create_link(self, source: Path, target: Path):
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(target), str(source)],
                check=True, capture_output=True,
            )
        else:
            os.symlink(source, target)

    def _remove_link(self, target: Path) -> bool:
        if os.name == "nt":
            if target.exists():
                os.rmdir(target)
                return True
        else:
            if target.is_symlink() or target.exists():
                os.unlink(target)
                return True
        if hasattr(target, "is_junction") and target.is_junction():
            os.rmdir(target)
            return True
        return False

    def _add_mount(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, "Verwendung: bach mount add <pfad> <alias>"

        source = Path(args[0]).resolve()
        alias = args[1]
        target = self.base_path / "user" / alias

        if not source.exists():
            return False, f"Quellpfad existiert nicht: {source}"

        if dry_run:
            return True, f"[DRY-RUN] Wuerde Junction erstellen: {target} -> {source} und in DB speichern."

        try:
            if not target.exists():
                self._create_link(source, target)

            conn = self._get_db_conn()
            conn.execute("""
                INSERT INTO connections (name, type, category, endpoint, is_active, help_text)
                VALUES (?, 'mount', 'storage', ?, 1, 'User Folder Mount')
                ON CONFLICT(name) DO UPDATE SET endpoint=excluded.endpoint, is_active=1
            """, (alias, str(source)))
            conn.commit()
            conn.close()

            return True, f"[OK] Ordner angebunden und gespeichert: {alias} -> {source}"
        except Exception as e:
            return False, f"Fehler: {e}"

    def _remove_mount(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: bach mount remove <alias>"
        
        alias = args[0]
        target = self.base_path / "user" / alias
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Junction entfernen und aus DB loeschen: {alias}"
        
        try:
            self._remove_link(target)

            conn = self._get_db_conn()
            conn.execute("DELETE FROM connections WHERE type='mount' AND name=?", (alias,))
            conn.commit()
            conn.close()
            
            return True, f"[OK] Anbindung entfernt: {alias}"
        except Exception as e:
            return False, f"Fehler beim Entfernen: {e}"

    def _restore_mounts(self, dry_run: bool) -> Tuple[bool, str]:
        """Stellt alle Mounts aus der DB wieder her."""
        try:
            conn = self._get_db_conn()
            rows = conn.execute("SELECT name, endpoint FROM connections WHERE type='mount' AND is_active=1").fetchall()
            conn.close()
            
            restored = []
            errors = []
            
            for row in rows:
                alias = row['name']
                source = Path(row['endpoint'])
                target = self.base_path / "user" / alias
                
                if not source.exists():
                    errors.append(f"{alias}: Quelle fehlt ({source})")
                    continue
                
                if target.exists():
                    # Schon da, alles gut
                    continue
                    
                if dry_run:
                    restored.append(f"[DRY] {alias}")
                    continue
                    
                try:
                    self._create_link(source, target)
                    restored.append(alias)
                except Exception as ex:
                    errors.append(f"{alias}: {ex}")
            
            msg = f"Wiederhergestellt: {len(restored)} | Fehler: {len(errors)}"
            if errors:
                msg += "\n" + "\n".join(errors)
            return True, msg
            
        except Exception as e:
            return False, f"Restore-Fehler: {e}"
