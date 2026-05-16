"""Tests for CalendarHandler."""

import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch


CALENDAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS assistant_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    event_type TEXT,
    start_datetime DATETIME,
    end_datetime DATETIME,
    location TEXT,
    description TEXT,
    attendees TEXT,
    status TEXT DEFAULT 'geplant' CHECK(status IN ('geplant', 'bestaetigt', 'abgesagt', 'erledigt')),
    reminder_minutes INTEGER,
    is_recurring INTEGER DEFAULT 0,
    recurrence_rule TEXT,
    external_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
)
"""

ROUTINES_SCHEMA = """
CREATE TABLE IF NOT EXISTS household_routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    frequency TEXT NOT NULL,
    schedule TEXT,
    category TEXT,
    duration_minutes INTEGER,
    last_done TIMESTAMP,
    next_due TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 0
)
"""


@pytest.fixture
def cal_env(tmp_path):
    base = tmp_path / "bach"
    base.mkdir()
    (base / "hub").mkdir()
    db_dir = base / "data"
    db_dir.mkdir()
    db_path = db_dir / "bach.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute(CALENDAR_SCHEMA)
    conn.execute(ROUTINES_SCHEMA)
    conn.commit()
    conn.close()
    return base, db_path


@pytest.fixture
def handler(cal_env):
    base, db_path = cal_env
    import sys
    sys.path.insert(0, str(base.parent))

    from hub.calendar_handler import CalendarHandler

    h = CalendarHandler(base)
    h._canonical_db = db_path
    h.db_path = db_path
    return h


@pytest.fixture
def populated(handler, cal_env):
    _, db_path = cal_env
    now = datetime.now()
    conn = sqlite3.connect(str(db_path))

    conn.execute(
        "INSERT INTO assistant_calendar (title, event_type, start_datetime, location, status) VALUES (?, ?, ?, ?, ?)",
        ("Zahnarzt", "termin", (now + timedelta(days=1)).strftime("%Y-%m-%d 10:00:00"), "Praxis Dr. X", "geplant"),
    )
    conn.execute(
        "INSERT INTO assistant_calendar (title, event_type, start_datetime, status) VALUES (?, ?, ?, ?)",
        ("Besprechung", "termin", (now + timedelta(days=2)).strftime("%Y-%m-%d 14:00:00"), "geplant"),
    )
    conn.execute(
        "INSERT INTO assistant_calendar (title, event_type, start_datetime, status) VALUES (?, ?, ?, ?)",
        ("Altes Event", "erinnerung", (now - timedelta(days=60)).strftime("%Y-%m-%d 09:00:00"), "erledigt"),
    )

    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, next_due, is_active) VALUES (?, ?, ?, ?, ?)",
        ("Staubsaugen", "weekly", "Putzen", now.strftime("%Y-%m-%d 09:00:00"), 1),
    )
    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, next_due, is_active) VALUES (?, ?, ?, ?, ?)",
        ("Wäsche", "weekly", "Waschen", (now + timedelta(days=3)).strftime("%Y-%m-%d 09:00:00"), 1),
    )
    conn.execute(
        "INSERT INTO household_routines (name, frequency, category, next_due, is_active) VALUES (?, ?, ?, ?, ?)",
        ("Inaktiv", "daily", "Sonstig", now.strftime("%Y-%m-%d 09:00:00"), 0),
    )
    conn.commit()
    conn.close()
    return handler


# ─── Init ───────────────────────────────────────────────────

class TestCalendarInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "calendar"

    def test_target_file(self, handler, cal_env):
        _, db_path = cal_env
        assert handler.target_file == db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "week" in ops
        assert "month" in ops
        assert "today" in ops
        assert "add" in ops
        assert "show" in ops
        assert "done" in ops
        assert "delete" in ops
        assert "help" in ops

    def test_get_db_connection(self, handler):
        conn = handler._get_db()
        assert conn is not None
        conn.close()


# ─── Help ───────────────────────────────────────────────────

class TestCalendarHelp:
    def test_help(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok
        assert "CALENDAR" in msg
        assert "bach calendar" in msg

    def test_empty_operation_shows_help(self, handler):
        ok, msg = handler.handle("", [])
        assert ok
        assert "CALENDAR" in msg

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("foobar", [])
        assert not ok
        assert "Unbekannte Operation" in msg


# ─── List ───────────────────────────────────────────────────

class TestCalendarList:
    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "0 Eintraege" in msg or "Keine Termine" in msg

    def test_list_with_data(self, populated):
        ok, msg = populated.handle("list", [])
        assert ok
        assert "Zahnarzt" in msg

    def test_list_custom_days(self, populated):
        ok, msg = populated.handle("list", ["60"])
        assert ok

    def test_list_includes_routines(self, populated):
        ok, msg = populated.handle("list", ["60"])
        assert ok
        assert "Staubsaugen" in msg or "Wäsche" in msg


# ─── Today ──────────────────────────────────────────────────

class TestCalendarToday:
    def test_today_empty(self, handler):
        ok, msg = handler.handle("today", [])
        assert ok
        assert "Heute" in msg

    def test_today_with_events(self, populated):
        ok, msg = populated.handle("today", [])
        assert ok
        assert "Heute" in msg
        assert "Staubsaugen" in msg

    def test_today_shows_weekday(self, populated):
        ok, msg = populated.handle("today", [])
        assert ok
        wd = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        today_wd = wd[datetime.now().weekday()]
        assert today_wd in msg


# ─── Week ───────────────────────────────────────────────────

class TestCalendarWeek:
    def test_week_view(self, populated):
        ok, msg = populated.handle("week", [])
        assert ok
        assert "KW" in msg

    def test_week_includes_routines(self, populated):
        ok, msg = populated.handle("week", [])
        assert ok
        assert "Staubsaugen" in msg or "Eintraege" in msg

    def test_week_excludes_inactive_routines(self, populated):
        ok, msg = populated.handle("week", [])
        assert ok
        assert "Inaktiv" not in msg


# ─── Month ──────────────────────────────────────────────────

class TestCalendarMonth:
    def test_month_view(self, populated):
        ok, msg = populated.handle("month", [])
        assert ok
        month_names = ["Januar", "Februar", "Maerz", "April", "Mai", "Juni",
                       "Juli", "August", "September", "Oktober", "November", "Dezember"]
        current_month = month_names[datetime.now().month - 1]
        assert current_month in msg

    def test_month_shows_events(self, populated):
        ok, msg = populated.handle("month", [])
        assert ok
        assert "Zahnarzt" in msg


# ─── Add ────────────────────────────────────────────────────

class TestCalendarAdd:
    def test_add_no_args(self, handler):
        ok, msg = handler.handle("add", [])
        assert not ok
        assert "Usage" in msg

    def test_add_simple(self, handler):
        ok, msg = handler.handle("add", ["Meeting"])
        assert ok
        assert "Meeting" in msg
        assert "erstellt" in msg

    def test_add_with_date_iso(self, handler):
        ok, msg = handler.handle("add", ["Test", "--date", "2026-06-15", "--time", "14:00"])
        assert ok
        assert "2026-06-15" in msg

    def test_add_with_date_german(self, handler):
        ok, msg = handler.handle("add", ["Test", "-d", "15.06.2026", "-t", "14:00"])
        assert ok
        assert "2026-06-15" in msg

    def test_add_with_short_date(self, handler):
        ok, msg = handler.handle("add", ["Test", "-d", "15.06"])
        assert ok
        year = datetime.now().year
        assert f"{year}-06-15" in msg

    def test_add_with_location(self, handler, cal_env):
        _, db_path = cal_env
        ok, msg = handler.handle("add", ["Arzt", "--location", "Praxis"])
        assert ok
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assistant_calendar WHERE title='Arzt'").fetchone()
        assert row["location"] == "Praxis"
        conn.close()

    def test_add_with_type_and_note(self, handler, cal_env):
        _, db_path = cal_env
        ok, msg = handler.handle("add", ["Reminder", "--type", "erinnerung", "--note", "Nicht vergessen"])
        assert ok
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assistant_calendar WHERE title='Reminder'").fetchone()
        assert row["event_type"] == "erinnerung"
        assert row["description"] == "Nicht vergessen"
        conn.close()

    def test_add_default_time(self, handler, cal_env):
        _, db_path = cal_env
        ok, msg = handler.handle("add", ["DefaultTime"])
        assert ok
        assert "09:00" in msg

    def test_add_only_flags_no_title(self, handler):
        ok, msg = handler.handle("add", ["--date", "2026-06-15"])
        assert not ok
        assert "Kein Titel" in msg

    def test_add_title_after_flags(self, handler):
        ok, msg = handler.handle("add", ["--date", "2026-06-15", "Meeting"])
        assert ok
        assert "Meeting" in msg


# ─── Show ───────────────────────────────────────────────────

class TestCalendarShow:
    def test_show_no_args(self, handler):
        ok, msg = handler.handle("show", [])
        assert not ok
        assert "Usage" in msg

    def test_show_existing(self, populated):
        ok, msg = populated.handle("show", ["1"])
        assert ok
        assert "Zahnarzt" in msg
        assert "Praxis Dr. X" in msg
        assert "TERMIN 1" in msg

    def test_show_not_found(self, handler):
        ok, msg = handler.handle("show", ["999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_show_recurring_flag(self, populated, cal_env):
        _, db_path = cal_env
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE assistant_calendar SET is_recurring=1 WHERE id=1")
        conn.commit()
        conn.close()
        ok, msg = populated.handle("show", ["1"])
        assert ok
        assert "Ja" in msg

    def test_show_with_description(self, populated, cal_env):
        _, db_path = cal_env
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE assistant_calendar SET description='Wichtig!' WHERE id=1")
        conn.commit()
        conn.close()
        ok, msg = populated.handle("show", ["1"])
        assert ok
        assert "Wichtig!" in msg


# ─── Done ───────────────────────────────────────────────────

class TestCalendarDone:
    def test_done_no_args(self, handler):
        ok, msg = handler.handle("done", [])
        assert not ok
        assert "Usage" in msg

    def test_done_single(self, populated, cal_env):
        _, db_path = cal_env
        ok, msg = populated.handle("done", ["1"])
        assert ok
        assert "erledigt" in msg
        assert "Zahnarzt" in msg
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM assistant_calendar WHERE id=1").fetchone()
        assert row["status"] == "erledigt"
        conn.close()

    def test_done_multiple(self, populated):
        ok, msg = populated.handle("done", ["1", "2"])
        assert ok
        assert "Zahnarzt" in msg
        assert "Besprechung" in msg

    def test_done_not_found(self, handler):
        ok, msg = handler.handle("done", ["999"])
        assert ok
        assert "WARN" in msg


# ─── Delete ─────────────────────────────────────────────────

class TestCalendarDelete:
    def test_delete_no_args(self, handler):
        ok, msg = handler.handle("delete", [])
        assert not ok
        assert "Usage" in msg

    def test_delete_existing(self, populated, cal_env):
        _, db_path = cal_env
        ok, msg = populated.handle("delete", ["1"])
        assert ok
        assert "geloescht" in msg
        assert "Zahnarzt" in msg
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT * FROM assistant_calendar WHERE id=1").fetchone()
        assert row is None
        conn.close()

    def test_delete_not_found(self, handler):
        ok, msg = handler.handle("delete", ["999"])
        assert not ok
        assert "nicht gefunden" in msg


# ─── Range View ─────────────────────────────────────────────

class TestRangeView:
    def test_empty_range(self, handler):
        start = datetime(2099, 1, 1)
        end = datetime(2099, 1, 7)
        ok, msg = handler._range_view(start, end, "Testbereich")
        assert ok
        assert "Keine Termine" in msg

    def test_range_groups_by_day(self, populated):
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0)
        end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59)
        ok, msg = populated._range_view(start, end, "Testwoche")
        assert ok
        assert "---" in msg

    def test_range_shows_location(self, populated):
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0)
        end = (now + timedelta(days=2)).replace(hour=23, minute=59, second=59)
        ok, msg = populated._range_view(start, end, "Diese Woche")
        assert ok
        assert "Praxis Dr. X" in msg


# ─── Helper Methods ─────────────────────────────────────────

class TestHelperMethods:
    def test_parse_ids_integers(self, handler):
        ids, rest = handler._parse_ids(["1", "2", "hello", "3"])
        assert ids == [1, 2, 3]
        assert rest == ["hello"]

    def test_parse_ids_empty(self, handler):
        ids, rest = handler._parse_ids([])
        assert ids == []
        assert rest == []

    def test_parse_ids_no_numbers(self, handler):
        ids, rest = handler._parse_ids(["abc", "def"])
        assert ids == []
        assert rest == ["abc", "def"]

    def test_get_arg_flag(self, handler):
        result = handler._get_arg(["--date", "2026-01-01", "--time", "10:00"], "--date")
        assert result == "2026-01-01"

    def test_get_arg_equals_syntax(self, handler):
        result = handler._get_arg(["--date=2026-01-01"], "--date")
        assert result == "2026-01-01"

    def test_get_arg_missing(self, handler):
        result = handler._get_arg(["--time", "10:00"], "--date")
        assert result is None

    def test_get_arg_flag_at_end(self, handler):
        result = handler._get_arg(["--date"], "--date")
        assert result is None


# ─── Edge Cases ─────────────────────────────────────────────

class TestEdgeCases:
    def test_add_with_end_time(self, handler, cal_env):
        _, db_path = cal_env
        ok, msg = handler.handle("add", ["Meeting", "--time", "10:00", "--end", "11:30"])
        assert ok
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assistant_calendar WHERE title='Meeting'").fetchone()
        assert "11:30" in row["end_datetime"]
        conn.close()

    def test_weekdays_de_constant(self, handler):
        assert len(handler.WEEKDAYS_DE) == 7
        assert handler.WEEKDAYS_DE[0] == "Mo"
        assert handler.WEEKDAYS_DE[6] == "So"

    def test_month_december(self, handler):
        with patch("hub.calendar_handler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 12, 15, 10, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            ok, msg = handler.handle("month", [])
            assert ok
            assert "Dezember" in msg
