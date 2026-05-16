# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for HaushaltHandler (hub/haushalt.py)."""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.haushalt import HaushaltHandler


# ═══════════════════════════════════════════════════════════════
# SCHEMA HELPERS
# ═══════════════════════════════════════════════════════════════

SCHEMA_SQL = """
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS household_shopping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    category TEXT DEFAULT 'Sonstige',
    quantity TEXT,
    is_done INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fin_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kategorie TEXT,
    anbieter TEXT,
    betrag REAL,
    intervall TEXT,
    kuendigungs_status TEXT DEFAULT 'aktiv',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fin_insurances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anbieter TEXT NOT NULL,
    tarif_name TEXT,
    police_nr TEXT,
    sparte TEXT NOT NULL,
    status TEXT DEFAULT 'aktiv',
    beitrag REAL,
    zahlweise TEXT,
    steuer_relevant_typ TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS irregular_costs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    expected_month INTEGER,
    expected_amount REAL,
    is_recurring INTEGER DEFAULT 1,
    last_paid_date TEXT,
    last_paid_amount REAL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS household_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    quantity INTEGER DEFAULT 0,
    unit TEXT DEFAULT 'Stueck',
    min_quantity INTEGER DEFAULT 1,
    pack_size REAL DEFAULT 1,
    priority INTEGER DEFAULT 2,
    location TEXT,
    archived INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS household_suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    supplier_type TEXT DEFAULT 'other',
    address TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    archived INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS household_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'routine',
    start_date TEXT,
    end_date TEXT,
    target_date TEXT,
    quantity_value REAL NOT NULL,
    cycle_interval_days INTEGER,
    status TEXT DEFAULT 'active',
    reason TEXT,
    priority INTEGER DEFAULT 2,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (article_id) REFERENCES household_inventory(id)
);

CREATE TABLE IF NOT EXISTS household_stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    transaction_type TEXT NOT NULL,
    amount REAL NOT NULL,
    stock_before REAL,
    stock_after REAL,
    supplier_id INTEGER,
    price_per_unit REAL,
    note TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS health_medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dosage TEXT,
    schedule TEXT,
    status TEXT DEFAULT 'aktiv',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _create_db(db_path: Path):
    """Create empty DB with all required tables."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.close()


