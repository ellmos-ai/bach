# SPDX-License-Identifier: MIT
"""Tests fuer hub/daemon.py — DaemonHandler (Rueckwaertskompatibilitaets-Wrapper)."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.daemon import DaemonHandler, SchedulerHandler


class TestDaemonAlias:
    """DaemonHandler ist ein reiner Re-Export von SchedulerHandler."""

    def test_daemon_handler_is_scheduler_handler(self):
        assert DaemonHandler is SchedulerHandler

    def test_module_exports(self):
        from hub import daemon
        assert "DaemonHandler" in daemon.__all__
        assert "SchedulerHandler" in daemon.__all__


class TestDaemonInstantiation:
    """DaemonHandler laesst sich wie SchedulerHandler instanziieren."""

    def test_create_with_tmp_path(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        (base / "data").mkdir()
        (base / "data" / "logs").mkdir()
        handler = DaemonHandler(base)
        assert handler.profile_name == "scheduler"

    def test_get_operations(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        (base / "data").mkdir()
        (base / "data" / "logs").mkdir()
        handler = DaemonHandler(base)
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "status" in ops
        assert "jobs" in ops
        assert "start" in ops
        assert "stop" in ops
        assert "session" in ops

    def test_handle_status(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        handler = DaemonHandler(base)
        with patch.object(handler, "_get_daemon_pid", return_value=0):
            ok, text = handler.handle("status", [])
        assert ok is True
        assert "SCHEDULER STATUS" in text

    def test_handle_unknown_operation_falls_to_status(self, tmp_path):
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        handler = DaemonHandler(base)
        with patch.object(handler, "_get_daemon_pid", return_value=0):
            ok, text = handler.handle("unknown_operation", [])
        assert ok is True
        # Unknown operation falls through to _show_status
        assert "SCHEDULER STATUS" in text

    def test_handle_list_is_not_valid_operation(self, tmp_path):
        """'list' ist keine gueltige Operation -- wird als unknown behandelt."""
        base = tmp_path / "system"
        base.mkdir()
        (base / "gui").mkdir()
        data_dir = base / "data"
        data_dir.mkdir()
        (data_dir / "logs").mkdir()
        handler = DaemonHandler(base)
        with patch.object(handler, "_get_daemon_pid", return_value=0):
            ok, text = handler.handle("list", [])
        # Falls through to status
        assert ok is True
