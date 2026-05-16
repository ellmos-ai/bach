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
Tool: c_json_repair
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_json_repair

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_json_repair.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
import urllib.request

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
REGISTRY_FILE = SCRIPT_DIR / "emoji_registry.json"

GEMOJI_URL = "https:/raw.githubusercontent.com/github/gemoji/master/db/emoji.json"
TASKS_FILE = BATCH_DIR / "tasks.json"

# Spezial-Zeichen die NICHT ersetzt werden sollen (harmlos in JSON)
SAFE_CHARS = set([
    '\u2192',  # -> Pfeil (wird separat behandelt)
    '\u2190',  # <- Pfeil
    '\u2194',  # <-> Pfeil
])

# Manuelle Overrides fuer bessere ASCII-Namen
ASCII_OVERRIDES = {
    # Pfeile
    '\u2192': '->',      # Rightwards Arrow
    '\u2190': '<-',      # Leftwards Arrow
    '\u2194': '<->',     # Left Right Arrow
    '\u2191': '^',       # Upwards Arrow
    '\u2193': 'v',       # Downwards Arrow
    # Ampel
    '\U0001F7E2': '[GRUEN]',
    '\U0001F7E1': '[GELB]',
    '\U0001F534': '[ROT]',
    # Haeufige
    '\U0001F527': '[TOOL]',
    '\U0001F4C1': '[FOLDER]',
    '\U0001F4C4': '[FILE]',
    '\u2705': '[OK]',
    '\u274C': '[X]',
    '\u26A0': '[WARN]',
    '\u2139': '[INFO]',
    '\U0001F512': '[LOCK]',
    # Typografische Zeichen (diese ersetzen wir NICHT mehr direkt)
    # da sie in JSON-Strings bleiben koennen
}

# Typografische Zeichen die wir ignorieren (sind OK in JSON)
IGNORE_CHARS = set([
    '\u201C',  # "
    '\u201D',  # "
    '\u2018',  # '
    '\u2019',  # '
    '\u2013',  # en-dash
    '\u2014',  # em-dash
])


