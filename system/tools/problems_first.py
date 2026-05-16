#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Tool: problems_first
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version problems_first

Description:
    [Beschreibung hinzufügen]

Usage:
    python problems_first.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

"""
Problems First - Automatische Fehler-Erkennung
==============================================

Von CHIAH nach BACH portiert.
Scannt Auto-Log und andere Quellen nach Problemen.
"""
from pathlib import Path
from datetime import datetime, timedelta
import re


def scan_problems(base_path: Path, hours: int = 24) -> dict:
    """
    Scannt nach Problemen der letzten X Stunden.
    
    Returns:
        dict: {
            'errors': [(timestamp, message), ...],
            'warnings': [(timestamp, message), ...],
            'total': int
        }
    """
    results = {
        'errors': [],
        'warnings': [],
        'total': 0
    }
    
    # Auto-Log scannen
    log_path = base_path / "logs" / "auto_log_extended.txt"
    if log_path.exists():
        _scan_log_file(log_path, results, hours)
    
    # Auch normalen auto_log prüfen
    simple_log = base_path / "logs" / "auto_log.txt"
    if simple_log.exists():
        _scan_log_file(simple_log, results, hours)
    
    results['total'] = len(results['errors']) + len(results['warnings'])
    return results


def _scan_log_file(log_path: Path, results: dict, hours: int):
    """Scannt einzelne Log-Datei nach Problemen."""
    try:
        content = log_path.read_text(encoding='utf-8', errors='ignore')
        lines = content.strip().split('\n')
        
        # Pattern für Log-Einträge: [HH:MM:SS] [TYPE] Message
        pattern = r'\[(\d{2}:\d{2}:\d{2})\]\s*\[(\w+)\]\s*(.+)'
        
        for line in lines[-500:]:  # Letzte 500 Zeilen
            match = re.match(pattern, line)
            if match:
                timestamp, log_type, message = match.groups()
                log_type_upper = log_type.upper()
                
                if log_type_upper == 'ERROR':
                    results['errors'].append((timestamp, message))
                elif log_type_upper in ('WARNING', 'WARN'):
                    results['warnings'].append((timestamp, message))
                elif 'ERROR' in message.upper():
                    results['errors'].append((timestamp, message))
                elif 'FAILED' in message.upper() or 'FEHLER' in message.upper():
                    results['errors'].append((timestamp, message))
                    
    except Exception as e:
        results['errors'].append(('NOW', f'Log-Scan fehlgeschlagen: {e}'))


def format_problems_report(problems: dict, max_each: int = 5) -> str:
    """
    Formatiert Problems-Report für Startup.
    
    Args:
        problems: Ergebnis von scan_problems()
        max_each: Max Einträge pro Kategorie
        
    Returns:
        str: Formatierter Report oder leerer String wenn keine Probleme
    """
    if problems['total'] == 0:
        return ""
    
    lines = []
    lines.append("[PROBLEMS FIRST]")
    
    if problems['errors']:
        lines.append(f" [!] {len(problems['errors'])} ERROR(s) gefunden:")
        for ts, msg in problems['errors'][:max_each]:
            # Nachricht kürzen
            short_msg = msg[:60] + "..." if len(msg) > 60 else msg
            lines.append(f"    [{ts}] {short_msg}")
        if len(problems['errors']) > max_each:
            lines.append(f"    ... und {len(problems['errors']) - max_each} weitere")
    
    if problems['warnings']:
        lines.append(f" [W] {len(problems['warnings'])} WARNING(s):")
        for ts, msg in problems['warnings'][:max_each]:
            short_msg = msg[:60] + "..." if len(msg) > 60 else msg
            lines.append(f"    [{ts}] {short_msg}")
        if len(problems['warnings']) > max_each:
            lines.append(f"    ... und {len(problems['warnings']) - max_each} weitere")
    
    lines.append("")
    lines.append(" --> bach logs errors (Details)")
    
    return '\n'.join(lines)


# CLI-Support
if __name__ == "__main__":
    import sys
    base = Path(__file__).parent.parent
    
    hours = 24
    if len(sys.argv) > 1:
        try:
            hours = int(sys.argv[1])
        except (ValueError, TypeError):
            pass
    
    problems = scan_problems(base, hours)
    
    if problems['total'] == 0:
        print("[OK] Keine Probleme in den letzten", hours, "Stunden")
    else:
        print(format_problems_report(problems))
