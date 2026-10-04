"""Calendar provenance and due-date contracts using only a disposable SQLite DB."""

import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from gui.api import unified_api


class LifeCalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "calendar.db"
        self.db_patch = patch.object(unified_api, "BACH_DB", self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_new_event_is_user_origin_even_if_caller_requests_system(self):
        response = asyncio.run(unified_api.create_calendar_event({
            "title": "Zahnarzt", "start_datetime": "2026-10-03 09:00:00",
            "event_origin": "system",
        }))
        self.assertTrue(response["ok"])
        events = asyncio.run(unified_api.get_calendar_events(view="day", date="2026-10-03", include_routines=False))["events"]
        self.assertEqual(events[0]["origin"], "user")
        self.assertEqual(events[0]["title"], "Zahnarzt")

    def test_legacy_event_has_unknown_origin(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TABLE assistant_calendar(id INTEGER PRIMARY KEY, title TEXT, start_datetime TEXT, dist_type TEXT)")
            conn.execute("INSERT INTO assistant_calendar(title,start_datetime) VALUES (?,?)", ("Alttermin", "2026-10-03 10:00:00"))
            conn.commit()
        events = asyncio.run(unified_api.get_calendar_events(view="day", date="2026-10-03", include_routines=False))["events"]
        self.assertEqual(events[0]["origin"], "unknown")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertNotIn("event_origin", {row[1] for row in conn.execute("PRAGMA table_info(assistant_calendar)")})

    def test_legacy_schema_refuses_new_write_until_explicit_migration(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TABLE assistant_calendar(id INTEGER PRIMARY KEY, title TEXT, start_datetime TEXT)")
        with self.assertRaises(HTTPException) as error:
            asyncio.run(unified_api.create_calendar_event({"title":"Neu", "start_datetime":"2026-10-03 09:00:00"}))
        self.assertEqual(error.exception.status_code, 503)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='household_routines'").fetchone())

    def test_routine_without_due_date_is_not_a_fabricated_event(self):
        with closing(sqlite3.connect(self.db)) as conn:
            unified_api._ensure_calendar_tables(conn)
            conn.execute("INSERT INTO household_routines(name,next_due) VALUES (?,NULL)", ("Ohne Termin",))
        events = asyncio.run(unified_api.get_calendar_events(view="day", date="2026-10-03", include_routines=True))["events"]
        self.assertEqual(events, [])

    def test_week_query_only_returns_its_seven_days(self):
        for title, when in (("Vorher", "2026-09-27 09:00:00"), ("Montag", "2026-09-28 09:00:00"),
                            ("Sonntag", "2026-10-04 09:00:00"), ("Danach", "2026-10-05 09:00:00")):
            asyncio.run(unified_api.create_calendar_event({"title": title, "start_datetime": when}))
        events = asyncio.run(unified_api.get_calendar_events(view="week", date="2026-10-03", include_routines=False))["events"]
        self.assertEqual([event["title"] for event in events], ["Montag", "Sonntag"])

    def test_private_calendar_requires_device_token_even_on_loopback(self):
        from gui import server

        with patch.object(server, "validate_token", side_effect=lambda token: {"name": "fixture"} if token == "valid-fixture" else None):
            # No lifespan startup: it starts the production file watcher.
            client = TestClient(server.app)
            try:
                url = "/api/calendar/events?view=day&date=2026-10-03&include_routines=false"
                self.assertEqual(client.get(url).status_code, 401)
                self.assertEqual(client.get(url, headers={"Authorization": "Bearer invalid-fixture"}).status_code, 403)
                self.assertEqual(client.get(url, headers={"Authorization": "Bearer valid-fixture"}).status_code, 200)
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
