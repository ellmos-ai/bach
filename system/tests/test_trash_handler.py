# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for TrashHandler (hub/trash.py)."""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.trash import TrashHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def trash_env(tmp_path):
    """Minimal environment for TrashHandler with DB and trash dir."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    trash_dir = data_dir / "trash"
    trash_dir.mkdir()

    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files_trash (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_path TEXT,
            trash_path TEXT,
            size INTEGER,
            deleted_at TEXT,
            deleted_by TEXT DEFAULT 'claude',
            retention_days INTEGER DEFAULT 30,
            expires_at TEXT,
            status TEXT DEFAULT 'active',
            restored_at TEXT,
            purged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()
    return tmp_path


@pytest.fixture
def handler(trash_env):
    h = TrashHandler(trash_env)
    h.trash_dir = trash_env / "data" / "trash"
    return h


@pytest.fixture
def sample_file(trash_env):
    """Creates a sample file to be trashed."""
    f = trash_env / "testfile.txt"
    f.write_text("Hello, this is a test file.", encoding="utf-8")
    return f


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "trash"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "delete" in ops
        assert "restore" in ops
        assert "purge" in ops
        assert "info" in ops


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestListTrash:
    def test_empty_trash(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True
        assert "Leer" in output or "keine" in output.lower()

    def test_list_alias(self, handler):
        ok, output = handler.handle("ls", [])
        assert ok is True

    def test_default_shows_list(self, handler):
        ok, output = handler.handle("", [])
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# SOFT DELETE
# ═══════════════════════════════════════════════════════════════


class TestSoftDelete:
    def test_delete_existing_file(self, handler, sample_file):
        ok, output = handler.handle("delete", [str(sample_file)])
        assert ok is True
        assert "TRASH" in output
        assert not sample_file.exists()

    def test_delete_nonexistent(self, handler):
        ok, output = handler.handle("delete", ["/nonexistent/file.txt"])
        assert ok is False
        assert "FEHLER" in output or "existiert nicht" in output

    def test_delete_dry_run(self, handler, sample_file):
        ok, output = handler.handle("delete", [str(sample_file)], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output
        assert sample_file.exists()

    def test_delete_no_args(self, handler):
        ok, output = handler.handle("delete", [])
        assert ok is False
        assert "FEHLER" in output

    def test_delete_creates_db_entry(self, handler, sample_file):
        handler.handle("delete", [str(sample_file)])

        conn = sqlite3.connect(str(handler.db_path))
        rows = conn.execute("SELECT * FROM files_trash WHERE status='active'").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_delete_moves_to_trash_dir(self, handler, sample_file):
        handler.handle("delete", [str(sample_file)])
        trash_files = list(handler.trash_dir.glob("*"))
        assert len(trash_files) == 1
        assert "testfile.txt" in trash_files[0].name


# ═══════════════════════════════════════════════════════════════
# RESTORE
# ═══════════════════════════════════════════════════════════════


class TestRestore:
    def test_restore_deleted_file(self, handler, sample_file):
        original_content = sample_file.read_text(encoding="utf-8")
        handler.handle("delete", [str(sample_file)])

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT id FROM files_trash WHERE status='active'").fetchone()
        conn.close()
        trash_id = str(row[0])

        ok, output = handler.handle("restore", [trash_id])
        assert ok is True
        assert "RESTORE" in output
        assert sample_file.exists()
        assert sample_file.read_text(encoding="utf-8") == original_content

    def test_restore_nonexistent_id(self, handler):
        ok, output = handler.handle("restore", ["999"])
        assert ok is False
        assert "FEHLER" in output

    def test_restore_no_args(self, handler):
        ok, output = handler.handle("restore", [])
        assert ok is False

    def test_restore_dry_run(self, handler, sample_file):
        handler.handle("delete", [str(sample_file)])

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT id FROM files_trash WHERE status='active'").fetchone()
        conn.close()

        ok, output = handler.handle("restore", [str(row[0])], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output
        assert not sample_file.exists()

    def test_restore_already_restored(self, handler, sample_file):
        handler.handle("delete", [str(sample_file)])

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT id FROM files_trash WHERE status='active'").fetchone()
        trash_id = str(row[0])
        conn.close()

        handler.handle("restore", [trash_id])
        ok, output = handler.handle("restore", [trash_id])
        assert ok is False
        assert "nicht aktiv" in output.lower() or "FEHLER" in output


# ═══════════════════════════════════════════════════════════════
# PURGE
# ═══════════════════════════════════════════════════════════════


class TestPurge:
    def test_purge_no_expired(self, handler):
        ok, output = handler.handle("purge", [])
        assert ok is True
        assert "Keine" in output

    def test_purge_expired_file(self, handler, sample_file):
        handler.handle("delete", [str(sample_file)])

        conn = sqlite3.connect(str(handler.db_path))
        past = (datetime.now() - timedelta(days=1)).isoformat()
        conn.execute("UPDATE files_trash SET expires_at = ?", (past,))
        conn.commit()
        conn.close()

        ok, output = handler.handle("purge", [])
        assert ok is True
        assert "1" in output

    def test_purge_dry_run(self, handler, sample_file):
        handler.handle("delete", [str(sample_file)])

        conn = sqlite3.connect(str(handler.db_path))
        past = (datetime.now() - timedelta(days=1)).isoformat()
        conn.execute("UPDATE files_trash SET expires_at = ?", (past,))
        conn.commit()
        conn.close()

        ok, output = handler.handle("purge", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in output

        trash_files = list(handler.trash_dir.glob("*"))
        assert len(trash_files) == 1


# ═══════════════════════════════════════════════════════════════
# INFO
# ═══════════════════════════════════════════════════════════════


class TestInfo:
    def test_info_existing(self, handler, sample_file):
        handler.handle("delete", [str(sample_file)])

        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT id FROM files_trash").fetchone()
        conn.close()

        ok, output = handler.handle("info", [str(row[0])])
        assert ok is True
        assert "TRASH INFO" in output

    def test_info_nonexistent(self, handler):
        ok, output = handler.handle("info", ["999"])
        assert ok is False
        assert "FEHLER" in output

    def test_info_no_args(self, handler):
        ok, output = handler.handle("info", [])
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════


class TestHelp:
    def test_help(self, handler):
        ok, output = handler.handle("help", [])
        assert ok is True
        assert "TRASH" in output
        assert "Papierkorb" in output


# ═══════════════════════════════════════════════════════════════
# UNKNOWN OPERATION
# ═══════════════════════════════════════════════════════════════


class TestUnknown:
    def test_unknown_operation(self, handler):
        ok, output = handler.handle("foobar", [])
        assert ok is False
        assert "Unbekannte" in output or "FEHLER" in output


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import ast
        source_file = SYSTEM_ROOT / "hub" / "trash.py"
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                pytest.fail(f"Bare except at line {node.lineno} in trash.py")
