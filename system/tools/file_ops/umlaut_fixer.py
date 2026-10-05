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
Tool: umlaut_fixer
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version umlaut_fixer

Description:
    [Beschreibung hinzufügen]

Usage:
    python umlaut_fixer.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# coding: utf-8
"""
umlaut_fixer.py - Repariert kaputte deutsche Umlaute in Python-Dateien

Behebt typische Encoding-Probleme wie:
  - Lschen -> Loeschen
  - ffnen -> oeffnen
  - ber -> ueber
  
Extrahiert aus: A1 ProFiler/_Wartung/fix_profiler_complete.py

Usage:
    python umlaut_fixer.py <datei.py>
    python umlaut_fixer.py <datei.py> --dry-run
    python umlaut_fixer.py <datei.py> --json

Autor: Claude (adaptiert)
Abhaengigkeiten: keine (nur stdlib)
"""

import os
import re
import sys
import json
from pathlib import Path

# Reparatur-Woerterbuch fuer kaputte Umlaute
UMLAUT_FIXES = {
    # Loeschen-Familie
    r'\bLschen\b': 'Loeschen', r'\bLsch\b': 'Loesch', r'\bLscht\b': 'Loescht',
    r'\bgelscht\b': 'geloescht', r'\blschen\b': 'loeschen',
    # Hinzufuegen-Familie  
    r'\bHinzufgen\b': 'Hinzufuegen', r'\bhinzufgen\b': 'hinzufuegen',
    # Waehlen-Familie
    r'\bwhlen\b': 'waehlen', r'\bauswhlen\b': 'auswaehlen', 
    r'\bAuswhlen\b': 'Auswaehlen', r'\bausgewhlt\b': 'ausgewaehlt',
    # Oeffnen-Familie
    r'\bffnen\b': 'oeffnen', r'\bffnet\b': 'oeffnet', r'\bgeffnet\b': 'geoeffnet',
    r'\bOeffnen\b': 'Oeffnen',
    # Menue/Schliessen
    r'\bMen\b': 'Menue', r'\bSchlieen\b': 'Schliessen',
    # Groesse/Vorschlaege
    r'\bGre\b': 'Groesse', r'\bVorschlge\b': 'Vorschlaege',
    # Bestaetigung
    r'\bBesttigung\b': 'Bestaetigung', r'\bbesttigen\b': 'bestaetigen',
    # Abhaengigkeiten/Verknuepfungen
    r'\bAbhngigkeiten\b': 'Abhaengigkeiten', r'\bVerknpfungen\b': 'Verknuepfungen',
    # Rueckgaengig
    r'\bRckgngig\b': 'Rueckgaengig', r'\brckgngig\b': 'rueckgaengig',
    # Ueber-Familie
    r'\bEinfhrung\b': 'Einfuehrung', r'\bber\b': 'Ueber',
    r'\bberwacht\b': 'ueberwacht', r'\bberschreiben\b': 'ueberschreiben',
    r'\bberspringe\b': 'ueberspringe',
    # Verschluesselung
    r'\bVerschlsselung\b': 'Verschluesselung', r'\bverschlsselt\b': 'verschluesselt',
    r'\bEntschlsselung\b': 'Entschluesselung', r'\bentschlsselt\b': 'entschluesselt',
    # Schwaerzung
    r'\bSchwrzung\b': 'Schwaerzung', r'\bSchwrzt\b': 'Schwaerzt',
    r'\bgeschwrzt\b': 'geschwaerzt',
    # Pruefung
    r'\bPrfung\b': 'Pruefung', r'\bPrft\b': 'Prueft', r'\bprft\b': 'prueft',
    # Sonstiges
    r'\bVerzgerung\b': 'Verzoegerung', r'\bAbstze\b': 'Absaetze',
    r'\bErhhen\b': 'Erhoehen', r'\bVergrern\b': 'Vergroessern',
    r'\bBentigt\b': 'Benoetigt', r'\buntersttzt\b': 'unterstuetzt',
    r'\bgngige\b': 'gaengige', r'\bSchtzen\b': 'Schuetzen',
    r'\bschtzen\b': 'schuetzen',
    # Fr/fuer - NUR wenn gefolgt von Wort (nicht alleinstehend wie "Fr" Wochentag)
    r'\bFr (?=[a-zaeoeue])': 'Fuer ', r'\bfr (?=[a-zaeoeue])': 'fuer ',
    r'\bluft\b': 'laeuft', r'\bmglich\b': 'moeglich',
    r'\bMglichkeit\b': 'Moeglichkeit', r'\bzurck\b': 'zurueck',
    r'\bGlty\b': 'Gueltig', r'\bStrung\b': 'Stoerung',
    r'\bTglich\b': 'Taeglich', r'\bWchentlich\b': 'Woechentlich',
    r'\bJhrlich\b': 'Jaehrlich', r'\bzuverlssig\b': 'zuverlaessig',
}


