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
Tool: c_license_generator
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_license_generator

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_license_generator.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
c_license_generator.py - Drittanbieter-Lizenzen Generator

Zweck: Generiert THIRD_PARTY_LICENSES.txt mit allen installierten
       pip-Paket-Lizenzen. Nutzt pip-licenses (wird bei Bedarf installiert).

Autor: Claude (adaptiert von generate_third_party_licenses.py)
Abhängigkeiten: subprocess, os, json (stdlib) + pip-licenses (wird auto-installiert)

Usage:
    python c_license_generator.py [--output <file>] [--format plain|json|csv] [--json]
    
Beispiele:
    python c_license_generator.py                           # Standard: THIRD_PARTY_LICENSES.txt
    python c_license_generator.py --output licenses.txt     # Eigener Dateiname
    python c_license_generator.py --format json             # JSON-Format
    python c_license_generator.py --json                    # Maschinenlesbarer Output
"""

import os
import subprocess
import sys
import json
from typing import Dict, Any, Optional


def ensure_pip_licenses() -> bool:
    """Stellt sicher, dass pip-licenses installiert ist."""
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pip-licenses", "-q"],
            check=True,
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def generate_licenses(
    output_file: Optional[str] = None,
    format_type: str = "plain"
) -> Dict[str, Any]:
    """
    Generiert Lizenzdatei für alle installierten pip-Pakete.
    
    Args:
        output_file: Ausgabedatei (default: THIRD_PARTY_LICENSES.txt)
        format_type: plain, json, oder csv
    
    Returns:
        Dict mit Status und Details
    """
    if output_file is None:
        ext = ".json" if format_type == "json" else ".csv" if format_type == "csv" else ".txt"
        output_file = f"THIRD_PARTY_LICENSES{ext}"
    
    result = {
        "success": False,
        "output_file": output_file,
        "format": format_type,
        "package_count": 0,
        "error": None
    }
    
    # pip-licenses installieren falls nötig
    if not ensure_pip_licenses():
        result["error"] = "pip-licenses konnte nicht installiert werden"
        return result
    
    try:
        # Format-spezifische Argumente
        cmd = [sys.executable, "-m", "piplicenses", "--with-license-file"]
        
        if format_type == "json":
            cmd.append("--format=json")
        elif format_type == "csv":
            cmd.append("--format=csv")
        else:
            cmd.append("--format=plain")
        
        # Lizenzen generieren
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(proc.stdout)
        
        # Pakete zählen
        if format_type == "json":
            packages = json.loads(proc.stdout)
            result["package_count"] = len(packages)
        else:
            result["package_count"] = proc.stdout.count("\n") - 1
        
        result["success"] = True
        
    except subprocess.CalledProcessError as e:
        result["error"] = f"pip-licenses Fehler: {e.stderr}"
    except Exception as e:
        result["error"] = str(e)
    
    return result


def print_report(result: Dict[str, Any]) -> None:
    """Gibt lesbaren Report aus."""
    if result["success"]:
        print(f"✅ Lizenzdatei erstellt: {result['output_file']}")
        print(f"   Format: {result['format']}")
        print(f"   Pakete: {result['package_count']}")
    else:
        print(f"❌ Fehler: {result['error']}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generiert Drittanbieter-Lizenzdatei für pip-Pakete"
    )
    parser.add_argument("--output", "-o", help="Ausgabedatei")
    parser.add_argument("--format", "-f", choices=["plain", "json", "csv"], 
                        default="plain", help="Ausgabeformat")
    parser.add_argument("--json", action="store_true", help="JSON-Output für Scripting")
    
    args = parser.parse_args()
    
    result = generate_licenses(args.output, args.format)
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)
