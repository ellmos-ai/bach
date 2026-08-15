#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests fuer HausLagerist Integration (INT02)

Testet: inventory_engine.py Kernlogik + haushalt.py Handler-Operationen
"""

import os
import sys
import sqlite3
import pytest
from pathlib import Path

# BACH system path
BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub._services.household.inventory_engine import (
    InventoryEngine,
    AMPEL_ROT, AMPEL_GELB, AMPEL_GRUEN, AMPEL_GRAU,
    DEFAULT_WARN_DAYS,
)
from hub.haushalt import HaushaltHandler

MIGRATION_SQL = BACH_ROOT / "data" / "schema" / "migrations" / "025_hauslagerist_integration.sql"


@pytest.fixture
def tmp_db(tmp_path):
    """Erstellt temporaere DB mit Schema fuer Tests."""
    db_path = tmp_path / "test_bach.db"
    conn = sqlite3.connect(str(db_path))

    # Basis-Schema: household_inventory (wie vor Migration)
    conn.execute("""
        CREATE TABLE household_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            quantity INTEGER DEFAULT 0,
            unit TEXT DEFAULT 'Stueck',
            min_quantity INTEGER DEFAULT 1,
            location TEXT,
            expiry_date DATE,
            last_restocked DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dist_type INTEGER DEFAULT 0
        )
    """)

    # system_config (fuer Lern-Daten)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()

    # Migration anwenden (nur ALTER TABLE + CREATE TABLE, nicht executescript wegen ALTER)
    # ALTER TABLE einzeln
    for col, typ in [
        ("pack_unit", "TEXT DEFAULT 'Packung'"),
        ("pack_size", "REAL DEFAULT 1"),
        ("brand", "TEXT"),
        ("barcode", "TEXT"),
        ("priority", "INTEGER DEFAULT 2"),
        ("pull_threshold", "REAL DEFAULT 1.0"),
        ("learning_alpha", "REAL DEFAULT 0.3"),
        ("preferred_supplier_id", "INTEGER"),
        ("archived", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE household_inventory ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits

    # CREATE TABLE Statements aus Migration
    conn.execute("""
        CREATE TABLE IF NOT EXISTS household_suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            supplier_type TEXT DEFAULT 'other',
            address TEXT, phone TEXT, email TEXT, website TEXT, notes TEXT,
            archived INTEGER DEFAULT 0,
            dist_type INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS household_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            order_type TEXT NOT NULL DEFAULT 'routine',
            start_date TEXT, end_date TEXT, target_date TEXT,
            quantity_value REAL NOT NULL,
            cycle_interval_days INTEGER,
            status TEXT DEFAULT 'active',
            fulfilled_date TEXT, reason TEXT,
            priority INTEGER DEFAULT 2, notes TEXT,
            dist_type INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (article_id) REFERENCES household_inventory(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS household_stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            amount REAL NOT NULL,
            stock_before REAL, stock_after REAL,
            supplier_id INTEGER, price_per_unit REAL, note TEXT,
            dist_type INTEGER DEFAULT 0,
            timestamp TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (article_id) REFERENCES household_inventory(id)
        )
    """)
    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def engine(tmp_db):
    return InventoryEngine(tmp_db)


@pytest.fixture
def seeded_db(tmp_db):
    """DB mit Testdaten: 3 Artikel, 2 Orders, Bestandsbuchungen."""
    conn = sqlite3.connect(str(tmp_db))

    # Artikel
    conn.execute("""
        INSERT INTO household_inventory (name, category, quantity, unit, min_quantity, pack_size, priority)
        VALUES ('Milch', 'Lebensmittel', 4, 'Liter', 2, 1, 2)
    """)
    conn.execute("""
        INSERT INTO household_inventory (name, category, quantity, unit, min_quantity, pack_size, priority)
        VALUES ('Toilettenpapier', 'Hygiene', 20, 'Rollen', 4, 10, 3)
    """)
    conn.execute("""
        INSERT INTO household_inventory (name, category, quantity, unit, min_quantity, pack_size, priority)
        VALUES ('Zahnpasta', 'Hygiene', 0, 'Tube', 1, 1, 2)
    """)

    # Orders
    conn.execute("""
        INSERT INTO household_orders (article_id, order_type, quantity_value, cycle_interval_days, reason)
        VALUES (1, 'routine', 6, 14, 'Basis-Bedarf')
    """)
    conn.execute("""
        INSERT INTO household_orders (article_id, order_type, quantity_value, cycle_interval_days, reason)
        VALUES (2, 'routine', 10, 30, 'Basis-Bedarf')
    """)

    conn.commit()
    conn.close()
    return tmp_db


# ================================================================
# STATISCHE BERECHNUNGEN
# ================================================================

class TestPullQuotient:
    def test_basic(self):
        assert InventoryEngine.calculate_pull_quotient(10, 20) == 0.5

    def test_equal(self):
        assert InventoryEngine.calculate_pull_quotient(10, 10) == 1.0

    def test_surplus(self):
        assert InventoryEngine.calculate_pull_quotient(20, 10) == 2.0

    def test_no_demand(self):
        assert InventoryEngine.calculate_pull_quotient(5, 0) == float("inf")

    def test_zero_stock(self):
        assert InventoryEngine.calculate_pull_quotient(0, 10) == 0.0


class TestUrgency:
    def test_high_urgency(self):
        # Q=0.5, prio=3 => D = (3/0.5) * (1-0.5) = 6 * 0.5 = 3.0
        assert InventoryEngine.calculate_urgency(3, 0.5) == 3.0

    def test_no_urgency_surplus(self):
        # Q=1.5 => 1-Q = -0.5 => max(0, -0.5) = 0 => D=0
        assert InventoryEngine.calculate_urgency(2, 1.5) == 0.0

    def test_no_urgency_no_demand(self):
        assert InventoryEngine.calculate_urgency(2, float("inf")) == 0.0

    def test_critical_empty(self):
        # Q=0.1, prio=3 => D = (3/0.1) * (1-0.1) = 30 * 0.9 = 27.0
        assert InventoryEngine.calculate_urgency(3, 0.1) == pytest.approx(27.0)

    def test_capped_at_10(self):
        # Q=20 => capped to 10 => 1-10 = -9 => max(0, -9) = 0
        assert InventoryEngine.calculate_urgency(2, 20) == 0.0


class TestNeedsPull:
    def test_needs_pull(self):
        assert InventoryEngine.needs_pull(0.5, 1.0) is True

    def test_no_pull_surplus(self):
        assert InventoryEngine.needs_pull(1.5, 1.0) is False

    def test_no_pull_inf(self):
        assert InventoryEngine.needs_pull(float("inf"), 1.0) is False

    def test_threshold_custom(self):
        assert InventoryEngine.needs_pull(0.8, 0.5) is False
        assert InventoryEngine.needs_pull(0.3, 0.5) is True


# ================================================================
# DEMAND CALCULATION
# ================================================================

class TestDemand:
    def test_routine_demand(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        daily, breakdown = engine.calculate_daily_demand(1)  # Milch: 6/14
        assert daily == pytest.approx(6.0 / 14.0, abs=0.01)
        assert len(breakdown) == 1
        assert breakdown[0][0] == "Basis-Bedarf"

    def test_no_orders(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        daily, breakdown = engine.calculate_daily_demand(3)  # Zahnpasta: keine Orders
        assert daily == 0.0
        assert len(breakdown) == 0


# ================================================================
# AMPEL
# ================================================================

class TestAmpel:
    def test_grau_no_demand(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        assert engine.get_ampel_status(3) == AMPEL_GRAU  # Zahnpasta: keine Order

    def test_gruen_enough(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        assert engine.get_ampel_status(2) == AMPEL_GRUEN  # TP: 20 Rollen, ~60 Tage

    def test_rot_empty(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        # Milch auf 0 setzen
        conn = sqlite3.connect(str(seeded_db))
        conn.execute("UPDATE household_inventory SET quantity = 0 WHERE id = 1")
        conn.commit()
        conn.close()
        assert engine.get_ampel_status(1) == AMPEL_ROT

    def test_gelb_low(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        # Milch auf 1 Liter setzen (< 7 Tage bei 6/14 = 0.43/Tag => ~2.3 Tage)
        conn = sqlite3.connect(str(seeded_db))
        conn.execute("UPDATE household_inventory SET quantity = 1 WHERE id = 1")
        conn.commit()
        conn.close()
        assert engine.get_ampel_status(1) == AMPEL_GELB

    def test_overview_sorted(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        overview = engine.get_ampel_overview()
        assert len(overview) == 3
        # GRUEN zuerst (sortiert nach urgency), GRAU am Ende
        ampel_order = [x["ampel"] for x in overview]
        assert AMPEL_GRAU in ampel_order


# ================================================================
# PULL-LISTE
# ================================================================

class TestPullList:
    def test_pull_list_milch(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        pull = engine.generate_pull_list(days_ahead=30)
        # Milch: 4 Liter, Bedarf ~12.9 in 30 Tagen => Q < 1 => Pull
        milch_items = [x for x in pull if x["name"] == "Milch"]
        assert len(milch_items) == 1
        assert milch_items[0]["packs_needed"] > 0

    def test_no_pull_surplus(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        pull = engine.generate_pull_list(days_ahead=30)
        # Toilettenpapier: 20 Rollen, Bedarf 10 in 30 Tagen => Q = 2 => kein Pull
        tp_items = [x for x in pull if x["name"] == "Toilettenpapier"]
        assert len(tp_items) == 0


# ================================================================
# BESTANDSBUCHUNG
# ================================================================

class TestStockMovements:
    def test_stock_in(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        result = engine.stock_in(1, 6.0, price=1.29)
        assert result["before"] == 4
        assert result["after"] == 10
        assert result["amount"] == 6.0

    def test_stock_out(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        result = engine.stock_out(1, 2.0)
        assert result["before"] == 4
        assert result["after"] == 2
        assert result["amount"] == 2.0

    def test_stock_out_floor_zero(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        result = engine.stock_out(1, 100.0)
        assert result["after"] == 0  # Nicht negativ

    def test_transaction_logged(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        engine.stock_in(1, 5.0)
        engine.stock_out(1, 2.0)

        conn = sqlite3.connect(str(seeded_db))
        conn.row_factory = sqlite3.Row
        txns = conn.execute(
            "SELECT * FROM household_stock_transactions WHERE article_id = 1 ORDER BY id"
        ).fetchall()
        conn.close()

        assert len(txns) == 2
        assert txns[0]["transaction_type"] == "purchase"
        assert txns[0]["amount"] == 5.0
        assert txns[1]["transaction_type"] == "consumption"
        assert txns[1]["amount"] == -2.0

    def test_invalid_article(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        with pytest.raises(ValueError):
            engine.stock_in(999, 5.0)


# ================================================================
# INTELLIGENCE: EXPONENTIELLES GLAETTEN
# ================================================================

class TestLearning:
    def test_first_measurement(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        result = engine.learn_consumption(1, 0.5)
        assert result["new_value"] == 0.5
        assert result["data_points"] == 1

    def test_smoothing(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        # Erster Wert
        engine.learn_consumption(1, 0.5)
        # Zweiter Wert: V_new = 0.3 * 0.8 + 0.7 * 0.5 = 0.24 + 0.35 = 0.59
        result = engine.learn_consumption(1, 0.8)
        assert result["new_value"] == pytest.approx(0.59, abs=0.01)
        assert result["data_points"] == 2

    def test_convergence(self, seeded_db):
        engine = InventoryEngine(seeded_db)
        # Wiederholte Messungen von 1.0 sollten gegen 1.0 konvergieren
        for _ in range(20):
            result = engine.learn_consumption(1, 1.0)
        assert result["new_value"] == pytest.approx(1.0, abs=0.05)


# ================================================================
# HANDLER-INTEGRATION
# ================================================================

class TestHandler:
    @pytest.fixture
    def handler(self, tmp_db):
        """HaushaltHandler mit temp-DB."""
        # Handler braucht base_path mit data/bach.db Struktur
        base = tmp_db.parent / "system"
        data_dir = base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # DB an erwarteten Ort kopieren
        import shutil
        target = data_dir / "bach.db"
        shutil.copy2(str(tmp_db), str(target))

        return HaushaltHandler(base)

    def test_add_item(self, handler):
        ok, txt = handler.handle("add-item", ["Milch", "--cat", "Lebensmittel", "--unit", "Liter"])
        assert ok
        assert "Milch" in txt

    def test_add_item_no_args(self, handler):
        ok, txt = handler.handle("add-item", [])
        assert not ok
        assert "Usage" in txt

    def test_operations_count(self, handler):
        ops = handler.get_operations()
        assert len(ops) == 24
        assert "financial-summary" in ops

    def test_help_contains_pull(self, handler):
        ok, txt = handler.handle("help", [])
        assert ok
        assert "pull-check" in txt
        assert "ampel" in txt
        assert "stock-in" in txt
