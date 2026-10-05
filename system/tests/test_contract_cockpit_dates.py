# SPDX-License-Identifier: MIT
"""Tests für ContractCockpitHandler Fristenberechnung (init + fristen)."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from hub.contract_cockpit import ContractCockpitHandler


@pytest.fixture
def handler(tmp_path):
    base = tmp_path / "bach" / "system"
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "bach.db").touch()
    return ContractCockpitHandler(base)


def _insert_contracts(handler):
    """Hilfsfunktion: diverse Testverträge in die DB einspielen."""
    with handler._connection() as conn:
        conn.executescript(
            """
            INSERT INTO contracts
            (type, status, name, anbieter, beginn_datum, ablauf_datum,
             kuendigungsfrist_monate, verlaengerung_monate)
            VALUES
            ('abo', 'aktiv', 'Streaming', 'Netflix', '2024-01-01', NULL, 1, 1),
            ('versicherung', 'aktiv', 'Kfz', 'HUK', '2023-07-01', '2026-06-30', 3, 12),
            ('versicherung', 'aktiv', 'Hausrat', 'Allianz', '2022-03-01', NULL, 3, 12),
            ('abo', 'gekuendigt', 'Altabo', 'Sky', '2020-01-01', NULL, 1, 12);
            """
        )
        conn.commit()


def test_init_db_creates_tables_and_defaults(handler):
    handler._init_db()
    assert handler.target_file.exists()
    with handler._connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "contracts" in tables
        assert "contract_reminders" in tables
        assert "contract_payments" in tables
        assert "contract_claims" in tables
        assert "contract_types" in tables
        assert "contract_patterns" in tables

        types = conn.execute("SELECT name FROM contract_types").fetchall()
        assert any("Kfz-Versicherung" in t["name"] for t in types)

        patterns = conn.execute("SELECT pattern FROM contract_patterns").fetchall()
        assert len(patterns) > 0


def test_handle_init(handler):
    ok, msg = handler.handle("init", [])
    assert ok is True
    data = json.loads(msg)
    assert data["status"] == "initialized"
    assert handler.target_file.exists()


def test_recalc_cancellations_with_fixed_today(handler, monkeypatch):
    handler._init_db()
    _insert_contracts(handler)

    fixed_today = date(2025, 3, 15)
    monkeypatch.setattr("hub.contract_cockpit.date", type("D", (), {"today": staticmethod(lambda: fixed_today)}))

    updated = handler._recalc_cancellations()
    assert updated == 3  # drei aktive Verträge bekommen neue naechste_kuendigung

    with handler._connection() as conn:
        rows = {
            row["name"]: row["naechste_kuendigung"]
            for row in conn.execute("SELECT name, naechste_kuendigung FROM contracts").fetchall()
        }

    # monatliches Abo seit 2024-01-01, Frist 1 Monat -> naechstes Intervallende 2025-04-01
    assert rows["Streaming"] == "2025-04-01"

    # Versicherung mit Ablauf 2026-06-30, Frist 3 Monate -> 2026-03-30
    assert rows["Kfz"] == "2026-03-30"

    # jaehrliche Versicherung seit 2022-03-01, Frist 3 Monate vor Intervallende
    # naechstes Intervallende 2026-03-01 -> Kuendigungsfrist 2025-12-01
    assert rows["Hausrat"] == "2025-12-01"

    # gekuendigter Vertrag bleibt unveraendert
    assert rows["Altabo"] is None


def test_recalc_cancellation_idempotent(handler, monkeypatch):
    handler._init_db()
    _insert_contracts(handler)

    fixed_today = date(2025, 3, 15)
    monkeypatch.setattr("hub.contract_cockpit.date", type("D", (), {"today": staticmethod(lambda: fixed_today)}))

    assert handler._recalc_cancellations() == 3
    # Zweiter Durchlauf darf keine Aenderungen mehr finden
    assert handler._recalc_cancellations() == 0


def test_handle_fristen(handler, monkeypatch):
    handler._init_db()
    _insert_contracts(handler)

    fixed_today = date(2025, 3, 15)
    monkeypatch.setattr("hub.contract_cockpit.date", type("D", (), {"today": staticmethod(lambda: fixed_today)}))

    ok, msg = handler.handle("fristen", [])
    assert ok is True
    data = json.loads(msg)
    assert data["updated"] == 3
    # Engine erzeugt Erinnerungen für:
    # - Streaming-Kündigung 2025-04-01 (im 60-Tage-Fenster)
    # - Kfz-Kündigung 2026-03-30 (vorausberechnete Frist)
    # - Hausrat-Kündigung 2025-12-01 (vorausberechnete Frist)
    # Kfz-Ablauf 2026-06-30 liegt ausserhalb des Horizonts.
    assert data["reminders_added"] == 3


def test_handle_fristen_no_changes_when_recalc_already_up_to_date(handler, monkeypatch):
    handler._init_db()
    _insert_contracts(handler)

    fixed_today = date(2025, 3, 15)
    monkeypatch.setattr("hub.contract_cockpit.date", type("D", (), {"today": staticmethod(lambda: fixed_today)}))

    handler._recalc_cancellations()
    ok, msg = handler.handle("fristen", [])
    assert ok is True
    data = json.loads(msg)
    assert data["updated"] == 0
    # Bei bereits vorausberechneten Fristen werden zusätzlich
    # Streaming-, Kfz- und Hausrat-Kündigung sowie der Kfz-Ablauf
    # als Erinnerungen erkannt.
    assert data["reminders_added"] == 4
