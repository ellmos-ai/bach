#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
LangHandler - Mehrsprachigkeit und Uebersetzungs-Verwaltung
============================================================

CLI-Befehle:
  bach lang status           Sprachkonfiguration anzeigen
  bach lang scan             Code nach deutschen Strings durchsuchen
  bach lang list             Alle Uebersetzungen anzeigen
  bach lang missing          Fehlende Uebersetzungen anzeigen
  bach lang translate        Auto-Uebersetzung starten
  bach lang add <key>        Manuell Uebersetzung hinzufuegen
  bach lang export           Fuer LLM-Review exportieren
  bach lang import           LLM-Review importieren
  bach lang set <lang>       Standard-Sprache setzen (de/en)
  bach lang help             Hilfe anzeigen

Nutzt: bach.db / languages_config, languages_translations, languages_dictionary
"""

import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Set
from hub.base import BaseHandler


class LangHandler(BaseHandler):
    """Handler fuer Mehrsprachigkeit und Uebersetzungen."""

    # Quellen-Prioritaet (hoeher = vertrauenswuerdiger)
    SOURCE_PRIORITY = {
        'manual': 100,        # Manuell verifiziert
        'llm_reviewed': 80,   # LLM-korrigiert
        'llm_auto': 60,       # LLM-automatisch
        'google_auto': 40,    # Google Translate
        'windows_dict': 20,   # Windows/System Dictionary
        'auto_detected': 10,  # Automatisch erkannt (unuebersetzt)
    }

    # Patterns fuer String-Erkennung
    STRING_PATTERNS = [
        # Python print/return Statements
        re.compile(r'print\s*\(\s*f?["\']([^"\']+)["\']'),
        re.compile(r'return\s*\(\s*(?:True|False)\s*,\s*f?["\']([^"\']+)["\']'),
        re.compile(r'return\s*f?["\']([^"\']+)["\']'),
        # GUI/Qt Patterns
        re.compile(r'setText\s*\(\s*["\']([^"\']+)["\']'),
        re.compile(r'setWindowTitle\s*\(\s*["\']([^"\']+)["\']'),
        re.compile(r'QLabel\s*\(\s*["\']([^"\']+)["\']'),
        re.compile(r'QPushButton\s*\(\s*["\']([^"\']+)["\']'),
        # Help-Texte
        re.compile(r'"""([^"]{20,})"""', re.DOTALL),
        re.compile(r"'''([^']{20,})'''", re.DOTALL),
    ]

    # Deutsche Hinweis-Woerter
    GERMAN_HINTS = [
        "fehler", "warnung", "erfolg", "hinweis", "achtung",
        "datei", "ordner", "speichern", "laden", "oeffnen",
        "bearbeiten", "loeschen", "hinzufuegen", "aendern",
        "anzeigen", "suchen", "filtern", "sortieren",
        "einstellungen", "optionen", "konfiguration",
        "abbrechen", "bestaetigen", "weiter", "zurueck",
        "status", "uebersicht", "details", "hilfe",
        "erstellt", "aktualisiert", "geloescht", "gefunden",
        "verfuegbar", "nicht gefunden", "ungueltig", "erforderlich"
    ]

    def __init__(self, base_path: Path):
        super().__init__(base_path)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "lang"

    @property
    def target_file(self) -> Path:
        return self.db_path

    # Basis-Woerterbuch DE->EN (haeufige UI-Begriffe)
    BASE_DICTIONARY = {
        # Aktionen
        "speichern": "save", "laden": "load", "oeffnen": "open", "schliessen": "close",
        "erstellen": "create", "loeschen": "delete", "bearbeiten": "edit", "aendern": "change",
        "hinzufuegen": "add", "entfernen": "remove", "kopieren": "copy", "einfuegen": "paste",
        "suchen": "search", "finden": "find", "filtern": "filter", "sortieren": "sort",
        "aktualisieren": "update", "abbrechen": "cancel", "bestaetigen": "confirm",
        "starten": "start", "stoppen": "stop", "fortsetzen": "continue", "pausieren": "pause",
        "exportieren": "export", "importieren": "import", "sichern": "backup",
        # Status
        "erfolg": "success", "fehler": "error", "warnung": "warning", "hinweis": "notice",
        "fertig": "done", "bereit": "ready", "aktiv": "active", "inaktiv": "inactive",
        "geladen": "loaded", "gespeichert": "saved", "geloescht": "deleted",
        "gefunden": "found", "nicht gefunden": "not found", "leer": "empty",
        "gueltig": "valid", "ungueltig": "invalid", "erforderlich": "required",
        "ausstehend": "pending", "abgeschlossen": "completed", "fehlgeschlagen": "failed",
        # Navigation
        "weiter": "next", "zurueck": "back", "anfang": "start", "ende": "end",
        "hoch": "up", "runter": "down", "links": "left", "rechts": "right",
        "alle": "all", "keine": "none", "mehr": "more", "weniger": "less",
        # Objekte
        "datei": "file", "ordner": "folder", "dokument": "document", "bild": "image",
        "eintrag": "entry", "liste": "list", "tabelle": "table", "ansicht": "view",
        "einstellungen": "settings", "optionen": "options", "konfiguration": "configuration",
        "hilfe": "help", "info": "info", "uebersicht": "overview", "details": "details",
        "benutzer": "user", "profil": "profile", "konto": "account",
        "aufgabe": "task", "termin": "appointment", "notiz": "note", "nachricht": "message",
        # Zeit
        "heute": "today", "gestern": "yesterday", "morgen": "tomorrow",
        "woche": "week", "monat": "month", "jahr": "year", "tag": "day",
        "stunde": "hour", "minute": "minute", "sekunde": "second",
        # Zahlen/Mengen
        "anzahl": "count", "summe": "sum", "durchschnitt": "average",
        "minimum": "minimum", "maximum": "maximum", "gesamt": "total",
        # UI-Elemente
        "fenster": "window", "dialog": "dialog", "menue": "menu", "schaltflaeche": "button",
        "eingabe": "input", "ausgabe": "output", "auswahl": "selection",
        # System
        "system": "system", "programm": "program", "anwendung": "application",
        "version": "version", "update": "update", "neustart": "restart",
        "verbindung": "connection", "netzwerk": "network", "datenbank": "database",
        # BACH-spezifisch
        "task": "task", "backup": "backup", "daemon": "daemon", "handler": "handler",
        "skill": "skill", "agent": "agent", "workflow": "workflow",
    }

    def get_operations(self) -> dict:
        return {
            "status": "Sprachkonfiguration anzeigen",
            "scan": "Code nach deutschen Strings durchsuchen",
            "list": "Alle Uebersetzungen anzeigen",
            "missing": "Fehlende Uebersetzungen anzeigen",
            "translate": "Auto-Uebersetzung starten",
            "add": "Manuell Uebersetzung hinzufuegen",
            "add-language": "Neue Sprache hinzufuegen",
            "export": "Fuer LLM-Review exportieren",
            "import": "LLM-Review importieren",
            "set": "Standard-Sprache setzen",
            "dict": "Woerterbuch verwalten",
            "help": "Hilfe anzeigen",
        }

    def _get_db(self):
        """Verbindung zur Datenbank."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "help" or not operation:
            return self._show_help()
        elif operation == "status":
            return self._status()
        elif operation == "scan":
            return self._scan(args, dry_run)
        elif operation == "list":
            return self._list(args)
        elif operation == "missing":
            return self._missing(args)
        elif operation == "translate":
            return self._translate(args, dry_run)
        elif operation == "add":
            return self._add(args, dry_run)
        elif operation == "add-language":
            return self._add_language(args, dry_run)
        elif operation == "export":
            return self._export(args)
        elif operation == "import":
            return self._import_translations(args, dry_run)
        elif operation == "set":
            return self._set_language(args, dry_run)
        elif operation == "dict":
            return self._dict(args, dry_run)
        else:
            return (False, f"Unbekannte Operation: {operation}\nVerfuegbar: {', '.join(self.get_operations().keys())}")

    def _show_help(self) -> tuple:
        """Zeigt Hilfe an."""
        return (True, """LANG - Mehrsprachigkeit & Uebersetzungen
========================================

BEFEHLE:
  bach lang status                 Sprachkonfiguration anzeigen
  bach lang scan                   Code nach deutschen Strings durchsuchen
  bach lang scan --namespace cli   Nur bestimmten Bereich scannen
  bach lang list                   Alle Uebersetzungen anzeigen
  bach lang list --lang en         Nur englische Uebersetzungen
  bach lang missing                Fehlende Uebersetzungen anzeigen
  bach lang translate              Auto-Uebersetzung starten
  bach lang translate --source windows_dict   Mit Windows-Woerterbuch
  bach lang translate --source llm            Mit LLM (erfordert Prompt)
  bach lang add <key> --de "Text" --en "Text" Manuell hinzufuegen
  bach lang add-language <code>    Neue Sprache hinzufuegen (z.B. fr, es, pt)
  bach lang export                 Fuer LLM-Review exportieren
  bach lang export --format json   Als JSON exportieren
  bach lang import <datei>         LLM-Review importieren
  bach lang set de                 Standard-Sprache auf Deutsch
  bach lang set en                 Standard-Sprache auf Englisch

WOERTERBUCH:
  bach lang dict status            Woerterbuch-Status
  bach lang dict init              Basis-Woerterbuch (119 Begriffe) laden
  bach lang dict add <de> <en>     Begriff hinzufuegen
  bach lang dict search <term>     Begriff suchen

NAMESPACES:
  cli      - CLI-Ausgaben (Handler, bach.py)
  gui      - GUI-Texte (server.py, Templates)
  help     - Help-Dateien
  skills   - Skill/Agent-Beschreibungen
  errors   - Fehlermeldungen
  general  - Allgemeine Texte

QUELLEN (Prioritaet):
  manual (100)       - Manuell verifiziert
  llm_reviewed (80)  - LLM-korrigiert
  llm_auto (60)      - LLM-automatisch
  google_auto (40)   - Google Translate
  windows_dict (20)  - System-Woerterbuch
  auto_detected (10) - Nur erkannt, nicht uebersetzt

DATENBANK: bach.db / languages_config, languages_translations, languages_dictionary""")

    def _status(self) -> tuple:
        """Zeigt Sprachkonfiguration und Statistiken."""
        conn = self._get_db()
        try:
            # Config laden
            config = conn.execute("SELECT * FROM languages_config LIMIT 1").fetchone()

            # Statistiken
            total = conn.execute("SELECT COUNT(*) FROM languages_translations").fetchone()[0]
            verified = conn.execute("SELECT COUNT(*) FROM languages_translations WHERE is_verified = 1").fetchone()[0]

            # Nach Sprache
            by_lang = conn.execute("""
                SELECT language, COUNT(*) as cnt
                FROM languages_translations
                GROUP BY language
            """).fetchall()

            # Nach Namespace
            by_ns = conn.execute("""
                SELECT namespace, COUNT(*) as cnt
                FROM languages_translations
                GROUP BY namespace
                ORDER BY cnt DESC
            """).fetchall()

            # Nach Quelle
            by_source = conn.execute("""
                SELECT source, COUNT(*) as cnt
                FROM languages_translations
                GROUP BY source
                ORDER BY cnt DESC
            """).fetchall()

            # Fehlende Uebersetzungen
            # Keys die in 'de' existieren aber nicht in 'en'
            missing = conn.execute("""
                SELECT COUNT(DISTINCT t1.key)
                FROM languages_translations t1
                WHERE t1.language = 'de'
                AND NOT EXISTS (
                    SELECT 1 FROM languages_translations t2
                    WHERE t2.key = t1.key AND t2.language = 'en' AND t2.value != ''
                )
            """).fetchone()[0]

            # Woerterbuch
            dict_count = conn.execute("SELECT COUNT(*) FROM languages_dictionary").fetchone()[0]

            output = [
                "=== SPRACH-SYSTEM STATUS ===",
                "",
                "Konfiguration:",
                f"  Standard-Sprache:  {config['default_language'] if config else 'de'}",
                f"  Fallback-Sprache:  {config['fallback_language'] if config else 'en'}",
                f"  Auto-Translate:    {'Ja' if config and config['auto_translate'] else 'Nein'}",
                "",
                "Statistiken:",
                f"  Gesamt-Eintraege:  {total}",
                f"  Verifiziert:       {verified}",
                f"  Fehlende (en):     {missing}",
                f"  Woerterbuch:       {dict_count} Eintraege",
                "",
            ]

            if by_lang:
                output.append("Nach Sprache:")
                for row in by_lang:
                    output.append(f"  {row['language']}: {row['cnt']}")
                output.append("")

            if by_ns:
                output.append("Nach Namespace:")
                for row in by_ns[:5]:
                    output.append(f"  {row['namespace'] or 'general'}: {row['cnt']}")
                output.append("")

            if by_source:
                output.append("Nach Quelle:")
                for row in by_source:
                    prio = self.SOURCE_PRIORITY.get(row['source'], 0)
                    output.append(f"  {row['source'] or 'unknown'} ({prio}): {row['cnt']}")

            return (True, "\n".join(output))

        except Exception as e:
            return (False, f"[ERROR] {e}")
        finally:
            conn.close()

    def _scan(self, args: list, dry_run: bool) -> tuple:
        """Scannt Code nach deutschen Strings."""
        namespace_filter = self._get_arg(args, "--namespace") or self._get_arg(args, "-n")

        # Scan-Verzeichnisse nach Namespace
        scan_dirs = {
            'cli': [self.base_path / "hub"],
            'gui': [self.base_path / "gui"],
            'help': [self.base_path / "help"],
            'skills': [
                self.base_path / "skills" / "_agents",
                self.base_path / "skills" / "_experts",
                self.base_path / "skills" / "_workflows",
            ],
            'tools': [self.base_path / "skills" / "tools"],
        }

        if namespace_filter and namespace_filter in scan_dirs:
            dirs_to_scan = {namespace_filter: scan_dirs[namespace_filter]}
        else:
            dirs_to_scan = scan_dirs

        found_strings: Dict[str, Set[str]] = {}  # namespace -> set of strings

        for namespace, dirs in dirs_to_scan.items():
            found_strings[namespace] = set()
            for scan_dir in dirs:
                if not scan_dir.exists():
                    continue

                # Python-Dateien scannen
                for py_file in scan_dir.rglob("*.py"):
                    if "__pycache__" in str(py_file) or "_archive" in str(py_file):
                        continue
                    strings = self._extract_german_strings(py_file)
                    found_strings[namespace].update(strings)

                # Help/Txt-Dateien scannen
                for txt_file in scan_dir.rglob("*.txt"):
                    if "_archive" in str(txt_file):
                        continue
                    # Bei Help-Dateien: Titel und Abschnitte extrahieren
                    strings = self._extract_help_strings(txt_file)
                    found_strings[namespace].update(strings)

        # In DB einfuegen (wenn nicht dry_run)
        total_found = sum(len(s) for s in found_strings.values())
        added = 0

        if not dry_run and total_found > 0:
            conn = self._get_db()
            try:
                for namespace, strings in found_strings.items():
                    for string in strings:
                        # Pruefe ob bereits existiert
                        existing = conn.execute(
                            "SELECT id FROM languages_translations WHERE key = ? AND language = 'de'",
                            (self._make_key(string),)
                        ).fetchone()

                        if not existing:
                            conn.execute("""
                                INSERT INTO languages_translations
                                (key, namespace, language, value, is_verified, source, created_at)
                                VALUES (?, ?, 'de', ?, 0, 'auto_detected', ?)
                            """, (
                                self._make_key(string),
                                namespace,
                                string,
                                datetime.now().isoformat()
                            ))
                            added += 1

                conn.commit()
            finally:
                conn.close()

        # Report
        output = [
            "=== STRING-SCAN ERGEBNIS ===",
            "",
            f"Gefunden: {total_found} deutsche Strings",
            f"Neu hinzugefuegt: {added}" if not dry_run else "[DRY-RUN] Wuerde hinzufuegen: {0}".format(total_found),
            "",
            "Nach Namespace:",
        ]

        for ns, strings in found_strings.items():
            output.append(f"  {ns}: {len(strings)}")
            # Beispiele zeigen
            for s in list(strings)[:3]:
                short = s[:50] + "..." if len(s) > 50 else s
                output.append(f"    - {short}")

        return (True, "\n".join(output))

    def _extract_german_strings(self, file_path: Path) -> Set[str]:
        """Extrahiert deutsche Strings aus einer Python-Datei."""
        strings = set()
        try:
            content = file_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return strings

        for pattern in self.STRING_PATTERNS:
            for match in pattern.findall(content):
                if self._is_german(match):
                    # Bereinigen
                    clean = match.strip()
                    if len(clean) >= 3 and len(clean) <= 500:  # Sinnvolle Laenge
                        strings.add(clean)

        return strings

    def _extract_help_strings(self, file_path: Path) -> Set[str]:
        """Extrahiert uebersetzbare Strings aus Help-Dateien."""
        strings = set()
        try:
            content = file_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return strings

        # Titel (erste Zeile)
        lines = content.split('\n')
        if lines and self._is_german(lines[0]):
            strings.add(lines[0].strip())

        # Abschnitt-Titel (Zeilen mit === oder ---)
        for i, line in enumerate(lines):
            if i > 0 and (line.startswith('===') or line.startswith('---')):
                if i > 0 and self._is_german(lines[i-1]):
                    strings.add(lines[i-1].strip())

        return strings

    def _is_german(self, text: str) -> bool:
        """Prueft ob Text wahrscheinlich deutsch ist."""
        if not text or len(text) < 3:
            return False

        # Umlaute
        if any(ch in text for ch in "äöüÄÖÜß"):
            return True

        # Deutsche Keywords
        text_lower = text.lower()
        if any(hint in text_lower for hint in self.GERMAN_HINTS):
            return True

        return False

    def _make_key(self, text: str) -> str:
        """Erstellt einen Key aus dem Text."""
        # Ersten 50 Zeichen, lowercase, Sonderzeichen ersetzen
        key = text[:50].lower()
        key = re.sub(r'[^a-z0-9_]', '_', key)
        key = re.sub(r'_+', '_', key)
        return key.strip('_')

    def _list(self, args: list) -> tuple:
        """Listet alle Uebersetzungen."""
        lang_filter = self._get_arg(args, "--lang") or self._get_arg(args, "-l")
        ns_filter = self._get_arg(args, "--namespace") or self._get_arg(args, "-n")
        limit = int(self._get_arg(args, "--limit") or "50")

        conn = self._get_db()
        try:
            query = "SELECT * FROM languages_translations WHERE 1=1"
            params = []

            if lang_filter:
                query += " AND language = ?"
                params.append(lang_filter)

            if ns_filter:
                query += " AND namespace = ?"
                params.append(ns_filter)

            query += " ORDER BY namespace, key LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

            if not rows:
                return (True, "[LANG] Keine Uebersetzungen gefunden.")

            output = [f"[LANG] {len(rows)} Uebersetzung(en):", ""]

            current_ns = None
            for r in rows:
                ns = r['namespace'] or 'general'
                if ns != current_ns:
                    current_ns = ns
                    output.append(f"  [{ns.upper()}]")

                verified = "✓" if r['is_verified'] else " "
                value_short = (r['value'] or "")[:40]
                if len(r['value'] or "") > 40:
                    value_short += "..."

                output.append(f"    [{verified}] {r['key'][:25]:<25} ({r['language']}) {value_short}")

            return (True, "\n".join(output))

        finally:
            conn.close()

    def _missing(self, args: list) -> tuple:
        """Zeigt fehlende Uebersetzungen."""
        conn = self._get_db()
        try:
            # Keys die in 'de' existieren aber nicht in 'en'
            rows = conn.execute("""
                SELECT t1.key, t1.namespace, t1.value as de_value
                FROM languages_translations t1
                WHERE t1.language = 'de'
                AND NOT EXISTS (
                    SELECT 1 FROM languages_translations t2
                    WHERE t2.key = t1.key AND t2.language = 'en' AND t2.value != ''
                )
                ORDER BY t1.namespace, t1.key
                LIMIT 100
            """).fetchall()

            if not rows:
                return (True, "[LANG] Alle Strings haben englische Uebersetzungen!")

            output = [
                f"[LANG] {len(rows)} fehlende englische Uebersetzung(en):",
                "",
            ]

            current_ns = None
            for r in rows:
                ns = r['namespace'] or 'general'
                if ns != current_ns:
                    current_ns = ns
                    output.append(f"  [{ns.upper()}]")

                de_short = (r['de_value'] or "")[:50]
                output.append(f"    {r['key'][:25]:<25} = {de_short}")

            output.append("")
            output.append("Naechste Schritte:")
            output.append("  bach lang translate --source windows_dict   Auto-Uebersetzen")
            output.append("  bach lang export                            Fuer LLM-Review")

            return (True, "\n".join(output))

        finally:
            conn.close()

    def _translate(self, args: list, dry_run: bool) -> tuple:
        """Startet Auto-Uebersetzung."""
        source = self._get_arg(args, "--source") or "windows_dict"
        limit = int(self._get_arg(args, "--limit") or "100")

        if source not in self.SOURCE_PRIORITY:
            return (False, f"[ERROR] Unbekannte Quelle: {source}\nVerfuegbar: {', '.join(self.SOURCE_PRIORITY.keys())}")

        conn = self._get_db()
        try:
            # Fehlende Uebersetzungen holen
            rows = conn.execute("""
                SELECT t1.id, t1.key, t1.namespace, t1.value as de_value
                FROM languages_translations t1
                WHERE t1.language = 'de'
                AND NOT EXISTS (
                    SELECT 1 FROM languages_translations t2
                    WHERE t2.key = t1.key AND t2.language = 'en' AND t2.value != ''
                )
                LIMIT ?
            """, (limit,)).fetchall()

            if not rows:
                return (True, "[LANG] Keine fehlenden Uebersetzungen gefunden.")

            translated = 0
            skipped = 0

            for r in rows:
                de_text = r['de_value']
                en_text = None

                if source == "windows_dict":
                    # Versuche einfache Woerterbuch-Uebersetzung
                    en_text = self._translate_with_dict(de_text, conn)
                elif source == "llm":
                    # LLM-Uebersetzung wird als Batch exportiert
                    skipped += 1
                    continue

                if en_text and not dry_run:
                    # Einfuegen
                    conn.execute("""
                        INSERT INTO languages_translations
                        (key, namespace, language, value, is_verified, source, created_at)
                        VALUES (?, ?, 'en', ?, 0, ?, ?)
                    """, (
                        r['key'],
                        r['namespace'],
                        en_text,
                        source,
                        datetime.now().isoformat()
                    ))
                    translated += 1
                elif en_text:
                    translated += 1  # Dry-run count
                else:
                    skipped += 1

            if not dry_run:
                conn.commit()

            prefix = "[DRY-RUN] " if dry_run else ""
            return (True, f"{prefix}[LANG] Uebersetzung abgeschlossen:\n  Uebersetzt: {translated}\n  Uebersprungen: {skipped}\n  Quelle: {source}")

        finally:
            conn.close()

    def _translate_with_dict(self, de_text: str, conn) -> Optional[str]:
        """Versucht Uebersetzung mit Woerterbuch."""
        # Zuerst im eigenen Woerterbuch suchen
        row = conn.execute("""
            SELECT translation FROM languages_dictionary
            WHERE term = ? AND source_lang = 'de' AND target_lang = 'en'
            AND is_preferred = 1
            ORDER BY usage_count DESC LIMIT 1
        """, (de_text.lower(),)).fetchone()

        if row:
            return row['translation']

        # Fallback: Wort-fuer-Wort fuer einfache Texte
        # (Nur fuer sehr kurze, einfache Strings)
        if len(de_text) < 30 and ' ' not in de_text:
            word_row = conn.execute("""
                SELECT translation FROM languages_dictionary
                WHERE term = ? AND source_lang = 'de' AND target_lang = 'en'
                ORDER BY usage_count DESC LIMIT 1
            """, (de_text.lower(),)).fetchone()

            if word_row:
                return word_row['translation']

        return None

    def _add(self, args: list, dry_run: bool) -> tuple:
        """Fuegt manuell eine Uebersetzung hinzu."""
        if not args:
            return (False, "Fehler: Key fehlt.\n\nBeispiel: bach lang add mein_key --de \"Mein Text\" --en \"My text\"")

        key = args[0]
        de_text = self._get_arg(args, "--de")
        en_text = self._get_arg(args, "--en")
        namespace = self._get_arg(args, "--namespace") or self._get_arg(args, "-n") or "general"

        if not de_text and not en_text:
            return (False, "Fehler: Mindestens --de oder --en muss angegeben werden.")

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde hinzufuegen:\n  Key: {key}\n  DE: {de_text}\n  EN: {en_text}")

        conn = self._get_db()
        try:
            now = datetime.now().isoformat()

            if de_text:
                # Deutsche Version
                conn.execute("""
                    INSERT OR REPLACE INTO languages_translations
                    (key, namespace, language, value, is_verified, source, created_at, updated_at)
                    VALUES (?, ?, 'de', ?, 1, 'manual', ?, ?)
                """, (key, namespace, de_text, now, now))

            if en_text:
                # Englische Version
                conn.execute("""
                    INSERT OR REPLACE INTO languages_translations
                    (key, namespace, language, value, is_verified, source, created_at, updated_at)
                    VALUES (?, ?, 'en', ?, 1, 'manual', ?, ?)
                """, (key, namespace, en_text, now, now))

            conn.commit()
            return (True, f"[OK] Uebersetzung hinzugefuegt: {key}")

        finally:
            conn.close()

    def _add_language(self, args: list, dry_run: bool) -> tuple:
        """Fuegt eine neue Sprache zum System hinzu."""
        if not args:
            return (False, "Fehler: Sprach-Code fehlt.\n\nBeispiel: bach lang add-language fr")

        lang_code = args[0].lower().strip()

        # Validierung: 2-3 Buchstaben
        if not re.match(r'^[a-z]{2,3}$', lang_code):
            return (False, f"[ERROR] Ungueltiger Sprach-Code: {lang_code}\nErwartet: 2-3 Kleinbuchstaben (z.B. fr, es, pt)")

        conn = self._get_db()
        try:
            # Aktuell aktivierte Sprachen holen
            row = conn.execute("SELECT enabled_languages FROM languages_config LIMIT 1").fetchone()
            if not row:
                # Config existiert nicht -> initialisieren
                enabled_langs = ["de", "en"]
            else:
                enabled_langs = json.loads(row[0]) if row[0] else ["de", "en"]

            # Pruefen ob bereits vorhanden
            if lang_code in enabled_langs:
                return (False, f"[ERROR] Sprache '{lang_code}' ist bereits aktiviert.\nAktiv: {', '.join(enabled_langs)}")

            # Hinzufuegen
            enabled_langs.append(lang_code)

            if dry_run:
                return (True, f"[DRY-RUN] Wuerde Sprache hinzufuegen: {lang_code}\nNeue Liste: {', '.join(enabled_langs)}")

            # In DB speichern
            conn.execute("""
                UPDATE languages_config
                SET enabled_languages = ?, updated_at = ?
                WHERE id = 1
            """, (json.dumps(enabled_langs), datetime.now().isoformat()))

            # Falls Config noch nicht existiert, erstellen
            if conn.total_changes == 0:
                conn.execute("""
                    INSERT INTO languages_config (id, enabled_languages, updated_at)
                    VALUES (1, ?, ?)
                """, (json.dumps(enabled_langs), datetime.now().isoformat()))

            conn.commit()
            return (True, f"[OK] Sprache hinzugefuegt: {lang_code}\nAktivierte Sprachen: {', '.join(enabled_langs)}")

        except json.JSONDecodeError as e:
            return (False, f"[ERROR] enabled_languages JSON kaputt: {e}")
        finally:
            conn.close()

    def _export(self, args: list) -> tuple:
        """Exportiert fehlende Uebersetzungen fuer LLM-Review."""
        format_type = self._get_arg(args, "--format") or "prompt"
        output_file = self._get_arg(args, "--file")

        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT t1.key, t1.namespace, t1.value as de_value
                FROM languages_translations t1
                WHERE t1.language = 'de'
                AND NOT EXISTS (
                    SELECT 1 FROM languages_translations t2
                    WHERE t2.key = t1.key AND t2.language = 'en' AND t2.value != ''
                )
                ORDER BY t1.namespace, t1.key
            """).fetchall()

            if not rows:
                return (True, "[LANG] Keine fehlenden Uebersetzungen zum Exportieren.")

            if format_type == "json":
                # JSON-Format
                export_data = []
                for r in rows:
                    export_data.append({
                        "key": r['key'],
                        "namespace": r['namespace'],
                        "de": r['de_value'],
                        "en": ""
                    })
                output = json.dumps(export_data, indent=2, ensure_ascii=False)
            else:
                # Prompt-Format fuer LLM
                output_lines = [
                    "# BACH Translation Request",
                    "",
                    "Bitte uebersetze die folgenden deutschen Texte ins Englische.",
                    "Behalte technische Begriffe (CLI-Befehle, Variablen) bei.",
                    "Format: KEY | DEUTSCH | ENGLISCH",
                    "",
                    "---",
                    ""
                ]

                for r in rows:
                    de_clean = r['de_value'].replace('\n', ' ')[:100]
                    output_lines.append(f"{r['key']} | {de_clean} | ")

                output_lines.extend([
                    "",
                    "---",
                    "",
                    "Bitte fuege die englischen Uebersetzungen nach dem letzten | ein.",
                    "Importiere dann mit: bach lang import <datei>"
                ])
                output = "\n".join(output_lines)

            # In Datei speichern oder ausgeben
            if output_file:
                Path(output_file).write_text(output, encoding='utf-8')
                return (True, f"[EXPORT] {len(rows)} Eintraege exportiert nach: {output_file}")
            else:
                return (True, output)

        finally:
            conn.close()

    def _import_translations(self, args: list, dry_run: bool) -> tuple:
        """Importiert LLM-Review Uebersetzungen."""
        if not args:
            return (False, "Fehler: Datei fehlt.\n\nBeispiel: bach lang import translations.json")

        file_path = Path(args[0])
        if not file_path.exists():
            return (False, f"[ERROR] Datei nicht gefunden: {file_path}")

        content = file_path.read_text(encoding='utf-8')

        imported = 0
        errors = 0

        conn = self._get_db()
        try:
            # Versuche JSON
            if file_path.suffix == '.json' or content.strip().startswith('['):
                data = json.loads(content)
                for item in data:
                    if item.get('en'):
                        if not dry_run:
                            conn.execute("""
                                INSERT OR REPLACE INTO languages_translations
                                (key, namespace, language, value, is_verified, source, created_at, updated_at)
                                VALUES (?, ?, 'en', ?, 0, 'llm_reviewed', ?, ?)
                            """, (
                                item['key'],
                                item.get('namespace', 'general'),
                                item['en'],
                                datetime.now().isoformat(),
                                datetime.now().isoformat()
                            ))
                        imported += 1
            else:
                # Pipe-Format (KEY | DE | EN)
                for line in content.split('\n'):
                    if '|' in line and not line.startswith('#') and not line.startswith('-'):
                        parts = [p.strip() for p in line.split('|')]
                        if len(parts) >= 3 and parts[2]:  # Hat englische Uebersetzung
                            key = parts[0]
                            en_text = parts[2]

                            # Namespace aus existierendem DE-Eintrag holen
                            ns_row = conn.execute("""
                                SELECT namespace FROM languages_translations
                                WHERE key = ? AND language = 'de' LIMIT 1
                            """, (key,)).fetchone()
                            namespace = ns_row['namespace'] if ns_row else 'general'

                            if not dry_run:
                                conn.execute("""
                                    INSERT OR REPLACE INTO languages_translations
                                    (key, namespace, language, value, is_verified, source, created_at, updated_at)
                                    VALUES (?, ?, 'en', ?, 0, 'llm_reviewed', ?, ?)
                                """, (key, namespace, en_text, datetime.now().isoformat(), datetime.now().isoformat()))
                            imported += 1

            if not dry_run:
                conn.commit()

            prefix = "[DRY-RUN] " if dry_run else ""
            return (True, f"{prefix}[IMPORT] {imported} Uebersetzungen importiert")

        except json.JSONDecodeError as e:
            return (False, f"[ERROR] JSON-Parsing fehlgeschlagen: {e}")
        except Exception as e:
            return (False, f"[ERROR] Import fehlgeschlagen: {e}")
        finally:
            conn.close()

    def _set_language(self, args: list, dry_run: bool) -> tuple:
        """Setzt die Standard-Sprache."""
        if not args:
            return (False, "Fehler: Sprache fehlt.\n\nBeispiel: bach lang set en")

        lang = args[0].lower()

        conn = self._get_db()
        try:
            # Aktivierte Sprachen holen
            row = conn.execute("SELECT enabled_languages FROM languages_config LIMIT 1").fetchone()
            if not row or not row[0]:
                enabled_langs = ["de", "en"]
            else:
                enabled_langs = json.loads(row[0])

            # Validierung gegen aktivierte Sprachen
            if lang not in enabled_langs:
                return (False, f"[ERROR] Ungueltige Sprache: {lang}\nAktivierte Sprachen: {', '.join(enabled_langs)}\n\nHinzufuegen mit: bach lang add-language {lang}")

            if dry_run:
                return (True, f"[DRY-RUN] Wuerde Standard-Sprache setzen: {lang}")

            conn.execute("""
                UPDATE languages_config SET default_language = ?, updated_at = ?
            """, (lang, datetime.now().isoformat()))
            conn.commit()

            # Cache leeren
            clear_t_cache()

            return (True, f"[OK] Standard-Sprache gesetzt: {lang}")

        except json.JSONDecodeError as e:
            return (False, f"[ERROR] enabled_languages JSON kaputt: {e}")
        finally:
            conn.close()

    def _get_arg(self, args: list, flag: str) -> Optional[str]:
        """Holt Argument-Wert."""
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
            if a.startswith(flag + "="):
                return a[len(flag) + 1:]
        return None

    def _dict(self, args: list, dry_run: bool) -> tuple:
        """Verwaltet das Woerterbuch."""
        sub_cmd = args[0] if args else "status"

        if sub_cmd == "init":
            return self._dict_init(dry_run)
        elif sub_cmd == "add":
            return self._dict_add(args[1:], dry_run)
        elif sub_cmd == "search":
            return self._dict_search(args[1:])
        elif sub_cmd == "status":
            return self._dict_status()
        else:
            return (False, f"Unbekannter dict-Befehl: {sub_cmd}\n\nVerfuegbar: init, add, search, status")

    def _dict_status(self) -> tuple:
        """Zeigt Woerterbuch-Status."""
        conn = self._get_db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM languages_dictionary").fetchone()[0]

            by_lang = conn.execute("""
                SELECT source_lang || '->' || target_lang as pair, COUNT(*) as cnt
                FROM languages_dictionary
                GROUP BY pair
                ORDER BY cnt DESC
            """).fetchall()

            output = [
                "=== WOERTERBUCH STATUS ===",
                "",
                f"Gesamt-Eintraege: {total}",
                ""
            ]

            if by_lang:
                output.append("Nach Sprachpaar:")
                for row in by_lang:
                    output.append(f"  {row['pair']}: {row['cnt']}")

            output.extend([
                "",
                "Befehle:",
                "  bach lang dict init     Basis-Woerterbuch laden",
                "  bach lang dict add <de> <en>  Eintrag hinzufuegen",
                "  bach lang dict search <term>  Suchen"
            ])

            return (True, "\n".join(output))

        finally:
            conn.close()

    def _dict_init(self, dry_run: bool) -> tuple:
        """Initialisiert Woerterbuch mit Basis-Eintraegen."""
        if dry_run:
            return (True, f"[DRY-RUN] Wuerde {len(self.BASE_DICTIONARY)} Eintraege laden.")

        conn = self._get_db()
        try:
            added = 0
            skipped = 0
            now = datetime.now().isoformat()

            for de_term, en_term in self.BASE_DICTIONARY.items():
                # Pruefen ob bereits vorhanden
                existing = conn.execute("""
                    SELECT id FROM languages_dictionary
                    WHERE term = ? AND source_lang = 'de' AND target_lang = 'en'
                """, (de_term,)).fetchone()

                if existing:
                    skipped += 1
                    continue

                conn.execute("""
                    INSERT INTO languages_dictionary
                    (term, translation, source_lang, target_lang, is_preferred, usage_count, context, created_at)
                    VALUES (?, ?, 'de', 'en', 1, 0, 'base_dictionary', ?)
                """, (de_term, en_term, now))
                added += 1

            conn.commit()
            return (True, f"[DICT] Woerterbuch initialisiert:\n  Hinzugefuegt: {added}\n  Bereits vorhanden: {skipped}")

        finally:
            conn.close()

    def _dict_add(self, args: list, dry_run: bool) -> tuple:
        """Fuegt Woerterbuch-Eintrag hinzu."""
        if len(args) < 2:
            return (False, "Fehler: de und en Term erforderlich.\n\nBeispiel: bach lang dict add datei file")

        de_term = args[0].lower()
        en_term = args[1].lower()

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde hinzufuegen: {de_term} -> {en_term}")

        conn = self._get_db()
        try:
            now = datetime.now().isoformat()

            # INSERT OR REPLACE
            conn.execute("""
                INSERT OR REPLACE INTO languages_dictionary
                (term, translation, source_lang, target_lang, is_preferred, usage_count, context, created_at)
                VALUES (?, ?, 'de', 'en', 1, 0, 'manual', ?)
            """, (de_term, en_term, now))

            conn.commit()
            return (True, f"[DICT] Hinzugefuegt: {de_term} -> {en_term}")

        finally:
            conn.close()

    def _dict_search(self, args: list) -> tuple:
        """Durchsucht Woerterbuch."""
        if not args:
            return (False, "Fehler: Suchbegriff erforderlich.")

        term = args[0].lower()

        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT term, translation, source_lang, target_lang, usage_count
                FROM languages_dictionary
                WHERE term LIKE ? OR translation LIKE ?
                ORDER BY usage_count DESC
                LIMIT 20
            """, (f"%{term}%", f"%{term}%")).fetchall()

            if not rows:
                return (True, f"[DICT] Keine Treffer fuer '{term}'")

            output = [f"[DICT] {len(rows)} Treffer fuer '{term}':", ""]

            for r in rows:
                output.append(f"  {r['term']} ({r['source_lang']}) -> {r['translation']} ({r['target_lang']})  [{r['usage_count']} verwendet]")

            return (True, "\n".join(output))

        finally:
            conn.close()


# =============================================================================
# t() HELPER FUNCTION - Einfacher Uebersetzungs-Lookup
# =============================================================================
# Nutzung:
#   from hub.lang import t, get_lang, set_lang
#   print(t("speichern"))           # -> "save" (wenn Sprache EN)
#   print(t("save_btn", default="Save"))  # -> Fallback wenn nicht gefunden
#   print(t("datei", lang="en"))    # -> "file" (explizit EN)
# =============================================================================

_t_cache: Dict[str, str] = {}
_t_lang_cache: Optional[str] = None
_t_db_path: Optional[Path] = None


def _get_t_db_path() -> Path:
    """Ermittelt DB-Pfad (cached)."""
    global _t_db_path
    if _t_db_path is None:
        try:
            from hub.bach_paths import BACH_DB
            _t_db_path = BACH_DB
        except ImportError:
            _t_db_path = Path(__file__).parent.parent / "data" / "bach.db"
    return _t_db_path


def get_lang() -> str:
    """Gibt die aktuelle Sprache zurueck (de/en)."""
    global _t_lang_cache
    if _t_lang_cache is not None:
        return _t_lang_cache

    db_path = _get_t_db_path()
    if not db_path.exists():
        return "de"

    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT default_language FROM languages_config LIMIT 1").fetchone()
        _t_lang_cache = row[0] if row else "de"
        return _t_lang_cache
    except Exception:
        return "de"
    finally:
        if conn:
            conn.close()


def set_lang(lang: str) -> None:
    """Setzt die aktuelle Sprache (cleared cache)."""
    global _t_lang_cache, _t_cache
    _t_lang_cache = lang
    _t_cache.clear()


def clear_t_cache() -> None:
    """Leert den Translation-Cache."""
    global _t_cache, _t_lang_cache
    _t_cache.clear()
    _t_lang_cache = None


def _get_lang_config() -> Dict[str, str]:
    """
    Holt Sprachkonfiguration aus DB (default_language, fallback_language).

    Returns:
        Dict mit 'default' und 'fallback' Sprach-Codes.
    """
    db_path = _get_t_db_path()
    if not db_path.exists():
        return {'default': 'de', 'fallback': 'en'}

    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT default_language, fallback_language FROM languages_config LIMIT 1"
        ).fetchone()

        if row:
            return {'default': row[0] or 'de', 'fallback': row[1] or 'en'}
    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    return {'default': 'de', 'fallback': 'en'}


def t(key: str, lang: Optional[str] = None, default: Optional[str] = None) -> str:
    """
    Uebersetzt einen Key in die aktuelle/angegebene Sprache.

    Args:
        key: Translation-Key (z.B. "speichern", "datei_nicht_gefunden")
        lang: Optional Zielsprache ("de" oder "en"), sonst System-Einstellung
        default: Fallback-Wert wenn nicht gefunden (sonst wird Key zurueckgegeben)

    Returns:
        Uebersetzer Text oder default/key wenn nicht gefunden.

    Beispiele:
        t("speichern")              # -> "save" (wenn System-Sprache EN)
        t("speichern", lang="de")   # -> "speichern"
        t("speichern", lang="en")   # -> "save"
        t("unknown_key", default="Unbekannt")  # -> "Unbekannt"
    """
    global _t_cache

    target_lang = lang or get_lang()
    cache_key = f"{key}:{target_lang}"

    # Cache-Hit?
    if cache_key in _t_cache:
        return _t_cache[cache_key]

    # 1. Versuche exakten Match in languages_translations
    db_path = _get_t_db_path()
    if db_path.exists():
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))

            row = conn.execute("""
                SELECT value FROM languages_translations
                WHERE key = ? AND language = ? AND value != ''
                LIMIT 1
            """, (key, target_lang)).fetchone()

            if row and row[0]:
                _t_cache[cache_key] = row[0]
                return row[0]

            # 2. Fallback: Woerterbuch (fuer einzelne Woerter)
            lang_config = _get_lang_config()
            default_lang = lang_config['default']

            if target_lang != default_lang:
                dict_row = conn.execute("""
                    SELECT translation FROM languages_dictionary
                    WHERE term = ? AND source_lang = ? AND target_lang = ?
                    AND is_preferred = 1
                    ORDER BY usage_count DESC LIMIT 1
                """, (key.lower(), default_lang, target_lang)).fetchone()

                if dict_row and dict_row[0]:
                    _t_cache[cache_key] = dict_row[0]
                    return dict_row[0]

            # 3. Fallback: Fallback-Sprache aus Config pruefen
            fallback_lang = lang_config['fallback'] if target_lang != lang_config['fallback'] else lang_config['default']
            fallback_row = conn.execute("""
                SELECT value FROM languages_translations
                WHERE key = ? AND language = ? AND value != ''
                LIMIT 1
            """, (key, fallback_lang)).fetchone()

            if fallback_row and fallback_row[0]:
                _t_cache[cache_key] = fallback_row[0]
                return fallback_row[0]

        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    # Nicht gefunden: default oder Key zurueckgeben
    result = default if default is not None else key
    _t_cache[cache_key] = result
    return result


def t_exists(key: str, lang: Optional[str] = None) -> bool:
    """Prueft ob ein Translation-Key existiert."""
    db_path = _get_t_db_path()
    if not db_path.exists():
        return False

    target_lang = lang or get_lang()

    conn = None
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("""
            SELECT 1 FROM languages_translations
            WHERE key = ? AND language = ? AND value != ''
            LIMIT 1
        """, (key, target_lang)).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        if conn:
            conn.close()
