#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
BACH AI-kompatible Software Analyse v1.0.0

Filtert und analysiert AI-kompatible Software aus der System-Registry.
Portiert von RecludOS für BACH-Integration.

Usage:
  python ai_compatible.py              # Vollständige Analyse
  python ai_compatible.py --json       # JSON-Ausgabe
  python ai_compatible.py --category   # Nach Kategorie gruppiert
"""

import json
import sys
import argparse
from collections import Counter, defaultdict
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


def load_registry() -> Dict:
    """Lädt Software-Registry aus BACH data/"""
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"software": [], "last_scan": None, "version": "1.0.0"}


def categorize_tool(tool: Dict) -> str:
    """Kategorisiert ein Tool basierend auf seinen Eigenschaften"""
    name = tool.get('name', '').lower()
    notes = tool.get('notes', [])
    notes_str = ' '.join(notes)
    extension = tool.get('extension', '')
    
    if 'CLI-Tool' in notes_str:
        return 'CLI Tools'
    elif 'IDE' in notes_str:
        return 'IDEs & Editors'
    elif 'Python' in notes_str or 'pip' in name:
        return 'Python Ecosystem'
    elif 'Node' in notes_str or 'npm' in name:
        return 'Node.js Ecosystem'
    elif 'Git' in notes_str or 'git' in name:
        return 'Version Control'
    elif extension in ['.py', '.pyw']:
        return 'Python Scripts'
    elif extension in ['.ps1', '.bat', '.cmd']:
        return 'Shell Scripts'
    return 'Other Tools'


def analyze_ai_compatible(registry: Dict) -> Dict:
    """Analysiert AI-kompatible Software aus Registry"""
    ai_compatible = []
    by_category = defaultdict(list)
    interfaces = Counter()
    
    for sw in registry.get('software', []):
        ai = sw.get('ai_compatibility', {})
        
        if ai.get('level') == 'cli_native' or ai.get('cli_available'):
            tool = {
                'name': sw['name'],
                'path': sw.get('path', ''),
                'interface': sw.get('interface', 'unknown'),
                'level': ai.get('level', 'unknown'),
                'notes': ai.get('notes', []),
                'automation': ai.get('automation_ready', False),
                'extension': sw.get('extension', '')
            }
            ai_compatible.append(tool)
            interfaces[sw.get('interface', 'unknown')] += 1
            
            category = categorize_tool(tool)
            by_category[category].append(tool)
    
    # Deduplizieren
    seen = set()
    unique = []
    for tool in ai_compatible:
        name_lower = tool['name'].lower()
        if name_lower not in seen:
            seen.add(name_lower)
            unique.append(tool)
    
    return {
        'total_in_registry': len(registry.get('software', [])),
        'ai_compatible_raw': len(ai_compatible),
        'ai_compatible_unique': len(unique),
        'unique_tools': unique,
        'by_category': dict(by_category),
        'interfaces': dict(interfaces)
    }


def print_analysis(analysis: Dict):
    """Gibt formatierte Analyse aus"""
    print("=" * 70)
    print("  AI-KOMPATIBLE SOFTWARE - UEBERSICHT")
    print("=" * 70)
    print()
    print(f"  Gesamt in Registry:      {analysis['total_in_registry']:,}")
    print(f"  AI-kompatibel (roh):     {analysis['ai_compatible_raw']:,}")
    print(f"  AI-kompatibel (unique):  {analysis['ai_compatible_unique']:,}")
    print()
    
    # Nach Interface
    print("-" * 70)
    print("  NACH INTERFACE")
    print("-" * 70)
    for iface, count in sorted(analysis['interfaces'].items(), key=lambda x: -x[1]):
        bar = "#" * min(int(count / 50), 30)
        print(f"  {iface:<25} {count:>5}  {bar}")
    print()
    
    # Nach Kategorie
    print("-" * 70)
    print("  NACH KATEGORIE")
    print("-" * 70)
    for cat, tools in sorted(analysis['by_category'].items(), key=lambda x: -len(x[1])):
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
    
    sorted_unique = sorted(analysis['unique_tools'], key=lambda x: x['name'].lower())
    for i, tool in enumerate(sorted_unique[:50], 1):
        auto = "+" if tool['automation'] else " "
        notes = tool['notes'][0][:25] if tool['notes'] else ""
        print(f"  {i:3}. [{auto}] {tool['name']:<25} {notes}")
    
    if len(sorted_unique) > 50:
        print(f"\n  ... und {len(sorted_unique) - 50} weitere Tools")
    
    print()
    print("=" * 70)
    print(f"  Legende: [+] = automation_ready")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='BACH AI-kompatible Software Analyse')
    parser.add_argument('--json', action='store_true', help='JSON-Ausgabe')
    parser.add_argument('--category', action='store_true', help='Nur Kategorien anzeigen')
    parser.add_argument('--list', action='store_true', help='Nur Tool-Liste')
    args = parser.parse_args()
    
    # Registry laden
    if not REGISTRY_PATH.exists():
        print(f"⚠️  Registry nicht gefunden: {REGISTRY_PATH}")
        print("   Führe zuerst 'python system_explorer.py scan' aus.")
        sys.exit(1)
    
    registry = load_registry()
    analysis = analyze_ai_compatible(registry)
    
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