class GemojiDatabase:
    """
    Emoji-Lookup mit Fallback-Strategie:
    1. Erst emoji-Paket versuchen (besser, aktueller)
    2. Fallback auf lokale gemoji.json
    """
    
    def __init__(self):
        self.use_package = EMOJI_PACKAGE_AVAILABLE
        self.gemoji_data: Dict[str, Dict] = {}
        
        if not self.use_package:
            self._load_gemoji_json()
    
    def _load_gemoji_json(self):
        """Laedt gemoji.json als Fallback."""
        if not GEMOJI_FILE.exists():
            print(f"[WARN] gemoji.json nicht gefunden. Lade herunter...")
            self.update()
        
        try:
            with open(GEMOJI_FILE, 'r', encoding='utf-8') as f:
                gemoji_list = json.load(f)
            
            for entry in gemoji_list:
                emoji_char = entry.get('emoji', '')
                if emoji_char:
                    self.gemoji_data[emoji_char] = {
                        'description': entry.get('description', ''),
                        'aliases': entry.get('aliases', []),
                        'tags': entry.get('tags', []),
                        'category': entry.get('category', '')
                    }
        except Exception as e:
            print(f"[ERROR] Konnte gemoji.json nicht laden: {e}")
    
    def update(self) -> bool:
        """Laedt aktuelle gemoji.json von GitHub (fuer Fallback)."""
        try:
            print(f"[INFO] Lade gemoji.json von GitHub...")
            urllib.request.urlretrieve(GEMOJI_URL, GEMOJI_FILE)
            print(f"[OK] gemoji.json aktualisiert ({GEMOJI_FILE.stat().st_size / 1024} KB)")
            self._load_gemoji_json()
            return True
        except Exception as e:
            print(f"[ERROR] Download fehlgeschlagen: {e}")
            return False
    
    def lookup(self, char: str) -> Optional[str]:
        """
        Sucht Emoji-Namen.
        Returns: Name wie 'thumbs_up' oder None
        """
        if self.use_package:
            # Nutze emoji-Paket (demojize)
            try:
                result = emoji_pkg.demojize(char, delimiters=('', ''))
                # Wenn unveraendert zurueckkommt, wurde es nicht erkannt
                if result != char:
                    return result
            except Exception:
                pass
            return None
        else:
            # Fallback: gemoji.json
            info = self.gemoji_data.get(char)
            if info:
                if info['aliases']:
                    return info['aliases'][0]
                return info['description']
            return None
    
    def get_ascii(self, char: str) -> Optional[str]:
        """Generiert ASCII-Ersatz fuer Emoji."""
        # Erst manuelle Overrides pruefen
        if char in ASCII_OVERRIDES:
            return ASCII_OVERRIDES[char]
        
        # Ignorierte Zeichen
        if char in IGNORE_CHARS:
            return None  # Nicht ersetzen
        
        # Lookup via Paket oder Fallback
        name = self.lookup(char)
        if name:
            # Zu ASCII-Tag konvertieren
            ascii_tag = name.upper().replace(' ', '_').replace('-', '_')
            # Nur Buchstaben/Zahlen/Underscore
            ascii_tag = re.sub(r'[^A-Z0-9_]', '', ascii_tag)
            
            if ascii_tag:
                return f"[{ascii_tag}]"
        
        return None
    
    def get_source(self) -> str:
        """Gibt an welche Quelle genutzt wird."""
        if self.use_package:
            return f"emoji-Paket v{emoji_pkg.__version__}"
        else:
            return f"gemoji.json ({len(self.gemoji_data)} Eintraege)"
    
    def __len__(self):
        if self.use_package:
            # emoji-Paket hat ~1900 Emojis
            return len(emoji_pkg.EMOJI_DATA) if hasattr(emoji_pkg, 'EMOJI_DATA') else 1900
        return len(self.gemoji_data)


