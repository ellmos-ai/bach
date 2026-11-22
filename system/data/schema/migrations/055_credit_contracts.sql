-- Migration 055: credit_contracts (Kredite) fuer das Ocean-Modul credits-core
-- Datum: 2026-11-22
-- Ticket: T-20260902-294356643 (Umschuldung, Kredit-Ueberblick und Vergleich)
-- Beschreibung: Legt die Tabelle an, auf der credits_core.CreditStore arbeitet.
--   DDL entspricht credits_core.SCHEMA_SQL; dist_type = 0 markiert Nutzerdaten
--   (gehen nie in Distributionen). Idempotent (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS credit_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    creditor TEXT NOT NULL,
    kind TEXT,
    reference TEXT,
    status TEXT,
    active INTEGER,
    start_date TEXT,
    principal REAL,
    monthly_payment REAL,
    term_months INTEGER,
    eff_rate_min REAL,
    eff_rate_max REAL,
    nominal_rate REAL,
    remaining_min REAL,
    remaining_max REAL,
    remaining_basis TEXT NOT NULL DEFAULT 'unknown',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dist_type INTEGER DEFAULT 0,
    UNIQUE (source, source_id)
);
