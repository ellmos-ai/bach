# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for LangHandler (hub/lang.py)."""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.lang import LangHandler


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

LANG_SCHEMA = """
CREATE TABLE IF NOT EXISTS languages_config (
    id INTEGER PRIMARY KEY,
    default_language TEXT DEFAULT 'de',
    fallback_language TEXT DEFAULT 'en',
    auto_translate INTEGER DEFAULT 0,
    enabled_languages TEXT DEFAULT '["de","en"]',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS languages_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    namespace TEXT DEFAULT 'general',
    language TEXT NOT NULL,
    value TEXT,
    is_verified INTEGER DEFAULT 0,
    source TEXT DEFAULT 'auto_detected',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS languages_dictionary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    translation TEXT NOT NULL,
    source_lang TEXT DEFAULT 'de',
    target_lang TEXT DEFAULT 'en',
    is_preferred INTEGER DEFAULT 1,
    usage_count INTEGER DEFAULT 0,
    context TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, type TEXT, category TEXT, path TEXT,
    description TEXT, is_active INTEGER DEFAULT 1,
    version TEXT, dist_type INTEGER DEFAULT 0
);
"""


def _create_db(db_path: Path):
    """Creates a test DB with lang tables."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(LANG_SCHEMA)
    conn.execute("""
        INSERT OR IGNORE INTO languages_config (id, default_language, fallback_language, auto_translate, enabled_languages)
        VALUES (1, 'de', 'en', 0, '["de","en"]')
    """)
    conn.commit()
    conn.close()


def _create_db_with_data(db_path: Path):
    """Creates a test DB with sample translations and dictionary entries."""
    _create_db(db_path)
    conn = sqlite3.connect(str(db_path))

    conn.execute("""
        INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
        VALUES ('speichern', 'cli', 'de', 'Speichern', 1, 'manual', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
        VALUES ('speichern', 'cli', 'en', 'Save', 1, 'manual', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
        VALUES ('loeschen', 'cli', 'de', 'Loeschen', 0, 'auto_detected', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
        VALUES ('oeffnen', 'gui', 'de', 'Oeffnen', 0, 'auto_detected', '2026-01-01')
    """)

    conn.execute("""
        INSERT INTO languages_dictionary (term, translation, source_lang, target_lang, is_preferred, usage_count, context, created_at)
        VALUES ('datei', 'file', 'de', 'en', 1, 5, 'base_dictionary', '2026-01-01')
    """)
    conn.execute("""
        INSERT INTO languages_dictionary (term, translation, source_lang, target_lang, is_preferred, usage_count, context, created_at)
        VALUES ('ordner', 'folder', 'de', 'en', 1, 3, 'base_dictionary', '2026-01-01')
    """)

    conn.commit()
    conn.close()


def _load_release_export(system_dir: Path, filename: str):
    """Loads a generated release export artifact."""
    export_file = system_dir / "exports" / "translations" / filename
    assert export_file.exists()
    return json.loads(export_file.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def lang_env(tmp_path):
    """Minimal environment for LangHandler."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "data").mkdir()
    (system_dir / "hub").mkdir()
    db_path = system_dir / "data" / "bach.db"
    _create_db(db_path)
    return system_dir


@pytest.fixture
def handler(lang_env):
    """LangHandler with empty DB."""
    h = LangHandler(lang_env)
    h.db_path = lang_env / "data" / "bach.db"
    return h


@pytest.fixture
def handler_with_data(lang_env):
    """LangHandler with sample data."""
    db_path = lang_env / "data" / "bach.db"
    _create_db_with_data(db_path)
    h = LangHandler(lang_env)
    h.db_path = db_path
    return h


# ═══════════════════════════════════════════════════════════════
# BASIC PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "lang"

    def test_target_file(self, handler):
        assert handler.target_file == handler.db_path

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        for key in ["status", "scan", "report", "list", "missing", "translate",
                     "add", "add-language", "export", "import", "set", "dict", "help"]:
            assert key in ops


class TestAppInit:
    def test_init_with_app_object(self, lang_env):
        app = MagicMock()
        app.base_path = lang_env
        app.db = MagicMock()
        h = LangHandler(app)
        assert h.base_path == lang_env


# ═══════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════


class TestRouting:
    def test_help_operation(self, handler):
        ok, msg = handler.handle("help", [], dry_run=False)
        assert ok is True
        assert "LANG" in msg
        assert "BEFEHLE" in msg

    def test_empty_operation_shows_help(self, handler):
        ok, msg = handler.handle("", [], dry_run=False)
        assert ok is True
        assert "LANG" in msg

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [], dry_run=False)
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_report_operation(self, handler):
        ok, msg = handler.handle("report", [], dry_run=False)
        assert ok is False
        assert "I18N-DRIFT REPORT" in msg


# ═══════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_empty_db(self, handler):
        ok, msg = handler.handle("status", [], dry_run=False)
        assert ok is True
        assert "SPRACH-SYSTEM STATUS" in msg
        assert "Standard-Sprache" in msg
        assert "Gesamt-Eintraege" in msg

    def test_status_with_data(self, handler_with_data):
        ok, msg = handler_with_data.handle("status", [], dry_run=False)
        assert ok is True
        assert "Gesamt-Eintraege:  4" in msg
        assert "Verifiziert:       2" in msg


class TestReportDetails:
    def test_report_detects_missing_release_artifacts(self, handler):
        ok, msg = handler.handle("report", [], dry_run=False)
        assert ok is False
        assert "Config-Export fehlt" in msg
        assert "Manifest fehlt" in msg

    def test_report_ok_after_release_exports_exist(self, handler):
        ok, _ = handler.handle("add", ["gruss", "--de", "Grüße", "--en", "Greetings"], dry_run=False)
        assert ok is True

        ok, msg = handler.handle("report", [], dry_run=False)
        assert ok is True
        assert "Abweichungen: keine" in msg

    def test_report_json_detects_translation_and_locale_drift(self, handler):
        ok, _ = handler.handle("add", ["save_button", "--de", "Speichern", "--en", "Save"], dry_run=False)
        assert ok is True

        translations_path = handler.base_path / "exports" / "translations" / "languages_translations.release.json"
        translations = json.loads(translations_path.read_text(encoding="utf-8"))
        for row in translations:
            if row["key"] == "save_button" and row["language"] == "en":
                row["value"] = "Save now"
        translations_path.write_text(json.dumps(translations, indent=2, ensure_ascii=False), encoding="utf-8")

        ok, msg = handler.handle("report", ["--json"], dry_run=False)
        payload = json.loads(msg)

        assert ok is False
        assert payload["ok"] is False
        assert payload["release"]["missing_in_release"]
        assert payload["release"]["only_in_release"]
        assert payload["release"]["locale_content_issues"]


# ═══════════════════════════════════════════════════════════════
# _is_german
# ═══════════════════════════════════════════════════════════════


class TestIsGerman:
    def test_empty_string(self, handler):
        assert handler._is_german("") is False

    def test_short_string(self, handler):
        assert handler._is_german("ab") is False

    def test_umlaut_detected(self, handler):
        assert handler._is_german("Datei öffnen") is True
        assert handler._is_german("Größe ändern") is True

    def test_german_keyword(self, handler):
        assert handler._is_german("Datei nicht gefunden") is True
        assert handler._is_german("Einstellungen speichern") is True

    def test_english_text(self, handler):
        assert handler._is_german("Save file") is False
        assert handler._is_german("Open dialog") is False

    def test_sz_detected(self, handler):
        assert handler._is_german("Straße") is True


# ═══════════════════════════════════════════════════════════════
# _make_key
# ═══════════════════════════════════════════════════════════════


class TestMakeKey:
    def test_simple_text(self, handler):
        assert handler._make_key("Datei speichern") == "datei_speichern"

    def test_special_chars_replaced(self, handler):
        assert handler._make_key("Fehler: Datei!") == "fehler_datei"

    def test_truncated_at_50(self, handler):
        long_text = "a" * 100
        key = handler._make_key(long_text)
        assert len(key) <= 50

    def test_no_trailing_underscores(self, handler):
        assert not handler._make_key("test!").endswith("_")


# ═══════════════════════════════════════════════════════════════
# _get_arg
# ═══════════════════════════════════════════════════════════════


class TestGetArg:
    def test_flag_with_value(self, handler):
        assert handler._get_arg(["--lang", "en"], "--lang") == "en"

    def test_flag_with_equals(self, handler):
        assert handler._get_arg(["--lang=en"], "--lang") == "en"

    def test_missing_flag(self, handler):
        assert handler._get_arg(["--other", "x"], "--lang") is None

    def test_flag_at_end_without_value(self, handler):
        assert handler._get_arg(["--lang"], "--lang") is None


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [], dry_run=False)
        assert ok is True
        assert "Keine Uebersetzungen" in msg

    def test_list_with_data(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", [], dry_run=False)
        assert ok is True
        assert "4 Uebersetzung" in msg

    def test_list_filter_by_lang(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", ["--lang", "en"], dry_run=False)
        assert ok is True
        assert "1 Uebersetzung" in msg

    def test_list_filter_by_namespace(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", ["--namespace", "gui"], dry_run=False)
        assert ok is True
        assert "1 Uebersetzung" in msg


# ═══════════════════════════════════════════════════════════════
# MISSING
# ═══════════════════════════════════════════════════════════════


class TestMissing:
    def test_missing_empty_db(self, handler):
        ok, msg = handler.handle("missing", [], dry_run=False)
        assert ok is True
        assert "Alle de-Strings" in msg

    def test_missing_with_data(self, handler_with_data):
        ok, msg = handler_with_data.handle("missing", [], dry_run=False)
        assert ok is True
        assert "fehlende" in msg
        assert "loeschen" in msg or "oeffnen" in msg

    def test_missing_respects_namespace(self, handler):
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("""
            INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
            VALUES ('shared_key', 'cli', 'de', 'Konfiguration', 0, 'auto_detected', '2026-01-01')
        """)
        conn.execute("""
            INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
            VALUES ('shared_key', 'help', 'en', 'Configuration', 0, 'llm_reviewed', '2026-01-01')
        """)
        conn.commit()
        conn.close()

        ok, msg = handler.handle("missing", [], dry_run=False)
        assert ok is True
        assert "shared_key" in msg


# ═══════════════════════════════════════════════════════════════
# ADD
# ═══════════════════════════════════════════════════════════════


class TestAdd:
    def test_add_no_args(self, handler):
        ok, msg = handler.handle("add", [], dry_run=False)
        assert ok is False
        assert "Key fehlt" in msg

    def test_add_no_text(self, handler):
        ok, msg = handler.handle("add", ["test_key"], dry_run=False)
        assert ok is False
        assert "Sprachversion" in msg

    def test_add_dry_run(self, handler):
        ok, msg = handler.handle("add", ["test_key", "--de", "Test", "--en", "Test"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_add_de_and_en(self, handler):
        ok, msg = handler.handle("add", ["gruss", "--de", "Hallo", "--en", "Hello"], dry_run=False)
        assert ok is True
        assert "hinzugefuegt" in msg

        conn = sqlite3.connect(str(handler.db_path))
        conn.row_factory = sqlite3.Row
        de_row = conn.execute(
            "SELECT value FROM languages_translations WHERE key='gruss' AND language='de'"
        ).fetchone()
        en_row = conn.execute(
            "SELECT value FROM languages_translations WHERE key='gruss' AND language='en'"
        ).fetchone()
        conn.close()
        assert de_row["value"] == "Hallo"
        assert en_row["value"] == "Hello"

    def test_add_only_de(self, handler):
        ok, msg = handler.handle("add", ["nur_de", "--de", "Nur Deutsch"], dry_run=False)
        assert ok is True
        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute(
            "SELECT COUNT(*) FROM languages_translations WHERE key='nur_de'"
        ).fetchone()
        conn.close()
        assert row[0] == 1

    def test_add_refreshes_release_exports(self, handler):
        ok, msg = handler.handle("add", ["gruss", "--de", "Grüße", "--en", "Greetings"], dry_run=False)
        assert ok is True
        assert "hinzugefuegt" in msg

        manifest = _load_release_export(handler.base_path, "manifest.release.json")
        translations = _load_release_export(handler.base_path, "languages_translations.release.json")
        locale_en = json.loads((handler.base_path / "exports" / "translations" / "locales" / "en.json").read_text(encoding="utf-8"))

        assert manifest["source_db"] == "runtime_db"
        assert manifest["counts"]["translations"] == 2
        assert any(row["key"] == "gruss" and row["language"] == "de" and row["value"] == "Grüße" for row in translations)
        assert any(row["key"] == "gruss" and row["language"] == "en" and row["value"] == "Greetings" for row in translations)
        assert locale_en["entries"]["general"]["gruss"] == "Greetings"

    def test_release_exports_redact_local_onedrive_paths(self, handler):
        local_path = r'base_dir = Path(r"C:\Users\Example\OneDrive\PrivateProject")'
        ok, msg = handler.handle("add", ["legacy_path", "--de", local_path], dry_run=False)
        assert ok is True

        translations = _load_release_export(handler.base_path, "languages_translations.release.json")
        row = next(item for item in translations if item["key"] == "legacy_path")
        assert "C:\\Users\\Example\\OneDrive" not in row["value"]
        assert "<BACH_WORKSPACE>" in row["value"]

    def test_release_exports_redact_userprofile_paths(self, handler):
        local_path = r"Log: C:\Users\Example\Downloads\bach.log"
        ok, msg = handler.handle("add", ["userprofile_path", "--de", local_path], dry_run=False)
        assert ok is True

        translations = _load_release_export(handler.base_path, "languages_translations.release.json")
        row = next(item for item in translations if item["key"] == "userprofile_path")
        assert "C:\\Users\\Example" not in row["value"]
        assert "%USERPROFILE%" in row["value"]


# ═══════════════════════════════════════════════════════════════
# ADD-LANGUAGE
# ═══════════════════════════════════════════════════════════════


class TestAddLanguage:
    def test_add_language_no_args(self, handler):
        ok, msg = handler.handle("add-language", [], dry_run=False)
        assert ok is False
        assert "Sprach-Code fehlt" in msg

    def test_add_language_invalid_code(self, handler):
        ok, msg = handler.handle("add-language", ["1234"], dry_run=False)
        assert ok is False
        assert "Ungueltiger Sprach-Code" in msg

    def test_add_language_dry_run(self, handler):
        ok, msg = handler.handle("add-language", ["fr"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        assert "fr" in msg

    def test_add_language_success(self, handler):
        ok, msg = handler.handle("add-language", ["fr"], dry_run=False)
        assert ok is True
        assert "fr" in msg

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT enabled_languages FROM languages_config LIMIT 1").fetchone()
        conn.close()
        langs = json.loads(row[0])
        assert "fr" in langs

    def test_add_language_duplicate(self, handler):
        ok, msg = handler.handle("add-language", ["en"], dry_run=False)
        assert ok is False
        assert "bereits aktiviert" in msg

    def test_add_language_refreshes_release_exports(self, handler):
        ok, msg = handler.handle("add-language", ["fr"], dry_run=False)
        assert ok is True
        assert "fr" in msg

        config = _load_release_export(handler.base_path, "languages_config.release.json")
        manifest = _load_release_export(handler.base_path, "manifest.release.json")

        assert "fr" in config["enabled_languages"]
        assert manifest["counts"]["config_rows"] == 1


# ═══════════════════════════════════════════════════════════════
# SET LANGUAGE
# ═══════════════════════════════════════════════════════════════


class TestSetLanguage:
    def test_set_no_args(self, handler):
        ok, msg = handler.handle("set", [], dry_run=False)
        assert ok is False
        assert "Sprache fehlt" in msg

    def test_set_invalid_language(self, handler):
        ok, msg = handler.handle("set", ["xx"], dry_run=False)
        assert ok is False
        assert "Ungueltige Sprache" in msg

    def test_set_dry_run(self, handler):
        ok, msg = handler.handle("set", ["en"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    @patch("hub.lang.clear_t_cache")
    def test_set_en(self, mock_clear, handler):
        ok, msg = handler.handle("set", ["en"], dry_run=False)
        assert ok is True
        assert "en" in msg
        mock_clear.assert_called_once()

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT default_language FROM languages_config LIMIT 1").fetchone()
        conn.close()
        assert row[0] == "en"


# ═══════════════════════════════════════════════════════════════
# TRANSLATE
# ═══════════════════════════════════════════════════════════════


class TestTranslate:
    def test_translate_unknown_source(self, handler):
        ok, msg = handler.handle("translate", ["--source", "fake"], dry_run=False)
        assert ok is False
        assert "Unbekannte Quelle" in msg

    def test_translate_empty_db(self, handler):
        ok, msg = handler.handle("translate", [], dry_run=False)
        assert ok is True
        assert "Keine fehlenden" in msg

    def test_translate_with_dict_match(self, handler_with_data):
        conn = sqlite3.connect(str(handler_with_data.db_path))
        conn.execute("""
            INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
            VALUES ('datei', 'cli', 'de', 'datei', 0, 'auto_detected', '2026-01-01')
        """)
        conn.commit()
        conn.close()

        ok, msg = handler_with_data.handle("translate", ["--source", "windows_dict"], dry_run=False)
        assert ok is True
        assert "Uebersetzt:" in msg

    def test_translate_dry_run(self, handler_with_data):
        ok, msg = handler_with_data.handle("translate", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg


# ═══════════════════════════════════════════════════════════════
# DICT
# ═══════════════════════════════════════════════════════════════


class TestDict:
    def test_dict_status_empty(self, handler):
        ok, msg = handler.handle("dict", ["status"], dry_run=False)
        assert ok is True
        assert "WOERTERBUCH STATUS" in msg
        assert "Gesamt-Eintraege: 0" in msg

    def test_dict_status_with_data(self, handler_with_data):
        ok, msg = handler_with_data.handle("dict", ["status"], dry_run=False)
        assert ok is True
        assert "Gesamt-Eintraege: 2" in msg

    def test_dict_init_dry_run(self, handler):
        ok, msg = handler.handle("dict", ["init"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_dict_init(self, handler):
        ok, msg = handler.handle("dict", ["init"], dry_run=False)
        assert ok is True
        assert "initialisiert" in msg

        conn = sqlite3.connect(str(handler.db_path))
        count = conn.execute("SELECT COUNT(*) FROM languages_dictionary").fetchone()[0]
        conn.close()
        assert count == len(LangHandler.BASE_DICTIONARY)

    def test_dict_init_idempotent(self, handler):
        handler.handle("dict", ["init"], dry_run=False)
        ok, msg = handler.handle("dict", ["init"], dry_run=False)
        assert ok is True
        assert "Bereits vorhanden:" in msg

        conn = sqlite3.connect(str(handler.db_path))
        count = conn.execute("SELECT COUNT(*) FROM languages_dictionary").fetchone()[0]
        conn.close()
        assert count == len(LangHandler.BASE_DICTIONARY)

    def test_dict_add_no_args(self, handler):
        ok, msg = handler.handle("dict", ["add"], dry_run=False)
        assert ok is False
        assert "de und en Term" in msg

    def test_dict_add_success(self, handler):
        ok, msg = handler.handle("dict", ["add", "katze", "cat"], dry_run=False)
        assert ok is True
        assert "katze" in msg
        assert "cat" in msg

    def test_dict_add_refreshes_release_exports(self, handler):
        ok, msg = handler.handle("dict", ["add", "größe", "size"], dry_run=False)
        assert ok is True
        assert "größe" in msg

        dictionary = _load_release_export(handler.base_path, "languages_dictionary.release.json")
        manifest = _load_release_export(handler.base_path, "manifest.release.json")

        assert any(row["term"] == "größe" and row["translation"] == "size" for row in dictionary)
        assert manifest["counts"]["dictionary_entries"] == 1

    def test_dict_add_dry_run(self, handler):
        ok, msg = handler.handle("dict", ["add", "katze", "cat"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_dict_search_no_args(self, handler):
        ok, msg = handler.handle("dict", ["search"], dry_run=False)
        assert ok is False
        assert "Suchbegriff" in msg

    def test_dict_search_found(self, handler_with_data):
        ok, msg = handler_with_data.handle("dict", ["search", "datei"], dry_run=False)
        assert ok is True
        assert "datei" in msg
        assert "file" in msg

    def test_dict_search_not_found(self, handler):
        ok, msg = handler.handle("dict", ["search", "zzz_nothing"], dry_run=False)
        assert ok is True
        assert "Keine Treffer" in msg

    def test_dict_unknown_subcmd(self, handler):
        ok, msg = handler.handle("dict", ["xxx"], dry_run=False)
        assert ok is False
        assert "Unbekannter dict-Befehl" in msg


# ═══════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════


class TestExport:
    def test_export_empty_db(self, handler):
        ok, msg = handler.handle("export", [], dry_run=False)
        assert ok is True
        assert "Keine fehlenden" in msg

    def test_export_prompt_format(self, handler_with_data):
        ok, msg = handler_with_data.handle("export", [], dry_run=False)
        assert ok is True
        assert "Translation Request" in msg
        assert "loeschen" in msg or "oeffnen" in msg

    def test_export_json_format(self, handler_with_data):
        ok, msg = handler_with_data.handle("export", ["--format", "json"], dry_run=False)
        assert ok is True
        data = json.loads(msg)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "key" in data[0]

    def test_export_to_file(self, handler_with_data, tmp_path):
        out_file = str(tmp_path / "export.json")
        ok, msg = handler_with_data.handle("export", ["--format", "json", "--file", out_file], dry_run=False)
        assert ok is True
        assert "exportiert" in msg
        assert Path(out_file).exists()


# ═══════════════════════════════════════════════════════════════
# IMPORT
# ═══════════════════════════════════════════════════════════════


class TestImport:
    def test_import_no_args(self, handler):
        ok, msg = handler.handle("import", [], dry_run=False)
        assert ok is False
        assert "Datei fehlt" in msg

    def test_import_file_not_found(self, handler):
        ok, msg = handler.handle("import", ["/nonexistent/file.json"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_import_json(self, handler, tmp_path):
        data = [
            {"key": "test_key", "namespace": "cli", "de": "Testtext", "en": "Test text"},
            {"key": "test_key2", "namespace": "gui", "de": "Zweiter", "en": "Second"},
        ]
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(data), encoding="utf-8")

        ok, msg = handler.handle("import", [str(import_file)], dry_run=False)
        assert ok is True
        assert "2 Uebersetzungen importiert" in msg

        conn = sqlite3.connect(str(handler.db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM languages_translations WHERE source='llm_reviewed'"
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_import_json_respects_source(self, handler, tmp_path):
        data = [
            {"key": "test_key", "namespace": "cli", "de": "Testtext", "en": "Test text", "source": "mixed_auto"},
        ]
        import_file = tmp_path / "import_with_source.json"
        import_file.write_text(json.dumps(data), encoding="utf-8")

        ok, msg = handler.handle("import", [str(import_file)], dry_run=False)
        assert ok is True

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute(
            "SELECT source FROM languages_translations WHERE key='test_key' AND namespace='cli' AND language='en'"
        ).fetchone()
        conn.close()
        assert row[0] == "mixed_auto"

    def test_import_json_dry_run(self, handler, tmp_path):
        data = [{"key": "k", "en": "v"}]
        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(data), encoding="utf-8")

        ok, msg = handler.handle("import", [str(import_file)], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(handler.db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM languages_translations WHERE source='llm_reviewed'"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_import_pipe_format(self, handler, tmp_path):
        content = "test_pipe | Testtext | Test text\ntest2 | Zweiter | Second\n"
        import_file = tmp_path / "import.txt"
        import_file.write_text(content, encoding="utf-8")

        ok, msg = handler.handle("import", [str(import_file)], dry_run=False)
        assert ok is True
        assert "2 Uebersetzungen importiert" in msg


# ═══════════════════════════════════════════════════════════════
# SCAN
# ═══════════════════════════════════════════════════════════════


class TestScan:
    def test_scan_empty_dirs(self, handler):
        ok, msg = handler.handle("scan", [], dry_run=False)
        assert ok is True
        assert "STRING-SCAN ERGEBNIS" in msg

    def test_scan_finds_german_strings(self, handler):
        hub_dir = handler.base_path / "hub"
        hub_dir.mkdir(exist_ok=True)
        (hub_dir / "test_scan.py").write_text(
            'print("Datei nicht gefunden")\nreturn (False, "Fehler beim Laden")\n',
            encoding="utf-8",
        )

        ok, msg = handler.handle("scan", [], dry_run=True)
        assert ok is True
        assert "Gefunden:" in msg

    def test_scan_with_namespace_filter(self, handler):
        hub_dir = handler.base_path / "hub"
        hub_dir.mkdir(exist_ok=True)
        (hub_dir / "test_scan2.py").write_text(
            'print("Warnung: Eintrag existiert bereits")\n',
            encoding="utf-8",
        )

        ok, msg = handler.handle("scan", ["--namespace", "cli"], dry_run=True)
        assert ok is True
        assert "cli:" in msg

    def test_scan_dry_run_counts_missing_namespace_rows(self, handler):
        hub_dir = handler.base_path / "hub"
        gui_dir = handler.base_path / "gui"
        hub_dir.mkdir(exist_ok=True)
        gui_dir.mkdir(exist_ok=True)

        (hub_dir / "scan_cli.py").write_text('print("Konfiguration")\n', encoding="utf-8")
        (gui_dir / "scan_gui.py").write_text('print("Konfiguration")\n', encoding="utf-8")

        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("""
            INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
            VALUES ('konfiguration', 'cli', 'de', 'Konfiguration', 0, 'auto_detected', '2026-01-01')
        """)
        conn.commit()
        conn.close()

        ok, msg = handler.handle("scan", [], dry_run=True)
        assert ok is True
        assert "Wuerde hinzufuegen: 1" in msg

    def test_scan_help_uses_docs_help_layout(self, handler):
        help_dir = handler.base_path / "docs" / "help"
        help_dir.mkdir(parents=True, exist_ok=True)
        (help_dir / "demo.txt").write_text(
            "Hilfe zu Einstellungen\n======================\nOptionen anzeigen\n---\n",
            encoding="utf-8",
        )

        ok, msg = handler.handle("scan", ["--namespace", "help"], dry_run=True)
        assert ok is True
        assert "help:" in msg
        assert "Hilfe zu Einstellungen" in msg

    def test_scan_gui_reads_templates_and_scripts(self, handler):
        template_dir = handler.base_path / "gui" / "templates"
        script_dir = handler.base_path / "gui" / "static" / "js"
        template_dir.mkdir(parents=True, exist_ok=True)
        script_dir.mkdir(parents=True, exist_ok=True)

        (template_dir / "demo.html").write_text(
            '<h1>Datei nicht gefunden</h1><button title="Einstellungen speichern">OK</button>',
            encoding="utf-8",
        )
        (script_dir / "demo.js").write_text(
            'const warning = "Warnung: Datei nicht gefunden";\n',
            encoding="utf-8",
        )

        ok, msg = handler.handle("scan", ["--namespace", "gui"], dry_run=True)
        assert ok is True
        assert "gui:" in msg
        assert "Datei nicht gefunden" in msg or "Warnung: Datei nicht gefunden" in msg


class TestReport:
    def test_report_detects_release_artifact_drift(self, handler_with_data):
        export_dir = handler_with_data.base_path / "exports" / "translations"
        locales_dir = export_dir / "locales"
        locales_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "manifest.release.json").write_text(
            json.dumps(
                {
                    "counts": {
                        "translations": 99,
                        "dictionary_entries": 1,
                        "locale_files": 2,
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (export_dir / "languages_translations.release.json").write_text(
            json.dumps([{"key": "speichern"}], ensure_ascii=False),
            encoding="utf-8",
        )
        (export_dir / "languages_dictionary.release.json").write_text(
            json.dumps([], ensure_ascii=False),
            encoding="utf-8",
        )
        (locales_dir / "de.json").write_text("{}", encoding="utf-8")

        ok, msg = handler_with_data.handle("report", [], dry_run=False)
        assert ok is False
        assert "Abweichungen:" in msg
        assert "Fehlende Locale-Dateien: en" in msg
        assert "Translation-Count weicht ab" in msg

    def test_report_json_includes_hardcoded_occurrence_details(self, handler):
        gui_templates = handler.base_path / "gui" / "templates"
        gui_js = handler.base_path / "gui" / "static" / "js"
        gui_templates.mkdir(parents=True, exist_ok=True)
        gui_js.mkdir(parents=True, exist_ok=True)

        (gui_templates / "sample.html").write_text(
            '<h1>Status</h1>\n<button title="Bitte speichern">Speichern</button>\n',
            encoding="utf-8",
        )
        (gui_js / "sample.js").write_text(
            'alert("Warnung: Datei nicht gefunden");\n',
            encoding="utf-8",
        )

        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("""
            INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
            VALUES ('status', 'gui', 'de', 'Status', 1, 'manual', '2026-01-01')
        """)
        conn.commit()
        conn.close()

        ok, msg = handler.handle("report", ["--json", "--surface", "gui", "--limit", "10"], dry_run=False)
        assert ok is False
        payload = json.loads(msg)

        assert payload["hardcoded_copy"]["namespace_filter"] == "gui"
        assert payload["hardcoded_copy"]["occurrences_total"] >= 3
        assert payload["hardcoded_copy"]["tracked_occurrences"] >= 1
        assert payload["hardcoded_copy"]["missing_occurrences"] >= 1

        details = payload["hardcoded_copy"]["details"]
        assert any(item["file"] == "gui/templates/sample.html" and item["line"] == 1 for item in details)
        assert any(item["file"] == "gui/static/js/sample.js" and item["kind"] == "javascript" for item in details)
        assert any(item["text"] == "Status" and item["tracked"] is True for item in details)

    def test_report_text_shows_occurrence_examples(self, handler):
        gui_templates = handler.base_path / "gui" / "templates"
        gui_templates.mkdir(parents=True, exist_ok=True)
        (gui_templates / "report.html").write_text(
            '<p>Fehler beim Laden</p>\n',
            encoding="utf-8",
        )

        ok, msg = handler.handle("report", ["--surface", "gui", "--limit", "5"], dry_run=False)
        assert ok is False
        assert "Fundstellen:" in msg
        assert "Beispiele:" in msg
        assert "gui/templates/report.html:1" in msg

    def test_report_gui_js_ignores_technical_literals_but_keeps_ui_copy(self, handler):
        gui_js = handler.base_path / "gui" / "static" / "js"
        gui_js.mkdir(parents=True, exist_ok=True)
        sample = gui_js / "noise-filter.js"
        sample.write_text(
            "\n".join(
                [
                    "const statusText = document.getElementById('status-text');",
                    "const apiUrl = '/api/status';",
                    "console.error('[BACH] Dashboard-Fehler:', error);",
                    "showToast('Bitte speichern', 'error');",
                    "const fallback = task.category || 'Allgemein';",
                    "container.innerHTML = '<p class=\"loading\">Fehler beim Laden</p>';",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        ok, msg = handler.handle("report", ["--json", "--surface", "gui", "--limit", "20"], dry_run=False)
        assert ok is False
        payload = json.loads(msg)
        details = [
            item for item in payload["hardcoded_copy"]["details"]
            if item["file"] == "gui/static/js/noise-filter.js"
        ]
        texts = {item["text"] for item in details}

        assert "Bitte speichern" in texts
        assert "Allgemein" in texts
        assert "Fehler beim Laden" in texts
        assert "status-text" not in texts
        assert "/api/status" not in texts
        assert "[BACH] Dashboard-Fehler:" not in texts


# ═══════════════════════════════════════════════════════════════
# _extract_german_strings
# ═══════════════════════════════════════════════════════════════


    def test_scan_gui_uses_report_filters_for_runtime_copy(self, handler):
        gui_dir = handler.base_path / "gui"
        gui_dir.mkdir(parents=True, exist_ok=True)
        gui_js = gui_dir / "static" / "js"
        gui_js.mkdir(parents=True, exist_ok=True)

        (gui_js / "noise-filter.js").write_text(
            "\n".join(
                [
                    "const statusText = document.getElementById('status-text');",
                    "const apiUrl = '/api/status';",
                    "console.error('[BACH] Dashboard-Fehler:', error);",
                    "showToast('Bitte speichern', 'error');",
                    "const fallback = task.category || 'Allgemein';",
                    "container.innerHTML = '<p class=\"loading\">Fehler beim Laden</p>';",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (gui_dir / "server.py").write_text(
            "\n".join(
                [
                    '"""Konfiguration der automatischen Dokumenten-Sortierung"""',
                    'SQL = """UPDATE workflow_tuev SET last_tuev_date = ?"""',
                    'def fail():',
                    '    return (False, "Fehler beim Starten")',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        ok, _ = handler.handle("scan", ["--namespace", "gui"], dry_run=False)
        assert ok is True

        conn = sqlite3.connect(str(handler.db_path))
        rows = conn.execute(
            """
            SELECT value
            FROM languages_translations
            WHERE namespace = 'gui' AND language = 'de'
            ORDER BY value
            """
        ).fetchall()
        conn.close()

        values = {row[0] for row in rows}
        assert values == {
            "Allgemein",
            "Bitte speichern",
            "Fehler beim Starten",
            "Fehler beim Laden",
        }


class TestExtractGermanStrings:
    def test_extracts_print(self, handler, tmp_path):
        f = tmp_path / "test.py"
        f.write_text('print("Datei erfolgreich gespeichert")\n', encoding="utf-8")
        result = handler._extract_german_strings(f)
        assert any("gespeichert" in s for s in result)

    def test_extracts_return_tuple(self, handler, tmp_path):
        f = tmp_path / "test.py"
        f.write_text('return (True, "Einstellungen geladen")\n', encoding="utf-8")
        result = handler._extract_german_strings(f)
        assert any("Einstellungen" in s for s in result)

    def test_skips_english(self, handler, tmp_path):
        f = tmp_path / "test.py"
        f.write_text('print("File saved successfully")\n', encoding="utf-8")
        result = handler._extract_german_strings(f)
        assert len(result) == 0

    def test_handles_unreadable_file(self, handler, tmp_path):
        f = tmp_path / "test.py"
        f.write_bytes(b'\x80\x81\x82')
        result = handler._extract_german_strings(f)
        assert isinstance(result, set)


class TestExtractScriptStrings:
    def test_extract_script_strings_skips_dom_ids_and_paths(self, handler, tmp_path):
        f = tmp_path / "sample.js"
        f.write_text(
            "\n".join(
                [
                    "const statusText = document.getElementById('status-text');",
                    "const apiUrl = '/api/status';",
                    "showToast('Bitte speichern', 'success');",
                    "const fallback = task.category || 'Allgemein';",
                    "container.innerHTML = '<p class=\"loading\">Fehler beim Laden</p>';",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        result = handler._extract_script_strings(f)

        assert "Bitte speichern" in result
        assert "Allgemein" in result
        assert "Fehler beim Laden" in result
        assert "status-text" not in result
        assert "/api/status" not in result

    def test_extract_script_strings_skips_markup_class_and_id_tokens(self, handler, tmp_path):
        f = tmp_path / "markup-noise.js"
        f.write_text(
            'container.innerHTML = `<div class="header-status"><span class="status-dot" id="status-dot"></span><span id="status-text">Bitte speichern</span></div>`;\n',
            encoding="utf-8",
        )

        result = handler._extract_script_strings(f)

        assert "Bitte speichern" in result
        assert "header-status" not in result
        assert "status-dot" not in result
        assert "status-text" not in result


# ═══════════════════════════════════════════════════════════════
# _extract_help_strings
# ═══════════════════════════════════════════════════════════════


class TestExtractHelpStrings:
    def test_extracts_title(self, handler, tmp_path):
        f = tmp_path / "help.txt"
        f.write_text("Hilfe zu den Einstellungen\n===========================\n", encoding="utf-8")
        result = handler._extract_help_strings(f)
        assert "Hilfe zu den Einstellungen" in result

    def test_extracts_section_headers(self, handler, tmp_path):
        f = tmp_path / "help.txt"
        f.write_text("Titel\n===\nInhalt\nOptionen anzeigen\n---\n", encoding="utf-8")
        result = handler._extract_help_strings(f)
        assert "Optionen anzeigen" in result


# ═══════════════════════════════════════════════════════════════
# MODULE-LEVEL FUNCTIONS
# ═══════════════════════════════════════════════════════════════


class TestMultilanguage:
    def test_add_supports_additional_language_flags(self, handler):
        ok, msg = handler.handle("add", ["save_button", "--de", "Speichern", "--es", "Guardar", "--ru", "Sohranit"], dry_run=False)
        assert ok is True
        assert "hinzugefuegt" in msg

        conn = sqlite3.connect(str(handler.db_path))
        rows = conn.execute(
            "SELECT language FROM languages_translations WHERE key='save_button' ORDER BY language"
        ).fetchall()
        enabled_row = conn.execute("SELECT enabled_languages FROM languages_config LIMIT 1").fetchone()
        conn.close()

        assert {row[0] for row in rows} == {"de", "es", "ru"}
        enabled_languages = json.loads(enabled_row[0])
        assert "es" in enabled_languages
        assert "ru" in enabled_languages

    def test_missing_supports_custom_target_language(self, handler):
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("""
            INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
            VALUES ('speichern', 'cli', 'de', 'Speichern', 1, 'manual', '2026-01-01')
        """)
        conn.execute("""
            INSERT INTO languages_translations (key, namespace, language, value, is_verified, source, created_at)
            VALUES ('speichern', 'cli', 'en', 'Save', 1, 'manual', '2026-01-01')
        """)
        conn.commit()
        conn.close()

        ok, msg = handler.handle("missing", ["--target", "es"], dry_run=False)
        assert ok is True
        assert "fehlende es" in msg
        assert "speichern" in msg

    def test_export_json_supports_custom_target_language(self, handler_with_data):
        ok, msg = handler_with_data.handle("export", ["--format", "json", "--target", "es"], dry_run=False)
        assert ok is True
        data = json.loads(msg)
        assert data[0]["target_language"] == "es"
        assert "es" in data[0]

    def test_import_json_with_translations_map(self, handler, tmp_path):
        data = [
            {
                "key": "save_button",
                "namespace": "gui",
                "de": "Speichern",
                "translations": {
                    "en": "Save",
                    "es": "Guardar",
                    "ru": "Sohranit",
                    "ja": "Hozon",
                    "zh": "Bao cun",
                },
                "source": "gemini_reviewed",
            }
        ]
        import_file = tmp_path / "import_multi.json"
        import_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        ok, msg = handler.handle("import", [str(import_file)], dry_run=False)
        assert ok is True
        assert "5 Uebersetzungen importiert" in msg

        conn = sqlite3.connect(str(handler.db_path))
        rows = conn.execute(
            "SELECT language, source FROM languages_translations WHERE key='save_button' ORDER BY language"
        ).fetchall()
        enabled = json.loads(conn.execute("SELECT enabled_languages FROM languages_config LIMIT 1").fetchone()[0])
        conn.close()

        assert {row[0] for row in rows} == {"en", "es", "ja", "ru", "zh"}
        assert {row[1] for row in rows} == {"gemini_reviewed"}
        for lang_code in ["es", "ru", "ja", "zh"]:
            assert lang_code in enabled

    def test_dict_add_supports_custom_language_pair(self, handler):
        ok, msg = handler.handle("dict", ["add", "speichern", "guardar", "--target-lang", "es"], dry_run=False)
        assert ok is True
        assert "(es)" in msg

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute(
            "SELECT source_lang, target_lang FROM languages_dictionary WHERE term='speichern' AND translation='guardar'"
        ).fetchone()
        conn.close()
        assert row == ("de", "es")


class TestModuleFunctions:
    def test_set_lang_clears_cache(self):
        from hub.lang import set_lang, _t_cache, _t_lang_cache, clear_t_cache
        clear_t_cache()
        set_lang("en")
        from hub import lang as lang_mod
        assert lang_mod._t_lang_cache == "en"
        set_lang("de")
        assert lang_mod._t_lang_cache == "de"

    def test_clear_t_cache(self):
        from hub.lang import clear_t_cache
        from hub import lang as lang_mod
        lang_mod._t_cache["test:de"] = "cached"
        lang_mod._t_lang_cache = "de"
        clear_t_cache()
        assert lang_mod._t_cache == {}
        assert lang_mod._t_lang_cache is None

    @patch("hub.lang._get_t_db_path")
    def test_get_lang_no_db(self, mock_path):
        from hub.lang import get_lang, clear_t_cache
        clear_t_cache()
        mock_path.return_value = Path("/nonexistent/bach.db")
        result = get_lang()
        assert result == "de"

    @patch("hub.lang._get_t_db_path")
    def test_t_exists_no_db(self, mock_path):
        from hub.lang import t_exists
        mock_path.return_value = Path("/nonexistent/bach.db")
        assert t_exists("anything") is False

    @patch("hub.lang._get_t_db_path")
    def test_t_returns_default(self, mock_path):
        from hub.lang import t, clear_t_cache
        clear_t_cache()
        mock_path.return_value = Path("/nonexistent/bach.db")
        assert t("unknown_key", default="Fallback") == "Fallback"

    @patch("hub.lang._get_t_db_path")
    def test_t_returns_key_when_no_default(self, mock_path):
        from hub.lang import t, clear_t_cache
        clear_t_cache()
        mock_path.return_value = Path("/nonexistent/bach.db")
        assert t("my_key") == "my_key"

    def test_t_cache_hit(self):
        from hub.lang import t, clear_t_cache
        from hub import lang as lang_mod
        clear_t_cache()
        lang_mod._t_lang_cache = "de"
        lang_mod._t_cache["cached_key:de"] = "Gecachter Wert"
        assert t("cached_key") == "Gecachter Wert"
        clear_t_cache()
