#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer ContactHandler"""

import sys
import sqlite3
import pytest
from pathlib import Path

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.contact import ContactHandler

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    category TEXT,
    subcategory TEXT,
    organization TEXT,
    position TEXT,
    phone TEXT,
    phone_mobile TEXT,
    phone_work TEXT,
    email TEXT,
    email_work TEXT,
    street TEXT,
    city TEXT,
    zip_code TEXT,
    country TEXT DEFAULT 'Deutschland',
    website TEXT,
    birthday TEXT,
    notes TEXT,
    tags TEXT,
    is_active INTEGER DEFAULT 1,
    source TEXT,
    source_id INTEGER,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


@pytest.fixture
def tmp_contact(tmp_path):
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "help").mkdir()

    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

    return system_dir, db_path


@pytest.fixture
def handler(tmp_contact):
    system_dir, db_path = tmp_contact
    h = ContactHandler(system_dir)
    h.user_db_path = db_path
    return h


@pytest.fixture
def seeded_handler(handler):
    conn = sqlite3.connect(str(handler.user_db_path))
    conn.execute(
        "INSERT INTO contacts (id, name, first_name, last_name, category, email, phone_mobile, organization, position, birthday, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "Max Mustermann", "Max", "Mustermann", "beruflich", "max@test.de", "0171-1234567", "TestCorp", "Entwickler", "1990-06-15", 1),
    )
    conn.execute(
        "INSERT INTO contacts (id, name, first_name, last_name, category, email, phone, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (2, "Lisa Mueller", "Lisa", "Mueller", "privat", "lisa@test.de", "030-9876543", 1),
    )
    conn.execute(
        "INSERT INTO contacts (id, name, category, is_active) "
        "VALUES (?, ?, ?, ?)",
        (3, "Dr. Meier", "arzt", 0),
    )
    conn.commit()
    conn.close()
    return handler


# ================================================================
# PROPERTIES
# ================================================================

class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "contact"

    def test_target_file(self, handler):
        assert handler.target_file == handler.user_db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "search" in ops
        assert "add" in ops
        assert "show" in ops
        assert "edit" in ops
        assert "delete" in ops
        assert "birthday" in ops
        assert "export" in ops


# ================================================================
# HANDLE ROUTING
# ================================================================

