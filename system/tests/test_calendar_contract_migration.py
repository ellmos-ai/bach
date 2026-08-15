"""Tests für die fail-closed Konsolidierung des Kalendervertrags."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).parents[1]
    / "data"
    / "schema"
    / "migrations"
    / "037_calendar_contract.py"
)
SCHEMA = Path(__file__).parents[1] / "data" / "schema" / "schema.sql"


def _load_migration():
    spec = importlib.util.spec_from_file_location("calendar_contract_037", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_schema(conn):
    conn.execute(
        """
        CREATE TABLE assistant_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_type TEXT,
            start_datetime DATETIME,
            end_datetime DATETIME,
            location TEXT,
            description TEXT,
            status TEXT DEFAULT 'geplant',
            reminder_minutes INTEGER,
            is_recurring INTEGER DEFAULT 0,
            recurrence_rule TEXT,
            external_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dist_type INTEGER DEFAULT 0
        )
        """
    )


def _legacy_schema(conn):
    conn.execute(
        """
        CREATE TABLE calendar_events (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            event_date TEXT,
            event_time TEXT
        )
        """
    )


def test_empty_legacy_table_becomes_compatibility_view():
    conn = sqlite3.connect(":memory:")
    _canonical_schema(conn)
    _legacy_schema(conn)
    conn.execute(
        """
        INSERT INTO assistant_calendar
            (title, event_type, start_datetime, reminder_minutes,
             is_recurring, recurrence_rule)
        VALUES ('Jour fixe', 'termin', '2026-08-18 10:30:00', 30, 1,
                'FREQ=WEEKLY')
        """
    )

    _load_migration().run_migration(conn)

    obj_type = conn.execute(
        "SELECT type FROM sqlite_master WHERE name='calendar_events'"
    ).fetchone()[0]
    row = conn.execute("SELECT * FROM calendar_events").fetchone()
    columns = [item[0] for item in conn.execute("SELECT * FROM calendar_events").description]
    mapped = dict(zip(columns, row))
    assert obj_type == "view"
    assert mapped["event_date"] == "2026-08-18"
    assert mapped["event_time"] == "10:30:00"
    assert mapped["reminder_minutes"] == 30
    assert mapped["recurrence_pattern"] == "FREQ=WEEKLY"


def test_fresh_full_schema_uses_only_canonical_calendar_storage():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))

    _load_migration().run_migration(conn)

    objects = dict(
        conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE name IN ('assistant_calendar', 'calendar_events')"
        ).fetchall()
    )
    assert objects == {
        "assistant_calendar": "table",
        "calendar_events": "view",
    }


def test_nonempty_legacy_table_aborts_without_dropping_data():
    conn = sqlite3.connect(":memory:")
    _canonical_schema(conn)
    _legacy_schema(conn)
    conn.execute(
        "INSERT INTO calendar_events (id, title, event_date) "
        "VALUES (7, 'Alttermin', '2026-08-18')"
    )

    with pytest.raises(RuntimeError, match="1 Legacy-Einträge"):
        _load_migration().run_migration(conn)

    assert conn.execute(
        "SELECT title FROM calendar_events WHERE id=7"
    ).fetchone()[0] == "Alttermin"
