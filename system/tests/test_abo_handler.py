# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for AboHandler (hub/abo.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.abo import AboHandler


@pytest.fixture
def abo_env(tmp_path, monkeypatch):
    """AboHandler with temporary DB."""
    base = tmp_path / "bach" / "system"
    data = base / "data"
    data.mkdir(parents=True)
    db_path = data / "bach.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE abo_subscriptions (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL, anbieter TEXT NOT NULL,
            kategorie TEXT, betrag_monatlich REAL,
            zahlungsintervall TEXT DEFAULT 'monatlich',
            kuendigungslink TEXT, erkannt_am TEXT,
            bestaetigt INTEGER DEFAULT 0, aktiv INTEGER DEFAULT 1,
            created_at TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE abo_payments (
            id INTEGER PRIMARY KEY,
            subscription_id INTEGER, posten_id INTEGER,
            betrag REAL, datum TEXT, created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE abo_patterns (
            id INTEGER PRIMARY KEY,
            pattern TEXT NOT NULL, anbieter TEXT NOT NULL,
            kategorie TEXT, kuendigungslink TEXT,
            dist_type INTEGER DEFAULT 2
        )
    """)
    conn.commit()
    conn.close()

    handler = AboHandler(base)
    monkeypatch.setattr(handler, "user_db", db_path)
    return handler, base, db_path


class TestAboBasic:
    def test_profile_name(self, abo_env):
        handler, _, _ = abo_env
        assert handler.profile_name == "abo"

    def test_operations(self, abo_env):
        handler, _, _ = abo_env
        ops = handler.get_operations()
        assert "scan" in ops
        assert "list" in ops
        assert "confirm" in ops
        assert "costs" in ops

    def test_help(self, abo_env):
        handler, _, _ = abo_env
        ok, msg = handler.handle("help", [])
        assert ok is True
        assert "ABOSERVICE" in msg

    def test_unknown_operation(self, abo_env):
        handler, _, _ = abo_env
        ok, msg = handler.handle("nope", [])
        assert ok is False
        assert "Unbekannte Operation" in msg


class TestAboInit:
    def test_init_dry_run(self, abo_env):
        handler, _, _ = abo_env
        ok, msg = handler.handle("init", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_init_creates_tables(self, abo_env):
        handler, base, db_path = abo_env
        # Tables already exist from fixture, init should still succeed
        ok, msg = handler.handle("init", [])
        assert ok is True
        assert "initialisiert" in msg


class TestAboList:
    def test_list_empty(self, abo_env):
        handler, _, _ = abo_env
        ok, msg = handler.handle("list", [])
        assert ok is True

    def test_list_with_entries(self, abo_env):
        handler, _, db_path = abo_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO abo_subscriptions (name, anbieter, kategorie, betrag_monatlich, aktiv) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Netflix Standard", "Netflix", "Streaming", 12.99, 1),
        )
        conn.execute(
            "INSERT INTO abo_subscriptions (name, anbieter, kategorie, betrag_monatlich, aktiv) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Spotify Family", "Spotify", "Musik", 14.99, 1),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "Netflix" in msg
        assert "Spotify" in msg


class TestAboCosts:
    def test_costs_empty(self, abo_env):
        handler, _, _ = abo_env
        ok, msg = handler.handle("costs", [])
        assert ok is True

    def test_costs_with_data(self, abo_env):
        handler, _, db_path = abo_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO abo_subscriptions (name, anbieter, kategorie, betrag_monatlich, aktiv) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Netflix", "Netflix", "Streaming", 12.99, 1),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("costs", [])
        assert ok is True
        assert "12" in msg or "Streaming" in msg


class TestAboConfirmDismiss:
    def test_confirm_existing(self, abo_env):
        handler, _, db_path = abo_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO abo_subscriptions (name, anbieter, bestaetigt) VALUES (?, ?, ?)",
            ("Test Abo", "TestProvider", 0),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("confirm", ["1"])
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT bestaetigt FROM abo_subscriptions WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 1

    def test_dismiss_existing(self, abo_env):
        handler, _, db_path = abo_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO abo_subscriptions (name, anbieter, aktiv) VALUES (?, ?, ?)",
            ("Dismissed", "Provider", 1),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("dismiss", ["1"])
        assert ok is True


class TestAboPatterns:
    def test_patterns_empty(self, abo_env):
        handler, _, _ = abo_env
        ok, msg = handler.handle("patterns", [])
        assert ok is True
