# SPDX-License-Identifier: MIT
"""
BACH Distribution Handler
=========================
CLI-Handler fuer Distribution-System (dist_type-basiert).

Befehle:
    bach --dist status     System-Status anzeigen
    bach --dist verify     Siegel pruefen
    bach --dist snapshot   Snapshot erstellen
    bach --dist release    Release erstellen
    bach --dist classify   dist_type Verteilung anzeigen
    bach --dist list       Snapshots/Releases auflisten
"""

import sys
from pathlib import Path
from .base import BaseHandler

# Tools-Pfad hinzufuegen (fuer tools/distribution.py)
TOOLS_PATH = Path(__file__).parent.parent / "tools"
if str(TOOLS_PATH) not in sys.path:
    sys.path.insert(0, str(TOOLS_PATH))


from hub._services.ocean_stack_bridge import deprecated_legacy_bach
@deprecated_legacy_bach("bundle-installer")
class DistHandler(BaseHandler):
    """Handler fuer --dist Befehle"""
    
    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.tools_dir = base_path / "tools"
        self._dist_system = None
    
    @property
    def profile_name(self) -> str:
        return "dist"
    
    @property
    def target_file(self) -> Path:
        return self.tools_dir / "distribution.py"

    def get_operations(self) -> dict:
        return {
            "status": "System-Status (Siegel, dist_type Statistiken)",
            "verify": "Siegel-Integritaet pruefen",
            "classify": "dist_type Verteilung anzeigen",
            "snapshot": "Snapshot erstellen",
            "release": "Release erstellen",
            "restore": "Aus Distribution-ZIP wiederherstellen",
            "install": "Distribution in neuem Ordner installieren",
            "list": "Snapshots/Releases/ZIPs auflisten"
        }
    
    def _get_dist_system(self):
        """Lazy-load des Distribution-Managers."""
        if self._dist_system is None:
            try:
                from distribution import DistributionManager
                self._dist_system = DistributionManager()
            except ImportError as e:
                return None, f"[ERR] Konnte DistributionManager nicht laden: {e}"
            except Exception as e:
                return None, f"[ERR] Fehler beim Initialisieren: {e}"
        return self._dist_system, None
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not operation:
            return True, self._show_help()
        
        op = operation.lower()
        
        if op == "status":
            return self._show_status()
        elif op == "verify":
            return self._verify_seal()
        elif op == "classify":
            return self._classify()
        elif op == "snapshot":
            return self._create_snapshot(args, dry_run)
        elif op == "release":
            return self._create_release(args, dry_run)
        elif op == "restore":
            return self._restore_dist(args, dry_run)
        elif op == "install":
            return self._install_dist(args, dry_run)
        elif op == "list":
            return self._list_items(args)
        elif op in ["help", "-h"]:
            return True, self._show_help()
        else:
            return False, f"Unbekannter Befehl: {op}\n\n{self._show_help()}"
    
    def _show_help(self) -> str:
        """Zeigt Hilfe an."""
        lines = [
            "BACH Distribution System",
            "========================",
            "",
            "Befehle:",
            "  bach --dist status              System-Status anzeigen",
            "  bach --dist verify              Siegel pruefen",
            "  bach --dist classify            dist_type Verteilung anzeigen",
            "  bach --dist snapshot NAME       Snapshot erstellen",
            "  bach --dist snapshot --list     Snapshots auflisten",
            "  bach --dist release NAME        Release erstellen",
            "  bach --dist restore ZIP         Aus Distribution-ZIP wiederherstellen",
            "  bach --dist restore --list      Verfuegbare ZIPs anzeigen",
            "  bach --dist install ZIP ZIEL    Distribution in neuem Ordner installieren",
            "  bach --dist install --list      Verfuegbare ZIPs anzeigen",
            "  bach --dist list [snapshots|releases]  Auflisten",
            "",
            "Restore-Optionen:",
            "  --no-backup                     Kein Backup-Snapshot vor Restore",
            "  --target PFAD                   In anderes Verzeichnis extrahieren",
            "  --dry-run                       Nur simulieren",
            "",
            "Optionen:",
            "  --dry-run    Nur simulieren (bei snapshot/release)",
            ""
        ]
        return "\n".join(lines)
    
    def _show_status(self) -> tuple:
        """Zeigt System-Status (dist_type-basiert)."""
        dist, err = self._get_dist_system()
        if err:
            return False, err

        try:
            status = dist.status()

            lines = [
                "\n[DISTRIBUTION STATUS]",
                "=" * 50,
            ]

            # Siegel
            seal = status.get("seal", {})
            seal_icon = "[OK]" if seal.get("intact") else "[!!]"
            lines.append(f" Siegel: {seal_icon} {seal.get('message', 'Unbekannt')}")

            # Zahlen
            lines.append(f" Manifest: {status.get('manifest_count', 0)} Eintraege")
            lines.append(f" Snapshots: {status.get('snapshots', 0)}")
            lines.append(f" Releases: {status.get('releases_final', 0)} final / {status.get('releases_total', 0)} gesamt")

            # dist_type Verteilung
            dist_stats = status.get("dist_stats", {})
            if dist_stats:
                lines.append(f"\n dist_type Verteilung:")
                lines.append(f"   {'Tabelle':<12} {'Gesamt':>7} {'CORE':>6} {'TMPL':>6} {'USER':>6}")
                lines.append(f"   {'-'*40}")
                for tbl, vals in dist_stats.items():
                    lines.append(f"   {tbl:<12} {vals['total']:>7} {vals['core']:>6} {vals['template']:>6} {vals['user_data']:>6}")

            # Identitaet
            identity = status.get("identity")
            if identity:
                inst = identity.get("instance", {})
                if inst:
                    lines.append(f"\n[IDENTITAET]")
                    lines.append(f" Name: {inst.get('name', 'unbekannt')}")
                    lines.append(f" ID: {inst.get('id', 'unbekannt')}")

            lines.append("=" * 50)

            return True, "\n".join(lines)

        except Exception as e:
            return False, f"[ERR] Status-Abfrage fehlgeschlagen: {e}"
    
    def _verify_seal(self) -> tuple:
        """Prueft Siegel-Integritaet."""
        dist, err = self._get_dist_system()
        if err:
            return False, err
        
        try:
            intact, message = dist.verify_seal()
            
            if intact:
                return True, f"[OK] Siegel-Verifizierung: {message}"
            else:
                return False, f"[WARNUNG] Siegel-Verifizierung: {message}"
                
        except Exception as e:
            return False, f"[ERR] Verifizierung fehlgeschlagen: {e}"
    
    def _classify(self) -> tuple:
        """Zeigt dist_type Verteilung aus v_distribution_stats."""
        dist, err = self._get_dist_system()
        if err:
            return False, err

        try:
            stats = dist.classify()
            if not stats:
                return True, "[INFO] Keine dist_type-Statistiken verfuegbar"

            lines = [
                "\n[DIST_TYPE VERTEILUNG]",
                "=" * 50,
                f"  {'Tabelle':<12} {'Gesamt':>7} {'CORE(2)':>8} {'TMPL(1)':>8} {'USER(0)':>8}",
                f"  {'-'*44}",
            ]

            total_all = 0
            for tbl, vals in stats.items():
                lines.append(f"  {tbl:<12} {vals['total']:>7} {vals['core']:>8} {vals['template']:>8} {vals['user_data']:>8}")
                total_all += vals['total']

            lines.append(f"  {'-'*44}")
            lines.append(f"  {'GESAMT':<12} {total_all:>7}")
            lines.append("=" * 50)

            return True, "\n".join(lines)

        except Exception as e:
            return False, f"[ERR] Classify fehlgeschlagen: {e}"
    
    def _create_snapshot(self, args: list, dry_run: bool) -> tuple:
        """Erstellt Snapshot."""
        # --list Option
        if "--list" in args:
            return self._list_items(["snapshots"])
        
        if not args or args[0].startswith("-"):
            return False, "[ERR] Snapshot-Name erforderlich: bach --dist snapshot NAME"
        
        name = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else None
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Snapshot erstellen: {name}"
        
        dist, err = self._get_dist_system()
        if err:
            return False, err
        
        try:
            snapshot_id = dist.create_snapshot(name, description, "manual")
            if snapshot_id:
                return True, f"[OK] Snapshot erstellt: {name} (ID: {snapshot_id})"
            else:
                return False, f"[ERR] Snapshot konnte nicht erstellt werden (existiert bereits?)"
        except Exception as e:
            return False, f"[ERR] Snapshot-Erstellung fehlgeschlagen: {e}"
    
    def _create_release(self, args: list, dry_run: bool) -> tuple:
        """Erstellt Release."""
        if not args or args[0].startswith("-"):
            return False, "[ERR] Release-Name erforderlich: bach --dist release NAME"
        
        name = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else None
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Release erstellen: {name}"
        
        dist, err = self._get_dist_system()
        if err:
            return False, err
        
        try:
            release_id = dist.create_release(name, "base", description)
            if release_id:
                return True, f"[OK] Release erstellt: {name} (ID: {release_id})"
            else:
                return False, "[ERR] Release konnte nicht erstellt werden"
        except Exception as e:
            return False, f"[ERR] Release-Erstellung fehlgeschlagen: {e}"
    
    def _restore_dist(self, args: list, dry_run: bool) -> tuple:
        """Stellt aus Distribution-ZIP wieder her."""
        from pathlib import Path
        
        # --list Option: Zeige verfuegbare ZIPs
        if "--list" in args:
            dist, err = self._get_dist_system()
            if err:
                return False, err
            
            zips = dist.list_dist_zips()
            if not zips:
                return True, "[INFO] Keine Distribution-ZIPs in dist/ gefunden"
            
            lines = ["\n[VERFUEGBARE DISTRIBUTION-ZIPS]", "-" * 60]
            for z in zips:
                size_mb = z['size'] / (1024 * 1024)
                lines.append(f"  {z['name']:40} {size_mb:6.1f} MB  ({z['file_count']} Dateien)")
            lines.append("")
            lines.append("Nutzung: bach --dist restore DATEINAME.zip")
            return True, "\n".join(lines)
        
        # ZIP-Pfad ermitteln
        if not args or args[0].startswith("-"):
            return False, "[ERR] ZIP-Datei erforderlich: bach --dist restore DATEI.zip\n" + \
                         "      Verfuegbare ZIPs anzeigen: bach --dist restore --list"
        
        zip_arg = args[0]
        zip_path = Path(zip_arg)
        
        # Wenn nur Dateiname, in dist/ suchen
        if not zip_path.exists():
            dist_dir = self.base_path / "dist"
            zip_path = dist_dir / zip_arg
        
        if not zip_path.exists():
            return False, f"[ERR] ZIP nicht gefunden: {zip_arg}\n" + \
                         "      Verfuegbare ZIPs: bach --dist restore --list"
        
        # Optionen parsen
        no_backup = "--no-backup" in args
        target_dir = None
        for i, a in enumerate(args):
            if a == "--target" and i + 1 < len(args):
                target_dir = Path(args[i + 1])
        
        dist, err = self._get_dist_system()
        if err:
            return False, err
        
        try:
            result = dist.restore_from_dist(
                zip_path=zip_path,
                target_dir=target_dir,
                create_backup=not no_backup,
                dry_run=dry_run
            )
            
            if result.get("errors") and not result.get("restored"):
                return False, f"[ERR] Restore fehlgeschlagen: {result['errors']}"

            # NUL-Dateien entfernen nach Restore
            if not dry_run:
                try:
                    from tools.nulcleaner import clean_nul_files_headless
                    target = target_dir if target_dir else self.base_path
                    nul_result = clean_nul_files_headless(str(target), verbose=False)
                    if nul_result['found'] > 0:
                        result['nul_cleaned'] = nul_result['deleted']
                except Exception:
                    pass  # Silent fail

            lines = ["\n[DISTRIBUTION RESTORE]", "=" * 50]
            lines.append(f"  Quelle:  {zip_path.name}")
            lines.append(f"  Ziel:    {result.get('target_dir', self.base_path)}")
            lines.append(f"  Modus:   {'DRY-RUN' if dry_run else 'LIVE'}")
            lines.append("")
            lines.append(f"  Wiederhergestellt: {len(result.get('restored', []))}")
            lines.append(f"  Fehler:            {len(result.get('errors', []))}")
            if result.get('nul_cleaned'):
                lines.append(f"  NUL-Dateien:       {result['nul_cleaned']} entfernt")
            if result.get("backup_snapshot"):
                lines.append(f"  Backup-Snapshot:   {result['backup_snapshot']}")
            lines.append("=" * 50)
            
            return True, "\n".join(lines)
            
        except Exception as e:
            return False, f"[ERR] Restore fehlgeschlagen: {e}"
    
    def _install_dist(self, args: list, dry_run: bool) -> tuple:
        """
        Installiert BACH Distribution in neuem Ordner.
        
        Wrapper fuer restore --target mit vereinfachter Syntax.
        
        Nutzung:
            bach --dist install DATEI.zip ZIEL_ORDNER
            bach --dist install --list
        """
        from pathlib import Path
        
        # --list Option
        if "--list" in args or not args:
            return self._restore_dist(["--list"], dry_run)
        
        # Argumente parsen
        zip_arg = args[0] if args else None
        target_arg = args[1] if len(args) > 1 else None
        
        if not zip_arg or zip_arg.startswith("-"):
            return False, (
                "[ERR] ZIP-Datei und Zielordner erforderlich\n\n"
                "Nutzung:\n"
                "  bach --dist install DATEI.zip ZIEL_ORDNER\n"
                "  bach --dist install DATEI.zip C:\\Pfad\\Neuer\\Ordner\n"
                "  bach --dist install --list              (verfuegbare ZIPs anzeigen)\n\n"
                "Beispiel:\n"
                "  bach --dist install bach_vanilla_1.1.0.zip D:\\BACH_Test"
            )
        
        if not target_arg:
            return False, (
                "[ERR] Zielordner fehlt!\n\n"
                "Nutzung: bach --dist install DATEI.zip ZIEL_ORDNER\n\n"
                "Der Zielordner wird erstellt falls er nicht existiert.\n"
                "Bei bestehendem Ordner werden Dateien ueberschrieben."
            )
        
        # Zielordner vorbereiten
        target_dir = Path(target_arg)
        
        # Info anzeigen
        lines = [
            "\n[BACH DISTRIBUTION INSTALL]",
            "=" * 50,
            f"  Quelle:     {zip_arg}",
            f"  Ziel:       {target_dir}",
            f"  Modus:      {'DRY-RUN' if dry_run else 'LIVE'}",
            "=" * 50,
            ""
        ]
        
        # Zielordner erstellen falls noetig
        if not dry_run and not target_dir.exists():
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                lines.append(f"  [OK] Zielordner erstellt: {target_dir}")
            except Exception as e:
                return False, f"[ERR] Konnte Zielordner nicht erstellen: {e}"
        elif dry_run and not target_dir.exists():
            lines.append(f"  [DRY-RUN] Wuerde Ordner erstellen: {target_dir}")
        
        # restore --target aufrufen
        restore_args = [zip_arg, "--target", str(target_dir), "--no-backup"]
        success, result = self._restore_dist(restore_args, dry_run)
        
        if success:
            lines.append(result)
            lines.append("")
            
            # Systemordner automatisch anlegen
            system_dirs = [
                "user/_archive",
                "user/data-analysis", 
                "user/steuer",
                "logs",
                "messages"
            ]
            
            lines.append("[SYSTEMORDNER ERSTELLEN]")
            for dir_name in system_dirs:
                dir_path = target_dir / dir_name
                if dry_run:
                    lines.append(f"  [DRY-RUN] Wuerde erstellen: {dir_name}/")
                else:
                    try:
                        dir_path.mkdir(parents=True, exist_ok=True)
                        lines.append(f"  [OK] {dir_name}/")
                    except Exception as e:
                        lines.append(f"  [WARN] {dir_name}/ - {e}")
            
            lines.append("")
            lines.append("[NAECHSTE SCHRITTE]")
            lines.append(f"  cd {target_dir}")
            lines.append("  python bach.py --startup")
            return True, "\n".join(lines)
        else:
            return False, result
    
    def _list_items(self, args: list) -> tuple:
        """Listet Snapshots oder Releases."""
        dist, err = self._get_dist_system()
        if err:
            return False, err
        
        item_type = args[0] if args else "snapshots"
        
        try:
            if item_type.startswith("snap"):
                snapshots = dist.list_snapshots(20)
                if not snapshots:
                    return True, "[INFO] Keine Snapshots vorhanden"
                
                lines = ["\n[SNAPSHOTS]", "-" * 60]
                for s in snapshots:
                    lines.append(f"  {s['name']:30} {s['snapshot_date'][:16]}  ({s.get('file_count', '?')} Dateien)")
                return True, "\n".join(lines)
            
            elif item_type.startswith("rel"):
                releases = dist.list_releases(20)
                if not releases:
                    return True, "[INFO] Keine Releases vorhanden"

                lines = ["\n[RELEASES]", "-" * 60]
                for r in releases:
                    status_icon = "[OK]" if r.get('status') == 'final' else "[..]"
                    lines.append(f"  {status_icon} {r['version']:15} {str(r.get('release_date', ''))[:16]}  {r.get('status', '?')}")
                return True, "\n".join(lines)
            
            else:
                return False, f"[ERR] Unbekannter Typ: {item_type}. Nutze 'snapshots' oder 'releases'"
                
        except Exception as e:
            return False, f"[ERR] Auflisten fehlgeschlagen: {e}"
