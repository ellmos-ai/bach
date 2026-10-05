# SPDX-License-Identifier: MIT
"""Migrationstests für ContractCockpitHandler._migrate_legacy."""

import sqlite3
from pathlib import Path

import pytest

from hub.contract_cockpit import ContractCockpitHandler


LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS abo_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    anbieter TEXT,
    kategorie TEXT,
    betrag_monatlich REAL,
    zahlungsintervall TEXT,
    kuendigungslink TEXT,
    erkannt_am TEXT,
    bestaetigt INTEGER DEFAULT 0,
    aktiv INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS abo_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER,
    posten_id INTEGER,
    betrag REAL,
    datum TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS abo_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT,
    anbieter TEXT,
    kategorie TEXT,
    kuendigungslink TEXT,
    dist_type INTEGER DEFAULT 2,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fin_insurances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anbieter TEXT,
    tarif_name TEXT,
    police_nr TEXT,
    sparte TEXT,
    status TEXT,
    beginn_datum TEXT,
    ablauf_datum TEXT,
    kuendigungsfrist_monate INTEGER DEFAULT 1,
    verlaengerung_monate INTEGER DEFAULT 12,
    naechste_kuendigung TEXT,
    beitrag REAL,
    zahlweise TEXT,
    steuer_relevant_typ TEXT,
    ordner_pfad TEXT,
    notizen TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fin_insurance_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insurance_id INTEGER,
    schadensdatum TEXT,
    beschreibung TEXT,
    status TEXT DEFAULT 'offen',
    betrag_gefordert REAL,
    betrag_gezahlt REAL,
    aktenzeichen_versicherung TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fin_insurance_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    muster TEXT,
    typische_fragen TEXT,
    typical_cost_range TEXT,
    dist_type INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@pytest.fixture
def legacy_db_path(tmp_path):
    base = tmp_path / "bach" / "system"
    db_dir = base / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(LEGACY_SCHEMA)
    conn.commit()
    conn.close()
    return base, db_path


def test_migrate_abo_subscriptions(legacy_db_path):
    base, db_path = legacy_db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """INSERT INTO abo_subscriptions
           (name, anbieter, betrag_monatlich, zahlungsintervall,
            kuendigungslink, erkannt_am, bestaetigt, aktiv)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("Netflix", "Netflix Inc", 12.99, "monatlich",
         "https://cancel", "2024-01-01", 1, 1),
    )
    conn.commit()
    conn.close()

    handler = ContractCockpitHandler(base)
    stats = handler._migrate_legacy()

    assert stats["contracts_from_abo"] == 1
    assert stats["payments"] == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    contract = conn.execute(
        "SELECT * FROM contracts WHERE source_type='abo_subscriptions'"
    ).fetchone()
    assert contract is not None
    assert contract["type"] == "abo"
    assert contract["status"] == "aktiv"
    assert contract["name"] == "Netflix"
    payment = conn.execute(
        "SELECT * FROM contract_payments WHERE contract_id=?", (contract["id"],)
    ).fetchone()
    assert payment is not None
    assert payment["betrag"] == 12.99
    conn.close()


def test_migrate_insurances_and_claims(legacy_db_path):
    base, db_path = legacy_db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """INSERT INTO fin_insurances
           (anbieter, tarif_name, police_nr, sparte, status,
            beginn_datum, ablauf_datum, beitrag, zahlweise)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("Allianz", "Hausrat Premium", "HR-123", "Hausrat", "aktiv",
         "2023-03-01", "2026-03-01", 150.0, "jährlich"),
    )
    conn.execute(
        """INSERT INTO fin_insurance_claims
           (insurance_id, schadensdatum, beschreibung, status,
            betrag_gefordert, betrag_gezahlt, aktenzeichen_versicherung)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (1, "2024-06-15", "Wasserschaden", "offen", 5000.0, 0.0, "AZ-987"),
    )
    conn.commit()
    conn.close()

    handler = ContractCockpitHandler(base)
    stats = handler._migrate_legacy()

    assert stats["contracts_from_insurance"] == 1
    assert stats["payments"] == 1
    assert stats["claims"] == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    contract = conn.execute(
        "SELECT * FROM contracts WHERE source_type='fin_insurances'"
    ).fetchone()
    assert contract is not None
    assert contract["type"] == "versicherung"
    assert contract["anbieter"] == "Allianz"
    claim = conn.execute(
        "SELECT * FROM contract_claims WHERE contract_id=?", (contract["id"],)
    ).fetchone()
    assert claim is not None
    assert claim["betrag_gefordert"] == 5000.0
    conn.close()


def test_migrate_abo_payments(legacy_db_path):
    base, db_path = legacy_db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """INSERT INTO abo_subscriptions
           (name, anbieter, betrag_monatlich, zahlungsintervall,
            erkannt_am, bestaetigt, aktiv)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("Spotify", "Spotify AB", 9.99, "monatlich", "2024-02-01", 1, 1),
    )
    conn.execute(
        """INSERT INTO abo_payments
           (subscription_id, posten_id, betrag, datum)
           VALUES (?, ?, ?, ?)""",
        (1, 42, 9.99, "2024-03-01"),
    )
    conn.commit()
    conn.close()

    handler = ContractCockpitHandler(base)
    stats = handler._migrate_legacy()

    assert stats["contracts_from_abo"] == 1
    assert stats["payments"] == 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM contract_payments
           WHERE contract_id=(SELECT id FROM contracts
                             WHERE source_type='abo_subscriptions' AND source_id=1)"""
    ).fetchall()
    assert len(rows) == 2
    assert any(r["posten_id"] == 42 for r in rows)
    conn.close()


def test_migrate_patterns_and_types(legacy_db_path):
    base, db_path = legacy_db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """INSERT INTO abo_patterns
           (pattern, anbieter, kategorie, kuendigungslink, dist_type)
           VALUES (?, ?, ?, ?, ?)""",
        ("Netflix.*Standard", "Netflix", "Streaming", "https://netflix/cancel", 2),
    )
    conn.execute(
        """INSERT INTO fin_insurance_types
           (id, name, muster, typische_fragen, typical_cost_range, dist_type)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (100, "Gebäudeversicherung", "Hausrat.*", "Wie groß?", "150-300 EUR/Jahr", 1),
    )
    conn.commit()
    conn.close()

    handler = ContractCockpitHandler(base)
    stats = handler._migrate_legacy()

    assert stats["patterns"] == 2
    assert stats["types"] == 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    abo_pattern = conn.execute(
        "SELECT * FROM contract_patterns WHERE pattern='Netflix.*Standard'"
    ).fetchone()
    assert abo_pattern is not None
    assert abo_pattern["anbieter"] == "Netflix"
    assert abo_pattern["applies_to"] == "abo"
    vers_pattern = conn.execute(
        "SELECT * FROM contract_patterns WHERE pattern='Hausrat.*'"
    ).fetchone()
    assert vers_pattern is not None
    assert vers_pattern["applies_to"] == "versicherung"
    conn.close()


def test_migrate_idempotent(legacy_db_path):
    base, db_path = legacy_db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """INSERT INTO abo_subscriptions
           (name, anbieter, betrag_monatlich, erkannt_am, bestaetigt, aktiv)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("Prime", "Amazon", 8.99, "2024-01-01", 1, 1),
    )
    conn.commit()
    conn.close()

    handler = ContractCockpitHandler(base)
    stats1 = handler._migrate_legacy()
    stats2 = handler._migrate_legacy()

    assert stats1["contracts_from_abo"] == 1
    assert stats2["contracts_from_abo"] == 0
