"""Regression tests for the current-period financial summary contract."""

from __future__ import annotations

import json
import asyncio
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.financial.summary_service import (
    FinancialSummaryError,
    FinancialSummaryService,
)
from hub.haushalt import HaushaltHandler


SCHEMA = """
CREATE TABLE mail_accounts (
    id INTEGER PRIMARY KEY,
    is_active INTEGER DEFAULT 1
);
CREATE TABLE mail_sync_runs (
    id INTEGER PRIMARY KEY,
    finished_at TEXT,
    status TEXT,
    emails_matched INTEGER DEFAULT 0
);
CREATE TABLE financial_emails (
    id INTEGER PRIMARY KEY,
    email_date TEXT,
    category TEXT,
    document_type TEXT,
    betrag REAL,
    steuer_relevant INTEGER DEFAULT 0,
    status TEXT DEFAULT 'neu'
);
CREATE TABLE financial_subscriptions (
    id INTEGER PRIMARY KEY,
    provider_id TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    category TEXT NOT NULL,
    betrag_monatlich REAL,
    betrag_jaehrlich REAL,
    zahlungsintervall TEXT,
    naechste_zahlung TEXT,
    kuendigungslink TEXT,
    letzte_rechnung_id INTEGER,
    letzte_zahlung TEXT,
    zahlungen_count INTEGER DEFAULT 0,
    aktiv INTEGER DEFAULT 1,
    bestaetigt INTEGER DEFAULT 0,
    steuer_relevant INTEGER DEFAULT 0
);
CREATE TABLE financial_summary (
    id INTEGER PRIMARY KEY,
    jahr INTEGER NOT NULL,
    monat INTEGER,
    summen_kategorie TEXT,
    total_ausgaben REAL DEFAULT 0,
    total_steuer_relevant REAL DEFAULT 0,
    total_abos REAL DEFAULT 0,
    anzahl_rechnungen INTEGER DEFAULT 0,
    anzahl_abos INTEGER DEFAULT 0,
    berechnet_am TEXT,
    dist_type INTEGER DEFAULT 0
);
"""


