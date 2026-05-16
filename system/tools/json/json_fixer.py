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
Tool: c_json_fixer
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_json_fixer

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_json_fixer.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
json_fixer.py - JSON-Dateien reparieren
=======================================

Repariert kaputte JSON-Dateien:
- BOM entfernen
- Trailing Commas
- Einzel-Quotes
- Unescaped Strings

Usage:
    python json_fixer.py <datei>           # Einzelne Datei
    python json_fixer.py <ordner>          # Alle JSON im Ordner
    python json_fixer.py <path> --dry-run  # Nur pruefen
    python json_fixer.py <path> --backup   # Mit Backup

Autor: BACH v1.1
"""

import sys
import json
import re
import shutil
import argparse
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass


def remove_bom(content: str) -> str:
    """Entfernt UTF-8 BOM."""
    if content.startswith('\ufeff'):
        return content[1:]
    return content


def fix_trailing_commas(content: str) -> str:
    """Entfernt trailing commas vor } oder ]."""
    # Trailing comma vor }
    content = re.sub(r',(\s*})', r'\1', content)
    # Trailing comma vor ]
    content = re.sub(r',(\s*\])', r'\1', content)
    return content


def fix_single_quotes(content: str) -> str:
    """Ersetzt Single-Quotes durch Double-Quotes (vorsichtig)."""
    # Nur wenn es wie JSON aussieht
    if "'" in content and '"' not in content:
        content = content.replace("'", '"')
    return content


def fix_newlines(content: str) -> str:
    """Entfernt problematische Newlines in Strings."""
    # PowerShell `n Artefakte
    content = content.replace('`n', ' ')
    return content


def try_parse_json(content: str) -> tuple:
    """Versucht JSON zu parsen. Gibt (success, data/error) zurueck."""
    try:
        data = json.loads(content)
        return True, data
    except json.JSONDecodeError as e:
        return False, str(e)


def fix_json_content(content: str) -> tuple:
    """Wendet alle Fixes an. Gibt (fixed_content, fixes_applied) zurueck."""
    original = content
    fixes = []
    
    # 1. BOM entfernen
    content = remove_bom(content)
    if content != original:
        fixes.append("BOM entfernt")
        original = content
    
    # 2. Trailing Commas
    content = fix_trailing_commas(content)
    if content != original:
        fixes.append("Trailing Commas entfernt")
        original = content
    
    # 3. Single Quotes
    content = fix_single_quotes(content)
    if content != original:
        fixes.append("Single-Quotes ersetzt")
        original = content
    
    # 4. Newlines
    content = fix_newlines(content)
    if content != original:
        fixes.append("Newlines bereinigt")
    
    return content, fixes


def fix_json_file(file_path: Path, dry_run: bool = True, 
                  create_backup: bool = False) -> dict:
    """Repariert eine JSON-Datei."""
    result = {
        "file": str(file_path),
        "status": "unknown",
        "fixes": [],
        "error": None
    }
    
    try:
        # Datei lesen (mit utf-8-sig fuer BOM-Toleranz)
        content = file_path.read_text(encoding='utf-8-sig')
        
        # Erst pruefen ob bereits valide
        success, data = try_parse_json(content)
        if success:
            result["status"] = "valid"
            return result
        
        # Fixes anwenden
        fixed_content, fixes = fix_json_content(content)
        result["fixes"] = fixes
        
        # Erneut pruefen
        success, data = try_parse_json(fixed_content)
        if not success:
            result["status"] = "unfixable"
            result["error"] = data
            return result
        
        # Speichern
        if not dry_run:
            if create_backup:
                backup_path = file_path.with_suffix(f".json.bak")
                shutil.copy2(file_path, backup_path)
            
            # Sauber speichern
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
        
        result["status"] = "fixed"
        return result
        
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result


def process_path(path: Path, dry_run: bool, backup: bool) -> list:
    """Verarbeitet Datei oder Ordner."""
    results = []
    
    if path.is_file():
        if path.suffix.lower() == '.json':
            results.append(fix_json_file(path, dry_run, backup))
    elif path.is_dir():
        for json_file in path.glob("**/*.json"):
            results.append(fix_json_file(json_file, dry_run, backup))
    
    return results


def print_results(results: list, dry_run: bool):
    """Gibt Ergebnisse aus."""
    valid = [r for r in results if r["status"] == "valid"]
    fixed = [r for r in results if r["status"] == "fixed"]
    unfixable = [r for r in results if r["status"] == "unfixable"]
    errors = [r for r in results if r["status"] == "error"]
    
    print(f"\nErgebnisse:")
    print(f"  Bereits valide: {len(valid)}")
    print(f"  Repariert:      {len(fixed)}")
    print(f"  Nicht reparierbar: {len(unfixable)}")
    print(f"  Fehler:         {len(errors)}")
    
    if fixed:
        print(f"\nReparierte Dateien:")
        for r in fixed:
            name = Path(r["file"]).name
            fixes = ", ".join(r["fixes"])
            prefix = "[DRY]" if dry_run else "[FIX]"
            print(f"  {prefix} {name}: {fixes}")
    
    if unfixable:
        print(f"\nNicht reparierbar:")
        for r in unfixable:
            name = Path(r["file"]).name
            print(f"  [ERR] {name}: {r['error'][:50]}...")


def main():
    parser = argparse.ArgumentParser(
        description="JSON-Dateien reparieren"
    )
    parser.add_argument("path", help="Datei oder Ordner")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Nur pruefen (default)")
    parser.add_argument("--execute", action="store_true",
                        help="Tatsaechlich reparieren")
    parser.add_argument("--backup", action="store_true",
                        help="Backup vor Aenderung erstellen")
    
    args = parser.parse_args()
    
    path = Path(args.path)
    if not path.exists():
        print(f"Fehler: Pfad existiert nicht: {path}")
        sys.exit(1)
    
    dry_run = not args.execute
    
    print("=" * 60)
    print("JSON FIXER")
    print("=" * 60)
    print(f"Pfad:    {path}")
    print(f"Dry-Run: {dry_run}")
    print(f"Backup:  {args.backup}")
    print("=" * 60)
    
    results = process_path(path, dry_run, args.backup)
    
    if not results:
        print("\nKeine JSON-Dateien gefunden.")
        return
    
    print_results(results, dry_run)
    
    if dry_run and any(r["status"] == "fixed" for r in results):
        print("\n[DRY-RUN] Nutze --execute um zu reparieren.")


if __name__ == "__main__":
    main()