def fix_umlaut_errors(content: str) -> tuple:
    """
    Repariert kaputte Umlaute im Text.
    
    Returns:
        tuple: (reparierter_text, liste_der_aenderungen)
    """
    changes = []
    fixed_content = content
    
    for pattern, replacement in UMLAUT_FIXES.items():
        matches = list(re.finditer(pattern, fixed_content))
        if matches:
            for match in matches:
                changes.append({
                    'original': match.group(),
                    'fixed': replacement,
                    'position': match.start()
                })
            fixed_content = re.sub(pattern, replacement, fixed_content)
    
    return fixed_content, changes


def analyze_file(filepath: str) -> dict:
    """
    Analysiert eine Datei auf Umlaut-Probleme.
    
    Returns:
        dict mit Analyse-Ergebnissen
    """
    path = Path(filepath)
    
    if not path.exists():
        return {'error': f'Datei nicht gefunden: {filepath}'}
    
    # Fix: Ordner ueberspringen (bei --recursive)
    if not path.is_file():
        return None
    
    # Versuche verschiedene Encodings
    content = None
    used_encoding = None
    
    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            with open(path, 'r', encoding=encoding, errors='strict') as f:
                content = f.read()
            used_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    
    if content is None:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        used_encoding = 'utf-8 (mit Ersetzungen)'
    
    fixed_content, changes = fix_umlaut_errors(content)
    
    return {
        'file': str(path.absolute()),
        'encoding_detected': used_encoding,
        'issues_found': len(changes),
        'changes': changes,
        'fixed_content': fixed_content
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    filepath = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    json_output = '--json' in sys.argv
    
    result = analyze_file(filepath)
    
    # Skip directories
    if result is None:
        print(f"[INFO] Uebersprungen (kein Datei): {filepath}")
        sys.exit(0)
    
    if 'error' in result:
        if json_output:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"[FEHLER] {result['error']}")
        sys.exit(1)
    
    if json_output:
        # Ohne fixed_content fuer kompaktere Ausgabe
        output = {k: v for k, v in result.items() if k != 'fixed_content'}
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(f"Datei: {result['file']}")
        print(f"Encoding: {result['encoding_detected']}")
        print(f"Probleme gefunden: {result['issues_found']}")
        
        if result['changes']:
            print("\nAenderungen:")
            for change in result['changes'][:20]:
                print(f"  {change['original']} -> {change['fixed']}")
            if len(result['changes']) > 20:
                print(f"  ... und {len(result['changes']) - 20} weitere")
        
        if not dry_run and result['issues_found'] > 0:
            # Backup erstellen
            backup_path = filepath + '.bak'
            with open(backup_path, 'w', encoding='utf-8') as f:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as src:
                    f.write(src.read())
            
            # Reparierte Version speichern
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(result['fixed_content'])
            
            print(f"\n[OK] Datei repariert. Backup: {backup_path}")
        elif dry_run:
            print("\n[DRY-RUN] Keine Aenderungen vorgenommen.")


if __name__ == "__main__":
    main()