@pytest.fixture
def summary_db(tmp_path):
    db_path = tmp_path / "summary.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.executemany(
        """
        INSERT INTO financial_emails
            (id, email_date, category, document_type, betrag,
             steuer_relevant, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "2026-08-01", "Energie", "rechnung", 10.0, 1, "verarbeitet"),
            (2, "2026-07-10", "Software", "rechnung", 20.0, 0, "neu"),
            (3, "2026-08-05", "Ignoriert", "rechnung", 99.0, 0, "ignoriert"),
            (4, "2025-12-05", "Alt", "rechnung", 50.0, 0, "verarbeitet"),
        ],
    )
    subscription = (
        "p1", "Provider 1", "Streaming", 5.0, None, "monatlich",
        None, None, 10, "2026-08-01", 3, 1, 1, 0,
    )
    conn.execute(
        """
        INSERT INTO financial_subscriptions
            (provider_id, provider_name, category, betrag_monatlich,
             betrag_jaehrlich, zahlungsintervall, naechste_zahlung,
             kuendigungslink, letzte_rechnung_id, letzte_zahlung,
             zahlungen_count, aktiv, bestaetigt, steuer_relevant)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        subscription,
    )
    conn.execute(
        """
        INSERT INTO financial_subscriptions
            (provider_id, provider_name, category, betrag_monatlich,
             betrag_jaehrlich, zahlungsintervall, naechste_zahlung,
             kuendigungslink, letzte_rechnung_id, letzte_zahlung,
             zahlungen_count, aktiv, bestaetigt, steuer_relevant)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*subscription[:10], 2, *subscription[11:]),
    )
    conn.execute(
        """
        INSERT INTO financial_subscriptions
            (provider_id, provider_name, category, betrag_monatlich,
             betrag_jaehrlich, zahlungsintervall, naechste_zahlung,
             kuendigungslink, letzte_rechnung_id, letzte_zahlung,
             zahlungen_count, aktiv, bestaetigt, steuer_relevant)
        VALUES ('p2', 'Provider 2', 'Cloud', NULL, 120, 'jaehrlich',
                NULL, NULL, NULL, NULL, 1, 1, 1, 0)
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_calculate_separates_observed_and_recurring_costs(summary_db):
    result = FinancialSummaryService(summary_db).calculate(today=date(2026, 8, 15))

    month, year = result["summaries"]
    assert month["jahr"] == 2026 and month["monat"] == 8
    assert month["total_ausgaben"] == 10.0
    assert month["total_steuer_relevant"] == 10.0
    assert month["total_abos"] == 15.0
    assert month["anzahl_rechnungen"] == 1
    assert month["anzahl_abos"] == 2
    assert json.loads(month["summen_kategorie"]) == {"Energie": 10.0}

    assert year["monat"] is None
    assert year["total_ausgaben"] == 30.0
    assert year["total_steuer_relevant"] == 10.0
    assert year["total_abos"] == 180.0
    assert year["anzahl_rechnungen"] == 2
    assert result["duplicate_subscription_rows"] == 1


def test_refresh_is_idempotent_and_does_not_delete_duplicates(summary_db):
    service = FinancialSummaryService(summary_db)
    service.refresh(today=date(2026, 8, 15))
    service.refresh(today=date(2026, 8, 15))

    conn = sqlite3.connect(summary_db)
    assert conn.execute("SELECT COUNT(*) FROM financial_summary").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM financial_subscriptions").fetchone()[0] == 3
    conn.close()


def test_dry_run_does_not_write(summary_db):
    FinancialSummaryService(summary_db).refresh(
        dry_run=True, today=date(2026, 8, 15)
    )

    conn = sqlite3.connect(summary_db)
    assert conn.execute("SELECT COUNT(*) FROM financial_summary").fetchone()[0] == 0
    conn.close()


def test_conflicting_duplicate_group_fails_closed(summary_db):
    conn = sqlite3.connect(summary_db)
    conn.execute(
        "UPDATE financial_subscriptions SET category='Konflikt' WHERE id=2"
    )
    conn.commit()
    conn.close()

    with pytest.raises(FinancialSummaryError, match="widersprüchliche"):
        FinancialSummaryService(summary_db).refresh(today=date(2026, 8, 15))

    conn = sqlite3.connect(summary_db)
    assert conn.execute("SELECT COUNT(*) FROM financial_summary").fetchone()[0] == 0
    conn.close()


def test_duplicate_summary_period_fails_closed(summary_db):
    conn = sqlite3.connect(summary_db)
    conn.executemany(
        "INSERT INTO financial_summary (jahr, monat) VALUES (2026, NULL)",
        [(), ()],
    )
    conn.commit()
    conn.close()

    with pytest.raises(FinancialSummaryError, match="mehrfach vorhanden"):
        FinancialSummaryService(summary_db).refresh(today=date(2026, 8, 15))


def test_haushalt_handler_refresh_and_show(summary_db):
    handler = HaushaltHandler(summary_db.parent)
    handler.user_db_path = summary_db

    ok_dry, dry_message = handler.handle(
        "financial-summary", ["refresh"], dry_run=True
    )
    ok_real, real_message = handler.handle("financial-summary", ["refresh"])
    ok_show, show_message = handler.handle("financial-summary", ["show"])

    assert ok_dry and "DRY-RUN" in dry_message
    assert ok_real and "historische Abo-Duplikate" in real_message
    assert ok_show and "FINANZZUSAMMENFASSUNG" in show_message
    assert "Beobachtete Ausgaben" in show_message


def test_fresh_financial_schema_prevents_trigger_duplicates(tmp_path):
    db_path = tmp_path / "fresh.db"
    schema_path = (
        SYSTEM_ROOT / "hub" / "_services" / "mail" / "schema_financial.sql"
    )
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    for index in range(1, 5):
        conn.execute(
            """
            INSERT INTO financial_emails
                (message_id, provider_id, provider_name, category,
                 sender, subject, email_date, betrag, status)
            VALUES (?, 'provider-1', 'Provider 1', 'Cloud',
                    'billing@example.test', 'Invoice', ?, 10, 'neu')
            """,
            (f"message-{index}", f"2026-0{index}-01"),
        )
    conn.commit()

    assert conn.execute(
        "SELECT COUNT(*) FROM financial_subscriptions WHERE provider_id='provider-1'"
    ).fetchone()[0] == 1
    conn.close()


def test_financial_api_deduplicates_legacy_subscriptions(summary_db, monkeypatch):
    import gui.server as server

    def get_test_db():
        conn = sqlite3.connect(summary_db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(server, "get_user_db", get_test_db)

    status = asyncio.run(server.financial_status())
    listing = asyncio.run(server.financial_subscriptions(active_only=True))

    assert status["active_subscriptions"] == 2
    assert status["monthly_subscription_cost"] == 15.0
    assert listing["count"] == 2
