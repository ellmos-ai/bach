#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH System Explorer v1.0.0

Automatische Software-Erkennung für BACH.
Scannt das Betriebssystem nach installierter Software,
erfasst Fähigkeiten und AI-Kompatibilität.

Portiert von: RecludOS System Explorer v1.0.0

Usage:
  python system_explorer.py scan --mode standard
  python system_explorer.py list --filter ai_compatible
  python system_explorer.py suggest
  python system_explorer.py register "software_name"
"""

import os
import sys
import json
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import argparse

# Windows Console UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# ============================================================================
# BACH-PFADE (angepasst von RecludOS)
# ============================================================================
SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parent.parent  # tools/partner_communication -> BACH
DATA_DIR = BACH_ROOT / "data"
DB_PATH = DATA_DIR / "bach.db"
PARTNERS_DIR = DATA_DIR / "partners"


class SystemExplorer:
    """Erkundet das System nach Software und Ressourcen"""
    
    def __init__(self, base_path: str = None):
        self.script_dir = SCRIPT_DIR
        self.base_path = Path(base_path) if base_path else BACH_ROOT
        self.data_dir = DATA_DIR
        self.partners_dir = PARTNERS_DIR
        self.config = self._load_config()
        self.registry = self._load_registry()
        self.scan_results = []
        
    def _load_config(self) -> Dict:
        """Lädt Konfiguration"""
        config_path = self.script_dir / "config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return self._default_config()
    
    def _default_config(self) -> Dict:
        """Standard-Konfiguration falls keine config.json existiert"""
        if sys.platform == "win32":
            scan_dirs = [
                "%PROGRAMFILES%",
                "%PROGRAMFILES(X86)%",
                "%LOCALAPPDATA%\\Programs"
            ]
            exclude = ["Windows", "System32", "SysWOW64", "$Recycle.Bin"]
            extensions = {
                "executables": [".exe"],
                "scripts": [".py", ".ps1", ".bat", ".cmd"]
            }
        elif sys.platform == "darwin":
            scan_dirs = [
                "/Applications",
                "/usr/local/bin",
                "/opt/homebrew/bin",
                str(Path.home() / "Applications")
            ]
            exclude = [".Trash", "Library", ".Spotlight-V100"]
            extensions = {
                "executables": [],
                "scripts": [".py", ".sh", ".command"]
            }
        else:
            scan_dirs = [
                "/usr/bin",
                "/usr/local/bin",
                "/opt",
                str(Path.home() / ".local" / "bin")
            ]
            exclude = ["proc", "sys", "dev", "run", "snap"]
            extensions = {
                "executables": [],
                "scripts": [".py", ".sh"]
            }

        return {
            "scan_directories": {
                "default": scan_dirs,
                "user_defined": []
            },
            "exclude_directories": exclude,
            "file_extensions": extensions,
            "max_depth": 4,
            "enable_system_wide_search": False,
            "known_ai_compatible_software": {
                "cli_tools": ["python", "node", "npm", "git", "ffmpeg", "curl", "wget"],
                "ai_tools": ["ollama", "claude", "copilot"],
                "ide_with_cli": ["code", "cursor", "pycharm"]
            }
        }
    
    def _load_registry(self) -> Dict:
        """Lädt bestehende Software-Registry aus BACH data/"""
        registry_path = self.data_dir / "software_registry.json"
        if registry_path.exists():
            with open(registry_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"software": [], "last_scan": None, "version": "1.0.0"}
    
    def _save_registry(self):
        """Speichert Software-Registry in BACH data/"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        registry_path = self.data_dir / "software_registry.json"
        self.registry["last_scan"] = datetime.now().isoformat()
        with open(registry_path, 'w', encoding='utf-8') as f:
            json.dump(self.registry, f, indent=2, ensure_ascii=False)
        print(f"📝 Registry gespeichert: {registry_path}")
    
    def _expand_path(self, path: str) -> str:
        """Expandiert Umgebungsvariablen in Pfaden"""
        return os.path.expandvars(path)

    def scan(self, mode: str = "standard") -> List[Dict]:
        """
        Scannt System nach Software
        
        Modes:
        - standard: Nur Hauptprogrammordner
        - deep: Inkl. AppData
        - full: Systemweite Suche
        """
        print(f"🔍 Starte System-Scan (Modus: {mode})...")
        
        directories = []
        
        # Basis-Verzeichnisse
        if mode in ["standard", "deep", "full"]:
            scan_dirs = self.config.get("scan_directories", {})
            for path in scan_dirs.get("default", scan_dirs.get("windows", [])):
                expanded = self._expand_path(path)
                if os.path.exists(expanded):
                    directories.append(expanded)

        # User-definierte Verzeichnisse
        for path in self.config.get("scan_directories", {}).get("user_defined", []):
            if os.path.exists(path):
                directories.append(path)

        # Systemweite Suche
        if mode == "full" and self.config.get("enable_system_wide_search"):
            if sys.platform == "win32":
                directories.extend(["C:\\", "D:\\"])
            elif sys.platform == "darwin":
                directories.append("/")
            else:
                directories.extend(["/usr", "/opt", "/home"])
        
        # Scan durchführen
        for directory in directories:
            print(f"  📂 Scanne: {directory}")
            self._scan_directory(directory)
        
        print(f"\n✅ Scan abgeschlossen: {len(self.scan_results)} Programme gefunden")
        return self.scan_results
    
    def _scan_directory(self, directory: str, depth: int = 0):
        """Scannt ein Verzeichnis rekursiv"""
        max_depth = self.config.get("max_depth", 4)
        exclude = self.config.get("exclude_directories", [])
        extensions = []
        
        for ext_list in self.config.get("file_extensions", {}).values():
            extensions.extend(ext_list)
        
        try:
            for entry in os.scandir(directory):
                # Ausschlüsse prüfen
                if entry.name in exclude:
                    continue
                
                if entry.is_dir() and depth < max_depth:
                    self._scan_directory(entry.path, depth + 1)
                elif entry.is_file():
                    ext = Path(entry.name).suffix.lower()
                    if ext in extensions:
                        software = self._analyze_file(entry.path)
                        if software:
                            self.scan_results.append(software)
        except PermissionError:
            pass
        except Exception:
            pass

    def _analyze_file(self, filepath: str) -> Optional[Dict]:
        """Analysiert eine Datei und extrahiert Software-Informationen"""
        path = Path(filepath)
        name = path.stem
        
        # Bekannte System-Dateien ignorieren
        ignore_patterns = ["unins", "setup", "install", "update", "crash", "dump"]
        if any(p in name.lower() for p in ignore_patterns):
            return None
        
        software = {
            "name": name,
            "path": str(path),
            "extension": path.suffix.lower(),
            "size_bytes": path.stat().st_size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "interface": self._detect_interface(path),
            "ai_compatibility": self._detect_ai_compatibility(name, path),
            "capabilities": [],
            "delegation_potential": "unknown",
            "registered_in_partners": False
        }
        
        return software
    
    def _detect_interface(self, path: Path) -> str:
        """Erkennt ob Software GUI oder CLI ist"""
        name_lower = path.stem.lower()
        
        # CLI-Indikatoren
        cli_patterns = ["cli", "cmd", "console", "terminal", "shell"]
        if any(p in name_lower for p in cli_patterns):
            return "cli"
        
        # Bekannte CLI-Tools
        known_cli = self.config.get("known_ai_compatible_software", {}).get("cli_tools", [])
        if name_lower in [t.lower() for t in known_cli]:
            return "cli"
        
        # Scripts sind meist CLI
        if path.suffix.lower() in [".py", ".ps1", ".bat", ".cmd", ".sh"]:
            return "cli"
        
        return "gui"
    
    def _detect_ai_compatibility(self, name: str, path: Path) -> Dict:
        """Erkennt AI/Automatisierungs-Kompatibilität"""
        name_lower = name.lower()
        
        result = {
            "level": "unknown",
            "cli_available": False,
            "api_available": False,
            "automation_ready": False,
            "notes": []
        }
        
        # Bekannte CLI-Tools
        known_cli = self.config.get("known_ai_compatible_software", {}).get("cli_tools", [])
        if name_lower in [t.lower() for t in known_cli]:
            result["level"] = "cli_native"
            result["cli_available"] = True
            result["automation_ready"] = True
            result["notes"].append("Bekanntes CLI-Tool")
        
        # AI-Tools
        ai_tools = self.config.get("known_ai_compatible_software", {}).get("ai_tools", [])
        if name_lower in [t.lower() for t in ai_tools]:
            result["level"] = "cli_native"
            result["cli_available"] = True
            result["api_available"] = True
            result["notes"].append("AI/ML Tool")
        
        # IDEs mit CLI
        ide_cli = self.config.get("known_ai_compatible_software", {}).get("ide_with_cli", [])
        if name_lower in [t.lower() for t in ide_cli]:
            result["level"] = "cli_partial"
            result["cli_available"] = True
            result["notes"].append("IDE mit CLI-Unterstützung")
        
        # Scripts
        if path.suffix.lower() in [".py", ".ps1", ".bat"]:
            result["level"] = "cli_native"
            result["cli_available"] = True
            result["automation_ready"] = True
        
        return result

    def suggest_integrations(self) -> List[Dict]:
        """Schlägt Integrationen für AI-kompatible Software vor"""
        suggestions = []
        
        for software in self.registry.get("software", []):
            ai_compat = software.get("ai_compatibility", {})
            
            if ai_compat.get("level") in ["cli_native", "cli_partial"]:
                suggestion = {
                    "software": software["name"],
                    "path": software["path"],
                    "reason": ai_compat.get("notes", []),
                    "suggested_location": self._get_partner_path(software),
                    "delegation_type": self._suggest_delegation_type(software),
                    "priority": "high" if ai_compat.get("level") == "cli_native" else "medium"
                }
                suggestions.append(suggestion)
        
        # Speichere Vorschläge in BACH logs/
        log_dir = BACH_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        suggestions_path = log_dir / "integration_suggestions.json"
        with open(suggestions_path, 'w', encoding='utf-8') as f:
            json.dump(suggestions, f, indent=2, ensure_ascii=False)
        
        return suggestions
    
    def _get_partner_path(self, software: Dict) -> str:
        """Bestimmt den Pfad in data/partners/ für die Software"""
        interface = software.get("interface", "gui")
        name = software["name"].lower().replace(" ", "_")
        
        if interface == "cli":
            return f"data/partners/cli_tools/{name}"
        else:
            return f"data/partners/gui_tools/{name}"
    
    def _suggest_delegation_type(self, software: Dict) -> str:
        """Schlägt Delegations-Typ vor"""
        ai_compat = software.get("ai_compatibility", {})
        
        if ai_compat.get("api_available"):
            return "api_delegation"
        elif ai_compat.get("cli_available"):
            return "cli_delegation"
        elif ai_compat.get("automation_ready"):
            return "automation_delegation"
        else:
            return "manual_delegation"
    
    def register_in_partners(self, software_name: str) -> bool:
        """Registriert Software in data/partners/"""
        software = None
        for s in self.registry.get("software", []):
            if s["name"].lower() == software_name.lower():
                software = s
                break
        
        if not software:
            print(f"❌ Software nicht gefunden: {software_name}")
            return False
        
        partner_path = self._get_partner_path(software)
        full_path = BACH_ROOT / partner_path
        
        # Ordner erstellen
        full_path.mkdir(parents=True, exist_ok=True)
        
        # Registry erstellen
        registry = {
            "name": software["name"],
            "path": software["path"],
            "interface": software.get("interface", "unknown"),
            "ai_compatibility": software.get("ai_compatibility", {}),
            "registered_at": datetime.now().isoformat(),
            "delegation_enabled": software.get("ai_compatibility", {}).get("cli_available", False)
        }
        
        registry_path = full_path / "registry.json"
        with open(registry_path, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        
        # Delegation-Template für CLI-Tools
        if software.get("interface") == "cli":
            template = {
                "name": software["name"],
                "command_template": f"{software['path']} {{args}}",
                "common_arguments": [],
                "examples": []
            }
            template_path = full_path / "delegation_template.json"
            with open(template_path, 'w', encoding='utf-8') as f:
                json.dump(template, f, indent=2, ensure_ascii=False)
        
        # Update Registry
        for s in self.registry.get("software", []):
            if s["name"] == software["name"]:
                s["registered_in_partners"] = True
                break
        self._save_registry()
        
        print(f"✅ Registriert: {software_name} → {partner_path}")
        return True

    def list_software(self, filter_type: str = None) -> List[Dict]:
        """Listet erfasste Software"""
        software = self.registry.get("software", [])
        
        if filter_type == "cli":
            return [s for s in software if s.get("interface") == "cli"]
        elif filter_type == "gui":
            return [s for s in software if s.get("interface") == "gui"]
        elif filter_type == "ai_compatible":
            return [s for s in software 
                    if s.get("ai_compatibility", {}).get("level") in ["cli_native", "cli_partial"]]
        elif filter_type == "registered":
            return [s for s in software if s.get("registered_in_partners")]
        elif filter_type == "unregistered":
            return [s for s in software if not s.get("registered_in_partners")]
        
        return software
    
    def run_scan_and_save(self, mode: str = "standard"):
        """Führt Scan durch und speichert Ergebnisse"""
        results = self.scan(mode)
        
        # Merge mit bestehender Registry (keine Duplikate)
        existing_paths = {s["path"] for s in self.registry.get("software", [])}
        new_software = [s for s in results if s["path"] not in existing_paths]
        
        self.registry["software"].extend(new_software)
        self._save_registry()
        
        print(f"📊 {len(new_software)} neue Programme hinzugefügt")
        print(f"📊 Gesamt: {len(self.registry['software'])} Programme in Registry")


def main():
    """CLI-Interface für System Explorer"""
    parser = argparse.ArgumentParser(description="BACH System Explorer - Software-Erkennung")
    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")
    
    # Scan
    scan_parser = subparsers.add_parser("scan", help="System nach Software scannen")
    scan_parser.add_argument("--mode", choices=["standard", "deep", "full"], 
                            default="standard", help="Scan-Modus")
    
    # List
    list_parser = subparsers.add_parser("list", help="Erfasste Software auflisten")
    list_parser.add_argument("--filter", choices=["cli", "gui", "ai_compatible", "registered", "unregistered"],
                            help="Filter für Liste")
    
    # Suggest
    subparsers.add_parser("suggest", help="Integrationsvorschläge erstellen")
    
    # Register
    reg_parser = subparsers.add_parser("register", help="Software in data/partners/ registrieren")
    reg_parser.add_argument("name", help="Name der Software")
    
    args = parser.parse_args()
    explorer = SystemExplorer()
    
    if args.command == "scan":
        explorer.run_scan_and_save(args.mode)
        
    elif args.command == "list":
        software = explorer.list_software(args.filter)
        print(f"\n📋 Software-Liste ({len(software)} Einträge):\n")
        for s in software[:50]:  # Max 50 anzeigen
            ai = s.get("ai_compatibility", {}).get("level", "?")
            reg = "✓" if s.get("registered_in_partners") else "○"
            print(f"  [{reg}] {s['name']:<30} | {s.get('interface', '?'):<4} | AI: {ai}")
        if len(software) > 50:
            print(f"\n  ... und {len(software) - 50} weitere")
            
    elif args.command == "suggest":
        suggestions = explorer.suggest_integrations()
        print(f"\n💡 {len(suggestions)} Integrationsvorschläge:\n")
        for s in suggestions[:20]:
            print(f"  [{s['priority']}] {s['software']}")
            print(f"        → {s['suggested_location']}")
            print(f"        Typ: {s['delegation_type']}")
            
    elif args.command == "register":
        explorer.register_in_partners(args.name)
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
