#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests fuer DailyOverview Service (INT05)

Testet: Dashboard-Aggregator Datensammlung + Formatierung
"""

import sys
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub._services.dashboard.daily_overview import DailyOverview

MIGRATION_025 = BACH_ROOT / "data" / "schema" / "migrations" / "025_hauslagerist_integration.sql"
MIGRATION_026 = BACH_ROOT / "data" / "schema" / "migrations" / "026_literatur_integration.sql"


@pytest.fixture
def tmp_db(tmp_path):
    """DB mit allen relevanten Tabellen."""
    db_path = tmp_path / "test_bach.db"
    conn = sqlite3.connect(str(db_path))

    # Routinen
    conn.execute("""
        CREATE TABLE household_routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT, frequency TEXT,
            interval_days INTEGER, next_due TEXT, is_active INTEGER DEFAULT 1
        )
    """)

    # Kalender (Produktions-Schema: start_datetime statt event_date/event_time)
    conn.execute("""
        CREATE TABLE assistant_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, start_datetime DATETIME, end_datetime DATETIME,
            event_type TEXT, status TEXT DEFAULT 'geplant'
        )
    """)

    # Einkaufsliste
    conn.execute("""
        CREATE TABLE household_shopping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, is_done INTEGER DEFAULT 0
        )
    """)

    # Inventar (Basis)
    conn.execute("""
        CREATE TABLE household_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT, quantity INTEGER DEFAULT 0,
            unit TEXT DEFAULT 'Stueck', min_quantity INTEGER DEFAULT 1,
            location TEXT, expiry_date DATE, last_restocked DATE, notes TEXT,
            created_at TIMESTAMP, updated_at TIMESTAMP, dist_type INTEGER DEFAULT 0,
            pack_unit TEXT DEFAULT 'Packung', pack_size REAL DEFAULT 1,
            brand TEXT, barcode TEXT, priority INTEGER DEFAULT 2,
            pull_threshold REAL DEFAULT 1.0, learning_alpha REAL DEFAULT 0.3,
            preferred_supplier_id INTEGER, archived INTEGER DEFAULT 0
        )
    """)

    # Inventar-Nebentabellen
    conn.execute("""
        CREATE TABLE household_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL, order_type TEXT DEFAULT 'routine',
            start_date TEXT, end_date TEXT, target_date TEXT,
            quantity_value REAL NOT NULL, cycle_interval_days INTEGER,
            status TEXT DEFAULT 'active', fulfilled_date TEXT, reason TEXT,
            priority INTEGER DEFAULT 2, notes TEXT, dist_type INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE household_stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL, transaction_type TEXT NOT NULL,
            amount REAL NOT NULL, stock_before REAL, stock_after REAL,
            supplier_id INTEGER, price_per_unit REAL, note TEXT,
            dist_type INTEGER DEFAULT 0, timestamp TEXT
        )
    """)
    conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT)")

    # Gesundheit
    conn.execute("""
        CREATE TABLE health_medications (
            id INTEGER PRIMARY KEY, name TEXT, dosage TEXT,
            schedule TEXT, status TEXT DEFAULT 'aktiv', diagnosis_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE health_appointments (
            id INTEGER PRIMARY KEY, title TEXT, appointment_date TEXT,
            appointment_type TEXT, doctor_id INTEGER, status TEXT DEFAULT 'geplant'
        )
    """)
    conn.execute("""
        CREATE TABLE health_contacts (
            id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER DEFAULT 1
        )
    """)

    # Literatur
    conn.executescript(MIGRATION_026.read_text(encoding="utf-8"))

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def svc(tmp_db):
    return DailyOverview(tmp_db)


@pytest.fixture
def seeded_db(tmp_db):
    """DB mit Testdaten."""
    conn = sqlite3.connect(str(tmp_db))
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Routinen
    conn.execute(
        "INSERT INTO household_routines (name, category, next_due, is_active) VALUES (?, ?, ?, 1)",
        ("Staubsaugen", "Haushalt", today_str + " 08:00:00")
    )
    conn.execute(
        "INSERT INTO household_routines (name, category, next_due, is_active) VALUES (?, ?, ?, 1)",
        ("Bad putzen", "Haushalt", today_str + " 10:00:00")
    )
    conn.execute(
        "INSERT INTO household_routines (name, category, next_due, is_active) VALUES (?, ?, ?, 0)",
        ("Inaktive Routine", "Test", today_str + " 10:00:00")
    )

    # Termine
    conn.execute(
        "INSERT INTO assistant_calendar (title, start_datetime, event_type) VALUES (?, ?, ?)",
        ("Zahnarzt", f"{today_str} 14:00:00", "termin")
    )

    # Einkauf
    conn.execute("INSERT INTO household_shopping (name, is_done) VALUES ('Milch', 0)")
    conn.execute("INSERT INTO household_shopping (name, is_done) VALUES ('Brot', 0)")
    conn.execute("INSERT INTO household_shopping (name, is_done) VALUES ('Erledigt', 1)")

    # Medikamente
    conn.execute(
        "INSERT INTO health_medications (name, dosage, schedule, status) VALUES (?, ?, ?, ?)",
        ("Ibuprofen", "400mg", "bei Bedarf", "aktiv")
    )

    # Literatur
    conn.execute(
        "INSERT INTO lit_sources (title, read_status) VALUES (?, ?)",
        ("Ungelesenes Paper", "unread")
    )
    conn.execute(
        "INSERT INTO lit_sources (title, read_status) VALUES (?, ?)",
        ("In Arbeit", "reading")
    )
    conn.execute(
        "INSERT INTO lit_sources (title, read_status) VALUES (?, ?)",
        ("Fertig gelesen", "read")
    )

    conn.commit()
    conn.close()
    return tmp_db


# ================================================================
# STRUKTURIERTE DATEN
# ================================================================

class TestOverviewStructure:
    def test_empty_db(self, svc):
        data = svc.get_overview()
        assert "date" in data
        assert "weekday" in data
        assert data["routines"]["count"] == 0
        assert data["calendar"]["count"] == 0
        assert data["shopping"]["count"] == 0
        assert data["health_meds"]["count"] == 0
        assert data["literatur"]["total"] == 0

    def test_routines(self, seeded_db):
        svc = DailyOverview(seeded_db)
        data = svc.get_overview()
        # 2 aktive faellige Routinen (inaktive nicht gezaehlt)
        assert data["routines"]["count"] == 2
        names = [r["name"] for r in data["routines"]["items"]]
        assert "Staubsaugen" in names
        assert "Bad putzen" in names
        assert "Inaktive Routine" not in names

    def test_calendar(self, seeded_db):
        svc = DailyOverview(seeded_db)
        data = svc.get_overview()
        assert data["calendar"]["count"] == 1
        assert data["calendar"]["items"][0]["title"] == "Zahnarzt"

    def test_shopping(self, seeded_db):
        svc = DailyOverview(seeded_db)
        data = svc.get_overview()
        assert data["shopping"]["count"] == 2  # nur offene

    def test_health_meds(self, seeded_db):
        svc = DailyOverview(seeded_db)
        data = svc.get_overview()
        assert data["health_meds"]["count"] == 1
        assert data["health_meds"]["items"][0]["name"] == "Ibuprofen"

    def test_literatur(self, seeded_db):
        svc = DailyOverview(seeded_db)
        data = svc.get_overview()
        assert data["literatur"]["total"] == 3
        assert data["literatur"]["unread"] == 1
        assert data["literatur"]["reading"] == 1

    def test_inventory_empty(self, svc):
        data = svc.get_overview()
        assert data["inventory"]["total"] == 0


# ================================================================
# FORMATIERUNG
# ================================================================

class TestFormatting:
    def test_format_empty(self, svc):
        txt = svc.format_today()
        assert "HEUTE:" in txt
        assert "Keine faelligen Routinen" in txt

    def test_format_with_data(self, seeded_db):
        svc = DailyOverview(seeded_db)
        txt = svc.format_today()
        assert "ROUTINEN (2)" in txt
        assert "Staubsaugen" in txt
        assert "TERMINE (1)" in txt
        assert "Zahnarzt" in txt
        assert "MEDIKAMENTE (1)" in txt
        assert "Ibuprofen" in txt
        assert "EINKAUFSLISTE: 2 Artikel" in txt
        assert "LITERATUR:" in txt
        assert "1 ungelesen" in txt
        assert "1 in Bearbeitung" in txt

    def test_format_actions(self, seeded_db):
        svc = DailyOverview(seeded_db)
        txt = svc.format_today()
        assert "bach routine done" in txt
        assert "bach haushalt shopping" in txt