class EmojiRegistry:
    """Lokale Registry fuer Custom-Mappings und Statistiken."""
    
    def __init__(self):
        self.data = self._load()
        self.stats = {
            'auto_resolved': 0,
            'quarantined': 0,
            'ignored': 0
        }
    
    def _load(self) -> Dict:
        if REGISTRY_FILE.exists():
            try:
                with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"meta": {"version": "3.0"}, "emojis": {}, "quarantine": []}
    
    def save(self):
        self.data["meta"]["last_updated"] = datetime.now().isoformat()
        with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def add_quarantine(self, char: str, found_in: str):
        """Fuegt Zeichen zur Quarantaene hinzu."""
        unicode_hex = f"U+{ord(char):04X}"
        entry = {
            "char": char,
            "unicode": unicode_hex,
            "found_in": found_in,
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        
        # Duplikate vermeiden
        existing = [q['unicode'] for q in self.data.get('quarantine', [])]
        if unicode_hex not in existing:
            self.data.setdefault('quarantine', []).append(entry)
    
    def get_quarantine(self) -> List[Dict]:
        return self.data.get('quarantine', [])


def create_quarantine_task(quarantine_entries: List[Dict]) -> bool:
    """Erstellt einen Task fuer Quarantaene-Emojis."""
    if not quarantine_entries or not TASKS_FILE.exists():
        return False
    
    try:
        with open(TASKS_FILE, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    # Pruefen ob Task schon existiert
    task_id = "EMOJI_QUARANTINE"
    existing = [t for t in tasks.get('tasks', []) if t.get('id') == task_id]
    if existing:
        # Task existiert - nur updaten wenn mehr Eintraege
        return False
    
    # Emojis fuer Beschreibung sammeln
    emoji_list = [f"{q['unicode']} ({q['found_in']})" for q in quarantine_entries[:5]]
    if len(quarantine_entries) > 5:
        emoji_list.append(f"... +{len(quarantine_entries) - 5} weitere")
    
    new_task = {
        "id": task_id,
        "title": f"[Q] {len(quarantine_entries)} Emoji(s) in Quarantaene",
        "status": "open",
        "priority": "low",
        "category": "maintenance",
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "description": f"Unbekannte Emojis gefunden:\n" + "\n".join(emoji_list),
        "action": "ASCII-Mapping in c_json_repair.py ASCII_OVERRIDES hinzufuegen"
    }
    
    tasks.setdefault('tasks', []).append(new_task)
    
    try:
        with open(TASKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
        print(f"[TASK] Quarantaene-Task erstellt: {task_id}")
        return True
    except OSError:
        return False


def process_content(content: str, gemoji: GemojiDatabase, registry: EmojiRegistry, 
                    filename: str) -> Tuple[str, List[str]]:
    """Verarbeitet Content und ersetzt Emojis."""
    changes = []
    
    # Finde alle Nicht-ASCII Zeichen
    result = []
    i = 0
    
    while i < len(content):
        char = content[i]
        
        # ASCII-Zeichen direkt uebernehmen
        if ord(char) < 128:
            result.append(char)
            i += 1
            continue
        
        # Ignorierte Zeichen (typografisch)
        if char in IGNORE_CHARS:
            result.append(char)
            registry.stats['ignored'] += 1
            i += 1
            continue
        
        # Deutsche Umlaute und normale erweiterte Zeichen belassen
        if char in 'äöüÄÖÜß' or (0x00A0 <= ord(char) <= 0x00FF):
            # Latin-1 Supplement - normale europaeische Zeichen
            result.append(char)
            i += 1
            continue
        
        # Latin Extended-A und B (europaeische Sonderzeichen)
        if 0x0100 <= ord(char) <= 0x024F:
            result.append(char)
            i += 1
            continue
        
        # Allgemeine Interpunktion (U+2000-U+206F) belassen
        if 0x2000 <= ord(char) <= 0x206F:
            result.append(char)
            i += 1
            continue
        
        # ASCII-Ersatz suchen
        ascii_replacement = gemoji.get_ascii(char)
        
        if ascii_replacement:
            result.append(ascii_replacement)
            registry.stats['auto_resolved'] += 1
            unicode_hex = f"U+{ord(char):04X}"
            changes.append(f"AUTO: {unicode_hex} -> {ascii_replacement}")
        else:
            # Unbekanntes Zeichen - Quarantaene
            unicode_hex = f"U+{ord(char):04X}"
            quarantine_marker = f"[Q:{ord(char):04X}]"
            result.append(quarantine_marker)
            registry.add_quarantine(char, filename)
            registry.stats['quarantined'] += 1
            changes.append(f"QUARANTINE: {unicode_hex} -> {quarantine_marker}")
        
        i += 1
    
    return ''.join(result), changes


def fix_mojibake(content: str) -> Tuple[str, List[str]]:
    """Repariert bekannte Mojibake-Sequenzen."""
    fixes = []
    
    # Bekannte Mojibake-Patterns (Byte-Sequenzen)
    mojibake_map = {
        b'\xc3\xa2\xe2\x80\xa0\xe2\x80\x99': b'->',  # Doppelt-encodierter Pfeil
        b'\xc3\xa2\xe2\x80\xa0\xe2\x80\x98': b'<-',
        b'\xc3\xa4': 'ä'.encode('utf-8'),  # ae
        b'\xc3\xb6': 'ö'.encode('utf-8'),  # oe
        b'\xc3\xbc': 'ü'.encode('utf-8'),  # ue
        b'\xc3\x84': 'Ä'.encode('utf-8'),  # Ae
        b'\xc3\x96': 'Ö'.encode('utf-8'),  # Oe
        b'\xc3\x9c': 'Ü'.encode('utf-8'),  # Ue
        b'\xc3\x9f': 'ß'.encode('utf-8'),  # ss
    }
    
    try:
        content_bytes = content.encode('utf-8')
        for bad, good in mojibake_map.items():
            if bad in content_bytes:
                content_bytes = content_bytes.replace(bad, good)
                fixes.append(f"Mojibake repariert")
        content = content_bytes.decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass

    return content, fixes


def repair_json(file_path: str, dry_run: bool = False) -> Dict[str, Any]:
    """Hauptfunktion: Repariert JSON-Datei."""
    result = {
        "file": file_path,
        "success": False,
        "changes": [],
        "stats": {},
        "error": None
    }
    
    gemoji = GemojiDatabase()
    registry = EmojiRegistry()
    
    try:
        # Lesen
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            original = f.read()
        
        content = original
        
        # 1. Mojibake reparieren
        content, mojibake_fixes = fix_mojibake(content)
        result["changes"].extend(mojibake_fixes)
        
        # 2. Emojis verarbeiten
        content, emoji_changes = process_content(content, gemoji, registry, 
                                                  Path(file_path).name)
        result["changes"].extend(emoji_changes)
        
        # JSON validieren
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            result["error"] = f"JSON invalid nach Verarbeitung: {e}"
            return result
        
        # Speichern
        if not dry_run and content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Registry speichern wenn Quarantaene
            if registry.stats['quarantined'] > 0:
                registry.save()
                # Task erstellen
                create_quarantine_task(registry.get_quarantine())
        
        result["success"] = True
        result["stats"] = registry.stats
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def cmd_stats():
    """Zeigt Statistiken."""
    gemoji = GemojiDatabase()
    registry = EmojiRegistry()
    
    print("=" * 50)
    print("EMOJI SYSTEM STATUS")
    print("=" * 50)
    print(f"Datenquelle:        {gemoji.get_source()}")
    print(f"Emoji-Eintraege:    ~{len(gemoji)}")
    print(f"Custom Overrides:   {len(ASCII_OVERRIDES)}")
    print(f"Ignorierte Zeichen: {len(IGNORE_CHARS)}")
    
    if not EMOJI_PACKAGE_AVAILABLE:
        print(f"\n[TIPP] Fuer bessere Ergebnisse:")
        print(f"       pip install emoji")
    
    quarantine = registry.get_quarantine()
    if quarantine:
        print(f"\n[QUARANTINE] {len(quarantine)} unbekannte Zeichen:")
        for q in quarantine[:10]:
            print(f"  {q['unicode']} - gefunden in {q['found_in']}")
        if len(quarantine) > 10:
            print(f"  ... und {len(quarantine) - 10} weitere")
    else:
        print(f"\nQuarantaene:        leer (alles automatisch geloest!)")
    
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
    
    # Spezial-Kommandos
    if '--update-gemoji' in sys.argv:
        gemoji = GemojiDatabase()
        gemoji.update()
        sys.exit(0)
    
    if '--stats' in sys.argv:
        cmd_stats()
        sys.exit(0)
    
    # Normal: Datei reparieren
    file_path = sys.argv[1]
    dry_run = '--dry-run' in sys.argv
    
    if not os.path.isfile(file_path):
        print(f"[FEHLER] Datei nicht gefunden: {file_path}")
        sys.exit(1)
    
    result = repair_json(file_path, dry_run)
    
    # Output
    status = "OK" if result["success"] else "FEHLER"
    mode = " (DRY-RUN)" if dry_run else ""
    print(f"[{status}]{mode} {result['file']}")
    
    if result["stats"]:
        s = result["stats"]
        print(f"  Auto-geloest:  {s.get('auto_resolved', 0)}")
        print(f"  Ignoriert:     {s.get('ignored', 0)}")
        print(f"  Quarantaene:   {s.get('quarantined', 0)}")
    
    if result["changes"]:
        unique_changes = list(set(result["changes"]))[:5]
        for c in unique_changes:
            print(f"    {c}")
        if len(result["changes"]) > 5:
            print(f"    ... und {len(result['changes']) - 5} weitere")
    
    if result["error"]:
        print(f"  Fehler: {result['error']}")
    
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
