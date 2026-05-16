# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for DistHandler (hub/dist.py)."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def base_path(tmp_path):
    """Create minimal BACH directory structure."""
    (tmp_path / "data").mkdir()
    (tmp_path / "tools").mkdir()
    return tmp_path


class TestDistHandlerInit:
    def test_init(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        assert handler.base_path == base_path
        assert handler.tools_dir == base_path / "tools"

    def test_profile_name(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        assert handler.profile_name == "dist"

    def test_target_file(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        assert handler.target_file == base_path / "tools" / "distribution.py"


class TestGetOperations:
    def test_all_operations_present(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        ops = handler.get_operations()
        expected = {"status", "verify", "classify", "snapshot", "release", "restore", "install", "list"}
        assert set(ops.keys()) == expected

    def test_operations_have_descriptions(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        for key, desc in handler.get_operations().items():
            assert isinstance(desc, str)
            assert len(desc) > 3


class TestGetDistSystem:
    def test_lazy_load_import_error(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        with patch.dict(sys.modules, {"distribution": None}):
            handler._dist_system = None
            result, err = handler._get_dist_system()
            assert result is None
            assert err is not None

    def test_lazy_load_cached(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        mock_dist = MagicMock()
        handler._dist_system = mock_dist
        result, err = handler._get_dist_system()
        assert result is mock_dist
        assert err is None

    def test_lazy_load_success(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        result, err = handler._get_dist_system()
        if result is not None:
            assert err is None
        else:
            assert err is not None


class TestHandle:
    def test_empty_operation_shows_help(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        success, msg = handler.handle("", [], dry_run=False)
        assert success is True
        assert "BACH Distribution System" in msg

    def test_help_operation(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        success, msg = handler.handle("help", [], dry_run=False)
        assert success is True
        assert "snapshot" in msg

    def test_unknown_operation(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        success, msg = handler.handle("nonexistent", [], dry_run=False)
        assert success is False
        assert "Unbekannter Befehl" in msg

    def test_status_with_mock_dist(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        mock_dist = MagicMock()
        mock_dist.status.return_value = {
            "seal": {"intact": True, "message": "OK"},
            "manifest_count": 100,
            "snapshots": 3,
            "releases_final": 1,
            "releases_total": 2,
            "dist_stats": {},
        }
        handler._dist_system = mock_dist
        success, msg = handler.handle("status", [], dry_run=False)
        assert success is True
        assert "DISTRIBUTION STATUS" in msg

    def test_verify_no_dist_system(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        success, msg = handler.handle("verify", [], dry_run=False)
        assert success is False


class TestShowHelp:
    def test_help_content(self, base_path):
        from hub.dist import DistHandler
        handler = DistHandler(base_path)
        help_text = handler._show_help()
        assert "bach --dist status" in help_text
        assert "bach --dist verify" in help_text
        assert "bach --dist snapshot" in help_text
        assert "bach --dist release" in help_text
        assert "--dry-run" in help_text
