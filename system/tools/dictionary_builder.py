#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool: c_dictionary_builder
Version: 1.0.0
Author: BACH Team
Created: 2026-02-04
Updated: 2026-02-04
Anthropic-Compatible: True

VERSIONS-HINWEIS: Prüfe auf neuere Versionen mit: bach tools version c_dictionary_builder

Description:
    [Beschreibung hinzufügen]

Usage:
    python c_dictionary_builder.py [args]
"""

__version__ = "1.0.0"
__author__ = "BACH Team"

# -*- coding: utf-8 -*-
"""
RecludOS Language Dictionary Builder v1.0.0

Erfasst alle Ordner- und Dateinamen des RecludOS-Systems und erstellt
ein mehrsprachiges Wörterbuch für zukünftige Lokalisierung.

Funktionen:
- Scan aller Ordner/Dateinamen im recludOS-Verzeichnis
- Automatische Extraktion deutscher Begriffe
- Manuelles Hinzufügen von Übersetzungen
- Online-Abfrage-Vorbereitung (DeepL, Google Translate API)
- Export/Import von Wörterbüchern

Autor: RecludOS System
Datum: 2025-12-30
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

# Windows Console UTF-8 Support
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

# Pfade
SCRIPT_DIR = Path(__file__).parent
LOCALES_DIR = SCRIPT_DIR / "locales"
DICTIONARY_FILE = LOCALES_DIR / "dictionary.json"
RECLUDOS_BASE = SCRIPT_DIR.parents[4]  # main/system/controll/manage/system/languages -> recludOS root

# Unterstützte Sprachen
SUPPORTED_LANGUAGES = {
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "nl": "Nederlands",
    "pl": "Polski",
    "ru": "Русский",
    "zh": "中文",
    "ja": "日本語"
}

# Ausschluss-Patterns (keine Übersetzung nötig)
EXCLUDE_PATTERNS = [
    r"^\.",           # Versteckte Dateien
    r"^__",           # Python-Interna
    r"\.pyc$",        # Kompilierte Python
    r"\.git",         # Git
    r"node_modules",  # Node
    r"\.json$",       # JSON-Dateien (Daten, keine UI)
    r"\.db$",         # Datenbanken
    r"\.log$",        # Logs
]

# Technische Begriffe (bleiben unübersetzt)
TECHNICAL_TERMS = {
    "API", "JSON", "XML", "HTML", "CSS", "SQL", "HTTP", "HTTPS",
    "URL", "URI", "ID", "UUID", "CLI", "GUI", "UI", "UX",
    "PDF", "CSV", "TXT", "MD", "YAML", "TOML",
    "Python", "JavaScript", "TypeScript", "Rust", "Go",
    "Git", "GitHub", "Docker", "Kubernetes",
    "Claude", "Gemini", "GPT", "LLM", "AI", "ML",
    "RecludOS", "recludOS", "Ollama", "MCP"
}


