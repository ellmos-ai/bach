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
Tool: german_scanner
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version german_scanner

Description:
    [Beschreibung hinzufügen]

Usage:
    python german_scanner.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# coding: utf-8
"""
german_scanner.py - Findet deutsche Strings in Python-Projekten

Scannt Python-Dateien nach:
  - Strings mit Umlauten (ae, oe, ue, ss)
  - GUI-Texten (setText, setWindowTitle, QLabel, etc.)
  - Deutschen Keywords (Datei, Bearbeiten, Speichern, etc.)

Nuetzlich fuer:
  - Internationalisierung (i18n) vorbereiten
  - Hardcoded Strings finden
  - Uebersetzungs-Listen erstellen

Extrahiert aus: A3 Entwicklungsschleife Advanced/TranslationSystem.py

Usage:
    python german_scanner.py <ordner>
    python german_scanner.py <ordner> --json
    python german_scanner.py <ordner> --export translations.json

Autor: Claude (adaptiert)
Abhaengigkeiten: keine (nur stdlib)
"""

import os
import re
import sys
import json
from pathlib import Path
from typing import Set, Dict, List

# Patterns fuer GUI-String-Erkennung
STRING_PATTERNS = [
    re.compile(r'setText\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'setWindowTitle\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'setToolTip\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'setPlaceholderText\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'QLabel\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'QPushButton\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'QAction\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'addAction\s*\([^,]*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'addTab\s*\([^,]+,\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'QMessageBox\.\w+\s*\([^,]*,\s*["\']([^"\']+)["\']\s*'),
    re.compile(r'showMessage\s*\(\s*["\']([^"\']+)["\']\s*\)'),
    re.compile(r'print\s*\(\s*["\']([^"\']+)["\']\s*\)'),
]

# Deutsche Hinweis-Woerter
GERMAN_HINTS = [
    "datei", "bearbeiten", "ansicht", "hilfe", "oeffnen", "speichern",
    "schliessen", "einstellungen", "abbrechen", "ok", "ja", "nein",
    "start", "stop", "pause", "fortsetzen", "laden", "aktualisieren",
    "hinzufuegen", "entfernen", "loeschen", "kopieren", "einfuegen",
    "suchen", "ersetzen", "weiter", "zurueck", "fertig", "abschliessen",
    "fehler", "warnung", "info", "erfolg", "bitte", "eingabe",
]

# Ordner die uebersprungen werden
SKIP_DIRS = {'build', 'dist', 'venv', '.venv', '__pycache__', '.git', 
             'node_modules', 'env', '.egg-info'}


def is_german(text: str) -> bool:
    """Prueft ob Text wahrscheinlich deutsch ist."""
    # Umlaute pruefen
    if any(ch in text.lower() for ch in "aeoeueaeoeuess"):
        # Echte Umlaute
        if any(ch in text for ch in "aeoeueAeOeUess"):
            return True
    
    # Deutsche Keywords
    text_lower = text.lower()
    if any(hint in text_lower for hint in GERMAN_HINTS):
        return True
    
    return False


def scan_file(filepath: Path) -> List[Dict]:
    """Scannt eine Python-Datei nach deutschen Strings."""
    results = []
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        return [{'error': str(e)}]
    
    for pattern in STRING_PATTERNS:
        for match in pattern.finditer(content):
            text = match.group(1).strip()
            if text and len(text) > 1 and is_german(text):
                # Zeilennummer finden
                line_num = content[:match.start()].count('\n') + 1
                results.append({
                    'text': text,
                    'line': line_num,
                    'file': str(filepath)
                })
    
    return results


def scan_directory(directory: Path) -> Dict:
    """Scannt ein Verzeichnis rekursiv nach deutschen Strings."""
    all_strings = set()
    file_results = []
    files_scanned = 0
    
    for py_file in directory.rglob("*.py"):
        # Skip-Ordner pruefen
        if any(skip in py_file.parts for skip in SKIP_DIRS):
            continue
        
        files_scanned += 1
        results = scan_file(py_file)
        
        for result in results:
            if 'error' not in result:
                all_strings.add(result['text'])
                file_results.append(result)
    
    return {
        'directory': str(directory.absolute()),
        'files_scanned': files_scanned,
        'unique_strings': len(all_strings),
        'total_occurrences': len(file_results),
        'strings': sorted(list(all_strings)),
        'details': file_results
    }


def export_translations(strings: List[str], output_file: Path):
    """Exportiert Strings als Uebersetzungs-Template."""
    translations = {}
    for s in strings:
        # Key aus String generieren (snake_case)
        key = re.sub(r'[^a-zA-Z0-9]+', '_', s.lower()).strip('_')[:50]
        translations[key] = {
            "de": s,
            "en": ""  # Leer fuer manuelle Uebersetzung
        }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(translations, f, indent=2, ensure_ascii=False)
    
    return len(translations)


def safe_print(text: str):
    """Encoding-sicheres Print fuer Windows-Konsole."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Fallback: Nicht-druckbare Zeichen ersetzen
        print(text.encode('ascii', 'replace').decode('ascii'))


def main():
    # UTF-8 Output erzwingen wenn moeglich
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass  # Alte Python-Versionen
    
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    target = sys.argv[1]
    json_output = '--json' in sys.argv
    export_file = None
    
    # Export-Parameter pruefen
    if '--export' in sys.argv:
        idx = sys.argv.index('--export')
        if idx + 1 < len(sys.argv):
            export_file = sys.argv[idx + 1]
    
    path = Path(target)
    
    if not path.exists():
        print(f"[FEHLER] Pfad nicht gefunden: {target}")
        sys.exit(1)
    
    if path.is_file():
        results = scan_file(path)
        output = {
            'file': str(path),
            'strings_found': len(results),
            'strings': [r['text'] for r in results if 'error' not in r],
            'details': results
        }
    else:
        output = scan_directory(path)
    
    if json_output:
        # Kompakte Ausgabe ohne Details
        compact = {k: v for k, v in output.items() if k != 'details'}
        print(json.dumps(compact, indent=2, ensure_ascii=False))
    else:
        print(f"Gescannt: {output.get('directory', output.get('file'))}")
        print(f"Dateien: {output.get('files_scanned', 1)}")
        print(f"Unique Strings: {output.get('unique_strings', len(output.get('strings', [])))}")
        
        strings = output.get('strings', [])
        if strings:
            print("\nGefundene deutsche Strings:")
            for s in strings[:30]:
                safe_print(f"  - {s}")
            if len(strings) > 30:
                print(f"  ... und {len(strings) - 30} weitere")
    
    # Export wenn gewuenscht
    if export_file:
        strings = output.get('strings', [])
        count = export_translations(strings, Path(export_file))
        print(f"\n[OK] {count} Strings exportiert nach: {export_file}")


if __name__ == "__main__":
    main()
