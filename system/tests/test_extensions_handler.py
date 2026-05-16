# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ExtensionsHandler (hub/extensions.py)."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.extensions import ExtensionsHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def ext_env(tmp_path):
    """Minimal environment for ExtensionsHandler."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "data").mkdir()
    (system_dir / "hub").mkdir()

    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir()

    return system_dir


@pytest.fixture
def handler(ext_env):
    """ExtensionsHandler with mocked base_path."""
    h = ExtensionsHandler(ext_env)
    return h


@pytest.fixture
def ext_with_data(ext_env):
    """Environment with sample extensions."""
    extensions_dir = ext_env.parent / "extensions"

    # Extension 1: Full-featured
    ext1 = extensions_dir / "my_tool"
    ext1.mkdir()
    (ext1 / "main.py").write_text("# main", encoding="utf-8")
    (ext1 / "helper.py").write_text("# helper", encoding="utf-8")
    (ext1 / "START.bat").write_text("@echo off\npython main.py", encoding="utf-8")
    (ext1 / "SKILL.md").write_text(
        "---\nname: my_tool\ndescription: A test tool\n---\n", encoding="utf-8"
    )
    (ext1 / "README.md").write_text("# My Tool\nThis is a test tool.\n", encoding="utf-8")
    (ext1 / "requirements.txt").write_text("requests\n", encoding="utf-8")

    # Extension 2: Minimal (only py files)
    ext2 = extensions_dir / "simple_ext"
    ext2.mkdir()
    (ext2 / "app.py").write_text("# app", encoding="utf-8")

    # Extension 3: With README but no SKILL.md
    ext3 = extensions_dir / "readme_only"
    ext3.mkdir()
    (ext3 / "run.py").write_text("# run", encoding="utf-8")
    (ext3 / "README.md").write_text("# Readme Only\nSome description here.\n", encoding="utf-8")

    # Hidden dir (should be skipped)
    hidden = extensions_dir / ".hidden"
    hidden.mkdir()

    h = ExtensionsHandler(ext_env)
    return h


# ═══════════════════════════════════════════════════════════════
# BASIC PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "extensions"

    def test_target_file(self, handler, ext_env):
        assert handler.target_file == ext_env.parent / "extensions"

    def test_extensions_dir_uses_self_base_path(self, ext_env):
        h = ExtensionsHandler(ext_env)
        assert h.extensions_dir == ext_env.parent / "extensions"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "list" in ops
        assert "show" in ops
        assert "run" in ops
        assert "sync" in ops
        assert "search" in ops


# ═══════════════════════════════════════════════════════════════
# APP-STYLE INIT (regression test for the base_path.parent bug)
# ═══════════════════════════════════════════════════════════════


class TestAppInit:
    def test_init_with_app_object(self, ext_env):
        """Regression: ExtensionsHandler must work with App-style init."""
        app = MagicMock()
        app.base_path = ext_env
        app.db = MagicMock()
        h = ExtensionsHandler(app)
        assert h.extensions_dir == ext_env.parent / "extensions"
        assert h.base_path == ext_env


# ═══════════════════════════════════════════════════════════════
# HANDLE ROUTING
# ═══════════════════════════════════════════════════════════════


class TestRouting:
    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [], dry_run=False)
        assert ok is True
        assert "Keine Extensions gefunden" in msg

    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [], dry_run=False)
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_show_no_args(self, handler):
        ok, msg = handler.handle("show", [], dry_run=False)
        assert ok is False
        assert "Name angeben" in msg

    def test_run_no_args(self, handler):
        ok, msg = handler.handle("run", [], dry_run=False)
        assert ok is False
        assert "Name angeben" in msg

    def test_search_no_args(self, handler):
        ok, msg = handler.handle("search", [], dry_run=False)
        assert ok is False
        assert "Suchbegriff angeben" in msg


# ═══════════════════════════════════════════════════════════════
# FILESYSTEM SCANNING
# ═══════════════════════════════════════════════════════════════


class TestFsScan:
    def test_scan_returns_list(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        assert isinstance(exts, list)

    def test_scan_finds_extensions(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        names = [e["name"] for e in exts]
        assert "my_tool" in names
        assert "simple_ext" in names
        assert "readme_only" in names

    def test_scan_skips_hidden_dirs(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        names = [e["name"] for e in exts]
        assert ".hidden" not in names

    def test_scan_detects_skill_md(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        my_tool = next(e for e in exts if e["name"] == "my_tool")
        assert my_tool["has_skill"] is True
        simple = next(e for e in exts if e["name"] == "simple_ext")
        assert simple["has_skill"] is False

    def test_scan_detects_start_bat(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        my_tool = next(e for e in exts if e["name"] == "my_tool")
        assert my_tool["has_start"] is True

    def test_scan_reads_description_from_skill(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        my_tool = next(e for e in exts if e["name"] == "my_tool")
        assert my_tool["description"] == "A test tool"

    def test_scan_reads_description_from_readme(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        readme_only = next(e for e in exts if e["name"] == "readme_only")
        assert "Some description" in readme_only["description"]

    def test_scan_counts_py_files(self, ext_with_data):
        exts = ext_with_data._get_extensions_from_fs()
        my_tool = next(e for e in exts if e["name"] == "my_tool")
        assert my_tool["py_count"] == 2

    def test_scan_nonexistent_dir(self, handler):
        handler.extensions_dir = handler.base_path / "nonexistent"
        exts = handler._get_extensions_from_fs()
        assert exts == []


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_with_data(self, ext_with_data):
        ok, msg = ext_with_data.handle("list", [], dry_run=False)
        assert ok is True
        assert "3 Extensions gefunden" in msg
        assert "my_tool" in msg
        assert "simple_ext" in msg

    def test_list_shows_flags(self, ext_with_data):
        ok, msg = ext_with_data.handle("list", [], dry_run=False)
        assert "SKILL" in msg
        assert "START" in msg


# ═══════════════════════════════════════════════════════════════
# SHOW
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_existing(self, ext_with_data):
        ok, msg = ext_with_data.handle("show", ["my_tool"], dry_run=False)
        assert ok is True
        assert "EXTENSION: my_tool" in msg
        assert "SKILL.md" in msg

    def test_show_nonexistent(self, ext_with_data):
        ok, msg = ext_with_data.handle("show", ["nonexistent"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    def test_show_fuzzy_match(self, ext_with_data):
        ok, msg = ext_with_data.handle("show", ["tool"], dry_run=False)
        assert ok is False
        assert "Meinten Sie" in msg
        assert "my_tool" in msg


# ═══════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════


class TestSearch:
    def test_search_by_name(self, ext_with_data):
        ok, msg = ext_with_data.handle("search", ["simple"], dry_run=False)
        assert ok is True
        assert "simple_ext" in msg

    def test_search_no_match(self, ext_with_data):
        ok, msg = ext_with_data.handle("search", ["zzz_nonexistent"], dry_run=False)
        assert ok is True
        assert "Keine Treffer" in msg


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════


class TestRun:
    def test_run_nonexistent(self, ext_with_data):
        ok, msg = ext_with_data.handle("run", ["nonexistent"], dry_run=False)
        assert ok is False
        assert "nicht gefunden" in msg

    @patch("subprocess.Popen")
    def test_run_with_start_bat_on_windows(self, mock_popen, ext_with_data):
        with patch("sys.platform", "win32"):
            ok, msg = ext_with_data.handle("run", ["my_tool"], dry_run=False)
            assert ok is True
            assert "gestartet" in msg

    @patch("subprocess.Popen")
    def test_run_fallback_to_py_file(self, mock_popen, ext_with_data):
        ok, msg = ext_with_data.handle("run", ["simple_ext"], dry_run=False)
        assert ok is True
        assert "gestartet" in msg
        assert "app.py" in msg

    def test_run_no_startable_file(self, ext_with_data):
        empty_ext = ext_with_data.extensions_dir / "empty_ext"
        empty_ext.mkdir()
        ok, msg = ext_with_data.handle("run", ["empty_ext"], dry_run=False)
        assert ok is False
        assert "Keine startbare Datei" in msg

    @patch("subprocess.Popen", side_effect=OSError("exec failed"))
    def test_run_popen_error(self, mock_popen, ext_with_data):
        ok, msg = ext_with_data.handle("run", ["simple_ext"], dry_run=False)
        assert ok is False
        assert "fehlgeschlagen" in msg


# ═══════════════════════════════════════════════════════════════
# SYNC
# ═══════════════════════════════════════════════════════════════


class TestSync:
    def test_sync_no_extensions(self, handler):
        ok, msg = handler.handle("sync", [], dry_run=False)
        assert ok is True
        assert "Keine Extensions zum Synchronisieren" in msg

    @patch("sqlite3.connect")
    def test_sync_dry_run(self, mock_connect, ext_with_data):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        ok, msg = ext_with_data.handle("sync", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        mock_conn.commit.assert_not_called()

    @patch("sqlite3.connect")
    def test_sync_inserts_new(self, mock_connect, ext_with_data):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        ok, msg = ext_with_data.handle("sync", [], dry_run=False)
        assert ok is True
        assert "neu" in msg
        mock_conn.commit.assert_called_once()
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(insert_calls) == 3, (
            f"Expected 3 INSERTs (one per extension), got {len(insert_calls)}"
        )

    @patch("sqlite3.connect")
    def test_sync_updates_existing(self, mock_connect, ext_with_data):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("my_tool",)]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        ok, msg = ext_with_data.handle("sync", [], dry_run=False)
        assert ok is True
        assert "aktualisiert" in msg
        update_calls = [c for c in mock_cursor.execute.call_args_list
                        if "UPDATE" in str(c)]
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if "INSERT" in str(c)]
        assert len(update_calls) == 1, (
            f"Expected 1 UPDATE (my_tool), got {len(update_calls)}"
        )
        assert len(insert_calls) == 2, (
            f"Expected 2 INSERTs (simple_ext + readme_only), got {len(insert_calls)}"
        )

    @patch("sqlite3.connect")
    def test_sync_closes_connection(self, mock_connect, ext_with_data):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        ext_with_data.handle("sync", [], dry_run=False)
        mock_conn.close.assert_called_once()

    @patch("sqlite3.connect")
    def test_sync_closes_on_error(self, mock_connect, ext_with_data):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = Exception("DB error")
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        with pytest.raises(Exception):
            ext_with_data.handle("sync", [], dry_run=False)
        mock_conn.close.assert_called_once()
