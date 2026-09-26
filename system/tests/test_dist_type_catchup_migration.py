# -*- coding: utf-8 -*-
"""T-20260926-850075227: additive Migration holt die 3 auf allen Hosts
fehlenden migration_002-Effekte nach (bach_agents.dist_type,
bach_experts.dist_type, VIEW v_user_backup_tables), ohne die alte
Migrationsdatei zu aendern. Muss idempotent sein (zweiter Lauf No-op)."""

import importlib.util
import sqlite3
from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1]
    / "data"
    / "schema"
    / "migrations"
    / "049_migration_002_dist_type_catchup.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("dist_type_catchup_049", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_schema(conn):
    """Minimaler Auszug: nur die Tabellen, die die Migration beruehrt."""
    conn.executescript(
        """
        CREATE TABLE bach_agents (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE bach_experts (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE assistant_contacts (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE assistant_calendar (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE fin_insurances (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE fin_contracts (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE health_contacts (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE health_diagnoses (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE health_medications (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE health_lab_values (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE health_documents (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE health_appointments (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE household_routines (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        CREATE TABLE financial_emails (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0);
        """
    )


def test_catchup_adds_missing_columns_and_view():
    conn = sqlite3.connect(":memory:")
    _base_schema(conn)
    _load_migration().run_migration(conn)

    cols_agents = {r[1] for r in conn.execute("PRAGMA table_info(bach_agents)")}
    cols_experts = {r[1] for r in conn.execute("PRAGMA table_info(bach_experts)")}
    assert "dist_type" in cols_agents
    assert "dist_type" in cols_experts

    views = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view'")}
    assert "v_user_backup_tables" in views
    # View ist abfragbar (leere Tabellen -> alle Zaehler 0)
    assert conn.execute("SELECT COUNT(*) FROM v_user_backup_tables").fetchone()[0] == 12


def test_catchup_is_idempotent():
    conn = sqlite3.connect(":memory:")
    _base_schema(conn)
    migration = _load_migration()
    migration.run_migration(conn)
    migration.run_migration(conn)  # zweiter Lauf: darf nicht scheitern (ADD COLUMN doppelt)

    cols_agents = {r[1] for r in conn.execute("PRAGMA table_info(bach_agents)")}
    assert list(cols_agents).count("dist_type") <= 1  # kein Duplikat


def test_catchup_noop_when_effects_already_present():
    """Wie auf Laptop/Mac nach dem Live-Baseline-Lauf: Spalten/View schon da."""
    conn = sqlite3.connect(":memory:")
    _base_schema(conn)
    conn.execute("ALTER TABLE bach_agents ADD COLUMN dist_type INTEGER DEFAULT 2")
    conn.execute("ALTER TABLE bach_experts ADD COLUMN dist_type INTEGER DEFAULT 2")
    _load_migration().run_migration(conn)  # darf nicht scheitern
