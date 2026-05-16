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
Tool: c_pattern_tool
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_pattern_tool

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_pattern_tool.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
pattern_tool.py - Dateinamen kuerzen durch Pattern-Erkennung
============================================================

Kombiniert pattern_renamer.py und pattern_trimmer.py in einem Tool.

Funktionen:
- PREFIX: Gemeinsame Prefixe bei Gruppen entfernen
- SUFFIX: Gemeinsame Suffixe bei Gruppen entfernen
- BOTH: Prefix und Suffix kombiniert

Usage:
    python pattern_tool.py <ordner> --dry-run
    python pattern_tool.py <ordner> --execute
    python pattern_tool.py <ordner> --prefix-only
    python pattern_tool.py <ordner> --suffix-only
    python pattern_tool.py <ordner> -m 5  # Min 5 Zeichen Pattern

Autor: BACH v1.1
"""

import sys
import argparse
from pathlib import Path
from collections import defaultdict

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass


def find_prefix_patterns(names: list, min_len: int = 3) -> dict:
    """Findet gemeinsame Prefixe."""
    prefix_groups = defaultdict(list)
    
    for i, name1 in enumerate(names):
        for j, name2 in enumerate(names):
            if i >= j:
                continue
            
            prefix = ""
            for c1, c2 in zip(name1, name2):
                if c1 == c2:
                    prefix += c1
                else:
                    break
            
            if len(prefix) >= min_len:
                for k, name in enumerate(names):
                    if name.startswith(prefix):
                        if k not in prefix_groups[prefix]:
                            prefix_groups[prefix].append(k)
    
    return {p: idx for p, idx in prefix_groups.items() if len(idx) >= 2}


def find_suffix_patterns(names: list, min_len: int = 3) -> dict:
    """Findet gemeinsame Suffixe (vor Extension)."""
    suffix_groups = defaultdict(list)
    
    for i, name1 in enumerate(names):
        for j, name2 in enumerate(names):
            if i >= j:
                continue
            
            # Reversed vergleichen
            suffix = ""
            for c1, c2 in zip(reversed(name1), reversed(name2)):
                if c1 == c2:
                    suffix = c1 + suffix
                else:
                    break
            
            if len(suffix) >= min_len:
                for k, name in enumerate(names):
                    if name.endswith(suffix):
                        if k not in suffix_groups[suffix]:
                            suffix_groups[suffix].append(k)
    
    return {s: idx for s, idx in suffix_groups.items() if len(idx) >= 2}


def trim_prefix(files: list, pattern: str, dry_run: bool = True) -> list:
    """Entfernt Prefix von Dateien."""
    results = []
    for f in files:
        if f.stem.startswith(pattern):
            new_stem = f.stem[len(pattern):]
            if new_stem:  # Nicht auf 0 kuerzen
                new_name = new_stem + f.suffix
                results.append((f, f.parent / new_name))
    return results


def trim_suffix(files: list, pattern: str, dry_run: bool = True) -> list:
    """Entfernt Suffix von Dateien (vor Extension)."""
    results = []
    for f in files:
        if f.stem.endswith(pattern):
            new_stem = f.stem[:-len(pattern)]
            if new_stem:  # Nicht auf 0 kuerzen
                new_name = new_stem + f.suffix
                results.append((f, f.parent / new_name))
    return results


def scan_folder(folder: Path, mode: str = "both", min_pattern: int = 3, 
                dry_run: bool = True, recursive: bool = False) -> dict:
    """Scannt Ordner und findet Patterns."""
    
    if recursive:
        files = list(folder.rglob("*"))
    else:
        files = list(folder.iterdir())
    
    files = [f for f in files if f.is_file()]
    
    if not files:
        return {"error": "Keine Dateien gefunden"}
    
    names = [f.stem for f in files]
    results = {
        "folder": str(folder),
        "files_scanned": len(files),
        "prefix_patterns": {},
        "suffix_patterns": {},
        "renames": []
    }
    
    # Prefix-Patterns
    if mode in ["prefix", "both"]:
        prefix_patterns = find_prefix_patterns(names, min_pattern)
        results["prefix_patterns"] = {p: len(idx) for p, idx in prefix_patterns.items()}
        
        # Laengstes Pattern zuerst
        if prefix_patterns:
            longest = max(prefix_patterns.keys(), key=len)
            affected_files = [files[i] for i in prefix_patterns[longest]]
            renames = trim_prefix(affected_files, longest, dry_run)
            results["renames"].extend(renames)
    
    # Suffix-Patterns
    if mode in ["suffix", "both"]:
        suffix_patterns = find_suffix_patterns(names, min_pattern)
        results["suffix_patterns"] = {s: len(idx) for s, idx in suffix_patterns.items()}
        
        if suffix_patterns:
            longest = max(suffix_patterns.keys(), key=len)
            affected_files = [files[i] for i in suffix_patterns[longest]]
            renames = trim_suffix(affected_files, longest, dry_run)
            results["renames"].extend(renames)
    
    return results


def execute_renames(renames: list) -> int:
    """Fuehrt Umbenennungen durch."""
    count = 0
    for old_path, new_path in renames:
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
            print(f"  {old_path.name} -> {new_path.name}")
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Dateinamen kuerzen durch Pattern-Erkennung"
    )
    parser.add_argument("folder", help="Ordner zum Scannen")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Nur anzeigen, nicht umbenennen (default)")
    parser.add_argument("--execute", action="store_true",
                        help="Umbenennungen durchfuehren")
    parser.add_argument("--prefix-only", action="store_true",
                        help="Nur Prefix-Patterns")
    parser.add_argument("--suffix-only", action="store_true",
                        help="Nur Suffix-Patterns")
    parser.add_argument("-m", "--min-pattern", type=int, default=3,
                        help="Minimale Pattern-Laenge (default: 3)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Rekursiv scannen")
    
    args = parser.parse_args()
    
    folder = Path(args.folder)
    if not folder.exists():
        print(f"Fehler: Ordner existiert nicht: {folder}")
        sys.exit(1)
    
    # Modus bestimmen
    mode = "both"
    if args.prefix_only:
        mode = "prefix"
    elif args.suffix_only:
        mode = "suffix"
    
    dry_run = not args.execute
    
    print("=" * 60)
    print("PATTERN TOOL")
    print("=" * 60)
    print(f"Ordner:      {folder}")
    print(f"Modus:       {mode}")
    print(f"Min-Pattern: {args.min_pattern}")
    print(f"Dry-Run:     {dry_run}")
    print("=" * 60)
    
    results = scan_folder(folder, mode, args.min_pattern, dry_run, args.recursive)
    
    if "error" in results:
        print(f"\nFehler: {results['error']}")
        sys.exit(1)
    
    print(f"\nDateien gescannt: {results['files_scanned']}")
    
    if results["prefix_patterns"]:
        print(f"\nPrefix-Patterns gefunden:")
        for p, count in sorted(results["prefix_patterns"].items(), key=lambda x: -len(x[0])):
            print(f"  '{p}' ({count} Dateien)")
    
    if results["suffix_patterns"]:
        print(f"\nSuffix-Patterns gefunden:")
        for s, count in sorted(results["suffix_patterns"].items(), key=lambda x: -len(x[0])):
            print(f"  '{s}' ({count} Dateien)")
    
    if results["renames"]:
        print(f"\nUmbenennungen ({len(results['renames'])}):")
        for old, new in results["renames"]:
            print(f"  {old.name} -> {new.name}")
        
        if args.execute:
            print("\nFuehre Umbenennungen durch...")
            count = execute_renames(results["renames"])
            print(f"\n{count} Dateien umbenannt.")
        else:
            print("\n[DRY-RUN] Nutze --execute um durchzufuehren")
    else:
        print("\nKeine Umbenennungen vorgeschlagen.")


if __name__ == "__main__":
    main()
