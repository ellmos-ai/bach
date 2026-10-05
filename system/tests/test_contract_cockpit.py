# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ContractCockpitHandler (hub/contract_cockpit.py)."""
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.contract_cockpit import ContractCockpitHandler
from hub._services.contract_dates import calc_next_cancellation


@pytest.fixture
def handler(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "bach.db").touch()
    return ContractCockpitHandler(tmp_path)


def _db_path(tmp_path):
    return tmp_path / "data" / "bach.db"


def _insert(db_path):
    """Testvertrag einfuegen (frist=0 -> naechste_kuendigung == ablauf_datum)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO contracts
        (type, status, name, anbieter, beginn_datum, ablauf_datum,
         kuendigungsfrist_monate, verlaengerung_monate, betrag_monatlich,
         zahlungsintervall)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "abo",
            "aktiv",
            "TestAbo",
            "TestGmbH",
            "2020-01-01",
            (date.today() + timedelta(days=45)).isoformat(),
            0,
            12,
            9.99,
            "monatlich",
        ),
    )
    conn.commit()
    conn.close()


class TestInit:
    def test_init_status(self, handler):
        ok, msg = handler.handle("init", [])
        assert ok is True
        out = json.loads(msg)
        assert out["status"] == "initialized"

    def test_init_creates_tables(self, handler, tmp_path):
        handler.handle("init", [])
        conn = sqlite3.connect(str(_db_path(tmp_path)))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "contracts" in tables
        assert "contract_reminders" in tables
        assert "contract_types" in tables
        assert "contract_patterns" in tables
        conn.close()

    def test_init_seeds_contract_types(self, handler, tmp_path):
        handler.handle("init", [])
        conn = sqlite3.connect(str(_db_path(tmp_path)))
        count = conn.execute("SELECT COUNT(*) FROM contract_types").fetchone()[0]
        conn.close()
        assert count == 7

    def test_init_seeds_contract_patterns(self, handler, tmp_path):
        handler.handle("init", [])
        conn = sqlite3.connect(str(_db_path(tmp_path)))
        count = conn.execute("SELECT COUNT(*) FROM contract_patterns").fetchone()[0]
        conn.close()
        assert count == 6


class TestList:
    def test_list_all_contains_testabo(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("list", [])
        assert ok is True
        out = json.loads(msg)
        assert any(c["name"] == "TestAbo" for c in out)

    def test_list_type_filter_no_match(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("list", ["type=versicherung"])
        assert ok is True
        assert json.loads(msg) == []

    def test_list_status_filter_match(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("list", ["status=aktiv"])
        assert ok is True
        out = json.loads(msg)
        assert any(c["name"] == "TestAbo" for c in out)

    def test_list_status_filter_no_match(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("list", ["status=gekuendigt"])
        assert ok is True
        assert json.loads(msg) == []


class TestFristen:
    def test_fristen_updates_contract(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("fristen", [])
        assert ok is True
        out = json.loads(msg)
        assert isinstance(out["updated"], int)
        assert out["updated"] >= 1
        assert out["reminders_added"] >= 0

        ok2, msg2 = handler.handle("list", [])
        assert ok2 is True
        out2 = json.loads(msg2)
        row = [c for c in out2 if c["name"] == "TestAbo"][0]
        ablauf = date.today() + timedelta(days=45)
        expected = calc_next_cancellation(
            date(2020, 1, 1), ablauf, 0, 12, date.today()
        )
        assert row["naechste_kuendigung"] == str(expected)
        assert row["naechste_kuendigung"] == ablauf.isoformat()


class TestCosts:
    def test_costs_totals(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("costs", [])
        assert ok is True
        out = json.loads(msg)
        assert out["total_monthly"] == pytest.approx(9.99)
        assert out["total_yearly"] == round(9.99 * 12, 2)
        assert out["monthly_by_type"]["abo"] == pytest.approx(9.99)

    def test_costs_filter_type(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("costs", ["type=abo"])
        assert ok is True
        out = json.loads(msg)
        assert out["filter_type"] == "abo"


class TestExport:
    def test_export_default_csv(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("export", [])
        assert ok is True
        out = json.loads(msg)
        path = Path(out["path"])
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "name" in text
        assert "TestAbo" in text

    def test_export_json(self, handler, tmp_path):
        handler.handle("init", [])
        _insert(_db_path(tmp_path))
        ok, msg = handler.handle("export", ["fmt=json"])
        assert ok is True
        out = json.loads(msg)
        path = Path(out["path"])
        assert path.exists()
        contracts = json.loads(path.read_text(encoding="utf-8"))
        names = [c["name"] for c in contracts]
        assert "TestAbo" in names


class TestScan:
    def test_scan_finds_pattern(self, handler, tmp_path):
        handler.handle("init", [])
        ok, msg = handler.handle("scan", ["text=Meine Spotify Rechnung"])
        assert ok is True
        out = json.loads(msg)
        assert len(out["found"]) == 1
        assert out["found"][0]["anbieter"] == "Spotify"
        assert out["found"][0]["type"] == "abo"

        conn = sqlite3.connect(str(_db_path(tmp_path)))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM contracts WHERE anbieter = ?", ("Spotify",)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["status"] == "erkannt"
        assert row["name"] == "Streaming / Medien"
        assert row["kuendigungsfrist_monate"] == 1

    def test_scan_skips_existing(self, handler, tmp_path):
        handler.handle("init", [])
        handler.handle("scan", ["text=Meine Spotify Rechnung"])
        ok, msg = handler.handle("scan", ["text=Meine Spotify Rechnung"])
        assert ok is True
        out = json.loads(msg)
        assert out["found"] == []


class TestReminders:
    def test_reminders_returns_list(self, handler, tmp_path):
        handler.handle("init", [])
        ok, msg = handler.handle("reminders", [])
        assert ok is True
        assert isinstance(json.loads(msg), list)


class TestUnknownOperation:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("bogus", [])
        assert ok is False
        out = json.loads(msg)
        assert "Unbekannte Operation" in out["error"]
