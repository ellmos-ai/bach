# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for BackupHandler (hub/backup.py)."""

import asyncio
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
        assert "status" in ops
        assert "list" in ops
        assert "info" in ops

    def test_context_injector_uses_real_user_restore_command(self, tmp_path):
        import sqlite3
        from pathlib import Path

        schema_dir = Path(__file__).resolve().parent.parent / "data" / "schema"
        db = tmp_path / "s.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE context_triggers (id INTEGER PRIMARY KEY, trigger_phrase TEXT,"
            " hint_text TEXT, source TEXT, agent_id TEXT DEFAULT 'default', is_active INTEGER DEFAULT 1,"
            " updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO context_triggers (trigger_phrase, hint_text, source) VALUES ("
            "'backup', 'Backup: bach backup create [--to-nas] | bach backup list | bach restore backup latest', 'manual')"
        )
        sql = (schema_dir / "migrations" / "045_context_triggers_sichtung.sql").read_text(encoding="utf-8")
        conn.executescript(sql)
        hint = conn.execute(
            "SELECT hint_text FROM context_triggers WHERE trigger_phrase='backup'"
        ).fetchone()[0]
        conn.close()
        assert "backup_manager.py restore backup latest" in hint
        assert "bach restore backup latest" not in hint


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
    def test_defaults_use_canonical_local_runtime_paths(self):
        from hub.bach_paths import BACH_DB, BACKUPS_DIR
        from tools import backup_manager

        assert backup_manager.DB_PATH == BACH_DB
        assert backup_manager.BACKUPS_DIR == BACKUPS_DIR / "userdata"

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

    def test_backup_zip_contains_consistent_db_outside_repo(self, tmp_path, monkeypatch):
        """T-20261122-100577457: Das Zip muss die DB enthalten, auch wenn sie
        ausserhalb des Repos liegt und ihre juengsten Zeilen noch im WAL stehen."""
        from tools import backup_manager

        db_path = tmp_path / "home" / ".bach" / "bach.db"
        db_path.parent.mkdir(parents=True)
        live = sqlite3.connect(str(db_path))  # bleibt offen: WAL nicht eingecheckt
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT)")
        live.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
        live.execute("CREATE TABLE only_in_full_db (x TEXT)")
        live.execute("INSERT INTO tasks (title) VALUES ('im-wal')")
        live.execute("INSERT INTO only_in_full_db VALUES ('steuer')")
        live.commit()

        monkeypatch.setattr(backup_manager, "DB_PATH", db_path)
        monkeypatch.setattr(backup_manager, "BACKUPS_DIR", tmp_path / "backups")
        monkeypatch.setattr(backup_manager, "SNAPSHOTS_DIR", tmp_path / "snap")
        monkeypatch.setattr(backup_manager, "MEMORY_DIR", tmp_path / "no_memory")
        monkeypatch.setattr(backup_manager, "LOGS_DIR", tmp_path / "no_logs")
        monkeypatch.setattr(backup_manager, "USER_DIR", tmp_path / "no_user")

        ok, zip_str = backup_manager.BackupManager().create_backup()
        live.close()

        assert ok, zip_str
        with zipfile.ZipFile(zip_str) as zf:
            assert "data/bach.db" in zf.namelist()
            zf.extract("data/bach.db", tmp_path / "restored")
        restored = sqlite3.connect(str(tmp_path / "restored" / "data" / "bach.db"))
        try:
            assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert restored.execute("SELECT title FROM tasks").fetchone()[0] == "im-wal"
            assert restored.execute("SELECT x FROM only_in_full_db").fetchone()[0] == "steuer"
        finally:
            restored.close()

    def test_headless_backup_uses_canonical_local_directory(self, tmp_path, monkeypatch):
        from gui.api import headless

        db_path = tmp_path / "bach.db"
        live = sqlite3.connect(str(db_path))  # offen: Zeile nur im WAL
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE t (x TEXT)")
        live.execute("INSERT INTO t VALUES ('im-wal')")
        live.commit()
        backup_root = tmp_path / "backups"

        monkeypatch.setattr(headless, "BACH_DB", str(db_path))
        monkeypatch.setattr(headless, "BACKUPS_DIR", backup_root)

        result = asyncio.run(headless.create_backup(None))
        live.close()

        backup_path = Path(result["backup"])
        assert backup_path.parent == backup_root / "api"
        copy = sqlite3.connect(str(backup_path))
        try:
            assert copy.execute("SELECT x FROM t").fetchone()[0] == "im-wal"
        finally:
            copy.close()

    def test_simple_backup_fallback_contains_wal_consistent_db(self, handler, backup_env):
        live = sqlite3.connect(str(backup_env / "data" / "bach.db"))
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE t (x TEXT)")
        live.execute("INSERT INTO t VALUES ('im-wal')")
        live.commit()
        with patch.object(handler, '_get_backup_manager', return_value=None):
            ok, _ = handler.handle("create", [], dry_run=False)
        live.close()
        assert ok is True
        zip_path = next(handler.backups_dir.glob("*.zip"))
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract("data/bach.db", backup_env / "x")
        copy = sqlite3.connect(str(backup_env / "x" / "data" / "bach.db"))
        try:
            assert copy.execute("SELECT x FROM t").fetchone()[0] == "im-wal"
        finally:
            copy.close()


