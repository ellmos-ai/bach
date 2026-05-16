#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
tool_discovery.py - Problem-basierte Tool-Empfehlung
=====================================================

Analysiert Problembeschreibungen und empfiehlt passende BACH-Tools.

Usage:
    python tool_discovery.py suggest "encoding problem mit umlauten"
    python tool_discovery.py list-patterns
    python tool_discovery.py --json

Autor: BACH v1.1
Version: 1.0.0
Erstellt: 2026-01-21
"""

import json
import os
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parent
DATA_DIR = SCRIPT_DIR / "data"
PATTERNS_FILE = DATA_DIR / "problem_patterns.json"


class ToolDiscovery:
    """Problem-basierte Tool-Empfehlung."""
    
    def __init__(self):
        self.patterns = self._load_patterns()
        
    def _load_patterns(self) -> Dict:
        """Laedt Problem-Patterns aus JSON."""
        if PATTERNS_FILE.exists():
            try:
                with open(PATTERNS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('patterns', {})
            except Exception as e:
                print(f"[WARN] Konnte Patterns nicht laden: {e}")
        return {}
    
    def extract_keywords(self, text: str) -> List[str]:
        """Extrahiert Keywords aus Text."""
        # Lowercase und Sonderzeichen entfernen
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Woerter extrahieren (mindestens 2 Zeichen)
        words = [w.strip() for w in text.split() if len(w.strip()) >= 2]
        
        return list(set(words))
    
    def suggest_for_problem(self, description: str) -> List[Dict]:
        """
        Empfiehlt Tools basierend auf Problembeschreibung.
        
        Returns:
            Liste von Dicts: {pattern, tools, score, description}
        """
        keywords = self.extract_keywords(description)
        results = []
        
        for pattern_name, pattern_data in self.patterns.items():
            pattern_keywords = [k.lower() for k in pattern_data.get('keywords', [])]
            
            # Score berechnen: Anzahl der gematchten Keywords
            matched = [k for k in keywords if any(pk in k or k in pk for pk in pattern_keywords)]
            score = len(matched)
            
            if score > 0:
                results.append({
                    'pattern': pattern_name,
                    'tools': pattern_data.get('tools', []),
                    'score': score,
                    'matched_keywords': matched,
                    'description': pattern_data.get('description', '')
                })
        
        # Nach Score sortieren (hoechster zuerst)
        results.sort(key=lambda x: x['score'], reverse=True)
        
        return results
    
    def list_patterns(self) -> List[Dict]:
        """Listet alle verfuegbaren Patterns."""
        result = []
        for name, data in self.patterns.items():
            result.append({
                'name': name,
                'tools': data.get('tools', []),
                'keywords': data.get('keywords', [])[:5],  # Erste 5
                'description': data.get('description', '')
            })
        return result
    
    def get_tool_for_pattern(self, pattern_name: str) -> Optional[List[str]]:
        """Holt Tools fuer ein spezifisches Pattern."""
        if pattern_name in self.patterns:
            return self.patterns[pattern_name].get('tools', [])
        return None


def format_suggestions(suggestions: List[Dict]) -> str:
    """Formatiert Vorschlaege fuer CLI-Output."""
    if not suggestions:
        return "Keine passenden Tools gefunden."
    
    lines = ["[TOOL-EMPFEHLUNGEN]", ""]
    
    for i, s in enumerate(suggestions[:5], 1):  # Top 5
        tools_str = ", ".join(s['tools'])
        lines.append(f"  {i}. {s['pattern'].upper()} (Score: {s['score']})")
        lines.append(f"     Tools: {tools_str}")
        lines.append(f"     Beschreibung: {s['description']}")
        lines.append(f"     Matched: {', '.join(s['matched_keywords'])}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    """CLI-Hauptfunktion."""
    import argparse
    
    parser = argparse.ArgumentParser(description='BACH Tool Discovery')
    parser.add_argument('command', nargs='?', default='help',
                       choices=['suggest', 'list-patterns', 'help'],
                       help='Befehl')
    parser.add_argument('description', nargs='*', help='Problembeschreibung')
    parser.add_argument('--json', action='store_true', help='JSON-Output')
    
    args = parser.parse_args()
    discovery = ToolDiscovery()
    
    if args.command == 'suggest':
        if not args.description:
            print("Fehler: Problembeschreibung erforderlich")
            print("Usage: python tool_discovery.py suggest \"mein problem\"")
            sys.exit(1)
        
        problem = " ".join(args.description)
        suggestions = discovery.suggest_for_problem(problem)
        
        if args.json:
            print(json.dumps(suggestions, indent=2, ensure_ascii=False))
        else:
            print(format_suggestions(suggestions))
    
    elif args.command == 'list-patterns':
        patterns = discovery.list_patterns()
        
        if args.json:
            print(json.dumps(patterns, indent=2, ensure_ascii=False))
        else:
            print("[VERFUEGBARE PATTERNS]")
            print("")
            for p in patterns:
                tools_str = ", ".join(p['tools'])
                keywords_str = ", ".join(p['keywords'])
                print(f"  {p['name'].upper()}")
                print(f"    Tools: {tools_str}")
                print(f"    Keywords: {keywords_str}...")
                print("")
    
    else:
        print("""
BACH Tool Discovery
===================

Befehle:
  suggest "beschreibung"  - Tools fuer Problem empfehlen
  list-patterns           - Alle verfuegbaren Patterns anzeigen

Beispiele:
  python tool_discovery.py suggest "encoding problem mit umlauten"
  python tool_discovery.py suggest "json file is broken"
  python tool_discovery.py list-patterns --json
        """)


if __name__ == '__main__':
    main()
