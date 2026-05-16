# SPDX-License-Identifier: MIT
"""
Backup Handler - Backup-Verwaltung
==================================

--backup create          Backup erstellen
--backup create --to-nas Auch auf NAS kopieren
--backup list            Backups auflisten
--backup info <name>     Backup-Details
"""
import sys
from pathlib import Path
from datetime import datetime
from .base import BaseHandler
from .lang import t


class BackupHandler(BaseHandler):
    """Handler fuer --backup Operationen"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        # Backups LOKAL speichern — NICHT in OneDrive (OneDrive IST das Backup)
        if sys.platform == "win32":
            self.backups_dir = Path(r"C:\_Local_DEV\BACKUPS\BACH\userdata")
        else:
            self.backups_dir = Path.home() / ".bach" / "backups" / "userdata"
        self.tools_dir = base_path / "tools"
    
    @property
    def profile_name(self) -> str:
        return "backup"
    
    @property
    def target_file(self) -> Path:
        return self.backups_dir
    
    def get_operations(self) -> dict:
        return {
            "create": t("backup_create_desc", default="Backup erstellen (--to-nas fuer NAS-Kopie)"),
            "list": t("backup_list_desc", default="Alle Backups auflisten"),
            "info": t("backup_info_desc", default="Backup-Details anzeigen")
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "create":
            to_nas = "--to-nas" in args
            return self._create(to_nas, dry_run)
        elif operation == "list":
            show_nas = "--nas" in args
            return self._list(show_nas)
        elif operation == "info" and args:
            return self._info(args[0])
        else:
            return self._list(False)
    
    def _get_backup_manager(self):
        """Importiert BackupManager bei Bedarf."""
        sys.path.insert(0, str(self.tools_dir))
        try:
            from backup_manager import BackupManager
            return BackupManager()
        except ImportError as e:
            return None
    
    def _create(self, to_nas: bool, dry_run: bool) -> tuple:
        """Backup erstellen."""
        if dry_run:
            return True, f"[DRY-RUN] {t('wuerde_backup_erstellen', default='Wuerde Backup erstellen')}"
        
        manager = self._get_backup_manager()
        if manager:
            success, msg = manager.create_backup(to_nas=to_nas)
            return success, msg
        
        # Fallback ohne BackupManager
        return self._simple_backup()
    
    def _simple_backup(self) -> tuple:
        """Einfaches Backup ohne BackupManager."""
        import zipfile
        
        self.backups_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        zip_name = f"userdata_{timestamp}.zip"
        zip_path = self.backups_dir / zip_name
        
        # User-Daten sichern
        user_dirs = ["memory", "logs", "user"]
        
        results = [f"{t('erstelle_backup', default='Erstelle Backup')}: {zip_name}"]
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dir_name in user_dirs:
                dir_path = self.base_path / dir_name
                if dir_path.exists():
                    for item in dir_path.rglob("*"):
                        if item.is_file():
                            rel_path = item.relative_to(self.base_path)
                            zf.write(item, rel_path)
                            results.append(f"  + {rel_path}")
            
            # DB sichern
            db_path = self.base_path / "data" / "bach.db"
            if db_path.exists():
                zf.write(db_path, "data/bach.db")
                results.append("  + data/bach.db")
        
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        results.append(f"\n[OK] Backup erstellt: {zip_name} ({size_mb:.2f} MB)")
        
        return True, "\n".join(results)
    
    def _list(self, show_nas: bool) -> tuple:
        """Backups auflisten."""
        manager = self._get_backup_manager()
        if manager:
            backups = manager.list_backups(show_nas=show_nas)
            location = "NAS" if show_nas else "Lokal"
            results = [f"BACKUPS ({location})", "=" * 40]

            if not backups:
                return True, t("keine_backups", default="Keine Backups gefunden.")

            for backup in backups[:20]:
                name = backup.get("name") or Path(backup.get("path", "")).name
                size = f"{backup.get('size_mb', 0):.2f} MB"
                created = backup.get("created_at", "?")[:19]
                results.append(f"  {name:<35} {size:>8} ({created})")

            if len(backups) > 20:
                results.append(f"  ... und {len(backups) - 20} weitere")

            return True, "\n".join(results)

        results = ["BACKUPS", "=" * 40]
        
        if not self.backups_dir.exists():
            return True, t("keine_backups", default="Keine Backups gefunden.")

        backups = sorted(self.backups_dir.glob("*.zip"), reverse=True)

        if not backups:
            return True, t("keine_backups", default="Keine Backups gefunden.")
        
        for b in backups[:20]:
            size = f"{b.stat().st_size / (1024*1024):.2f} MB"
            mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            results.append(f"  {b.name:<35} {size:>8} ({mtime})")
        
        if len(backups) > 20:
            results.append(f"  ... und {len(backups) - 20} weitere")
        
        return True, "\n".join(results)
    
    def _info(self, name: str) -> tuple:
        """Backup-Info anzeigen."""
        import zipfile

        manager = self._get_backup_manager()
        if manager:
            backups = manager.list_backups(show_nas=False)
            matches = [
                backup for backup in backups
                if name in backup.get("name", "") or name in Path(backup.get("path", "")).name
            ]
            if not matches:
                return False, f"{t('backup_nicht_gefunden', default='Backup nicht gefunden')}: {name}"

            backup = matches[0]
            results = [f"BACKUP INFO: {backup.get('name', '?')}", "=" * 40]
            results.append(f"Pfad:   {backup.get('path', '?')}")
            results.append(f"Groesse: {backup.get('size_mb', 0):.2f} MB")
            results.append(f"Datum:  {backup.get('created_at', '?')}")
            contents = backup.get("contents", [])
            if contents:
                results.append(f"Dateien: {len(contents)}")
                results.append("\nInhalt (erste 10):")
                for item in contents[:10]:
                    results.append(f"  {item}")
                if len(contents) > 10:
                    results.append(f"  ... und {len(contents) - 10} weitere")

            return True, "\n".join(results)
        
        # Backup finden
        matches = list(self.backups_dir.glob(f"*{name}*"))
        if not matches:
            return False, f"{t('backup_nicht_gefunden', default='Backup nicht gefunden')}: {name}"
        
        backup = matches[0]
        
        results = [f"BACKUP INFO: {backup.name}", "=" * 40]
        results.append(f"Pfad:   {backup}")
        results.append(f"Groesse: {backup.stat().st_size / (1024*1024):.2f} MB")
        results.append(f"Datum:  {datetime.fromtimestamp(backup.stat().st_mtime)}")
        
        try:
            with zipfile.ZipFile(backup, 'r') as zf:
                files = zf.namelist()
                results.append(f"Dateien: {len(files)}")
                results.append("\nInhalt (erste 10):")
                for f in files[:10]:
                    results.append(f"  {f}")
                if len(files) > 10:
                    results.append(f"  ... und {len(files) - 10} weitere")
        except Exception as e:
            results.append(f"[FEHLER] {e}")
        
        return True, "\n".join(results)
