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
Tool: c_file_cleaner
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_file_cleaner

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_file_cleaner.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
file_cleaner.py - Dateien nach Alter/Muster bereinigen
======================================================

Findet und loescht alte Dateien oder Dateien nach Muster.
Nuetzlich fuer Backup-Ordner, Logs, temporaere Dateien.

Usage:
    python file_cleaner.py <ordner> --age 30           # Aelter als 30 Tage
    python file_cleaner.py <ordner> --pattern "*.log"  # Nach Muster
    python file_cleaner.py <ordner> --keep 5           # Behalte 5 neueste
    python file_cleaner.py <ordner> --execute          # Tatsaechlich loeschen

Autor: BACH v1.1
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass


def get_file_age_days(path: Path) -> float:
    """Gibt Alter der Datei in Tagen zurueck."""
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime).total_seconds() / 86400


def get_folder_size_mb(path: Path) -> float:
    """Berechnet Ordnergroesse in MB."""
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total / (1024 * 1024)


def find_old_files(folder: Path, max_age_days: int, 
                   pattern: str = "*", recursive: bool = False) -> List[Tuple[Path, float]]:
    """Findet Dateien aelter als max_age_days."""
    results = []
    
    if recursive:
        files = folder.rglob(pattern)
    else:
        files = folder.glob(pattern)
    
    for f in files:
        if f.is_file():
            age = get_file_age_days(f)
            if age > max_age_days:
                results.append((f, age))
    
    return sorted(results, key=lambda x: -x[1])  # Aelteste zuerst


def find_excess_files(folder: Path, keep_count: int, 
                      pattern: str = "*") -> List[Tuple[Path, float]]:
    """Findet Dateien die ueber keep_count hinausgehen (aelteste)."""
    files = []
    
    for f in folder.glob(pattern):
        if f.is_file():
            mtime = f.stat().st_mtime
            files.append((f, mtime))
    
    # Nach Datum sortieren (neueste zuerst)
    files.sort(key=lambda x: -x[1])
    
    # Ueberschuessige zurueckgeben
    if len(files) <= keep_count:
        return []
    
    excess = files[keep_count:]
    return [(f, get_file_age_days(f)) for f, _ in excess]


def find_by_pattern(folder: Path, pattern: str, 
                    recursive: bool = False) -> List[Tuple[Path, float]]:
    """Findet Dateien nach Muster."""
    results = []
    
    if recursive:
        files = folder.rglob(pattern)
    else:
        files = folder.glob(pattern)
    
    for f in files:
        if f.is_file():
            results.append((f, get_file_age_days(f)))
    
    return sorted(results, key=lambda x: x[0].name)


def delete_files(files: List[Tuple[Path, float]], dry_run: bool = True) -> int:
    """Loescht Dateien. Gibt Anzahl geloeschter zurueck."""
    count = 0
    for f, age in files:
        if dry_run:
            print(f"  [DRY] {f.name} ({age:.1f} Tage)")
        else:
            try:
                f.unlink()
                print(f"  [DEL] {f.name}")
                count += 1
            except Exception as e:
                print(f"  [ERR] {f.name}: {e}")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Dateien nach Alter/Muster bereinigen"
    )
    parser.add_argument("folder", help="Ordner zum Bereinigen")
    parser.add_argument("--age", type=int, 
                        help="Max Alter in Tagen")
    parser.add_argument("--keep", type=int,
                        help="Anzahl neueste behalten")
    parser.add_argument("--pattern", default="*",
                        help="Datei-Pattern (default: *)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Rekursiv suchen")
    parser.add_argument("--execute", action="store_true",
                        help="Tatsaechlich loeschen (default: dry-run)")
    parser.add_argument("--dirs", action="store_true",
                        help="Auch Ordner einbeziehen (nur bei --age)")
    
    args = parser.parse_args()
    
    folder = Path(args.folder)
    if not folder.exists():
        print(f"Fehler: Ordner existiert nicht: {folder}")
        sys.exit(1)
    
    dry_run = not args.execute
    
    print("=" * 60)
    print("FILE CLEANER")
    print("=" * 60)
    print(f"Ordner:    {folder}")
    print(f"Pattern:   {args.pattern}")
    print(f"Rekursiv:  {args.recursive}")
    print(f"Dry-Run:   {dry_run}")
    print("=" * 60)
    
    files_to_delete = []
    
    if args.age:
        print(f"\nSuche Dateien aelter als {args.age} Tage...")
        files_to_delete = find_old_files(folder, args.age, args.pattern, args.recursive)
    elif args.keep:
        print(f"\nBehalte {args.keep} neueste, loesche Rest...")
        files_to_delete = find_excess_files(folder, args.keep, args.pattern)
    else:
        print(f"\nSuche Dateien mit Pattern '{args.pattern}'...")
        files_to_delete = find_by_pattern(folder, args.pattern, args.recursive)
    
    if not files_to_delete:
        print("\nKeine Dateien gefunden.")
        return
    
    total_size = sum(f.stat().st_size for f, _ in files_to_delete if f.exists()) / (1024*1024)
    
    print(f"\nGefunden: {len(files_to_delete)} Dateien ({total_size:.2f} MB)")
    print()
    
    deleted = delete_files(files_to_delete, dry_run)
    
    if dry_run:
        print(f"\n[DRY-RUN] {len(files_to_delete)} Dateien wuerden geloescht.")
        print("Nutze --execute um tatsaechlich zu loeschen.")
    else:
        print(f"\n{deleted} Dateien geloescht.")


if __name__ == "__main__":
    main()
