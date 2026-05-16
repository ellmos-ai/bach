# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for FsHandler (hub/fs.py).

FSProtection and PathClassifier are mocked to avoid side effects
(they create directories in the real BACH installation on import).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_fs_protection():
    """Mock FSProtection instance."""
    m = MagicMock()
    m.check_integrity.return_value = (True, "Integrity OK: 0 issues")
    m.heal.return_value = (True, "Healed 0 files")
    return m


@pytest.fixture
def mock_classifier():
    """Mock PathClassifier instance."""
    m = MagicMock()
    m.classify_path.return_value = 2
    m.get_protection_level.return_value = "CORE"
    m.scan_directory.return_value = {0: ["user/a.txt"], 1: ["data/b.db"], 2: ["hub/c.py"]}
    return m


@pytest.fixture
def handler(tmp_path, monkeypatch, mock_fs_protection, mock_classifier):
    """FsHandler with mocked FSProtection and PathClassifier."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    db_path.write_bytes(b"")
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)

    # Patch at the hub.fs module level so __init__ uses our mocks
    monkeypatch.setattr("hub.fs.FSProtection", lambda base_path: mock_fs_protection)
    monkeypatch.setattr("hub.fs.PathClassifier", lambda base_path: mock_classifier)

    from hub.fs import FSHandler
    h = FSHandler(tmp_path)
    return h


# ═══════════════════════════════════════════════════════════════
# TESTS: PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "fs"

    def test_target_file(self, handler):
        assert handler.target_file.name == "bach.db"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "check" in ops
        assert "heal" in ops
        assert "classify" in ops
        assert "scan" in ops
        assert "status" in ops


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE
# ═══════════════════════════════════════════════════════════════


class TestHandle:
    def test_check_operation(self, handler):
        ok, msg = handler.handle("check", [])
        assert ok is True
        assert isinstance(msg, str)

    def test_empty_operation_defaults_to_check(self, handler):
        ok, msg = handler.handle("", [])
        assert ok is True

    def test_heal_all(self, handler):
        ok, msg = handler.handle("heal", ["--all"])
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_heal_specific_file(self, handler):
        ok, msg = handler.handle("heal", ["hub/base.py"])
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_heal_no_args(self, handler):
        ok, msg = handler.handle("heal", [])
        assert ok is False
        assert "Usage" in msg

    def test_classify_operation(self, handler):
        ok, msg = handler.handle("classify", ["hub/base.py"])
        assert ok is True
        assert "dist_type=" in msg

    def test_classify_no_args(self, handler):
        ok, msg = handler.handle("classify", [])
        assert ok is False
        assert "Usage" in msg

    def test_scan_operation(self, handler):
        ok, msg = handler.handle("scan", [])
        assert ok is True
        assert "CORE" in msg
        assert "TEMPLATE" in msg
        assert "USER" in msg

    def test_tree_is_unknown(self, handler):
        """'tree' is not a valid fs operation."""
        ok, msg = handler.handle("tree", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_size_is_unknown(self, handler):
        """'size' is not a valid fs operation."""
        ok, msg = handler.handle("size", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg
