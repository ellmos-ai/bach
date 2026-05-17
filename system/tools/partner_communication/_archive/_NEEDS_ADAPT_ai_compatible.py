#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""AI-kompatible Software Analyse"""

import json
import os
import sys
import io
from collections import Counter, defaultdict
from pathlib import Path

# Windows Console fix
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

# Sammeln
ai_compatible = []
by_category = defaultdict(list)
interfaces = Counter()

for sw in data.get('software', []):
    ai = sw.get('ai_compatibility', {})
    
    if ai.get('level') == 'cli_native' or ai.get('cli_available'):
        tool = {
            'name': sw['name'],
            'path': sw.get('path', ''),
            'interface': sw.get('interface', 'unknown'),
            'level': ai.get('level', 'unknown'),
            'notes': ai.get('notes', []),
            'automation': ai.get('automation_ready', False)
        }
        ai_compatible.append(tool)
        interfaces[sw.get('interface', 'unknown')] += 1
        
        # Kategorisieren nach Notes
        notes_str = ' '.join(ai.get('notes', []))
        if 'CLI-Tool' in notes_str:
            by_category['CLI Tools'].append(tool)
        elif 'IDE' in notes_str:
            by_category['IDEs & Editors'].append(tool)
        elif 'Python' in notes_str or 'pip' in sw['name'].lower():
            by_category['Python Ecosystem'].append(tool)
        elif 'Node' in notes_str or 'npm' in sw['name'].lower():
            by_category['Node.js Ecosystem'].append(tool)
        elif 'Git' in notes_str or 'git' in sw['name'].lower():
            by_category['Version Control'].append(tool)
        elif sw.get('extension') in ['.py', '.pyw']:
            by_category['Python Scripts'].append(tool)
        elif sw.get('extension') in ['.ps1', '.bat', '.cmd']:
            by_category['Shell Scripts'].append(tool)
        else:
            by_category['Other Tools'].append(tool)

# Deduplizieren
seen = set()
unique = []
for tool in ai_compatible:
    name_lower = tool['name'].lower()
    if name_lower not in seen:
        seen.add(name_lower)
        unique.append(tool)

# Output
print("=" * 70)
print("  AI-KOMPATIBLE SOFTWARE - UEBERSICHT")
print("=" * 70)
print()
print(f"  Gesamt in Registry:      {len(data.get('software', [])):,}")
print(f"  AI-kompatibel (roh):     {len(ai_compatible):,}")
print(f"  AI-kompatibel (unique):  {len(unique):,}")
print()

print("-" * 70)
print("  NACH INTERFACE")
print("-" * 70)
for iface, count in interfaces.most_common():
    bar = "#" * min(count / 50, 30)
    print(f"  {iface:<25} {count:>5}  {bar}")
print()

print("-" * 70)
print("  NACH KATEGORIE")
print("-" * 70)
for cat, tools in sorted(by_category.items(), key=lambda x: -len(x[1])):
    # Deduplizieren innerhalb Kategorie
    unique_in_cat = []
    seen_cat = set()
    for t in tools:
        if t['name'].lower() not in seen_cat:
            seen_cat.add(t['name'].lower())
            unique_in_cat.append(t)
    print(f"\n  {cat} ({len(unique_in_cat)} unique)")
    print(f"  {'-' * 40}")
    for t in unique_in_cat[:15]:
        auto = "+" if t['automation'] else " "
        print(f"    [{auto}] {t['name'][:30]:<30}")
    if len(unique_in_cat) > 15:
        print(f"    ... und {len(unique_in_cat) - 15} weitere")

print()
print("-" * 70)
print("  TOP 50 AI-KOMPATIBLE TOOLS (alphabetisch)")
print("-" * 70)

# Sortiere unique alphabetisch und zeige Top 50
sorted_unique = sorted(unique, key=lambda x: x['name'].lower())
for i, tool in enumerate(sorted_unique[:50], 1):
    auto = "+" if tool['automation'] else " "
    notes = tool['notes'][0][:25] if tool['notes'] else ""
    print(f"  {i:3}. [{auto}] {tool['name']:<25} {notes}")

if len(unique) > 50:
    print(f"\n  ... und {len(unique) - 50} weitere Tools")

print()
print("=" * 70)
print(f"  Legende: [+] = automation_ready")
print("=" * 70)
