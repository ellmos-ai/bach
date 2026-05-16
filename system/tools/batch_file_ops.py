#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: batch_file_ops
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version batch_file_ops

Description:
    [Beschreibung hinzufügen]

Usage:
    python batch_file_ops.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
batch_file_ops.py - Batch-Dateioperationen

Sammelt und löscht/verschiebt/kopiert Dateien nach Pattern.

Usage:
    python batch_file_ops.py delete <ordner> --pattern "*.py"
    python batch_file_ops.py delete <ordner> --pattern "TOOLS_*.py"
    python batch_file_ops.py move <quelle> <ziel> --pattern "*.txt"
    python batch_file_ops.py copy <quelle> <ziel> --pattern "*.md"
    python batch_file_ops.py list <ordner> --pattern "*"
    python batch_file_ops.py delete <ordner> --pattern "*.py" --dry-run

Autor: Claude
"""

import argparse
import sys
import io
from pathlib import Path
import shutil

# Windows Console UTF-8 Fix
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass


def list_files(directory: Path, pattern: str, recursive: bool = False) -> list:
    """Listet Dateien nach Pattern"""
    if recursive:
        return list(directory.rglob(pattern))
    return list(directory.glob(pattern))


def delete_files(directory: Path, pattern: str, dry_run: bool = False, recursive: bool = False):
    """Löscht Dateien nach Pattern"""
    files = list_files(directory, pattern, recursive)
    
    if not files:
        print(f"Keine Dateien gefunden: {pattern}")
        return 0
    
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Lösche {len(files)} Dateien:")
    print("-" * 50)
    
    count = 0
    for f in files:
        if f.is_file():
            print(f"  {'→' if dry_run else '✓'} {f.name}")
            if not dry_run:
                f.unlink()
            count += 1
    
    print("-" * 50)
    print(f"{'Würde löschen' if dry_run else 'Gelöscht'}: {count} Dateien")
    return count


def move_files(source: Path, dest: Path, pattern: str, dry_run: bool = False, recursive: bool = False):
    """Verschiebt Dateien nach Pattern"""
    files = list_files(source, pattern, recursive)
    
    if not files:
        print(f"Keine Dateien gefunden: {pattern}")
        return 0
    
    dest.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Verschiebe {len(files)} Dateien nach {dest}:")
    print("-" * 50)
    
    count = 0
    for f in files:
        if f.is_file():
            target = dest / f.name
            print(f"  {'→' if dry_run else '✓'} {f.name}")
            if not dry_run:
                shutil.move(str(f), str(target))
            count += 1
    
    print("-" * 50)
    print(f"{'Würde verschieben' if dry_run else 'Verschoben'}: {count} Dateien")
    return count


def copy_files(source: Path, dest: Path, pattern: str, dry_run: bool = False, recursive: bool = False):
    """Kopiert Dateien nach Pattern"""
    files = list_files(source, pattern, recursive)
    
    if not files:
        print(f"Keine Dateien gefunden: {pattern}")
        return 0
    
    dest.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Kopiere {len(files)} Dateien nach {dest}:")
    print("-" * 50)
    
    count = 0
    for f in files:
        if f.is_file():
            target = dest / f.name
            print(f"  {'→' if dry_run else '✓'} {f.name}")
            if not dry_run:
                shutil.copy2(str(f), str(target))
            count += 1
    
    print("-" * 50)
    print(f"{'Würde kopieren' if dry_run else 'Kopiert'}: {count} Dateien")
    return count


def main():
    parser = argparse.ArgumentParser(description="Batch-Dateioperationen")
    parser.add_argument("action", choices=["delete", "move", "copy", "list"])
    parser.add_argument("source", help="Quellordner")
    parser.add_argument("dest", nargs="?", help="Zielordner (für move/copy)")
    parser.add_argument("--pattern", "-p", default="*", help="Datei-Pattern (z.B. *.py)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Nur anzeigen")
    parser.add_argument("--recursive", "-r", action="store_true", help="Rekursiv")
    
    args = parser.parse_args()
    source = Path(args.source)
    
    if not source.exists():
        print(f"Ordner nicht gefunden: {source}")
        sys.exit(1)
    
    if args.action == "list":
        files = list_files(source, args.pattern, args.recursive)
        print(f"\n{len(files)} Dateien gefunden ({args.pattern}):")
        for f in files:
            print(f"  📄 {f.name}")
    
    elif args.action == "delete":
        delete_files(source, args.pattern, args.dry_run, args.recursive)
    
    elif args.action in ["move", "copy"]:
        if not args.dest:
            print("Zielordner erforderlich für move/copy")
            sys.exit(1)
        dest = Path(args.dest)
        if args.action == "move":
            move_files(source, dest, args.pattern, args.dry_run, args.recursive)
        else:
            copy_files(source, dest, args.pattern, args.dry_run, args.recursive)


if __name__ == "__main__":
    main()
