# SPDX-License-Identifier: MIT
"""
Steuer Handler - Steuerbelegs-Verwaltung
========================================

steuer status            Status anzeigen
steuer scan              Watch-Ordner pruefen  
steuer init YYYY         Neues Steuerjahr anlegen
steuer list              Listen anzeigen
steuer profile list      Profile auflisten
steuer profile show NAME Profil anzeigen
steuer profile create    Neues Profil erstellen
steuer watch list        Watch-Ordner anzeigen
steuer watch add PFAD    Watch-Ordner hinzufuegen
steuer export            Exportieren

steuer posten list       Posten anzeigen (--liste W|G|V|Z, --belegnr NR)
steuer posten show ID    Einzelnen Posten anzeigen (z.B. 151-1)
steuer posten add        Neuen Posten erstellen (interaktiv oder mit Parametern)
steuer posten edit ID    Posten bearbeiten
steuer posten move ID L  Posten in Liste verschieben (W/G/V/Z)
steuer posten delete ID  Posten loeschen

steuer beleg scan        Neue Belege in belege/ finden und nummerieren
steuer beleg deprecate VON BIS [GRUND]  Belege als ungueltig markieren
steuer beleg list        Alle Belege auflisten (--status ERFASST|NICHT_ERFASST|DEPRECATED)

steuer batch posten      Mehrere Posten fuer einen Beleg (JSON/interaktiv)
steuer batch belege      Mehrere Belege mit Posten im Batch (JSON-Datei)
steuer batch help        Batch-Hilfe anzeigen
"""
import sys
import json
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
from .base import BaseHandler


