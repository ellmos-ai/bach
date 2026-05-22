# SPDX-License-Identifier: MIT
"""
BACH Maintain Handler
=====================
CLI-Handler fuer Wartungs- und Analyse-Tools.

Befehle:
    bach --maintain docs          Dokumentations-Check
    bach --maintain duplicates    Duplikat-Erkennung
    bach --maintain generate      Skill/Agent Generator
    bach --maintain export        Export-Tools
    bach --maintain headers       SKILL.md YAML-Header generieren/validieren
    bach --maintain pattern       Dateinamen-Pattern kuerzen
    bach --maintain scan          System nach CLI-Tools scannen
    bach --maintain skill-help    Help-Dateien aus SKILL.md generieren
    bach --maintain workflows     Workflow-Format validieren
"""

import os
import sys
import subprocess
from pathlib import Path
from .base import BaseHandler
from .lang import t
from .status import StatusHandler


class MaintainHandler(BaseHandler):
    """Handler fuer --maintain Befehle"""

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.tools_dir = base_path / "tools"
        # Fix: UTF-8 Encoding fuer alle Subprocesses (Windows cp1252 Problem)
        self._subprocess_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    
    @property
    def profile_name(self) -> str:
        return "maintain"
    
    @property
    def target_file(self) -> Path:
        return self.tools_dir
    
    def get_operations(self) -> dict:
        return {
            "docs": "Dokumentations-Update-Check",
            "duplicates": "Duplikat-Erkennung fuer Tools",
            "generate": "Skill/Agent Generator",
            "export": "Export-Tools (Skill/Agent/OS)",
            "health": "BACH-Gesamtstatus anzeigen",
            "pattern": "Dateinamen-Pattern kuerzen",
            "scan": "System nach CLI-Tools scannen",
            "clean": "Dateien nach Alter/Muster loeschen",
            "json": "JSON-Dateien reparieren",
            "heal": "VERALTET — siehe docs-paths (Pfade sind automatisch via bach_paths.py)",
            "docs-paths": "Dokumentations-Pfade aktualisieren (.md/.txt)",
            "registry": "Registry-Konsistenz pruefen",
            "skills": "Skill-Gesundheit pruefen",
            "sync": "Skills mit Datenbank synchronisieren",
            "headers": "SKILL.md YAML-Header generieren/validieren",
            "skill-help": "Help-Dateien aus SKILL.md generieren",
            "workflows": "Workflow-Format validieren",
            "nul": "Windows NUL-Dateien entfernen [scan|delete] [pfad]",
            "list": "Verfuegbare Wartungs-Tools anzeigen"
        }
    
    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if not operation or operation == "list":
            return True, self._list_tools()
        
        op = operation.lower()
        
        if op == "docs":
            return self._run_docs_check(args, dry_run)
        elif op == "duplicates":
            return self._run_duplicate_check(args)
        elif op == "generate":
            return self._run_generator(args)
        elif op == "export":
            return self._run_export(args)
        elif op == "health":
            return StatusHandler(self.base_path).handle("show", [], dry_run)
        elif op == "pattern":
            return self._run_pattern_tool(args, dry_run)
        elif op == "scan":
            return self._run_tool_scanner(args)
        elif op == "clean":
            return self._run_file_cleaner(args, dry_run)
        elif op == "json":
            return self._run_json_fixer(args, dry_run)
        elif op == "heal":
            return True, """HINWEIS: Pfad-Heilung ist nicht mehr noetig!
============================================================
bach_paths.py verwaltet alle Laufzeit-Pfade automatisch.
Wenn BACH verschoben wird, passen sich Pfade von selbst an.

Fuer Dokumentations-Updates (Help, Wiki, Markdown):
  bach --maintain docs-paths          Dry-Run (nur anzeigen)
  bach --maintain docs-paths --apply  Tatsaechlich korrigieren

Siehe: bach --help tools/path_healer"""
        elif op == "docs-paths":
            return self._run_doc_path_updater(args, dry_run)
        elif op == "registry":
            return self._run_registry_watcher(args)
        elif op == "skills":
            return self._run_skill_health_monitor(args)
        elif op == "sync":
            return self._run_sync_skills(args, dry_run)
        elif op == "headers":
            return self._run_skill_headers(args, dry_run)
        elif op == "skill-help":
            return self._run_skill_help(args, dry_run)
        elif op == "workflows":
            return self._run_workflow_validator(args)
        elif op == "nul":
            return self._run_nul_cleaner(args, dry_run)
        elif op in ["help", "-h"]:
            return True, self._show_help()
        else:
            return False, f"Unbekannter Befehl: {op}\n\n{self._show_help()}"
    
    def _run_docs_check(self, args: list, dry_run: bool) -> tuple:
        """Fuehrt Dokumentations-Check aus."""
        script = self.tools_dir / "doc_update_checker.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"

        # Ohne explizites Subcommand bleibt "check" der Default.
        # Sobald der erste Wert kein Flag ist, geben wir ihn direkt an das Tool
        # weiter (z.B. "report", "auto-update", "schedule").
        if args and not str(args[0]).startswith("-"):
            cmd_args = list(args)
        else:
            cmd_args = ["check"]
            if args:
                cmd_args.extend(args)

        if dry_run and "--dry-run" not in cmd_args and cmd_args[0] in {
            "check",
            "auto-update",
            "auto-fix",
        }:
            cmd_args.append("--dry-run")
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=120,
                cwd=str(self.base_path)
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_duplicate_check(self, args: list) -> tuple:
        """Fuehrt Duplikat-Check aus."""
        script = self.tools_dir / "duplicate_detector.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        return True, """Duplicate Detector
