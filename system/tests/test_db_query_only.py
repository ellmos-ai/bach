# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Regressionstests: SQLite query_only Leseabsicherung & Single-Flight Network Lock
(T-20260917-318279373)
"""

from __future__ import annotations

import json
import os
import sqlite3
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.db import (
    Database,
    get_db_connection,
    get_readonly_db_connection,
)
from core.safe_db import SafeDB
from core.network_lock import (
    SingleFlightLock,
    SingleFlightLockError,
    get_lock_info,
    is_locked,
    force_break_lock,
    single_flight_lock,
)
from hub.cloud import CloudHandler
from hub.transit_sync_provider import ExternalTransitSyncEngine


# ==============================================================================
# SQLite query_only Regression Tests
# ==============================================================================

class TestDatabaseQueryOnly:
    @pytest.fixture
    def db_setup(self, tmp_path):
        db_file = tmp_path / "test.db"
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        (schema_dir / "schema.sql").write_text(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, val INTEGER);\n"
            "INSERT INTO items (name, val) VALUES ('alpha', 10), ('beta', 20);\n",
            encoding="utf-8",
        )
        db = Database(db_file, schema_dir)
        db.init_schema()
        return db

    def test_connect_readonly_executes_reads(self, db_setup):
        """Lesende Anfragen funktionieren unter connect(read_only=True) einwandfrei."""
        with db_setup.connect(read_only=True) as conn:
            rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
            assert len(rows) == 2
            assert rows[0]["name"] == "alpha"
            assert rows[1]["name"] == "beta"

    def test_connect_readonly_rejects_insert(self, db_setup):
        """INSERT unter connect(read_only=True) scheitert mit OperationalError."""
        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            with db_setup.connect(read_only=True) as conn:
                conn.execute("INSERT INTO items (name, val) VALUES ('gamma', 30)")

    def test_connect_readonly_rejects_update(self, db_setup):
        """UPDATE unter connect(read_only=True) scheitert mit OperationalError."""
        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            with db_setup.connect(read_only=True) as conn:
                conn.execute("UPDATE items SET val = 99 WHERE name = 'alpha'")

    def test_connect_readonly_rejects_delete(self, db_setup):
        """DELETE unter connect(read_only=True) scheitert mit OperationalError."""
        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            with db_setup.connect(read_only=True) as conn:
                conn.execute("DELETE FROM items WHERE name = 'alpha'")

    def test_connect_readonly_rejects_ddl(self, db_setup):
        """CREATE TABLE unter connect(read_only=True) scheitert mit OperationalError."""
        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            with db_setup.connect(read_only=True) as conn:
                conn.execute("CREATE TABLE evil (id INT)")

    def test_connect_readonly_convenience_method(self, db_setup):
        """connect_readonly Context Manager sperrt Schreibzugriffe."""
        with db_setup.connect_readonly() as conn:
            rows = conn.execute("SELECT count(*) FROM items").fetchone()
            assert rows[0] == 2

        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            with db_setup.connect_readonly() as conn:
                conn.execute("DELETE FROM items")

    def test_execute_read_and_scalar_read(self, db_setup):
        """execute_read und execute_scalar_read liefern korrekte Daten und sperren Writes."""
        items = db_setup.execute_read("SELECT name, val FROM items WHERE val > ?", (15,))
        assert items == [{"name": "beta", "val": 20}]

        count = db_setup.execute_scalar_read("SELECT COUNT(*) FROM items")
        assert count == 2

        one = db_setup.execute_one_read("SELECT name FROM items WHERE val = ?", (10,))
        assert one == {"name": "alpha"}

        with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
            db_setup.execute_read("INSERT INTO items (name, val) VALUES ('delta', 40)")

    def test_get_db_connection_readonly(self, db_setup):
        """get_db_connection mit read_only=True und get_readonly_db_connection weisen Writes ab."""
        conn = get_db_connection(db_setup.db_path, read_only=True)
        try:
            assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
                conn.execute("INSERT INTO items (name, val) VALUES ('err', 1)")
        finally:
            conn.close()

        ro_conn = get_readonly_db_connection(db_setup.db_path)
        try:
            assert ro_conn.execute("PRAGMA query_only").fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
                ro_conn.execute("DROP TABLE items")
        finally:
            ro_conn.close()

    def test_safe_db_select_query_only(self, db_setup):
        """SafeDB.select fuehrt PRAGMA query_only = ON und erlaubt saubere Lesezugriffe."""
        safe = SafeDB(db_setup.db_path)
        results = safe.select("items")
        assert len(results) == 2

        # Verify internal connection opened in read_only mode
        ro_conn = safe._connect(read_only=True)
        try:
            assert ro_conn.execute("PRAGMA query_only").fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError, match="attempt to write a readonly database"):
                ro_conn.execute("UPDATE items SET val = 0")
        finally:
            ro_conn.close()


# ==============================================================================
# Single-Flight Network Lock Regression Tests
# ==============================================================================

class TestSingleFlightLock:
    def test_atomic_acquire_and_release(self, tmp_path):
        """Single-Flight Lock erstellt transfer-attempt.json atomar und raeumt sie auf."""
        lock_dir = tmp_path / "transit"
        lock_file = lock_dir / "transfer-attempt.json"

        assert not is_locked(lock_dir)
        lock = SingleFlightLock(lock_dir, operation="test_sync")

        assert lock.acquire() is True
        assert lock.is_acquired is True
        assert lock_file.exists()
        assert is_locked(lock_dir)

        # Inspect lock file payload
        data = lock.read_lock_file()
        assert data is not None
        assert data["machine"] == socket.gethostname()
        assert data["pid"] == os.getpid()
        assert data["operation"] == "test_sync"
        assert "process_token" in data
        assert "expires_at" in data

        assert lock.release() is True
        assert lock.is_acquired is False
        assert not lock_file.exists()
        assert not is_locked(lock_dir)

    def test_parallel_conflict_raises_error(self, tmp_path):
        """Zweiter paralleler Lock-Versuch wird hart mit SingleFlightLockError abgewiesen."""
        lock_dir = tmp_path / "transit"

        lock1 = SingleFlightLock(lock_dir, operation="flight_1")
        assert lock1.acquire() is True

        lock2 = SingleFlightLock(lock_dir, operation="flight_2", timeout=0.0)
        with pytest.raises(SingleFlightLockError, match="Single-Flight Lock aktiv"):
            lock2.acquire()

        lock1.release()

        # Nach Release kann lock2 erwerben
        assert lock2.acquire() is True
        lock2.release()

    def test_context_manager_usage(self, tmp_path):
        """Context Manager gewaehrleistet automatische Freigabe."""
        lock_dir = tmp_path / "cloud_data"
        with single_flight_lock(lock_dir, operation="cloud_op") as lock:
            assert lock.is_acquired is True
            assert (lock_dir / "transfer-attempt.json").exists()

        assert not (lock_dir / "transfer-attempt.json").exists()

    def test_stale_lock_expired_ttl_reclaimed(self, tmp_path):
        """Abgelaufener Lock (TTL) wird automatisch erkannt und uebernommen."""
        lock_dir = tmp_path / "transit"
        lock_dir.mkdir()
        lock_file = lock_dir / "transfer-attempt.json"

        # Simuliere abgelaufenen Lock
        expired_time = (datetime.now() - timedelta(minutes=5)).isoformat()
        stale_payload = {
            "lock_id": "stale-id",
            "machine": "other-machine",
            "pid": 999999,
            "process_token": "other-machine:999999:stale-id",
            "operation": "old_op",
            "created_at": (datetime.now() - timedelta(minutes=10)).isoformat(),
            "expires_at": expired_time,
        }
        lock_file.write_text(json.dumps(stale_payload), encoding="utf-8")

        new_lock = SingleFlightLock(lock_dir, operation="fresh_op")
        assert new_lock.acquire() is True

        active_data = new_lock.read_lock_file()
        assert active_data["operation"] == "fresh_op"
        assert active_data["pid"] == os.getpid()
        new_lock.release()

    def test_stale_lock_dead_pid_reclaimed(self, tmp_path):
        """Lock auf demselben Host mit totem PID wird sicher abgeraeumt."""
        lock_dir = tmp_path / "transit"
        lock_dir.mkdir()
        lock_file = lock_dir / "transfer-attempt.json"

        # Finde einen freien/toten PID
        dead_pid = 4194300
        stale_payload = {
            "lock_id": "dead-id",
            "machine": socket.gethostname(),
            "pid": dead_pid,
            "process_token": f"{socket.gethostname()}:{dead_pid}:dead-id",
            "operation": "dead_worker",
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        }
        lock_file.write_text(json.dumps(stale_payload), encoding="utf-8")

        new_lock = SingleFlightLock(lock_dir, operation="reclaim_dead")
        assert new_lock.acquire() is True
        assert new_lock.read_lock_file()["operation"] == "reclaim_dead"
        new_lock.release()

    def test_force_break_lock(self, tmp_path):
        """force_break_lock loescht existierende Lockdatei."""
        lock_dir = tmp_path / "transit"
        lock = SingleFlightLock(lock_dir)
        lock.acquire()
        assert is_locked(lock_dir)

        assert force_break_lock(lock_dir) is True
        assert not is_locked(lock_dir)


# ==============================================================================
# Integration: CloudHandler & TransitSync Single-Flight Tests
# ==============================================================================

class TestCloudHandlerSingleFlight:
    @pytest.fixture
    def handler(self, tmp_path):
        return CloudHandler(tmp_path)

    def test_status_shows_lock_free_and_active(self, handler):
        """Status zeigt Single-Flight Lock als Frei und bei Belegung als AKTIV."""
        ok, out = handler.handle("status", [])
        assert ok is True
        assert "Single-Flight Lock: Frei" in out

        # Lock extern belegen
        lock = SingleFlightLock(handler.lock_dir, operation="manual_transfer")
        lock.acquire()
        try:
            ok, out = handler.handle("status", [])
            assert ok is True
            assert "Single-Flight Lock: AKTIV" in out
            assert f"PID: {os.getpid()}" in out

            # Test --json flag
            ok_json, json_out = handler.handle("status", ["--json"])
            assert ok_json is True
            data = json.loads(json_out)
            assert data["single_flight_lock"]["operation"] == "manual_transfer"
        finally:
            lock.release()

    def test_lock_status_operation(self, handler):
        """Operation lock-status liefert Details bzw. meldet freien Zustand."""
        ok, out = handler.handle("lock-status", [])
        assert ok is True
        assert "frei" in out

        with SingleFlightLock(handler.lock_dir, operation="background_push"):
            ok, out = handler.handle("lock-status", [])
            assert ok is True
            assert "AKTIV" in out
            assert "background_push" in out

    def test_pause_blocked_when_parallel_flight_active(self, handler):
        """pause wird abgewiesen, wenn ein paralleler Single-Flight Lock aktiv ist."""
        with SingleFlightLock(handler.lock_dir, operation="active_transfer"):
            ok, out = handler.handle("pause", ["onedrive"])
            assert ok is False
            assert "Single-Flight Lock aktiv" in out

    def test_resume_blocked_when_parallel_flight_active(self, handler):
        """resume wird abgewiesen, wenn ein paralleler Single-Flight Lock aktiv ist."""
        with SingleFlightLock(handler.lock_dir, operation="active_transfer"):
            ok, out = handler.handle("resume", ["onedrive"])
            assert ok is False
            assert "Single-Flight Lock aktiv" in out

    def test_toggle_blocked_when_parallel_flight_active(self, handler):
        """toggle wird abgewiesen, wenn ein paralleler Single-Flight Lock aktiv ist."""
        with SingleFlightLock(handler.lock_dir, operation="active_transfer"):
            ok, out = handler.handle("toggle", ["onedrive"])
            assert ok is False
            assert "Single-Flight Lock aktiv" in out


class TestTransitSyncSingleFlight:
    def test_engine_push_and_sync_acquire_lock(self, tmp_path):
        """ExternalTransitSyncEngine push und sync sperren transit_dir ueber SingleFlightLock."""
        transit_dir = tmp_path / "transit"
        transit_dir.mkdir()

        mock_module = MagicMock()
        mock_config = MagicMock()
        mock_config.transit = transit_dir
        mock_config.node_id = "test-node"
        mock_config.namespace = "bach"

        mock_sync = MagicMock()
        mock_module.TransitSync.return_value = mock_sync

        mock_snapshot = MagicMock()
        mock_snapshot.path.name = "snapshot_001.snap"
        mock_sync.push.return_value = mock_snapshot

        mock_report = MagicMock()
        mock_report.inserted = 3
        mock_report.updated = 2
        mock_report.snapshot = "foreign_001.snap"
        mock_sync.pull.return_value = [mock_report]

        engine = ExternalTransitSyncEngine(mock_module, mock_config)

        # 1. Test push lock
        res = engine.push()
        assert res == "snapshot_001.snap"
        assert not is_locked(transit_dir)  # Lock was released cleanly

        # 2. Test sync lock
        ok, msg = engine.sync()
        assert ok is True
        assert "snapshot_001.snap" in msg
        assert not is_locked(transit_dir)

        # 3. Test that push fails if another flight is holding lock
        with SingleFlightLock(transit_dir, operation="competing_node"):
            with pytest.raises(SingleFlightLockError, match="Single-Flight Lock aktiv"):
                engine.push()
