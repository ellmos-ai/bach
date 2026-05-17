#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Analyse echter AI-kompatibler Tools (nur EXE/CMD/BAT)"""

import json
import os
import sys
import io
from collections import Counter
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

path = Path(
    os.getenv(
        "BACH_SOFTWARE_REGISTRY",
        Path.home()
        / "OneDrive"
        / ".AI"
        / "BACH"
        / "main"
        / "system"
        / "act"
        / "communicate"
        / "system-explorer"
        / "software_registry.json",
    )
)

with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Nur echte EXE/CMD/BAT Tools (keine .py Module)
real_tools = []
categories = {
    'CLI Tools (bekannt)': [],
    'IDEs & Editors': [],
    'Runtimes & Interpreter': [],
    'Package Managers': [],
    'Media & Grafik': [],
    'Network Tools': [],
    'Archive Tools': [],
    'Version Control': [],
    'Datenbank Tools': [],
    'System Tools': [],
    'Entwickler Tools': [],
    'Sonstige': []
}

# Bekannte Tools fuer Kategorisierung
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

for sw in data.get('software', []):
    ai = sw.get('ai_compatibility', {})
    ext = sw.get('extension', '')
    
    # Nur .exe, .cmd, .bat - keine .py Module
    if ext in ['.exe', '.cmd', '.bat'] and (ai.get('level') == 'cli_native' or ai.get('cli_available')):
        name_lower = sw['name'].lower()
        notes = ' '.join(ai.get('notes', []))
        
        tool = {
            'name': sw['name'],
            'path': sw.get('path', ''),
            'notes': notes[:40],
            'automation': ai.get('automation_ready', False)
        }
        real_tools.append(tool)
        
        # Kategorisieren
        categorized = False
        
        if name_lower in KNOWN_TOOLS['vcs'] or 'git' in name_lower:
            categories['Version Control'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['runtimes']:
            categories['Runtimes & Interpreter'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['package_mgr']:
            categories['Package Managers'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['media']:
            categories['Media & Grafik'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['network']:
            categories['Network Tools'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['archive']:
            categories['Archive Tools'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['database']:
            categories['Datenbank Tools'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['ides']:
            categories['IDEs & Editors'].append(tool)
            categorized = True
        elif name_lower in KNOWN_TOOLS['devtools']:
            categories['Entwickler Tools'].append(tool)
            categorized = True
        elif 'cli-tool' in notes.lower():
            categories['CLI Tools (bekannt)'].append(tool)
            categorized = True
        elif 'ide' in notes.lower():
            categories['IDEs & Editors'].append(tool)
            categorized = True
        
        if not categorized:
            categories['Sonstige'].append(tool)

# Deduplizieren global
seen = set()
unique = []
for t in real_tools:
    if t['name'].lower() not in seen:
        seen.add(t['name'].lower())
        unique.append(t)

print('=' * 70)
print('  ECHTE AI-KOMPATIBLE TOOLS (EXE/CMD/BAT)')
print('=' * 70)
print()
print(f'  Gesamt in Registry:     {len(data.get("software", [])):,}')
print(f'  Davon EXE/CMD/BAT:      {len(real_tools):,}')
print(f'  Unique Tools:           {len(unique)}')
print()
print('=' * 70)
print('  NACH KATEGORIE')
print('=' * 70)

for cat, tools in categories.items():
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
print('  BEREITS IN CLI_TOOLS REGISTRIERT: 12')
print('  git, python, node, pip, pip3, 7z, ffmpeg, curl, ssh, grep, code, notepad++')
print('=' * 70)