==================
Dieses Tool benoetigt eine Tool-Registry.

Verwendung:
  from tools.duplicate_detector import DuplicateDetector
  detector = DuplicateDetector(registry)
  result = detector.check_duplicate("neues-tool", "Beschreibung", ["keywords"])

Features:
- Name-Similarity Check
- Keyword-Matching
- Usage-Tracking
- Gap-Analysis

Siehe: tools/duplicate_detector.py"""
    
    def _run_generator(self, args: list) -> tuple:
        """Fuehrt Skill/Agent Generator aus."""
        script = self.tools_dir / "skill_generator.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        if not args:
            return True, """Skill Generator
===============
Generiert Skill-Strukturen von MICRO bis EXTENDED.

Verwendung:
  bach --maintain generate <n> [profil] [zielordner]

Profile:
  MICRO    Nur Datei(en), kein Ordnersystem
  LIGHT    Minimale Struktur (SKILL.md + _config + _data)
  STANDARD Standard-Skill mit einfachem Memory
  EXTENDED Komplexer Skill mit Mikro-Skills

Beispiele:
  bach --maintain generate mein-skill STANDARD skills/
  bach --maintain generate analyse MICRO skills/workflows/

Siehe: tools/skill_generator.py"""
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_export(self, args: list) -> tuple:
        """Fuehrt Export-Tool aus."""
        script = self.tools_dir / "exporter.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        if not args:
            return True, """Exporter
========
Export-Tool fuer Skills, Agents und OS.

Befehle:
  skill     Exportiert einen Skill als Standalone
  agent     Exportiert einen Agent mit seinen Skills
  os-fresh  Erstellt ein frisches OS-Paket
  os-reset  Setzt ein OS zurueck

Verwendung:
  bach --maintain export skill <n> --from-os <path>
  bach --maintain export os-fresh <path> --output <zip>

Siehe: tools/exporter.py"""
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=120
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_pattern_tool(self, args: list, dry_run: bool) -> tuple:
        """Fuehrt Pattern-Tool aus."""
        script = self.tools_dir / "pattern_tool.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        if not args:
            return True, """Pattern Tool
============
Kuerzt Dateinamen durch Pattern-Erkennung.

Verwendung:
  bach --maintain pattern <ordner> [optionen]

Optionen:
  --dry-run       Nur anzeigen (default)
  --execute       Umbenennungen durchfuehren
  --prefix-only   Nur Prefix-Patterns
  --suffix-only   Nur Suffix-Patterns
  -m <n>          Minimale Pattern-Laenge (default: 3)
  -r              Rekursiv scannen

Beispiele:
  bach --maintain pattern ./docs --dry-run
  bach --maintain pattern ./docs --execute -m 5

Siehe: tools/pattern_tool.py"""
        
        cmd_args = list(args)
        if dry_run and "--execute" not in args:
            cmd_args.append("--dry-run")
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_tool_scanner(self, args: list) -> tuple:
        """Fuehrt Tool-Scanner aus."""
        script = self.tools_dir / "tool_scanner.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        cmd_args = args if args else ["scan"]
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_file_cleaner(self, args: list, dry_run: bool) -> tuple:
        """Fuehrt File-Cleaner aus."""
        script = self.tools_dir / "file_cleaner.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        if not args:
            return True, """File Cleaner
