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
Tool: c_standard_fixer
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_standard_fixer

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_standard_fixer.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# coding: utf-8
"""
c_standard_fixer.py - Toolchain fuer haeufige Code-Probleme

Fuehrt mehrere Fixer nacheinander aus:
  1. BOM-Fix (entfernt/korrigiert Byte Order Mark)
  2. Encoding-Fix (utf-8 sicherstellen)
  3. Umlaut-Fix (kaputte deutsche Umlaute reparieren)
  4. Indent-Check (Einrueckungsprobleme erkennen)

Usage:
    python c_standard_fixer.py <datei.py>
    python c_standard_fixer.py <datei.py> --dry-run
    python c_standard_fixer.py <ordner> --recursive
    python c_standard_fixer.py <datei.py> --only bom,umlaut
    python c_standard_fixer.py --list-tools

Konfiguration:
    Die aktiven Tools koennen in STANDARD_FIXER_CONFIG angepasst werden.

Autor: Claude
Version: 1.0
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

# Windows Console Encoding Fix
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# ============================================================================
# KONFIGURATION - Hier Tools aktivieren/deaktivieren
# ============================================================================

STANDARD_FIXER_CONFIG = {
    "tools": [
        {
            "name": "bom_fix",
            "description": "Entfernt/korrigiert BOM (Byte Order Mark)",
            "enabled": True,
            "order": 1
        },
        {
            "name": "encoding_fix",
            "description": "Stellt UTF-8 Encoding sicher",
            "enabled": True,
            "order": 2
        },
        {
            "name": "json_repair",
            "description": "Repariert JSON (Newlines, Mojibake)",
            "enabled": True,
            "order": 3,
            "file_types": [".json"]
        },
        {
            "name": "umlaut_fix",
            "description": "Repariert kaputte deutsche Umlaute",
            "enabled": True,
            "order": 4
        },
        {
            "name": "indent_check",
            "description": "Prueft Einrueckung (nur Diagnose, kein Fix)",
            "enabled": True,
            "order": 5
        }
    ],
    "backup": True,
    "file_extensions": [".py", ".md", ".txt", ".json"],
    "ignore_patterns": ["__pycache__", ".git", "venv", "node_modules", ".bak"]
}

# Pfad zu den DEV_TOOLS (relativ vom neuen Standort _maintain_and_cleanup)
DEV_TOOLS_DIR = Path(__file__).parent.parent / "DEV_TOOLS"


# ============================================================================
# FIXER FUNKTIONEN
# ============================================================================

def fix_bom(filepath: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Entfernt BOM aus Datei und repariert PowerShell-Artefakte."""
    result = {"tool": "bom_fix", "file": str(filepath), "success": True, "changes": [], "errors": []}
    
    try:
        # Mit utf-8-sig lesen (erkennt BOM automatisch)
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        
        # Pruefen ob BOM vorhanden war
        with open(filepath, 'rb') as f:
            raw_start = f.read(3)
        
        has_bom = raw_start == b'\xef\xbb\xbf'
        
        # PowerShell-Artefakte reparieren (`n statt \n)
        has_ps_artifacts = '`n' in content
        if has_ps_artifacts:
            content = content.replace('`n', '\n')
            result["changes"].append("PowerShell-Newline-Artefakte (`n) repariert")
        
        if has_bom:
            result["changes"].append("BOM entfernt")
        
        if (has_bom or has_ps_artifacts) and not dry_run:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        
    except Exception as e:
        result["success"] = False
        result["errors"].append(str(e))
    
    return result


