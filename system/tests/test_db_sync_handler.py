#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer DBSyncManager und DBSyncHandler"""

import sys
import json
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timedelta

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.db_sync import DBSyncManager, DBSyncHandler


MINIMAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);
CREATE TABLE IF NOT EXISTS secrets (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    value TEXT NOT NULL
);
"""


@pytest.fixture
def sync_env(tmp_path):
    db_dir = tmp_path / ".bach"
    db_dir.mkdir()
    db_path = db_dir / "bach.db"

    conn = sqlite3.connect(str(db_path))
    conn.executescript(MINIMAL_SCHEMA)
    conn.execute("INSERT INTO memory_facts (category, key, value) VALUES ('system', 'test', 'value')")
    conn.commit()
    conn.close()

    transit_dir = tmp_path / "transit"
    transit_dir.mkdir()

    system_dir = tmp_path / "system"
    system_dir.mkdir()

    manager = DBSyncManager(db_path=db_path, transit_dir=transit_dir)
    manager.local_bach_dir = db_dir
    manager.base_path = system_dir

    handler = DBSyncHandler(system_dir)
    return manager, handler, db_path, transit_dir


# ================================================================
# STATIC HELPERS
# ================================================================

class TestExtractHost:
    def test_valid_filename(self):
        p = Path("bach_LAPTOP_2026-05-15T14-30-00.bachdb")
        assert DBSyncManager._extract_host(p) == "LAPTOP"

    def test_hostname_with_hyphens(self):
        p = Path("bach_my-pc-01_2026-01-01T00-00-00.bachdb")
        assert DBSyncManager._extract_host(p) == "my-pc-01"

    def test_invalid_format(self):
        p = Path("backup_2026.bachdb")
        assert DBSyncManager._extract_host(p) is None

    def test_no_timestamp(self):
        p = Path("bach_HOST.bachdb")
        assert DBSyncManager._extract_host(p) is None


# ================================================================
# BACKUP GUARD
# ================================================================

class TestBackupGuard:
    def test_no_backup_today(self, sync_env):
        m, _, _, _ = sync_env
        assert m._has_backup_today() is False

    def test_backup_today_detected(self, sync_env):
        m, _, _, transit = sync_env
        today = datetime.now().strftime("%Y-%m-%d")
        fake = transit / f"bach_{m.hostname}_{today}T10-00-00.bachdb"
        fake.write_text("dummy")
        assert m._has_backup_today() is True

    def test_create_backup_if_needed_first_time(self, sync_env):
        m, _, _, _ = sync_env
        result = m.create_backup_if_needed()
        assert result is not None
        assert result.exists()
        assert m.hostname in result.name

    def test_create_backup_if_needed_skips_duplicate(self, sync_env):
        m, _, _, _ = sync_env
        first = m.create_backup_if_needed()
        assert first is not None
        second = m.create_backup_if_needed()
        assert second is None

    def test_retention_days_default(self, sync_env):
        m, _, _, _ = sync_env
        assert m._get_retention_days() == 7

    def test_retention_days_from_config(self, sync_env):
        m, _, db, _ = sync_env
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO system_config (key, value) VALUES ('backup_retention_days', '14')")
        conn.commit()
        conn.close()
        assert m._get_retention_days() == 14


# ================================================================
# CREATE BACKUP
# ================================================================

class TestCreateBackup:
    def test_creates_file(self, sync_env):
        m, _, _, transit = sync_env
        path = m.create_backup()
        assert path.exists()
        assert path.suffix == ".bachdb"
        assert path.parent == transit

    def test_backup_contains_data(self, sync_env):
        m, _, _, _ = sync_env
        path = m.create_backup()
        conn = sqlite3.connect(str(path))
        count = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
        conn.close()
        assert count >= 1

    def test_backup_secrets_stripped(self, sync_env):
        m, _, db, _ = sync_env
        conn = sqlite3.connect(str(db))
        conn.execute("INSERT INTO secrets (key, value) VALUES ('api_key', 'secret123')")
        conn.commit()
        conn.close()

        path = m.create_backup()
        conn = sqlite3.connect(str(path))
        count = conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0]
        conn.close()
        assert count == 0

    def test_backup_db_not_found(self, sync_env):
        m, _, _, _ = sync_env
        m.db_path = Path("/nonexistent/bach.db")
        with pytest.raises(FileNotFoundError):
            m.create_backup()

    def test_backup_updates_heartbeat(self, sync_env):
        m, _, _, _ = sync_env
        m.create_backup()
        assert m.heartbeat_file.exists()
        data = json.loads(m.heartbeat_file.read_text(encoding='utf-8'))
        assert m.hostname in data


# ================================================================
# FIND NEWER BACKUPS
# ================================================================

class TestFindNewer:
    def test_no_backups(self, sync_env):
        m, _, _, _ = sync_env
        assert m.find_newer_backups() == []

    def test_own_backups_ignored(self, sync_env):
        m, _, _, transit = sync_env
        own = transit / f"bach_{m.hostname}_2026-05-15T10-00-00.bachdb"
        own.write_text("dummy")
        assert m.find_newer_backups() == []

    def test_foreign_backup_found(self, sync_env):
        m, _, _, transit = sync_env
        foreign = transit / "bach_OTHER-PC_2026-05-15T10-00-00.bachdb"
        foreign.write_text("dummy")
        result = m.find_newer_backups()
        assert len(result) == 1
        assert "OTHER-PC" in result[0].name

    def test_already_pulled_skipped(self, sync_env):
        m, _, _, transit = sync_env
        foreign = transit / "bach_OTHER-PC_2026-05-15T10-00-00.bachdb"
        foreign.write_text("dummy")

        state = {"last_pulled": {"OTHER-PC": foreign.stat().st_mtime + 1}}
        m._save_sync_state(state)

        assert m.find_newer_backups() == []


# ================================================================
# MERGE
# ================================================================

class TestMerge:
    def test_merge_newer_rows(self, sync_env):
        m, _, db, transit = sync_env

        remote_db = transit / "bach_OTHER_2026-05-15T10-00-00.bachdb"
        conn = sqlite3.connect(str(remote_db))
        conn.executescript(MINIMAL_SCHEMA)
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        conn.execute(
            "INSERT INTO memory_facts (category, key, value, updated_at) VALUES (?, ?, ?, ?)",
            ("project", "remote_key", "remote_val", future)
        )
        conn.commit()
        conn.close()

        stats = m.merge_backup(remote_db)
        assert "memory_facts" in stats
        assert stats["memory_facts"] >= 1

        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT value FROM memory_facts WHERE key = 'remote_key'").fetchone()
        conn.close()
        assert row[0] == "remote_val"

    def test_merge_no_local_db_copies(self, sync_env):
        m, _, db, transit = sync_env
        db.unlink()

        remote_db = transit / "bach_OTHER_2026-05-15T10-00-00.bachdb"
        conn = sqlite3.connect(str(remote_db))
        conn.executescript(MINIMAL_SCHEMA)
        conn.commit()
        conn.close()

        stats = m.merge_backup(remote_db)
        assert "_initial_copy" in stats
        assert db.exists()


# ================================================================
# CLEANUP
# ================================================================

class TestCleanup:
    def test_cleanup_removes_old(self, sync_env):
        m, _, _, transit = sync_env
        import os

        old = transit / "bach_HOST_2020-01-01T00-00-00.bachdb"
        old.write_text("old")
        old_time = (datetime.now() - timedelta(days=30)).timestamp()
        os.utime(str(old), (old_time, old_time))

        new = transit / "bach_HOST_2026-05-15T10-00-00.bachdb"
        new.write_text("new")

        deleted = m.cleanup_old_backups(keep_days=7, keep_per_host=1)
        assert deleted == 1
        assert not old.exists()
        assert new.exists()

    def test_cleanup_keeps_recent(self, sync_env):
        m, _, _, transit = sync_env
        recent = transit / "bach_HOST_2026-05-15T10-00-00.bachdb"
        recent.write_text("recent")
        deleted = m.cleanup_old_backups(keep_days=7, keep_per_host=10)
        assert deleted == 0
        assert recent.exists()


# ================================================================
# HEARTBEAT & CONFLICTS
# ================================================================

class TestHeartbeat:
    def test_update_heartbeat(self, sync_env):
        m, _, _, _ = sync_env
        m._update_heartbeat()
        assert m.heartbeat_file.exists()
        data = json.loads(m.heartbeat_file.read_text(encoding='utf-8'))
        assert m.hostname in data
        assert data[m.hostname]["active"] is True

    def test_no_conflicts_empty(self, sync_env):
        m, _, _, _ = sync_env
        assert m.check_conflicts() == []

    def test_conflict_detected(self, sync_env):
        m, _, _, _ = sync_env
        heartbeats = {
            "OTHER-PC": {
                "last_seen": datetime.now().isoformat(),
                "pid": 12345,
                "active": True
            }
        }
        m.heartbeat_file.write_text(json.dumps(heartbeats), encoding='utf-8')
        conflicts = m.check_conflicts()
        assert len(conflicts) == 1
        assert "OTHER-PC" in conflicts[0]

    def test_stale_heartbeat_ignored(self, sync_env):
        m, _, _, _ = sync_env
        old_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        heartbeats = {
            "OLD-PC": {
                "last_seen": old_time,
                "pid": 999,
                "active": True
            }
        }
        m.heartbeat_file.write_text(json.dumps(heartbeats), encoding='utf-8')
        assert m.check_conflicts() == []


# ================================================================
# SYNC ON START/EXIT
# ================================================================

class TestSyncEvents:
    def test_sync_on_start_no_backups(self, sync_env):
        m, _, _, _ = sync_env
        ok, msg = m.sync_on_start()
        assert ok is True
        assert "Keine neueren" in msg

    def test_sync_on_exit_creates_backup(self, sync_env):
        m, _, _, transit = sync_env
        ok, msg = m.sync_on_exit()
        assert ok is True
        assert "ProSync Push" in msg
        backups = list(transit.glob("bach_*.bachdb"))
        assert len(backups) >= 1

    def test_sync_on_exit_skips_duplicate(self, sync_env):
        m, _, _, _ = sync_env
        m.create_backup_if_needed()
        ok, msg = m.sync_on_exit()
        assert ok is True
        assert "Bereits heute" in msg


# ================================================================
# TABLE DISCOVERY
# ================================================================

class TestTableDiscovery:
    def test_finds_timestamped_tables(self, sync_env):
        m, _, db, _ = sync_env
        conn = sqlite3.connect(str(db))
        tables = m._discover_timestamped_tables(conn)
        conn.close()
        assert "memory_facts" in tables
        assert tables["memory_facts"] == "updated_at"

    def test_excludes_secrets(self, sync_env):
        m, _, db, _ = sync_env
        conn = sqlite3.connect(str(db))
        tables = m._discover_timestamped_tables(conn)
        conn.close()
        assert "secrets" not in tables


# ================================================================
# ENSURE LOCAL DB
# ================================================================

class TestEnsureLocalDB:
    def test_already_exists(self, sync_env):
        m, _, _, _ = sync_env
        assert m.ensure_local_db() is True

    def test_no_source_db(self, sync_env):
        m, _, db, _ = sync_env
        local = m.local_bach_dir / "bach.db"
        local.unlink(missing_ok=True)
        db.unlink(missing_ok=True)
        assert m.ensure_local_db() is False


# ================================================================
# DBSYNCHANDLER
# ================================================================

class TestDBSyncHandler:
    def test_profile_name(self, sync_env):
        _, h, _, _ = sync_env
        assert h.profile_name == "dbsync"

    def test_operations(self, sync_env):
        _, h, _, _ = sync_env
        ops = h.get_operations()
        assert "backup" in ops
        assert "sync" in ops
        assert "status" in ops
        assert "cleanup" in ops
        assert "enable" in ops
        assert "disable" in ops

    def test_unknown_operation(self, sync_env):
        _, h, _, _ = sync_env
        ok, msg = h.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_enable_disable(self, sync_env):
        _, h, _, _ = sync_env
        config_dir = h.base_path / "data" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        ok, msg = h.handle("enable", [])
        assert ok is True
        assert (config_dir / "db_sync_enabled").exists()

        ok, msg = h.handle("disable", [])
        assert ok is True
        assert not (config_dir / "db_sync_enabled").exists()


# ================================================================
# GET STATUS
# ================================================================

class TestGetStatus:
    def test_status_empty(self, sync_env):
        m, _, _, _ = sync_env
        status = m.get_status()
        assert "DB SYNC" in status
        assert "Lokale DB" in status

    def test_status_with_backups(self, sync_env):
        m, _, _, _ = sync_env
        m.create_backup()
        status = m.get_status()
        assert m.hostname in status


# ================================================================
# SYNC STATE
# ================================================================

class TestSyncState:
    def test_empty_state(self, sync_env):
        m, _, _, _ = sync_env
        state = m._load_sync_state()
        assert state == {}

    def test_save_load_state(self, sync_env):
        m, _, _, _ = sync_env
        m._save_sync_state({"last_pulled": {"OTHER": 12345.0}})
        state = m._load_sync_state()
        assert state["last_pulled"]["OTHER"] == 12345.0

    def test_corrupt_state_returns_empty(self, sync_env):
        m, _, _, _ = sync_env
        m._sync_state_file.write_text("NOT JSON", encoding='utf-8')
        state = m._load_sync_state()
        assert state == {}
