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
import re

SAFE_MOUNT_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

class MountHandler(BaseHandler):
    """Handler fuer --mount Befehle"""
    
    @property
    def profile_name(self) -> str:
        return "mount"
    
    @property
    def target_file(self) -> Path:
        return self.base_path / "user"

    def _safe_alias(self, value: str) -> str:
        alias = str(value or "")
        if not SAFE_MOUNT_ALIAS_RE.fullmatch(alias):
            raise ValueError("Ungueltiger Mount-Alias")
        return alias

    def _target_for_alias(self, alias: str) -> Path:
        target_root = self.target_file.resolve()
        target = (target_root / self._safe_alias(alias)).resolve(strict=False)
        target.relative_to(target_root)
        return target

    def _resolve_mount_source(self, value: str) -> Path:
        raw = str(value or "")
        if "\x00" in raw:
            raise ValueError("Ungueltiger Quellpfad")
        # strict=False: resolve(strict=True) wirft auf Windows FileNotFoundError
        # (OSError), die Aufrufer fangen aber nur ValueError -> Crash.
        # Existenz pruefen die Aufrufer selbst (eigene Meldungen).
        source = Path(raw).expanduser().resolve(strict=False)
        if source.exists() and not source.is_dir():
            raise ValueError("Quellpfad ist kein Ordner")
        return source
    
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
                try:
                    alias = self._safe_alias(row['name'])
                except ValueError:
                    continue
                status = "[OK]" if row['is_active'] else "[--]"
                target_path = self._target_for_alias(alias)
                exists = "[EXISTIERT]" if target_path.exists() else "[FEHLT]"
                lines.append(f"{status} {alias} -> {row['endpoint']} {exists}")
                
            return True, "\n".join(lines)
        except Exception:
            return False, "Fehler beim Lesen der DB"

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

        try:
            source = self._resolve_mount_source(args[0])
            alias = self._safe_alias(args[1])
            target = self._target_for_alias(alias)
        except ValueError as exc:
            return False, str(exc)

        if not source.exists():
            return False, "Quellpfad existiert nicht"

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
        except Exception:
            return False, "Fehler beim Anlegen der Anbindung"

    def _remove_mount(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: bach mount remove <alias>"
        
        try:
            alias = self._safe_alias(args[0])
            target = self._target_for_alias(alias)
        except ValueError as exc:
            return False, str(exc)
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Junction entfernen und aus DB loeschen: {alias}"
        
        try:
            self._remove_link(target)

            conn = self._get_db_conn()
            conn.execute("DELETE FROM connections WHERE type='mount' AND name=?", (alias,))
            conn.commit()
            conn.close()
            
            return True, f"[OK] Anbindung entfernt: {alias}"
        except Exception:
            return False, "Fehler beim Entfernen"

    def _restore_mounts(self, dry_run: bool) -> Tuple[bool, str]:
        """Stellt alle Mounts aus der DB wieder her."""
        try:
            conn = self._get_db_conn()
            rows = conn.execute("SELECT name, endpoint FROM connections WHERE type='mount' AND is_active=1").fetchall()
            conn.close()
            
            restored = []
            errors = []
            
            for row in rows:
                try:
                    alias = self._safe_alias(row["name"])
                    source = self._resolve_mount_source(row["endpoint"])
                    target = self._target_for_alias(alias)
                except ValueError:
                    errors.append("Ungueltiger Mount-Eintrag")
                    continue
                
                if not source.exists():
                    errors.append(f"{alias}: Quelle fehlt")
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
                except Exception:
                    errors.append(f"{alias}: Wiederherstellung fehlgeschlagen")
            
            msg = f"Wiederhergestellt: {len(restored)} | Fehler: {len(errors)}"
            if errors:
                msg += "\n" + "\n".join(errors)
            return True, msg
            
        except Exception:
            return False, "Restore-Fehler"
