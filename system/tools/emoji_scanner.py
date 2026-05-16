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
Tool: c_emoji_scanner
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_emoji_scanner

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_emoji_scanner.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import sys
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# Versuche emoji-Paket zu laden
try:
    import emoji as emoji_pkg
    EMOJI_PACKAGE_AVAILABLE = True
except ImportError:
    emoji_pkg = None
    EMOJI_PACKAGE_AVAILABLE = False

# Pfade
SCRIPT_DIR = Path(__file__).parent
BATCH_DIR = SCRIPT_DIR.parent
GEMOJI_FILE = SCRIPT_DIR / "gemoji.json"

# Emoji-Pattern (breiter Unicode-Bereich)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # Symbole & Piktogramme
    "\U00002702-\U000027B0"  # Dingbats
    "\U00002190-\U000021FF"  # Pfeile
    "\U00002600-\U000026FF"  # Misc Symbole
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F680-\U0001F6FF"  # Transport
    "]+"
)

# Custom Overrides (gleich wie in c_json_repair.py)
ASCII_OVERRIDES = {
    '\u2192': '->', '\u2190': '<-', '\u2194': '<->',
    '\U0001F7E2': '[GRUEN]', '\U0001F7E1': '[GELB]', '\U0001F534': '[ROT]',
    '\U0001F527': '[TOOL]', '\U0001F4C1': '[FOLDER]', '\U0001F4C4': '[FILE]',
    '\u2705': '[OK]', '\u274C': '[X]', '\u26A0': '[WARN]',
}


class EmojiLookup:
    """Emoji-Lookup mit Fallback-Strategie."""
    
    def __init__(self):
        self.use_package = EMOJI_PACKAGE_AVAILABLE
        self.gemoji_data: Dict[str, str] = {}
        
        if not self.use_package:
            self._load_gemoji()
    
    def _load_gemoji(self):
        """Laedt gemoji.json als Fallback."""
        if GEMOJI_FILE.exists():
            try:
                with open(GEMOJI_FILE, 'r', encoding='utf-8') as f:
                    for entry in json.load(f):
                        emoji_char = entry.get('emoji', '')
                        if emoji_char:
                            name = entry.get('aliases', [entry.get('description', '')])[0]
                            self.gemoji_data[emoji_char] = name
            except (json.JSONDecodeError, OSError):
                pass
    
    def can_resolve(self, char: str) -> Tuple[bool, str]:
        """
        Prueft ob Emoji aufgeloest werden kann.
        Returns: (kann_aufloesen, ascii_name)
        """
        # Custom Override?
        if char in ASCII_OVERRIDES:
            return True, ASCII_OVERRIDES[char]
        
        # Via Paket oder Fallback
        if self.use_package:
            try:
                result = emoji_pkg.demojize(char, delimiters=('', ''))
                if result != char:
                    ascii_tag = result.upper().replace(' ', '_').replace('-', '_')
                    ascii_tag = re.sub(r'[^A-Z0-9_]', '', ascii_tag)
                    return True, f"[{ascii_tag}]"
            except Exception:
                pass
        else:
            if char in self.gemoji_data:
                name = self.gemoji_data[char]
                ascii_tag = name.upper().replace(' ', '_').replace('-', '_')
                ascii_tag = re.sub(r'[^A-Z0-9_]', '', ascii_tag)
                return True, f"[{ascii_tag}]"
        
        return False, f"[Q:{ord(char):04X}]"
    
    def get_source(self) -> str:
        if self.use_package:
            return f"emoji-Paket v{emoji_pkg.__version__}"
        return f"gemoji.json ({len(self.gemoji_data)} Eintraege)"


def scan_file(filepath: Path, lookup: EmojiLookup) -> Dict:
    """Scannt eine Datei nach Emojis."""
    result = {
        "file": str(filepath.name),
        "total": 0,
        "resolvable": 0,
        "unresolvable": 0,
        "details": []
    }
    
    try:
        content = filepath.read_text(encoding='utf-8')
    except OSError:
        return result
    
    seen = set()
    for match in EMOJI_PATTERN.finditer(content):
        for char in match.group():
            if char in seen:
                continue
            seen.add(char)
            
            result["total"] += 1
            can_resolve, ascii_name = lookup.can_resolve(char)
            
            if can_resolve:
                result["resolvable"] += 1
            else:
                result["unresolvable"] += 1
                result["details"].append(f"U+{ord(char):04X} -> {ascii_name}")
    
    return result


def scan_batch_files() -> List[Dict]:
    """Scannt alle wichtigen JSON-Dateien."""
    files = [
        BATCH_DIR / "DATA" / "system-tasks.json",
        BATCH_DIR / "TASKS_all.json",
        BATCH_DIR / "chat.json",
        BATCH_DIR / "config.json",
    ]
    
    lookup = EmojiLookup()
    results = []
    
    for f in files:
        if f.exists():
            results.append(scan_file(f, lookup))
    
    return results


def print_status():
    """Zeigt System-Status."""
    lookup = EmojiLookup()
    
    print("=" * 50)
    print("EMOJI SYSTEM STATUS")
    print("=" * 50)
    print(f"Datenquelle:      {lookup.get_source()}")
    print(f"Custom Overrides: {len(ASCII_OVERRIDES)}")
    
    if not EMOJI_PACKAGE_AVAILABLE:
        print(f"\n[TIPP] Fuer bessere Ergebnisse:")
        print(f"       pip install emoji")
    
    print("=" * 50)


def main():
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass
    
    if len(sys.argv) < 2 or '--help' in sys.argv:
        print(__doc__)
        sys.exit(0)
    
    if '--status' in sys.argv:
        print_status()
        sys.exit(0)
    
    if '--scan-batch' in sys.argv:
        results = scan_batch_files()
        lookup = EmojiLookup()
        
        total = sum(r["total"] for r in results)
        resolvable = sum(r["resolvable"] for r in results)
        unresolvable = sum(r["unresolvable"] for r in results)
        
        print("=" * 50)
        print("EMOJI-SCANNER ERGEBNIS")
        print("=" * 50)
        print(f"Datenquelle:      {lookup.get_source()}")
        print(f"Dateien gescannt: {len(results)}")
        print(f"Emojis gefunden:  {total} (unique)")
        print(f"Auto-aufloesbar:  {resolvable}")
        print(f"Quarantaene:      {unresolvable}")
        print("=" * 50)
        
        if unresolvable > 0:
            print("\n[WARNUNG] Nicht aufloesbare Emojis:")
            for r in results:
                for d in r["details"]:
                    print(f"  {d}")
        
        sys.exit(1 if unresolvable > 0 else 0)
    
    # Einzelne Datei/Ordner scannen
    target = Path(sys.argv[1])
    
    if not target.exists():
        print(f"[FEHLER] Nicht gefunden: {target}")
        sys.exit(1)
    
    lookup = EmojiLookup()
    
    if target.is_file():
        results = [scan_file(target, lookup)]
    else:
        results = []
        for f in target.rglob("*.json"):
            if ".bak" not in str(f) and "__pycache__" not in str(f):
                results.append(scan_file(f, lookup))
    
    # Output
    total = sum(r["total"] for r in results)
    resolvable = sum(r["resolvable"] for r in results)
    unresolvable = sum(r["unresolvable"] for r in results)
    
    status = "OK" if unresolvable == 0 else "WARNUNG"
    print(f"[{status}] {len(results)} Datei(en), {total} Emojis")
    print(f"        {resolvable} aufloesbar, {unresolvable} Quarantaene")
    
    sys.exit(1 if unresolvable > 0 else 0)


if __name__ == "__main__":
    main()
