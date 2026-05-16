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
Tool: c_indent_checker
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_indent_checker

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_indent_checker.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
c_indent_checker.py - Python-Einrückungsprüfer

Zweck: Prüft Python-Dateien auf häufige Einrückungsfehler:
       - Fehlende Doppelpunkte nach Strukturen (def, if, class, etc.)
       - return/yield außerhalb von Blöcken
       - Mischung aus Tabs und Leerzeichen

Autor: Claude (adaptiert von indent_gui_checker.py)
Abhängigkeiten: os, re, json (stdlib)

Usage:
    python c_indent_checker.py <file_or_folder> [--recursive] [--log] [--json]
    
Beispiele:
    python c_indent_checker.py script.py          # Einzelne Datei
    python c_indent_checker.py ./src --recursive  # Ganzer Ordner
    python c_indent_checker.py ./src --log        # Log-Datei erstellen
    python c_indent_checker.py script.py --json   # JSON-Output
"""

import os
import re
import json
from typing import Dict, Any, List


def check_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Prüft eine Python-Datei auf Einrückungsfehler.
    
    Args:
        file_path: Pfad zur Python-Datei
    
    Returns:
        Liste von Fehlern mit Details
    """
    errors = []
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return [{"file": file_path, "line": 0, "type": "read_error", "message": str(e)}]
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        indent_level = len(line) - len(line.lstrip())
        
        # Check 1: Strukturen ohne Doppelpunkt
        structure_pattern = r"^(def|if|elif|else|for|while|try|except|finally|class|with|async def|async for|async with)\b"
        if re.match(structure_pattern, stripped):
            if not stripped.endswith(":") and not stripped.endswith(":\\"):
                # Mehrzeilige Definitionen ignorieren (endet mit \)
                if not stripped.endswith("\\"):
                    errors.append({
                        "file": file_path,
                        "line": i,
                        "type": "missing_colon",
                        "message": f"Struktur ohne ':' - '{stripped[:50]}...'" if len(stripped) > 50 else f"Struktur ohne ':' - '{stripped}'"
                    })
        
        # Check 2: return/yield auf Einrückungsebene 0
        if stripped.startswith(("return", "yield")) and indent_level == 0:
            errors.append({
                "file": file_path,
                "line": i,
                "type": "unindented_return",
                "message": f"'{stripped.split()[0]}' außerhalb eines Blocks"
            })
        
        # Check 3: Mischung aus Tab und Leerzeichen
        leading = line[:len(line) - len(line.lstrip())]
        if "\t" in leading and " " in leading:
            errors.append({
                "file": file_path,
                "line": i,
                "type": "mixed_indent",
                "message": "Mischung aus Tab und Leerzeichen"
            })
    
    return errors


def check_folder(folder_path: str, recursive: bool = False) -> Dict[str, Any]:
    """
    Prüft alle Python-Dateien in einem Ordner.
    
    Args:
        folder_path: Pfad zum Ordner
        recursive: Unterordner einbeziehen
    
    Returns:
        Dict mit Statistiken und Fehlern
    """
    result = {
        "folder": folder_path,
        "files_checked": 0,
        "files_with_errors": 0,
        "total_errors": 0,
        "errors": []
    }
    
    if recursive:
        file_iterator = (
            os.path.join(root, f)
            for root, _, files in os.walk(folder_path)
            for f in files if f.endswith(".py")
        )
    else:
        file_iterator = (
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.endswith(".py") and os.path.isfile(os.path.join(folder_path, f))
        )
    
    for file_path in file_iterator:
        file_errors = check_file(file_path)
        result["files_checked"] += 1
        
        if file_errors:
            result["files_with_errors"] += 1
            result["total_errors"] += len(file_errors)
            result["errors"].extend(file_errors)
    
    return result



def print_report(result: Dict[str, Any], verbose: bool = True) -> None:
    """Gibt lesbaren Report aus."""
    if isinstance(result, list):
        # Einzeldatei-Ergebnis
        if not result:
            print("✅ Keine Einrückungsfehler gefunden")
        else:
            print(f"❌ {len(result)} Fehler gefunden:\n")
            for err in result:
                print(f"  Zeile {err['line']:4}: [{err['type']}] {err['message']}")
    else:
        # Ordner-Ergebnis
        print(f"\n{'='*60}")
        print(f"Einrückungsprüfung: {result['folder']}")
        print(f"{'='*60}")
        print(f"Dateien geprüft:    {result['files_checked']}")
        print(f"Dateien mit Fehler: {result['files_with_errors']}")
        print(f"Fehler gesamt:      {result['total_errors']}")
        
        if result["errors"] and verbose:
            print(f"\nFehler-Details:")
            current_file = None
            for err in result["errors"]:
                if err["file"] != current_file:
                    current_file = err["file"]
                    print(f"\n  📄 {os.path.relpath(current_file, result['folder'])}")
                print(f"     Zeile {err['line']:4}: [{err['type']}] {err['message']}")


def save_log(result: Dict[str, Any], log_path: str) -> None:
    """Speichert Ergebnisse in Log-Datei."""
    with open(log_path, "w", encoding="utf-8") as f:
        if isinstance(result, list):
            if not result:
                f.write("✅ Keine Einrückungsfehler gefunden.\n")
            else:
                for err in result:
                    f.write(f"{err['file']} | Zeile {err['line']}: [{err['type']}] {err['message']}\n")
        else:
            f.write(f"Ordner: {result['folder']}\n")
            f.write(f"Dateien: {result['files_checked']}, Fehler: {result['total_errors']}\n\n")
            for err in result["errors"]:
                f.write(f"{err['file']} | Zeile {err['line']}: [{err['type']}] {err['message']}\n")


if __name__ == "__main__":
    import argparse
    import sys
    
    # Fix für Windows Console Encoding (Emoji-Support)
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    
    parser = argparse.ArgumentParser(
        description="Prüft Python-Dateien auf Einrückungsfehler"
    )
    parser.add_argument("path", help="Datei oder Ordner")
    parser.add_argument("--recursive", "-r", action="store_true", help="Unterordner einbeziehen")
    parser.add_argument("--log", "-l", action="store_true", help="Log-Datei erstellen")
    parser.add_argument("--quiet", "-q", action="store_true", help="Nur Zusammenfassung")
    parser.add_argument("--json", action="store_true", help="JSON-Output")
    
    args = parser.parse_args()
    
    if os.path.isfile(args.path):
        result = check_file(args.path)
    elif os.path.isdir(args.path):
        result = check_folder(args.path, args.recursive)
    else:
        print(f"FEHLER: Pfad nicht gefunden: {args.path}")
        sys.exit(1)
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result, not args.quiet)
    
    if args.log:
        log_path = "indent_check.log" if os.path.isfile(args.path) else os.path.join(args.path, "indent_check.log")
        save_log(result, log_path)
        print(f"\n📝 Log gespeichert: {log_path}")
