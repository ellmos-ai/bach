# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for BackupHandler (hub/backup.py)."""

import sqlite3
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.backup import BackupHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def backup_env(tmp_path):
    """Minimal environment for BackupHandler."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

    for d in ("memory", "logs", "user"):
        sub = tmp_path / d
        sub.mkdir()
        (sub / "test.txt").write_text(f"content of {d}", encoding="utf-8")

    return tmp_path


@pytest.fixture
def handler(backup_env, tmp_path):
    h = BackupHandler(backup_env)
    h.backups_dir = tmp_path / "backups"
    h.backups_dir.mkdir()
    return h


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "backup"

    def test_operations_contain_create(self, handler):
        ops = handler.get_operations()
        assert "create" in ops
        assert "list" in ops
        assert "info" in ops


# ═══════════════════════════════════════════════════════════════
# HANDLE DISPATCH
# ═══════════════════════════════════════════════════════════════


class TestHandleDispatch:
    def test_default_operation_returns_list(self, handler):
        ok, output = handler.handle("", [], dry_run=False)
        assert ok is True

    def test_list_operation(self, handler):
        ok, output = handler.handle("list", [], dry_run=False)
        assert ok is True

    def test_create_dry_run(self, handler):
        ok, output = handler.handle("create", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output

    def test_info_without_args_falls_to_list(self, handler):
        ok, output = handler.handle("info", [], dry_run=False)
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# SIMPLE BACKUP (fallback without BackupManager)
# ═══════════════════════════════════════════════════════════════


class TestSimpleBackup:
    def test_creates_zip(self, handler, backup_env):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("create", [], dry_run=False)

        assert ok is True
        assert "OK" in output or "Backup" in output

        zips = list(handler.backups_dir.glob("*.zip"))
        assert len(zips) == 1

    def test_zip_contains_files(self, handler, backup_env):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            handler.handle("create", [], dry_run=False)

        zips = list(handler.backups_dir.glob("*.zip"))
        with zipfile.ZipFile(zips[0], 'r') as zf:
            names = zf.namelist()
            assert any("memory" in n for n in names)
            assert any("bach.db" in n for n in names)

    def test_backup_size_reported(self, handler, backup_env):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("create", [], dry_run=False)

        assert "MB" in output


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestListBackups:
    def test_empty_list(self, handler):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("list", [], dry_run=False)
        assert ok is True
        assert "Keine" in output or "BACKUPS" in output

    def test_list_after_create(self, handler, backup_env):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            handler.handle("create", [], dry_run=False)

        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("list", [], dry_run=False)
        assert ok is True
        assert "userdata_" in output

    def test_list_nonexistent_dir(self, handler, tmp_path):
        handler.backups_dir = tmp_path / "does_not_exist"
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("list", [], dry_run=False)
        assert ok is True
        assert "Keine" in output or "Backup" in output


# ═══════════════════════════════════════════════════════════════
# INFO
# ═══════════════════════════════════════════════════════════════


class TestBackupInfo:
    def test_info_existing(self, handler, backup_env):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            handler.handle("create", [], dry_run=False)

        zips = list(handler.backups_dir.glob("*.zip"))
        name = zips[0].stem

        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("info", [name], dry_run=False)
        assert ok is True
        assert "BACKUP INFO" in output
        assert "Dateien:" in output

    def test_info_not_found(self, handler):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("info", ["nonexistent_backup_xyz"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in output or "Backup" in output


# ═══════════════════════════════════════════════════════════════
# NAS FLAG
# ═══════════════════════════════════════════════════════════════


class TestNasFlag:
    def test_create_with_to_nas_flag(self, handler):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("create", ["--to-nas"], dry_run=False)
        assert ok is True

    def test_list_with_nas_flag(self, handler):
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, output = handler.handle("list", ["--nas"], dry_run=False)
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# WITH BACKUP MANAGER (mocked)
# ═══════════════════════════════════════════════════════════════


class TestWithBackupManager:
    def test_create_delegates_to_manager(self, handler):
        mock_mgr = MagicMock()
        mock_mgr.create_backup.return_value = (True, "[OK] Manager backup done")
        with patch.object(handler, '_get_backup_manager', return_value=mock_mgr):
            ok, output = handler.handle("create", [], dry_run=False)

        assert ok is True
        assert "Manager backup done" in output
        mock_mgr.create_backup.assert_called_once_with(to_nas=False)

    def test_list_delegates_to_manager(self, handler):
        mock_mgr = MagicMock()
        mock_mgr.list_backups.return_value = [
            {"name": "backup_20260101.zip", "path": "/tmp/b.zip", "size_mb": 5.0, "created_at": "2026-01-01T00:00"}
        ]
        with patch.object(handler, '_get_backup_manager', return_value=mock_mgr):
            ok, output = handler.handle("list", [], dry_run=False)

        assert ok is True
        assert "backup_20260101" in output

    def test_info_delegates_to_manager(self, handler):
        mock_mgr = MagicMock()
        mock_mgr.list_backups.return_value = [
            {"name": "mybackup.zip", "path": "/tmp/mybackup.zip", "size_mb": 3.5, "created_at": "2026-01-15", "contents": ["file1.txt", "file2.txt"]}
        ]
        with patch.object(handler, '_get_backup_manager', return_value=mock_mgr):
            ok, output = handler.handle("info", ["mybackup"], dry_run=False)

        assert ok is True
        assert "mybackup" in output


class TestBackupManager:
    def test_creates_missing_snapshot_parent(self, tmp_path, monkeypatch):
        from tools import backup_manager

        db_path = tmp_path / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(backup_manager, "DB_PATH", db_path)
        monkeypatch.setattr(backup_manager, "BACKUPS_DIR", tmp_path / "backups")
        monkeypatch.setattr(
            backup_manager,
            "SNAPSHOTS_DIR",
            tmp_path / "missing_dist" / "snapshots",
        )

        manager = backup_manager.BackupManager()

        assert manager.backups_dir.exists()
        assert manager.snapshots_dir.exists()


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import ast
        source_file = SYSTEM_ROOT / "hub" / "backup.py"
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                pytest.fail(f"Bare except at line {node.lineno} in backup.py")
