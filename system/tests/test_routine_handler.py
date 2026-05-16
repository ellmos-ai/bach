#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer hub/routine.py — RoutineHandler (Haushaltsroutinen)."""

import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from hub.routine import RoutineHandler

SCHEMA = """
CREATE TABLE IF NOT EXISTS household_routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    frequency TEXT DEFAULT 'woechentlich',
    schedule TEXT DEFAULT '',
    category TEXT DEFAULT 'Sonstige',
    duration_minutes INTEGER DEFAULT 0,
    last_done TEXT,
    next_due TEXT,
    is_active INTEGER DEFAULT 1,
    notes TEXT DEFAULT '',
    created_at TEXT
);
"""


@pytest.fixture
def handler(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(SCHEMA)
    conn.commit()
    conn.close()

    h = RoutineHandler.__new__(RoutineHandler)
    h.base_path = tmp_path
    h._canonical_db = db_path
    h.db_path = db_path
    return h


@pytest.fixture
def handler_with_data(handler):
    conn = sqlite3.connect(str(handler.db_path))
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    last_week = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    next_week = (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    past = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, duration_minutes, last_done, next_due, is_active, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Staubsaugen", "woechentlich", "Wohnzimmer", 30, last_week, yesterday, 1, "", now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, duration_minutes, last_done, next_due, is_active, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Geschirr", "taeglich", "Kueche", 15, yesterday, tomorrow, 1, "Abends machen", now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, duration_minutes, last_done, next_due, is_active, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Fenster putzen", "monatlich", "Wohnzimmer", 60, past, next_week, 1, "", now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, duration_minutes, last_done, next_due, is_active, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Alte Aufgabe", "woechentlich", "Archiv", 10, last_week, yesterday, 0, "", now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
    return handler


# ========== LIST ==========

class TestList:

    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "Keine Routinen" in msg

    def test_list_active_only(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", [])
        assert ok
        assert "3 Routine(n)" in msg
        assert "Staubsaugen" in msg
        assert "Geschirr" in msg
        assert "Fenster putzen" in msg
        assert "Alte Aufgabe" not in msg

    def test_list_all(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", ["--all"])
        assert ok
        assert "4 Routine(n)" in msg
        assert "Alte Aufgabe" in msg

    def test_list_category_filter(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", ["--category", "Kueche"])
        assert ok
        assert "1 Routine(n)" in msg
        assert "Geschirr" in msg
        assert "Staubsaugen" not in msg

    def test_list_category_short_flag(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", ["-c", "Wohnzimmer"])
        assert ok
        assert "2 Routine(n)" in msg

    def test_list_all_with_category(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", ["--all", "--category", "Archiv"])
        assert ok
        assert "1 Routine(n)" in msg
        assert "Alte Aufgabe" in msg

    def test_list_overdue_marker(self, handler_with_data):
        ok, msg = handler_with_data.handle("list", [])
        assert ok
        assert "!!!" in msg


# ========== DUE ==========

class TestDue:

    def test_due_default_7_days(self, handler_with_data):
        ok, msg = handler_with_data.handle("due", [])
        assert ok
        assert "ROUTINES" in msg

    def test_due_custom_days(self, handler_with_data):
        ok, msg = handler_with_data.handle("due", ["1"])
        assert ok

    def test_due_no_results(self, handler):
        ok, msg = handler.handle("due", [])
        assert ok
        assert "Keine faelligen" in msg

    def test_due_overdue_section(self, handler_with_data):
        ok, msg = handler_with_data.handle("due", [])
        assert ok
        assert "UEBERFAELLIG" in msg
        assert "Staubsaugen" in msg

    def test_due_upcoming_section(self, handler_with_data):
        ok, msg = handler_with_data.handle("due", [])
        assert ok


# ========== DONE ==========

class TestDone:

    def test_done_no_id(self, handler):
        ok, msg = handler.handle("done", [])
        assert not ok
        assert "Usage" in msg

    def test_done_single(self, handler_with_data):
        ok, msg = handler_with_data.handle("done", ["1"])
        assert ok
        assert "erledigt" in msg
        assert "Staubsaugen" in msg
        conn = sqlite3.connect(str(handler_with_data.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE id = 1").fetchone()
        assert row["last_done"] is not None
        now = datetime.now()
        next_due = datetime.strptime(row["next_due"], "%Y-%m-%d %H:%M:%S")
        assert next_due > now
        conn.close()

    def test_done_multiple(self, handler_with_data):
        ok, msg = handler_with_data.handle("done", ["1", "2"])
        assert ok
        assert "Staubsaugen" in msg
        assert "Geschirr" in msg

    def test_done_not_found(self, handler_with_data):
        ok, msg = handler_with_data.handle("done", ["999"])
        assert ok
        assert "nicht gefunden" in msg

    def test_done_with_note(self, handler_with_data):
        ok, msg = handler_with_data.handle("done", ["2", "--note", "Grundreinigung"])
        assert ok
        conn = sqlite3.connect(str(handler_with_data.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE id = 2").fetchone()
        assert "Grundreinigung" in row["notes"]
        conn.close()

    def test_done_daily_frequency(self, handler_with_data):
        ok, msg = handler_with_data.handle("done", ["2"])
        assert ok
        conn = sqlite3.connect(str(handler_with_data.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE id = 2").fetchone()
        next_due = datetime.strptime(row["next_due"], "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        diff = (next_due - now).total_seconds()
        assert 0 < diff < 86400 + 60
        conn.close()

    def test_done_monthly_frequency(self, handler_with_data):
        ok, msg = handler_with_data.handle("done", ["3"])
        assert ok
        conn = sqlite3.connect(str(handler_with_data.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE id = 3").fetchone()
        next_due = datetime.strptime(row["next_due"], "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        diff = (next_due - now).days
        assert 28 <= diff <= 31
        conn.close()


# ========== ADD ==========

class TestAdd:

    def test_add_no_args(self, handler):
        ok, msg = handler.handle("add", [])
        assert not ok
        assert "Usage" in msg

    def test_add_simple(self, handler):
        ok, msg = handler.handle("add", ["Waschmaschine"])
        assert ok
        assert "erstellt" in msg
        assert "Waschmaschine" in msg
        conn = sqlite3.connect(str(handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE name = 'Waschmaschine'").fetchone()
        assert row is not None
        assert row["frequency"] == "woechentlich"
        assert row["category"] == "Sonstige"
        conn.close()

    def test_add_with_options(self, handler):
        ok, msg = handler.handle("add", ["Muell", "--freq", "taeglich", "--cat", "Kueche", "--dur", "5"])
        assert ok
        conn = sqlite3.connect(str(handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE name = 'Muell'").fetchone()
        assert row["frequency"] == "taeglich"
        assert row["category"] == "Kueche"
        assert row["duration_minutes"] == 5
        conn.close()

    def test_add_short_flags(self, handler):
        ok, msg = handler.handle("add", ["Boden wischen", "-f", "monatlich", "-c", "Bad", "-d", "20"])
        assert ok
        conn = sqlite3.connect(str(handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE name = 'Boden wischen'").fetchone()
        assert row["frequency"] == "monatlich"
        assert row["category"] == "Bad"
        assert row["duration_minutes"] == 20
        conn.close()

    def test_add_with_note(self, handler):
        ok, msg = handler.handle("add", ["Gardinen", "--note", "Nur im Fruehjahr"])
        assert ok
        conn = sqlite3.connect(str(handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE name = 'Gardinen'").fetchone()
        assert "Fruehjahr" in row["notes"]
        conn.close()

    def test_add_invalid_duration(self, handler):
        ok, msg = handler.handle("add", ["Test", "--dur", "abc"])
        assert ok
        conn = sqlite3.connect(str(handler.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM household_routines WHERE name = 'Test'").fetchone()
        assert row["duration_minutes"] == 0
        conn.close()

    def test_add_flag_value_treated_as_name(self, handler):
        ok, msg = handler.handle("add", ["--freq", "taeglich"])
        assert ok
        assert "taeglich" in msg

    def test_add_only_flags(self, handler):
        ok, msg = handler.handle("add", ["--freq"])
        assert not ok
        assert "Kein Name" in msg


# ========== SHOW ==========

class TestShow:

    def test_show_no_id(self, handler):
        ok, msg = handler.handle("show", [])
        assert not ok
        assert "Usage" in msg

    def test_show_existing(self, handler_with_data):
        ok, msg = handler_with_data.handle("show", ["2"])
        assert ok
        assert "Geschirr" in msg
        assert "taeglich" in msg
        assert "Kueche" in msg
        assert "15 Min" in msg

    def test_show_not_found(self, handler_with_data):
        ok, msg = handler_with_data.handle("show", ["999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_show_overdue_marker(self, handler_with_data):
        ok, msg = handler_with_data.handle("show", ["1"])
        assert ok
        assert "UEBERFAELLIG" in msg

    def test_show_notes(self, handler_with_data):
        ok, msg = handler_with_data.handle("show", ["2"])
        assert ok
        assert "Abends machen" in msg


# ========== HELP ==========

class TestHelp:

    def test_help(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok
        assert "ROUTINE" in msg
        assert "BEFEHLE" in msg

    def test_empty_operation(self, handler):
        ok, msg = handler.handle("", [])
        assert ok
        assert "ROUTINE" in msg


# ========== UNKNOWN OPERATION ==========

class TestUnknown:

    def test_unknown(self, handler):
        ok, msg = handler.handle("xyz", [])
        assert not ok
        assert "Unbekannte Operation" in msg


# ========== INTERNAL METHODS ==========

class TestInternalMethods:

    def test_parse_ids(self, handler):
        ids, rest = handler._parse_ids(["1", "2", "--note", "foo"])
        assert ids == [1, 2]
        assert rest == ["--note", "foo"]

    def test_parse_ids_empty(self, handler):
        ids, rest = handler._parse_ids([])
        assert ids == []
        assert rest == []

    def test_get_arg(self, handler):
        assert handler._get_arg(["--freq", "taeglich", "--cat", "Bad"], "--freq") == "taeglich"
        assert handler._get_arg(["--freq", "taeglich"], "--cat") is None

    def test_get_arg_equals_syntax(self, handler):
        assert handler._get_arg(["--freq=monatlich"], "--freq") == "monatlich"

    def test_calc_next_due_daily(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        result = handler._calc_next_due(now, "taeglich")
        assert result == now + timedelta(days=1)

    def test_calc_next_due_weekly(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        result = handler._calc_next_due(now, "woechentlich")
        assert result == now + timedelta(days=7)

    def test_calc_next_due_biweekly(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        result = handler._calc_next_due(now, "2-woechentlich")
        assert result == now + timedelta(days=14)

    def test_calc_next_due_monthly(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        result = handler._calc_next_due(now, "monatlich")
        assert result == now + timedelta(days=30)

    def test_calc_next_due_quarterly(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        result = handler._calc_next_due(now, "quartal")
        assert result == now + timedelta(days=90)

    def test_calc_next_due_yearly(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        result = handler._calc_next_due(now, "jaehrlich")
        assert result == now + timedelta(days=365)

    def test_calc_next_due_umlaut_variants(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        assert handler._calc_next_due(now, "täglich") == now + timedelta(days=1)
        assert handler._calc_next_due(now, "wöchentlich") == now + timedelta(days=7)
        assert handler._calc_next_due(now, "halbjährlich") == now + timedelta(days=182)
        assert handler._calc_next_due(now, "jährlich") == now + timedelta(days=365)

    def test_calc_next_due_english(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        assert handler._calc_next_due(now, "daily") == now + timedelta(days=1)
        assert handler._calc_next_due(now, "weekly") == now + timedelta(days=7)
        assert handler._calc_next_due(now, "biweekly") == now + timedelta(days=14)
        assert handler._calc_next_due(now, "monthly") == now + timedelta(days=30)
        assert handler._calc_next_due(now, "quarterly") == now + timedelta(days=90)
        assert handler._calc_next_due(now, "yearly") == now + timedelta(days=365)

    def test_calc_next_due_unknown_fallback(self, handler):
        now = datetime(2026, 1, 1, 12, 0)
        result = handler._calc_next_due(now, "unknown")
        assert result == now + timedelta(days=7)


# ========== PROPERTIES ==========

class TestProperties:

    def test_profile_name(self, handler):
        assert handler.profile_name == "routine"

    def test_target_file(self, handler):
        assert handler.target_file == handler.db_path

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "due" in ops
        assert "done" in ops
        assert "add" in ops
        assert "show" in ops
        assert "help" in ops
