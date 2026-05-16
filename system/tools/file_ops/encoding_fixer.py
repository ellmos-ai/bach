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
Tool: c_encoding_fixer
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_encoding_fixer

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_encoding_fixer.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
c_encoding_fixer.py - Encoding-Probleme in Textdateien beheben

Zweck: Korrigiert Encoding-Fehler (Mojibake, falsche UTF-8 Dekodierung etc.)
       mit der ftfy-Bibliothek. Erstellt automatisch Backups.

Autor: Claude (adaptiert von EncodingFixxer.py)
Abhängigkeiten: ftfy (pip install ftfy), os, json (stdlib)

Usage:
    python c_encoding_fixer.py <file_or_folder> [--no-backup] [--recursive] [--json]
    
Beispiele:
    python c_encoding_fixer.py script.py              # Einzelne Datei
    python c_encoding_fixer.py ./src --recursive      # Ganzer Ordner
    python c_encoding_fixer.py file.py --no-backup    # Ohne Backup
    python c_encoding_fixer.py file.py --json         # JSON-Output
"""

import os
import sys
import json
from typing import Dict, Any, List, Optional

# Windows Console Encoding Fix
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

try:
    from ftfy import fix_text
except ImportError:
    print("FEHLER: ftfy nicht installiert. Bitte: pip install ftfy")
    sys.exit(1)


def fix_file_encoding(file_path: str, create_backup: bool = True) -> Dict[str, Any]:
    """
    Korrigiert Encoding-Probleme in einer Datei.
    
    Args:
        file_path: Pfad zur Datei
        create_backup: Backup erstellen (.bak)
    
    Returns:
        Dict mit Status und Details
    """
    result = {
        "file": file_path,
        "success": False,
        "backup": None,
        "changes_made": False,
        "error": None
    }
    
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        
        fixed_content = fix_text(content)
        
        # Prüfen ob Änderungen nötig
        if content == fixed_content:
            result["success"] = True
            result["changes_made"] = False
            return result
        
        # Backup erstellen
        if create_backup:
            backup_path = file_path + ".bak"
            # Falls .bak existiert, nummerieren
            counter = 1
            while os.path.exists(backup_path):
                backup_path = f"{file_path}.bak{counter}"
                counter += 1
            os.rename(file_path, backup_path)
            result["backup"] = backup_path
        
        # Korrigierten Inhalt schreiben
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(fixed_content)
        
        result["success"] = True
        result["changes_made"] = True
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def fix_folder_encoding(
    folder_path: str,
    recursive: bool = False,
    create_backup: bool = True,
    extensions: List[str] = None
) -> Dict[str, Any]:
    """
    Korrigiert Encoding in allen Dateien eines Ordners.
    
    Args:
        folder_path: Pfad zum Ordner
        recursive: Unterordner einbeziehen
        create_backup: Backups erstellen
        extensions: Dateiendungen filtern (default: .py, .txt, .md, .json)
    """
    if extensions is None:
        extensions = [".py", ".txt", ".md", ".json", ".csv", ".xml", ".html"]
    
    result = {
        "folder": folder_path,
        "files_processed": 0,
        "files_fixed": 0,
        "files_unchanged": 0,
        "errors": [],
        "details": []
    }
    
    if recursive:
        file_iterator = (
            os.path.join(root, f)
            for root, _, files in os.walk(folder_path)
            for f in files
        )
    else:
        file_iterator = (
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, f))
        )
    
    for file_path in file_iterator:
        if not any(file_path.endswith(ext) for ext in extensions):
            continue
        
        file_result = fix_file_encoding(file_path, create_backup)
        result["files_processed"] += 1
        
        if file_result["success"]:
            if file_result["changes_made"]:
                result["files_fixed"] += 1
            else:
                result["files_unchanged"] += 1
        else:
            result["errors"].append(file_result)
        
        result["details"].append(file_result)
    
    return result



def print_report(result: Dict[str, Any], verbose: bool = False) -> None:
    """Gibt lesbaren Report aus."""
    if "file" in result:
        # Einzeldatei-Ergebnis
        if result["success"]:
            if result["changes_made"]:
                print(f"✅ {result['file']} - korrigiert")
                if result["backup"]:
                    print(f"   Backup: {result['backup']}")
            else:
                print(f"⚪ {result['file']} - keine Änderungen nötig")
        else:
            print(f"❌ {result['file']} - Fehler: {result['error']}")
    else:
        # Ordner-Ergebnis
        print(f"\n{'='*60}")
        print(f"Encoding-Fix Report: {result['folder']}")
        print(f"{'='*60}")
        print(f"Verarbeitet: {result['files_processed']}")
        print(f"Korrigiert:  {result['files_fixed']}")
        print(f"Unverändert: {result['files_unchanged']}")
        print(f"Fehler:      {len(result['errors'])}")
        
        if verbose and result["details"]:
            print(f"\nDetails:")
            for detail in result["details"]:
                status = "✅" if detail["changes_made"] else "⚪" if detail["success"] else "❌"
                print(f"  {status} {os.path.basename(detail['file'])}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Korrigiert Encoding-Probleme in Textdateien mit ftfy"
    )
    parser.add_argument("path", help="Datei oder Ordner")
    parser.add_argument("--no-backup", action="store_true", help="Kein Backup erstellen")
    parser.add_argument("--recursive", "-r", action="store_true", help="Unterordner einbeziehen")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detaillierte Ausgabe")
    parser.add_argument("--json", action="store_true", help="JSON-Output")
    
    args = parser.parse_args()
    
    create_backup = not args.no_backup
    
    if os.path.isfile(args.path):
        result = fix_file_encoding(args.path, create_backup)
    elif os.path.isdir(args.path):
        result = fix_folder_encoding(args.path, args.recursive, create_backup)
    else:
        print(f"FEHLER: Pfad nicht gefunden: {args.path}")
        sys.exit(1)
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result, args.verbose)
