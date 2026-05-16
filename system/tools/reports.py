#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: reports
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version reports

Description:
    [Beschreibung hinzufügen]

Usage:
    python reports.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# coding: utf-8
"""
reports.py - Erstellt Änderungsreports für andere Steuerroutinen

Generiert lesbare Markdown-Reports aus Verzeichnisänderungen.
Speichert in: reports/<alias>_changes_<datum>.md

Usage:
    python reports.py <alias>
    python reports.py skills
"""

import sys
import json
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REPORTS_DIR = SCRIPT_DIR / "reports"

sys.path.insert(0, str(SCRIPT_DIR))
try:
    from watcher import check_changes, get_latest_snapshot
    from writer import WATCHED_DIRS
except ImportError:
    check_changes = None
    get_latest_snapshot = None
    WATCHED_DIRS = {}


def create_report(alias: str) -> str:
    """Erstellt Änderungsreport für Alias."""
    changes = check_changes(alias)
    
    report_lines = [
        f"# Änderungsreport: {alias}",
        f"**Erstellt:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ""
    ]
    
    if changes.get("reason") == "no_previous_snapshot":
        report_lines.extend([
            "## Status",
            "Kein vorheriger Snapshot vorhanden.",
            "Erstelle zuerst einen Baseline-Snapshot.",
            ""
        ])
    else:
        report_lines.extend([
            f"**Zeitraum:** {changes.get('last_snapshot', 'unbekannt')[:10]} bis {changes.get('current_timestamp', 'jetzt')[:10]}",
            ""
        ])
        
        if not changes["has_changes"]:
            report_lines.extend([
                "## Status",
                "✅ Keine Änderungen seit letztem Snapshot.",
                ""
            ])
        else:
            # Neue Dateien
            new_files = changes.get("new_files", [])
            report_lines.extend([
                f"## Neue Dateien ({len(new_files)})",
                ""
            ])
            if new_files:
                for f in sorted(new_files):
                    report_lines.append(f"- `{f}`")
            else:
                report_lines.append("*Keine*")
            report_lines.append("")
            
            # Geänderte Dateien
            modified = changes.get("modified_files", [])
            report_lines.extend([
                f"## Geänderte Dateien ({len(modified)})",
                ""
            ])
            if modified:
                for m in modified:
                    report_lines.append(f"- `{m['path']}` (Größe: {m['old_size']} → {m['new_size']})")
            else:
                report_lines.append("*Keine*")
            report_lines.append("")
            
            # Gelöschte Dateien
            deleted = changes.get("deleted_files", [])
            report_lines.extend([
                f"## Gelöschte Dateien ({len(deleted)})",
                ""
            ])
            if deleted:
                for f in sorted(deleted):
                    report_lines.append(f"- `{f}`")
            else:
                report_lines.append("*Keine*")
            report_lines.append("")
            
            # Neue Verzeichnisse
            new_dirs = changes.get("new_directories", [])
            report_lines.extend([
                f"## Neue Verzeichnisse ({len(new_dirs)})",
                ""
            ])
            if new_dirs:
                for d in sorted(new_dirs):
                    report_lines.append(f"- `{d}/`")
            else:
                report_lines.append("*Keine*")
            report_lines.append("")
            
            # Gelöschte Verzeichnisse
            del_dirs = changes.get("deleted_directories", [])
            report_lines.extend([
                f"## Gelöschte Verzeichnisse ({len(del_dirs)})",
                ""
            ])
            if del_dirs:
                for d in sorted(del_dirs):
                    report_lines.append(f"- `{d}/`")
            else:
                report_lines.append("*Keine*")
    
    # Report speichern
    REPORTS_DIR.mkdir(exist_ok=True)
    filename = f"{alias}_changes_{datetime.now().strftime('%Y-%m-%d')}.md"
    filepath = REPORTS_DIR / filename
    
    report_content = "\n".join(report_lines)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    return str(filepath)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python reports.py <alias>")
        print(f"Verfügbare Aliase: {list(WATCHED_DIRS.keys())}")
        sys.exit(1)
    
    alias = sys.argv[1]
    
    try:
        filepath = create_report(alias)
        print(f"Report erstellt: {filepath}")
    except Exception as e:
        print(f"Fehler: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