class DictionaryBuilder:
    """Baut und verwaltet das RecludOS-Sprachwörterbuch."""
    
    def __init__(self):
        self.dictionary: Dict[str, Dict[str, str]] = {}
        self.scan_stats = {
            "total_items": 0,
            "folders": 0,
            "files": 0,
            "unique_terms": 0,
            "excluded": 0
        }
        self._load_dictionary()
    
    def _load_dictionary(self):
        """Lädt bestehendes Wörterbuch oder erstellt neues."""
        LOCALES_DIR.mkdir(exist_ok=True)
        
        if DICTIONARY_FILE.exists():
            try:
                with open(DICTIONARY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.dictionary = data.get("terms", {})
                    print(f"[OK] Wörterbuch geladen: {len(self.dictionary)} Einträge")
            except Exception as e:
                print(f"[WARN] Fehler beim Laden: {e}")
                self.dictionary = {}
        else:
            print("[INFO] Neues Wörterbuch wird erstellt")
            self.dictionary = {}
    
    def _save_dictionary(self):
        """Speichert Wörterbuch."""
        data = {
            "version": "1.0.0",
            "base_language": "de",
            "supported_languages": list(SUPPORTED_LANGUAGES.keys()),
            "last_updated": datetime.now().isoformat(),
            "stats": {
                "total_terms": len(self.dictionary),
                "fully_translated": sum(
                    1 for t in self.dictionary.values() 
                    if len(t) > 1
                )
            },
            "terms": self.dictionary
        }
        
        with open(DICTIONARY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"[OK] Wörterbuch gespeichert: {len(self.dictionary)} Einträge")
    
    def _should_exclude(self, name: str) -> bool:
        """Prüft ob Name ausgeschlossen werden soll."""
        for pattern in EXCLUDE_PATTERNS:
            if re.search(pattern, name, re.IGNORECASE):
                return True
        return False
    
    def _is_technical(self, term: str) -> bool:
        """Prüft ob Begriff technisch ist."""
        return term.upper() in {t.upper() for t in TECHNICAL_TERMS}
    
    def _extract_terms(self, name: str) -> List[str]:
        """Extrahiert übersetzbare Begriffe aus Name."""
        # Entferne Dateiendung
        name = Path(name).stem if '.' in name else name
        
        # Verschiedene Trennzeichen
        # CamelCase auftrennen
        name = re.sub(r'([a-z])([A-Z])', r'\1_\2', name)
        
        # Trenne an _, -, Leerzeichen
        parts = re.split(r'[_\-\s]+', name)
        
        terms = []
        for part in parts:
            part = part.strip()
            if len(part) < 2:
                continue
            if self._is_technical(part):
                continue
            if part.isdigit():
                continue
            terms.append(part)
        
        return terms
    
    def scan_recludos(self, path: Optional[Path] = None, max_depth: int = 6) -> Dict[str, int]:
        """
        Scannt RecludOS-Verzeichnis und erfasst alle Namen.
        
        Args:
            path: Startpfad (default: RecludOS-Root)
            max_depth: Maximale Tiefe
            
        Returns:
            Dict mit gefundenen Begriffen und Häufigkeit
        """
        if path is None:
            path = RECLUDOS_BASE
        
        print(f"\n[SCAN] Starte Scan von: {path}")
        print(f"       Max. Tiefe: {max_depth}")
        print("-" * 50)
        
        term_frequency: Dict[str, int] = {}
        
        def scan_dir(current_path: Path, depth: int):
            if depth > max_depth:
                return
            
            try:
                for item in current_path.iterdir():
                    name = item.name
                    
                    if self._should_exclude(name):
                        self.scan_stats["excluded"] += 1
                        continue
                    
                    self.scan_stats["total_items"] += 1
                    
                    if item.is_dir():
                        self.scan_stats["folders"] += 1
                        scan_dir(item, depth + 1)
                    else:
                        self.scan_stats["files"] += 1
                    
                    # Begriffe extrahieren
                    terms = self._extract_terms(name)
                    for term in terms:
                        term_lower = term.lower()
                        term_frequency[term_lower] = term_frequency.get(term_lower, 0) + 1
                        
                        # Zum Wörterbuch hinzufügen falls neu
                        if term_lower not in self.dictionary:
                            self.dictionary[term_lower] = {
                                "de": term,  # Original als Deutsch
                                "_source": "scan",
                                "_first_seen": datetime.now().isoformat()
                            }
                            
            except PermissionError:
                pass
            except Exception as e:
                print(f"[WARN] Fehler bei {current_path}: {e}")
        
        scan_dir(path, 0)
        
        self.scan_stats["unique_terms"] = len(term_frequency)
        
        print(f"\n[ERGEBNIS]")
        print(f"  Ordner:           {self.scan_stats['folders']}")
        print(f"  Dateien:          {self.scan_stats['files']}")
        print(f"  Ausgeschlossen:   {self.scan_stats['excluded']}")
        print(f"  Eindeutige Terme: {self.scan_stats['unique_terms']}")
        
        self._save_dictionary()
        
        return term_frequency

    def add_translation(self, term: str, language: str, translation: str) -> bool:
        """
        Fügt Übersetzung für einen Begriff hinzu.
        
        Args:
            term: Deutscher Begriff (Schlüssel)
            language: Zielsprache (z.B. 'en')
            translation: Übersetzung
            
        Returns:
            True bei Erfolg
        """
        term_lower = term.lower()
        
        if language not in SUPPORTED_LANGUAGES:
            print(f"[ERR] Sprache '{language}' nicht unterstützt")
            print(f"      Verfügbar: {', '.join(SUPPORTED_LANGUAGES.keys())}")
            return False
        
        if term_lower not in self.dictionary:
            self.dictionary[term_lower] = {"de": term}
        
        self.dictionary[term_lower][language] = translation
        self.dictionary[term_lower]["_last_modified"] = datetime.now().isoformat()
        
        self._save_dictionary()
        print(f"[OK] {term} ({language}): {translation}")
        return True
    
    def batch_translate(self, translations: List[Tuple[str, str, str]]) -> int:
        """
        Fügt mehrere Übersetzungen hinzu.
        
        Args:
            translations: Liste von (term, language, translation) Tupeln
            
        Returns:
            Anzahl erfolgreicher Übersetzungen
        """
        success = 0
        for term, lang, trans in translations:
            term_lower = term.lower()
            if term_lower not in self.dictionary:
                self.dictionary[term_lower] = {"de": term}
            
            if lang in SUPPORTED_LANGUAGES:
                self.dictionary[term_lower][lang] = trans
                success += 1
        
        self._save_dictionary()
        return success
    
    def get_untranslated(self, language: str) -> List[str]:
        """Gibt alle Begriffe zurück, die in einer Sprache noch fehlen."""
        if language not in SUPPORTED_LANGUAGES:
            return []
        
        untranslated = []
        for term, translations in self.dictionary.items():
            if language not in translations:
                untranslated.append(term)
        
        return sorted(untranslated)
    
    def get_translation(self, term: str, language: str) -> Optional[str]:
        """Holt Übersetzung für einen Begriff."""
        term_lower = term.lower()
        if term_lower in self.dictionary:
            return self.dictionary[term_lower].get(language)
        return None
    
    def export_for_translation(self, language: str, output_file: Optional[Path] = None) -> Path:
        """
        Exportiert unübersetzte Begriffe zur externen Übersetzung.
        
        Args:
            language: Zielsprache
            output_file: Ausgabedatei (optional)
            
        Returns:
            Pfad zur exportierten Datei
        """
        if output_file is None:
            output_file = LOCALES_DIR / f"translate_to_{language}.json"
        
        untranslated = self.get_untranslated(language)
        
        export_data = {
            "target_language": language,
            "target_language_name": SUPPORTED_LANGUAGES.get(language, language),
            "source_language": "de",
            "exported": datetime.now().isoformat(),
            "total_terms": len(untranslated),
            "terms": {
                term: {
                    "de": self.dictionary[term].get("de", term),
                    language: ""  # Zu übersetzen
                }
                for term in untranslated
            }
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"[OK] Exportiert: {len(untranslated)} Begriffe nach {output_file}")
        return output_file
    
    def import_translations(self, input_file: Path) -> int:
        """
        Importiert Übersetzungen aus externer Datei.
        
        Args:
            input_file: Pfad zur Import-Datei
            
        Returns:
            Anzahl importierter Übersetzungen
        """
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        language = data.get("target_language")
        terms = data.get("terms", {})
        
        imported = 0
        for term, translations in terms.items():
            if language in translations and translations[language]:
                self.add_translation(term, language, translations[language])
                imported += 1
        
        return imported
    
    def status(self) -> Dict:
        """Gibt Status-Übersicht zurück."""
        stats = {
            "total_terms": len(self.dictionary),
            "languages": {}
        }
        
        for lang in SUPPORTED_LANGUAGES:
            translated = sum(
                1 for t in self.dictionary.values()
                if lang in t and t[lang]
            )
            stats["languages"][lang] = {
                "name": SUPPORTED_LANGUAGES[lang],
                "translated": translated,
                "missing": len(self.dictionary) - translated,
                "percent": round(translated / max(len(self.dictionary), 1) * 100, 1)
            }
        
        return stats
    
    def print_status(self):
        """Zeigt Status-Übersicht an."""
        stats = self.status()
        
        print("\n" + "=" * 60)
        print("RECLUDOS LANGUAGE DICTIONARY STATUS")
        print("=" * 60)
        print(f"\nGesamt-Begriffe: {stats['total_terms']}")
        print("\nÜbersetzungs-Fortschritt:")
        print("-" * 40)
        
        for lang, data in stats["languages"].items():
            bar_len = int(data["percent"] / 5)
            bar = "[" + "#" * bar_len + "-" * (20 - bar_len) + "]"
            print(f"  {data['name']:12} {bar} {data['percent']:5.1f}% ({data['translated']}/{stats['total_terms']})")
        
        print("=" * 60)


# =============================================================================
# ONLINE TRANSLATION (Vorbereitung)
# =============================================================================

class OnlineTranslator:
    """
    Vorbereitung für Online-Übersetzungs-APIs.
    
    Unterstützte APIs (geplant):
    - DeepL API
    - Google Cloud Translation
    - Microsoft Translator
    - LibreTranslate (Open Source)
    """
    
    def __init__(self, api_key: Optional[str] = None, provider: str = "deepl"):
        self.api_key = api_key
        self.provider = provider
        self.enabled = api_key is not None
    
    def translate(self, text: str, source: str = "de", target: str = "en") -> Optional[str]:
        """
        Übersetzt Text online.
        
        HINWEIS: Noch nicht implementiert - Platzhalter für zukünftige Integration.
        """
        if not self.enabled:
            print("[INFO] Online-Übersetzung nicht konfiguriert")
            print("       Setze API-Key in config.json oder Umgebungsvariable")
            return None
        
        # TODO: Implementiere API-Aufrufe
        # if self.provider == "deepl":
        #     return self._translate_deepl(text, source, target)
        # elif self.provider == "google":
        #     return self._translate_google(text, source, target)
        
        return None
    
    def batch_translate(self, terms: List[str], target: str = "en") -> Dict[str, str]:
        """Batch-Übersetzung mehrerer Begriffe."""
        results = {}
        for term in terms:
            translation = self.translate(term, target=target)
            if translation:
                results[term] = translation
        return results


# =============================================================================
# CLI INTERFACE
# =============================================================================

def print_help():
    """Zeigt Hilfe an."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║          RecludOS Language Dictionary Builder v1.0.0             ║
╚══════════════════════════════════════════════════════════════════╝

VERWENDUNG:
  python dictionary_builder.py <befehl> [optionen]

BEFEHLE:
  scan                    Scannt RecludOS und erfasst alle Namen
  status                  Zeigt Übersetzungs-Fortschritt
  add <term> <lang> <text> Fügt Übersetzung hinzu
  get <term> [lang]       Zeigt Übersetzung(en) für Begriff
  missing <lang>          Zeigt fehlende Übersetzungen
  export <lang>           Exportiert unübersetzte Begriffe
  import <datei>          Importiert Übersetzungen
  help                    Diese Hilfe

SPRACHEN:
  de  Deutsch (Basis)     en  English
  fr  Français            es  Español
  it  Italiano            pt  Português
  nl  Nederlands          pl  Polski
  ru  Русский             zh  中文
  ja  日本語

BEISPIELE:
  python dictionary_builder.py scan
  python dictionary_builder.py add system en System
  python dictionary_builder.py export en
  python dictionary_builder.py missing en

DATEIEN:
  locales/dictionary.json     Hauptwörterbuch
  locales/translate_to_*.json Export-Dateien
""")


