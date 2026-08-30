# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for AboHandler (hub/abo.py)."""

import json
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
    conn.execute("""
        CREATE TABLE scheduler_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            profile_name TEXT,
            description TEXT,
            job_type TEXT NOT NULL,
            schedule TEXT,
            command TEXT NOT NULL,
            script_path TEXT,
            arguments TEXT,
            is_active INTEGER DEFAULT 0,
            timeout_seconds INTEGER DEFAULT 300,
            retry_on_fail INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE scheduler_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            started_at TEXT,
            finished_at TEXT,
            duration_seconds REAL,
            result TEXT,
            output TEXT,
            error TEXT,
            triggered_by TEXT
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


class TestAboTrackerImport:
    @staticmethod
    def _payload():
        return {
            "schema": "abotracker-export-v1",
            "schema_version": 1,
            "exported_at": "2026-08-15T05:00:00Z",
            "providers": [
                {
                    "name": "StreamCo",
                    "cancellation_url": "https://example.test/cancel",
                    "last_payment_date": "2026-08-01",
                    "models": [
                        {
                            "name": "Premium",
                            "price_per_month": 12.5,
                            "billing_cycle": "monthly",
                            "status_level": 2,
                            "status_label": "confirmed",
                            "is_currently_paid": True,
                        }
                    ],
                }
            ],
        }

    def test_import_is_idempotent(self, abo_env, tmp_path):
        handler, _, db_path = abo_env
        source = tmp_path / "abos.json"
        source.write_text(json.dumps(self._payload()), encoding="utf-8")

        ok1, msg1 = handler.handle("import", [str(source)])
        ok2, msg2 = handler.handle("import", [str(source)])

        assert ok1 and ok2
        assert "1 neu" in msg1
        assert "1 aktualisiert" in msg2
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT * FROM abo_subscriptions").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM abo_subscriptions").fetchone()[0] == 1
        assert row[4] == 12.5
        assert row[8] == 1
        assert row[9] == 1
        conn.close()

    def test_dry_run_does_not_write(self, abo_env, tmp_path):
        handler, _, db_path = abo_env
        source = tmp_path / "abos.json"
        source.write_text(json.dumps(self._payload()), encoding="utf-8")

        ok, msg = handler.handle("import", [str(source)], dry_run=True)

        assert ok and "DRY-RUN" in msg
        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM abo_subscriptions").fetchone()[0] == 0
        conn.close()

    def test_wrong_schema_rejected(self, abo_env, tmp_path):
        handler, _, _ = abo_env
        source = tmp_path / "abos.json"
        source.write_text('{"schema":"wrong"}', encoding="utf-8")

        ok, msg = handler.handle("import", [str(source)])

        assert not ok
        assert "Falsches Schema" in msg

    def test_wrong_schema_version_rejected(self, abo_env, tmp_path):
        handler, _, _ = abo_env
        payload = self._payload()
        payload["schema_version"] = 2
        source = tmp_path / "abos.json"
        source.write_text(json.dumps(payload), encoding="utf-8")

        ok, msg = handler.handle("import", [str(source)])

        assert not ok
        assert "Falsche Schema-Version" in msg

    def test_schedule_import_upserts_active_job(self, abo_env, tmp_path):
        handler, _, db_path = abo_env
        source = tmp_path / "abos.json"
        source.write_text(json.dumps(self._payload()), encoding="utf-8")

        ok1, _ = handler.handle("schedule-import", [str(source), "--interval", "12h"])
        ok2, _ = handler.handle("schedule-import", [str(source), "--interval", "24h"])

        assert ok1 and ok2
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT schedule, arguments, is_active FROM scheduler_jobs "
            "WHERE name='alltag-import-abotracker'"
        ).fetchone()
        assert row[0] == "24h"
        assert row[1].startswith('abo import "')
        assert str(source.resolve()) in row[1]
        assert row[2] == 1
        assert conn.execute("SELECT COUNT(*) FROM scheduler_jobs").fetchone()[0] == 1
        conn.close()

    def test_scheduled_import_executes_with_space_in_path(
        self, abo_env, tmp_path, monkeypatch
    ):
        handler, _, db_path = abo_env
        source_dir = tmp_path / "Export mit Leerzeichen"
        source_dir.mkdir()
        source = source_dir / "abos.json"
        source.write_text(json.dumps(self._payload()), encoding="utf-8")
        handler.base_path = SYSTEM_ROOT
        monkeypatch.setenv("BACH_DB", str(db_path))

        ok, _ = handler.handle("schedule-import", [str(source), "--interval", "24h"])
        assert ok

        from gui.daemon_service import DaemonService

        service = DaemonService(db_path)
        service.load_jobs()
        result = service.run_job(next(iter(service.jobs)), triggered_by="test")

        assert result["success"] is True, result
        assert "AboTracker-Import: 1 neu" in result["output"]
        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM abo_subscriptions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM scheduler_runs").fetchone()[0] == 1
        conn.close()


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
