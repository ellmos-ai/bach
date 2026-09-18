# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit-Tests fuer BACH Kernel-Sicherheit: PRAGMA query_only & Single-Flight Lock."""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from core.db import Database
from core.network_lock import SingleFlightLock, SingleFlightLockError


class TestQueryOnlyProtection:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_file = tmp_path / "test_kernel.db"
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        db = Database(db_file, schema_dir)

        # Initialtabelle mit Schreibverbindung anlegen
        with db.connect() as conn:
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO items (name) VALUES ('Alpha'), ('Beta')")
        return db

    def test_readonly_select_allowed(self, test_db):
        with test_db.connect_readonly() as conn:
            rows = conn.execute("SELECT name FROM items ORDER BY id").fetchall()
            names = [r["name"] for r in rows]
            assert names == ["Alpha", "Beta"]

    def test_readonly_insert_rejected(self, test_db):
        with test_db.connect_readonly() as conn:
            with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
                conn.execute("INSERT INTO items (name) VALUES ('Gamma')")

    def test_readonly_update_rejected(self, test_db):
        with test_db.connect_readonly() as conn:
            with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
                conn.execute("UPDATE items SET name = 'Omega' WHERE id = 1")

    def test_readonly_delete_rejected(self, test_db):
        with test_db.connect_readonly() as conn:
            with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
                conn.execute("DELETE FROM items WHERE id = 1")

    def test_readonly_drop_table_rejected(self, test_db):
        with test_db.connect_readonly() as conn:
            with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
                conn.execute("DROP TABLE items")


class TestSingleFlightLock:
    def test_acquire_and_release(self, tmp_path):
        lock_file = tmp_path / "transfer-attempt.json"
        lock = SingleFlightLock(lock_file, ttl_seconds=60)

        assert not lock_file.exists()
        with lock:
            assert lock_file.exists()
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            assert data["purpose"] == "sqlite-transit-sync"
            assert "machine_token" in data
            assert data["pid"] > 0
        assert not lock_file.exists()

    def test_contention_rejected(self, tmp_path):
        lock_file = tmp_path / "transfer-attempt.json"
        lock1 = SingleFlightLock(lock_file, ttl_seconds=60)
        lock2 = SingleFlightLock(lock_file, ttl_seconds=60)

        with lock1:
            with pytest.raises(SingleFlightLockError, match="Konkurrierender Transfer aktiv"):
                lock2.acquire()

    def test_stale_lock_recovery(self, tmp_path):
        lock_file = tmp_path / "transfer-attempt.json"
        # Erstelle ein abgelaufenes Lock
        stale_data = {
            "machine_token": "other-host",
            "pid": 99999,
            "session_token": "old-token",
            "started_at": time.time() - 500,
            "expires_at": time.time() - 100,
            "purpose": "test",
        }
        lock_file.write_text(json.dumps(stale_data), encoding="utf-8")

        new_lock = SingleFlightLock(lock_file, ttl_seconds=60)
        # Sollte das abgelaufene Lock uebernehmen
        with new_lock:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            assert data["session_token"] == new_lock.session_token
        assert not lock_file.exists()
