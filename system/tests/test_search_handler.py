# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SearchHandler (hub/search.py)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.search import SearchHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def handler(tmp_path, monkeypatch):
    """Minimal SearchHandler with mocked engine."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    db_path.write_bytes(b"")  # ensure file exists so _canonical_db resolves to it
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    h = SearchHandler(tmp_path)
    return h


@pytest.fixture
def mock_engine():
    """Reusable mock for UnifiedSearch engine."""
    engine = MagicMock()
    engine.search.return_value = (True, [])
    engine.index_all.return_value = (True, "Indexed all.")
    engine.status.return_value = (True, {
        "total_items": 0,
        "total_words": 0,
        "total_tags": 0,
        "fts_entries": 0,
        "by_source": {},
    })
    engine.rebuild.return_value = (True, "Rebuilt.")
    engine.list_tags.return_value = (True, [])
    engine.find_duplicates.return_value = (True, [])
    return engine


# ═══════════════════════════════════════════════════════════════
# TESTS: PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "search"

    def test_target_file(self, handler):
        assert handler.target_file == handler.db_path

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "search" in ops
        assert "index" in ops
        assert "status" in ops
        assert "rebuild" in ops
        assert "tags" in ops
        assert "dupes" in ops
        assert "help" in ops


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE
# ═══════════════════════════════════════════════════════════════


class TestHandle:
    def test_help_operation(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok is True
        assert "BACH Unified Search" in msg

    def test_empty_operation(self, handler):
        ok, msg = handler.handle("", [])
        assert ok is True
        assert isinstance(msg, str)

    def test_find_treated_as_search(self, handler, mock_engine):
        """'find' is not a keyword, so it is routed to _search as a query."""
        handler._engine = mock_engine
        ok, msg = handler.handle("find", ["testquery"])
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        mock_engine.search.assert_called_once()

    def test_grep_treated_as_search(self, handler, mock_engine):
        """'grep' is not a keyword, so it is routed to _search as a query."""
        handler._engine = mock_engine
        ok, msg = handler.handle("grep", ["something"])
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        mock_engine.search.assert_called_once()

    def test_status_operation(self, handler, mock_engine):
        handler._engine = mock_engine
        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "UNIFIED SEARCH INDEX" in msg

    def test_index_operation(self, handler, mock_engine):
        handler._engine = mock_engine
        ok, msg = handler.handle("index", [])
        assert ok is True
        mock_engine.index_all.assert_called_once()

    def test_rebuild_operation(self, handler, mock_engine):
        handler._engine = mock_engine
        ok, msg = handler.handle("rebuild", [])
        assert ok is True
        mock_engine.rebuild.assert_called_once()

    def test_tags_no_args(self, handler, mock_engine):
        handler._engine = mock_engine
        ok, msg = handler.handle("tags", [])
        assert ok is True
        assert isinstance(msg, str)

    def test_dupes_operation(self, handler, mock_engine):
        handler._engine = mock_engine
        ok, msg = handler.handle("dupes", [])
        assert ok is True
        assert isinstance(msg, str)

    def test_scan_no_args(self, handler, mock_engine):
        handler._engine = mock_engine
        ok, msg = handler.handle("scan", [])
        assert ok is False
        assert "Usage" in msg

    def test_search_with_results(self, handler, mock_engine):
        mock_engine.search.return_value = (True, [
            {"source": "wiki", "title": "Test Article", "tags": ["test"],
             "source_path": None, "snippet": "A test snippet"},
        ])
        handler._engine = mock_engine
        ok, msg = handler.handle("testquery", [])
        assert ok is True
        assert "Test Article" in msg
        assert "1 Treffer" in msg

    def test_search_no_results(self, handler, mock_engine):
        mock_engine.search.return_value = (True, [])
        handler._engine = mock_engine
        ok, msg = handler.handle("nonexistent_xyz", [])
        assert ok is True
        assert "Keine Treffer" in msg

    def test_unknown_treated_as_search(self, handler, mock_engine):
        """Any unknown operation string is treated as a search query."""
        handler._engine = mock_engine
        ok, msg = handler.handle("xyzrandomop", [])
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        mock_engine.search.assert_called_once()