def _make_db(path, title):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO tasks (title) VALUES (?)", (title,))
    conn.commit()
    conn.close()


def _titles(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT title FROM tasks")]
    finally:
        conn.close()


@pytest.fixture
def bm(tmp_path, monkeypatch):
    """BackupManager mit isolierten Pfaden; DB ausserhalb des Repos."""
    from tools import backup_manager

    db_path = tmp_path / "home" / ".bach" / "bach.db"
    _make_db(db_path, "alt")
    monkeypatch.setattr(backup_manager, "DB_PATH", db_path)
    monkeypatch.setattr(backup_manager, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup_manager, "SNAPSHOTS_DIR", tmp_path / "snap")
    monkeypatch.setattr(backup_manager, "BACH_DIR", tmp_path / "bach_dir")
    for n in ("MEMORY_DIR", "LOGS_DIR", "USER_DIR"):
        monkeypatch.setattr(backup_manager, n, tmp_path / ("no_" + n))
    return backup_manager.BackupManager(), db_path


class TestRestoreDbFile:
    def test_restore_replaces_db_and_keeps_safety_copy(self, bm):
        manager, db_path = bm
        ok, zip_str = manager.create_backup()
        assert ok
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO tasks (title) VALUES ('neu')")
        conn.commit()
        conn.close()
        # veraltete Sidecars der laufenden DB duerfen den Restore nicht verfaelschen
        db_path.with_name("bach.db-wal").write_bytes(b"stale")
        db_path.with_name("bach.db-shm").write_bytes(b"stale")

        ok, _ = manager.restore_backup(Path(zip_str).stem, force=True, auto_backup=False)

        assert ok
        assert _titles(db_path) == ["alt"]
        assert not db_path.with_name("bach.db-wal").exists()
        safety = list(db_path.parent.glob("bach.db.pre-restore-*.bak"))
        assert len(safety) == 1 and _titles(safety[0]) == ["alt", "neu"]
        assert not list(db_path.parent.glob(".restore_*"))

    def test_restore_corrupt_db_in_zip_is_fail_closed(self, bm, tmp_path):
        manager, db_path = bm
        bad = manager.backups_dir / "userdata_bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("data/bach.db", b"das ist keine sqlite datei" * 100)
            zf.writestr("memory/x.txt", "darf nicht geschrieben werden")

        ok, _ = manager.restore_backup("userdata_bad", force=True, auto_backup=False)

        assert not ok
        assert _titles(db_path) == ["alt"]
        assert not (tmp_path / "bach_dir" / "memory" / "x.txt").exists()
        assert not list(db_path.parent.glob(".restore_*"))
        assert not list(db_path.parent.glob("*.pre-restore-*"))

    def test_restore_legacy_json_only_zip_keeps_old_behaviour(self, bm, tmp_path):
        import json
        manager, db_path = bm
        legacy = manager.backups_dir / "userdata_legacy.zip"
        with zipfile.ZipFile(legacy, "w") as zf:
            zf.writestr("db_export.json", json.dumps(
                {"tasks": [{"id": 7, "title": "aus-json"}]}))

        ok, _ = manager.restore_backup("userdata_legacy", force=True, auto_backup=False)

        assert ok
        assert _titles(db_path) == ["aus-json"]  # bisheriges Verhalten: Tabelle ersetzt


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
