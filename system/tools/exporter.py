#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
exporter.py
===========
Export-Tool für Skills, Agents und OS.

Version: 1.0.0
Erstellt: 2026-01-14

KONZEPT:
  Im OS sind Skills/Agents leichtgewichtig (nutzen OS-Infrastruktur).
  Für externe Nutzung müssen sie "verpackt" werden mit eigener Infrastruktur.

BEFEHLE:
  skill     Exportiert einen Skill aus dem OS als Standalone
  agent     Exportiert einen Agent mit seinen Skills
  os-fresh  Erstellt ein frisches OS-Paket (ohne Userdaten)
  os-reset  Setzt ein OS zurück (löscht Userdaten)

Verwendung:
    python exporter.py skill <name> --from-os <os-path> [--output <zip>]
    python exporter.py agent <name> --from-os <os-path> [--output <zip>]
    python exporter.py os-fresh <os-path> [--output <zip>] [--version <v>]
    python exporter.py os-reset <os-path> [--backup] [--confirm]

Beispiele:
    python exporter.py skill recherche --from-os ./mein-os
    python exporter.py agent schreib-assistent --from-os ./mein-os
    python exporter.py os-fresh ./mein-os --output os-v1.0.zip
    python exporter.py os-reset ./mein-os --backup
"""

import os
import sys
import json
import shutil
import argparse
import zipfile
from datetime import datetime
from pathlib import Path

# =============================================================================
# KONSTANTEN
# =============================================================================

# Standalone-Skill Struktur
STANDALONE_SKILL_STRUCTURE = {
    "_config": ["config.json"],
    "_data": ["tasks.json"],
    "_memory": ["usage_log.json", "lessons_learned.md", "preferences.json"],
    "_backup": []
}

# Standalone-Agent Struktur
STANDALONE_AGENT_STRUCTURE = {
    "_config": ["config.json", "skills.json", "workflow_config.json"],
    "_data": ["tasks.json", "tasks_done.json"],
    "_data/projekte": [],
    "_data/inputs": [],
    "_data/outputs": [],
    "_memory": ["context.md", "preferences.json"],
    "_memory/session": [],
    "_memory/global": ["lessons_learned.md", "entscheidungen.md"],
    "_memory/projekte": [],
    "_workflows": ["_index.md"],
    "_skills": ["_registry.json"],
    "_backup": [],
    "_reports/sessions": [],
    "_reports/projekte": []
}

# OS System-Ordner (bleiben bei Reset)
OS_SYSTEM_FOLDERS = ["_system", "_boot", "_registry", "_config", "skills", "agents"]

# OS User-Ordner (werden bei Reset gelöscht)
OS_USER_FOLDERS = ["_user", "_memory", "_backup", "_data"]

# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def create_zip(source_path: Path, output_path: Path) -> bool:
    """Erstellt ein ZIP-Archiv"""
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in source_path.rglob('*'):
                if file.is_file():
                    arcname = file.relative_to(source_path)
                    zipf.write(file, arcname)
        return True
    except Exception as e:
        print(f"[!] ZIP-Fehler: {e}")
        return False


def get_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_folder(path: Path, files: list = None):
    """Erstellt Ordner mit optionalen Dateien"""
    path.mkdir(parents=True, exist_ok=True)
    if files:
        for f in files:
            (path / f).touch()


def generate_config_json(name: str, item_type: str, profile: str) -> str:
    """Generiert config.json"""
    return json.dumps({
        "name": name,
        "type": item_type,
        "profile": profile,
        "version": "0.1.0",
        "exported_from": "os",
        "export_date": datetime.now().strftime("%Y-%m-%d"),
        "generator": "exporter.py",
        "settings": {
            "memory_enabled": True,
            "standalone": True
        }
    }, indent=4, ensure_ascii=False)


def generate_readme(name: str, item_type: str, original_path: str) -> str:
    """Generiert README.md"""
    return f'''# {name}

> Standalone {item_type.capitalize()} - Exportiert aus OS

## Herkunft

- **Exportiert von:** {original_path}
- **Export-Datum:** {datetime.now().strftime("%Y-%m-%d")}
- **Tool:** exporter.py (BACH_STREAM)

## Für Claude

**Einstiegspunkt:** `SKILL.md`

## Hinweis

Dieser {item_type.capitalize()} wurde aus einem OS exportiert und enthält
nun eine eigene Infrastruktur (Memory, Config, Backup) für Standalone-Nutzung.
'''


# =============================================================================
# SKILL EXPORT
# =============================================================================

def export_skill(name: str, os_path: Path, output: Path = None) -> bool:
    """Exportiert einen Skill aus dem OS als Standalone"""
    
    print(f"\n[+] Exportiere Skill: {name}")
    print(f"[+] Aus OS: {os_path}")
    
    # Skill im OS finden
    skill_locations = [
        os_path / "skills" / f"{name}.md",
        os_path / "skills" / name / "SKILL.md",
        os_path / "_user" / "skills" / f"{name}.md",
        os_path / "_user" / "skills" / name / "SKILL.md"
    ]
    
    skill_file = None
    for loc in skill_locations:
        if loc.exists():
            skill_file = loc
            break
    
    if not skill_file:
        print(f"[!] Skill nicht gefunden: {name}")
        print(f"    Gesucht in: skills/, _user/skills/")
        return False
    
    print(f"[+] Gefunden: {skill_file}")
    
    # Temp-Ordner erstellen
    temp_dir = Path(f"_export_temp_{name}_{get_timestamp()}")
    export_dir = temp_dir / name
    export_dir.mkdir(parents=True)
    
    try:
        # SKILL.md kopieren
        skill_content = skill_file.read_text(encoding='utf-8')
        (export_dir / "SKILL.md").write_text(skill_content, encoding='utf-8')
        print(f"  📄 SKILL.md")
        
        # README.md erstellen
        readme = generate_readme(name, "skill", str(skill_file.parent))
        (export_dir / "README.md").write_text(readme, encoding='utf-8')
        print(f"  📄 README.md")
        
        # Standalone-Struktur erstellen
        for folder, files in STANDALONE_SKILL_STRUCTURE.items():
            folder_path = export_dir / folder
            folder_path.mkdir(parents=True, exist_ok=True)
            print(f"  📁 {folder}/")
            
            for filename in files:
                file_path = folder_path / filename
                if filename == "config.json":
                    content = generate_config_json(name, "skill", "STANDARD")
                elif filename == "tasks.json":
                    content = json.dumps([], indent=4)
                elif filename == "usage_log.json":
                    content = json.dumps({"version": "1.0", "entries": []}, indent=4)
                elif filename == "preferences.json":
                    content = json.dumps({"version": "1.0", "user_preferences": {}}, indent=4)
                elif filename.endswith(".md"):
                    content = f"# {filename.replace('.md', '').replace('_', ' ').title()}\n\n[TODO]\n"
                else:
                    content = ""
                
                file_path.write_text(content, encoding='utf-8')
                print(f"    📄 {filename}")
            
            if not files:
                (folder_path / ".gitkeep").write_text("# Placeholder\n", encoding='utf-8')
        
        # ZIP erstellen oder Ordner behalten
        if output:
            zip_path = output if str(output).endswith('.zip') else Path(f"{output}.zip")
            if create_zip(export_dir, zip_path):
                print(f"\n[+] ✅ Exportiert: {zip_path}")
                shutil.rmtree(temp_dir)
            else:
                return False
        else:
            # Ordner in aktuelles Verzeichnis verschieben
            final_path = Path(name)
            if final_path.exists():
                shutil.rmtree(final_path)
            shutil.move(str(export_dir), str(final_path))
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"\n[+] ✅ Exportiert: {final_path.absolute()}")
        
        return True
        
    except Exception as e:
        print(f"[!] Fehler: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False


# =============================================================================
# AGENT EXPORT
# =============================================================================

def export_agent(name: str, os_path: Path, output: Path = None) -> bool:
    """Exportiert einen Agent mit seinen Skills aus dem OS"""
    
    print(f"\n[+] Exportiere Agent: {name}")
    print(f"[+] Aus OS: {os_path}")
    
    # Agent im OS finden
    agent_locations = [
        os_path / "agents" / name,
        os_path / "agents" / f"{name}.md",
        os_path / "_user" / "agents" / name,
        os_path / "_user" / "agents" / f"{name}.md"
    ]
    
    agent_path = None
    agent_is_file = False
    for loc in agent_locations:
        if loc.exists():
            agent_path = loc
            agent_is_file = loc.is_file()
            break
    
    if not agent_path:
        print(f"[!] Agent nicht gefunden: {name}")
        return False
    
    print(f"[+] Gefunden: {agent_path}")
    
    # Temp-Ordner erstellen
    temp_dir = Path(f"_export_temp_{name}_{get_timestamp()}")
    export_dir = temp_dir / name
    export_dir.mkdir(parents=True)
    
    try:
        # Agent-Inhalt kopieren
        if agent_is_file:
            # Einzelne Datei
            content = agent_path.read_text(encoding='utf-8')
            (export_dir / "SKILL.md").write_text(content, encoding='utf-8')
        else:
            # Ordner
            for item in agent_path.rglob('*'):
                if item.is_file():
                    rel_path = item.relative_to(agent_path)
                    dest = export_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)
        
        print(f"  📄 Agent-Dateien kopiert")
        
        # Standalone-Struktur sicherstellen
        for folder, files in STANDALONE_AGENT_STRUCTURE.items():
            folder_path = export_dir / folder
            if not folder_path.exists():
                folder_path.mkdir(parents=True, exist_ok=True)
                print(f"  📁 {folder}/ (ergänzt)")
                
                for filename in files:
                    file_path = folder_path / filename
                    if not file_path.exists():
                        if filename == "config.json":
                            content = generate_config_json(name, "agent", "AGENT")
                        elif filename.endswith(".json"):
                            content = json.dumps({"version": "1.0"}, indent=4)
                        else:
                            content = f"# {filename}\n\n[TODO]\n"
                        file_path.write_text(content, encoding='utf-8')
                
                if not files:
                    (folder_path / ".gitkeep").write_text("# Placeholder\n", encoding='utf-8')
        
        # Skills extrahieren und mit exportieren
        skills_used = []
        skill_md = export_dir / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding='utf-8')
            # Einfache Extraktion - suche nach Skills-Referenzen
            # In echter Implementierung: Parse SKILL.md oder _skills/_registry.json
        
        # Skills aus OS kopieren
        skills_registry = export_dir / "_skills" / "_registry.json"
        if skills_registry.exists():
            try:
                registry = json.loads(skills_registry.read_text(encoding='utf-8'))
                for skill_entry in registry.get("skills", []):
                    skill_name = skill_entry.get("name", "")
                    if skill_name and not skill_entry.get("_example"):
                        # Skill aus OS holen
                        os_skill = os_path / "skills" / f"{skill_name}.md"
                        if os_skill.exists():
                            dest_skill = export_dir / "_skills" / skill_name
                            dest_skill.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(os_skill, dest_skill / "SKILL.md")
                            skills_used.append(skill_name)
                            print(f"  📦 Skill: {skill_name}")
            except (json.JSONDecodeError, OSError):
                pass
        
        # README ergänzen
        readme = generate_readme(name, "agent", str(agent_path))
        if skills_used:
            readme += f"\n## Enthaltene Skills\n\n"
            for s in skills_used:
                readme += f"- {s}\n"
        (export_dir / "README.md").write_text(readme, encoding='utf-8')
        
        # ZIP erstellen oder Ordner behalten
        if output:
            zip_path = output if str(output).endswith('.zip') else Path(f"{output}.zip")
            if create_zip(export_dir, zip_path):
                print(f"\n[+] ✅ Exportiert: {zip_path}")
                shutil.rmtree(temp_dir)
            else:
                return False
        else:
            final_path = Path(name)
            if final_path.exists():
                shutil.rmtree(final_path)
            shutil.move(str(export_dir), str(final_path))
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"\n[+] ✅ Exportiert: {final_path.absolute()}")
        
        return True
        
    except Exception as e:
        print(f"[!] Fehler: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False


# =============================================================================
# OS FRESH EXPORT
# =============================================================================

def export_os_fresh(os_path: Path, output: Path = None, version: str = "1.0") -> bool:
    """Erstellt ein frisches OS-Paket ohne Userdaten"""
    
    print(f"\n[+] Erstelle Fresh-OS von: {os_path}")
    
    if not os_path.exists():
        print(f"[!] OS nicht gefunden: {os_path}")
        return False
    
    # Temp-Ordner
    os_name = os_path.name
    temp_dir = Path(f"_export_temp_{os_name}_{get_timestamp()}")
    export_dir = temp_dir / f"{os_name}-fresh-v{version}"
    export_dir.mkdir(parents=True)
    
    try:
        print(f"\n[+] Kopiere System-Dateien...")
        
        # System-Ordner kopieren
        for folder in OS_SYSTEM_FOLDERS:
            src = os_path / folder
            if src.exists():
                dest = export_dir / folder
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                print(f"  📁 {folder}/")
        
        # Root-Dateien kopieren
        for item in os_path.iterdir():
            if item.is_file():
                shutil.copy2(item, export_dir / item.name)
                print(f"  📄 {item.name}")
        
        # Leere User-Struktur erstellen
        print(f"\n[+] Erstelle leere User-Struktur...")
        user_dir = export_dir / "_user"
        user_folders = [
            "_memory", "_memory/session", "_memory/global",
            "_projects", "_backup", 
            "skills", "agents"
        ]
        for folder in user_folders:
            (user_dir / folder).mkdir(parents=True, exist_ok=True)
            (user_dir / folder / ".gitkeep").write_text("# Placeholder\n", encoding='utf-8')
            print(f"  📁 _user/{folder}/")
        
        # Default User-Config
        user_config = {
            "version": "1.0",
            "created": datetime.now().strftime("%Y-%m-%d"),
            "user_preferences": {},
            "note": "Fresh installation - configure as needed"
        }
        (user_dir / "config.json").write_text(
            json.dumps(user_config, indent=4, ensure_ascii=False), encoding='utf-8'
        )
        
        # INSTALL.md erstellen
        install_md = f'''# Installation: {os_name}

> Version: {version}
> Erstellt: {datetime.now().strftime("%Y-%m-%d")}

## Installation

1. ZIP entpacken
2. In gewünschtes Verzeichnis verschieben
3. Fertig! Sofort nutzbar.

## Erste Schritte

1. `SKILL.md` lesen
2. `_user/config.json` anpassen
3. Loslegen!

## Struktur

- `_system/` - OS-Kern (nicht ändern)
- `skills/` - Standard-Skills
- `agents/` - Agent-Templates
- `_user/` - Deine Daten (hier arbeiten)

---
*Exportiert mit exporter.py (BACH_STREAM)*
'''
        (export_dir / "INSTALL.md").write_text(install_md, encoding='utf-8')
        print(f"  📄 INSTALL.md")
        
        # ZIP erstellen
        if output:
            zip_path = output if str(output).endswith('.zip') else Path(f"{output}.zip")
        else:
            zip_path = Path(f"{os_name}-fresh-v{version}.zip")
        
        if create_zip(export_dir, zip_path):
            print(f"\n[+] ✅ Fresh-OS erstellt: {zip_path}")
            print(f"    📦 Größe: {zip_path.stat().st_size / 1024:.1f} KB")
            shutil.rmtree(temp_dir)
            return True
        else:
            return False
        
    except Exception as e:
        print(f"[!] Fehler: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False


# =============================================================================
# OS RESET
# =============================================================================

def reset_os(os_path: Path, backup: bool = False, confirm: bool = False) -> bool:
    """Setzt ein OS zurück - löscht Userdaten"""
    
    print(f"\n[+] OS Reset: {os_path}")
    
    if not os_path.exists():
        print(f"[!] OS nicht gefunden: {os_path}")
        return False
    
    # User-Ordner identifizieren
    user_paths = []
    for folder in OS_USER_FOLDERS:
        p = os_path / folder
        if p.exists():
            user_paths.append(p)
    
    if not user_paths:
        print(f"[!] Keine User-Daten gefunden")
        return True
    
    print(f"\n[!] Folgende Ordner werden gelöscht:")
    for p in user_paths:
        size = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
        print(f"    - {p.name}/ ({size/1024:.1f} KB)")
    
    # Bestätigung
    if not confirm:
        response = input("\n    Wirklich fortfahren? (j/N): ").strip().lower()
        if response != 'j':
            print("    Abgebrochen.")
            return False
    
    # Backup erstellen
    if backup:
        backup_name = f"{os_path.name}_backup_{get_timestamp()}"
        backup_path = os_path.parent / backup_name
        backup_path.mkdir()
        
        print(f"\n[+] Erstelle Backup: {backup_path}")
        for p in user_paths:
            dest = backup_path / p.name
            shutil.copytree(p, dest)
            print(f"  📁 {p.name}/ → Backup")
        
        # Backup als ZIP
        zip_path = Path(f"{backup_name}.zip")
        create_zip(backup_path, zip_path)
        shutil.rmtree(backup_path)
        print(f"  📦 Backup: {zip_path}")
    
    # Löschen
    print(f"\n[+] Lösche User-Daten...")
    for p in user_paths:
        shutil.rmtree(p)
        print(f"  🗑️  {p.name}/")
    
    # Leere Struktur neu erstellen
    print(f"\n[+] Erstelle leere Struktur...")
    for folder in OS_USER_FOLDERS:
        p = os_path / folder
        p.mkdir(parents=True, exist_ok=True)
        (p / ".gitkeep").write_text("# Placeholder\n", encoding='utf-8')
        print(f"  📁 {folder}/")
    
    # User-Unterordner
    user_dir = os_path / "_user"
    if user_dir.exists():
        for sub in ["_memory", "_projects", "skills", "agents"]:
            (user_dir / sub).mkdir(parents=True, exist_ok=True)
            (user_dir / sub / ".gitkeep").write_text("# Placeholder\n", encoding='utf-8')
    
    print(f"\n[+] ✅ OS zurückgesetzt: {os_path}")
    return True


# =============================================================================
# CLI
# =============================================================================

def print_banner():
    print("=" * 65)
    print("  EXPORTER v1.0 - BACH_STREAM BUILD TOOL")
    print("=" * 65)
    print()
    print("  Befehle:")
    print("    skill      Skill aus OS exportieren")
    print("    agent      Agent mit Skills exportieren")
    print("    os-fresh   Frisches OS-Paket erstellen")
    print("    os-reset   OS zurücksetzen (Userdaten löschen)")
    print()


def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    parser = argparse.ArgumentParser(
        description='Export-Tool für Skills, Agents und OS',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Befehle')
    
    # skill
    p_skill = subparsers.add_parser('skill', help='Skill exportieren')
    p_skill.add_argument('name', help='Name des Skills')
    p_skill.add_argument('--from-os', required=True, help='Pfad zum OS')
    p_skill.add_argument('--output', '-o', help='Ausgabe (ZIP oder Ordner)')
    
    # agent
    p_agent = subparsers.add_parser('agent', help='Agent exportieren')
    p_agent.add_argument('name', help='Name des Agents')
    p_agent.add_argument('--from-os', required=True, help='Pfad zum OS')
    p_agent.add_argument('--output', '-o', help='Ausgabe (ZIP oder Ordner)')
    
    # os-fresh
    p_fresh = subparsers.add_parser('os-fresh', help='Fresh-OS erstellen')
    p_fresh.add_argument('os_path', help='Pfad zum OS')
    p_fresh.add_argument('--output', '-o', help='Ausgabe-ZIP')
    p_fresh.add_argument('--version', '-v', default='1.0', help='Version')
    
    # os-reset
    p_reset = subparsers.add_parser('os-reset', help='OS zurücksetzen')
    p_reset.add_argument('os_path', help='Pfad zum OS')
    p_reset.add_argument('--backup', '-b', action='store_true', help='Backup erstellen')
    p_reset.add_argument('--confirm', '-y', action='store_true', help='Ohne Nachfrage')
    
    args = parser.parse_args()
    
    print_banner()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == 'skill':
        success = export_skill(args.name, Path(args.from_os), 
                               Path(args.output) if args.output else None)
    
    elif args.command == 'agent':
        success = export_agent(args.name, Path(args.from_os),
                               Path(args.output) if args.output else None)
    
    elif args.command == 'os-fresh':
        success = export_os_fresh(Path(args.os_path),
                                  Path(args.output) if args.output else None,
                                  args.version)
    
    elif args.command == 'os-reset':
        success = reset_os(Path(args.os_path), args.backup, args.confirm)
    
    else:
        print(f"[!] Unbekannter Befehl: {args.command}")
        return 1
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
