#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests fuer UpdateHandler"""

import sys
import json
import sqlite3
import pytest
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

BACH_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACH_ROOT))

from hub.update import UpdateHandler


@pytest.fixture
def tmp_system(tmp_path):
    """Erstellt eine minimale BACH-Verzeichnisstruktur."""
    system_dir = tmp_path / "system"
    for d in ("hub", "core", "data", "skills", "data/migrations"):
        (system_dir / d).mkdir(parents=True, exist_ok=True)
    # version.json
    version_data = {
        "version": "3.3.0",
        "schema_version": 42,
        "updated_at": "2026-05-01T12:00:00",
        "migrations_applied": ["001_initial", "002_memory"],
        "last_verified": "2026-05-01T12:00:00",
        "verification_status": "ok",
    }
    (system_dir / "data" / "version.json").write_text(
        json.dumps(version_data, indent=4), encoding="utf-8"
    )
    # Minimale bach.db
    db_path = tmp_path / ".bach" / "bach.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT, value TEXT)")
    conn.commit()
    conn.close()
    return system_dir, db_path


@pytest.fixture
def handler(tmp_system):
    system_dir, db_path = tmp_system
    h = UpdateHandler(system_dir)
    h.db_path = db_path
    h.backups_dir = system_dir.parent / "backups" / "updates"
    return h


# ──────────────────────────────────────────────
# Basis
# ──────────────────────────────────────────────

class TestUpdateBasics:
    def test_profile_name(self, handler):
        assert handler.profile_name == "update"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert "check" in ops
        assert "status" in ops
        assert "apply" in ops
        assert "rollback" in ops
        assert "verify" in ops
        assert "migrations" in ops

    def test_handle_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert not ok
        assert "Unbekannte Operation" in msg


# ──────────────────────────────────────────────
# Version
# ──────────────────────────────────────────────

class TestVersionManagement:
    def test_load_version(self, handler):
        ver = handler._load_version()
        assert ver["version"] == "3.3.0"
        assert ver["schema_version"] == 42
        assert "001_initial" in ver["migrations_applied"]

    def test_load_version_missing_file(self, handler):
        handler.version_file.unlink()
        ver = handler._load_version()
        assert ver["version"] == "0.0.0"
        assert ver["schema_version"] == 0

    def test_save_version(self, handler):
        ver = handler._load_version()
        ver["version"] = "4.0.0"
        handler._save_version(ver)
        reloaded = handler._load_version()
        assert reloaded["version"] == "4.0.0"


# ──────────────────────────────────────────────
# Status
# ──────────────────────────────────────────────