class TestHandleRouting:
    def test_unknown_op(self, handler):
        ok, msg = handler.handle("xyzfoo", [])
        assert ok is False
        assert "Unbekannte" in msg

    def test_help(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok is True
        assert "CONTACT" in msg

    def test_empty_op(self, handler):
        ok, msg = handler.handle("", [])
        assert ok is True
        assert "CONTACT" in msg


# ================================================================
# LIST
# ================================================================

class TestList:
    def test_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "Keine Kontakte" in msg

    def test_with_data(self, seeded_handler):
        ok, msg = seeded_handler.handle("list", [])
        assert ok is True
        assert "Max Mustermann" in msg
        assert "Lisa Mueller" in msg
        assert "Dr. Meier" not in msg

    def test_list_all(self, seeded_handler):
        ok, msg = seeded_handler.handle("list", ["--all"])
        assert ok is True
        assert "Dr. Meier" in msg

    def test_list_context_filter(self, seeded_handler):
        ok, msg = seeded_handler.handle("list", ["--context", "beruflich"])
        assert ok is True
        assert "Max Mustermann" in msg
        assert "Lisa Mueller" not in msg


# ================================================================
# SEARCH
# ================================================================

class TestSearch:
    def test_no_args(self, handler):
        ok, msg = handler.handle("search", [])
        assert ok is False
        assert "Usage" in msg

    def test_no_results(self, seeded_handler):
        ok, msg = seeded_handler.handle("search", ["nonexistent"])
        assert ok is True
        assert "Keine Treffer" in msg

    def test_by_name(self, seeded_handler):
        ok, msg = seeded_handler.handle("search", ["Max"])
        assert ok is True
        assert "Max Mustermann" in msg

    def test_by_email(self, seeded_handler):
        ok, msg = seeded_handler.handle("search", ["lisa@test.de"])
        assert ok is True
        assert "Lisa Mueller" in msg

    def test_by_org(self, seeded_handler):
        ok, msg = seeded_handler.handle("search", ["TestCorp"])
        assert ok is True
        assert "Max Mustermann" in msg


# ================================================================
# ADD
# ================================================================

class TestAdd:
    def test_no_args(self, handler):
        ok, msg = handler.handle("add", [])
        assert ok is False
        assert "Usage" in msg

    def test_add_simple(self, handler):
        ok, msg = handler.handle("add", ["Erika Muster"])
        assert ok is True
        assert "erstellt" in msg
        assert "Erika Muster" in msg

    def test_add_with_options(self, handler):
        ok, msg = handler.handle("add", [
            "Test Person", "--email", "test@mail.de",
            "--context", "beruflich", "--mobile", "0171-999"
        ])
        assert ok is True
        assert "erstellt" in msg

        conn = sqlite3.connect(str(handler.user_db_path))
        row = conn.execute("SELECT * FROM contacts WHERE name = 'Test Person'").fetchone()
        conn.close()
        assert row is not None

    def test_add_with_birthday(self, handler):
        ok, msg = handler.handle("add", ["Geb Test", "--birthday", "15.06.1990"])
        assert ok is True

        conn = sqlite3.connect(str(handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT birthday FROM contacts WHERE name = 'Geb Test'").fetchone()
        conn.close()
        assert row["birthday"] == "1990-06-15"

    def test_add_invalid_birthday(self, handler):
        ok, msg = handler.handle("add", ["Bad Date", "--birthday", "invalid"])
        assert ok is False
        assert "Datum" in msg


# ================================================================
# SHOW
# ================================================================

class TestShow:
    def test_no_id(self, handler):
        ok, msg = handler.handle("show", [])
        assert ok is False
        assert "Usage" in msg

    def test_not_found(self, seeded_handler):
        ok, msg = seeded_handler.handle("show", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_found(self, seeded_handler):
        ok, msg = seeded_handler.handle("show", ["1"])
        assert ok is True
        assert "Max Mustermann" in msg
        assert "max@test.de" in msg
        assert "TestCorp" in msg
        assert "Entwickler" in msg


# ================================================================
# EDIT
# ================================================================

class TestEdit:
    def test_no_args(self, handler):
        ok, msg = handler.handle("edit", [])
        assert ok is False
        assert "Usage" in msg

    def test_not_found(self, seeded_handler):
        ok, msg = seeded_handler.handle("edit", ["999", "--name", "New"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_no_changes(self, seeded_handler):
        ok, msg = seeded_handler.handle("edit", ["1"])
        assert ok is False
        assert "Keine Aenderungen" in msg

    def test_edit_email(self, seeded_handler):
        ok, msg = seeded_handler.handle("edit", ["1", "--email", "new@mail.de"])
        assert ok is True
        assert "aktualisiert" in msg
        assert "email" in msg

        conn = sqlite3.connect(str(seeded_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT email FROM contacts WHERE id = 1").fetchone()
        conn.close()
        assert row["email"] == "new@mail.de"

    def test_edit_multiple(self, seeded_handler):
        ok, msg = seeded_handler.handle("edit", [
            "1", "--name", "Max Neu", "--company", "NeuCorp"
        ])
        assert ok is True
        assert "name" in msg
        assert "organization" in msg

    def test_edit_note_appends(self, seeded_handler):
        seeded_handler.handle("edit", ["1", "--note", "Erste Notiz"])
        seeded_handler.handle("edit", ["1", "--note", "Zweite Notiz"])

        conn = sqlite3.connect(str(seeded_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT notes FROM contacts WHERE id = 1").fetchone()
        conn.close()
        assert "Erste Notiz" in row["notes"]
        assert "Zweite Notiz" in row["notes"]


# ================================================================
# DELETE
# ================================================================

class TestDelete:
    def test_no_id(self, handler):
        ok, msg = handler.handle("delete", [])
        assert ok is False
        assert "Usage" in msg

    def test_not_found(self, seeded_handler):
        ok, msg = seeded_handler.handle("delete", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_soft_delete(self, seeded_handler):
        ok, msg = seeded_handler.handle("delete", ["1"])
        assert ok is True
        assert "deaktiviert" in msg

        conn = sqlite3.connect(str(seeded_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT is_active FROM contacts WHERE id = 1").fetchone()
        conn.close()
        assert row["is_active"] == 0

    def test_already_inactive(self, seeded_handler):
        ok, msg = seeded_handler.handle("delete", ["3"])
        assert ok is True
        assert "bereits inaktiv" in msg


# ================================================================
# BIRTHDAY
# ================================================================

class TestBirthday:
    def test_no_birthdays(self, handler):
        ok, msg = handler.handle("birthday", [])
        assert ok is True
        assert "Keine Kontakte mit Geburtstag" in msg

    def test_with_data(self, seeded_handler):
        ok, msg = seeded_handler.handle("birthday", ["365"])
        assert ok is True


# ================================================================
# EXPORT
# ================================================================

class TestExport:
    def test_export_empty(self, handler):
        ok, msg = handler.handle("export", [])
        assert ok is True

    def test_export_text_with_mobile(self, seeded_handler):
        ok, msg = seeded_handler.handle("export", ["--format", "txt"])
        assert ok is True
        assert "0171-1234567" in msg

    def test_export_text_basic(self, seeded_handler):
        ok, msg = seeded_handler.handle("export", [])
        assert ok is True
        assert "Max Mustermann" in msg


# ================================================================
# HELPERS
# ================================================================

class TestHelpers:
    def test_parse_ids(self, handler):
        ids, rest = handler._parse_ids(["1", "abc", "3", "--flag"])
        assert ids == [1, 3]
        assert rest == ["abc", "--flag"]

    def test_get_arg(self, handler):
        assert handler._get_arg(["--email", "x@y.de"], "--email") == "x@y.de"
        assert handler._get_arg(["--email=x@y.de"], "--email") == "x@y.de"
        assert handler._get_arg(["foo"], "--email") is None
        assert handler._get_arg(["--email"], "--email") is None

    def test_parse_date_german(self, handler):
        assert handler._parse_date("15.06.1990") == "1990-06-15"

    def test_parse_date_iso(self, handler):
        assert handler._parse_date("1990-06-15") == "1990-06-15"

    def test_parse_date_invalid(self, handler):
        assert handler._parse_date("invalid") is None

    def test_format_birthday(self, handler):
        result = handler._format_birthday("1990-06-15")
        assert "1990" in result or "15.06" in result
        assert "Jahre" in result

    def test_format_birthday_none(self, handler):
        assert handler._format_birthday(None) == "---"

    def test_vcard_escape(self, handler):
        assert handler._vcard_escape("a;b,c") == "a\\;b\\,c"
        assert handler._vcard_escape("line1\nline2") == "line1\\nline2"
        assert handler._vcard_escape("") == ""
        assert handler._vcard_escape(None) == ""
