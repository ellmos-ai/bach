"""Tests for VersicherungHandler (hub/versicherung.py)."""
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.versicherung import VersicherungHandler

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS fin_insurances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anbieter TEXT NOT NULL,
    tarif_name TEXT,
    police_nr TEXT UNIQUE,
    sparte TEXT NOT NULL,
    status TEXT DEFAULT 'aktiv',
    beginn_datum DATE,
    ablauf_datum DATE,
    kuendigungsfrist_monate INTEGER DEFAULT 3,
    verlaengerung_monate INTEGER DEFAULT 12,
    naechste_kuendigung DATE,
    beitrag REAL,
    zahlweise TEXT,
    steuer_relevant_typ TEXT,
    ordner_pfad TEXT,
    notizen TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fin_insurance_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insurance_id INTEGER REFERENCES fin_insurances(id),
    schadensdatum DATE,
    beschreibung TEXT,
    status TEXT DEFAULT 'offen',
    betrag_gefordert REAL,
    betrag_gezahlt REAL,
    aktenzeichen_versicherung TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS insurance_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT,
    description TEXT,
    when_useful TEXT,
    priority INTEGER DEFAULT 3,
    legal_requirement TEXT,
    typical_cost_range TEXT,
    dist_type INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DB_SCHEMA)
    conn.close()
    return db_path


@pytest.fixture
def handler(tmp_db):
    h = VersicherungHandler(tmp_db.parent)
    h._canonical_db = tmp_db
    h.user_db_path = tmp_db
    return h


@pytest.fixture
def populated_db(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    today = datetime.now().strftime("%Y-%m-%d")
    future_30 = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    past_10 = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

    conn.executemany(
        """INSERT INTO fin_insurances
           (anbieter, tarif_name, police_nr, sparte, status, beginn_datum,
            naechste_kuendigung, beitrag, zahlweise, steuer_relevant_typ, notizen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("Allianz", "Komfort Plus", "HP-001", "Haftpflicht", "aktiv",
             "2024-01-01", future_30, 5.90, "monatlich", "Sonstige_Vorsorge", None),
            ("HUK", "KFZ Basis", "KFZ-123", "KFZ", "aktiv",
             "2024-06-01", None, 89.50, "monatlich", None, "Fahrzeug: VW Golf"),
            ("AXA", "BU Gold", "BU-456", "BU", "aktiv",
             "2023-01-01", past_10, 120.0, "quartalsweise", "Basisvorsorge", None),
            ("DEVK", "Hausrat", "HR-789", "Hausrat", "gekuendigt",
             "2020-01-01", None, 8.50, "monatlich", None, None),
        ],
    )

    conn.executemany(
        """INSERT INTO fin_insurance_claims
           (insurance_id, schadensdatum, beschreibung, status, betrag_gefordert, betrag_gezahlt, aktenzeichen_versicherung)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (2, "2025-11-15", "Parkrempler", "offen", 1500.0, None, "AZ-2025-001"),
            (2, "2024-03-10", "Steinschlag", "reguliert", 350.0, 350.0, None),
        ],
    )

    conn.executemany(
        "INSERT INTO insurance_types (id, name, category, priority, when_useful) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Haftpflicht", "Personen", 1, "Immer"),
            (2, "BU", "Personen", 1, "Fuer Berufstaetige"),
            (3, "Hausrat", "Sach", 2, "Bei eigenem Haushalt"),
            (4, "Rechtsschutz", "Sach", 3, "Optional"),
        ],
    )

    conn.commit()
    conn.close()
    return tmp_db


@pytest.fixture
def pop_handler(populated_db):
    h = VersicherungHandler(populated_db.parent)
    h._canonical_db = populated_db
    h.user_db_path = populated_db
    return h


# ======================================================================
# Properties
# ======================================================================
class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "versicherung"

    def test_target_file(self, handler):
        assert handler.target_file == handler.user_db_path

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        expected = {"list", "show", "add", "edit", "delete", "status", "fristen", "check", "claim", "help"}
        assert set(ops.keys()) == expected