class SteuerHandler(BaseHandler):
    """Handler fuer Steuer-Operationen"""
    
    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.steuer_dir = self.base_path.parent / "user" / "steuer"  # FIX: base_path=system/, user/ ist eine Ebene höher (BACH_ROOT/user/)
        self.profile_dir = self.steuer_dir / "profile"
        self.watch_dir = self.steuer_dir / "watch"
        self.templates_dir = self.steuer_dir / "templates"
        self.db_path = self._canonical_db
        self.username = "user"  # Default, spaeter aus Config

    @staticmethod
    def _parse_posten_id(posten_id: str):
        """Parse '42-3' -> (42, 3) or None on error."""
        parts = posten_id.split("-", 1)
        if len(parts) != 2:
            return None
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None
    
    @property
    def profile_name(self) -> str:
        return "steuer"
    
    @property
    def target_file(self) -> Path:
        return self.steuer_dir
    
    def get_operations(self) -> dict:
        return {
            "status": "Status anzeigen (--jahr YYYY, --user NAME)",
            "scan": "Watch-Ordner auf neue Belege pruefen",
            "init": "Neues Steuerjahr anlegen (init YYYY [--user NAME])",
            "list": "Listen anzeigen (--jahr YYYY, --liste NAME)",
            "profile": "Profil-Verwaltung (list, show NAME, create NAME)",
            "watch": "Watch-Ordner verwalten (list, add PFAD, remove PFAD)",
            "export": "Exportieren (--jahr YYYY, --format txt|xlsx)",
            "posten": "Posten verwalten (list, show, add, edit, move, delete)",
            "beleg": "Beleg-Verwaltung (scan, deprecate, list, sync)",
            "batch": "Batch-Import (posten, belege, delete, move)",
            "tools": "Steuer-Tools anzeigen und ausfuehren",
            "check": "Vollstaendigkeitspruefung (--jahr YYYY)",
            "eigenbeleg": "Eigenbeleg erstellen (--bezeichnung --brutto --liste)"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "help":
            return self._show_help()
        elif operation == "status":
            return self._status(args)
        elif operation == "scan":
            return self._scan(args, dry_run)
        elif operation == "init":
            return self._init_year(args, dry_run)
        elif operation == "list":
            return self._list(args)
        elif operation == "profile":
            return self._profile(args, dry_run)
        elif operation == "watch":
            return self._watch(args, dry_run)
        elif operation == "export":
            return self._export(args)
        elif operation == "posten":
            return self._posten(args, dry_run)
        elif operation == "beleg":
            return self._beleg(args, dry_run)
        elif operation == "batch":
            return self._batch(args, dry_run)
        elif operation == "tools":
            return self._tools(args, dry_run)
        elif operation == "import":
            if args and args[0] == "camt":
                return self._import_camt(args[1:], dry_run)
            return False, "Unbekannter Import-Befehl."
        elif operation == "check":
            return self._check(args)
        elif operation == "eigenbeleg":
            return self._eigenbeleg(args, dry_run)
        elif operation == "year":
            # Legacy-Kompatibilitaet
            if args and args[0] == "create":
                return self._init_year(args[1:], dry_run)
            return self._init_year(args, dry_run)
        else:
            return self._status([])
    
    def _show_help(self) -> tuple:
        """Zeigt Steuer-Hilfe an."""
        help_file = self.base_path / "help" / "steuer.txt"
        if help_file.exists():
            return True, help_file.read_text(encoding='utf-8')
        else:
            return True, """STEUER-AGENT HILFE

Ausfuehrliche Hilfe: bach --help steuer

Kurzuebersicht:
  steuer status        Status anzeigen
  steuer posten add    Posten erfassen
  steuer posten list   Posten auflisten
  steuer beleg scan    Belege scannen

Batch-Tools:
  python tools/make_bundle.py <quelle> <start> <ende>
  python tools/regenerate_txt.py
"""
    
    # ═══════════════════════════════════════════════════════════════
    # STATUS
    # ═══════════════════════════════════════════════════════════════
    
    def _status(self, args: list) -> tuple:
        """Status anzeigen."""
        results = ["", "STEUER-AGENT STATUS", "=" * 50]

        # Auto-Init: Steuerjahr sicherstellen
        success, active_year = self._ensure_active_year()
        if not success:
            return False, "Fehler bei Steuerjahr-Initialisierung"

        # Profile zaehlen
        profiles = list(self.profile_dir.glob("*.txt")) if self.profile_dir.exists() else []
        results.append(f"\nProfile:        {len(profiles)}")
        if profiles:
            results.append(f"                {', '.join([p.stem for p in profiles])}")

        # Jahre zaehlen
        years = sorted([d.name for d in self.steuer_dir.iterdir()
                       if d.is_dir() and d.name.isdigit()])
        results.append(f"\nSteuerjahre:    {len(years)}")
        if years:
            results.append(f"                {', '.join(years)}")
            results.append(f"Aktives Jahr:   {active_year}")
        
        # Watch-Ordner Status
        watch_config = self._get_watch_config()
        aktive_watches = [w for w in watch_config if w.get('aktiv', True)]
        results.append(f"\nWatch-Ordner:   {len(aktive_watches)} aktiv")
        
        # Jahr-Details wenn angegeben
        jahr = self._get_arg(args, "--jahr")
        if jahr and jahr in years:
            results.extend(self._get_year_details(jahr))
        elif years:
            # Neuestes Jahr zeigen
            results.extend(self._get_year_details(years[-1]))
        
        results.append("")
        return True, "\n".join(results)
    
    def _get_year_details(self, jahr: str) -> list:
        """Details fuer ein Steuerjahr."""
        results = [f"\n--- STEUERJAHR {jahr} ---"]
        jahr_dir = self.steuer_dir / jahr
        
        if not jahr_dir.exists():
            return [f"Jahr {jahr} nicht gefunden."]
        
        # Belege zaehlen
        belege_dir = jahr_dir / "belege"
        if belege_dir.exists():
            belege = [f for f in belege_dir.iterdir() if f.is_file()]
            results.append(f"Belege:         {len(belege)}")
        
        # Listen-Status
        listen = ["WERBUNGSKOSTEN", "GEMISCHTE_POSTEN", "ZURUECKGESTELLTE_POSTEN"]
        for liste in listen:
            list_file = jahr_dir / f"{liste}.txt"
            if list_file.exists():
                # Posten zaehlen (einfache Heuristik)
                content = list_file.read_text(encoding='utf-8')
                lines = [l for l in content.split('\n') if l.strip().startswith(('1','2','3','4','5','6','7','8','9'))]
                results.append(f"{liste[:15]:<16} {len(lines)} Posten")
        
        return results
    
    # ═══════════════════════════════════════════════════════════════
    # SCAN - Watch-Ordner pruefen
    # ═══════════════════════════════════════════════════════════════
    
    def _scan(self, args: list, dry_run: bool) -> tuple:
        """Watch-Ordner pruefen."""
        results = ["", "WATCH-ORDNER SCAN", "=" * 50]
        
        watch_config = self._get_watch_config()
        aktive = [w for w in watch_config if w.get('aktiv', True)]
        
        if not aktive:
            return True, "Keine aktiven Watch-Ordner konfiguriert.\nNutze: bach steuer watch add PFAD"
        
        total_found = 0
        all_files = []
        
        for watch in aktive:
            pfad = Path(watch['pfad'])
            results.append(f"\n[{pfad.name}]")
            
            if not pfad.exists():
                results.append(f"  WARNUNG: Ordner nicht gefunden!")
                continue
            
            # Dateien finden
            extensions = ['.pdf', '.jpg', '.jpeg', '.png']
            files = []
            for ext in extensions:
                files.extend(pfad.glob(f"*{ext}"))
                files.extend(pfad.glob(f"*{ext.upper()}"))
            
            if files:
                results.append(f"  Gefunden: {len(files)} Dokumente")
                for f in files[:5]:  # Max 5 anzeigen
                    size = f"{f.stat().st_size / 1024:.1f} KB"
                    results.append(f"    - {f.name:<35} {size}")
                if len(files) > 5:
                    results.append(f"    ... und {len(files) - 5} weitere")
                
                total_found += len(files)
                all_files.extend(files)
            else:
                results.append(f"  Keine neuen Dokumente")
        
        results.append(f"\n{'=' * 50}")
        results.append(f"GESAMT: {total_found} neue Dokumente gefunden")
        
        if total_found > 0:
            results.append("\nNutze den Chat-Agent um die Belege zu erfassen.")
        
        return True, "\n".join(results)
    
    def _get_watch_config(self) -> list:
        """Watch-Konfiguration lesen."""
        config_file = self.watch_dir / "config.txt"
        if not config_file.exists():
            return []
        
        watches = []
        content = config_file.read_text(encoding='utf-8')
        
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('[AKTIV]') or line.startswith('[INAKTIV]'):
                parts = line.split('|')
                if len(parts) >= 2:
                    aktiv = line.startswith('[AKTIV]')
                    pfad = parts[0].replace('[AKTIV]', '').replace('[INAKTIV]', '').strip()
                    modus = parts[1].strip() if len(parts) > 1 else 'bei_start'
                    profil = parts[2].strip() if len(parts) > 2 else None
                    watches.append({
                        'pfad': pfad,
                        'aktiv': aktiv,
                        'modus': modus,
                        'profil': profil
                    })
        
        return watches
    
    # ═══════════════════════════════════════════════════════════════
    # INIT - Neues Steuerjahr
    # ═══════════════════════════════════════════════════════════════
    
    def _init_year(self, args: list, dry_run: bool) -> tuple:
        """Steuerjahr anlegen."""
        if not args:
            return False, "Steuerjahr fehlt.\nUsage: bach steuer init 2025"
        
        jahr = args[0]
        if not jahr.isdigit() or len(jahr) != 4:
            return False, f"Ungueltiges Jahr: {jahr}\nUsage: bach steuer init 2025"
        
        jahr_dir = self.steuer_dir / jahr
        
        if jahr_dir.exists():
            return False, f"Steuerjahr {jahr} existiert bereits.\nPfad: {jahr_dir}"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Steuerjahr {jahr} erstellen"
        
        # User-Parameter
        user = self._get_arg(args, "--user") or "default"
        
        # Steuer-Kategorien (Hauptordner)
        (jahr_dir / "Außergewöhnliche Belastungen").mkdir(parents=True, exist_ok=True)
        (jahr_dir / "Haushaltsnahe Dienstleistungen & Handwerker").mkdir(exist_ok=True)
        (jahr_dir / "Sonderausgaben").mkdir(exist_ok=True)
        (jahr_dir / "Versicherungen und Altersvorsorge").mkdir(exist_ok=True)

        # Werbungskosten mit Unterstruktur
        wk = jahr_dir / "Werbungskosten"
        (wk / "belege" / "_bundles").mkdir(parents=True, exist_ok=True)
        (wk / "belege" / "_Fahrten&Homeoffice").mkdir(parents=True, exist_ok=True)
        (wk / "belege" / "_Fehlbelege").mkdir(parents=True, exist_ok=True)
        (wk / "belege" / "_Papierkorb").mkdir(parents=True, exist_ok=True)
        (wk / "belege" / "Weitere").mkdir(parents=True, exist_ok=True)
        (wk / "export" / "csv").mkdir(parents=True, exist_ok=True)

        # Templates kopieren und anpassen
        if self.templates_dir.exists():
            for template in self.templates_dir.glob("*.txt"):
                content = template.read_text(encoding='utf-8')
                content = content.replace("[JAHR]", jahr)
                content = content.replace("[PROFIL]", user)
                (wk / template.name).write_text(content, encoding='utf-8')
        else:
            # Fallback: Minimale Dateien erstellen
            self._create_minimal_files(wk, jahr, user)

        return True, f"Steuerjahr {jahr} erstellt.\nPfad: {jahr_dir}\n\nNaechste Schritte:\n1. Belege in {wk / 'belege' / 'Weitere'} ablegen\n2. Chat-Agent starten zur Erfassung"
    
    def _create_minimal_files(self, jahr_dir: Path, jahr: str, user: str):
        """Minimale Dateien erstellen wenn keine Templates."""
        files = {
            "WERBUNGSKOSTEN.txt": f"WERBUNGSKOSTEN {jahr}\n{'='*40}\nUser: {user}\n",
            "GEFILTERTE_POSTEN.txt": f"GEFILTERTE POSTEN {jahr}\n{'='*40}\n",
            "GEMISCHTE_POSTEN.txt": f"GEMISCHTE POSTEN {jahr}\n{'='*40}\n",
            "ZURUECKGESTELLTE_POSTEN.txt": f"ZURUECKGESTELLTE POSTEN {jahr}\n{'='*40}\n",
            "DOKUMENTENVERZEICHNIS.txt": f"DOKUMENTENVERZEICHNIS {jahr}\n{'='*40}\n",
            "POSTENVERZEICHNIS.txt": f"POSTENVERZEICHNIS {jahr}\n{'='*40}\n"
        }
        for name, content in files.items():
            (jahr_dir / name).write_text(content, encoding='utf-8')
    
    # ═══════════════════════════════════════════════════════════════
    # ENSURE ACTIVE YEAR - Auto-Init wenn kein Jahr vorhanden
    # ═══════════════════════════════════════════════════════════════

    def _ensure_active_year(self, target_year: str = None) -> tuple:
        """Stellt sicher, dass ein aktives Steuerjahr existiert. Auto-Init wenn noetig.

        Returns:
            (success: bool, active_year: str or None)
        """
        from datetime import datetime as dt
        if target_year is None:
            target_year = str(dt.now().year)

        if not self.steuer_dir.exists():
            self.steuer_dir.mkdir(parents=True, exist_ok=True)

        years = sorted([d.name for d in self.steuer_dir.iterdir()
                       if d.is_dir() and d.name.isdigit()])

        if target_year in years:
            return True, target_year

        if not years:
            success, message = self._init_year([target_year], dry_run=False)
            if success:
                print(f"[AUTO-INIT] Steuerjahr {target_year} automatisch erstellt")
                return True, target_year
            else:
                return False, None

        return True, years[-1]

    # ═══════════════════════════════════════════════════════════════
    # LIST - Listen anzeigen
    # ═══════════════════════════════════════════════════════════════
    
    def _list(self, args: list) -> tuple:
        """Listen anzeigen."""
        # Jahr ermitteln
        jahr = self._get_arg(args, "--jahr")
        liste = self._get_arg(args, "--liste")
        
        if not jahr:
            success, active_year = self._ensure_active_year()
            if success:
                jahr = active_year
            else:
                return False, "Fehler bei Steuerjahr-Initialisierung"
        
        jahr_dir = self.steuer_dir / jahr
        if not jahr_dir.exists():
            return False, f"Steuerjahr {jahr} nicht gefunden."
        
        if liste:
            # Spezifische Liste anzeigen
            list_file = jahr_dir / f"{liste.upper()}.txt"
            if not list_file.exists():
                list_file = jahr_dir / f"{liste}.txt"
            
            if list_file.exists():
                return True, list_file.read_text(encoding='utf-8')
            else:
                return False, f"Liste nicht gefunden: {liste}"
        else:
            # Alle Listen auflisten
            results = [f"\nLISTEN - STEUERJAHR {jahr}", "=" * 50]
            for f in sorted(jahr_dir.glob("*.txt")):
                size = f"{f.stat().st_size / 1024:.1f} KB"
                results.append(f"  {f.stem:<35} {size}")
            results.append(f"\nAnzeigen mit: bach steuer list --liste NAME --jahr {jahr}")
            return True, "\n".join(results)
    
    # ═══════════════════════════════════════════════════════════════
    # PROFILE - Profilverwaltung
    # ═══════════════════════════════════════════════════════════════
    
    def _profile(self, args: list, dry_run: bool) -> tuple:
        """Profil-Verwaltung."""
        if not args:
            return self._profile_list()
        
        sub_cmd = args[0]
        
        if sub_cmd == "list":
            return self._profile_list()
        elif sub_cmd == "show":
            name = args[1] if len(args) > 1 else None
            return self._profile_show(name)
        elif sub_cmd == "create":
            name = args[1] if len(args) > 1 else None
            return self._profile_create(name, dry_run)
        else:
            # Direkt Name angegeben
            return self._profile_show(sub_cmd)
    
    def _profile_list(self) -> tuple:
        """Profile auflisten."""
        if not self.profile_dir.exists():
            return True, "Keine Profile gefunden.\nNutze: bach steuer profile create NAME"
        
        profiles = list(self.profile_dir.glob("*.txt"))
        if not profiles:
            return True, "Keine Profile gefunden."
        
        results = ["\nPROFILE", "=" * 50]
        for p in profiles:
            # Beruf aus Profil lesen
            content = p.read_text(encoding='utf-8')
            beruf = ""
            for line in content.split('\n'):
                if line.startswith("Beruf:"):
                    beruf = line.replace("Beruf:", "").strip()
                    break
            results.append(f"  {p.stem:<20} {beruf}")
        
        results.append(f"\nDetails: bach steuer profile show NAME")
        return True, "\n".join(results)
    
    def _profile_show(self, name: str = None) -> tuple:
        """Profil anzeigen."""
        if not name:
            return self._profile_list()
        
        profile_file = self.profile_dir / f"{name}.txt"
        if not profile_file.exists():
            return False, f"Profil nicht gefunden: {name}"
        
        return True, profile_file.read_text(encoding='utf-8')
    
    def _profile_create(self, name: str, dry_run: bool) -> tuple:
        """Profil erstellen."""
        if not name:
            return False, "Profilname fehlt.\nUsage: bach steuer profile create NAME"
        
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        new_profile = self.profile_dir / f"{name}.txt"
        
        if new_profile.exists():
            return False, f"Profil existiert bereits: {name}"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Profil {name} erstellen"
        
        content = f"""============================================================
STEUER-PROFIL: {name.upper()}
============================================================

Erstellt: {datetime.now().strftime('%Y-%m-%d')}
Version: 1.0.0

------------------------------------------------------------
PERSOENLICHE DATEN
------------------------------------------------------------

Name:               {name}
Aktives Steuerjahr: [wird pro Session gesetzt]

------------------------------------------------------------
BERUFLICHER KONTEXT
------------------------------------------------------------

Beruf:              
Branche:            

Absetzbare Kategorien:
- 
- 

------------------------------------------------------------
NOTIZEN
------------------------------------------------------------

"""
        new_profile.write_text(content, encoding='utf-8')
        return True, f"Profil erstellt: {name}\nBearbeite: {new_profile}"
    
    # ═══════════════════════════════════════════════════════════════
    # WATCH - Watch-Ordner verwalten
    # ═══════════════════════════════════════════════════════════════
    
    def _watch(self, args: list, dry_run: bool) -> tuple:
        """Watch-Ordner verwalten."""
        if not args:
            return self._watch_list()
        
        sub_cmd = args[0]
        
        if sub_cmd == "list":
            return self._watch_list()
        elif sub_cmd == "add":
            pfad = args[1] if len(args) > 1 else None
            return self._watch_add(pfad, dry_run)
        elif sub_cmd == "remove":
            pfad = args[1] if len(args) > 1 else None
            return self._watch_remove(pfad, dry_run)
        else:
            return self._watch_list()
    
    def _watch_list(self) -> tuple:
        """Watch-Ordner auflisten."""
        watches = self._get_watch_config()
        
        if not watches:
            return True, "Keine Watch-Ordner konfiguriert.\nNutze: bach steuer watch add PFAD"
        
        results = ["\nWATCH-ORDNER", "=" * 50]
        for w in watches:
            status = "[AKTIV]" if w.get('aktiv', True) else "[INAKTIV]"
            pfad = Path(w['pfad'])
            exists = "[OK]" if pfad.exists() else "[FEHLT]"
            results.append(f"  {status:<10} {exists:<8} {w['pfad']}")
        
        results.append(f"\nPruefen: bach steuer scan")
        return True, "\n".join(results)
    
    def _watch_add(self, pfad: str, dry_run: bool) -> tuple:
        """Watch-Ordner hinzufuegen."""
        if not pfad:
            return False, r"Pfad fehlt.\nUsage: bach steuer watch add C:\Pfad\zum\Ordner"
        
        pfad_obj = Path(pfad)
        if not pfad_obj.exists():
            return False, f"Ordner existiert nicht: {pfad}"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Watch-Ordner hinzufuegen: {pfad}"
        
        # Config-Datei aktualisieren
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        config_file = self.watch_dir / "config.txt"
        
        if config_file.exists():
            content = config_file.read_text(encoding='utf-8')
            if pfad in content:
                return False, f"Ordner bereits konfiguriert: {pfad}"
            
            # Neue Zeile hinzufuegen
            new_line = f"[AKTIV]  {pfad} | bei_start   | default"
            
            # Nach "UEBERWACHTE ORDNER" einfuegen
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if "Format:" in line:
                    lines.insert(i + 2, new_line)
                    break
            else:
                lines.append(new_line)
            
            config_file.write_text('\n'.join(lines), encoding='utf-8')
        else:
            # Neue Config erstellen
            self._create_watch_config(pfad)
        
        return True, f"Watch-Ordner hinzugefuegt: {pfad}"
    
    def _watch_remove(self, pfad: str, dry_run: bool) -> tuple:
        """Watch-Ordner entfernen."""
        if not pfad:
            return False, "Pfad fehlt."
        
        config_file = self.watch_dir / "config.txt"
        if not config_file.exists():
            return False, "Keine Watch-Konfiguration gefunden."
        
        content = config_file.read_text(encoding='utf-8')
        if pfad not in content:
            return False, f"Ordner nicht in Konfiguration: {pfad}"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde Watch-Ordner entfernen: {pfad}"
        
        # Zeile entfernen
        lines = [l for l in content.split('\n') if pfad not in l]
        config_file.write_text('\n'.join(lines), encoding='utf-8')
        
        return True, f"Watch-Ordner entfernt: {pfad}"
    
    def _create_watch_config(self, initial_path: str):
        """Neue Watch-Config erstellen."""
        content = f"""============================================================
WATCHER-KONFIGURATION
============================================================

Version:            1.0.0
Letzte Aenderung:   {datetime.now().strftime('%Y-%m-%d')}

------------------------------------------------------------
UEBERWACHTE ORDNER
------------------------------------------------------------

Format: [STATUS] PFAD | SCAN_MODUS | ZIEL_PROFIL

[AKTIV]  {initial_path} | bei_start   | default

------------------------------------------------------------
SCAN-MODI
------------------------------------------------------------

bei_start    = Nur beim Chat-Start pruefen
manuell      = Nur auf explizite Anfrage
"""
        config_file = self.watch_dir / "config.txt"
        config_file.write_text(content, encoding='utf-8')
    
    # ═══════════════════════════════════════════════════════════════
    # EXPORT
    # ═══════════════════════════════════════════════════════════════
    
    def _export(self, args: list) -> tuple:
        """Export-Funktion.
        
        Formate:
        - txt:   Standard TXT-Dateien (bereits vorhanden)
        - datev: DATEV Buchungsstapel CSV
        - csv:   Einfaches CSV fuer Excel
        """
        jahr = self._get_arg(args, "--jahr")
        format_type = self._get_arg(args, "--format") or "txt"
        liste = self._get_arg(args, "--liste")  # Optional: nur bestimmte Liste
        
        if not jahr:
            years = sorted([d.name for d in self.steuer_dir.iterdir() 
                           if d.is_dir() and d.name.isdigit()])
            if years:
                jahr = years[-1]
            else:
                return False, "Kein Steuerjahr gefunden."
        
        if format_type == "txt":
            return True, f"TXT-Export: Dateien befinden sich in\n{self.steuer_dir / jahr}"
        elif format_type == "datev":
            return self._export_datev(jahr, liste)
        elif format_type == "csv":
            return self._export_csv(jahr, liste)
        elif format_type == "vorsorge":
            return self._export_vorsorgeaufwand(jahr)
        else:
            return True, f"""Format '{format_type}' nicht unterstuetzt.

Verfuegbare Formate:
  --format txt      Standard TXT-Dateien
  --format datev    DATEV Buchungsstapel CSV (fuer Steuerberater)
  --format csv      Einfaches CSV (fuer Excel)
  --format vorsorge Anlage Vorsorgeaufwand (Versicherungsbeitraege)

Beispiel:
  bach steuer export --jahr 2025 --format datev
  bach steuer export --format vorsorge"""
    
    def _export_datev(self, jahr: str, liste: str = None) -> tuple:
        """DATEV Buchungsstapel CSV Export.
        
        Erstellt DATEV-kompatible CSV nach Buchungsstapel-Format.
        Kontenrahmen: SKR04 (Standard fuer Freiberufler)
        
        SKR04 Konten:
        - 6000-6999: Betriebsausgaben (hier: 6800 Arbeitsmittel)
        - 1890: Privateinlagen (Gegenkonto fuer Privatausgaben)
        """
        import csv
        import sys
        sys.path.insert(0, str(self.base_path / "tools"))
        from skr04_mapper import get_mapper
        
        # SKR04 Konten-Mapping (via skr04_mapper.py + skr04_konten.json)
        mapper = get_mapper()
        
        # Fallback fuer nicht exportierbare Listen
        skip_listen = ["VERWORFEN", "ZURUECKGESTELLT"]
        
        try:
            conn = self._get_db()
            
            # Posten abfragen
            sql = """SELECT dokument_id || '-' || postennr AS posten_id_str,
                            bezeichnung, datum, brutto, netto,
                            liste, anteil, absetzbar_brutto, rechnungssteller,
                            dokument_id, dateiname
                     FROM steuer_posten
                     WHERE username = ? AND steuerjahr = ?"""
            params = [self.username, int(jahr)]

            if liste:
                liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE"}
                liste_full = liste_map.get(liste.upper(), liste.upper())
                sql += " AND liste = ?"
                params.append(liste_full)
            else:
                # Nur absetzbare Listen exportieren
                sql += " AND liste IN ('WERBUNGSKOSTEN', 'GEMISCHTE')"

            sql += " ORDER BY datum, dokument_id"
            
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            
            if not rows:
                return False, f"Keine exportierbaren Posten fuer {jahr} gefunden."
            
            # Export-Verzeichnis
            export_dir = self.steuer_dir / jahr / "export"
            export_dir.mkdir(exist_ok=True)
            
            # DATEV Header (Buchungsstapel)
            datev_file = export_dir / f"DATEV_Buchungsstapel_{jahr}_{datetime.now().strftime('%Y%m%d')}.csv"
            
            with open(datev_file, 'w', newline='', encoding='cp1252') as f:
                writer = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
                
                # DATEV Header-Zeilen (vereinfacht)
                writer.writerow([
                    "EXTF", "700", "21", "Buchungsstapel", "13", "",
                    datetime.now().strftime('%Y%m%d%H%M%S000'), "", "RE", "", 
                    self.username, "", "", "", "", "", "", "", "", "", "", "", "", ""
                ])
                
                # Spaltenheader
                writer.writerow([
                    "Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen",
                    "WKZ Umsatz", "Kurs", "Basis-Umsatz", "WKZ Basis-Umsatz",
                    "Konto", "Gegenkonto (ohne BU-Schlüssel)", "BU-Schlüssel",
                    "Belegdatum", "Belegfeld 1", "Belegfeld 2",
                    "Skonto", "Buchungstext", "Postensperre", "Diverse Adressnummer",
                    "Geschäftspartnerbank", "Sachverhalt", "Zinssperre", "Beleglink",
                    "Beleginfo - Art 1", "Beleginfo - Inhalt 1",
                    "Beleginfo - Art 2", "Beleginfo - Inhalt 2"
                ])
                
                # Datenzeilen
                exported = 0
                for r in rows:
                    # Nicht exportierbare Listen ueberspringen
                    if r['liste'] in skip_listen:
                        continue
                    
                    # Intelligentes Konto-Mapping (via SKR04Mapper)
                    konto = mapper.get_konto(dict(r))
                    
                    # Absetzbar-Betrag verwenden (bei Gemischten bereits berechnet)
                    betrag = r['absetzbar_brutto'] or r['brutto']
                    
                    # Datum formatieren (TTMM)
                    try:
                        datum_obj = datetime.strptime(r['datum'], '%Y-%m-%d')
                        datum_datev = datum_obj.strftime('%d%m')
                    except (ValueError, TypeError):
                        datum_datev = ""
                    
                    # Buchungstext (max 60 Zeichen)
                    buchungstext = f"{r['rechnungssteller'] or ''} {r['bezeichnung'] or ''}"[:60]
                    
                    writer.writerow([
                        f"{betrag:.2f}".replace(".", ","),  # Umsatz
                        "S",                                  # Soll
                        "EUR", "", "", "",                    # Währung
                        konto,                                # Konto (Aufwand)
                        "1890",                               # Gegenkonto (Privateinlage)
                        "",                                   # BU-Schlüssel
                        datum_datev,                          # Belegdatum
                        f"B{r['dokument_id']:04d}",           # Belegfeld 1
                        r['posten_id_str'],                   # Belegfeld 2
                        "", buchungstext, "", "", "", "", "",
                        r['dateiname'] or "", "", "", "", ""
                    ])
                    exported += 1
            
            results = [f"\nDATEV-EXPORT {jahr}", "=" * 50]
            results.append(f"Datei:     {datev_file.name}")
            results.append(f"Pfad:      {export_dir}")
            results.append(f"Posten:    {exported}")
            results.append(f"Format:    DATEV Buchungsstapel (EXTF)")
            results.append(f"Encoding:  CP1252 (Windows)")
            results.append("")
            results.append("HINWEIS: Pruefen Sie die Konten-Zuordnung mit Ihrem Steuerberater!")
            results.append("SKR04-Mapping: Automatische Zuordnung via data/skr04_konten.json")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"DATEV-Export Fehler: {e}"
    
    def _export_csv(self, jahr: str, liste: str = None) -> tuple:
        """Einfacher CSV-Export fuer Excel."""
        import csv
        
        try:
            conn = self._get_db()
            
            sql = """SELECT dokument_id || '-' || postennr AS posten_id_str,
                            bezeichnung, datum, brutto, netto,
                            liste, anteil, absetzbar_brutto, rechnungssteller,
                            dokument_id, dateiname, bemerkung
                     FROM steuer_posten
                     WHERE username = ? AND steuerjahr = ?"""
            params = [self.username, int(jahr)]
            
            if liste:
                liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE", 
                            "V": "VERWORFEN", "Z": "ZURUECKGESTELLT"}
                liste_full = liste_map.get(liste.upper(), liste.upper())
                sql += " AND liste = ?"
                params.append(liste_full)
            
            sql += " ORDER BY liste, datum, dokument_id"
            
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            
            if not rows:
                return False, f"Keine Posten fuer {jahr} gefunden."
            
            export_dir = self.steuer_dir / jahr / "export"
            export_dir.mkdir(exist_ok=True)
            
            csv_file = export_dir / f"Steuerposten_{jahr}_{datetime.now().strftime('%Y%m%d')}.csv"
            
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                
                # Header
                writer.writerow([
                    "PostenID", "Belegnr", "Datum", "Anbieter", "Bezeichnung",
                    "Brutto", "Netto", "Liste", "Anteil", "Absetzbar",
                    "Dateiname", "Bemerkung"
                ])
                
                # Daten
                for r in rows:
                    brutto = r['brutto'] or 0
                    netto = r['netto'] or 0
                    anteil = r['anteil'] or 0
                    absetzbar = r['absetzbar_brutto'] or 0
                    
                    writer.writerow([
                        r['posten_id_str'],
                        f"B{r['dokument_id']:04d}",
                        r['datum'] or "",
                        r['rechnungssteller'] or "",
                        r['bezeichnung'] or "",
                        f"{brutto:.2f}".replace(".", ","),
                        f"{netto:.2f}".replace(".", ","),
                        r['liste'] or "",
                        f"{anteil*100:.0f}%",
                        f"{absetzbar:.2f}".replace(".", ","),
                        r['dateiname'] or "",
                        r['bemerkung'] or ""
                    ])
            
            results = [f"\nCSV-EXPORT {jahr}", "=" * 50]
            results.append(f"Datei:  {csv_file.name}")
            results.append(f"Pfad:   {export_dir}")
            results.append(f"Posten: {len(rows)}")
            results.append("")
            results.append("Oeffnen mit Excel: Doppelklick auf die CSV-Datei")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"CSV-Export Fehler: {e}"
    
    def _export_vorsorgeaufwand(self, jahr: str) -> tuple:
        """Export: Anlage Vorsorgeaufwand (Versicherungsbeitraege).

        Gruppiert Versicherungen nach steuerlicher Relevanz:
        - Basisvorsorge (Kranken-/Pflegeversicherung): Zeile 24-30
        - Sonstige Vorsorge (Haftpflicht, Risiko-LV, Unfall): Zeile 46-48
        - Nicht absetzbar (Hausrat, Rechtsschutz)
        """
        try:
            conn = self._get_db()

            rows = conn.execute("""
                SELECT anbieter, sparte, beitrag, zahlweise, steuer_relevant_typ
                FROM fin_insurances
                WHERE status = 'aktiv'
                ORDER BY steuer_relevant_typ ASC, sparte ASC
            """).fetchall()
            conn.close()

            if not rows:
                return False, "Keine aktiven Versicherungen gefunden."

            lines = [
                f"=== ANLAGE VORSORGEAUFWAND {jahr} ===",
                f"    (Versicherungsbeitraege fuer Steuererklaerung)",
                "",
            ]

            # Nach Typ gruppieren
            groups = {"Basisvorsorge": [], "Sonstige_Vorsorge": [], "Nicht_absetzbar": [], "---": []}
            for r in rows:
                typ = r["steuer_relevant_typ"] or "---"
                if typ not in groups:
                    groups[typ] = []
                groups[typ].append(r)

            # Basisvorsorge (Zeile 24-30)
            basis = groups.get("Basisvorsorge", [])
            if basis:
                lines.append("  BASISVORSORGE (Zeile 24-30: Kranken-/Pflegeversicherung)")
                lines.append("  " + "-" * 60)
                total_basis = 0
                for r in basis:
                    jahresbeitrag = self._calc_jahresbeitrag(r["beitrag"], r["zahlweise"])
                    total_basis += jahresbeitrag
                    lines.append(
                        f"    {r['sparte']:<20} ({r['anbieter']:<15}) {jahresbeitrag:>10.2f} EUR/Jahr"
                    )
                lines.append(f"    {'':->60}")
                lines.append(f"    {'SUMME Basisvorsorge':<36} {total_basis:>10.2f} EUR/Jahr")
                lines.append("")

            # Sonstige Vorsorge (Zeile 46-48)
            sonstige = groups.get("Sonstige_Vorsorge", [])
            if sonstige:
                lines.append("  SONSTIGE VORSORGEAUFWENDUNGEN (Zeile 46-48)")
                lines.append("  " + "-" * 60)
                total_sonstige = 0
                for r in sonstige:
                    jahresbeitrag = self._calc_jahresbeitrag(r["beitrag"], r["zahlweise"])
                    total_sonstige += jahresbeitrag
                    note = ""
                    if r["sparte"] in ("KFZ",):
                        note = " (nur Haftpflichtanteil)"
                    lines.append(
                        f"    {r['sparte']:<20} ({r['anbieter']:<15}) {jahresbeitrag:>10.2f} EUR/Jahr{note}"
                    )
                lines.append(f"    {'':->60}")
                lines.append(f"    {'SUMME Sonstige Vorsorge':<36} {total_sonstige:>10.2f} EUR/Jahr")
                lines.append(f"    Hoechstbetrag:                               1.900,00 EUR")
                if total_sonstige > 1900:
                    lines.append(f"    *** ACHTUNG: Hoechstbetrag ueberschritten ({total_sonstige - 1900:.2f} EUR darueber) ***")
                lines.append("")

            # Nicht absetzbar
            nicht_abs = groups.get("Nicht_absetzbar", [])
            if nicht_abs:
                lines.append("  NICHT ABSETZBAR (informativ)")
                lines.append("  " + "-" * 60)
                for r in nicht_abs:
                    jahresbeitrag = self._calc_jahresbeitrag(r["beitrag"], r["zahlweise"])
                    lines.append(
                        f"    {r['sparte']:<20} ({r['anbieter']:<15}) {jahresbeitrag:>10.2f} EUR/Jahr"
                    )
                lines.append("")

            # Zusammenfassung
            total_absetzbar = sum(
                self._calc_jahresbeitrag(r["beitrag"], r["zahlweise"])
                for r in basis + sonstige
            )
            lines.extend([
                "  " + "=" * 60,
                f"  GESAMT ABSETZBAR:                          {total_absetzbar:>10.2f} EUR/Jahr",
                "",
                "  HINWEIS: Betraege pruefen und ggf. mit Beitragsbescheinigungen",
                "  der Versicherungen abgleichen. KFZ-Versicherung: Nur der",
                "  Haftpflichtanteil ist absetzbar (ca. 50-70% des Gesamtbeitrags).",
            ])

            # CSV-Export
            export_dir = self.steuer_dir / jahr / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            csv_file = export_dir / f"vorsorgeaufwand_{jahr}.csv"

            import csv
            with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Sparte", "Anbieter", "Jahresbeitrag", "Steuer_Typ", "Absetzbar"])
                for r in rows:
                    jb = self._calc_jahresbeitrag(r["beitrag"], r["zahlweise"])
                    typ = r["steuer_relevant_typ"] or "---"
                    absetzbar = "Ja" if typ in ("Basisvorsorge", "Sonstige_Vorsorge") else "Nein"
                    writer.writerow([
                        r["sparte"], r["anbieter"],
                        f"{jb:.2f}".replace(".", ","),
                        typ, absetzbar
                    ])

            lines.append(f"\n  CSV-Export: {csv_file}")

            return True, "\n".join(lines)

        except Exception as e:
            return False, f"Vorsorgeaufwand-Export Fehler: {e}"

    def _calc_jahresbeitrag(self, beitrag, zahlweise):
        """Berechnet Jahresbeitrag aus Einzelbeitrag + Zahlweise."""
        if not beitrag:
            return 0.0
        zahlweise = (zahlweise or "monatlich").lower()
        if zahlweise == "monatlich":
            return beitrag * 12
        elif zahlweise == "quartalsweise":
            return beitrag * 4
        elif zahlweise == "halbjaehrlich":
            return beitrag * 2
        elif zahlweise == "jaehrlich":
            return beitrag
        return beitrag * 12  # Default: monatlich

    # ═══════════════════════════════════════════════════════════════
    # POSTEN - Postenverwaltung via DB
    # ═══════════════════════════════════════════════════════════════
    
    def _get_db(self):
        """DB-Verbindung holen."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def _posten(self, args: list, dry_run: bool) -> tuple:
        """Posten-Verwaltung Router."""
        if not args:
            return self._posten_list([])
        
        sub_cmd = args[0]
        sub_args = args[1:]
        
        if sub_cmd == "list":
            return self._posten_list(sub_args)
        elif sub_cmd == "show":
            return self._posten_show(sub_args)
        elif sub_cmd == "add":
            return self._posten_add(sub_args, dry_run)
        elif sub_cmd == "edit":
            return self._posten_edit(sub_args, dry_run)
        elif sub_cmd == "search":
            return self._posten_search(sub_args)
        elif sub_cmd == "move":
            return self._posten_move(sub_args, dry_run)
        elif sub_cmd == "delete":
            return self._posten_delete(sub_args, dry_run)
        else:
            # Vielleicht direkt eine PostenID?
            if "-" in sub_cmd:
                return self._posten_show([sub_cmd])
            return self._posten_list(args)
    
    def _posten_list(self, args: list) -> tuple:
        """Posten auflisten."""
        liste = self._get_arg(args, "--liste")
        belegnr = self._get_arg(args, "--belegnr")
        steller = self._get_arg(args, "--steller")
        rechnungsnr = self._get_arg(args, "--rechnungsnr") or self._get_arg(args, "--rechnr")
        limit = self._get_arg(args, "--limit") or "50"
        
        # Liste-Kurzform expandieren
        liste_map = {
            "W": "WERBUNGSKOSTEN",
            "G": "GEMISCHTE",
            "V": "VERWORFEN",
            "Z": "ZURUECKGESTELLT"
        }
        if liste and liste.upper() in liste_map:
            liste = liste_map[liste.upper()]
        
        try:
            conn = self._get_db()
            
            # Query bauen
            sql = """SELECT dokument_id || '-' || postennr AS posten_id_str,
                            bezeichnung, brutto, liste,
                            rechnungssteller, datum, bemerkung, anteil
                     FROM steuer_posten
                     WHERE username = ?"""
            params = [self.username]

            if liste:
                sql += " AND liste = ?"
                params.append(liste.upper())

            if belegnr:
                sql += " AND dokument_id = ?"
                params.append(int(belegnr))

            if steller:
                sql += " AND rechnungssteller LIKE ?"
                params.append(f"%{steller}%")

            if rechnungsnr:
                sql += " AND rechnungsnr LIKE ?"
                params.append(f"%{rechnungsnr}%")

            sql += f" ORDER BY dokument_id, postennr LIMIT {int(limit)}"
            
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            
            if not rows:
                return True, "Keine Posten gefunden."
            
            # Formatierte Ausgabe
            results = [f"\nPOSTEN ({len(rows)} Eintraege)", "=" * 70]
            results.append(f"{'ID':<8} {'Brutto':>10} {'Liste':<6} {'Anbieter':<8} {'Bezeichnung':<30}")
            results.append("-" * 70)
            
            for r in rows:
                bez = (r['bezeichnung'] or "?")[:30]
                liste_kurz = (r['liste'] or "?")[:5]
                anbieter = (r['rechnungssteller'] or "?")[:8]
                brutto = f"{r['brutto']:.2f} EUR" if r['brutto'] else "0.00 EUR"
                results.append(f"{r['posten_id_str']:<8} {brutto:>10} {liste_kurz:<6} {anbieter:<8} {bez}")
            
            results.append("")
            results.append("Details: bach steuer posten show ID")
            results.append("Filter:  --liste W|G|V|Z  --belegnr NR  --steller FILTER  --rechnungsnr NR --limit N")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"DB-Fehler: {e}"
    
    def _posten_show(self, args: list) -> tuple:
        """Einzelnen Posten anzeigen."""
        if not args:
            return False, "PostenID fehlt.\nUsage: bach steuer posten show 151-1"
        
        posten_id = args[0]
        
        try:
            conn = self._get_db()
            # Parse posten_id "42-3" -> dokument_id=42, postennr=3
            parts = posten_id.split("-", 1)
            if len(parts) == 2:
                try:
                    dok_id = int(parts[0])
                    post_nr = int(parts[1])
                except ValueError:
                    return False, f"Ungueltige PostenID: {posten_id}"
                row = conn.execute("""
                    SELECT * FROM steuer_posten
                    WHERE dokument_id = ? AND postennr = ? AND username = ?
                """, (dok_id, post_nr, self.username)).fetchone()
            else:
                return False, f"Ungueltige PostenID: {posten_id} (erwartet: NR-NR)"
            conn.close()

            if not row:
                return False, f"Posten nicht gefunden: {posten_id}"

            results = [f"\nPOSTEN {posten_id}", "=" * 50]
            results.append(f"Bezeichnung:      {row['bezeichnung']}")
            results.append(f"Datum:            {row['datum']}")
            results.append(f"Brutto:           {row['brutto']:.2f} EUR")
            results.append(f"Netto:            {row['netto']:.2f} EUR")
            results.append(f"Liste:            {row['liste']}")
            results.append(f"Anteil:           {row['anteil']*100:.0f}%")
            results.append(f"Absetzbar:        {row['absetzbar_brutto']:.2f} EUR")
            results.append(f"Rechnungssteller: {row['rechnungssteller']}")
            results.append(f"Rechnungsnr:      {row['rechnungsnr'] or '-'}")
            results.append(f"Dateiname:        {row['dateiname']}")
            results.append(f"Bemerkung:        {row['bemerkung'] or '-'}")
            results.append(f"Belegnr:          B{row['dokument_id']:04d}")
            results.append("")
            results.append(f"Bearbeiten: bach steuer posten edit {posten_id}")
            results.append(f"Verschieben: bach steuer posten move {posten_id} W|G|V|Z")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"DB-Fehler: {e}"
    
    def _posten_add(self, args: list, dry_run: bool) -> tuple:
        """Neuen Posten hinzufuegen."""
        # Parameter parsen
        belegnr = self._get_arg(args, "--belegnr")
        bezeichnung = self._get_arg(args, "--bezeichnung") or self._get_arg(args, "--bez")
        brutto = self._get_arg(args, "--brutto")
        liste = self._get_arg(args, "--liste") or "Z"
        anteil = self._get_arg(args, "--anteil") or "0.5"
        bemerkung = self._get_arg(args, "--bemerkung") or ""
        datum = self._get_arg(args, "--datum")
        anbieter = self._get_arg(args, "--anbieter")
        rechnungsnr = self._get_arg(args, "--rechnungsnr") or self._get_arg(args, "--rechnr")
        
        if not belegnr:
            return False, """Belegnummer fehlt.
            