============
Dateien nach Alter/Muster bereinigen.

Verwendung:
  bach --maintain clean <ordner> [optionen]

Optionen:
  --age <tage>    Dateien aelter als X Tage
  --keep <n>      Nur N neueste behalten
  --pattern <p>   Datei-Pattern (z.B. "*.log")
  -r              Rekursiv suchen
  --execute       Tatsaechlich loeschen

Beispiele:
  bach --maintain clean ./logs --age 30
  bach --maintain clean ./backups --keep 5 --execute

Siehe: tools/file_cleaner.py"""
        
        cmd_args = list(args)
        if dry_run and "--execute" not in args:
            pass  # Default ist dry-run
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=120
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_json_fixer(self, args: list, dry_run: bool) -> tuple:
        """Fuehrt JSON-Fixer aus."""
        script = self.tools_dir / "json_fixer.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        if not args:
            return True, """JSON Fixer
==========
Repariert kaputte JSON-Dateien.

Verwendung:
  bach --maintain json <datei/ordner> [optionen]

Optionen:
  --dry-run    Nur pruefen (default)
  --execute    Tatsaechlich reparieren
  --backup     Backup vor Aenderung

Repariert:
  - UTF-8 BOM
  - Trailing Commas
  - Single-Quotes
  - PowerShell Newlines

Beispiele:
  bach --maintain json ./config.json
  bach --maintain json ./data --execute --backup

Siehe: tools/json_fixer.py"""
        
        cmd_args = list(args)
        if dry_run and "--execute" not in args:
            cmd_args.append("--dry-run")
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_doc_path_updater(self, args: list, dry_run: bool) -> tuple:
        """Aktualisiert veraltete Pfade in Dokumentation (Help, Wiki, Markdown)."""
        script = self.tools_dir / "maintenance" / "doc_path_updater.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"

        if not args:
            return True, """Doc Path Updater
================
Aktualisiert veraltete Pfade in Dokumentation (.md, .txt).
Laufzeit-Pfade werden von bach_paths.py automatisch verwaltet!

Verwendung:
  bach --maintain docs-paths              Dry-Run (nur anzeigen)
  bach --maintain docs-paths --apply      Tatsaechlich korrigieren
  bach --maintain docs-paths --report     Report generieren

Siehe: bach --help tools/path_healer"""

        cmd_args = list(args)
        if "--apply" not in args:
            cmd_args.append("--dry-run")
        else:
            cmd_args.remove("--apply")

        try:
            result = subprocess.run(
                [sys.executable, str(script), "--base", str(self.base_path.parent)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=120,
                cwd=str(self.base_path.parent)
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_registry_watcher(self, args: list) -> tuple:
        """Fuehrt Registry Watcher aus."""
        script = self.tools_dir / "maintenance" / "registry_watcher.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        if not args:
            args = ["check"]  # Default: Quick-Check
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + list(args),
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=60,
                cwd=str(self.base_path)
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_skill_health_monitor(self, args: list) -> tuple:
        """Fuehrt Skill Health Monitor aus."""
        script = self.tools_dir / "maintenance" / "skill_health_monitor.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        if not args:
            args = ["check"]  # Default: Quick-Check
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + list(args),
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=60,
                cwd=str(self.base_path)
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"
    
    def _run_sync_skills(self, args: list, dry_run: bool) -> tuple:
        """Synchronisiert skills/ Dateien mit DB."""
        script = self.tools_dir / "maintenance" / "sync_skills.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"
        
        cmd_args = []
        if dry_run or "--dry-run" in args:
            cmd_args.append("--dry-run")
        if "--verbose" in args or "-v" in args:
            cmd_args.append("--verbose")
        
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=60,
                cwd=str(self.base_path)
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"

    def _run_skill_headers(self, args: list, dry_run: bool) -> tuple:
        """
        Generiert/validiert YAML-Header fuer SKILL.md Dateien.

        Verwendung:
            bach --maintain headers                  # Dry-run alle
            bach --maintain headers --fix            # Alle korrigieren
            bach --maintain headers --path skills/   # Bestimmter Ordner
            bach --maintain headers --update-db      # DB-Versionen updaten
        """
        script = self.tools_dir / "skill_header_gen.py"
        if not script.exists():
            return False, f"Script nicht gefunden: {script}"

        if not args:
            return True, """Skill Header Generator