def fix_encoding(filepath: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Stellt UTF-8 Encoding sicher."""
    result = {"tool": "encoding_fix", "file": str(filepath), "success": True, "changes": [], "errors": []}
    
    try:
        # Versuche verschiedene Encodings
        content = None
        original_encoding = None
        
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    content = f.read()
                original_encoding = encoding
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            result["errors"].append("Konnte Datei mit keinem Encoding lesen")
            result["success"] = False
            return result
        
        if original_encoding not in ['utf-8', 'utf-8-sig']:
            result["changes"].append(f"Encoding konvertiert: {original_encoding} -> utf-8")
            if not dry_run:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
        
    except Exception as e:
        result["success"] = False
        result["errors"].append(str(e))
    
    return result


def fix_umlauts(filepath: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Repariert kaputte Umlaute via c_umlaut_fixer.py."""
    result = {"tool": "umlaut_fix", "file": str(filepath), "success": True, "changes": [], "errors": []}
    
    umlaut_fixer = DEV_TOOLS_DIR / "c_umlaut_fixer.py"
    
    if not umlaut_fixer.exists():
        result["errors"].append("c_umlaut_fixer.py nicht gefunden")
        result["success"] = False
        return result
    
    try:
        args = ["python", str(umlaut_fixer), str(filepath), "--json"]
        if dry_run:
            args.append("--dry-run")
        
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
        
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                umlaut_result = json.loads(proc.stdout)
                if umlaut_result.get("issues_found", 0) > 0:
                    for change in umlaut_result.get("changes", [])[:5]:
                        result["changes"].append(f"{change['original']} -> {change['fixed']}")
                    if umlaut_result["issues_found"] > 5:
                        result["changes"].append(f"... und {umlaut_result['issues_found'] - 5} weitere")
            except json.JSONDecodeError:
                pass
        
    except Exception as e:
        result["success"] = False
        result["errors"].append(str(e))
    
    return result


def check_indent(filepath: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Prueft Einrueckung via c_indent_checker.py (nur Diagnose)."""
    result = {"tool": "indent_check", "file": str(filepath), "success": True, "changes": [], "errors": [], "warnings": []}
    
    indent_checker = DEV_TOOLS_DIR / "c_indent_checker.py"
    
    if not indent_checker.exists():
        result["errors"].append("c_indent_checker.py nicht gefunden")
        result["success"] = False
        return result
    
    try:
        proc = subprocess.run(
            ["python", str(indent_checker), str(filepath)],
            capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace'
        )
        
        # Ausgabe parsen
        output = proc.stdout + proc.stderr
        if "Fehler gefunden" in output:
            # Extrahiere Fehleranzahl
            lines = output.strip().split('\n')
            for line in lines:
                if "Zeile" in line and "[" in line:
                    result["warnings"].append(line.strip())
        
    except Exception as e:
        result["success"] = False
        result["errors"].append(str(e))
    
    return result


def repair_json(filepath: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Repariert JSON-Dateien (Newlines in Strings, Mojibake)."""
    result = {"tool": "json_repair", "file": str(filepath), "success": True, "changes": [], "errors": []}
    
    # Nur fuer JSON-Dateien
    if filepath.suffix.lower() != '.json':
        return result
    
    json_repair_script = Path(__file__).parent / "c_json_repair.py"
    
    if not json_repair_script.exists():
        result["errors"].append("c_json_repair.py nicht gefunden")
        result["success"] = False
        return result
    
    try:
        args = ["python", str(json_repair_script), str(filepath), "--json"]
        if dry_run:
            args.append("--dry-run")
        
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
        
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                json_result = json.loads(proc.stdout)
                fixes = json_result.get("fixes_applied", [])
                if fixes:
                    for fix in fixes:
                        if fix != "reformatted":  # reformatted ist intern
                            result["changes"].append(f"JSON: {fix}")
            except json.JSONDecodeError:
                pass
        elif proc.returncode != 0:
            result["errors"].append(proc.stderr.strip() if proc.stderr else "JSON repair failed")
        
    except Exception as e:
        result["success"] = False
        result["errors"].append(str(e))
    
    return result


# ============================================================================
# HAUPTLOGIK
# ============================================================================

FIXER_MAP = {
    "bom_fix": fix_bom,
    "encoding_fix": fix_encoding,
    "json_repair": repair_json,
    "umlaut_fix": fix_umlauts,
    "indent_check": check_indent
}


def get_enabled_tools() -> List[Dict]:
    """Gibt aktivierte Tools sortiert nach Reihenfolge zurueck."""
    tools = [t for t in STANDARD_FIXER_CONFIG["tools"] if t["enabled"]]
    return sorted(tools, key=lambda x: x["order"])


def should_process_file(filepath: Path) -> bool:
    """Prueft ob Datei verarbeitet werden soll."""
    # Extension pruefen
    if filepath.suffix.lower() not in STANDARD_FIXER_CONFIG["file_extensions"]:
        return False
    
    # Ignore patterns pruefen
    path_str = str(filepath)
    for pattern in STANDARD_FIXER_CONFIG["ignore_patterns"]:
        if pattern in path_str:
            return False
    
    return True


def process_file(filepath: Path, dry_run: bool = False, only_tools: Optional[List[str]] = None) -> Dict[str, Any]:
    """Verarbeitet eine einzelne Datei mit allen aktivierten Tools."""
    results = {
        "file": str(filepath),
        "tools_run": [],
        "total_changes": 0,
        "total_warnings": 0,
        "total_errors": 0,
        "success": True
    }
    
    # Backup erstellen (einmalig vor allen Fixes)
    if STANDARD_FIXER_CONFIG["backup"] and not dry_run:
        backup_path = filepath.with_suffix(filepath.suffix + '.standardfixer.bak')
        try:
            with open(filepath, 'rb') as src:
                with open(backup_path, 'wb') as dst:
                    dst.write(src.read())
        except Exception as e:
            results["backup_error"] = str(e)
    
    # Tools ausfuehren
    for tool_config in get_enabled_tools():
        tool_name = tool_config["name"]
        
        # Filter: nur bestimmte Tools?
        if only_tools and tool_name not in only_tools:
            continue
        
        if tool_name in FIXER_MAP:
            tool_result = FIXER_MAP[tool_name](filepath, dry_run)
            results["tools_run"].append(tool_result)
            
            results["total_changes"] += len(tool_result.get("changes", []))
            results["total_warnings"] += len(tool_result.get("warnings", []))
            results["total_errors"] += len(tool_result.get("errors", []))
            
            if not tool_result["success"]:
                results["success"] = False
    
    return results


def process_directory(dirpath: Path, dry_run: bool = False, only_tools: Optional[List[str]] = None) -> List[Dict]:
    """Verarbeitet alle passenden Dateien in einem Verzeichnis rekursiv."""
    all_results = []
    
    for filepath in dirpath.rglob("*"):
        if filepath.is_file() and should_process_file(filepath):
            result = process_file(filepath, dry_run, only_tools)
            all_results.append(result)
    
    return all_results


def print_results(results: List[Dict], verbose: bool = False):
    """Gibt Ergebnisse formatiert aus."""
    total_files = len(results)
    total_changes = sum(r["total_changes"] for r in results)
    total_warnings = sum(r["total_warnings"] for r in results)
    total_errors = sum(r["total_errors"] for r in results)
    
    print("\n" + "=" * 60)
    print("STANDARD-FIXER ERGEBNIS")
    print("=" * 60)
    print(f"Dateien verarbeitet: {total_files}")
    print(f"Aenderungen:         {total_changes}")
    print(f"Warnungen:           {total_warnings}")
    print(f"Fehler:              {total_errors}")
    print("=" * 60)
    
    # Details pro Datei (wenn Aenderungen/Fehler)
    for result in results:
        if result["total_changes"] > 0 or result["total_errors"] > 0 or verbose:
            print(f"\n[{'OK' if result['success'] else 'FEHLER'}] {result['file']}")
            
            for tool_result in result["tools_run"]:
                if tool_result.get("changes") or tool_result.get("errors") or tool_result.get("warnings"):
                    print(f"  {tool_result['tool']}:")
                    for change in tool_result.get("changes", []):
                        print(f"    + {change}")
                    for warning in tool_result.get("warnings", []):
                        print(f"    ! {warning}")
                    for error in tool_result.get("errors", []):
                        print(f"    X {error}")


def list_tools():
    """Listet alle verfuegbaren Tools auf."""
    print("\nVerfuegbare Tools:")
    print("-" * 50)
    for tool in STANDARD_FIXER_CONFIG["tools"]:
        status = "[X]" if tool["enabled"] else "[ ]"
        print(f"  {status} {tool['name']:15} - {tool['description']}")
    print("-" * 50)
    print(f"\nDatei-Extensions: {', '.join(STANDARD_FIXER_CONFIG['file_extensions'])}")
    print(f"Backup aktiviert: {STANDARD_FIXER_CONFIG['backup']}")


def main():
    # Windows Console Encoding Fix
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    if len(sys.argv) < 2 or '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        sys.exit(0)
    
    if '--list-tools' in sys.argv:
        list_tools()
        sys.exit(0)
    
    target = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    recursive = '--recursive' in sys.argv
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    
    # --only Filter parsen
    only_tools = None
    for arg in sys.argv:
        if arg.startswith('--only='):
            only_tools = arg.split('=')[1].split(',')
    
    path = Path(target)
    
    if not path.exists():
        print(f"[FEHLER] Pfad nicht gefunden: {target}")
        sys.exit(1)
    
    if dry_run:
        print("[DRY-RUN] Keine Aenderungen werden vorgenommen.\n")
    
    if path.is_file():
        results = [process_file(path, dry_run, only_tools)]
    elif path.is_dir():
        if recursive:
            results = process_directory(path, dry_run, only_tools)
        else:
            # Nur direkte Dateien im Ordner
            results = []
            for f in path.iterdir():
                if f.is_file() and should_process_file(f):
                    results.append(process_file(f, dry_run, only_tools))
    else:
        print(f"[FEHLER] Unbekannter Pfadtyp: {target}")
        sys.exit(1)
    
    print_results(results, verbose)
    
    # Exit-Code basierend auf Fehlern
    has_errors = any(r["total_errors"] > 0 for r in results)
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
