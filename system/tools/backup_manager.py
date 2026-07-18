#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: backup_manager
Version: 1.0.0
Author: BACH Team
Created: 2026-02-08
Updated: 2026-02-08
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version backup_manager

backup_manager.py - BACH Backup & Restore System

Verwaltet:
- User-Backup (dist_type=0) -> system/data/system/data/system/data/system/data/backups/*.zip
- Template-Snapshots (dist_type=1) -> dist/snapshots/*.orig  
- Distribution-Restore (dist_type=2) -> Aus dist/

Usage:
    python backup_manager.py create [--to-nas]
    python backup_manager.py list [--nas]
    python backup_manager.py info <name>
    python backup_manager.py restore backup <name>
    python backup_manager.py restore template <file>
    python backup_manager.py restore dist <name>
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Pfade
BACH_DIR = Path(__file__).parent.parent
DB_PATH = BACH_DIR / "data" / "bach.db"
BACKUPS_DIR = BACH_DIR / "_backups"
SNAPSHOTS_DIR = BACH_DIR / "dist" / "snapshots"
DISTRIBUTIONS_DIR = BACH_DIR / "dist"
MEMORY_DIR = BACH_DIR / "memory"
LOGS_DIR = BACH_DIR / "data" / "logs"
USER_DIR = BACH_DIR / "user"

# NAS-Pfad (wird aus DB geladen)
DEFAULT_NAS_PATH = r"\YOUR_NAS_IP\fritz.nas\Extreme_SSD\BACKUP\BACH_Backups"


class BackupManager:
    """Verwaltet Backups, Snapshots und Restores."""
    
    def __init__(self):
        self.db_path = DB_PATH
        self.backups_dir = BACKUPS_DIR
        self.snapshots_dir = SNAPSHOTS_DIR
        self._ensure_dirs()
        self.nas_path = self._get_nas_path()
    
    def _ensure_dirs(self):
        """Erstellt notwendige Verzeichnisse."""
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_nas_path(self) -> Optional[Path]:
        """Lädt NAS-Pfad aus Datenbank."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT value FROM system_config WHERE key = 'backup_nas_path'"
                ).fetchone()
                if row:
                    return Path(row[0])
        except sqlite3.Error:
            pass
        return Path(DEFAULT_NAS_PATH)
    
    def _get_db(self):
        """Datenbank-Verbindung."""
        return sqlite3.connect(self.db_path)
    
    # ═══════════════════════════════════════════════════════════════
    # BACKUP CREATE
    # ═══════════════════════════════════════════════════════════════
    
    def create_backup(self, to_nas: bool = False) -> Tuple[bool, str]:
        """
        Erstellt Backup aller Userdaten (dist_type=0).
        
        Returns:
            (success, message/path)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        backup_name = f"userdata_{timestamp}"
        zip_path = self.backups_dir / f"{backup_name}.zip"
        
        print(f"\n[BACKUP] Erstelle Backup: {backup_name}")
        print("=" * 60)
        
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                
                # 1. Manifest erstellen
                manifest = {
                    "name": backup_name,
                    "created_at": datetime.now().isoformat(),
                    "bach_version": self._get_bach_version(),
                    "type": "userdata",
                    "dist_type": 0,
                    "contents": []
                }
                
                # 2. Datenbank-Export (nur User-Tabellen)
                print("  -> Exportiere Datenbank...")
                db_export = self._export_user_tables()
                zf.writestr("db_export.json", json.dumps(db_export, indent=2, ensure_ascii=False))
                manifest["contents"].append("db_export.json")
                
                # 3. Memory-Verzeichnis
                if MEMORY_DIR.exists():
                    print("  -> Sichere Memory...")
                    for file in MEMORY_DIR.rglob("*"):
                        if file.is_file():
                            arcname = f"memory/{file.relative_to(MEMORY_DIR)}"
                            zf.write(file, arcname)
                            manifest["contents"].append(arcname)
                
                # 4. Logs-Verzeichnis
                if LOGS_DIR.exists():
                    print("  -> Sichere Logs...")
                    for file in LOGS_DIR.rglob("*"):
                        if file.is_file():
                            arcname = f"logs/{file.relative_to(LOGS_DIR)}"
                            zf.write(file, arcname)
                            manifest["contents"].append(arcname)
                
                # 5. User-Verzeichnis
                if USER_DIR.exists():
                    print("  -> Sichere User-Daten...")
                    for file in USER_DIR.rglob("*"):
                        if file.is_file():
                            arcname = f"user/{file.relative_to(USER_DIR)}"
                            zf.write(file, arcname)
                            manifest["contents"].append(arcname)
                
                # 6. Manifest speichern
                zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            
            # Größe berechnen
            size_mb = zip_path.stat().st_size / (1024 * 1024)
            print(f"\n  [OK] Backup erstellt: {zip_path.name} ({size_mb:.2f} MB)")
            
            # Optional: Auf NAS kopieren
            if to_nas and self.nas_path:
                nas_result = self._copy_to_nas(zip_path)
                if nas_result:
                    print(f"  [OK] Auf NAS kopiert: {self.nas_path}")
            
            # Rotation durchführen
            self._rotate_backups()
            
            print("=" * 60)
            return True, str(zip_path)
            
        except Exception as e:
            print(f"\n  [ERR] Fehler: {e}")
            return False, str(e)
    
    def _export_user_tables(self) -> Dict:
        """Exportiert User-Tabellen aus der Datenbank."""
        export = {}
        
        with self._get_db() as conn:
            conn.row_factory = sqlite3.Row
            
            # Tasks (immer dist_type=0)
            tasks = conn.execute("SELECT * FROM tasks").fetchall()
            export["tasks"] = [dict(row) for row in tasks]
            
            # Memory Sessions
            try:
                sessions = conn.execute("SELECT * FROM memory_sessions").fetchall()
                export["memory_sessions"] = [dict(row) for row in sessions]
            except sqlite3.Error:
                export["memory_sessions"] = []
            
            # Memory Lessons
            try:
                lessons = conn.execute("SELECT * FROM memory_lessons").fetchall()
                export["memory_lessons"] = [dict(row) for row in lessons]
            except sqlite3.Error:
                export["memory_lessons"] = []
            
            # Memory Context
            try:
                context = conn.execute("SELECT * FROM memory_context").fetchall()
                export["memory_context"] = [dict(row) for row in context]
            except sqlite3.Error:
                export["memory_context"] = []
            
            # Token-Monitoring
            try:
                tokens = conn.execute("SELECT * FROM monitor_tokens").fetchall()
                export["monitor_tokens"] = [dict(row) for row in tokens]
            except sqlite3.Error:
                export["monitor_tokens"] = []
            
            # Success-Monitoring
            try:
                success = conn.execute("SELECT * FROM monitor_success").fetchall()
                export["monitor_success"] = [dict(row) for row in success]
            except sqlite3.Error:
                export["monitor_success"] = []
        
        return export
    
    def _get_bach_version(self) -> str:
        """Holt BACH-Version aus der Datenbank."""
        try:
            with self._get_db() as conn:
                row = conn.execute(
                    "SELECT version FROM system_identity WHERE id = 1"
                ).fetchone()
                if row:
                    return row[0]
        except sqlite3.Error:
            pass
        return "unknown"
    
    def _copy_to_nas(self, source: Path) -> bool:
        """Kopiert Backup auf NAS."""
        try:
            if not self.nas_path:
                return False
            
            self.nas_path.mkdir(parents=True, exist_ok=True)
            dest = self.nas_path / source.name
            shutil.copy2(source, dest)
            return True
        except Exception as e:
            print(f"  ! NAS-Kopie fehlgeschlagen: {e}")
            return False
    
    def _rotate_backups(self, local_keep: int = 7, nas_keep: int = 30):
        """Löscht alte Backups."""
        # Lokale Rotation
        backups = sorted(self.backups_dir.glob("userdata_*.zip"), reverse=True)
        for old in backups[local_keep:]:
            old.unlink()
            print(f"  -> Gelöscht (lokal): {old.name}")
        
        # NAS-Rotation
        if self.nas_path and self.nas_path.exists():
            nas_backups = sorted(self.nas_path.glob("userdata_*.zip"), reverse=True)
            for old in nas_backups[nas_keep:]:
                old.unlink()
                print(f"  -> Gelöscht (NAS): {old.name}")
    
    # ═══════════════════════════════════════════════════════════════
    # BACKUP LIST
    # ═══════════════════════════════════════════════════════════════
    
    def list_backups(self, show_nas: bool = False) -> List[Dict]:
        """Listet verfügbare Backups."""
        backups = []
        
        # Lokale Backups
        if not show_nas:
            for zip_file in sorted(self.backups_dir.glob("userdata_*.zip"), reverse=True):
                info = self._get_backup_info(zip_file)
                if info:
                    info["location"] = "lokal"
                    backups.append(info)
        
        # NAS-Backups
        if show_nas and self.nas_path and self.nas_path.exists():
            for zip_file in sorted(self.nas_path.glob("userdata_*.zip"), reverse=True):
                info = self._get_backup_info(zip_file)
                if info:
                    info["location"] = "NAS"
                    backups.append(info)
        
        return backups
    
    def _get_backup_info(self, zip_path: Path) -> Optional[Dict]:
        """Liest Backup-Informationen aus Manifest."""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                manifest = json.loads(zf.read("manifest.json"))
                manifest["path"] = str(zip_path)
                manifest["size_mb"] = zip_path.stat().st_size / (1024 * 1024)
                return manifest
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError):
            return {
                "name": zip_path.stem,
                "path": str(zip_path),
                "size_mb": zip_path.stat().st_size / (1024 * 1024),
                "created_at": "unknown"
            }
    
    def print_backup_list(self, show_nas: bool = False):
        """Zeigt Backup-Liste formatiert an."""
        backups = self.list_backups(show_nas)
        
        location = "NAS" if show_nas else "Lokal"
        print(f"\n[BACKUPS] {location}")
        print("=" * 70)
        
        if not backups:
            print("  Keine Backups gefunden.")
        else:
            print(f"  {'Name':<35} {'Größe':>10} {'Datum':<20}")
            print("  " + "-" * 65)
            for b in backups:
                name = b.get("name", "?")[:35]
                size = f"{b.get('size_mb', 0):.2f} MB"
                date = b.get("created_at", "?")[:19]
                print(f"  {name:<35} {size:>10} {date:<20}")
        
        print("=" * 70)
    
    # ═══════════════════════════════════════════════════════════════
    # RESTORE BACKUP
    # ═══════════════════════════════════════════════════════════════
    
    def restore_backup(self, name: str, force: bool = False, 
                       auto_backup: bool = True) -> Tuple[bool, str]:
        """
        Stellt Userdaten aus Backup wieder her.
        
        Args:
            name: Backup-Name oder "latest"
            force: Ohne Bestätigung
            auto_backup: Vorher Auto-Backup erstellen
        """
        # Backup finden
        if name == "latest":
            backups = sorted(self.backups_dir.glob("userdata_*.zip"), reverse=True)
            if not backups:
                return False, "Keine Backups gefunden"
            zip_path = backups[0]
        else:
            zip_path = self.backups_dir / f"{name}.zip"
            if not zip_path.exists():
                zip_path = self.backups_dir / name
                if not zip_path.exists():
                    return False, f"Backup nicht gefunden: {name}"
        
        print(f"\n[RESTORE] Backup: {zip_path.name}")
        print("=" * 60)
        
        # Bestätigung
        if not force:
            print("\n  [!]  ACHTUNG: Dies überschreibt aktuelle Userdaten!")
            confirm = input("  Fortfahren? [y/N]: ").strip().lower()
            if confirm != 'y':
                return False, "Abgebrochen"
        
        # Auto-Backup
        if auto_backup:
            print("\n  -> Erstelle Auto-Backup...")
            self.create_backup()
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                
                # 1. Datenbank wiederherstellen
                if "db_export.json" in zf.namelist():
                    print("  -> Stelle Datenbank wieder her...")
                    db_export = json.loads(zf.read("db_export.json"))
                    self._restore_db_tables(db_export)
                
                # 2. Memory wiederherstellen
                print("  -> Stelle Memory wieder her...")
                for name in zf.namelist():
                    if name.startswith("memory/"):
                        target = BACH_DIR / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with open(target, 'wb') as f:
                            f.write(zf.read(name))
                
                # 3. Logs wiederherstellen
                print("  -> Stelle Logs wieder her...")
                for name in zf.namelist():
                    if name.startswith("logs/"):
                        target = BACH_DIR / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with open(target, 'wb') as f:
                            f.write(zf.read(name))
                
                # 4. User-Daten wiederherstellen
                print("  -> Stelle User-Daten wieder her...")
                for name in zf.namelist():
                    if name.startswith("user/"):
                        target = BACH_DIR / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with open(target, 'wb') as f:
                            f.write(zf.read(name))
            
            print("\n  [OK] Restore abgeschlossen!")
            print("=" * 60)
            return True, str(zip_path)
            
        except Exception as e:
            print(f"\n  [ERR] Fehler: {e}")
            return False, str(e)
    
    def _restore_db_tables(self, export: Dict):
        """Stellt Datenbank-Tabellen wieder her."""
        with self._get_db() as conn:
            
            # Tasks
            if "tasks" in export and export["tasks"]:
                conn.execute("DELETE FROM tasks")
                for task in export["tasks"]:
                    cols = ", ".join(task.keys())
                    placeholders = ", ".join(["?" for _ in task])
                    conn.execute(
                        f"INSERT OR REPLACE INTO tasks ({cols}) VALUES ({placeholders})",
                        list(task.values())
                    )
            
            # Memory Sessions
            if "memory_sessions" in export and export["memory_sessions"]:
                try:
                    conn.execute("DELETE FROM memory_sessions")
                    for session in export["memory_sessions"]:
                        cols = ", ".join(session.keys())
                        placeholders = ", ".join(["?" for _ in session])
                        conn.execute(
                            f"INSERT OR REPLACE INTO memory_sessions ({cols}) VALUES ({placeholders})",
                            list(session.values())
                        )
                except sqlite3.Error:
                    pass

            conn.commit()
    
    # ═══════════════════════════════════════════════════════════════
    # RESTORE TEMPLATE
    # ═══════════════════════════════════════════════════════════════
    
    def restore_template(self, filename: str) -> Tuple[bool, str]:
        """Setzt eine Template-Datei (dist_type=1) auf Original zurück."""
        orig_file = self.snapshots_dir / f"{filename}.orig"
        
        if not orig_file.exists():
            return False, f"Kein Snapshot gefunden: {filename}"
        
        # Ziel finden
        target = BACH_DIR / filename
        if not target.exists():
            # Suche in Unterordnern
            matches = list(BACH_DIR.rglob(filename))
            if matches:
                target = matches[0]
            else:
                return False, f"Ziel nicht gefunden: {filename}"
        
        print(f"\n[RESTORE] Template: {filename}")
        print("=" * 60)
        
        # Backup der aktuellen Version
        backup_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup_path)
        print(f"  -> Backup erstellt: {backup_path.name}")
        
        # Original wiederherstellen
        shutil.copy2(orig_file, target)
        print(f"  [OK] Wiederhergestellt: {target.name}")
        print("=" * 60)
        
        return True, str(target)
    
    def create_snapshot(self, filepath: Path) -> Tuple[bool, str]:
        """Erstellt Snapshot einer Template-Datei."""
        if not filepath.exists():
            return False, f"Datei nicht gefunden: {filepath}"
        
        orig_name = filepath.name + ".orig"
        orig_path = self.snapshots_dir / orig_name
        
        shutil.copy2(filepath, orig_path)
        return True, str(orig_path)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="BACH Backup & Restore Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s create                  Backup erstellen (lokal)
  %(prog)s create --to-nas         Backup erstellen + NAS
  %(prog)s list                    Lokale Backups anzeigen
  %(prog)s list --nas              NAS-Backups anzeigen
  %(prog)s info userdata_2026-01-14  Backup-Details
  %(prog)s restore backup latest   Neuestes Backup wiederherstellen
  %(prog)s restore template SKILL.md  Template zurücksetzen
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Befehle")
    
    # create
    p_create = subparsers.add_parser("create", help="Backup erstellen")
    p_create.add_argument("--to-nas", action="store_true", help="Auch auf NAS kopieren")
    
    # list
    p_list = subparsers.add_parser("list", help="Backups auflisten")
    p_list.add_argument("--nas", action="store_true", help="NAS-Backups anzeigen")
    
    # info
    p_info = subparsers.add_parser("info", help="Backup-Info anzeigen")
    p_info.add_argument("name", help="Backup-Name")
    
    # restore
    p_restore = subparsers.add_parser("restore", help="Wiederherstellen")
    p_restore.add_argument("type", choices=["backup", "template", "dist"], 
                          help="Was wiederherstellen")
    p_restore.add_argument("name", help="Name/Datei")
    p_restore.add_argument("--force", action="store_true", help="Ohne Bestätigung")
    p_restore.add_argument("--no-auto-backup", action="store_true", 
                          help="Kein Auto-Backup vor Restore")
    
    # snapshot
    p_snapshot = subparsers.add_parser("snapshot", help="Template-Snapshot erstellen")
    p_snapshot.add_argument("file", help="Datei für Snapshot")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    manager = BackupManager()
    
    if args.command == "create":
        success, msg = manager.create_backup(to_nas=args.to_nas)
        sys.exit(0 if success else 1)
    
    elif args.command == "list":
        manager.print_backup_list(show_nas=args.nas)
    
    elif args.command == "info":
        backups = manager.list_backups()
        for b in backups:
            if args.name in b.get("name", ""):
                print(json.dumps(b, indent=2, ensure_ascii=False))
                return
        print(f"Backup nicht gefunden: {args.name}")
    
    elif args.command == "restore":
        if args.type == "backup":
            success, msg = manager.restore_backup(
                args.name, 
                force=args.force,
                auto_backup=not args.no_auto_backup
            )
        elif args.type == "template":
            success, msg = manager.restore_template(args.name)
        elif args.type == "dist":
            print("Distribution-Restore noch nicht implementiert")
            success = False
        
        sys.exit(0 if success else 1)
    
    elif args.command == "snapshot":
        filepath = Path(args.file)
        if not filepath.is_absolute():
            filepath = BACH_DIR / filepath
        success, msg = manager.create_snapshot(filepath)
        if success:
            print(f"Snapshot erstellt: {msg}")
        else:
            print(f"Fehler: {msg}")


if __name__ == "__main__":
    main()
