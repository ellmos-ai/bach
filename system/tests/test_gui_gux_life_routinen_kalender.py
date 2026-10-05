# SPDX-License-Identifier: MIT
"""
Contract and acceptance tests for Life, Routines, and Calendar providers.
Covers GUX-048..060 and NAV-AUFG-02.
"""

import asyncio
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from gui import server
from gui.api import unified_api


class TestGuxLifeRoutinenKalender(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_user.db"
        self.calendar_db = Path(self.tmp_dir.name) / "test_calendar.db"

        # Patch BACH_DB in unified_api
        self.db_patch = patch.object(unified_api, "BACH_DB", self.calendar_db)
        self.db_patch.start()

        # Initialize user.db with routines table
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    interval_type TEXT NOT NULL,
                    interval_value INTEGER DEFAULT 1,
                    specific_day TEXT,
                    custom_cron TEXT,
                    preferred_time TEXT,
                    duration_minutes INTEGER,
                    priority INTEGER DEFAULT 2,
                    is_active INTEGER DEFAULT 1,
                    next_due_at TEXT,
                    last_completed_at TEXT,
                    assigned_agent TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

        # Initialize calendar DB with assistant_calendar
        with closing(sqlite3.connect(self.calendar_db)) as conn:
            unified_api._ensure_calendar_tables(conn)
            conn.commit()

    def tearDown(self):
        self.db_patch.stop()
        try:
            self.tmp_dir.cleanup()
        except OSError:
            pass

    # ── GUX-048 & GUX-049: Separation of System- and Personal Routines ──

    def test_gux_048_routinen_tab_bach_separation(self):
        """GUX-048: /routinen?tab=bach serves daemon system jobs and provides link to personal life routines."""
        client = TestClient(server.app, base_url="http://127.0.0.1:8000")
        try:
            resp = client.get("/routinen?tab=bach")
            self.assertEqual(resp.status_code, 200)
            text = resp.text
            # Checks for BACH system routines tab
            self.assertIn("tab-bach", text)
            self.assertIn("Zeitgesteuerte BACH-Jobs", text)
            # Checks for clear reference/link to /life?tab=routinen for personal routines
            self.assertIn("/life?tab=routinen", text)
        finally:
            client.close()

    def test_gux_049_life_tab_routinen_inline_view(self):
        """GUX-049: /life?tab=routinen returns 200 without redirect and provides full inline personal routine UI."""
        client = TestClient(server.app, base_url="http://127.0.0.1:8000")
        try:
            resp = client.get("/life?tab=routinen", follow_redirects=False)
            self.assertEqual(resp.status_code, 200)
            text = resp.text
            self.assertIn("pane-routinen", text)
            self.assertIn("Deine Routinen", text)
            self.assertIn("personal-routines-list", text)
        finally:
            client.close()

    # ── NAV-AUFG-02 & GUX-049: Routine Agent Binding & CRUD ──

    def test_nav_aufg_02_routine_agent_binding_and_crud(self):
        """NAV-AUFG-02: User routines persist assigned_agent and allow full lifecycle without fabricating system routines."""
        with (
            patch.object(server, "get_user_db", side_effect=lambda: sqlite3.connect(self.db_path)),
            patch.object(server, "validate_token", side_effect=lambda token: {"name": "fixture"} if token == "valid-fixture" else None),
        ):
            client = TestClient(server.app, base_url="http://127.0.0.1:8000")
            try:
                headers = {"Authorization": "Bearer valid-fixture"}

                # Normal operation without BACH_LEGACY_DOMAIN_WRITES: 423 Locked (Domain gate)
                with patch.dict(os.environ, {}, clear=True):
                    fail_res = client.post(
                        "/api/routines",
                        json={"name": "Test", "interval_type": "taeglich"},
                        headers=headers,
                    )
                    self.assertEqual(fail_res.status_code, 423)
                    self.assertIn("[GESPERRT]", fail_res.json()["detail"])

                # With migration switch BACH_LEGACY_DOMAIN_WRITES=1: writes allowed
                with patch.dict(os.environ, {"BACH_LEGACY_DOMAIN_WRITES": "1"}):
                    # 1. Create routine with assigned_agent
                    create_payload = {
                        "name": "Abendliches Code-Review",
                        "category": "Arbeit",
                        "interval_type": "taeglich",
                        "priority": 1,
                        "duration_minutes": 30,
                        "assigned_agent": "codex",
                    }
                    res = client.post("/api/routines", json=create_payload, headers=headers)
                    self.assertEqual(res.status_code, 200)
                    routine_id = res.json()["id"]

                    # 2. Read back routine and verify assigned_agent
                    res = client.get("/api/routines", headers=headers)
                    self.assertEqual(res.status_code, 200)
                    data = res.json()
                    self.assertTrue(data["success"])
                    routines = data["routines"]
                    matching = [r for r in routines if r["id"] == routine_id]
                    self.assertEqual(len(matching), 1)
                    self.assertEqual(matching[0]["assigned_agent"], "codex")

                    # 3. Update routine with different agent
                    update_payload = {
                        "name": "Abendliches Code-Review",
                        "category": "Arbeit",
                        "interval_type": "taeglich",
                        "priority": 1,
                        "duration_minutes": 45,
                        "assigned_agent": "gemini",
                    }
                    res = client.put(f"/api/routines/{routine_id}", json=update_payload, headers=headers)
                    self.assertEqual(res.status_code, 200)

                    # Verify update
                    res = client.get("/api/routines", headers=headers)
                    matching = [r for r in res.json()["routines"] if r["id"] == routine_id]
                    self.assertEqual(matching[0]["assigned_agent"], "gemini")
                    self.assertEqual(matching[0]["duration_minutes"], 45)

                    # 4. Complete routine
                    res = client.post(f"/api/routines/{routine_id}/complete", headers=headers)
                    self.assertEqual(res.status_code, 200)
                    self.assertTrue(res.json()["success"])

                    # 5. Delete routine
                    res = client.delete(f"/api/routines/{routine_id}", headers=headers)
                    self.assertEqual(res.status_code, 200)
                    res = client.get("/api/routines", headers=headers)
                    matching = [r for r in res.json()["routines"] if r["id"] == routine_id]
                    self.assertEqual(len(matching), 0)
            finally:
                client.close()

    # ── GUX-051..054 & GUX-059: Life Providers Endpoint & Honest In-Arbeit Gates ──

    def test_gux_051_054_059_life_providers_endpoint(self):
        """GUX-051, 052, 054, 059: /api/life/providers reports honest in-arbeit states without fake data."""
        with patch.object(server, "validate_token", side_effect=lambda token: {"name": "fixture"} if token == "valid-fixture" else None):
            client = TestClient(server.app, base_url="http://127.0.0.1:8000")
            try:
                # 1. Unauthenticated request must fail (Perimeter security)
                self.assertEqual(client.get("/api/life/providers").status_code, 401)

                # 2. Authenticated request with device token
                res = client.get("/api/life/providers", headers={"Authorization": "Bearer valid-fixture"})
                self.assertEqual(res.status_code, 200)
                data = res.json()

                # Required provider keys
                self.assertIn("routinika", data)
                self.assertIn("uptoday", data)
                self.assertIn("health", data)
                self.assertIn("balance", data)

                # Health: GUX-051 privacy-compliant / honest in-arbeit gate
                self.assertFalse(data["health"]["available"])
                self.assertIn("keine Gesundheitsdaten", data["health"]["message"])

                # Balance: GUX-052 honest stub with missing adapter steps
                self.assertFalse(data["balance"]["available"])
                self.assertIn("In Arbeit", data["balance"]["message"])

                # Routinika & UpToDay: GUX-054 & GUX-059 conditional availability
                self.assertIn("available", data["routinika"])
                self.assertIn("available", data["uptoday"])
            finally:
                client.close()

    # ── GUX-053: Standalone Focus Timer Window ──

    def test_gux_053_focus_timer_detached_window_contract(self):
        """GUX-053: Focus timer opens popup only upon user interaction, and ?focus=1 activates standalone mode."""
        client = TestClient(server.app, base_url="http://127.0.0.1:8000")
        try:
            # 1. Normal life page has focus window button and function
            res = client.get("/life?tab=selbstmanagement")
            self.assertEqual(res.status_code, 200)
            self.assertIn("btn-focus-window", res.text)
            self.assertIn("openFocusWindow()", res.text)
            self.assertIn("life?tab=selbstmanagement&focus=1", res.text)

            # 2. When loaded with ?focus=1, script applies .standalone-focus
            res_focus = client.get("/life?tab=selbstmanagement&focus=1")
            self.assertEqual(res_focus.status_code, 200)
            self.assertIn("standalone-focus", res_focus.text)
        finally:
            client.close()

    # ── GUX-055..058: 4 Calendar Views Structure ──

    def test_gux_055_058_calendar_four_views_structure(self):
        """GUX-055..058: Day (blue row), Week (7 cols), Month (equal tiles), Year (mini-day boxes)."""
        client = TestClient(server.app, base_url="http://127.0.0.1:8000")
        try:
            res = client.get("/life?tab=kalender")
            self.assertEqual(res.status_code, 200)
            text = res.text

            # View buttons
            self.assertIn('data-view="day"', text)
            self.assertIn('data-view="week"', text)
            self.assertIn('data-view="month"', text)
            self.assertIn('data-view="year"', text)

            # GUX-055: Day view timeline container & current-hour highlight class
            self.assertIn("day-timeline-container", text)
            self.assertIn("current-hour", text)

            # GUX-056: Week view 7-column grid
            self.assertIn("week-grid-container", text)

            # GUX-057: Month view equal grid matrix
            self.assertIn("month-days-matrix", text)
            self.assertIn("month-day-cell", text)

            # GUX-058: Year view with mini-day boxes
            self.assertIn("year-quarters-grid", text)
            self.assertIn("mini-day", text)
        finally:
            client.close()

    # ── GUX-060: Calendar Origin Filter ──

    def test_gux_060_calendar_origin_filtering(self):
        """GUX-060: /api/calendar/events filters by origin: all, user, system, without_system, unknown."""
        # Seed events with distinct origins
        asyncio.run(
            unified_api.create_calendar_event(
                {"title": "Nutzer-Termin", "start_datetime": "2026-10-05 10:00:00"}
            )
        )
        with closing(sqlite3.connect(self.calendar_db)) as conn:
            conn.execute(
                "INSERT INTO assistant_calendar(title, start_datetime, event_origin) VALUES (?,?,?)",
                ("System-Termin", "2026-10-05 12:00:00", "system"),
            )
            conn.execute(
                "INSERT INTO assistant_calendar(title, start_datetime, event_origin) VALUES (?,?,?)",
                ("Alt-Termin-Ohne-Herkunft", "2026-10-05 14:00:00", "unknown"),
            )
            conn.commit()

        # 1. origin=all
        events_all = asyncio.run(
            unified_api.get_calendar_events(view="day", date="2026-10-05", include_routines=False, origin="all")
        )["events"]
        self.assertEqual(len(events_all), 3)

        # 2. origin=user
        events_user = asyncio.run(
            unified_api.get_calendar_events(view="day", date="2026-10-05", include_routines=False, origin="user")
        )["events"]
        self.assertEqual(len(events_user), 1)
        self.assertEqual(events_user[0]["title"], "Nutzer-Termin")
        self.assertEqual(events_user[0]["origin"], "user")

        # 3. origin=system
        events_sys = asyncio.run(
            unified_api.get_calendar_events(view="day", date="2026-10-05", include_routines=False, origin="system")
        )["events"]
        self.assertEqual(len(events_sys), 1)
        self.assertEqual(events_sys[0]["title"], "System-Termin")
        self.assertEqual(events_sys[0]["origin"], "system")

        # 4. origin=without_system
        events_no_sys = asyncio.run(
            unified_api.get_calendar_events(view="day", date="2026-10-05", include_routines=False, origin="without_system")
        )["events"]
        self.assertEqual(len(events_no_sys), 2)
        titles = {e["title"] for e in events_no_sys}
        self.assertIn("Nutzer-Termin", titles)
        self.assertIn("Alt-Termin-Ohne-Herkunft", titles)
        self.assertNotIn("System-Termin", titles)

        # 5. origin=unknown
        events_unknown = asyncio.run(
            unified_api.get_calendar_events(view="day", date="2026-10-05", include_routines=False, origin="unknown")
        )["events"]
        self.assertEqual(len(events_unknown), 1)
        self.assertEqual(events_unknown[0]["title"], "Alt-Termin-Ohne-Herkunft")
        self.assertEqual(events_unknown[0]["origin"], "unknown")


if __name__ == "__main__":
    unittest.main()
