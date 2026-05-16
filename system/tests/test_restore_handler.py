# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for RestoreHandler (hub/restore.py)."""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def base_path(tmp_path):
    """Create minimal BACH directory structure."""
    (tmp_path / "data").mkdir()
    (tmp_path / "system").mkdir()
    return tmp_path


@pytest.fixture
def restore_db(base_path):
    """Create a test DB with dist_file_versions table."""
    db_path = base_path / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dist_file_versions (
            id INTEGER PRIMARY KEY,
            file_path TEXT NOT NULL,
            version TEXT NOT NULL,
            file_hash TEXT,
            content BLOB,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            category TEXT DEFAULT 'system'
        )
    """)
    conn.execute("""
        INSERT INTO dist_file_versions (file_path, version, file_hash, content, category)
        VALUES ('system/hub/base.py', 'v1.0', 'abc123', X'68656C6C6F', 'core')
    """)
    conn.execute("""
        INSERT INTO dist_file_versions (file_path, version, file_hash, content, category)
        VALUES ('system/hub/base.py', 'v1.1', 'def456', X'776F726C64', 'core')
    """)
    conn.execute("""
        INSERT INTO dist_file_versions (file_path, version, file_hash, content, category)
        VALUES ('README.md', 'v1.0', 'ghi789', X'7265616D65', 'docs')
    """)
    conn.commit()
    conn.close()
    return db_path


class TestRestoreHandlerInit:
    def test_init(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        assert handler.base_path == base_path
        assert handler.system_root == base_path / "system"

    def test_profile_name(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        assert handler.profile_name == "restore"

    def test_operations(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        ops = handler.get_operations()
        assert "file" in ops
        assert "list" in ops
        assert "category" in ops
        assert "info" in ops


class TestResolveFilePath:
    def test_system_prefix(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        result = handler._resolve_file_path("system/hub/base.py")
        assert result == base_path / "system" / "hub" / "base.py"

    def test_root_file_exists(self, base_path):
        readme = base_path / "README.md"
        readme.write_text("test")
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        result = handler._resolve_file_path("README.md")
        assert result == readme

    def test_root_file_fallback_to_system(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        result = handler._resolve_file_path("nonexistent.py")
        assert result == base_path / "system" / "nonexistent.py"


class TestListVersions:
    def test_list_existing_file(self, base_path, restore_db):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        handler.db_path = restore_db
        versions = handler.list_versions("system/hub/base.py")
        assert len(versions) == 2

    def test_list_nonexistent_file(self, base_path, restore_db):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        handler.db_path = restore_db
        versions = handler.list_versions("nonexistent.py")
        assert versions == []


class TestRestoreFile:
    def test_restore_nonexistent(self, base_path, restore_db):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        handler.db_path = restore_db
        success, msg = handler.restore_file("no_such_file.py")
        assert success is False
        assert "nicht in dist_file_versions" in msg


class TestHandle:
    def test_handle_no_operation(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        success, msg = handler.handle("", [])
        assert success is True
        assert "RESTORE" in msg

    def test_handle_unknown_operation(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        success, msg = handler.handle("invalid_op", [])
        assert success is True
        assert "RESTORE" in msg

    def test_handle_file_no_args(self, base_path):
        from hub.restore import RestoreHandler
        handler = RestoreHandler(base_path)
        success, msg = handler.handle("file", [])
        assert "RESTORE" in msg
