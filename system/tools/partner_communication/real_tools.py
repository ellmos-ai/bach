#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH Real CLI Tools Analyse v1.0.0

Analysiert echte AI-kompatible CLI-Tools (nur EXE/CMD/BAT).
Filtert Python-Module heraus und zeigt nur direkt aufrufbare Tools.

Usage:
  python real_tools.py              # Vollständige Analyse
  python real_tools.py --json       # JSON-Ausgabe
  python real_tools.py --list       # Nur Tool-Namen
"""

import json
import sys
import argparse
from collections import Counter
from pathlib import Path
from typing import Dict, List

# Windows Console UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# ============================================================================
# BACH-PFADE
# ============================================================================
SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parent.parent  # tools/partner_communication -> BACH
DATA_DIR = BACH_ROOT / "data"
REGISTRY_PATH = DATA_DIR / "software_registry.json"

# Bekannte Tools für Kategorisierung
KNOWN_TOOLS = {
    'runtimes': ['python', 'python3', 'pythonw', 'node', 'ruby', 'perl', 'java', 'javaw', 'php', 'lua', 'r', 'julia'],
    'package_mgr': ['pip', 'pip3', 'npm', 'yarn', 'pnpm', 'conda', 'cargo', 'gem', 'composer', 'nuget', 'choco', 'winget', 'scoop'],
    'media': ['ffmpeg', 'ffprobe', 'vlc', 'imagemagick', 'convert', 'mogrify', 'gifsicle', 'optipng', 'pngquant', 'handbrake', 'youtube-dl', 'yt-dlp'],
    'network': ['curl', 'wget', 'ssh', 'scp', 'rsync', 'ftp', 'sftp', 'telnet', 'netcat', 'nc', 'nmap', 'ping', 'tracert', 'ipconfig', 'netstat'],
    'archive': ['7z', '7za', 'zip', 'unzip', 'tar', 'rar', 'unrar', 'gzip', 'gunzip', 'bzip2', 'xz'],
    'vcs': ['git', 'svn', 'hg', 'mercurial', 'cvs'],
    'database': ['mysql', 'psql', 'sqlite3', 'mongo', 'redis-cli', 'sqlcmd'],
    'ides': ['code', 'notepad++', 'vim', 'nvim', 'nano', 'emacs', 'atom', 'sublime_text', 'pycharm', 'idea', 'webstorm'],
    'devtools': ['make', 'cmake', 'ninja', 'msbuild', 'gcc', 'g++', 'clang', 'rustc', 'go', 'dotnet', 'docker', 'kubectl', 'terraform', 'ansible']
}


def load_registry() -> Dict:
    """Lädt Software-Registry aus BACH data/"""
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"software": [], "last_scan": None, "version": "1.0.0"}


def categorize_tool(tool: Dict) -> str:
    """Kategorisiert ein Tool basierend auf bekannten Tool-Listen"""
    name_lower = tool['name'].lower()
    notes = tool.get('notes', '').lower()
    
    if name_lower in KNOWN_TOOLS['vcs'] or 'git' in name_lower:
        return 'Version Control'
    elif name_lower in KNOWN_TOOLS['runtimes']:
        return 'Runtimes & Interpreter'
    elif name_lower in KNOWN_TOOLS['package_mgr']:
        return 'Package Managers'
    elif name_lower in KNOWN_TOOLS['media']:
        return 'Media & Grafik'
    elif name_lower in KNOWN_TOOLS['network']:
        return 'Network Tools'
    elif name_lower in KNOWN_TOOLS['archive']:
        return 'Archive Tools'
    elif name_lower in KNOWN_TOOLS['database']:
        return 'Datenbank Tools'
    elif name_lower in KNOWN_TOOLS['ides']:
        return 'IDEs & Editors'
    elif name_lower in KNOWN_TOOLS['devtools']:
        return 'Entwickler Tools'
    elif 'cli-tool' in notes:
        return 'CLI Tools (bekannt)'
    elif 'ide' in notes:
        return 'IDEs & Editors'
    return 'Sonstige'


def analyze_real_tools(registry: Dict) -> Dict:
    """Analysiert echte CLI-Tools (nur EXE/CMD/BAT)"""
    real_tools = []
    categories = {}
    
    for sw in registry.get('software', []):
        ai = sw.get('ai_compatibility', {})
        ext = sw.get('extension', '')
        
        # Nur .exe, .cmd, .bat - keine .py Module
        if ext in ['.exe', '.cmd', '.bat'] and (ai.get('level') == 'cli_native' or ai.get('cli_available')):
            notes = ' '.join(ai.get('notes', []))
            
            tool = {
                'name': sw['name'],
                'path': sw.get('path', ''),
                'notes': notes[:40],
                'automation': ai.get('automation_ready', False)
            }
            real_tools.append(tool)
            
            category = categorize_tool(tool)
            if category not in categories:
                categories[category] = []
            categories[category].append(tool)
    
    # Deduplizieren
    seen = set()
    unique = []
    for t in real_tools:
        if t['name'].lower() not in seen:
            seen.add(t['name'].lower())
            unique.append(t)
    
    return {
        'total_in_registry': len(registry.get('software', [])),
        'exe_cmd_bat_count': len(real_tools),
        'unique_count': len(unique),
        'unique_tools': unique,
        'by_category': categories
    }


def print_analysis(analysis: Dict):
    """Gibt formatierte Analyse aus"""
    print('=' * 70)
    print('  ECHTE AI-KOMPATIBLE TOOLS (EXE/CMD/BAT)')
    print('=' * 70)
    print()
    print(f'  Gesamt in Registry:     {analysis["total_in_registry"]:,}')
    print(f'  Davon EXE/CMD/BAT:      {analysis["exe_cmd_bat_count"]:,}')
    print(f'  Unique Tools:           {analysis["unique_count"]}')
    print()
    print('=' * 70)
    print('  NACH KATEGORIE')
    print('=' * 70)
    
    for cat, tools in sorted(analysis['by_category'].items(), key=lambda x: x[0]):
        if tools:
            # Deduplizieren pro Kategorie
            seen_cat = set()
            unique_cat = []
            for t in tools:
                if t['name'].lower() not in seen_cat:
                    seen_cat.add(t['name'].lower())
                    unique_cat.append(t)
            
            if unique_cat:
                print()
                print(f'  {cat} ({len(unique_cat)})')
                print('  ' + '-' * 50)
                for t in sorted(unique_cat, key=lambda x: x['name'].lower())[:25]:
                    auto = '+' if t['automation'] else ' '
                    n = t['notes'][:30] if t['notes'] else ''
                    print(f'    [{auto}] {t["name"]:<20} {n}')
                if len(unique_cat) > 25:
                    print(f'    ... und {len(unique_cat) - 25} weitere')
    
    print()
    print('=' * 70)
    print('  Legende: [+] = automation_ready')
    print('=' * 70)


def main():
    parser = argparse.ArgumentParser(description='BACH Real CLI Tools Analyse')
    parser.add_argument('--json', action='store_true', help='JSON-Ausgabe')
    parser.add_argument('--list', action='store_true', help='Nur Tool-Namen')
    args = parser.parse_args()
    
    if not REGISTRY_PATH.exists():
        print(f"⚠️  Registry nicht gefunden: {REGISTRY_PATH}")
        print("   Führe zuerst 'python system_explorer.py scan' aus.")
        sys.exit(1)
    
    registry = load_registry()
    analysis = analyze_real_tools(registry)
    
    if args.json:
        print(json.dumps(analysis, indent=2, ensure_ascii=False))
    elif args.list:
        for tool in sorted(analysis['unique_tools'], key=lambda x: x['name'].lower()):
            auto = "+" if tool['automation'] else " "
            print(f"[{auto}] {tool['name']}")
    else:
        print_analysis(analysis)


if __name__ == "__main__":
    main()