def _create_db_with_data(db_path: Path):
    """Create DB with sample data for testing."""
    _create_db(db_path)
    conn = sqlite3.connect(str(db_path))
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    next_week = (now + timedelta(days=5)).strftime("%Y-%m-%d")

    # Routines
    conn.executemany(
        "INSERT INTO household_routines (name, frequency, category, next_due, is_active) VALUES (?, ?, ?, ?, ?)",
        [
            ("Staubsaugen", "weekly", "Putzen", yesterday + " 10:00:00", 1),
            ("Muell rausbringen", "weekly", "Haushalt", today + " 08:00:00", 1),
            ("Wasche", "weekly", "Waschen", tomorrow + " 09:00:00", 1),
            ("Fenster putzen", "monthly", "Putzen", next_week + " 10:00:00", 1),
            ("Inaktive Routine", "daily", "Test", yesterday, 0),
        ],
    )

    # Contracts
    conn.executemany(
        "INSERT INTO fin_contracts (name, kategorie, betrag, intervall, kuendigungs_status) VALUES (?, ?, ?, ?, ?)",
        [
            ("Netflix", "Streaming", 12.99, "monatlich", "aktiv"),
            ("Vodafone", "Internet", 39.99, "monatlich", "aktiv"),
            ("ADAC", "Mobilitaet", 120.0, "jaehrlich", "aktiv"),
            ("Gekuendigt AG", "Test", 50.0, "monatlich", "gekuendigt"),
        ],
    )

    # Insurances
    conn.executemany(
        "INSERT INTO fin_insurances (anbieter, tarif_name, sparte, status, beitrag, zahlweise, steuer_relevant_typ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("HUK", "Komfort", "Haftpflicht", "aktiv", 120.0, "jaehrlich", "Sonstige_Vorsorge"),
            ("Allianz", "Standard", "Hausrat", "aktiv", 15.0, "monatlich", None),
            ("DKV", "Basis", "PKV", "aktiv", 400.0, "monatlich", "Basisvorsorge"),
        ],
    )

    # Irregular costs
    conn.executemany(
        "INSERT INTO irregular_costs (name, category, expected_month, expected_amount, is_recurring, last_paid_date) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("KFZ-Steuer", "Steuer", 3, 150.0, 1, "2025-03-15"),
            ("TÜV", "Auto", 6, 80.0, 1, None),
            ("Einmalkosten", "Sonstige", 1, 200.0, 0, None),
        ],
    )

    # Calendar events (production schema uses start_datetime DATETIME)
    conn.executemany(
        "INSERT INTO assistant_calendar (title, event_type, start_datetime, status) VALUES (?, ?, ?, ?)",
        [
            ("Zahnarzt", "termin", f"{today} 14:00:00", "geplant"),
            ("Meeting", "termin", f"{tomorrow} 10:00:00", "geplant"),
            ("Erledigter Termin", "termin", f"{today} 08:00:00", "erledigt"),
        ],
    )

    # Shopping
    conn.executemany(
        "INSERT INTO household_shopping (item_name, category, quantity, is_done) VALUES (?, ?, ?, ?)",
        [
            ("Milch", "Lebensmittel", "2L", 0),
            ("Brot", "Lebensmittel", None, 0),
            ("Shampoo", "Drogerie", "1", 1),
        ],
    )

    # Inventory
    conn.executemany(
        "INSERT INTO household_inventory (name, category, unit, quantity, min_quantity, pack_size, priority, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("Reis", "Lebensmittel", "kg", 5, 2, 1.0, 2, "Schrank"),
            ("Seife", "Hygiene", "Stueck", 0, 3, 1.0, 3, "Bad"),
        ],
    )

    # Suppliers
    conn.execute(
        "INSERT INTO household_suppliers (name, supplier_type, address) VALUES (?, ?, ?)",
        ("REWE", "supermarket", "Hauptstr. 1"),
    )

    # Medications
    conn.executemany(
        "INSERT INTO health_medications (name, dosage, schedule, status) VALUES (?, ?, ?, ?)",
        [
            ("Vitamin D", "1000 IE", "morgens", "aktiv"),
        ],
    )

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def hh_env(tmp_path):
    """Minimal environment for HaushaltHandler."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "data").mkdir()
    (system_dir / "hub").mkdir()
    db_path = tmp_path / ".bach" / "bach.db"
    db_path.parent.mkdir(parents=True)
    _create_db(db_path)
    return system_dir, db_path


@pytest.fixture
def handler(hh_env):
    """HaushaltHandler with empty DB."""
    system_dir, db_path = hh_env
    h = HaushaltHandler(system_dir)
    h.user_db_path = db_path
    return h


@pytest.fixture
def handler_data(hh_env):
    """HaushaltHandler with sample data."""
    system_dir, db_path = hh_env
    _create_db_with_data(db_path)
    h = HaushaltHandler(system_dir)
    h.user_db_path = db_path
    return h


# ═══════════════════════════════════════════════════════════════
# BASIC PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "haushalt"

    def test_target_file(self, handler):
        assert handler.target_file == handler.user_db_path

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        for key in ["status", "due", "today", "week", "costs", "shopping",
                     "inventory", "add-item", "stock-in", "stock-out",
                     "pull-check", "ampel", "order", "supplier", "add-supplier",
                     "kosten-monat", "add-kosten", "kosten-list",
                     "insurance-check", "help"]:
            assert key in ops, f"Missing operation: {key}"


class TestAppInit:
    def test_init_with_app_object(self, hh_env):
        system_dir, db_path = hh_env
        app = MagicMock()
        app.base_path = system_dir
        app.db = MagicMock()
        h = HaushaltHandler(app)
        assert h.base_path == system_dir


# ═══════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════


class TestRouting:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [], dry_run=False)
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_help(self, handler):
        ok, msg = handler.handle("help", [], dry_run=False)
        assert ok is True
        assert "HAUSHALT" in msg
        assert "Haushaltsmanagement" in msg

    def test_empty_op_shows_help(self, handler):
        ok, msg = handler.handle("", [], dry_run=False)
        assert ok is True
        assert "HAUSHALT" in msg

    def test_underscore_to_dash(self, handler):
        ok, msg = handler.handle("add_shopping", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg or "Artikelname" in msg


# ═══════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_empty_db(self, handler):
        ok, msg = handler.handle("status", [], dry_run=False)
        assert ok is True
        assert "HAUSHALTS-DASHBOARD" in msg
        assert "Routinen aktiv:" in msg

    def test_status_with_data(self, handler_data):
        ok, msg = handler_data.handle("status", [], dry_run=False)
        assert ok is True
        assert "HAUSHALTS-DASHBOARD" in msg
        assert "FIXKOSTEN" in msg
        assert "EUR" in msg

    def test_status_shows_overdue(self, handler_data):
        ok, msg = handler_data.handle("status", [], dry_run=False)
        assert ok is True
        assert "Staubsaugen" in msg or "UEBERFAELLIG" in msg


# ═══════════════════════════════════════════════════════════════
# DUE
# ═══════════════════════════════════════════════════════════════


class TestDue:
    def test_due_empty(self, handler):
        ok, msg = handler.handle("due", [], dry_run=False)
        assert ok is True
        assert "Keine faelligen" in msg

    def test_due_with_data(self, handler_data):
        ok, msg = handler_data.handle("due", [], dry_run=False)
        assert ok is True
        assert "Faellige Aufgaben" in msg
        assert "Staubsaugen" in msg

    def test_due_custom_days(self, handler_data):
        ok, msg = handler_data.handle("due", ["1"], dry_run=False)
        assert ok is True

    def test_due_shows_overdue_separately(self, handler_data):
        ok, msg = handler_data.handle("due", ["30"], dry_run=False)
        assert ok is True
        assert "UEBERFAELLIG" in msg


# ═══════════════════════════════════════════════════════════════
# WEEK
# ═══════════════════════════════════════════════════════════════


class TestWeek:
    def test_week_output(self, handler_data):
        ok, msg = handler_data.handle("week", [], dry_run=False)
        assert ok is True
        assert "WOCHENPLAN" in msg
        assert "HEUTE" in msg

    def test_week_empty_db(self, handler):
        ok, msg = handler.handle("week", [], dry_run=False)
        assert ok is True
        assert "WOCHENPLAN" in msg


# ═══════════════════════════════════════════════════════════════
# COSTS
# ═══════════════════════════════════════════════════════════════


class TestCosts:
    def test_costs_empty(self, handler):
        ok, msg = handler.handle("costs", [], dry_run=False)
        assert ok is True
        assert "FIXKOSTEN" in msg

    def test_costs_with_data(self, handler_data):
        ok, msg = handler_data.handle("costs", [], dry_run=False)
        assert ok is True
        assert "Netflix" in msg
        assert "Vodafone" in msg
        assert "Summe Vertraege" in msg
        assert "GESAMTE FIXKOSTEN" in msg

    def test_costs_excludes_cancelled(self, handler_data):
        ok, msg = handler_data.handle("costs", [], dry_run=False)
        assert "Gekuendigt AG" not in msg

    def test_costs_yearly_normalization(self, handler_data):
        ok, msg = handler_data.handle("costs", [], dry_run=False)
        assert ok is True
        assert "ADAC" in msg
        assert "10.00" in msg  # 120/12 = 10.00 EUR/Mo


# ═══════════════════════════════════════════════════════════════
# KOSTEN-MONAT / ADD-KOSTEN / KOSTEN-LIST
# ═══════════════════════════════════════════════════════════════


class TestKosten:
    def test_kosten_monat_empty(self, handler):
        ok, msg = handler.handle("kosten-monat", [], dry_run=False)
        assert ok is True
        assert "Keine erwarteten Kosten" in msg

    def test_kosten_monat_with_data(self, handler_data):
        ok, msg = handler_data.handle("kosten-monat", ["3"], dry_run=False)
        assert ok is True
        assert "KFZ-Steuer" in msg
        assert "150.00" in msg

    def test_kosten_monat_defaults_to_current(self, handler_data):
        ok, msg = handler_data.handle("kosten-monat", [], dry_run=False)
        assert ok is True

    def test_add_kosten_no_args(self, handler):
        ok, msg = handler.handle("add-kosten", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_add_kosten_success(self, handler):
        ok, msg = handler.handle(
            "add-kosten",
            ["Rundfunkbeitrag", "--monat", "1", "--betrag", "55.08", "--kategorie", "Abgaben"],
            dry_run=False,
        )
        assert ok is True
        assert "Rundfunkbeitrag" in msg

        conn = sqlite3.connect(str(handler.user_db_path))
        row = conn.execute("SELECT * FROM irregular_costs WHERE name = 'Rundfunkbeitrag'").fetchone()
        conn.close()
        assert row is not None

    def test_add_kosten_invalid_month(self, handler):
        ok, msg = handler.handle("add-kosten", ["Test", "--monat", "13"], dry_run=False)
        assert ok is False
        assert "Ungueltiger Monat" in msg

    def test_add_kosten_invalid_betrag(self, handler):
        ok, msg = handler.handle("add-kosten", ["Test", "--betrag", "abc"], dry_run=False)
        assert ok is False
        assert "Ungueltiger Betrag" in msg

    def test_add_kosten_einmalig(self, handler):
        ok, msg = handler.handle(
            "add-kosten", ["Einmal", "--einmalig", "--betrag", "100"],
            dry_run=False,
        )
        assert ok is True
        conn = sqlite3.connect(str(handler.user_db_path))
        row = conn.execute("SELECT is_recurring FROM irregular_costs WHERE name = 'Einmal'").fetchone()
        conn.close()
        assert row[0] == 0

    def test_kosten_list_empty(self, handler):
        ok, msg = handler.handle("kosten-list", [], dry_run=False)
        assert ok is True
        assert "Keine irregularen Kosten" in msg

    def test_kosten_list_with_data(self, handler_data):
        ok, msg = handler_data.handle("kosten-list", [], dry_run=False)
        assert ok is True
        assert "Kostenposition" in msg
        assert "KFZ-Steuer" in msg


# ═══════════════════════════════════════════════════════════════
# INSURANCE-CHECK
# ═══════════════════════════════════════════════════════════════


class TestInsuranceCheck:
    def test_no_insurances(self, handler):
        ok, msg = handler.handle("insurance-check", [], dry_run=False)
        assert ok is True
        assert "Keine aktiven Versicherungen" in msg

    def test_with_insurances(self, handler_data):
        ok, msg = handler_data.handle("insurance-check", [], dry_run=False)
        assert ok is True
        assert "VERSICHERUNGS-PORTFOLIO" in msg
        assert "Aktive Versicherungen: 3" in msg
        assert "AUFTEILUNG" in msg
        assert "STEUERLICHE ABSETZBARKEIT" in msg

    def test_insurance_score(self, handler_data):
        ok, msg = handler_data.handle("insurance-check", [], dry_run=False)
        assert "Portfolio-Score" in msg


# ═══════════════════════════════════════════════════════════════
# SHOPPING
# ═══════════════════════════════════════════════════════════════


class TestShopping:
    def test_shopping_empty(self, handler):
        ok, msg = handler.handle("shopping", [], dry_run=False)
        assert ok is True
        assert "leer" in msg

    def test_shopping_with_data(self, handler_data):
        ok, msg = handler_data.handle("shopping", [], dry_run=False)
        assert ok is True
        assert "Milch" in msg
        assert "Brot" in msg
        assert "Shampoo" not in msg  # is_done=1, filtered by default

    def test_shopping_all(self, handler_data):
        ok, msg = handler_data.handle("shopping", ["--all"], dry_run=False)
        assert ok is True
        assert "Shampoo" in msg

    def test_add_shopping_no_args(self, handler):
        ok, msg = handler.handle("add-shopping", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_add_shopping_success(self, handler):
        ok, msg = handler.handle(
            "add-shopping", ["Butter", "--cat", "Lebensmittel", "--qty", "250g"],
            dry_run=False,
        )
        assert ok is True
        assert "Butter" in msg

        conn = sqlite3.connect(str(handler.user_db_path))
        row = conn.execute("SELECT * FROM household_shopping WHERE item_name = 'Butter'").fetchone()
        conn.close()
        assert row is not None

    def test_done_shopping_no_args(self, handler):
        ok, msg = handler.handle("done-shopping", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_done_shopping_success(self, handler_data):
        ok, msg = handler_data.handle("done-shopping", ["1"], dry_run=False)
        assert ok is True
        assert "erledigt" in msg

        conn = sqlite3.connect(str(handler_data.user_db_path))
        row = conn.execute("SELECT is_done FROM household_shopping WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == 1

    def test_done_shopping_nonexistent(self, handler_data):
        ok, msg = handler_data.handle("done-shopping", ["999"], dry_run=False)
        assert ok is True
        assert "nicht gefunden" in msg


# ═══════════════════════════════════════════════════════════════
# ADD-ITEM (Inventory)
# ═══════════════════════════════════════════════════════════════


class TestAddItem:
    def test_no_args(self, handler):
        ok, msg = handler.handle("add-item", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_success(self, handler):
        ok, msg = handler.handle(
            "add-item",
            ["Mehl", "--cat", "Lebensmittel", "--unit", "kg", "--min", "2"],
            dry_run=False,
        )
        assert ok is True
        assert "Mehl" in msg

        conn = sqlite3.connect(str(handler.user_db_path))
        row = conn.execute("SELECT * FROM household_inventory WHERE name = 'Mehl'").fetchone()
        conn.close()
        assert row is not None

    def test_invalid_min(self, handler):
        ok, msg = handler.handle("add-item", ["Test", "--min", "abc"], dry_run=False)
        assert ok is False
        assert "Mindestbestand" in msg

    def test_invalid_priority(self, handler):
        ok, msg = handler.handle("add-item", ["Test", "--priority", "5"], dry_run=False)
        assert ok is False
        assert "1, 2 oder 3" in msg


# ═══════════════════════════════════════════════════════════════
# STOCK-IN / STOCK-OUT
# ═══════════════════════════════════════════════════════════════


class TestStock:
    def test_stock_in_no_args(self, handler):
        ok, msg = handler.handle("stock-in", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_stock_in_negative(self, handler):
        ok, msg = handler.handle("stock-in", ["1", "-5"], dry_run=False)
        assert ok is False
        assert "positiv" in msg

    def test_stock_out_no_args(self, handler):
        ok, msg = handler.handle("stock-out", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_stock_out_negative(self, handler):
        ok, msg = handler.handle("stock-out", ["1", "-3"], dry_run=False)
        assert ok is False
        assert "positiv" in msg

    def test_stock_in_invalid_price(self, handler):
        ok, msg = handler.handle("stock-in", ["1", "5", "--price", "abc"], dry_run=False)
        assert ok is False
        assert "Preis" in msg


# ═══════════════════════════════════════════════════════════════
# ORDER
# ═══════════════════════════════════════════════════════════════


class TestOrder:
    def test_order_no_args(self, handler):
        ok, msg = handler.handle("order", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_order_invalid_type(self, handler):
        ok, msg = handler.handle(
            "order", ["1", "--type", "invalid", "--qty", "5"],
            dry_run=False,
        )
        assert ok is False
        assert "Ungueltiger Order-Typ" in msg

    def test_order_routine_no_cycle(self, handler_data):
        ok, msg = handler_data.handle(
            "order", ["1", "--type", "routine", "--qty", "5"],
            dry_run=False,
        )
        assert ok is False
        assert "cycle" in msg.lower()

    def test_order_missing_qty(self, handler):
        ok, msg = handler.handle("order", ["1", "--type", "routine", "--cycle", "7"], dry_run=False)
        assert ok is False
        assert "Menge" in msg

    def test_order_nonexistent_article(self, handler):
        ok, msg = handler.handle(
            "order", ["999", "--qty", "5", "--cycle", "7"],
            dry_run=False,
        )
        assert ok is False
        assert "nicht gefunden" in msg

    def test_order_success(self, handler_data):
        ok, msg = handler_data.handle(
            "order", ["1", "--qty", "5", "--cycle", "14"],
            dry_run=False,
        )
        assert ok is True
        assert "Order" in msg
        assert "Reis" in msg

        conn = sqlite3.connect(str(handler_data.user_db_path))
        row = conn.execute("SELECT * FROM household_orders WHERE article_id = 1").fetchone()
        conn.close()
        assert row is not None


# ═══════════════════════════════════════════════════════════════
# SUPPLIER
# ═══════════════════════════════════════════════════════════════


class TestSupplier:
    def test_supplier_empty(self, handler):
        ok, msg = handler.handle("supplier", [], dry_run=False)
        assert ok is True
        assert "Keine Lieferanten" in msg

    def test_supplier_with_data(self, handler_data):
        ok, msg = handler_data.handle("supplier", [], dry_run=False)
        assert ok is True
        assert "REWE" in msg

    def test_add_supplier_no_args(self, handler):
        ok, msg = handler.handle("add-supplier", [], dry_run=False)
        assert ok is False
        assert "Usage" in msg

    def test_add_supplier_success(self, handler):
        ok, msg = handler.handle(
            "add-supplier", ["dm", "--type", "drugstore"],
            dry_run=False,
        )
        assert ok is True
        assert "dm" in msg

        conn = sqlite3.connect(str(handler.user_db_path))
        row = conn.execute("SELECT * FROM household_suppliers WHERE name = 'dm'").fetchone()
        conn.close()
        assert row is not None

    def test_add_supplier_duplicate(self, handler_data):
        ok, msg = handler_data.handle("add-supplier", ["REWE"], dry_run=False)
        assert ok is False
        assert "existiert bereits" in msg


# ═══════════════════════════════════════════════════════════════
# EXPORT-ROUTINE
# ═══════════════════════════════════════════════════════════════


class TestExportRoutine:
    def test_export_default(self, handler_data):
        ok, msg = handler_data.handle("export-routine", [], dry_run=False)
        assert ok is True
        assert "Tagesplan" in msg

    def test_export_multi_day(self, handler_data):
        ok, msg = handler_data.handle("export-routine", ["--days", "3"], dry_run=False)
        assert ok is True
        assert "Tagesplan" in msg

    def test_export_to_file(self, handler_data, tmp_path):
        out = str(tmp_path / "plan.md")
        ok, msg = handler_data.handle("export-routine", ["--out", out], dry_run=False)
        assert ok is True
        assert "exportiert" in msg
        assert Path(out).exists()
        content = Path(out).read_text(encoding="utf-8")
        assert "Tagesplan" in content

    def test_export_invalid_days(self, handler_data):
        ok, msg = handler_data.handle("export-routine", ["--days", "abc"], dry_run=False)
        assert ok is False
        assert "Ungueltiger Wert" in msg


# ═══════════════════════════════════════════════════════════════
# HELPER METHODS
# ═══════════════════════════════════════════════════════════════


class TestHelpers:
    def test_get_arg_flag_with_value(self, handler):
        result = handler._get_arg(["--cat", "Lebensmittel", "--qty", "2"], "--cat")
        assert result == "Lebensmittel"

    def test_get_arg_equals_syntax(self, handler):
        result = handler._get_arg(["--cat=Lebensmittel"], "--cat")
        assert result == "Lebensmittel"

    def test_get_arg_missing(self, handler):
        result = handler._get_arg(["--cat", "Lebensmittel"], "--qty")
        assert result is None

    def test_get_arg_flag_at_end(self, handler):
        result = handler._get_arg(["--cat"], "--cat")
        assert result is None

    def test_parse_ids(self, handler):
        ids, rest = handler._parse_ids(["1", "abc", "3", "--flag"])
        assert ids == [1, 3]
        assert rest == ["abc", "--flag"]

    def test_parse_ids_empty(self, handler):
        ids, rest = handler._parse_ids([])
        assert ids == []
        assert rest == []

    def test_ensure_shopping_table_idempotent(self, handler):
        conn = sqlite3.connect(str(handler.user_db_path))
        handler._ensure_shopping_table(conn)
        handler._ensure_shopping_table(conn)
        conn.close()

    def test_weekdays_constant(self, handler):
        assert len(handler.WEEKDAYS_DE) == 7
        assert handler.WEEKDAYS_DE[0] == "Mo"
        assert handler.WEEKDAYS_DE[6] == "So"