======================
Generiert und validiert YAML-Header fuer SKILL.md Dateien.

Verwendung:
  bach --maintain headers                    # Dry-run (alle)
  bach --maintain headers --fix              # Aenderungen schreiben
  bach --maintain headers --path <ordner>    # Bestimmter Ordner
  bach --maintain headers --update-db        # DB-Versionen aktualisieren
  bach --maintain headers -v                 # Ausfuehrliche Ausgabe

Optionen:
  --all         Alle Skill-Verzeichnisse scannen (default)
  --path <p>    Bestimmtes Verzeichnis scannen
  --file <f>    Einzelne SKILL.md verarbeiten
  --dry-run     Nur anzeigen (default)
  --fix         Aenderungen schreiben
  --update-db   DB-Versionen aus YAML-Headern aktualisieren
  -v            Ausfuehrlich

Gescannte Verzeichnisse:
  agents/*/SKILL.md
  agents/_experts/*/SKILL.md
  hub/_services/*/SKILL.md
  partners/*/SKILL.md

Beispiele:
  bach --maintain headers                     # Trockenlauf
  bach --maintain headers --fix               # Alle Header normalisieren
  bach --maintain headers --fix --update-db   # Header + DB aktualisieren
  bach --maintain headers --path agents -v

Siehe: tools/skill_header_gen.py"""

        # Build command line arguments
        cmd_args = ["--all"]

        # Parse args for our flags
        has_path = False
        has_file = False
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--path" and i + 1 < len(args):
                cmd_args = ["--path", args[i + 1]]
                has_path = True
                i += 2
                continue
            elif arg == "--file" and i + 1 < len(args):
                cmd_args = ["--file", args[i + 1]]
                has_file = True
                i += 2
                continue
            elif arg == "--fix":
                # Will be handled below
                pass
            elif arg in ("--update-db", "--verbose", "-v", "--all"):
                cmd_args.append(arg)
            i += 1

        # Add --fix or --dry-run
        if "--fix" in args and not dry_run:
            cmd_args.append("--fix")
        elif "--fix" in args:
            # User explicitly said --fix but handler has dry_run=True
            cmd_args.append("--fix")
        else:
            cmd_args.append("--dry-run")

        try:
            result = subprocess.run(
                [sys.executable, str(script)] + cmd_args,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                env=self._subprocess_env,
                timeout=120,
                cwd=str(self.base_path)
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, f"Fehler: {e}"

    def _run_skill_help(self, args: list, dry_run: bool) -> tuple:
        """
        Generiert Help-Dateien aus SKILL.md.

        Verwendung:
            bach --maintain skill-help                    # Alle Skills (dry-run)
            bach --maintain skill-help <name>             # Einzelner Skill
            bach --maintain skill-help --all              # Alle Skills
            bach --maintain skill-help --all --dry-run    # Nur anzeigen
        """
        if not args:
            return True, """Skill Help Generator