# ======================================================================
# Routing
# ======================================================================
class TestRouting:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("xyz", [])
        assert not ok
        assert "Unbekannte Operation" in msg

    def test_help(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok
        assert "VERSICHERUNG" in msg
        assert "BEFEHLE" in msg

    def test_empty_op_shows_help(self, handler):
        ok, msg = handler.handle("", [])
        assert ok
        assert "BEFEHLE" in msg


# ======================================================================
# Helpers
# ======================================================================
class TestHelpers:
    def test_parse_ids(self, handler):
        ids, rest = handler._parse_ids(["42", "--flag", "7", "text"])
        assert ids == [42, 7]
        assert rest == ["--flag", "text"]

    def test_parse_ids_empty(self, handler):
        ids, rest = handler._parse_ids([])
        assert ids == []
        assert rest == []

    def test_get_arg_flag(self, handler):
        assert handler._get_arg(["--beitrag", "50"], "--beitrag") == "50"

    def test_get_arg_equals(self, handler):
        assert handler._get_arg(["--beitrag=50"], "--beitrag") == "50"

    def test_get_arg_missing(self, handler):
        assert handler._get_arg(["--other", "x"], "--beitrag") is None

    def test_get_arg_flag_at_end(self, handler):
        assert handler._get_arg(["--beitrag"], "--beitrag") is None

    def test_parse_date_dd_mm_yyyy(self, handler):
        assert handler._parse_date("15.03.2026") == "2026-03-15"

    def test_parse_date_iso(self, handler):
        assert handler._parse_date("2026-03-15") == "2026-03-15"

    def test_parse_date_invalid(self, handler):
        assert handler._parse_date("not-a-date") is None

    def test_format_date(self, handler):
        assert handler._format_date("2026-03-15") == "15.03.2026"

    def test_format_date_none(self, handler):
        assert handler._format_date(None) == "---"

    def test_format_date_invalid(self, handler):
        assert handler._format_date("invalid") == "invalid"

    def test_calc_monthly_monatlich(self, handler):
        assert handler._calc_monthly(100.0, "monatlich") == 100.0

    def test_calc_monthly_jaehrlich(self, handler):
        assert abs(handler._calc_monthly(120.0, "jaehrlich") - 10.0) < 0.01

    def test_calc_monthly_quartalsweise(self, handler):
        assert abs(handler._calc_monthly(90.0, "quartalsweise") - 30.0) < 0.01

    def test_calc_monthly_halbjaehrlich(self, handler):
        assert abs(handler._calc_monthly(60.0, "halbjaehrlich") - 10.0) < 0.01

    def test_calc_monthly_none(self, handler):
        assert handler._calc_monthly(None, "monatlich") == 0.0

    def test_calc_yearly_monatlich(self, handler):
        assert abs(handler._calc_yearly(100.0, "monatlich") - 1200.0) < 0.01

    def test_calc_yearly_jaehrlich(self, handler):
        assert handler._calc_yearly(500.0, "jaehrlich") == 500.0

    def test_calc_yearly_quartalsweise(self, handler):
        assert abs(handler._calc_yearly(90.0, "quartalsweise") - 360.0) < 0.01

    def test_calc_yearly_none(self, handler):
        assert handler._calc_yearly(None, "monatlich") == 0.0


# ======================================================================
# LIST
# ======================================================================
class TestList:
    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "Keine Versicherungen" in msg

    def test_list_with_data(self, pop_handler):
        ok, msg = pop_handler.handle("list", [])
        assert ok
        assert "Allianz" in msg
        assert "HUK" in msg
        assert "AXA" in msg
        assert "DEVK" not in msg  # gekuendigt, filtered by default

    def test_list_all(self, pop_handler):
        ok, msg = pop_handler.handle("list", ["--all"])
        assert ok
        assert "DEVK" in msg
        assert "4 Versicherung" in msg

    def test_list_filter_sparte(self, pop_handler):
        ok, msg = pop_handler.handle("list", ["--sparte", "KFZ"])
        assert ok
        assert "HUK" in msg
        assert "Allianz" not in msg

    def test_list_filter_status(self, pop_handler):
        ok, msg = pop_handler.handle("list", ["--status", "gekuendigt"])
        assert ok
        assert "DEVK" in msg
        assert "Allianz" not in msg

    def test_list_shows_monthly_total(self, pop_handler):
        ok, msg = pop_handler.handle("list", [])
        assert ok
        assert "Gesamt monatlich" in msg
        assert "Gesamt jaehrlich" in msg


# ======================================================================
# SHOW
# ======================================================================
class TestShow:
    def test_show_no_id(self, handler):
        ok, msg = handler.handle("show", [])
        assert not ok
        assert "Usage" in msg

    def test_show_nonexistent(self, pop_handler):
        ok, msg = pop_handler.handle("show", ["999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_show_details(self, pop_handler):
        ok, msg = pop_handler.handle("show", ["1"])
        assert ok
        assert "Allianz" in msg
        assert "Komfort Plus" in msg
        assert "HP-001" in msg
        assert "Haftpflicht" in msg
        assert "5.90" in msg

    def test_show_with_claims(self, pop_handler):
        ok, msg = pop_handler.handle("show", ["2"])
        assert ok
        assert "HUK" in msg
        assert "SCHADENFAELLE" in msg
        assert "Parkrempler" in msg

    def test_show_without_claims(self, pop_handler):
        ok, msg = pop_handler.handle("show", ["1"])
        assert ok
        assert "SCHADENFAELLE" not in msg


# ======================================================================
# ADD
# ======================================================================
class TestAdd:
    def test_add_no_args(self, handler):
        ok, msg = handler.handle("add", [])
        assert not ok
        assert "Usage" in msg

    def test_add_missing_sparte(self, handler):
        ok, msg = handler.handle("add", ["--anbieter", "Test"])
        assert not ok

    def test_add_missing_anbieter(self, handler):
        ok, msg = handler.handle("add", ["--sparte", "KFZ"])
        assert not ok

    def test_add_success(self, handler):
        ok, msg = handler.handle("add", [
            "--anbieter", "TestVers", "--sparte", "Haftpflicht",
            "--beitrag", "12.50", "--zahlweise", "monatlich",
            "--police", "TEST-001"
        ])
        assert ok
        assert "TestVers" in msg
        assert "Haftpflicht" in msg
        # Verify in DB
        conn = sqlite3.connect(str(handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM fin_insurances WHERE police_nr = 'TEST-001'").fetchone()
        conn.close()
        assert row is not None
        assert row["anbieter"] == "TestVers"
        assert row["beitrag"] == 12.5
        assert row["status"] == "aktiv"

    def test_add_invalid_beitrag(self, handler):
        ok, msg = handler.handle("add", [
            "--anbieter", "Test", "--sparte", "KFZ", "--beitrag", "abc"
        ])
        assert not ok
        assert "Ungueltiger Beitrag" in msg

    def test_add_invalid_zahlweise(self, handler):
        ok, msg = handler.handle("add", [
            "--anbieter", "Test", "--sparte", "KFZ", "--zahlweise", "woechentlich"
        ])
        assert not ok
        assert "Ungueltige Zahlweise" in msg

    def test_add_with_dates(self, handler):
        ok, msg = handler.handle("add", [
            "--anbieter", "Test", "--sparte", "BU",
            "--beginn", "01.01.2025", "--ablauf", "31.12.2030",
            "--kuendigung", "01.10.2026"
        ])
        assert ok
        conn = sqlite3.connect(str(handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM fin_insurances WHERE anbieter = 'Test'").fetchone()
        conn.close()
        assert row["beginn_datum"] == "2025-01-01"
        assert row["ablauf_datum"] == "2030-12-31"
        assert row["naechste_kuendigung"] == "2026-10-01"

    def test_add_comma_beitrag(self, handler):
        ok, msg = handler.handle("add", [
            "--anbieter", "Test", "--sparte", "Hausrat", "--beitrag", "12,50"
        ])
        assert ok
        conn = sqlite3.connect(str(handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM fin_insurances WHERE anbieter = 'Test'").fetchone()
        conn.close()
        assert row["beitrag"] == 12.5

    def test_add_invalid_frist(self, handler):
        ok, msg = handler.handle("add", [
            "--anbieter", "Test", "--sparte", "KFZ", "--frist", "abc"
        ])
        assert not ok
        assert "Kuendigungsfrist" in msg

    def test_add_duplicate_police(self, pop_handler):
        ok, msg = pop_handler.handle("add", [
            "--anbieter", "Neue", "--sparte", "KFZ", "--police", "HP-001"
        ])
        assert not ok
        assert "existiert bereits" in msg


# ======================================================================
# EDIT
# ======================================================================
class TestEdit:
    def test_edit_no_id(self, handler):
        ok, msg = handler.handle("edit", [])
        assert not ok
        assert "Usage" in msg

    def test_edit_nonexistent(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["999", "--beitrag", "50"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_edit_no_changes(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1"])
        assert not ok
        assert "Keine Aenderungen" in msg

    def test_edit_beitrag(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1", "--beitrag", "7.90"])
        assert ok
        assert "aktualisiert" in msg
        conn = sqlite3.connect(str(pop_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT beitrag FROM fin_insurances WHERE id = 1").fetchone()
        conn.close()
        assert row["beitrag"] == 7.9

    def test_edit_status(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1", "--status", "beitragsfrei"])
        assert ok
        conn = sqlite3.connect(str(pop_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM fin_insurances WHERE id = 1").fetchone()
        conn.close()
        assert row["status"] == "beitragsfrei"

    def test_edit_invalid_status(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1", "--status", "ungueltig"])
        assert not ok
        assert "Ungueltiger Status" in msg

    def test_edit_invalid_zahlweise(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1", "--zahlweise", "woechentlich"])
        assert not ok
        assert "Ungueltige Zahlweise" in msg

    def test_edit_invalid_beitrag(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1", "--beitrag", "abc"])
        assert not ok
        assert "Ungueltiger Beitrag" in msg

    def test_edit_invalid_date(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1", "--beginn", "not-a-date"])
        assert not ok
        assert "Ungueltiges Datum" in msg

    def test_edit_invalid_frist(self, pop_handler):
        ok, msg = pop_handler.handle("edit", ["1", "--frist", "abc"])
        assert not ok
        assert "Ungueltige Frist" in msg

    def test_edit_note_appends(self, pop_handler):
        pop_handler.handle("edit", ["2", "--note", "Erster Nachtrag"])
        ok, msg = pop_handler.handle("edit", ["2", "--note", "Zweiter Nachtrag"])
        assert ok
        conn = sqlite3.connect(str(pop_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT notizen FROM fin_insurances WHERE id = 2").fetchone()
        conn.close()
        assert "Erster Nachtrag" in row["notizen"]
        assert "Zweiter Nachtrag" in row["notizen"]

    def test_edit_multiple_fields(self, pop_handler):
        ok, msg = pop_handler.handle("edit", [
            "1", "--beitrag=10", "--zahlweise", "jaehrlich", "--tarif", "Premium"
        ])
        assert ok
        assert "beitrag" in msg
        assert "zahlweise" in msg
        assert "tarif_name" in msg


# ======================================================================
# DELETE
# ======================================================================
class TestDelete:
    def test_delete_no_id(self, handler):
        ok, msg = handler.handle("delete", [])
        assert not ok
        assert "Usage" in msg

    def test_delete_nonexistent(self, pop_handler):
        ok, msg = pop_handler.handle("delete", ["999"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_delete_success(self, pop_handler):
        ok, msg = pop_handler.handle("delete", ["1"])
        assert ok
        assert "gekuendigt" in msg
        conn = sqlite3.connect(str(pop_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM fin_insurances WHERE id = 1").fetchone()
        conn.close()
        assert row["status"] == "gekuendigt"

    def test_delete_already_cancelled(self, pop_handler):
        ok, msg = pop_handler.handle("delete", ["4"])
        assert ok
        assert "bereits gekuendigt" in msg


# ======================================================================
# STATUS
# ======================================================================
class TestStatus:
    def test_status_empty(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok
        assert "DASHBOARD" in msg
        assert "gesamt: 0" in msg

    def test_status_with_data(self, pop_handler):
        ok, msg = pop_handler.handle("status", [])
        assert ok
        assert "DASHBOARD" in msg
        assert "Aktiv:" in msg
        assert "3" in msg  # 3 aktiv
        assert "Gekuendigt:" in msg
        assert "Kosten monatlich" in msg

    def test_status_shows_sparten(self, pop_handler):
        ok, msg = pop_handler.handle("status", [])
        assert ok
        assert "SPARTE" in msg
        assert "KFZ" in msg

    def test_status_shows_steuer(self, pop_handler):
        ok, msg = pop_handler.handle("status", [])
        assert ok
        assert "STEUERLICHE" in msg
        assert "Basisvorsorge" in msg
        assert "Sonstige Vorsorge" in msg

    def test_status_shows_open_claims(self, pop_handler):
        ok, msg = pop_handler.handle("status", [])
        assert ok
        assert "Offene Schadenfaelle" in msg

    def test_status_shows_upcoming_fristen(self, pop_handler):
        ok, msg = pop_handler.handle("status", [])
        assert ok
        assert "Kuendigungsfristen" in msg


# ======================================================================
# FRISTEN
# ======================================================================
class TestFristen:
    def test_fristen_empty(self, handler):
        ok, msg = handler.handle("fristen", [])
        assert ok
        assert "Keine Versicherungen" in msg

    def test_fristen_with_data(self, pop_handler):
        ok, msg = pop_handler.handle("fristen", [])
        assert ok
        assert "KUENDIGUNGSFRISTEN" in msg
        # Allianz has future_30, AXA has past_10
        assert "Allianz" in msg or "AXA" in msg

    def test_fristen_past_deadline(self, pop_handler):
        ok, msg = pop_handler.handle("fristen", [])
        assert ok
        assert "ABGELAUFENE" in msg
        assert "AXA" in msg

    def test_fristen_custom_days(self, pop_handler):
        ok, msg = pop_handler.handle("fristen", ["--tage", "365"])
        assert ok
        assert "365 Tage" in msg

    def test_fristen_positional_days(self, pop_handler):
        ok, msg = pop_handler.handle("fristen", ["180"])
        assert ok
        assert "180 Tage" in msg

    def test_fristen_invalid_days(self, pop_handler):
        ok, msg = pop_handler.handle("fristen", ["--tage", "abc"])
        assert not ok
        assert "Ungueltiger Wert" in msg


# ======================================================================
# CHECK
# ======================================================================
class TestCheck:
    def test_check_empty(self, handler):
        ok, msg = handler.handle("check", [])
        assert ok
        assert "Keine aktiven" in msg

    def test_check_with_data(self, pop_handler):
        ok, msg = pop_handler.handle("check", [])
        assert ok
        assert "PORTFOLIO CHECK" in msg
        assert "Aktive Versicherungen" in msg
        assert "AUFTEILUNG" in msg
        assert "STEUERLICHE" in msg

    def test_check_warns_missing_insurance(self, pop_handler):
        # PKV is missing — should appear in warnings
        ok, msg = pop_handler.handle("check", [])
        assert ok
        assert "PKV" in msg

    def test_check_uses_insurance_types(self, pop_handler):
        ok, msg = pop_handler.handle("check", [])
        assert ok
        # Rechtsschutz is priority 3, not checked. But Hausrat (prio 2) is gekuendigt, not aktiv
        # So Hausrat should show as missing in insurance_types check
        assert "Hausrat" in msg

    def test_check_score(self, pop_handler):
        ok, msg = pop_handler.handle("check", [])
        assert ok
        assert "Portfolio-Score" in msg


# ======================================================================
# CLAIM
# ======================================================================
class TestClaim:
    def test_claim_no_args(self, handler):
        ok, msg = handler.handle("claim", [])
        assert not ok
        assert "Usage" in msg

    def test_claim_unknown_sub(self, handler):
        ok, msg = handler.handle("claim", ["unknown"])
        assert not ok
        assert "Unbekannte" in msg

    def test_claim_add_no_args(self, handler):
        ok, msg = handler.handle("claim", ["add"])
        assert not ok
        assert "Usage" in msg

    def test_claim_add_nonexistent_insurance(self, pop_handler):
        ok, msg = pop_handler.handle("claim", [
            "add", "999", "--datum", "01.01.2026", "--beschreibung", "Test"
        ])
        assert not ok
        assert "nicht gefunden" in msg

    def test_claim_add_missing_fields(self, pop_handler):
        ok, msg = pop_handler.handle("claim", ["add", "1"])
        assert not ok
        assert "Pflichtfelder" in msg

    def test_claim_add_invalid_date(self, pop_handler):
        ok, msg = pop_handler.handle("claim", [
            "add", "1", "--datum", "invalid", "--beschreibung", "Test"
        ])
        assert not ok
        assert "Ungueltiges Datum" in msg

    def test_claim_add_invalid_betrag(self, pop_handler):
        ok, msg = pop_handler.handle("claim", [
            "add", "1", "--datum", "01.01.2026", "--beschreibung", "Test", "--betrag", "abc"
        ])
        assert not ok
        assert "Ungueltiger Betrag" in msg

    def test_claim_add_success(self, pop_handler):
        ok, msg = pop_handler.handle("claim", [
            "add", "1", "--datum", "15.03.2026",
            "--beschreibung", "Wasserschaden", "--betrag=2000",
            "--aktenzeichen", "AZ-TEST-1"
        ])
        assert ok
        assert "Schadenfall" in msg
        assert "Allianz" in msg
        assert "Wasserschaden" in msg
        conn = sqlite3.connect(str(pop_handler.user_db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM fin_insurance_claims WHERE beschreibung = 'Wasserschaden'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["insurance_id"] == 1
        assert row["betrag_gefordert"] == 2000.0
        assert row["aktenzeichen_versicherung"] == "AZ-TEST-1"
        assert row["status"] == "offen"

    def test_claim_list_empty(self, handler):
        ok, msg = handler.handle("claim", ["list"])
        assert ok
        assert "Keine Schadenfaelle" in msg

    def test_claim_list_all(self, pop_handler):
        ok, msg = pop_handler.handle("claim", ["list"])
        assert ok
        assert "Parkrempler" in msg
        assert "Steinschlag" in msg
        assert "Offen: 1" in msg
        assert "Reguliert: 1" in msg

    def test_claim_list_filtered(self, pop_handler):
        ok, msg = pop_handler.handle("claim", ["list", "2"])
        assert ok
        assert "Parkrempler" in msg

    def test_claim_list_no_results_for_id(self, pop_handler):
        ok, msg = pop_handler.handle("claim", ["list", "1"])
        assert ok
        assert "Keine Schadenfaelle" in msg
