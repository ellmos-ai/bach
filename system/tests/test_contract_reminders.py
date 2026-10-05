# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for contract_reminders service (hub/_services/contract_reminders.py)."""

from datetime import date
from pathlib import Path
import sqlite3
import sys

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.contract_cockpit import CREATE_TABLES
from hub._services.contract_reminders import (
    VALID_REMINDER_STATUS,
    get_due_reminders,
    get_pending_reminders,
    mark_reminder,
    sync_contract_reminders,
)

TODAY = date(2025, 1, 1)


class _TestConnection(sqlite3.Connection):
    """Connection-Subklasse, damit c.contract_id gesetzt werden kann."""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", factory=_TestConnection)
    c.row_factory = sqlite3.Row
    c.executescript(CREATE_TABLES)
    cur = c.execute(
        """INSERT INTO contracts
        (type, status, name, anbieter, beginn_datum, ablauf_datum, naechste_kuendigung)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("abo", "aktiv", "TestAbo", "TestGmbH", "2020-01-01", None, None),
    )
    c.commit()
    c.contract_id = cur.lastrowid
    yield c
    c.close()


def _contract(conn, **overrides):
    base = {
        "id": conn.contract_id,
        "name": "TestAbo",
        "anbieter": "TestGmbH",
        "naechste_kuendigung": None,
        "ablauf_datum": None,
    }
    base.update(overrides)
    return base


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM contract_reminders").fetchone()[0]


class TestSyncContractReminders:
    def test_sync_creates_kuendigung_and_ablauf(self, conn):
        rems = sync_contract_reminders(
            conn,
            _contract(conn, naechste_kuendigung="2025-01-15", ablauf_datum="2025-02-01"),
            today=TODAY,
        )
        conn.commit()
        assert len(rems) == 2
        assert {r["type"] for r in rems} == {"kuendigungsfrist", "ablauf"}
        by_type = {r["type"]: r for r in rems}
        assert by_type["kuendigungsfrist"]["subject"] == "Kündigungsfrist für TestAbo"
        assert by_type["ablauf"]["subject"] == "Ablaufdatum für TestAbo"
        assert by_type["kuendigungsfrist"]["trigger_date"] == "2025-01-15"
        assert by_type["ablauf"]["trigger_date"] == "2025-02-01"
        assert all(r["contract_id"] == conn.contract_id for r in rems)
        assert _count(conn) == 2

    def test_sync_no_dedup_on_repeat(self, conn):
        contract = _contract(
            conn, naechste_kuendigung="2025-01-15", ablauf_datum="2025-02-01"
        )
        first = sync_contract_reminders(conn, contract, today=TODAY)
        second = sync_contract_reminders(conn, contract, today=TODAY)
        conn.commit()
        assert len(first) == 2
        assert len(second) == 2
        # Aktuelles Verhalten: INSERT OR IGNORE ohne UNIQUE-Constraint dedupt
        # nicht -> Duplikate entstehen bei wiederholtem Sync.
        assert _count(conn) == 4

    def test_sync_outside_window(self, conn):
        rems = sync_contract_reminders(
            conn, _contract(conn, naechste_kuendigung="2025-04-01"), today=TODAY
        )
        conn.commit()
        assert rems == []
        assert _count(conn) == 0

    def test_sync_no_dates(self, conn):
        assert sync_contract_reminders(conn, _contract(conn), today=TODAY) == []
        assert _count(conn) == 0

    def test_sync_missing_contract_id(self, conn):
        assert (
            sync_contract_reminders(
                conn, {"naechste_kuendigung": "2025-01-15"}, today=TODAY
            )
            == []
        )
        assert _count(conn) == 0

    def test_sync_label_fallback_to_anbieter(self, conn):
        rems = sync_contract_reminders(
            conn,
            {
                "id": conn.contract_id,
                "name": None,
                "anbieter": "TestGmbH",
                "naechste_kuendigung": "2025-01-15",
                "ablauf_datum": None,
            },
            today=TODAY,
        )
        assert len(rems) == 1
        assert rems[0]["subject"] == "Kündigungsfrist für TestGmbH"


class TestGetDueReminders:
    def test_only_pending_within_horizon(self, conn):
        sync_contract_reminders(
            conn,
            _contract(conn, naechste_kuendigung="2025-01-15", ablauf_datum="2025-02-01"),
            today=TODAY,
        )
        # Eine Erinnerung als done markieren
        first_id = conn.execute(
            "SELECT id FROM contract_reminders ORDER BY id LIMIT 1"
        ).fetchone()[0]
        assert mark_reminder(conn, first_id, "done") is True
        # Eine weit in der Zukunft liegende pendende Erinnerung
        conn.execute(
            """INSERT INTO contract_reminders (contract_id, reminder_type, trigger_date, subject)
            VALUES (?, ?, ?, ?)""",
            (conn.contract_id, "ablauf", "2026-01-01", "Ablaufdatum für TestAbo"),
        )
        conn.commit()

        due = get_due_reminders(conn, today=TODAY, lookahead_days=60)
        assert len(due) == 1
        assert due[0]["status"] == "pending"
        assert due[0]["trigger_date"] <= "2025-03-02"
        # Join-Felder aus contracts
        assert due[0]["name"] == "TestAbo"
        assert due[0]["anbieter"] == "TestGmbH"
        assert due[0]["type"] == "abo"


class TestGetPendingReminders:
    def test_only_pending_sorted_ascending(self, conn):
        for trigger, status in (
            ("2025-03-01", "pending"),
            ("2025-01-10", "pending"),
            ("2025-02-01", "done"),
        ):
            conn.execute(
                """INSERT INTO contract_reminders
                (contract_id, reminder_type, trigger_date, subject, status)
                VALUES (?, ?, ?, ?, ?)""",
                (conn.contract_id, "kuendigungsfrist", trigger, "Betreff", status),
            )
        conn.commit()

        pending = get_pending_reminders(conn)
        assert len(pending) == 2
        assert [r["trigger_date"] for r in pending] == ["2025-01-10", "2025-03-01"]
        assert all(r["status"] == "pending" for r in pending)
        assert all(isinstance(r, dict) for r in pending)
        assert pending[0]["name"] == "TestAbo"
        assert pending[0]["anbieter"] == "TestGmbH"


class TestMarkReminder:
    def test_valid_status_values(self):
        assert VALID_REMINDER_STATUS == ("sent", "done", "dismissed")

    @pytest.mark.parametrize("status", ["sent", "done", "dismissed"])
    def test_mark_valid_status(self, conn, status):
        conn.execute(
            """INSERT INTO contract_reminders
            (contract_id, reminder_type, trigger_date, subject)
            VALUES (?, ?, ?, ?)""",
            (conn.contract_id, "kuendigungsfrist", "2025-01-15", "Betreff"),
        )
        conn.commit()
        rid = conn.execute("SELECT id FROM contract_reminders").fetchone()[0]

        assert mark_reminder(conn, rid, status) is True
        conn.commit()
        db_status = conn.execute(
            "SELECT status FROM contract_reminders WHERE id = ?", (rid,)
        ).fetchone()[0]
        assert db_status == status

    def test_mark_invalid_status_raises(self, conn):
        with pytest.raises(ValueError):
            mark_reminder(conn, 1, "bogus")

    def test_mark_unknown_id_returns_false(self, conn):
        assert mark_reminder(conn, 9999, "done") is False