====================
Generiert docs/help/*.txt Dateien aus SKILL.md.

Verwendung:
  bach --maintain skill-help <name>          Einzelner Skill
  bach --maintain skill-help --all           Alle Skills
  bach --maintain skill-help --all --dry-run Nur anzeigen

Beispiele:
  bach --maintain skill-help ati             Help fuer ATI-Agent
  bach --maintain skill-help --all           Alle Skills

Siehe: tools/skill_help_gen.py"""

        try:
            sys.path.insert(0, str(self.tools_dir))
            from skill_help_gen import HelpGenerator

            gen = HelpGenerator(self.base_path)

            # --dry-run aus args extrahieren
            is_dry = dry_run or "--dry-run" in args
            clean_args = [a for a in args if a not in ("--dry-run", "-n")]

            if "--all" in clean_args or "-a" in clean_args:
                return gen.generate_all(dry_run=is_dry)
            elif clean_args:
                # Erster Nicht-Flag-Argument ist der Skill-Name
                skill_name = clean_args[0]
                return gen.generate_for_skill(skill_name, dry_run=is_dry)
            else:
                return gen.generate_all(dry_run=is_dry)

        except ImportError as e:
            return False, f"[ERR] skill_help_gen.py nicht gefunden: {e}"
        except Exception as e:
            return False, f"[ERR] Fehler: {e}"

    def _run_workflow_validator(self, args: list) -> tuple:
        """
        Validiert Workflow-Dateien auf konsistentes Format.

        Verwendung:
            bach --maintain workflows        # Alle Workflows validieren
        """
        if not args:
            pass  # Default: alle validieren
        elif args[0] in ("help", "-h"):
            return True, """Workflow Format-Validator
=========================
Prueft Workflow-Dateien auf konsistentes Format.

Verwendung:
  bach --maintain workflows             Alle Workflows validieren

Prueft:
  - H1-Titel vorhanden
  - Beschreibung (> Blockquote, **Zweck:**, ## Uebersicht)
  - Schritte/Phasen-Struktur
  - Versions-Angabe (optional)

Erwartet in: skills/workflows/*.md

Siehe: tools/skill_help_gen.py"""

        try:
            sys.path.insert(0, str(self.tools_dir))
            from skill_help_gen import WorkflowValidator

            validator = WorkflowValidator(self.base_path)
            return validator.validate_all()

        except ImportError as e:
            return False, f"[ERR] skill_help_gen.py nicht gefunden: {e}"
        except Exception as e:
            return False, f"[ERR] Fehler: {e}"

    def _run_nul_cleaner(self, args: list, dry_run: bool) -> tuple:
        """
        Entfernt Windows NUL-Dateien.

        Verwendung:
            bach --maintain nul                    # Scan BACH_ROOT
            bach --maintain nul scan               # Nur scannen
            bach --maintain nul delete             # Scannen und loeschen
            bach --maintain nul delete C:\\Pfad   # Bestimmtes Verzeichnis
        """
        # Default: BACH_ROOT (eine Ebene ueber system/)
        bach_root = self.base_path.parent
        target_path = str(bach_root)

        # Modus bestimmen
        mode = "scan"  # Default: nur scannen
        for arg in args:
            if arg.lower() in ("delete", "clean", "remove"):
                mode = "delete"
            elif not arg.startswith("-") and Path(arg).exists():
                target_path = arg

        # Hilfe anzeigen wenn keine Args
        if not args:
            return True, """NUL Cleaner
===========
Entfernt Windows NUL-Dateien (reservierter Dateiname).

Verwendung:
  bach --maintain nul              # Scan BACH-Verzeichnis
  bach --maintain nul scan         # Nur scannen (default)
  bach --maintain nul delete       # Scannen und loeschen
  bach --maintain nul delete PFAD  # Bestimmtes Verzeichnis

Optionen:
  scan      Nur NUL-Dateien auflisten
  delete    NUL-Dateien loeschen

Beispiele:
  bach --maintain nul scan
  bach --maintain nul delete
  bach --maintain nul delete C:\\Users\\YOUR_USERNAME\\Projekt

NUL-Dateien entstehen auf Windows wenn versehentlich
nach 'NUL' geschrieben wird (Windows Device-Name)."""

        try:
            from tools.nulcleaner import find_nul_files, delete_nul_file

            nul_files = find_nul_files(target_path)

            if not nul_files:
                return True, f"[OK] Keine NUL-Dateien gefunden in: {target_path}"

            lines = [
                f"[NUL CLEANER] {target_path}",
                "=" * 50,
                f"Gefunden: {len(nul_files)} NUL-Dateien",
                ""
            ]

            if mode == "scan" or dry_run:
                for f in nul_files:
                    lines.append(f"  [NUL] {f}")
                if mode == "scan":
                    lines.append("")
                    lines.append("Zum Loeschen: bach --maintain nul delete")
                return True, "\n".join(lines)

            # Delete mode
            deleted = 0
            errors = []
            for f in nul_files:
                result = delete_nul_file(f)
                if result is True:
                    deleted += 1
                    lines.append(f"  [OK] Geloescht: {f}")
                else:
                    errors.append(f)
                    lines.append(f"  [ERR] Fehler: {f}")

            lines.append("")
            lines.append(f"Ergebnis: {deleted} geloescht, {len(errors)} Fehler")

            return len(errors) == 0, "\n".join(lines)

        except ImportError as e:
            return False, f"[ERR] NUL-Cleaner nicht gefunden: {e}"
        except Exception as e:
            return False, f"[ERR] Fehler: {e}"

    def _list_tools(self) -> str:
        """Listet verfuegbare Wartungs-Tools."""
        lines = []
        lines.append("=" * 50)
        lines.append("WARTUNGS-TOOLS")
        lines.append("=" * 50)
        lines.append("")
        lines.append("Verfuegbare Befehle:")
        lines.append("")
        lines.append("  docs        Dokumentations-Update-Check")
        lines.append("              Erkennt veraltete Dokumente (>60 Tage)")
        lines.append("")
        lines.append("  duplicates  Duplikat-Erkennung")
        lines.append("              Verhindert Tool-Duplikate")
        lines.append("")
        lines.append("  generate    Skill/Agent Generator")
        lines.append("              Erstellt neue Skill-Strukturen")
        lines.append("")
        lines.append("  export      Export-Tools")
        lines.append("              Exportiert Skills/Agents/OS")
        lines.append("")
        lines.append("  pattern     Pattern-Tool")
        lines.append("              Kuerzt Dateinamen durch Pattern-Erkennung")
        lines.append("")
        lines.append("  scan        Tool-Scanner")
        lines.append("              Findet installierte CLI-Tools")
        lines.append("")
        lines.append("  clean       File-Cleaner")
        lines.append("              Loescht Dateien nach Alter/Muster")
        lines.append("")
        lines.append("  json        JSON-Fixer")
        lines.append("              Repariert kaputte JSON-Dateien")
        lines.append("")
        lines.append("  heal        Path-Healer")
        lines.append("              Korrigiert veraltete Pfade")
        lines.append("")
        lines.append("  registry    Registry-Watcher")
        lines.append("              Prueft DB/JSON-Konsistenz")
        lines.append("")
        lines.append("  skills      Skill-Health-Monitor")
        lines.append("              Prueft Skills/Agenten-Zustand")
        lines.append("")
        lines.append("  headers     Skill-Header-Generator")
        lines.append("              YAML-Header fuer SKILL.md generieren/validieren")
        lines.append("")
        lines.append("  skill-help  Skill Help Generator")
        lines.append("              Generiert docs/help/*.txt aus SKILL.md")
        lines.append("")
        lines.append("  workflows   Workflow Format-Validator")
        lines.append("              Prueft Workflow-Dateien auf Format-Konsistenz")
        lines.append("")
        lines.append("  nul         NUL-Cleaner")
        lines.append("              Entfernt Windows NUL-Dateien")
        lines.append("")
        lines.append("Verwendung: bach --maintain <befehl> [optionen]")
        
        return "\n".join(lines)
    
    def _show_help(self) -> str:
        """Zeigt Hilfe."""
        return """BACH Maintain - Wartungs-Tools
==============================

Befehle:
  bach --maintain docs [--dry-run]    Dokumentations-Check
  bach --maintain duplicates          Duplikat-Info
  bach --maintain generate <args>     Skill Generator
  bach --maintain export <args>       Export-Tool
  bach --maintain health              BACH-Gesamtstatus
  bach --maintain pattern <ordner>    Pattern-Tool
  bach --maintain scan                Tool-Scanner
  bach --maintain clean <ordner>      File-Cleaner
  bach --maintain json <pfad>         JSON-Fixer
  bach --maintain heal                Path-Healer
  bach --maintain registry            Registry-Konsistenz
  bach --maintain skills              Skill-Gesundheit
  bach --maintain headers [--fix]     SKILL.md Header
  bach --maintain skill-help [name]   Help aus SKILL.md generieren
  bach --maintain workflows           Workflow-Format validieren
  bach --maintain list                Tools anzeigen

Beispiele:
  bach --maintain docs                # Doku pruefen
  bach --maintain docs report         # Markdown-Report erzeugen
  bach --maintain health              # Status anzeigen
  bach --maintain heal                # Pfade korrigieren
  bach --maintain registry report     # Detaillierter Registry-Report
  bach --maintain skills check        # Skill-Health Check
  bach --maintain skill-help --all    # Help-Dateien generieren
  bach --maintain workflows           # Workflow-Format pruefen
  bach --maintain clean ./logs --age 30

Tools (13):
  tools/doc_update_checker.py
  tools/duplicate_detector.py
  tools/skill_generator.py
  tools/exporter.py
  tools/pattern_tool.py
  tools/tool_scanner.py
  tools/file_cleaner.py
  tools/json_fixer.py
  tools/path_healer.py
  tools/skill_help_gen.py
  tools/skill_export.py"""