class TestStatus:
    def test_status_output(self, handler):
        ok, msg = handler._status()
        assert ok
        assert "3.3.0" in msg
        assert "42" in msg
        assert "001_initial" in msg

    def test_status_via_handle(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok

    def test_status_default_operation(self, handler):
        ok, msg = handler.handle("", [])
        assert ok
        assert "VERSION" in msg.upper() or "3.3.0" in msg


# ──────────────────────────────────────────────
# Verify
# ──────────────────────────────────────────────

class TestVerify:
    def test_verify_all_ok(self, handler):
        ok, msg = handler._verify()
        assert "Handler" in msg or "handler" in msg.lower() or "OK" in msg

    def test_verify_missing_dir(self, handler, tmp_system):
        system_dir, _ = tmp_system
        (system_dir / "core").rmdir()
        ok, msg = handler._verify()
        assert not ok
        assert "core" in msg

    def test_verify_db_table_count(self, handler):
        ok, msg = handler._verify()
        assert "Tabellen" in msg or "tabellen" in msg.lower()

    def test_verify_missing_db(self, handler, tmp_path):
        handler.db_path = tmp_path / "nonexistent.db"
        ok, msg = handler._verify()
        assert not ok
        assert "bach.db" in msg.lower() or "fehlt" in msg.lower()

    def test_verify_updates_version_json(self, handler):
        handler._verify()
        ver = handler._load_version()
        assert ver["last_verified"] is not None


# ──────────────────────────────────────────────
# Migrations
# ──────────────────────────────────────────────

class TestMigrations:
    def test_list_migrations_empty(self, handler):
        ok, msg = handler._list_migrations()
        assert ok
        assert "Keine Migrationen" in msg or "angewandt" in msg.lower()

    def test_list_migrations_with_files(self, handler):
        mig_dir = handler.migrations_dir
        (mig_dir / "003_new_feature.sql").write_text("SELECT 1;", encoding="utf-8")
        ok, msg = handler._list_migrations()
        assert ok
        assert "003_new_feature" in msg
        assert "ausstehend" in msg

    def test_run_sql_migration(self, handler):
        mig_dir = handler.migrations_dir
        (mig_dir / "003_add_col.sql").write_text(
            "CREATE TABLE IF NOT EXISTS test_mig (id INTEGER PRIMARY KEY);",
            encoding="utf-8"
        )
        handler._run_sql_migration(mig_dir / "003_add_col.sql")
        conn = sqlite3.connect(str(handler.db_path))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "test_mig" in tables

    def test_run_migrations_none_pending(self, handler):
        ok, msg = handler._run_migrations()
        assert ok
        assert "Keine ausstehenden" in msg or "keine" in msg.lower()

    def test_run_migrations_applies_sql(self, handler):
        mig_dir = handler.migrations_dir
        (mig_dir / "003_test.sql").write_text(
            "CREATE TABLE IF NOT EXISTS mig_test_table (x TEXT);",
            encoding="utf-8"
        )
        ok, msg = handler._run_migrations()
        assert ok
        assert "003_test" in msg
        ver = handler._load_version()
        assert "003_test" in ver["migrations_applied"]

    def test_run_migrations_dry_run(self, handler):
        mig_dir = handler.migrations_dir
        (mig_dir / "004_dry.sql").write_text("SELECT 1;", encoding="utf-8")
        ok, msg = handler._run_migrations(dry_run=True)
        assert ok
        assert "DRY-RUN" in msg
        ver = handler._load_version()
        assert "004_dry" not in ver["migrations_applied"]

    def test_run_py_migration(self, handler):
        mig_dir = handler.migrations_dir
        py_content = 'def run_migration():\n    pass\n'
        (mig_dir / "005_py_test.py").write_text(py_content, encoding="utf-8")
        handler._run_py_migration(mig_dir / "005_py_test.py")

    def test_run_py_migration_no_entrypoint(self, handler):
        mig_dir = handler.migrations_dir
        (mig_dir / "006_bad.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Weder run_migration"):
            handler._run_py_migration(mig_dir / "006_bad.py")

    def test_migrations_via_handle_list(self, handler):
        ok, msg = handler.handle("migrations", [])
        assert ok

    def test_migrations_via_handle_run(self, handler):
        ok, msg = handler.handle("migrations", ["run"])
        assert ok


# ──────────────────────────────────────────────
# Backup
# ──────────────────────────────────────────────

class TestBackup:
    def test_create_pre_update_backup(self, handler):
        ok, msg = handler._create_pre_update_backup()
        assert ok
        assert "Backup erstellt" in msg
        zips = list(handler.backups_dir.glob("pre_update_*.zip"))
        assert len(zips) == 1

    def test_backup_contains_db(self, handler):
        handler._create_pre_update_backup()
        zips = list(handler.backups_dir.glob("*.zip"))
        with zipfile.ZipFile(zips[0], "r") as zf:
            assert "bach.db" in zf.namelist()

    def test_backup_contains_version(self, handler):
        handler._create_pre_update_backup()
        zips = list(handler.backups_dir.glob("*.zip"))
        with zipfile.ZipFile(zips[0], "r") as zf:
            assert "version.json" in zf.namelist()

    def test_backup_dir_created_with_parents(self, handler, tmp_path):
        handler.backups_dir = tmp_path / "deep" / "nested" / "backups"
        ok, msg = handler._create_pre_update_backup()
        assert ok
        assert handler.backups_dir.exists()


# ──────────────────────────────────────────────
# Rollback
# ──────────────────────────────────────────────

class TestRollback:
    def test_rollback_no_backups_dir(self, handler, tmp_path):
        handler.backups_dir = tmp_path / "nonexistent"
        ok, msg = handler._rollback([], dry_run=False)
        assert not ok
        assert "Kein Backup-Verzeichnis" in msg

    def test_rollback_no_backups_found(self, handler):
        handler.backups_dir.mkdir(parents=True, exist_ok=True)
        ok, msg = handler._rollback([], dry_run=False)
        assert not ok
        assert "Keine Backups" in msg

    def test_rollback_dry_run(self, handler):
        handler._create_pre_update_backup()
        ok, msg = handler._rollback([], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_rollback_restores_db(self, handler):
        handler._create_pre_update_backup()
        # Modify the DB after backup
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("INSERT INTO tasks (title) VALUES ('after_backup')")
        conn.commit()
        conn.close()
        ok, msg = handler._rollback([], dry_run=False)
        assert ok
        assert "wiederhergestellt" in msg
        # DB should be restored — the inserted row should be gone
        conn = sqlite3.connect(str(handler.db_path))
        rows = conn.execute("SELECT title FROM tasks").fetchall()
        conn.close()
        titles = [r[0] for r in rows]
        assert "after_backup" not in titles

    def test_rollback_creates_pre_rollback_backup(self, handler):
        handler._create_pre_update_backup()
        ok, msg = handler._rollback([], dry_run=False)
        assert ok
        pre_rollback = handler.db_path.with_suffix(".db.pre_rollback")
        assert pre_rollback.exists()


# ──────────────────────────────────────────────
# Git
# ──────────────────────────────────────────────

class TestGit:
    def test_is_git_repo_false(self, handler):
        assert not handler._is_git_repo()

    def test_get_git_root_none(self, handler):
        assert handler._get_git_root() is None

    def test_git_cmd_no_repo(self, handler):
        ok, msg = handler._git_cmd(["git", "status"])
        assert not ok
        assert "Kein Git" in msg

    def test_git_info_no_repo(self, handler):
        assert handler._git_info() is None


# ──────────────────────────────────────────────
# Apply (Dry-Run)
# ──────────────────────────────────────────────

class TestApply:
    def test_apply_dry_run(self, handler):
        ok, msg = handler._apply([], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg
        assert "Backup" in msg
        assert "Git pull" in msg or "Pull" in msg

    def test_apply_no_git(self, handler):
        ok, msg = handler._apply([], dry_run=False)
        assert ok
        assert "Kein Git" in msg or "Git-Repo" in msg.lower() or "Ueberspringe" in msg


# ──────────────────────────────────────────────
# Check
# ──────────────────────────────────────────────

class TestCheck:
    def test_check_no_git(self, handler):
        ok, msg = handler._check()
        assert ok
        assert "Kein Git" in msg or "kein Git" in msg.lower()


# ──────────────────────────────────────────────
# Cross-OS
# ──────────────────────────────────────────────

class TestCrossOS:
    def test_backups_dir_platform_aware(self, tmp_system):
        system_dir, db_path = tmp_system
        with patch("sys.platform", "darwin"):
            h = UpdateHandler(system_dir)
            h.db_path = db_path
            assert ".bach" in str(h.backups_dir) or "Local_DEV" not in str(h.backups_dir)

    def test_backups_dir_windows(self, tmp_system):
        system_dir, db_path = tmp_system
        with patch("sys.platform", "win32"):
            h = UpdateHandler(system_dir)
            h.db_path = db_path
            assert "Local_DEV" in str(h.backups_dir) or "BACKUPS" in str(h.backups_dir)
