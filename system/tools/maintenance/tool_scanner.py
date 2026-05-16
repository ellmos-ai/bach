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
Tool: c_tool_scanner
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_tool_scanner

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_tool_scanner.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
tool_scanner.py - Scannt System nach verfuegbaren CLI-Tools
===========================================================

Findet installierte Tools und vergleicht mit registrierten Tools.
Nuetzlich fuer Tool-Discovery und System-Inventar.

Usage:
    python tool_scanner.py scan           # System scannen
    python tool_scanner.py --json         # JSON-Output
    python tool_scanner.py compare        # Mit Registry vergleichen

Autor: BACH v1.1 (basiert auf partner_scanner.py)
"""

import json
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

SCRIPT_DIR = Path(__file__).parent
BACH_ROOT = SCRIPT_DIR.parent
DATA_DIR = BACH_ROOT / "data"
SCAN_CACHE = DATA_DIR / "tool_scan_cache.json"

# Wichtige CLI-Tools die wir tracken
TRACKED_TOOLS = {
    # Python
    "python": "Python Interpreter",
    "python3": "Python 3 Interpreter",
    "pip": "Python Package Manager",
    "pip3": "Python 3 Package Manager",
    "conda": "Conda Package Manager",
    
    # Node/JS
    "node": "Node.js Runtime",
    "npm": "Node Package Manager",
    "yarn": "Yarn Package Manager",
    "pnpm": "PNPM Package Manager",
    
    # Version Control
    "git": "Git Version Control",
    "gh": "GitHub CLI",
    
    # Container/Cloud
    "docker": "Docker Container",
    "kubectl": "Kubernetes CLI",
    "terraform": "Terraform IaC",
    "aws": "AWS CLI",
    "az": "Azure CLI",
    "gcloud": "Google Cloud CLI",
    
    # Development
    "go": "Go Language",
    "rust": "Rust Language",
    "cargo": "Rust Package Manager",
    "make": "GNU Make",
    "cmake": "CMake Build",
    "code": "VS Code CLI",
    "vim": "Vim Editor",
    
    # Database
    "mysql": "MySQL Client",
    "psql": "PostgreSQL Client",
    "sqlite3": "SQLite CLI",
    
    # Utilities
    "curl": "cURL HTTP Client",
    "wget": "Wget Downloader",
    "ssh": "SSH Client",
    "7z": "7-Zip Archiver",
    "ffmpeg": "FFmpeg Media",
    "grep": "Grep Search",
    "jq": "JSON Processor",
    
    # AI
    "ollama": "Ollama LLM Runner",
}


def scan_tools() -> Dict:
    """Scannt System nach verfuegbaren Tools."""
    found = []
    not_found = []
    
    for tool, desc in TRACKED_TOOLS.items():
        path = shutil.which(tool)
        if path:
            found.append({
                "name": tool,
                "description": desc,
                "path": path
            })
        else:
            not_found.append(tool)
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "total_tracked": len(TRACKED_TOOLS),
        "found": len(found),
        "not_found": len(not_found),
        "tools": found,
        "missing": not_found
    }
    
    # Cache speichern
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCAN_CACHE, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    
    return result


def compare_with_registry() -> Dict:
    """Vergleicht gefundene Tools mit BACH Tool-Registry."""
    scan = scan_tools()
    
    # Versuche connections.json zu laden
    connections_file = DATA_DIR / "connections.json"
    registered = set()
    
    if connections_file.exists():
        try:
            with open(connections_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and "tools" in data:
                    registered = set(data["tools"].keys())
        except (json.JSONDecodeError, OSError):
            pass
    
    found_names = {t["name"] for t in scan["tools"]}
    
    return {
        "timestamp": scan["timestamp"],
        "found": len(found_names),
        "registered": len(registered),
        "new_tools": list(found_names - registered),
        "missing_tools": list(registered - found_names)
    }


def print_report(result: Dict):
    """Gibt formatierten Report aus."""
    print("=" * 60)
    print("TOOL SCANNER - System-Inventar")
    print("=" * 60)
    print(f"Scan:     {result['timestamp'][:19]}")
    print(f"Gefunden: {result['found']} / {result['total_tracked']}")
    print("=" * 60)
    
    print("\nGefundene Tools:")
    for tool in sorted(result["tools"], key=lambda x: x["name"]):
        print(f"  + {tool['name']:12} {tool['description']}")
    
    if result["missing"]:
        print(f"\nNicht gefunden ({len(result['missing'])}):")
        for tool in sorted(result["missing"]):
            desc = TRACKED_TOOLS.get(tool, "")
            print(f"  - {tool:12} {desc}")
    
    print(f"\nCache: {SCAN_CACHE}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="System Tool Scanner")
    parser.add_argument("command", nargs="?", default="scan",
                        choices=["scan", "compare"],
                        help="scan=Tools finden, compare=Mit Registry vergleichen")
    parser.add_argument("--json", action="store_true",
                        help="JSON-Output")
    args = parser.parse_args()
    
    if args.command == "scan":
        result = scan_tools()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_report(result)
    
    elif args.command == "compare":
        result = compare_with_registry()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 60)
            print("TOOL VERGLEICH")
            print("=" * 60)
            print(f"Gefunden:    {result['found']}")
            print(f"Registriert: {result['registered']}")
            
            if result["new_tools"]:
                print(f"\nNeue Tools (nicht registriert):")
                for t in result["new_tools"]:
                    print(f"  + {t}")
            
            if result["missing_tools"]:
                print(f"\nFehlende Tools (registriert aber nicht gefunden):")
                for t in result["missing_tools"]:
                    print(f"  - {t}")


if __name__ == "__main__":
    main()
