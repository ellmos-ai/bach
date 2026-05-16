#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer ProfileHandler"""

import sys
import json
import sqlite3
import pytest
from pathlib import Path

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.profile import ProfileHandler

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS assistant_user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    confidence TEXT DEFAULT 'mittel' CHECK(confidence IN ('niedrig', 'mittel', 'hoch')),
    learned_from TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);
"""


@pytest.fixture
def tmp_profile(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()

    user_dir = tmp_path / "user"
    user_dir.mkdir()

    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

    return system_dir, db_path


@pytest.fixture
def handler(tmp_profile):
    system_dir, db_path = tmp_profile
    h = ProfileHandler(system_dir)
    h.db_path = db_path
    h.profile_json = system_dir.parent / "user" / "profile.json"
    return h


@pytest.fixture
def handler_with_json(handler):
    profile_data = {
        "meta": {"version": "1.0", "updated": "2026-05-16"},
        "stats": {
            "name": "Lukas",
            "role": "Entwickler",
            "language": "de",
            "timezone": "Europe/Berlin",
            "os": "Windows 11"
        },
        "traits": {"detail_level": "hoch", "communication": "direkt"},
        "values": ["Open Source", "Datenschutz"],
        "goals": {
            "kurzfristig": ["Tests schreiben", "Bugs fixen"],
            "langfristig": ["BACH Release"]
        },
        "preferences": {
            "coding": {"editor": "vscode", "sprache": "Python"},
        },
    }
    handler.profile_json.write_text(json.dumps(profile_data), encoding="utf-8")
    return handler


@pytest.fixture
def seeded_handler(handler_with_json):
    h = handler_with_json
    conn = sqlite3.connect(str(h.db_path))
    conn.execute(
        "INSERT INTO assistant_user_profile (category, key, value, confidence, learned_from) "
        "VALUES (?, ?, ?, ?, ?)",
        ("praeferenz", "sprache", "Deutsch", "hoch", "user-input"),
    )
    conn.execute(
        "INSERT INTO assistant_user_profile (category, key, value, confidence, learned_from) "
        "VALUES (?, ?, ?, ?, ?)",
        ("gewohnheit", "arbeitszeit", "09-17 Uhr", "mittel", "beobachtung"),
    )
    conn.execute(
        "INSERT INTO assistant_user_profile (category, key, value, confidence, learned_from) "
        "VALUES (?, ?, ?, ?, ?)",
        ("eigenheit", "tmux_nutzer", "ja", "hoch", "user-input"),
    )
    conn.commit()
    conn.close()
    return h


# ================================================================
# PROPERTIES
# ================================================================

class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "profile"

    def test_target_file(self, handler):
        assert handler.target_file == handler.profile_json

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "show" in ops
        assert "edit" in ops
        assert "stats" in ops
        assert "json" in ops
        assert "db" in ops
        assert "export" in ops


# ================================================================
# SHOW
# ================================================================

class TestShow:
    def test_no_json_no_db(self, handler):
        ok, msg = handler.handle("show", [])
        assert ok is True
        assert "nicht gefunden" in msg

    def test_with_json(self, handler_with_json):
        ok, msg = handler_with_json.handle("show", [])
        assert ok is True
        assert "Lukas" in msg
        assert "Entwickler" in msg

    def test_with_json_and_db(self, seeded_handler):
        ok, msg = seeded_handler.handle("show", [])
        assert ok is True
        assert "Lukas" in msg
        assert "praeferenz" in msg or "sprache" in msg.lower()

    def test_unknown_op(self, handler):
        ok, msg = handler.handle("foobar", [])
        assert ok is False
        assert "Unbekannte" in msg


# ================================================================
# EDIT
# ================================================================

class TestEdit:
    def test_too_few_args(self, handler):
        ok, msg = handler.handle("edit", ["praeferenz"])
        assert ok is False
        assert "Verwendung" in msg

    def test_invalid_category(self, handler):
        ok, msg = handler.handle("edit", ["ungueltig", "key", "val"])
        assert ok is False
        assert "Ungueltige Kategorie" in msg

    def test_success(self, handler):
        ok, msg = handler.handle("edit", ["praeferenz", "farbe", "blau"])
        assert ok is True
        assert "aktualisiert" in msg

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute(
            "SELECT value, confidence FROM assistant_user_profile WHERE key = 'farbe'"
        ).fetchone()
        conn.close()
        assert row[0] == "blau"
        assert row[1] == "hoch"

    def test_upsert(self, handler):
        handler.handle("edit", ["praeferenz", "farbe", "blau"])
        handler.handle("edit", ["praeferenz", "farbe", "gruen"])

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute(
            "SELECT value FROM assistant_user_profile WHERE key = 'farbe'"
        ).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM assistant_user_profile WHERE key = 'farbe'").fetchone()[0]
        conn.close()
        assert row[0] == "gruen"
        assert count == 1

    def test_multi_word_value(self, handler):
        ok, msg = handler.handle("edit", ["eigenheit", "notiz", "mag", "keine", "meetings"])
        assert ok is True

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute(
            "SELECT value FROM assistant_user_profile WHERE key = 'notiz'"
        ).fetchone()
        conn.close()
        assert row[0] == "mag keine meetings"

    def test_dry_run(self, handler):
        ok, msg = handler.handle("edit", ["praeferenz", "farbe", "blau"], dry_run=True)
        assert ok is True
        assert "DRY" in msg

        conn = sqlite3.connect(str(handler.db_path))
        count = conn.execute("SELECT COUNT(*) FROM assistant_user_profile").fetchone()[0]
        conn.close()
        assert count == 0

    def test_update_alias(self, handler):
        ok, msg = handler.handle("update", ["gewohnheit", "key", "val"])
        assert ok is True
        assert "aktualisiert" in msg

    def test_all_valid_categories(self, handler):
        for cat in ("praeferenz", "gewohnheit", "eigenheit"):
            ok, msg = handler.handle("edit", [cat, f"test_{cat}", "wert"])
            assert ok is True


# ================================================================
# STATS
# ================================================================

class TestStats:
    def test_empty(self, handler):
        ok, msg = handler.handle("stats", [])
        assert ok is True
        assert "0" in msg

    def test_with_json(self, handler_with_json):
        ok, msg = handler_with_json.handle("stats", [])
        assert ok is True
        assert "v1.0" in msg

    def test_with_db_entries(self, seeded_handler):
        ok, msg = seeded_handler.handle("stats", [])
        assert ok is True
        assert "3" in msg


# ================================================================
# JSON / DB views
# ================================================================

class TestViews:
    def test_json_missing(self, handler):
        ok, msg = handler.handle("json", [])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_json_present(self, handler_with_json):
        ok, msg = handler_with_json.handle("json", [])
        assert ok is True
        assert "Lukas" in msg

    def test_db_empty(self, handler):
        ok, msg = handler.handle("db", [])
        assert ok is True
        assert "Keine" in msg

    def test_db_with_data(self, seeded_handler):
        ok, msg = seeded_handler.handle("db", [])
        assert ok is True
        assert "3 Eintraege" in msg
        assert "praeferenz" in msg
        assert "gewohnheit" in msg


# ================================================================
# EXPORT
# ================================================================

class TestExport:
    def test_export_empty(self, handler):
        ok, msg = handler.handle("export", [])
        assert ok is True
        assert "PROFILE EXPORT" in msg

    def test_export_with_all_data(self, seeded_handler):
        ok, msg = seeded_handler.handle("export", [])
        assert ok is True
        assert "BASICS:" in msg
        assert "Lukas" in msg
        assert "TRAITS:" in msg
        assert "VALUES:" in msg
        assert "GOALS:" in msg
        assert "LEARNED (DB):" in msg
        assert "sprache" in msg.lower()
