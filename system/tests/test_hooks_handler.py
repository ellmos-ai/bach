# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for HooksHandler (hub/hooks.py)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.hooks import HooksHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def handler(tmp_path, monkeypatch):
    """Minimal HooksHandler."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    db_path.write_bytes(b"")
    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return HooksHandler(tmp_path)


@pytest.fixture
def mock_hooks():
    """Fresh mock for core.hooks.hooks singleton."""
    m = MagicMock()
    m.status.return_value = "HOOK-FRAMEWORK STATUS\n==\nAktive Events: 0\nListener gesamt: 0"
    m.list_events.return_value = {
        "after_task_done": {"description": "Nach Task-Erledigung", "listeners": 0},
        "after_startup": {"description": "Nach dem Startup", "listeners": 1},
    }
    m.listener_count.return_value = 1
    m._log = []
    m.emit.return_value = []
    return m


# ═══════════════════════════════════════════════════════════════
# TESTS: PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "hooks"

    def test_target_file(self, handler):
        assert handler.target_file.name == "hooks.py"

    def test_get_operations(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "status" in ops
        assert "events" in ops
        assert "log" in ops
        assert "test" in ops


# ═══════════════════════════════════════════════════════════════
# TESTS: HANDLE
# ═══════════════════════════════════════════════════════════════


class TestHandle:
    def test_status_operation(self, handler, mock_hooks):
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("status", [])
        assert ok is True
        assert "HOOK-FRAMEWORK STATUS" in msg

    def test_empty_operation_defaults_to_status(self, handler, mock_hooks):
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("", [])
        assert ok is True
        mock_hooks.status.assert_called()

    def test_none_operation_defaults_to_status(self, handler, mock_hooks):
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle(None, [])
        assert ok is True
        mock_hooks.status.assert_called()

    def test_events_operation(self, handler, mock_hooks):
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("events", [])
        assert ok is True
        assert "HOOK EVENTS" in msg
        assert "after_task_done" in msg
        assert "after_startup" in msg

    def test_log_empty(self, handler, mock_hooks):
        mock_hooks._log = []
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("log", [])
        assert ok is True
        assert "Keine Hook-Events" in msg

    def test_log_with_entries(self, handler, mock_hooks):
        mock_hooks._log = [
            {"timestamp": "2026-05-16T12:00:00", "event": "after_startup",
             "listeners": 2, "results": 1},
        ]
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("log", [])
        assert ok is True
        assert "after_startup" in msg

    def test_test_event(self, handler, mock_hooks):
        mock_hooks.emit.return_value = ["result1"]
        mock_hooks.listener_count.return_value = 1
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("test", ["after_startup"])
        assert ok is True
        assert "TEST: after_startup" in msg
        mock_hooks.emit.assert_called_once()

    def test_test_no_args(self, handler, mock_hooks):
        """test without event name falls to else branch."""
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("test", [])
        assert ok is False
        assert "Usage" in msg

    def test_list_is_unknown(self, handler, mock_hooks):
        """'list' is not a valid operation -- falls to else."""
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("list", [])
        assert ok is False
        assert "Usage" in msg

    def test_register_is_unknown(self, handler, mock_hooks):
        """'register' is not a valid operation -- falls to else."""
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("register", [])
        assert ok is False
        assert "Usage" in msg

    def test_unknown_operation(self, handler, mock_hooks):
        with patch("core.hooks.hooks", mock_hooks):
            ok, msg = handler.handle("nonexistent", [])
        assert ok is False
        assert "Usage" in msg
