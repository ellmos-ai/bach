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
  bach lang report           i18n-Drift und Release-Artefakte prüfen
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
import html
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Set
from hub.base import BaseHandler

KNOWN_LANGUAGE_LABELS = {
    "de": "Deutsch",
    "en": "English",
    "es": "Spanish",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
}

DEFAULT_SOURCE_LANGUAGE = "de"
DEFAULT_TARGET_LANGUAGE = "en"


class LangHandler(BaseHandler):
    """Handler fuer Mehrsprachigkeit und Uebersetzungen."""

    LANGUAGE_LABELS = KNOWN_LANGUAGE_LABELS

    # Quellen-Prioritaet (hoeher = vertrauenswuerdiger)
    SOURCE_PRIORITY = {
        'manual': 100,        # Manuell verifiziert
        'llm_reviewed': 80,   # LLM-korrigiert
        'llm_auto': 60,       # LLM-automatisch
        'mixed_auto': 50,     # Gemischter Auto-Import (Online + lokaler Fallback)
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
        "status", "uebersicht", "details", "hilfe", "allgemein",
        "erstellt", "aktualisiert", "geloescht", "gefunden",
        "verfuegbar", "nicht gefunden", "ungueltig", "erforderlich"
    ]

    ENGLISH_HINTS = [
        "save", "load", "open", "close", "cancel", "confirm", "continue",
        "start", "stop", "pause", "settings", "overview", "details",
        "status", "warning", "error", "success", "help", "search",
        "filter", "sort", "delete", "remove", "message", "task",
        "profile", "dashboard", "retry", "clear", "refresh",
    ]

    HTML_ATTRIBUTE_PATTERNS = [
        (
            "html_attr",
            re.compile(
                r'\b(?:title|placeholder|aria-label|alt|value|data-confirm|data-empty|data-error|data-label)\s*=\s*["\']([^"\']+)["\']',
                re.IGNORECASE,
            ),
        ),
    ]

    JS_UI_PATTERNS = [
        ("javascript", re.compile(r'(?:alert|confirm|prompt)\s*\(\s*["\']([^"\']+)["\']')),
        ("javascript", re.compile(r'(?:textContent|innerText|placeholder|title|ariaLabel)\s*=\s*["\']([^"\']+)["\']')),
        ("javascript", re.compile(r'setAttribute\s*\(\s*["\'](?:title|placeholder|aria-label|data-confirm|data-empty|data-error|data-label)["\']\s*,\s*["\']([^"\']+)["\']')),
        ("javascript", re.compile(r'(?:throw\s+new\s+Error|new\s+Error)\s*\(\s*["\']([^"\']+)["\']')),
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
            "report": "i18n-Drift und Release-Artefakte pruefen",
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

    def _normalize_language_code(self, lang_code: Optional[str], fallback: str = DEFAULT_TARGET_LANGUAGE) -> str:
        """Normalisiert Sprachcodes auf 2-3 Kleinbuchstaben."""
        if not lang_code:
            return fallback
        code = str(lang_code).strip().lower()
        if re.match(r"^[a-z]{2,3}$", code):
            return code
        return fallback

    def _lang_label(self, lang_code: str) -> str:
        """Liefert eine menschenlesbare Sprachbezeichnung."""
        normalized = self._normalize_language_code(lang_code, "")
        return self.LANGUAGE_LABELS.get(normalized, normalized or "unknown")

    def _parse_enabled_languages_value(self, raw_value) -> List[str]:
        """Parst enabled_languages aus DB-JSON."""
        if isinstance(raw_value, list):
            values = raw_value
        elif raw_value:
            try:
                values = json.loads(raw_value)
            except json.JSONDecodeError:
                values = [DEFAULT_SOURCE_LANGUAGE, DEFAULT_TARGET_LANGUAGE]
        else:
            values = [DEFAULT_SOURCE_LANGUAGE, DEFAULT_TARGET_LANGUAGE]

        normalized = []
        for value in values:
            code = self._normalize_language_code(value, "")
            if code and code not in normalized:
                normalized.append(code)

        if DEFAULT_SOURCE_LANGUAGE not in normalized:
            normalized.insert(0, DEFAULT_SOURCE_LANGUAGE)
        if DEFAULT_TARGET_LANGUAGE not in normalized:
            normalized.append(DEFAULT_TARGET_LANGUAGE)
        return normalized

    def _get_enabled_languages(self, conn, include_detected: bool = True) -> List[str]:
        """Liefert aktivierte Sprachcodes aus Config und optional aus vorhandenen Daten."""
        row = conn.execute("SELECT enabled_languages FROM languages_config LIMIT 1").fetchone()
        enabled = self._parse_enabled_languages_value(row["enabled_languages"] if row else None)

        if include_detected:
            for detected in conn.execute(
                "SELECT DISTINCT language FROM languages_translations WHERE language IS NOT NULL ORDER BY language"
            ).fetchall():
                code = self._normalize_language_code(detected["language"], "")
                if code and code not in enabled:
                    enabled.append(code)

        return enabled

    def _ensure_languages_enabled(self, conn, languages: List[str]) -> List[str]:
        """Stellt sicher, dass angegebene Sprachcodes in languages_config aktiviert sind."""
        requested = []
        for language in languages:
            code = self._normalize_language_code(language, "")
            if code and code not in requested:
                requested.append(code)

        if not requested:
            return self._get_enabled_languages(conn, include_detected=False)

        enabled = self._get_enabled_languages(conn, include_detected=False)
        changed = False
        for code in requested:
            if code not in enabled:
                enabled.append(code)
                changed = True

        if changed:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO languages_config (id, enabled_languages, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    enabled_languages = excluded.enabled_languages,
                    updated_at = excluded.updated_at
            """, (json.dumps(enabled, ensure_ascii=False), now))

        return enabled

    def _get_source_language(self, args: list) -> str:
        """Quelle fuer fehlende Uebersetzungen."""
        return self._normalize_language_code(
            self._get_arg(args, "--source-lang") or self._get_arg(args, "--from"),
            DEFAULT_SOURCE_LANGUAGE,
        )

    def _get_target_language(self, args: list) -> str:
        """Zielsprache fuer Uebersetzung/Export."""
        return self._normalize_language_code(
            self._get_arg(args, "--target") or self._get_arg(args, "--to"),
            DEFAULT_TARGET_LANGUAGE,
        )

    def _collect_add_translations(self, args: list) -> Dict[str, str]:
        """Sammelt Sprachtexte aus add-Argumenten."""
        translations: Dict[str, str] = {}

        for lang_code in self.LANGUAGE_LABELS:
            value = self._get_arg(args, f"--{lang_code}")
            if value:
                translations[lang_code] = value

        idx = 0
        while idx < len(args):
            token = args[idx]
            if token == "--lang" and idx + 3 < len(args) and args[idx + 2] == "--text":
                code = self._normalize_language_code(args[idx + 1], "")
                value = args[idx + 3]
                if code and value:
                    translations[code] = value
                idx += 4
                continue
            idx += 1

        return translations

    def _collect_import_translations(self, item: dict) -> Dict[str, str]:
        """Extrahiert Sprachtexte aus JSON-Importen."""
        translations: Dict[str, str] = {}
        reserved_keys = {
            "key",
            "namespace",
            "source",
            "source_language",
            "target_language",
            "translation",
            "translations",
        }

        nested = item.get("translations")
        if isinstance(nested, dict):
            for lang_code, value in nested.items():
                code = self._normalize_language_code(lang_code, "")
                if code and value:
                    translations[code] = value

        target_lang = self._normalize_language_code(item.get("target_language"), "")
        if target_lang and item.get("translation"):
            translations[target_lang] = item["translation"]

        for key, value in item.items():
            if key in reserved_keys:
                continue
            code = self._normalize_language_code(key, "")
            if code and isinstance(value, str) and value:
                translations[code] = value

        return translations

    def _sql_literal(self, value) -> str:
        """Konvertiert Python-Werte in SQLite-Literale fuer Seed-Dateien."""
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        return "'" + str(value).replace("'", "''") + "'"

    def _release_export_dir(self) -> Path:
        """Zielordner fuer releasefaehige Sprach-Artefakte."""
        return self.base_path / "exports" / "translations"

    def _release_manifest_source(self) -> str:
        """Neutraler DB-Hinweis fuer releasefaehige Artefakte."""
        return "runtime_db"

    def _sanitize_release_value(self, value):
        """Entfernt lokale Benutzerpfade aus releasefaehigen Sprach-Artefakten."""
        if isinstance(value, str):
            value = re.sub(
                r"[A-Za-z]:\\Users\\[^\\\r\n\"']+\\OneDrive\\[^\"\r\n']+",
                "<BACH_WORKSPACE>",
                value,
            )
            value = re.sub(
                r"[A-Za-z]:/Users/[^/\r\n\"']+/OneDrive/[^\"\r\n']+",
                "<BACH_WORKSPACE>",
                value,
            )
            value = re.sub(
                r"[A-Za-z]:\\Users\\[^\\\r\n\"']+",
                "%USERPROFILE%",
                value,
            )
            value = re.sub(
                r"[A-Za-z]:/Users/[^/\r\n\"']+",
                "%USERPROFILE%",
                value,
            )
            return value
        if isinstance(value, list):
            return [self._sanitize_release_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._sanitize_release_value(item) for key, item in value.items()}
        return value

    def _sanitize_release_row(self, row) -> dict:
        """Konvertiert DB-Zeilen in releasefaehige, pfadbereinigte Dicts."""
        return {key: self._sanitize_release_value(value) for key, value in dict(row).items()}

    def _write_release_exports(self, conn) -> Path:
        """Spiegelt den aktuellen Sprachstand aus der DB in releasebezogene Dateien."""
        export_dir = self._release_export_dir()
        export_dir.mkdir(parents=True, exist_ok=True)
        locales_dir = export_dir / "locales"
        locales_dir.mkdir(parents=True, exist_ok=True)

        config_row = conn.execute("SELECT * FROM languages_config ORDER BY id LIMIT 1").fetchone()
        config_payload = dict(config_row) if config_row else {}
        enabled_languages = config_payload.get("enabled_languages")
        if isinstance(enabled_languages, str):
            try:
                config_payload["enabled_languages"] = json.loads(enabled_languages)
            except json.JSONDecodeError:
                pass
        else:
            config_payload["enabled_languages"] = self._get_enabled_languages(conn, include_detected=True)
        config_payload = self._sanitize_release_value(config_payload)

        translations_payload = [
            self._sanitize_release_row(row) for row in conn.execute("""
                SELECT key, namespace, language, value, is_verified, source, created_at, updated_at
                FROM languages_translations
                ORDER BY namespace, key, language
            """).fetchall()
        ]

        dictionary_payload = [
            self._sanitize_release_row(row) for row in conn.execute("""
                SELECT term, translation, source_lang, target_lang, is_preferred, usage_count, context, created_at
                FROM languages_dictionary
                ORDER BY source_lang, target_lang, term, translation
            """).fetchall()
        ]

        locale_files = {}
        enabled_language_list = config_payload.get("enabled_languages") or self._get_enabled_languages(conn, include_detected=True)
        translation_languages = sorted({row["language"] for row in translations_payload if row.get("language")})
        for language in translation_languages:
            if language not in enabled_language_list:
                enabled_language_list.append(language)

        for language in enabled_language_list:
            locale_payload = {
                "language": language,
                "label": self._lang_label(language),
                "generated_at": datetime.now().isoformat(),
                "entries": {},
            }
            for row in translations_payload:
                if row["language"] != language:
                    continue
                namespace = row["namespace"] or "general"
                locale_payload["entries"].setdefault(namespace, {})[row["key"]] = row["value"]

            locale_filename = f"{language}.json"
            (locales_dir / locale_filename).write_text(
                json.dumps(locale_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            locale_files[language] = f"locales/{locale_filename}"

        seed_lines = [
            "-- Auto-generated by system/tools/release_language.py",
            "-- Mirrors the current release language state from bach.db",
            "",
        ]
        if config_payload:
            config_columns = list(config_payload.keys())
            config_values = ", ".join(self._sql_literal(config_payload[column]) for column in config_columns)
            seed_lines.append(
                f"INSERT OR REPLACE INTO languages_config ({', '.join(config_columns)}) VALUES ({config_values});"
            )
            seed_lines.append("")

        for row in translations_payload:
            columns = list(row.keys())
            values = ", ".join(self._sql_literal(row[column]) for column in columns)
            seed_lines.append(
                f"INSERT OR REPLACE INTO languages_translations ({', '.join(columns)}) VALUES ({values});"
            )

        if translations_payload:
            seed_lines.append("")

        for row in dictionary_payload:
            columns = list(row.keys())
            values = ", ".join(self._sql_literal(row[column]) for column in columns)
            seed_lines.append(
                f"INSERT OR REPLACE INTO languages_dictionary ({', '.join(columns)}) VALUES ({values});"
            )

        seed_filename = "languages_seed.release.sql"
        (export_dir / seed_filename).write_text("\n".join(seed_lines) + "\n", encoding="utf-8")

        manifest_payload = {
            "generated_at": datetime.now().isoformat(),
            "export_kind": "languages_release_snapshot",
            "source_db": self._release_manifest_source(),
            "counts": {
                "config_rows": 1 if config_payload else 0,
                "translations": len(translations_payload),
                "dictionary_entries": len(dictionary_payload),
                "locale_files": len(locale_files),
            },
            "files": {
                "config": "languages_config.release.json",
                "translations": "languages_translations.release.json",
                "dictionary": "languages_dictionary.release.json",
                "seed_sql": seed_filename,
            },
            "locales": locale_files,
        }

        artifacts = {
            "languages_config.release.json": config_payload,
            "languages_translations.release.json": translations_payload,
            "languages_dictionary.release.json": dictionary_payload,
            "manifest.release.json": manifest_payload,
        }

        for filename, payload in artifacts.items():
            (export_dir / filename).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        return export_dir

    def _missing_translation_predicate(
        self,
        source_alias: str = "t1",
        target_alias: str = "t2",
        target_lang: str = DEFAULT_TARGET_LANGUAGE,
    ) -> str:
        """SQL-Praedikat fuer Eintraege ohne passendes Gegenstueck in target_lang."""
        normalized_target = self._normalize_language_code(target_lang, DEFAULT_TARGET_LANGUAGE)
        return f"""
            NOT EXISTS (
                SELECT 1 FROM languages_translations {target_alias}
                WHERE {target_alias}.key = {source_alias}.key
                AND {target_alias}.namespace = {source_alias}.namespace
                AND {target_alias}.language = '{normalized_target}'
                AND COALESCE({target_alias}.value, '') != ''
            )
        """

    def _get_missing_rows(
        self,
        conn,
        limit: Optional[int] = None,
        source_lang: str = DEFAULT_SOURCE_LANGUAGE,
        target_lang: str = DEFAULT_TARGET_LANGUAGE,
    ):
        """Liefert source_lang-Eintraege ohne target_lang-Uebersetzung fuer denselben Namespace."""
        normalized_source = self._normalize_language_code(source_lang, DEFAULT_SOURCE_LANGUAGE)
        query = f"""
            SELECT t1.key, t1.namespace, t1.value as de_value
            FROM languages_translations t1
            WHERE t1.language = ?
            AND {self._missing_translation_predicate('t1', 't2', target_lang)}
            ORDER BY t1.namespace, t1.key
        """
        params = [normalized_source]

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        return conn.execute(query, params).fetchall()

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation == "help" or not operation:
            return self._show_help()
        elif operation == "status":
            return self._status()
        elif operation == "scan":
            return self._scan(args, dry_run)
        elif operation == "report":
            return self._report(args)
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
  bach lang report                 Release-Artefakte + Hardcoded-Copy pruefen
  bach lang report --namespace gui Nur GUI-Flächen analysieren
  bach lang report --json          Maschinenlesbarer Drift-Report
  bach lang list                   Alle Uebersetzungen anzeigen
  bach lang list --lang en         Nur englische Uebersetzungen
  bach lang missing                Fehlende Uebersetzungen anzeigen (Standard: de -> en)
  bach lang missing --target es    Fehlende spanische Uebersetzungen
  bach lang translate              Auto-Uebersetzung starten
  bach lang translate --target en  Auto-Uebersetzung fuer bestimmte Zielsprache
  bach lang translate --source windows_dict   Mit Windows-Woerterbuch
  bach lang translate --source llm            Mit LLM (erfordert Prompt)
  bach lang add <key> --de "Text" --en "Text" Manuell hinzufuegen
  bach lang add <key> --es "Texto" --ru "Текст" Weitere Sprachen direkt setzen
  bach lang add <key> --lang ja --text "テキスト" Generische Sprachpaare
  bach lang add-language <code>    Neue Sprache hinzufuegen (z.B. fr, es, pt)
  bach lang export                 Fuer LLM-Review exportieren (Standard: de -> en)
  bach lang export --target zh     Export fuer Chinesisch
  bach lang export --format json   Als JSON exportieren
  bach lang import <datei>         LLM-Review importieren
  bach lang set de                 Standard-Sprache auf Deutsch
  bach lang set ja                 Standard-Sprache auf Japanisch

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
  mixed_auto (50)    - Gemischter Auto-Import
  google_auto (40)   - Google Translate
  windows_dict (20)  - System-Woerterbuch
  auto_detected (10) - Nur erkannt, nicht uebersetzt

DATENBANK: bach.db / languages_config, languages_translations, languages_dictionary""")

    def _scan_targets(self, namespace_filter: Optional[str]) -> Dict[str, List[Path]]:
        """Liefert Scan-Ziele fuer das aktuelle BACH-Layout."""
        scan_targets = {
            "cli": [
                self.base_path / "hub",
                self.base_path / "bach.py",
                self.base_path / "bach_api.py",
            ],
            "gui": [self.base_path / "gui"],
            "help": [self.base_path / "docs" / "help"],
            "skills": [
                self.base_path / "agents",
                self.base_path / "skills" / "workflows",
                self.base_path / "SKILL.md",
            ],
            "tools": [self.base_path / "tools"],
        }
        if namespace_filter and namespace_filter in scan_targets:
            return {namespace_filter: scan_targets[namespace_filter]}
        return scan_targets

    def _should_skip_scan_file(self, file_path: Path) -> bool:
        """Ignoriert Cache-, Archiv- und Build-Artefakte beim String-Scan."""
        skip_parts = {"__pycache__", "_archive", ".git", ".pytest_cache", "node_modules"}
        return any(part in skip_parts for part in file_path.parts)

    def _iter_scan_files(self, target: Path):
        """Iteriert unterstuetzte Textdateien fuer den String-Scan."""
        suffixes = (".py", ".txt", ".md", ".html", ".js")
        if target.is_file():
            if target.suffix.lower() in suffixes and not self._should_skip_scan_file(target):
                yield target
            return
        if not target.exists():
            return
        for suffix in suffixes:
            for file_path in target.rglob(f"*{suffix}"):
                if self._should_skip_scan_file(file_path):
                    continue
                yield file_path

    def _normalize_candidate_text(self, text: str) -> Optional[str]:
        """Bereinigt extrahierte Textfragmente fuer die Sprach-Erkennung."""
        clean = re.sub(r"\s+", " ", text or "").strip(" \t\r\n-*:|#>")
        if not clean or len(clean) < 3 or len(clean) > 300:
            return None
        if any(token in clean for token in ("{{", "}}", "{%", "%}")):
            return None
        return clean

    def _extract_markdown_strings(self, file_path: Path) -> Set[str]:
        """Extrahiert uebersetzbare Zeilen aus Markdown-Dateien."""
        strings = set()
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return strings

        in_code_block = False
        in_frontmatter = False
        frontmatter_seen = 0

        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if stripped == "---" and not in_code_block and frontmatter_seen < 2:
                in_frontmatter = not in_frontmatter
                frontmatter_seen += 1
                continue
            if in_code_block or in_frontmatter or not stripped:
                continue

            candidate = stripped
            candidate = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", candidate)
            candidate = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", candidate)
            candidate = re.sub(r"`[^`]+`", "", candidate)
            candidate = re.sub(r"^[-*#>\d\.\)\s]+", "", candidate)
            candidate = candidate.replace("|", " ")
            clean = self._normalize_candidate_text(candidate)
            if clean and self._is_german(clean):
                strings.add(clean)

        return strings

    def _extract_markup_strings(self, file_path: Path) -> Set[str]:
        """Extrahiert sichtbare Texte und UI-Attribute aus HTML-Templates."""
        strings = set()
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return strings

        text_nodes = re.findall(r">([^<>{}]{3,300})<", content)
        attr_nodes = re.findall(
            r"""(?:title|placeholder|aria-label|alt|data-confirm)\s*=\s*["']([^"']{3,300})["']""",
            content,
            flags=re.IGNORECASE,
        )

        for candidate in text_nodes + attr_nodes:
            clean = self._normalize_candidate_text(candidate)
            if clean and self._is_german(clean):
                strings.add(clean)

        return strings

    def _extract_inline_markup_candidates(self, text: str) -> List[str]:
        """Extrahiert sichtbare Texte aus eingebetteten HTML-Snippets, z.B. in JS-Templates."""
        candidates: List[str] = []
        cleaned = re.sub(r"{{.*?}}|{%.*?%}|{#.*?#}", "", text or "")

        for match in re.finditer(r">([^<>{}]{3,300})<", cleaned):
            candidates.append(html.unescape(match.group(1)))

        for match in re.finditer(
            r"""(?:title|placeholder|aria-label|alt|data-confirm)\s*=\s*["']([^"']{3,300})["']""",
            cleaned,
            flags=re.IGNORECASE,
        ):
            candidates.append(html.unescape(match.group(1)))

        return candidates

    def _should_skip_script_literal(self, candidate: str, raw_line: str) -> bool:
        """Filtert technische JS-Literale aus, damit der i18n-Report UI-Texte priorisiert."""
        text = (candidate or "").strip()
        line = (raw_line or "").strip()
        text_lower = text.lower()
        line_lower = line.lower()

        if not text:
            return True
        if "<" in text and ">" in text:
            return True
        if line_lower.startswith("console.") or " console." in line_lower:
            return True
        if text.startswith(("/api/", "api/", "http://", "https://", "?")):
            return True
        if re.match(r"^[a-z]{2}-[A-Z]{2}$", text):
            return True
        if re.match(r"^HTTP\s+\$\{[^}]+\}$", text):
            return True
        if any(token in text for token in ("/", "?", "=", "&")) and " " not in text:
            return True
        if any(
            marker in line_lower
            for marker in (
                "getelementbyid(",
                "queryselector(",
                "queryselectorall(",
                "closest(",
                "classlist.",
            )
        ) and re.match(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$", text_lower):
            return True
        if re.search(r"""\b(?:class|id)\s*=\s*["']""", line_lower) and re.match(
            r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$",
            text_lower,
        ):
            return True
        return False

    def _extract_script_strings(self, file_path: Path) -> Set[str]:
        """Extrahiert UI-relevante String-Literale aus JavaScript-Dateien."""
        strings = set()
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return strings

        literal_pattern = re.compile(r"""(?:"([^"\n]{3,300})"|'([^'\n]{3,300})'|`([^`\n]{3,300})`)""")
        for raw_line in lines:
            if "<" in raw_line and ">" in raw_line:
                for candidate in self._extract_inline_markup_candidates(raw_line):
                    clean = self._normalize_candidate_text(candidate)
                    if clean and self._is_german(clean):
                        strings.add(clean)
            for match in literal_pattern.findall(raw_line):
                candidate = next((part for part in match if part), "")
                if self._should_skip_script_literal(candidate, raw_line):
                    continue
                clean = self._normalize_candidate_text(candidate)
                if clean and self._is_german(clean):
                    strings.add(clean)

        return strings

    def _extract_strings_for_file(self, file_path: Path) -> Set[str]:
        """Waehlt je nach Dateityp den passenden Extraktor."""
        suffix = file_path.suffix.lower()
        if suffix == ".py":
            return self._extract_german_strings(file_path)
        if suffix == ".txt":
            return self._extract_help_strings(file_path)
        if suffix == ".md":
            return self._extract_markdown_strings(file_path)
        if suffix == ".html":
            return self._extract_markup_strings(file_path)
        if suffix == ".js":
            return self._extract_script_strings(file_path)
        return set()

    def _collect_found_strings(self, namespace_filter: Optional[str] = None) -> Dict[str, Set[str]]:
        """Sammelt erkannte deutsche Strings je Namespace."""
        found_strings: Dict[str, Set[str]] = {}
        for namespace, targets in self._scan_targets(namespace_filter).items():
            found_strings[namespace] = set()
            for target in targets:
                for file_path in self._iter_scan_files(target):
                    found_strings[namespace].update(self._extract_strings_for_file(file_path))
        return found_strings

    def _collect_hardcoded_occurrences(self, namespace_filter: Optional[str] = None) -> List[Dict[str, object]]:
        """Sammelt konkrete Hardcoded-Copy-Fundstellen inklusive Datei und Zeile."""
        occurrences: List[Dict[str, object]] = []
        seen = set()
        for namespace, targets in self._scan_targets(namespace_filter).items():
            for target in targets:
                for file_path in self._iter_scan_files(target):
                    for item in self._extract_detail_records_for_file(file_path, namespace):
                        key = (
                            item["namespace"],
                            item["file"],
                            item["line"],
                            item["kind"],
                            item["text"],
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        occurrences.append(item)
        return occurrences

    def _extract_detail_records_for_file(self, file_path: Path, namespace: str) -> List[Dict[str, object]]:
        """Waehlt je nach Dateityp den passenden Detail-Extraktor."""
        suffix = file_path.suffix.lower()
        if namespace == "gui" and suffix not in {".py", ".html", ".js"}:
            return []
        if namespace == "cli" and suffix != ".py":
            return []
        if namespace == "help" and suffix != ".txt":
            return []
        if suffix == ".py":
            return self._extract_python_string_details(file_path, namespace)
        if suffix == ".txt":
            return self._extract_help_string_details(file_path, namespace)
        if suffix == ".md":
            return self._extract_markdown_string_details(file_path, namespace)
        if suffix == ".html":
            return self._extract_markup_string_details(file_path, namespace)
        if suffix == ".js":
            return self._extract_script_string_details(file_path, namespace)
        return []

    def _detail_record(
        self,
        file_path: Path,
        namespace: str,
        line_no: int,
        text: str,
        kind: str,
    ) -> Optional[Dict[str, object]]:
        """Baut einen normalisierten Detail-Datensatz fuer Hardcoded Copy."""
        clean = self._normalize_candidate_text(text)
        if not clean or not self._is_german(clean):
            return None
        if clean.count("{") != clean.count("}") or clean.count("[") != clean.count("]"):
            return None
        return {
            "namespace": namespace,
            "file": file_path.relative_to(self.base_path).as_posix(),
            "line": line_no,
            "kind": kind,
            "text": clean,
            "suggested_key": self._make_key(clean),
        }

    def _extract_python_string_details(self, file_path: Path, namespace: str) -> List[Dict[str, object]]:
        """Extrahiert konkrete Python-Fundstellen mit Zeilennummer."""
        details: List[Dict[str, object]] = []
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return details

        runtime_patterns = self.STRING_PATTERNS[:7]
        for line_no, raw_line in enumerate(lines, 1):
            for pattern in runtime_patterns:
                for match in pattern.finditer(raw_line):
                    record = self._detail_record(file_path, namespace, line_no, match.group(1), "python")
                    if record:
                        details.append(record)
        return details

    def _extract_help_string_details(self, file_path: Path, namespace: str) -> List[Dict[str, object]]:
        """Extrahiert konkrete Help-Fundstellen mit Zeilennummer."""
        details: List[Dict[str, object]] = []
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return details

        for line_no, raw_line in enumerate(lines, 1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if line_no == 1:
                record = self._detail_record(file_path, namespace, line_no, stripped, "help")
                if record:
                    details.append(record)
            if line_no < len(lines) and lines[line_no].startswith(("===", "---")):
                record = self._detail_record(file_path, namespace, line_no, stripped, "help")
                if record:
                    details.append(record)
        return details

    def _extract_markdown_string_details(self, file_path: Path, namespace: str) -> List[Dict[str, object]]:
        """Extrahiert konkrete Markdown-Fundstellen mit Zeilennummer."""
        details: List[Dict[str, object]] = []
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return details

        in_code_block = False
        in_frontmatter = False
        frontmatter_seen = 0

        for line_no, raw_line in enumerate(lines, 1):
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if stripped == "---" and not in_code_block and frontmatter_seen < 2:
                in_frontmatter = not in_frontmatter
                frontmatter_seen += 1
                continue
            if in_code_block or in_frontmatter or not stripped:
                continue

            candidate = stripped
            candidate = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", candidate)
            candidate = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", candidate)
            candidate = re.sub(r"`[^`]+`", "", candidate)
            candidate = re.sub(r"^[-*#>\d\.\)\s]+", "", candidate)
            candidate = candidate.replace("|", " ")
            record = self._detail_record(file_path, namespace, line_no, candidate, "markdown")
            if record:
                details.append(record)
        return details

    def _extract_markup_string_details(self, file_path: Path, namespace: str) -> List[Dict[str, object]]:
        """Extrahiert konkrete HTML-/Template-Fundstellen mit Zeilennummer."""
        details: List[Dict[str, object]] = []
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return details

        in_script = False
        in_style = False
        for line_no, raw_line in enumerate(lines, 1):
            lower = raw_line.lower()
            if "<script" in lower:
                in_script = True
            if "<style" in lower:
                in_style = True
            if in_script or in_style:
                if "</script>" in lower:
                    in_script = False
                if "</style>" in lower:
                    in_style = False
                continue

            cleaned = re.sub(r"{{.*?}}|{%.*?%}|{#.*?#}", "", raw_line)
            for match in re.finditer(r">([^<>{}]{3,300})<", cleaned):
                record = self._detail_record(file_path, namespace, line_no, match.group(1), "html_text")
                if record:
                    details.append(record)

            for match in re.finditer(
                r"""(?:title|placeholder|aria-label|alt|data-confirm)\s*=\s*["']([^"']{3,300})["']""",
                cleaned,
                flags=re.IGNORECASE,
            ):
                record = self._detail_record(file_path, namespace, line_no, match.group(1), "html_attr")
                if record:
                    details.append(record)
        return details

    def _extract_script_string_details(self, file_path: Path, namespace: str) -> List[Dict[str, object]]:
        """Extrahiert konkrete JavaScript-Fundstellen mit Zeilennummer."""
        details: List[Dict[str, object]] = []
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return details

        literal_pattern = re.compile(r"""(?:"([^"\n]{3,300})"|'([^'\n]{3,300})'|`([^`\n]{3,300})`)""")
        for line_no, raw_line in enumerate(lines, 1):
            if "<" in raw_line and ">" in raw_line:
                for candidate in self._extract_inline_markup_candidates(raw_line):
                    record = self._detail_record(file_path, namespace, line_no, candidate, "javascript")
                    if record:
                        details.append(record)
            for match in literal_pattern.findall(raw_line):
                candidate = next((part for part in match if part), "")
                if self._should_skip_script_literal(candidate, raw_line):
                    continue
                record = self._detail_record(file_path, namespace, line_no, candidate, "javascript")
                if record:
                    details.append(record)
        return details

    def _normalize_translation_records(self, rows) -> Set[tuple]:
        """Normalisiert DB-/JSON-Uebersetzungen fuer Drift-Vergleiche."""
        normalized = set()
        for row in rows or []:
            key = str(row.get("key") or "").strip()
            language = self._normalize_language_code(row.get("language"), "")
            if not key or not language:
                continue

            normalized.add((
                key,
                str(row.get("namespace") or "general").strip() or "general",
                language,
                str(row.get("value") or ""),
            ))
        return normalized

    def _flatten_locale_entries(self, payload: Optional[dict]) -> Set[tuple]:
        """Reduziert Locale-Dateien auf Namespace/Key/Value-Tupel."""
        entries = payload.get("entries") if isinstance(payload, dict) else {}
        normalized = set()
        if not isinstance(entries, dict):
            return normalized

        for namespace, values in entries.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                clean_key = str(key).strip()
                if not clean_key:
                    continue
                normalized.add((
                    str(namespace or "general").strip() or "general",
                    clean_key,
                    str(value or ""),
                ))
        return normalized

    def _format_translation_record(self, record: tuple) -> str:
        key, namespace, language, value = record
        short_value = value if len(value) <= 60 else value[:57] + "..."
        return f"{namespace}.{key} [{language}] = {short_value}"

    def _format_locale_record(self, record: tuple) -> str:
        namespace, key, value = record
        short_value = value if len(value) <= 60 else value[:57] + "..."
        return f"{namespace}.{key} = {short_value}"

    def _release_artifact_report(
        self,
        enabled_languages: List[str],
        db_config: Dict[str, object],
        db_rows: List[dict],
    ) -> Dict[str, object]:
        """Prueft Manifest, Locale-Dateien und Release-Exports auf Konsistenz."""
        export_dir = self._release_export_dir()
        config_path = export_dir / "languages_config.release.json"
        manifest_path = export_dir / "manifest.release.json"
        translations_path = export_dir / "languages_translations.release.json"
        dictionary_path = export_dir / "languages_dictionary.release.json"
        locales_dir = export_dir / "locales"

        issues: List[str] = []
        config_payload = {}
        if config_path.exists():
            try:
                config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(f"Config-Export unlesbar: {exc}")
        else:
            issues.append("Config-Export fehlt")

        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(f"Manifest unlesbar: {exc}")
        else:
            issues.append("Manifest fehlt")

        translation_rows = []
        if translations_path.exists():
            try:
                translation_rows = json.loads(translations_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(f"Translation-Export unlesbar: {exc}")
        else:
            issues.append("Translation-Export fehlt")

        dictionary_rows = []
        if dictionary_path.exists():
            try:
                dictionary_rows = json.loads(dictionary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(f"Dictionary-Export unlesbar: {exc}")
        else:
            issues.append("Dictionary-Export fehlt")

        locale_codes = []
        if locales_dir.exists():
            locale_codes = sorted(path.stem for path in locales_dir.glob("*.json"))
        else:
            issues.append("Locale-Ordner fehlt")

        manifest_counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}
        expected_locale_count = manifest_counts.get("locale_files")
        expected_translation_count = manifest_counts.get("translations")
        expected_dictionary_count = manifest_counts.get("dictionary_entries")

        missing_locales = sorted(code for code in enabled_languages if code not in locale_codes)
        extra_locales = sorted(code for code in locale_codes if code not in enabled_languages)
        if missing_locales:
            issues.append(f"Fehlende Locale-Dateien: {', '.join(missing_locales)}")
        if extra_locales:
            issues.append(f"Unerwartete Locale-Dateien: {', '.join(extra_locales)}")
        if expected_locale_count is not None and expected_locale_count != len(locale_codes):
            issues.append(f"Locale-Anzahl weicht ab ({expected_locale_count} != {len(locale_codes)})")
        if expected_translation_count is not None and expected_translation_count != len(translation_rows):
            issues.append(f"Translation-Count weicht ab ({expected_translation_count} != {len(translation_rows)})")
        if expected_dictionary_count is not None and expected_dictionary_count != len(dictionary_rows):
            issues.append(f"Dictionary-Count weicht ab ({expected_dictionary_count} != {len(dictionary_rows)})")

        release_enabled = sorted(
            {
                self._normalize_language_code(code, "")
                for code in (config_payload.get("enabled_languages") or [])
                if self._normalize_language_code(code, "")
            }
        )
        if release_enabled != sorted(set(enabled_languages)):
            issues.append(
                f"Enabled-Languages drift ({release_enabled} != {sorted(set(enabled_languages))})"
            )

        release_default = self._normalize_language_code(
            config_payload.get("default_language"), DEFAULT_SOURCE_LANGUAGE
        )
        if config_payload and release_default != db_config["default_language"]:
            issues.append(
                f"Default-Language drift ({release_default} != {db_config['default_language']})"
            )

        release_fallback = self._normalize_language_code(
            config_payload.get("fallback_language"), DEFAULT_TARGET_LANGUAGE
        )
        if config_payload and release_fallback != db_config["fallback_language"]:
            issues.append(
                f"Fallback-Language drift ({release_fallback} != {db_config['fallback_language']})"
            )

        if config_payload and bool(config_payload.get("auto_translate")) != bool(db_config["auto_translate"]):
            issues.append(
                f"Auto-Translate drift ({bool(config_payload.get('auto_translate'))} != {bool(db_config['auto_translate'])})"
            )

        sanitized_db_rows = [self._sanitize_release_row(row) for row in db_rows]
        db_records = self._normalize_translation_records(sanitized_db_rows)
        release_records = self._normalize_translation_records(translation_rows)
        missing_in_release = sorted(db_records - release_records)
        only_in_release = sorted(release_records - db_records)
        if missing_in_release:
            issues.append(f"DB-Eintraege fehlen im Translation-Export ({len(missing_in_release)})")
        if only_in_release:
            issues.append(f"Release-Export enthaelt fremde Eintraege ({len(only_in_release)})")

        locale_payloads = {}
        if locales_dir.exists():
            for locale_file in locales_dir.glob("*.json"):
                try:
                    locale_payloads[locale_file.stem] = json.loads(locale_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    issues.append(f"Locale-Datei {locale_file.name} unlesbar: {exc}")

        locale_content_issues = []
        languages_to_check = sorted({
            *[code for code in enabled_languages if code],
            *[record[2] for record in db_records],
            *[record[2] for record in release_records],
            *locale_codes,
        })
        for language in languages_to_check:
            expected_entries = {
                (namespace, key, value)
                for key, namespace, row_language, value in release_records
                if row_language == language and value != ""
            }
            payload = locale_payloads.get(language)
            if expected_entries and payload is None:
                issues.append(f"Locale-Datei fuer {language} fehlt trotz {len(expected_entries)} Export-Eintraegen")
                continue
            if payload is None:
                continue

            payload_language = self._normalize_language_code(payload.get("language"), language)
            if payload_language != language:
                issues.append(f"Locale-Datei {language}.json meldet language={payload.get('language')!r}")

            actual_entries = self._flatten_locale_entries(payload)
            missing_entries = sorted(expected_entries - actual_entries)
            extra_entries = sorted(actual_entries - expected_entries)
            if missing_entries or extra_entries:
                locale_content_issues.append({
                    "language": language,
                    "missing": missing_entries,
                    "extra": extra_entries,
                })
                issues.append(
                    f"Locale-Inhalt drift fuer {language} ({len(missing_entries)} fehlend, {len(extra_entries)} extra)"
                )

        return {
            "config_exists": config_path.exists(),
            "manifest_exists": manifest_path.exists(),
            "manifest_counts": manifest_counts,
            "translation_count": len(translation_rows),
            "dictionary_count": len(dictionary_rows),
            "locale_codes": locale_codes,
            "issues_count": len(issues),
            "issues": issues,
            "missing_in_release": missing_in_release,
            "only_in_release": only_in_release,
            "locale_content_issues": locale_content_issues,
        }

    def _status(self) -> tuple:
        """Zeigt Sprachkonfiguration und Statistiken."""
        conn = self._get_db()
        try:
            # Config laden
            config = conn.execute("SELECT * FROM languages_config LIMIT 1").fetchone()
            enabled_languages = self._get_enabled_languages(conn, include_detected=True)

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

            missing_by_target = []
            for target_lang in enabled_languages:
                if target_lang == DEFAULT_SOURCE_LANGUAGE:
                    continue
                missing_count = conn.execute(f"""
                    SELECT COUNT(*)
                    FROM languages_translations t1
                    WHERE t1.language = ?
                    AND {self._missing_translation_predicate('t1', 't2', target_lang)}
                """, (DEFAULT_SOURCE_LANGUAGE,)).fetchone()[0]
                missing_by_target.append((target_lang, missing_count))

            # Woerterbuch
            dict_count = conn.execute("SELECT COUNT(*) FROM languages_dictionary").fetchone()[0]

            output = [
                "=== SPRACH-SYSTEM STATUS ===",
                "",
                "Konfiguration:",
                f"  Standard-Sprache:  {config['default_language'] if config else 'de'}",
                f"  Fallback-Sprache:  {config['fallback_language'] if config else 'en'}",
                f"  Aktiviert:         {', '.join(enabled_languages)}",
                f"  Auto-Translate:    {'Ja' if config and config['auto_translate'] else 'Nein'}",
                "",
                "Statistiken:",
                f"  Gesamt-Eintraege:  {total}",
                f"  Verifiziert:       {verified}",
                f"  Woerterbuch:       {dict_count} Eintraege",
                "",
            ]

            if missing_by_target:
                output.append("Fehlende pro Zielsprache:")
                for target_lang, missing_count in missing_by_target:
                    output.append(f"  {target_lang}: {missing_count}")
                output.append("")

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
        found_strings = self._collect_found_strings(namespace_filter)

        # In DB einfuegen (wenn nicht dry_run)
        total_found = sum(len(s) for s in found_strings.values())
        added = 0
        would_add = 0

        if total_found > 0:
            conn = self._get_db()
            try:
                for namespace, strings in found_strings.items():
                    for string in strings:
                        # Pruefe ob bereits existiert
                        existing = conn.execute(
                            """
                            SELECT id FROM languages_translations
                            WHERE key = ? AND namespace = ? AND language = 'de'
                            """,
                            (self._make_key(string), namespace)
                        ).fetchone()

                        if not existing:
                            would_add += 1
                            if not dry_run:
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

                if not dry_run:
                    conn.commit()
                    if added > 0:
                        self._write_release_exports(conn)
            finally:
                conn.close()

        # Report
        output = [
            "=== STRING-SCAN ERGEBNIS ===",
            "",
            f"Gefunden: {total_found} deutsche Strings",
            f"Neu hinzugefuegt: {added}" if not dry_run else f"[DRY-RUN] Wuerde hinzufuegen: {would_add}",
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

    def _report(self, args: list) -> tuple:
        """Erzeugt einen kompakten i18n-Drift-Report fuer Release und Hardcoded Copy."""
        json_output = "--json" in args
        limit = int(self._get_arg(args, "--limit") or "25")
        namespace_filter = (
            self._get_arg(args, "--surface")
            or self._get_arg(args, "--namespace")
            or self._get_arg(args, "-n")
        )
        occurrences = self._collect_hardcoded_occurrences(namespace_filter)
        occurrences.sort(key=lambda item: (item["file"], item["line"], item["text"]))
        found_strings: Dict[str, Set[str]] = {}
        for item in occurrences:
            found_strings.setdefault(str(item["namespace"]), set()).add(str(item["text"]))
        total_found = sum(len(strings) for strings in found_strings.values())

        conn = self._get_db()
        try:
            enabled_languages = self._get_enabled_languages(conn, include_detected=True)
            config = conn.execute("SELECT * FROM languages_config ORDER BY id LIMIT 1").fetchone()
            db_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT key, namespace, language, value
                    FROM languages_translations
                    ORDER BY namespace, key, language
                    """
                ).fetchall()
            ]
            db_config = {
                "default_language": self._normalize_language_code(
                    config["default_language"] if config else DEFAULT_SOURCE_LANGUAGE,
                    DEFAULT_SOURCE_LANGUAGE,
                ),
                "fallback_language": self._normalize_language_code(
                    config["fallback_language"] if config else DEFAULT_TARGET_LANGUAGE,
                    DEFAULT_TARGET_LANGUAGE,
                ),
                "auto_translate": bool(config["auto_translate"]) if config else False,
            }
            existing_de = {
                ((row["namespace"] or "general"), row["key"])
                for row in conn.execute(
                    "SELECT namespace, key FROM languages_translations WHERE language = ?",
                    (DEFAULT_SOURCE_LANGUAGE,),
                ).fetchall()
            }
            for item in occurrences:
                tracked = (item["namespace"], item["suggested_key"]) in existing_de
                item["tracked"] = tracked

            indexed_total = 0
            missing_total = 0
            namespace_lines = []
            for namespace in sorted(found_strings.keys()):
                strings = found_strings[namespace]
                indexed = sum(1 for string in strings if (namespace, self._make_key(string)) in existing_de)
                missing = len(strings) - indexed
                indexed_total += indexed
                missing_total += missing
                namespace_lines.append(
                    f"  {namespace}: gefunden {len(strings)} | indexiert {indexed} | offen {missing}"
                )

            release_report = self._release_artifact_report(enabled_languages, db_config, db_rows)
        finally:
            conn.close()

        ok = release_report["issues_count"] == 0
        tracked_occurrences = sum(1 for item in occurrences if item["tracked"])
        missing_occurrences = len(occurrences) - tracked_occurrences
        by_kind: Dict[str, int] = {}
        for item in occurrences:
            by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1

        if json_output:
            payload = {
                "ok": ok,
                "release": {
                    "manifest_exists": release_report["manifest_exists"],
                    "config_exists": release_report["config_exists"],
                    "manifest_counts": release_report.get("manifest_counts") or {},
                    "translation_count": release_report["translation_count"],
                    "dictionary_count": release_report["dictionary_count"],
                    "locale_codes": release_report["locale_codes"],
                    "issues": release_report["issues"],
                    "missing_in_release": [
                        self._format_translation_record(item)
                        for item in release_report["missing_in_release"]
                    ],
                    "only_in_release": [
                        self._format_translation_record(item)
                        for item in release_report["only_in_release"]
                    ],
                    "locale_content_issues": [
                        {
                            "language": issue["language"],
                            "missing": [
                                self._format_locale_record(item)
                                for item in issue["missing"]
                            ],
                            "extra": [
                                self._format_locale_record(item)
                                for item in issue["extra"]
                            ],
                        }
                        for issue in release_report["locale_content_issues"]
                    ],
                },
                "hardcoded_copy": {
                    "namespace_filter": namespace_filter,
                    "total_found": total_found,
                    "occurrences_total": len(occurrences),
                    "tracked_occurrences": tracked_occurrences,
                    "missing_occurrences": missing_occurrences,
                    "indexed_total": indexed_total,
                    "missing_total": missing_total,
                    "by_kind": by_kind,
                    "by_namespace": [
                        {
                            "namespace": namespace,
                            "found": len(found_strings[namespace]),
                            "indexed": sum(
                                1
                                for string in found_strings[namespace]
                                if (namespace, self._make_key(string)) in existing_de
                            ),
                            "missing": len(found_strings[namespace]) - sum(
                                1
                                for string in found_strings[namespace]
                                if (namespace, self._make_key(string)) in existing_de
                            ),
                        }
                        for namespace in sorted(found_strings.keys())
                    ],
                    "details": occurrences[:limit],
                },
            }
            return ok, json.dumps(payload, indent=2, ensure_ascii=False)

        output = [
            "=== I18N-DRIFT REPORT ===",
            "",
            "Release-Artefakte:",
            f"  Config: {'OK' if release_report['config_exists'] else 'FEHLT'}",
            f"  Manifest: {'OK' if release_report['manifest_exists'] else 'FEHLT'}",
            f"  Locale-Dateien: {len(release_report['locale_codes'])} ({', '.join(release_report['locale_codes']) if release_report['locale_codes'] else 'keine'})",
            f"  Translation-Export: {release_report['translation_count']}",
            f"  Dictionary-Export: {release_report['dictionary_count']}",
        ]

        manifest_counts = release_report.get("manifest_counts") or {}
        if manifest_counts:
            output.extend([
                f"  Manifest-Count Translations: {manifest_counts.get('translations', 0)}",
                f"  Manifest-Count Dictionary:   {manifest_counts.get('dictionary_entries', 0)}",
                f"  Manifest-Count Locales:      {manifest_counts.get('locale_files', 0)}",
            ])

        if release_report["issues"]:
            output.append("  Abweichungen:")
            for issue in release_report["issues"]:
                output.append(f"    - {issue}")
        else:
            output.append("  Abweichungen: keine")

        if release_report["missing_in_release"]:
            output.append("  DB fehlt im Release-Export:")
            for item in release_report["missing_in_release"][:5]:
                output.append(f"    - {self._format_translation_record(item)}")
            if len(release_report["missing_in_release"]) > 5:
                output.append(f"    ... +{len(release_report['missing_in_release']) - 5} weitere")

        if release_report["only_in_release"]:
            output.append("  Nur im Release-Export:")
            for item in release_report["only_in_release"][:5]:
                output.append(f"    - {self._format_translation_record(item)}")
            if len(release_report["only_in_release"]) > 5:
                output.append(f"    ... +{len(release_report['only_in_release']) - 5} weitere")

        if release_report["locale_content_issues"]:
            output.append("  Locale-Inhaltsdrift:")
            for issue in release_report["locale_content_issues"][:3]:
                output.append(
                    f"    - {issue['language']}: {len(issue['missing'])} fehlend, {len(issue['extra'])} extra"
                )
                for item in issue["missing"][:2]:
                    output.append(f"      fehlend: {self._format_locale_record(item)}")
                for item in issue["extra"][:2]:
                    output.append(f"      extra: {self._format_locale_record(item)}")
            if len(release_report["locale_content_issues"]) > 3:
                output.append(
                    f"    ... +{len(release_report['locale_content_issues']) - 3} weitere Sprache(n)"
                )

        output.extend([
            "",
            "Hardcoded Copy:",
            f"  Gefundene Strings: {total_found}",
            f"  Fundstellen: {len(occurrences)}",
            f"  Indexierte Fundstellen: {tracked_occurrences}",
            f"  Offene Fundstellen: {missing_occurrences}",
            f"  Bereits indexiert: {indexed_total}",
            f"  Offene DE-Eintraege: {missing_total}",
            "",
            "Nach Namespace:",
        ])
        output.extend(namespace_lines or ["  keine"])

        if by_kind:
            output.extend([
                "",
                "Nach Typ:",
            ])
            for kind, count in sorted(by_kind.items()):
                output.append(f"  {kind}: {count}")

        if occurrences:
            output.extend([
                "",
                "Beispiele:",
            ])
            for item in occurrences[:limit]:
                status = "indexiert" if item["tracked"] else "offen"
                output.append(
                    f"  [{status}] {item['file']}:{item['line']} "
                    f"({item['kind']}) -> {item['text']}"
                )

        return ok, "\n".join(output)

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
        source_lang = self._get_source_language(args)
        target_lang = self._get_target_language(args)

        conn = self._get_db()
        try:
            rows = self._get_missing_rows(conn, limit=100, source_lang=source_lang, target_lang=target_lang)

            if not rows:
                return (True, f"[LANG] Alle {source_lang}-Strings haben {target_lang}-Uebersetzungen!")

            output = [
                f"[LANG] {len(rows)} fehlende {target_lang}-Uebersetzung(en) fuer {source_lang}:",
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
            output.append(f"  bach lang translate --target {target_lang} --source windows_dict   Auto-Uebersetzen")
            output.append(f"  bach lang export --target {target_lang}                            Fuer LLM-Review")

            return (True, "\n".join(output))

        finally:
            conn.close()

    def _translate(self, args: list, dry_run: bool) -> tuple:
        """Startet Auto-Uebersetzung."""
        source = self._get_arg(args, "--source") or "windows_dict"
        limit = int(self._get_arg(args, "--limit") or "100")
        source_lang = self._get_source_language(args)
        target_lang = self._get_target_language(args)

        if source not in self.SOURCE_PRIORITY:
            return (False, f"[ERROR] Unbekannte Quelle: {source}\nVerfuegbar: {', '.join(self.SOURCE_PRIORITY.keys())}")

        conn = self._get_db()
        try:
            # Fehlende Uebersetzungen holen
            rows = self._get_missing_rows(conn, limit=limit, source_lang=source_lang, target_lang=target_lang)

            if not rows:
                return (True, "[LANG] Keine fehlenden Uebersetzungen gefunden.")

            translated = 0
            skipped = 0

            for r in rows:
                de_text = r['de_value']
                translated_text = None

                if source == "windows_dict":
                    # Versuche einfache Woerterbuch-Uebersetzung
                    translated_text = self._translate_with_dict(de_text, conn, source_lang, target_lang)
                elif source == "llm":
                    # LLM-Uebersetzung wird als Batch exportiert
                    skipped += 1
                    continue

                if translated_text and not dry_run:
                    # Einfuegen
                    conn.execute("""
                        INSERT INTO languages_translations
                        (key, namespace, language, value, is_verified, source, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                    """, (
                        r['key'],
                        r['namespace'],
                        target_lang,
                        translated_text,
                        source,
                        datetime.now().isoformat(),
                        datetime.now().isoformat(),
                    ))
                    translated += 1
                elif translated_text:
                    translated += 1  # Dry-run count
                else:
                    skipped += 1

            if not dry_run:
                conn.commit()
                if translated > 0:
                    self._ensure_languages_enabled(conn, [target_lang])
                    self._write_release_exports(conn)

            prefix = "[DRY-RUN] " if dry_run else ""
            return (True, f"{prefix}[LANG] Uebersetzung abgeschlossen:\n  Uebersetzt: {translated}\n  Uebersprungen: {skipped}\n  Sprachpaar: {source_lang}->{target_lang}\n  Quelle: {source}")

        finally:
            conn.close()

    def _translate_with_dict(self, de_text: str, conn, source_lang: str, target_lang: str) -> Optional[str]:
        """Versucht Uebersetzung mit Woerterbuch."""
        # Zuerst im eigenen Woerterbuch suchen
        row = conn.execute("""
            SELECT translation FROM languages_dictionary
            WHERE term = ? AND source_lang = ? AND target_lang = ?
            AND is_preferred = 1
            ORDER BY usage_count DESC LIMIT 1
        """, (de_text.lower(), source_lang, target_lang)).fetchone()

        if row:
            return row['translation']

        # Fallback: Wort-fuer-Wort fuer einfache Texte
        # (Nur fuer sehr kurze, einfache Strings)
        if len(de_text) < 30 and ' ' not in de_text:
            word_row = conn.execute("""
                SELECT translation FROM languages_dictionary
                WHERE term = ? AND source_lang = ? AND target_lang = ?
                ORDER BY usage_count DESC LIMIT 1
            """, (de_text.lower(), source_lang, target_lang)).fetchone()

            if word_row:
                return word_row['translation']

        return None

    def _add(self, args: list, dry_run: bool) -> tuple:
        """Fuegt manuell eine Uebersetzung hinzu."""
        if not args:
            return (False, "Fehler: Key fehlt.\n\nBeispiel: bach lang add mein_key --de \"Mein Text\" --en \"My text\"")

        key = args[0]
        namespace = self._get_arg(args, "--namespace") or self._get_arg(args, "-n") or "general"
        translations = self._collect_add_translations(args)

        if not translations:
            return (False, "Fehler: Mindestens eine Sprachversion muss angegeben werden (z.B. --de, --en, --es oder --lang <code> --text <wert>).")

        if dry_run:
            lines = [f"[DRY-RUN] Wuerde hinzufuegen:", f"  Key: {key}", f"  Namespace: {namespace}"]
            for lang_code, value in sorted(translations.items()):
                lines.append(f"  {lang_code.upper()}: {value}")
            return (True, "\n".join(lines))

        conn = self._get_db()
        try:
            now = datetime.now().isoformat()
            self._ensure_languages_enabled(conn, list(translations.keys()))

            for lang_code, value in translations.items():
                conn.execute("""
                    INSERT OR REPLACE INTO languages_translations
                    (key, namespace, language, value, is_verified, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, 'manual', ?, ?)
                """, (key, namespace, lang_code, value, now, now))

            conn.commit()
            self._write_release_exports(conn)
            return (True, f"[OK] Uebersetzung hinzugefuegt: {key}")

        finally:
            conn.close()

    def _add_language(self, args: list, dry_run: bool) -> tuple:
        """Fuegt eine neue Sprache zum System hinzu."""
        if not args:
            return (False, "Fehler: Sprach-Code fehlt.\n\nBeispiel: bach lang add-language fr")

        lang_code = self._normalize_language_code(args[0], "")

        # Validierung: 2-3 Buchstaben
        if not lang_code:
            return (False, f"[ERROR] Ungueltiger Sprach-Code: {lang_code}\nErwartet: 2-3 Kleinbuchstaben (z.B. fr, es, pt)")

        conn = self._get_db()
        try:
            enabled_langs = self._get_enabled_languages(conn, include_detected=False)

            # Pruefen ob bereits vorhanden
            if lang_code in enabled_langs:
                return (False, f"[ERROR] Sprache '{lang_code}' ist bereits aktiviert.\nAktiv: {', '.join(enabled_langs)}")

            # Hinzufuegen
            enabled_langs.append(lang_code)

            if dry_run:
                return (True, f"[DRY-RUN] Wuerde Sprache hinzufuegen: {lang_code}\nNeue Liste: {', '.join(enabled_langs)}")

            self._ensure_languages_enabled(conn, [lang_code])
            conn.commit()
            self._write_release_exports(conn)
            return (True, f"[OK] Sprache hinzugefuegt: {lang_code}\nAktivierte Sprachen: {', '.join(enabled_langs)}")

        except json.JSONDecodeError as e:
            return (False, f"[ERROR] enabled_languages JSON kaputt: {e}")
        finally:
            conn.close()

    def _export(self, args: list) -> tuple:
        """Exportiert fehlende Uebersetzungen fuer LLM-Review."""
        format_type = self._get_arg(args, "--format") or "prompt"
        output_file = self._get_arg(args, "--file")
        source_lang = self._get_source_language(args)
        target_lang = self._get_target_language(args)

        conn = self._get_db()
        try:
            rows = self._get_missing_rows(conn, source_lang=source_lang, target_lang=target_lang)

            if not rows:
                return (True, f"[LANG] Keine fehlenden {target_lang}-Uebersetzungen zum Exportieren.")

            if format_type == "json":
                # JSON-Format
                export_data = []
                for r in rows:
                    export_data.append({
                        "key": r['key'],
                        "namespace": r['namespace'],
                        "source_language": source_lang,
                        "target_language": target_lang,
                        source_lang: r['de_value'],
                        target_lang: ""
                    })
                output = json.dumps(export_data, indent=2, ensure_ascii=False)
            else:
                # Prompt-Format fuer LLM
                output_lines = [
                    "# BACH Translation Request",
                    "",
                    f"Bitte uebersetze die folgenden {source_lang}-Texte nach {target_lang} ({self._lang_label(target_lang)}).",
                    "Behalte technische Begriffe (CLI-Befehle, Variablen) bei.",
                    f"Format: KEY | {source_lang.upper()} | {target_lang.upper()}",
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
                    f"Bitte fuege die {target_lang}-Uebersetzungen nach dem letzten | ein.",
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
        imported_languages = set()
        target_lang = self._get_target_language(args)

        conn = self._get_db()
        try:
            # Versuche JSON
            if file_path.suffix == '.json' or content.strip().startswith('['):
                data = json.loads(content)
                for item in data:
                    translations = self._collect_import_translations(item)
                    source = item.get('source') or 'llm_reviewed'
                    namespace = item.get('namespace', 'general')
                    source_lang = self._normalize_language_code(item.get("source_language"), DEFAULT_SOURCE_LANGUAGE)
                    for lang_code, value in translations.items():
                        if lang_code == source_lang:
                            continue
                        if not dry_run:
                            conn.execute("""
                                INSERT OR REPLACE INTO languages_translations
                                (key, namespace, language, value, is_verified, source, created_at, updated_at)
                                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                            """, (
                                item['key'],
                                namespace,
                                lang_code,
                                value,
                                source,
                                datetime.now().isoformat(),
                                datetime.now().isoformat()
                            ))
                        imported += 1
                        imported_languages.add(lang_code)
            else:
                # Pipe-Format (KEY | DE | EN)
                for line in content.split('\n'):
                    if '|' in line and not line.startswith('#') and not line.startswith('-'):
                        parts = [p.strip() for p in line.split('|')]
                        if len(parts) >= 3 and parts[2]:  # Hat englische Uebersetzung
                            key = parts[0]
                            translated_text = parts[2]

                            # Namespace aus existierendem DE-Eintrag holen
                            ns_row = conn.execute("""
                                SELECT namespace FROM languages_translations
                                WHERE key = ? AND language = ? LIMIT 1
                            """, (key, DEFAULT_SOURCE_LANGUAGE)).fetchone()
                            namespace = ns_row['namespace'] if ns_row else 'general'

                            if not dry_run:
                                conn.execute("""
                                    INSERT OR REPLACE INTO languages_translations
                                    (key, namespace, language, value, is_verified, source, created_at, updated_at)
                                    VALUES (?, ?, ?, ?, 0, 'llm_reviewed', ?, ?)
                                """, (key, namespace, target_lang, translated_text, datetime.now().isoformat(), datetime.now().isoformat()))
                            imported += 1
                            imported_languages.add(target_lang)

            if not dry_run:
                if imported_languages:
                    self._ensure_languages_enabled(conn, list(imported_languages))
                conn.commit()
                if imported > 0:
                    self._write_release_exports(conn)

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
            self._write_release_exports(conn)

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
                "  bach lang dict add <quelle> <ziel> [--source-lang de --target-lang en]",
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
            if added > 0:
                self._write_release_exports(conn)
            return (True, f"[DICT] Woerterbuch initialisiert:\n  Hinzugefuegt: {added}\n  Bereits vorhanden: {skipped}")

        finally:
            conn.close()

    def _dict_add(self, args: list, dry_run: bool) -> tuple:
        """Fuegt Woerterbuch-Eintrag hinzu."""
        if len(args) < 2:
            return (False, "Fehler: de und en Term erforderlich.\n\nBeispiel: bach lang dict add datei file")

        source_term = args[0].lower()
        target_term = args[1].lower()
        source_lang = self._normalize_language_code(
            self._get_arg(args, "--source-lang") or self._get_arg(args, "--from"),
            DEFAULT_SOURCE_LANGUAGE,
        )
        target_lang = self._normalize_language_code(
            self._get_arg(args, "--target-lang") or self._get_arg(args, "--to"),
            DEFAULT_TARGET_LANGUAGE,
        )

        if dry_run:
            return (True, f"[DRY-RUN] Wuerde hinzufuegen: {source_term} ({source_lang}) -> {target_term} ({target_lang})")

        conn = self._get_db()
        try:
            now = datetime.now().isoformat()

            # INSERT OR REPLACE
            conn.execute("""
                INSERT OR REPLACE INTO languages_dictionary
                (term, translation, source_lang, target_lang, is_preferred, usage_count, context, created_at)
                VALUES (?, ?, ?, ?, 1, 0, 'manual', ?)
            """, (source_term, target_term, source_lang, target_lang, now))

            conn.commit()
            self._write_release_exports(conn)
            return (True, f"[DICT] Hinzugefuegt: {source_term} ({source_lang}) -> {target_term} ({target_lang})")

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