def main():
    """CLI-Haupteinstiegspunkt."""
    builder = DictionaryBuilder()
    
    if len(sys.argv) < 2:
        print_help()
        return
    
    cmd = sys.argv[1].lower()
    
    # === SCAN ===
    if cmd == "scan":
        path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
        depth = int(sys.argv[3]) if len(sys.argv) > 3 else 6
        
        freq = builder.scan_recludos(path, depth)
        
        # Top 20 häufigste Begriffe
        print("\nTop 20 häufigste Begriffe:")
        print("-" * 30)
        sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:20]
        for term, count in sorted_freq:
            print(f"  {term:20} {count:4}x")
    
    # === STATUS ===
    elif cmd == "status":
        builder.print_status()
    
    # === ADD ===
    elif cmd == "add":
        if len(sys.argv) < 5:
            print("Verwendung: add <term> <sprache> <übersetzung>")
            print("Beispiel:   add system en System")
            return
        
        term = sys.argv[2]
        lang = sys.argv[3]
        translation = " ".join(sys.argv[4:])
        builder.add_translation(term, lang, translation)
    
    # === GET ===
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Verwendung: get <term> [sprache]")
            return
        
        term = sys.argv[2].lower()
        lang = sys.argv[3] if len(sys.argv) > 3 else None
        
        if term in builder.dictionary:
            entry = builder.dictionary[term]
            print(f"\nÜbersetzungen für '{term}':")
            print("-" * 30)
            
            for key, value in entry.items():
                if key.startswith("_"):
                    continue
                if lang and key != lang:
                    continue
                lang_name = SUPPORTED_LANGUAGES.get(key, key)
                print(f"  {lang_name:12}: {value}")
        else:
            print(f"[INFO] Begriff '{term}' nicht im Wörterbuch")
    
    # === MISSING ===
    elif cmd == "missing":
        if len(sys.argv) < 3:
            print("Verwendung: missing <sprache>")
            print("Beispiel:   missing en")
            return
        
        lang = sys.argv[2]
        missing = builder.get_untranslated(lang)
        
        print(f"\nFehlende Übersetzungen für {SUPPORTED_LANGUAGES.get(lang, lang)}:")
        print(f"Gesamt: {len(missing)}")
        print("-" * 40)
        
        # Zeige erste 50
        for term in missing[:50]:
            de_term = builder.dictionary[term].get("de", term)
            print(f"  {de_term}")
        
        if len(missing) > 50:
            print(f"\n  ... und {len(missing) - 50} weitere")
    
    # === EXPORT ===
    elif cmd == "export":
        if len(sys.argv) < 3:
            print("Verwendung: export <sprache>")
            return
        
        lang = sys.argv[2]
        output = Path(sys.argv[3]) if len(sys.argv) > 3 else None
        builder.export_for_translation(lang, output)
    
    # === IMPORT ===
    elif cmd == "import":
        if len(sys.argv) < 3:
            print("Verwendung: import <datei>")
            return
        
        input_file = Path(sys.argv[2])
        if not input_file.exists():
            print(f"[ERR] Datei nicht gefunden: {input_file}")
            return
        
        count = builder.import_translations(input_file)
        print(f"[OK] {count} Übersetzungen importiert")
    
    # === HELP ===
    elif cmd in ["help", "-h", "--help", "?"]:
        print_help()
    
    else:
        print(f"[ERR] Unbekannter Befehl: {cmd}")
        print("      Verwende 'help' für Hilfe")


if __name__ == "__main__":
    main()