Usage: bach steuer posten add --belegnr 151 --bezeichnung "Living Puppets" --brutto 34.95 --liste W

Parameter:
  --belegnr NR       Belegnummer (erforderlich)
  --bezeichnung TXT  Produktbezeichnung (erforderlich)
  --brutto WERT      Bruttobetrag (erforderlich)
  --liste W|G|V|Z    Zielliste (default: Z)
  --anteil 0.0-1.0   Anteil bei Gemischt (default: 0.5)
  --bemerkung TXT    Optionale Bemerkung
  --datum YYYY-MM-DD Datum (default: aus Beleg)
  --anbieter NAME    Anbieter (default: aus Beleg)
  --rechnungsnr NR   Rechnungsnummer"""
        
        if not bezeichnung or not brutto:
            return False, "Bezeichnung und Brutto sind erforderlich."
        
        # Liste expandieren
        liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE", "V": "VERWORFEN", "Z": "ZURUECKGESTELLT"}
        liste_full = liste_map.get(liste.upper(), liste.upper())
        
        try:
            brutto_val = float(brutto.replace(",", "."))
            anteil_val = float(anteil.replace(",", "."))
            netto_val = brutto_val / 1.19
            absetzbar = brutto_val * anteil_val if liste_full == "GEMISCHTE" else brutto_val
            
            conn = self._get_db()
            
            # Beleg-Info holen (id == belegnr nach Migration 002)
            beleg = conn.execute("""
                SELECT dateiname, anbieter FROM steuer_dokumente
                WHERE id = ? AND username = ?
            """, (int(belegnr), self.username)).fetchone()

            if not beleg:
                conn.close()
                return False, f"Beleg B{int(belegnr):04d} nicht gefunden."

            # Naechste Postennr fuer diesen Beleg
            max_nr = conn.execute("""
                SELECT MAX(postennr) FROM steuer_posten
                WHERE dokument_id = ? AND username = ?
            """, (int(belegnr), self.username)).fetchone()[0] or 0
            next_nr = max_nr + 1
            posten_id_str = f"{belegnr}-{next_nr}"

            if dry_run:
                conn.close()
                return True, f"[DRY-RUN] Wuerde Posten erstellen: {posten_id_str} | {bezeichnung} | {brutto_val:.2f} EUR | {liste_full}"

            # Datum aus Dateiname extrahieren (z.B. Otto_2025-02-05_...)
            beleg_datum = datum
            if not beleg_datum:
                import re
                m = re.search(r'(\d{4}-\d{2}-\d{2})', beleg['dateiname'])
                beleg_datum = m.group(1) if m else datetime.now().strftime('%Y-%m-%d')

            if not anbieter:
                anbieter = beleg['anbieter'] or ""

            # Einfuegen
            conn.execute("""
                INSERT INTO steuer_posten
                (username, steuerjahr, dokument_id, postennr, bezeichnung, datum, typ,
                 rechnungssteller, rechnungsnr, dateiname, netto, brutto, liste, anteil,
                 absetzbar_netto, absetzbar_brutto, bemerkung,
                 version, created_at, updated_at)
                VALUES (?, 2025, ?, ?, ?, ?, 'Material', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            """, (self.username, int(belegnr), next_nr, bezeichnung, beleg_datum,
                  anbieter, rechnungsnr, beleg['dateiname'],
                  netto_val, brutto_val, liste_full, anteil_val,
                  netto_val * anteil_val, absetzbar, bemerkung))
            conn.commit()
            conn.close()
            
            return True, f"Posten erstellt: {posten_id_str}\n  {bezeichnung}\n  {brutto_val:.2f} EUR -> {liste_full}"
            
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _posten_edit(self, args: list, dry_run: bool) -> tuple:
        """Posten bearbeiten."""
        if not args:
            return False, "PostenID fehlt.\nUsage: bach steuer posten edit 151-1 --bezeichnung 'Neuer Name'"
        
        posten_id = args[0]
        
        # Editierbare Felder
        bezeichnung = self._get_arg(args, "--bezeichnung") or self._get_arg(args, "--bez")
        brutto = self._get_arg(args, "--brutto")
        anteil = self._get_arg(args, "--anteil")
        rechnungsnr = self._get_arg(args, "--rechnungsnr") or self._get_arg(args, "--rechnr")
        bemerkung = self._get_arg(args, "--bemerkung")
        
        if not any([bezeichnung, brutto, anteil, bemerkung, rechnungsnr]):
            return False, f"""Keine Aenderungen angegeben.

Usage: bach steuer posten edit {posten_id} [OPTIONEN]

Optionen:
  --bezeichnung TXT  Neue Bezeichnung
  --brutto WERT      Neuer Bruttobetrag
  --anteil 0.0-1.0   Neuer Anteil
  --rechnungsnr NR   Neue Rechnungsnummer
  --bemerkung TXT    Neue Bemerkung"""
        
        try:
            conn = self._get_db()
            
            # Posten pruefen
            parsed = self._parse_posten_id(posten_id)
            if not parsed:
                conn.close()
                return False, f"Ungueltige PostenID: {posten_id}"
            dok_id, post_nr = parsed
            row = conn.execute("""
                SELECT * FROM steuer_posten WHERE dokument_id = ? AND postennr = ? AND username = ?
            """, (dok_id, post_nr, self.username)).fetchone()

            if not row:
                conn.close()
                return False, f"Posten nicht gefunden: {posten_id}"

            # Updates sammeln
            updates = []
            params = []

            if bezeichnung:
                updates.append("bezeichnung = ?")
                params.append(bezeichnung)

            if brutto:
                brutto_val = float(brutto.replace(",", "."))
                netto_val = brutto_val / 1.19
                current_anteil = row['anteil']
                updates.extend(["brutto = ?", "netto = ?",
                               "absetzbar_brutto = ?", "absetzbar_netto = ?"])
                params.extend([brutto_val, netto_val,
                              brutto_val * current_anteil, netto_val * current_anteil])

            if anteil:
                anteil_val = float(anteil.replace(",", "."))
                current_brutto = float(brutto.replace(",", ".")) if brutto else row['brutto']
                current_netto = current_brutto / 1.19
                updates.extend(["anteil = ?", "absetzbar_brutto = ?", "absetzbar_netto = ?"])
                params.extend([anteil_val, current_brutto * anteil_val, current_netto * anteil_val])

            if bemerkung:
                updates.append("bemerkung = ?")
                params.append(bemerkung)

            if rechnungsnr:
                updates.append("rechnungsnr = ?")
                params.append(rechnungsnr)

            updates.append("updated_at = datetime('now')")

            if dry_run:
                conn.close()
                return True, f"[DRY-RUN] Wuerde Posten {posten_id} aktualisieren"

            params.extend([dok_id, post_nr, self.username])
            conn.execute(f"""
                UPDATE steuer_posten SET {', '.join(updates)}
                WHERE dokument_id = ? AND postennr = ? AND username = ?
            """, params)
            conn.commit()
            conn.close()
            
            return True, f"Posten {posten_id} aktualisiert."
            
        except Exception as e:
            return False, f"Fehler: {e}"

    def _posten_search(self, args: list) -> tuple:
        """Posten uebergreifend suchen."""
        if not args:
            return False, "Suchbegriff fehlt.\nUsage: bach steuer posten search BEGRIFF"
        
        query_term = " ".join(args)
        limit = 50
        
        try:
            conn = self._get_db()
            
            # Suche in verschiedenen Feldern
            sql = """SELECT dokument_id || '-' || postennr AS posten_id_str,
                            bezeichnung, brutto, liste,
                            rechnungssteller, datum, bemerkung, rechnungsnr
                     FROM steuer_posten
                     WHERE username = ?
                       AND (bezeichnung LIKE ?
                            OR rechnungssteller LIKE ?
                            OR bemerkung LIKE ?
                            OR rechnungsnr LIKE ?
                            OR (dokument_id || '-' || postennr) LIKE ?)
                     ORDER BY datum DESC, dokument_id DESC
                     LIMIT ?"""
            like_term = f"%{query_term}%"
            params = [self.username, like_term, like_term, like_term, like_term, like_term, limit]
            
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            
            if not rows:
                return True, f"Keine Posten fuer '{query_term}' gefunden."
            
            results = [f"\nSUCHERGEBNISSE FUER '{query_term}' ({len(rows)})", "=" * 70]
            results.append(f"{'ID':<8} {'Brutto':>10} {'Liste':<6} {'Anbieter':<15} {'Bezeichnung'}")
            results.append("-" * 70)
            
            for r in rows:
                bez = (r['bezeichnung'] or "?")[:30]
                liste_kurz = (r['liste'] or "?")[:5]
                anbieter = (r['rechnungssteller'] or "?")[:15]
                brutto = f"{r['brutto']:.2f} EUR" if r['brutto'] else "0.00 EUR"
                results.append(f"{r['posten_id_str']:<8} {brutto:>10} {liste_kurz:<6} {anbieter:<15} {bez}")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"Suchfehler: {e}"
    
    def _posten_move(self, args: list, dry_run: bool) -> tuple:
        """Posten in andere Liste verschieben."""
        if len(args) < 2:
            return False, """PostenID und Zielliste fehlen.

Usage: bach steuer posten move 151-1 W

Listen:
  W = WERBUNGSKOSTEN (100% absetzbar)
  G = GEMISCHTE (anteilig absetzbar)
  V = VERWORFEN (nicht absetzbar)
  Z = ZURUECKGESTELLT (noch zu klaeren)"""
        
        posten_id = args[0]
        liste = args[1].upper()
        
        # Optionaler Anteil fuer Gemischte
        anteil = self._get_arg(args, "--anteil") or "0.5"
        
        liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE", "V": "VERWORFEN", "Z": "ZURUECKGESTELLT"}
        if liste not in liste_map:
            return False, f"Ungueltige Liste: {liste}\nErlaubt: W, G, V, Z"
        
        liste_full = liste_map[liste]
        
        try:
            conn = self._get_db()
            
            parsed = self._parse_posten_id(posten_id)
            if not parsed:
                conn.close()
                return False, f"Ungueltige PostenID: {posten_id}"
            dok_id, post_nr = parsed
            row = conn.execute("""
                SELECT * FROM steuer_posten WHERE dokument_id = ? AND postennr = ? AND username = ?
            """, (dok_id, post_nr, self.username)).fetchone()

            if not row:
                conn.close()
                return False, f"Posten nicht gefunden: {posten_id}"

            old_liste = row['liste']
            anteil_val = float(anteil.replace(",", "."))

            # Absetzbar berechnen
            if liste_full == "WERBUNGSKOSTEN":
                absetzbar = row['brutto']
                anteil_val = 1.0
            elif liste_full == "GEMISCHTE":
                absetzbar = row['brutto'] * anteil_val
            else:
                absetzbar = 0.0
                anteil_val = 0.0

            if dry_run:
                conn.close()
                return True, f"[DRY-RUN] Wuerde {posten_id} von {old_liste} nach {liste_full} verschieben"

            conn.execute("""
                UPDATE steuer_posten
                SET liste = ?, anteil = ?, absetzbar_brutto = ?,
                    absetzbar_netto = ?, updated_at = datetime('now')
                WHERE dokument_id = ? AND postennr = ? AND username = ?
            """, (liste_full, anteil_val, absetzbar, absetzbar/1.19, dok_id, post_nr, self.username))
            conn.commit()
            conn.close()
            
            return True, f"Posten {posten_id} verschoben: {old_liste} -> {liste_full}"
            
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _posten_delete(self, args: list, dry_run: bool) -> tuple:
        """Posten loeschen."""
        if not args:
            return False, "PostenID fehlt.\nUsage: bach steuer posten delete 151-1"
        
        posten_id = args[0]
        force = "--force" in args or "-f" in args
        
        try:
            conn = self._get_db()

            parsed = self._parse_posten_id(posten_id)
            if not parsed:
                conn.close()
                return False, f"Ungueltige PostenID: {posten_id}"
            dok_id, post_nr = parsed
            row = conn.execute("""
                SELECT bezeichnung, brutto, liste FROM steuer_posten
                WHERE dokument_id = ? AND postennr = ? AND username = ?
            """, (dok_id, post_nr, self.username)).fetchone()

            if not row:
                conn.close()
                return False, f"Posten nicht gefunden: {posten_id}"

            if not force:
                conn.close()
                return False, f"""Posten {posten_id} wirklich loeschen?
  {row['bezeichnung']}
  {row['brutto']:.2f} EUR | {row['liste']}

Bestaetigen mit: bach steuer posten delete {posten_id} --force"""

            if dry_run:
                conn.close()
                return True, f"[DRY-RUN] Wuerde Posten {posten_id} loeschen"

            conn.execute("""
                DELETE FROM steuer_posten WHERE dokument_id = ? AND postennr = ? AND username = ?
            """, (dok_id, post_nr, self.username))
            conn.commit()
            conn.close()
            
            return True, f"Posten {posten_id} geloescht."
            
        except Exception as e:
            return False, f"Fehler: {e}"
    
    # ═══════════════════════════════════════════════════════════════
    # BELEG - Belegverwaltung (scan, deprecate, list, sync)
    # ═══════════════════════════════════════════════════════════════
    
    def _beleg(self, args: list, dry_run: bool) -> tuple:
        """Beleg-Verwaltung Router."""
        if not args:
            return self._beleg_help()
        
        sub_cmd = args[0]
        sub_args = args[1:]
        
        if sub_cmd == "scan":
            return self._beleg_scan(sub_args, dry_run)
        elif sub_cmd == "deprecate":
            return self._beleg_deprecate(sub_args, dry_run)
        elif sub_cmd == "list":
            return self._beleg_list(sub_args)
        elif sub_cmd == "sync":
            return self._beleg_sync(sub_args, dry_run)
        elif sub_cmd == "help":
            return self._beleg_help()
        else:
            return self._beleg_help()
    
    def _beleg_help(self) -> tuple:
        """Beleg-Hilfe anzeigen."""
        return True, """
BELEG-VERWALTUNG
================

bach steuer beleg scan [--dry-run]
    Neue Belege in belege/ finden und automatisch nummerieren.
    Durchsucht alle Unterordner nach PDFs ohne B0XXX-Prefix.

bach steuer beleg deprecate VON BIS [GRUND] [--dry-run]
    Belege als ungueltig/ausgebucht markieren.
    Nummern bleiben reserviert, Status wird DEPRECATED.
    Beispiel: bach steuer beleg deprecate 215 466 "Alte Temu-Duplikate"

bach steuer beleg list [--status STATUS]
    Belege auflisten.
    Status: ERFASST, NICHT_ERFASST, DEPRECATED, ALL

bach steuer beleg sync [--dry-run]
    TXT-Dateien aus DB regenerieren (DOKUMENTENVERZEICHNIS.txt etc.)
"""
    
    def _beleg_scan(self, args: list, dry_run: bool) -> tuple:
        """Neue Belege scannen und nummerieren."""
        import subprocess
        
        # steuer_sync.py aufrufen
        script = self.base_path / "tools" / "steuer" / "steuer_sync.py"
        if not script.exists():
            return False, f"steuer_sync.py nicht gefunden: {script}"
        
        cmd = ["python", str(script), "scan"]
        if dry_run or "--dry-run" in args:
            cmd.append("--dry-run")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            output = result.stdout + result.stderr
            return True, output if output else "Scan abgeschlossen."
        except Exception as e:
            return False, f"Fehler beim Scan: {e}"
    
    def _beleg_deprecate(self, args: list, dry_run: bool) -> tuple:
        """Belege als deprecated markieren."""
        if len(args) < 2:
            return False, """VON und BIS Belegnummern fehlen.

Usage: bach steuer beleg deprecate 215 466 "Grund fuer Deprecation"

Die Belege werden als DEPRECATED markiert, die Nummern bleiben reserviert."""
        
        import subprocess

        script = self.base_path / "tools" / "steuer" / "steuer_sync.py"
        if not script.exists():
            return False, f"steuer_sync.py nicht gefunden: {script}"

        # Args zusammenbauen
        cmd = ["python", str(script), "deprecate", args[0], args[1]]
        
        # Grund hinzufuegen (alles nach VON BIS, ohne flags)
        grund_parts = [a for a in args[2:] if not a.startswith("-")]
        if grund_parts:
            cmd.append(" ".join(grund_parts))
        
        if dry_run or "--dry-run" in args:
            cmd.append("--dry-run")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            output = result.stdout + result.stderr
            return True, output if output else "Deprecate abgeschlossen."
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _beleg_list(self, args: list) -> tuple:
        """Belege auflisten."""
        status_filter = self._get_arg(args, "--status")
        limit = self._get_arg(args, "--limit") or "50"
        
        try:
            conn = self._get_db()
            
            sql = """SELECT id, dateiname, anbieter, erfasst_am, status, bemerkung
                     FROM steuer_dokumente
                     WHERE username = ?"""
            params = [self.username]

            if status_filter and status_filter.upper() != "ALL":
                sql += " AND status = ?"
                params.append(status_filter.upper())

            sql += f" ORDER BY id LIMIT {int(limit)}"

            rows = conn.execute(sql, params).fetchall()
            conn.close()

            if not rows:
                return True, "Keine Belege gefunden."

            # Zaehler fuer Status
            status_counts = {"ERFASST": 0, "NICHT_ERFASST": 0, "DEPRECATED": 0}

            results = [f"\nBELEGE ({len(rows)} Eintraege)", "=" * 80]
            results.append(f"{'Nr':<6} {'Anbieter':<12} {'Status':<14} {'Erfasst':<12} {'Dateiname':<30}")
            results.append("-" * 80)

            for r in rows:
                nr = f"B{r['id']:04d}"
                anbieter = (r['anbieter'] or "?")[:12]
                status = r['status'] or "?"
                erfasst = (r['erfasst_am'] or "-")[:12]
                datei = (r['dateiname'] or "?")[:30]

                if status in status_counts:
                    status_counts[status] += 1

                results.append(f"{nr:<6} {anbieter:<12} {status:<14} {erfasst:<12} {datei}")
            
            results.append("")
            results.append(f"Status: ERFASST={status_counts['ERFASST']} | NICHT_ERFASST={status_counts['NICHT_ERFASST']} | DEPRECATED={status_counts['DEPRECATED']}")
            results.append("")
            results.append("Filter: --status ERFASST|NICHT_ERFASST|DEPRECATED|ALL  --limit N")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"DB-Fehler: {e}"
    
    def _beleg_sync(self, args: list, dry_run: bool) -> tuple:
        """TXT-Dateien aus DB regenerieren."""
        import subprocess

        script = self.base_path / "tools" / "steuer" / "steuer_sync.py"
        if not script.exists():
            return False, f"steuer_sync.py nicht gefunden: {script}"
        
        cmd = ["python", str(script), "sync"]
        if dry_run or "--dry-run" in args:
            cmd.append("--dry-run")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            output = result.stdout + result.stderr
            return True, output if output else "Sync abgeschlossen."
        except Exception as e:
            return False, f"Fehler beim Sync: {e}"
    
    # ===================================================================
    # BATCH - Batch-Import von Posten und Belegen
    # ===================================================================
    
    def _batch(self, args: list, dry_run: bool) -> tuple:
        """Batch-Import Router."""
        if not args:
            return self._batch_help()
        
        sub_cmd = args[0]
        sub_args = args[1:]
        
        if sub_cmd == "help":
            return self._batch_help()
        elif sub_cmd == "posten":
            return self._batch_posten(sub_args, dry_run)
        elif sub_cmd == "belege":
            return self._batch_belege(sub_args, dry_run)
        elif sub_cmd == "delete":
            return self._batch_delete(sub_args, dry_run)
        elif sub_cmd == "move":
            return self._batch_move(sub_args, dry_run)
        else:
            return self._batch_help()
    
    def _batch_help(self) -> tuple:
        """Batch-Hilfe anzeigen."""
        return True, """
BATCH-IMPORT
============

bach steuer batch posten --belegnr NR --json "JSON"
    Mehrere Posten fuer einen Beleg im Batch hinzufuegen.
    
    JSON-Format (Array):
    [
      {"bez": "Artikel 1", "brutto": 19.99, "liste": "W"},
      {"bez": "Artikel 2", "brutto": 9.99, "liste": "V", "bem": "privat"}
    ]
    
    Beispiel:
    bach steuer batch posten --belegnr 42 --json '[{"bez":"SCHUBITRIX","brutto":17.50,"liste":"W"},{"bez":"Milch","brutto":2.99,"liste":"V"}]'

bach steuer batch posten --belegnr NR --file datei.json
    Posten aus JSON-Datei importieren.

bach steuer batch belege --file datei.json
    Mehrere Belege mit Posten aus JSON-Datei importieren.
    
    JSON-Format:
    {
      "belege": [
        {
          "belegnr": 42,
          "posten": [
            {"bez": "Artikel", "brutto": 19.99, "liste": "W"}
          ]
        }
      ]
    }

bach steuer batch belege --inline "BELEGNR:BEZ:BRUTTO:LISTE;..."
    Schnell-Erfassung im Inline-Format.
    
    Beispiel:
    bach steuer batch belege --inline "42:SCHUBITRIX:17.50:W;42:Milch:2.99:V;43:Lernspiel:12.00:W"

LISTEN-KUERZEL
--------------
W = WERBUNGSKOSTEN (100% absetzbar)
G = GEMISCHTE (anteilig, default 50%)
V = VERWORFEN (nicht absetzbar)
Z = ZURUECKGESTELLT (noch zu klaeren)

POSTEN-FELDER
-------------
bez      = Bezeichnung (erforderlich)
brutto   = Bruttobetrag (erforderlich)
liste    = W/G/V/Z (default: Z)
bem      = Bemerkung (optional)
datum    = YYYY-MM-DD (optional, default: aus Beleg)
anteil   = 0.0-1.0 (optional, nur bei G)

bach steuer batch delete --belegnr NR [--force]
    Alle Posten eines Belegs loeschen.
    
    Beispiel:
    bach steuer batch delete --belegnr 42 --force

bach steuer batch delete --posten "42-1,42-2,43-1" [--force]
    Bestimmte Posten loeschen (kommagetrennte Liste).
    
    Beispiel:
    bach steuer batch delete --posten "42-1,42-2,42-3" --force

bach steuer batch delete --liste V --limit 100 [--force]
    Alle Posten einer Liste loeschen (mit Limit).
    VORSICHT: Kann viele Posten loeschen!

bach steuer batch move --posten "42-1,42-2,43-1" --liste W
    Bestimmte Posten in andere Liste verschieben.

bach steuer batch move --belegnr 42 --liste W
    Alle Posten eines Belegs verschieben.

bach steuer batch move --von V --nach W --limit 50
    Posten zwischen Listen verschieben.
    
    Beispiel: Alle VERWORFEN nach WERBUNGSKOSTEN (max 50)
"""
    
    def _batch_posten(self, args: list, dry_run: bool) -> tuple:
        """Mehrere Posten fuer einen Beleg hinzufuegen."""
        belegnr = self._get_arg(args, "--belegnr")
        json_str = self._get_arg(args, "--json")
        json_file = self._get_arg(args, "--file")
        
        if not belegnr:
            return False, "Belegnummer fehlt.\nUsage: bach steuer batch posten --belegnr 42 --json '[...]'"
        
        # JSON laden
        posten_list = []
        if json_str:
            try:
                posten_list = json.loads(json_str)
            except json.JSONDecodeError as e:
                return False, f"JSON-Fehler: {e}"
        elif json_file:
            json_path = Path(json_file)
            if not json_path.exists():
                return False, f"Datei nicht gefunden: {json_file}"
            try:
                posten_list = json.loads(json_path.read_text(encoding='utf-8'))
            except json.JSONDecodeError as e:
                return False, f"JSON-Fehler in {json_file}: {e}"
        else:
            return False, "Keine Posten angegeben.\nNutze --json '[...]' oder --file datei.json"
        
        if not isinstance(posten_list, list):
            return False, "JSON muss ein Array von Posten sein."
        
        if not posten_list:
            return False, "Keine Posten im JSON gefunden."
        
        # Liste-Mapping
        liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE", "V": "VERWORFEN", "Z": "ZURUECKGESTELLT"}
        
        try:
            conn = self._get_db()
            
            # Beleg pruefen (id == belegnr nach Migration 002)
            beleg = conn.execute("""
                SELECT id, dateiname, anbieter FROM steuer_dokumente
                WHERE id = ? AND username = ?
            """, (int(belegnr), self.username)).fetchone()

            if not beleg:
                conn.close()
                return False, f"Beleg B{int(belegnr):04d} nicht gefunden."

            # Naechste Postennr ermitteln
            max_nr = conn.execute("""
                SELECT MAX(postennr) FROM steuer_posten
                WHERE dokument_id = ? AND username = ?
            """, (int(belegnr), self.username)).fetchone()[0] or 0
            
            results = [f"\nBATCH-IMPORT fuer B{int(belegnr):04d}", "=" * 50]
            
            if dry_run:
                results.append("[DRY-RUN] Keine Aenderungen")
            
            imported = 0
            errors = []
            
            for i, p in enumerate(posten_list):
                bez = p.get('bez') or p.get('bezeichnung')
                brutto = p.get('brutto')
                liste = p.get('liste', 'Z').upper()
                bem = p.get('bem') or p.get('bemerkung') or ''
                datum = p.get('datum')
                anteil = float(p.get('anteil', 0.5))
                
                if not bez or brutto is None:
                    errors.append(f"Posten {i+1}: bez oder brutto fehlt")
                    continue
                
                liste_full = liste_map.get(liste, liste)
                brutto_val = float(str(brutto).replace(",", "."))
                netto_val = brutto_val / 1.19
                
                # Anteil berechnen
                if liste_full == "WERBUNGSKOSTEN":
                    anteil = 1.0
                elif liste_full in ["VERWORFEN", "ZURUECKGESTELLT"]:
                    anteil = 0.0
                
                absetzbar = brutto_val * anteil
                
                next_nr = max_nr + imported + 1
                posten_id_str = f"{belegnr}-{next_nr}"
                
                if dry_run:
                    results.append(f"  [{posten_id_str}] {bez[:35]} | {brutto_val:.2f} EUR | {liste}")
                else:
                    # Datum aus Beleg extrahieren falls nicht angegeben
                    import re
                    if not datum:
                        m = re.search(r'(\d{4}-\d{2}-\d{2})', beleg['dateiname'] or '')
                        datum = m.group(1) if m else datetime.now().strftime('%Y-%m-%d')
                    
                    rechnungssteller = beleg['anbieter'] or ""

                    conn.execute("""
                        INSERT INTO steuer_posten
                        (username, steuerjahr, dokument_id, postennr, bezeichnung, datum, typ,
                         rechnungssteller, dateiname, netto, brutto, liste, anteil,
                         absetzbar_netto, absetzbar_brutto, bemerkung,
                         version, created_at, updated_at)
                        VALUES (?, 2025, ?, ?, ?, ?, 'Material', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
                    """, (self.username, int(belegnr), next_nr, bez, datum,
                          rechnungssteller, beleg['dateiname'],
                          netto_val, brutto_val, liste_full, anteil,
                          netto_val * anteil, absetzbar, bem))
                    
                    results.append(f"  [{posten_id_str}] {bez[:35]} | {brutto_val:.2f} EUR | {liste}")
                
                imported += 1
            
            if not dry_run:
                # Beleg als ERFASST markieren
                conn.execute("""
                    UPDATE steuer_dokumente SET status = 'ERFASST', erfasst_am = date('now')
                    WHERE id = ? AND username = ?
                """, (int(belegnr), self.username))
                conn.commit()
            
            conn.close()
            
            results.append("")
            results.append(f"Importiert: {imported}")
            if errors:
                results.append(f"Fehler: {len(errors)}")
                for e in errors[:5]:
                    results.append(f"  - {e}")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _batch_belege(self, args: list, dry_run: bool) -> tuple:
        """Mehrere Belege mit Posten importieren."""
        json_file = self._get_arg(args, "--file")
        inline = self._get_arg(args, "--inline")
        
        if not json_file and not inline:
            return False, """Keine Daten angegeben.

Usage:
  bach steuer batch belege --file import.json
  bach steuer batch belege --inline "42:Artikel:19.99:W;43:Ware:9.99:V"
"""
        
        # Daten laden
        belege_data = []
        
        if inline:
            # Inline-Format parsen: "BELEGNR:BEZ:BRUTTO:LISTE;..."
            for entry in inline.split(";"):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split(":")
                if len(parts) < 4:
                    continue
                belegnr = parts[0].strip()
                bez = parts[1].strip()
                brutto = parts[2].strip()
                liste = parts[3].strip() if len(parts) > 3 else "Z"
                
                # Beleg in Liste finden oder anlegen
                found = False
                for b in belege_data:
                    if b['belegnr'] == belegnr:
                        b['posten'].append({'bez': bez, 'brutto': brutto, 'liste': liste})
                        found = True
                        break
                if not found:
                    belege_data.append({
                        'belegnr': belegnr,
                        'posten': [{'bez': bez, 'brutto': brutto, 'liste': liste}]
                    })
        
        elif json_file:
            json_path = Path(json_file)
            if not json_path.exists():
                return False, f"Datei nicht gefunden: {json_file}"
            try:
                data = json.loads(json_path.read_text(encoding='utf-8'))
                belege_data = data.get('belege', [])
            except json.JSONDecodeError as e:
                return False, f"JSON-Fehler: {e}"
        
        if not belege_data:
            return False, "Keine Belege gefunden."
        
        results = ["\nBATCH-IMPORT BELEGE", "=" * 50]
        
        if dry_run:
            results.append("[DRY-RUN] Keine Aenderungen")
        
        total_posten = 0
        total_belege = 0
        
        for beleg in belege_data:
            belegnr = beleg.get('belegnr')
            posten_list = beleg.get('posten', [])
            
            if not belegnr or not posten_list:
                continue
            
            # _batch_posten aufrufen
            json_str = json.dumps(posten_list, ensure_ascii=False)
            success, msg = self._batch_posten(
                ['--belegnr', str(belegnr), '--json', json_str], 
                dry_run
            )
            
            if success:
                total_belege += 1
                total_posten += len(posten_list)
                results.append(f"\nB{int(belegnr):04d}: {len(posten_list)} Posten")
            else:
                results.append(f"\nB{int(belegnr):04d}: FEHLER - {msg}")
        
        results.append("")
        results.append("=" * 50)
        results.append(f"GESAMT: {total_belege} Belege, {total_posten} Posten")
        
        return True, "\n".join(results)
    
    def _batch_delete(self, args: list, dry_run: bool) -> tuple:
        """Mehrere Posten loeschen."""
        belegnr = self._get_arg(args, "--belegnr")
        posten_ids = self._get_arg(args, "--posten")
        liste = self._get_arg(args, "--liste")
        limit = self._get_arg(args, "--limit") or "50"
        force = "--force" in args or "-f" in args
        
        if not belegnr and not posten_ids and not liste:
            return False, """Keine Loeschkriterien angegeben.

Usage:
  bach steuer batch delete --belegnr 42 --force       # Alle Posten von Beleg 42
  bach steuer batch delete --posten "42-1,42-2"       # Bestimmte Posten
  bach steuer batch delete --liste V --limit 100      # Alle VERWORFEN (max 100)
"""
        
        # Liste-Mapping
        liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE", "V": "VERWORFEN", "Z": "ZURUECKGESTELLT"}
        
        try:
            conn = self._get_db()
            
            # Zu loeschende Posten ermitteln
            if posten_ids:
                # Kommagetrennte Liste - parse each to dokument_id+postennr
                id_parts = [p.strip() for p in posten_ids.split(",") if p.strip()]
                conditions = []
                params_list = []
                for pid in id_parts:
                    parsed = self._parse_posten_id(pid)
                    if parsed:
                        conditions.append("(dokument_id = ? AND postennr = ?)")
                        params_list.extend(parsed)
                if not conditions:
                    return False, "Keine gueltigen PostenIDs."
                where_clause = " OR ".join(conditions)
                rows = conn.execute(f"""
                    SELECT dokument_id || '-' || postennr AS posten_id_str,
                           id, dokument_id, postennr, bezeichnung, brutto, liste
                    FROM steuer_posten
                    WHERE ({where_clause}) AND username = ?
                """, params_list + [self.username]).fetchall()

            elif belegnr:
                # Alle Posten eines Belegs
                rows = conn.execute("""
                    SELECT dokument_id || '-' || postennr AS posten_id_str,
                           id, dokument_id, postennr, bezeichnung, brutto, liste
                    FROM steuer_posten
                    WHERE dokument_id = ? AND username = ?
                """, (int(belegnr), self.username)).fetchall()

            elif liste:
                # Alle Posten einer Liste
                liste_full = liste_map.get(liste.upper(), liste.upper())
                rows = conn.execute(f"""
                    SELECT dokument_id || '-' || postennr AS posten_id_str,
                           id, dokument_id, postennr, bezeichnung, brutto, liste
                    FROM steuer_posten
                    WHERE liste = ? AND username = ? LIMIT {int(limit)}
                """, (liste_full, self.username)).fetchall()

            if not rows:
                conn.close()
                return True, "Keine Posten zum Loeschen gefunden."

            results = [f"\nBATCH DELETE - {len(rows)} Posten", "=" * 50]

            for r in rows:
                bez = (r['bezeichnung'] or "?")[:30]
                results.append(f"  [{r['posten_id_str']}] {bez} | {r['brutto']:.2f} EUR | {r['liste'][:4]}")
            
            if not force:
                conn.close()
                results.append("")
                results.append("WARNUNG: Diese Posten werden geloescht!")
                results.append("Bestaetigen mit --force")
                return True, "\n".join(results)
            
            if dry_run:
                conn.close()
                results.append("")
                results.append("[DRY-RUN] Keine Aenderungen")
                return True, "\n".join(results)
            
            # Loeschen - use row IDs collected above
            row_ids = [r['id'] for r in rows]
            placeholders = ",".join(["?" for _ in row_ids])
            conn.execute(f"""
                DELETE FROM steuer_posten
                WHERE id IN ({placeholders}) AND username = ?
            """, row_ids + [self.username])

            if belegnr:
                # Beleg-Status zuruecksetzen
                conn.execute("""
                    UPDATE steuer_dokumente SET status = 'NICHT_ERFASST', erfasst_am = NULL
                    WHERE id = ? AND username = ?
                """, (int(belegnr), self.username))
            
            conn.commit()
            conn.close()
            
            results.append("")
            results.append(f"GELOESCHT: {len(rows)} Posten")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _batch_move(self, args: list, dry_run: bool) -> tuple:
        """Mehrere Posten verschieben."""
        posten_ids = self._get_arg(args, "--posten")
        belegnr = self._get_arg(args, "--belegnr")
        von_liste = self._get_arg(args, "--von")
        nach_liste = self._get_arg(args, "--nach") or self._get_arg(args, "--liste")
        limit = self._get_arg(args, "--limit") or "50"
        anteil = self._get_arg(args, "--anteil") or "0.5"
        
        if not nach_liste:
            return False, """Zielliste fehlt.

Usage:
  bach steuer batch move --posten "42-1,42-2" --liste W
  bach steuer batch move --belegnr 42 --liste W
  bach steuer batch move --von V --nach W --limit 50
"""
        
        # Liste-Mapping
        liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE", "V": "VERWORFEN", "Z": "ZURUECKGESTELLT"}
        nach_full = liste_map.get(nach_liste.upper(), nach_liste.upper())
        
        if nach_full not in liste_map.values():
            return False, f"Ungueltige Zielliste: {nach_liste}\nErlaubt: W, G, V, Z"
        
        try:
            conn = self._get_db()
            
            # Zu verschiebende Posten ermitteln
            if posten_ids:
                id_parts = [p.strip() for p in posten_ids.split(",") if p.strip()]
                conditions = []
                params_list = []
                for pid in id_parts:
                    parsed = self._parse_posten_id(pid)
                    if parsed:
                        conditions.append("(dokument_id = ? AND postennr = ?)")
                        params_list.extend(parsed)
                if not conditions:
                    return False, "Keine gueltigen PostenIDs."
                where_clause = " OR ".join(conditions)
                rows = conn.execute(f"""
                    SELECT dokument_id || '-' || postennr AS posten_id_str,
                           id, dokument_id, postennr, bezeichnung, brutto, liste
                    FROM steuer_posten
                    WHERE ({where_clause}) AND username = ?
                """, params_list + [self.username]).fetchall()

            elif belegnr:
                rows = conn.execute("""
                    SELECT dokument_id || '-' || postennr AS posten_id_str,
                           id, dokument_id, postennr, bezeichnung, brutto, liste
                    FROM steuer_posten
                    WHERE dokument_id = ? AND username = ?
                """, (int(belegnr), self.username)).fetchall()

            elif von_liste:
                von_full = liste_map.get(von_liste.upper(), von_liste.upper())
                rows = conn.execute(f"""
                    SELECT dokument_id || '-' || postennr AS posten_id_str,
                           id, dokument_id, postennr, bezeichnung, brutto, liste
                    FROM steuer_posten
                    WHERE liste = ? AND username = ? LIMIT {int(limit)}
                """, (von_full, self.username)).fetchall()

            else:
                conn.close()
                return False, "Keine Posten angegeben (--posten, --belegnr oder --von)"

            if not rows:
                conn.close()
                return True, "Keine Posten zum Verschieben gefunden."

            results = [f"\nBATCH MOVE -> {nach_liste} ({len(rows)} Posten)", "=" * 50]

            for r in rows:
                bez = (r['bezeichnung'] or "?")[:30]
                results.append(f"  [{r['posten_id_str']}] {bez} | {r['brutto']:.2f} EUR | {r['liste'][:4]} -> {nach_liste}")
            
            if dry_run:
                conn.close()
                results.append("")
                results.append("[DRY-RUN] Keine Aenderungen")
                return True, "\n".join(results)
            
            # Anteil berechnen
            anteil_val = float(anteil.replace(",", "."))
            if nach_full == "WERBUNGSKOSTEN":
                anteil_val = 1.0
            elif nach_full in ["VERWORFEN", "ZURUECKGESTELLT"]:
                anteil_val = 0.0
            
            # Verschieben - use row IDs
            for r in rows:
                brutto = r['brutto']
                absetzbar = brutto * anteil_val

                conn.execute("""
                    UPDATE steuer_posten
                    SET liste = ?, anteil = ?, absetzbar_brutto = ?,
                        absetzbar_netto = ?, updated_at = datetime('now')
                    WHERE id = ? AND username = ?
                """, (nach_full, anteil_val, absetzbar, absetzbar/1.19, r['id'], self.username))
            
            conn.commit()
            conn.close()
            
            results.append("")
            results.append(f"VERSCHOBEN: {len(rows)} Posten -> {nach_full}")
            
            return True, "\n".join(results)
            
        except Exception as e:
            return False, f"Fehler: {e}"
    
    # ===================================================================
    # TOOLS - Steuer-Tools verwalten
    # ===================================================================
    
    def _tools(self, args: list, dry_run: bool) -> tuple:
        """Steuer-Tools anzeigen und ausfuehren."""
        if not args:
            return self._tools_list()
        
        sub_cmd = args[0]
        sub_args = args[1:]
        
        if sub_cmd == "list":
            return self._tools_list()
        elif sub_cmd == "run" and sub_args:
            return self._tools_run(sub_args, dry_run)
        elif sub_cmd == "register":
            return self._tools_register(dry_run)
        else:
            # Vielleicht direkt ein Tool-Name?
            return self._tools_run([sub_cmd] + sub_args, dry_run)
    
    def _tools_list(self) -> tuple:
        """Steuer-Tools auflisten."""
        results = ["\nSTEUER-TOOLS", "=" * 60]
        
        # Aus DB laden
        db_path = self._canonical_db
        if db_path.exists():
            from .lang import get_lang
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            # TOWER_OF_BABEL: pro Name eine Zeile, aktive Sprache bevorzugt
            rows = conn.execute("""
                SELECT name, command, description,
                       MAX(language = ?) AS _lang_pref
                FROM tools
                WHERE category = 'steuer'
                GROUP BY name ORDER BY name
            """, (get_lang(),)).fetchall()
            conn.close()
            
            if rows:
                results.append(f"\nRegistriert in bach.db ({len(rows)} Tools):")
                results.append("-" * 60)
                for r in rows:
                    results.append(f"  {r['name']:<20} {r['description'][:40]}")
                results.append("")
        
        # Dateien im Ordner
        tools_dir = self.base_path / "tools" / "steuer"
        if tools_dir.exists():
            py_files = sorted([f.stem for f in tools_dir.glob("*.py") 
                              if not f.stem.startswith("_")])
            results.append(f"Dateien in tools/steuer/ ({len(py_files)}):")
            results.append("-" * 60)
            for name in py_files[:15]:
                results.append(f"  {name}.py")
            if len(py_files) > 15:
                results.append(f"  ... und {len(py_files)-15} weitere")
        
        results.append("")
        results.append("Ausfuehren: bach steuer tools run <name> [args]")
        results.append("Registrieren: bach steuer tools register")
        
        return True, "\n".join(results)
    
    def _tools_run(self, args: list, dry_run: bool) -> tuple:
        """Steuer-Tool ausfuehren."""
        if not args:
            return False, "Tool-Name fehlt.\nUsage: bach steuer tools run <n> [args]"
        
        tool_name = args[0]
        tool_args = args[1:]
        
        # Tool finden
        tools_dir = self.base_path / "tools" / "steuer"
        tool_path = tools_dir / f"{tool_name}.py"
        
        if not tool_path.exists():
            # Ohne .py versuchen
            tool_path = tools_dir / tool_name
            if not tool_path.exists():
                return False, f"Tool nicht gefunden: {tool_name}\nPfad: {tools_dir}"
        
        if dry_run:
            return True, f"[DRY-RUN] Wuerde ausfuehren: python {tool_path} {' '.join(tool_args)}"
        
        import subprocess
        import os
        
        # Environment mit PYTHONPATH erweitern fuer _config.py Import
        env = os.environ.copy()
        pythonpath = str(tools_dir)
        if "PYTHONPATH" in env:
            pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
        env["PYTHONPATH"] = pythonpath
        
        # BACH_DIR als Umgebungsvariable setzen
        env["BACH_DIR"] = str(self.base_path)
        
        cmd = ["python", str(tool_path)] + tool_args
        
        try:
            # cwd auf tools/steuer setzen, damit relative Imports funktionieren
            result = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=120, cwd=str(tools_dir), env=env)
            output = result.stdout + result.stderr
            return True, output if output else f"Tool {tool_name} ausgefuehrt (keine Ausgabe)"
        except subprocess.TimeoutExpired:
            return False, f"Tool {tool_name} Timeout (>120s)"
        except Exception as e:
            return False, f"Fehler bei {tool_name}: {e}"
    
    def _tools_register(self, dry_run: bool) -> tuple:
        """Steuer-Tools in bach.db registrieren."""
        register_script = self.base_path / "tools" / "steuer" / "register_tools.py"
        
        if not register_script.exists():
            return False, f"register_tools.py nicht gefunden"
        
        if dry_run:
            return True, "[DRY-RUN] Wuerde Steuer-Tools registrieren"
        
        import subprocess
        try:
            result = subprocess.run(["python", str(register_script)],
                                   capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=30)
            return True, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    # ===================================================================
    # CHECK - Vollstaendigkeitspruefung (STEUER_003)
    # ===================================================================

    def _check(self, args: list) -> tuple:
        """Vollstaendigkeitspruefung fuer Steuerjahr."""
        jahr = self._get_arg(args, "--jahr") or "2025"

        results = [f"\nVOLLSTAENDIGKEITSPRUEFUNG {jahr}", "=" * 50]
        issues = []
        warnings = []

        try:
            conn = self._get_db()

            # 1. Belege ohne Posten
            belege_ohne_posten = conn.execute("""
                SELECT d.id, d.dateiname
                FROM steuer_dokumente d
                LEFT JOIN steuer_posten p ON d.id = p.dokument_id AND d.username = p.username
                WHERE d.username = ? AND d.steuerjahr = ? AND d.status = 'ERFASST'
                AND p.id IS NULL
                ORDER BY d.id
            """, (self.username, int(jahr))).fetchall()

            if belege_ohne_posten:
                issues.append(f"Belege ohne Posten: {len(belege_ohne_posten)}")
                for b in belege_ohne_posten[:5]:
                    issues.append(f"  - B{b['id']:04d}: {b['dateiname']}")
                if len(belege_ohne_posten) > 5:
                    issues.append(f"  ... und {len(belege_ohne_posten) - 5} weitere")

            # 2. Posten ohne Beleg (Eigenbelege ausgenommen)
            posten_ohne_beleg = conn.execute("""
                SELECT p.dokument_id || '-' || p.postennr AS posten_id_str, p.bezeichnung
                FROM steuer_posten p
                LEFT JOIN steuer_dokumente d ON p.dokument_id = d.id AND p.username = d.username
                WHERE p.username = ? AND p.steuerjahr = ?
                AND p.ist_eigenbeleg = 0 AND d.id IS NULL
                ORDER BY p.dokument_id
            """, (self.username, int(jahr))).fetchall()

            if posten_ohne_beleg:
                issues.append(f"Posten ohne Beleg: {len(posten_ohne_beleg)}")
                for p in posten_ohne_beleg[:5]:
                    issues.append(f"  - {p['posten_id_str']}: {p['bezeichnung']}")

            # 3. Luecken in Belegnummern (id == belegnr)
            alle_belegnr = conn.execute("""
                SELECT DISTINCT id FROM steuer_dokumente
                WHERE username = ? AND steuerjahr = ?
                ORDER BY id
            """, (self.username, int(jahr))).fetchall()

            if alle_belegnr:
                nummern = [b['id'] for b in alle_belegnr]
                luecken = []
                for i in range(nummern[0], nummern[-1] + 1):
                    if i not in nummern:
                        luecken.append(i)

                if luecken:
                    warnings.append(f"Luecken in Belegnummern: {len(luecken)}")
                    if len(luecken) <= 10:
                        warnings.append(f"  Fehlend: {', '.join([f'B{n:04d}' for n in luecken])}")
                    else:
                        warnings.append(f"  Fehlend: {', '.join([f'B{n:04d}' for n in luecken[:10]])} ...")

            # 4. Fehlende Monate
            monate_mit_belegen = conn.execute("""
                SELECT DISTINCT strftime('%m', datum) as monat
                FROM steuer_posten
                WHERE username = ? AND steuerjahr = ?
                AND datum IS NOT NULL
            """, (self.username, int(jahr))).fetchall()

            vorhandene_monate = {int(m['monat']) for m in monate_mit_belegen if m['monat']}
            aktueller_monat = datetime.now().month if str(datetime.now().year) == jahr else 12
            fehlende_monate = []
            for m in range(1, aktueller_monat + 1):
                if m not in vorhandene_monate:
                    fehlende_monate.append(m)

            if fehlende_monate:
                monatsnamen = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                              "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
                warnings.append(f"Monate ohne Belege: {', '.join([monatsnamen[m-1] for m in fehlende_monate])}")

            # 5. Posten ohne MwSt-Betrag
            ohne_mwst = conn.execute("""
                SELECT COUNT(*) as cnt FROM steuer_posten
                WHERE username = ? AND steuerjahr = ? AND mwst_betrag IS NULL
            """, (self.username, int(jahr))).fetchone()['cnt']

            if ohne_mwst > 0:
                warnings.append(f"Posten ohne MwSt-Betrag: {ohne_mwst}")

            # 6. Statistik
            stats = conn.execute("""
                SELECT
                    COUNT(*) as gesamt,
                    SUM(CASE WHEN liste = 'WERBUNGSKOSTEN' THEN 1 ELSE 0 END) as werbungskosten,
                    SUM(CASE WHEN liste = 'GEMISCHTE' THEN 1 ELSE 0 END) as gemischte,
                    SUM(CASE WHEN liste = 'ZURUECKGESTELLT' THEN 1 ELSE 0 END) as zurueck,
                    SUM(CASE WHEN liste = 'VERWORFEN' THEN 1 ELSE 0 END) as verworfen,
                    SUM(CASE WHEN ist_eigenbeleg = 1 THEN 1 ELSE 0 END) as eigenbelege
                FROM steuer_posten
                WHERE username = ? AND steuerjahr = ?
            """, (self.username, int(jahr))).fetchone()

            conn.close()

            # Ergebnis zusammenstellen
            results.append(f"\nSTATISTIK:")
            results.append(f"  Gesamt Posten:    {stats['gesamt'] or 0}")
            results.append(f"  Werbungskosten:   {stats['werbungskosten'] or 0}")
            results.append(f"  Gemischte:        {stats['gemischte'] or 0}")
            results.append(f"  Zurueckgestellt:  {stats['zurueck'] or 0}")
            results.append(f"  Verworfen:        {stats['verworfen'] or 0}")
            results.append(f"  Eigenbelege:      {stats['eigenbelege'] or 0}")

            if issues:
                results.append(f"\n❌ PROBLEME ({len(issues)}):")
                results.extend(issues)

            if warnings:
                results.append(f"\n⚠️  WARNUNGEN ({len(warnings)}):")
                results.extend(warnings)

            if not issues and not warnings:
                results.append("\n✅ Keine Probleme gefunden!")

            results.append("")
            return True, "\n".join(results)

        except Exception as e:
            return False, f"Pruefung fehlgeschlagen: {e}"

    # ===================================================================
    # EIGENBELEG (STEUER_002)
    # ===================================================================

    def _eigenbeleg(self, args: list, dry_run: bool) -> tuple:
        """Eigenbeleg erstellen fuer fehlende Originalbelege."""
        bezeichnung = self._get_arg(args, "--bezeichnung") or self._get_arg(args, "--bez")
        brutto = self._get_arg(args, "--brutto")
        liste = self._get_arg(args, "--liste") or "W"
        datum = self._get_arg(args, "--datum") or datetime.now().strftime('%Y-%m-%d')
        grund = self._get_arg(args, "--grund") or "Kein Originalbeleg vorhanden"
        mwst_satz = self._get_arg(args, "--mwst") or "19"

        if not bezeichnung or not brutto:
            return False, """Eigenbeleg-Erstellung

Usage: bach steuer eigenbeleg --bezeichnung "Parkgebuehr" --brutto 5.00

Parameter:
  --bezeichnung TXT  Beschreibung (erforderlich)
  --brutto WERT      Bruttobetrag (erforderlich)
  --liste W|G|V|Z    Zielliste (default: W)
  --datum YYYY-MM-DD Datum (default: heute)
  --mwst 7|19        MwSt-Satz (default: 19)
  --grund TXT        Begruendung (default: "Kein Originalbeleg vorhanden")

Typische Anwendungsfaelle:
  - Parkgebuehren ohne Quittung
  - Kleine Barauszahlungen
  - Trinkgelder bei Geschaeftsessen"""

        try:
            brutto_val = float(brutto.replace(",", "."))
            mwst_satz_val = int(mwst_satz)

            # MwSt berechnen
            if mwst_satz_val == 19:
                netto_val = brutto_val / 1.19
            elif mwst_satz_val == 7:
                netto_val = brutto_val / 1.07
            else:
                netto_val = brutto_val  # Keine MwSt

            mwst_betrag = brutto_val - netto_val

            # Liste expandieren
            liste_map = {"W": "WERBUNGSKOSTEN", "G": "GEMISCHTE", "V": "VERWORFEN", "Z": "ZURUECKGESTELLT"}
            liste_full = liste_map.get(liste.upper(), liste.upper())

            # Jahr aus Datum
            steuerjahr = int(datum.split('-')[0])

            conn = self._get_db()

            # Naechste Eigenbeleg-Nummer (E9001, E9002, ...)
            max_eigenbeleg = conn.execute("""
                SELECT MAX(dokument_id) as max_nr FROM steuer_posten
                WHERE username = ? AND steuerjahr = ? AND ist_eigenbeleg = 1
            """, (self.username, steuerjahr)).fetchone()['max_nr']

            if max_eigenbeleg and max_eigenbeleg >= 9000:
                next_belegnr = max_eigenbeleg + 1
            else:
                next_belegnr = 9001  # Eigenbelege starten bei 9001

            posten_id_str = f"E{next_belegnr}-1"

            if dry_run:
                conn.close()
                return True, f"""[DRY-RUN] Wuerde Eigenbeleg erstellen:
  ID:          {posten_id_str}
  Bezeichnung: {bezeichnung}
  Brutto:      {brutto_val:.2f} EUR
  Netto:       {netto_val:.2f} EUR
  MwSt:        {mwst_betrag:.2f} EUR ({mwst_satz_val}%)
  Liste:       {liste_full}
  Datum:       {datum}
  Grund:       {grund}"""

            # Eigenbeleg in DB speichern
            conn.execute("""
                INSERT INTO steuer_posten
                (username, steuerjahr, dokument_id, postennr, bezeichnung, datum, typ,
                 rechnungssteller, dateiname, netto, brutto, mwst_betrag, mwst_satz,
                 liste, anteil, absetzbar_netto, absetzbar_brutto, bemerkung,
                 ist_eigenbeleg, version, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, 'Eigenbeleg',
                        'EIGENBELEG', ?, ?, ?, ?, ?,
                        ?, 1.0, ?, ?, ?,
                        1, 1, datetime('now'), datetime('now'))
            """, (self.username, steuerjahr, next_belegnr, bezeichnung, datum,
                  f"EIGENBELEG_{next_belegnr}.pdf", netto_val, brutto_val, mwst_betrag, mwst_satz_val,
                  liste_full, netto_val, brutto_val, grund))
            conn.commit()

            # PDF-Eigenbeleg erstellen
            pdf_created = self._create_eigenbeleg_pdf(
                next_belegnr, bezeichnung, brutto_val, netto_val,
                mwst_betrag, mwst_satz_val, datum, grund, steuerjahr
            )

            conn.close()

            result = f"""Eigenbeleg erstellt: {posten_id_str}
  Bezeichnung: {bezeichnung}
  Brutto:      {brutto_val:.2f} EUR
  Liste:       {liste_full}"""

            if pdf_created:
                result += f"\n  PDF:         user/steuer/{steuerjahr}/eigenbelege/EIGENBELEG_{next_belegnr}.pdf"

            return True, result

        except Exception as e:
            return False, f"Fehler beim Erstellen: {e}"

    def _create_eigenbeleg_pdf(self, belegnr: int, bezeichnung: str, brutto: float,
                               netto: float, mwst: float, mwst_satz: int,
                               datum: str, grund: str, steuerjahr: int) -> bool:
        """Erstellt ein PDF fuer den Eigenbeleg."""
        try:
            # Eigenbeleg-Ordner erstellen
            eigenbeleg_dir = self.steuer_dir / str(steuerjahr) / "eigenbelege"
            eigenbeleg_dir.mkdir(parents=True, exist_ok=True)

            # Einfache TXT-Version (PDF-Erstellung benoetigt reportlab)
            txt_path = eigenbeleg_dir / f"EIGENBELEG_{belegnr}.txt"

            content = f"""
================================================================================
                              EIGENBELEG
================================================================================

Belegnummer:    E{belegnr}
Datum:          {datum}

--------------------------------------------------------------------------------

Bezeichnung:    {bezeichnung}

Netto:          {netto:>10.2f} EUR
MwSt ({mwst_satz}%):     {mwst:>10.2f} EUR
--------------------------------------------------------------------------------
Brutto:         {brutto:>10.2f} EUR

--------------------------------------------------------------------------------

Begruendung:    {grund}

--------------------------------------------------------------------------------

Erstellt:       {datetime.now().strftime('%Y-%m-%d %H:%M')}
Ersteller:      {self.username}

================================================================================
Dieser Eigenbeleg wurde fuer die Steuererklarung {steuerjahr} erstellt.
================================================================================
"""

            txt_path.write_text(content.strip(), encoding='utf-8')
            return True

        except Exception:
            return False

    # ===================================================================
    # HELPER
    # ===================================================================

    def _get_arg(self, args: list, flag: str) -> str:
        """Argument nach Flag holen."""
        for i, arg in enumerate(args):
            if arg == flag and i + 1 < len(args):
                return args[i + 1]
        return None

    def _import_camt(self, args: list, dry_run: bool) -> tuple:
        """Importiert Transaktionen aus einer CAMT.053 Datei."""
        from agents._experts.steuer.camt_parser import CamtParser
        if not args:
            return False, "Dateipfad fehlt. Nutzung: bach steuer import camt <pfad>"

        path = Path(args[0])
        if not path.exists():
            return False, f"Datei nicht gefunden: {path}"

        try:
            parser = CamtParser(path)
            txs = parser.parse()
            balances = parser.parse_balances() if hasattr(parser, 'parse_balances') else []

            if dry_run:
                bal_info = "; ".join(
                    f"{b['iban']}: {b['balance']:.2f} {b['currency'] or 'EUR'} ({b['date']})"
                    for b in balances) or "keine Salden gefunden"
                return True, (f"[DRY-RUN] Wuerde {len(txs)} Transaktionen aus {path.name} "
                              f"importieren. Salden: {bal_info}")

            res = [f"[OK] {len(txs)} Transaktionen aus {path.name} gelesen:"]
            for tx in txs[:5]:
                res.append(f"  - {tx['datum']} | {tx['betrag']:>10.2f} | {tx['partner'][:20]}")
            if len(txs) > 5:
                res.append(f"  ... und {len(txs)-5} weitere.")

            res.extend(self._persist_camt_balances(self.db_path, balances))

            return True, "\n".join(res)
        except Exception as e:
            return False, f"Fehler beim Import: {e}"

    @staticmethod
    def _persist_camt_balances(db_path, balances: list) -> list:
        """Schreibt CAMT-Abschlusssalden nach bank_accounts (UPDATE per IBAN, sonst INSERT).

        IBAN wird normalisiert (Leerzeichen raus, Grossschreibung), damit manuell
        erfasste Konten nicht dupliziert werden. dry_run-Aufrufer rufen das nie auf.
        """
        import sqlite3
        if not balances:
            return ["[WARN] Keine Salden in der Datei - bank_accounts unveraendert."]
        lines = []
        con = sqlite3.connect(str(db_path))
        try:
            for bal in balances:
                iban_norm = (bal.get('iban') or '').replace(' ', '').upper()
                if not iban_norm or iban_norm == 'UNKNOWN':
                    lines.append("[WARN] Saldo ohne IBAN uebersprungen.")
                    continue
                row = con.execute(
                    "SELECT id FROM bank_accounts WHERE REPLACE(UPPER(COALESCE(iban,'')),' ','')=?",
                    (iban_norm,)).fetchone()
                waehrung = bal.get('currency') or 'EUR'
                if row:
                    con.execute(
                        "UPDATE bank_accounts SET balance=?, balance_date=?, "
                        "updated_at=datetime('now') WHERE id=?",
                        (bal['balance'], bal.get('date'), row[0]))
                    lines.append(f"[OK] Konto {iban_norm}: Saldo {bal['balance']:.2f} "
                                 f"{waehrung} zum {bal.get('date')} aktualisiert.")
                else:
                    con.execute(
                        "INSERT INTO bank_accounts (name, iban, balance, balance_date) "
                        "VALUES (?,?,?,?)",
                        (f"CAMT-Import {iban_norm}", iban_norm,
                         bal['balance'], bal.get('date')))
                    lines.append(f"[OK] Konto {iban_norm} neu angelegt, Saldo "
                                 f"{bal['balance']:.2f} {waehrung} zum {bal.get('date')} "
                                 f"(Name via GUI editierbar).")
            con.commit()
        finally:
            con.close()
        return lines
