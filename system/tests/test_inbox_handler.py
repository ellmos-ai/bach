# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for InboxHandler (hub/inbox.py)."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from hub.inbox import InboxHandler, INBOX_WATCHER, INBOX_PID_FILE


class TestInboxHandlerInit:
    def test_init_default_base_path(self):
        handler = InboxHandler()
        assert handler.base_path is not None

    def test_init_custom_base_path(self, tmp_path):
        handler = InboxHandler(base_path=tmp_path)
        assert handler.base_path == tmp_path


class TestIsRunning:
    def test_not_running_no_pid_file(self, tmp_path):
        handler = InboxHandler(base_path=tmp_path)
        with patch("hub.inbox.INBOX_PID_FILE", tmp_path / "nonexistent.pid"):
            running, pid = handler._is_running()
            assert running is False
            assert pid is None

    def test_not_running_invalid_pid(self, tmp_path):
        pid_file = tmp_path / "inbox_watcher.pid"
        pid_file.write_text("not_a_number")
        handler = InboxHandler(base_path=tmp_path)
        with patch("hub.inbox.INBOX_PID_FILE", pid_file):
            running, pid = handler._is_running()
            assert running is False
            assert pid is None

    def test_not_running_stale_pid(self, tmp_path):
        pid_file = tmp_path / "inbox_watcher.pid"
        pid_file.write_text("99999999")
        handler = InboxHandler(base_path=tmp_path)
        with patch("hub.inbox.INBOX_PID_FILE", pid_file):
            running, pid = handler._is_running()
            assert running is False
            assert not pid_file.exists()


class TestStart:
    def test_start_already_running(self, tmp_path):
        handler = InboxHandler(base_path=tmp_path)
        with patch.object(handler, "_is_running", return_value=(True, 12345)):
            success, msg = handler._start()
            assert success is True
            assert "Bereits aktiv" in msg
            assert "12345" in msg

    def test_start_missing_watcher_script(self, tmp_path):
        handler = InboxHandler(base_path=tmp_path)
        with patch.object(handler, "_is_running", return_value=(False, None)):
            with patch("hub.inbox.INBOX_WATCHER", tmp_path / "nonexistent.py"):
                success, msg = handler._start()
                assert success is False
                assert "nicht gefunden" in msg


class TestStop:
    def test_stop_not_running(self, tmp_path):
        handler = InboxHandler(base_path=tmp_path)
        with patch.object(handler, "_is_running", return_value=(False, None)):
            success, msg = handler._stop()
            assert success is True
            assert "Nicht aktiv" in msg

    @patch("hub.inbox.subprocess.run")
    def test_stop_running_windows(self, mock_run, tmp_path):
        pid_file = tmp_path / "inbox_watcher.pid"
        pid_file.write_text("12345")
        handler = InboxHandler(base_path=tmp_path)
        with patch.object(handler, "_is_running", return_value=(True, 12345)):
            with patch("hub.inbox.INBOX_PID_FILE", pid_file):
                with patch("hub.inbox.sys.platform", "win32"):
                    success, msg = handler._stop()
                    assert success is True
                    assert "Gestoppt" in msg
                    mock_run.assert_called_once()


class TestStatus:
    def test_status_stopped(self, tmp_path):
        handler = InboxHandler(base_path=tmp_path)
        with patch.object(handler, "_is_running", return_value=(False, None)):
            with patch("hub.inbox.INBOX_WATCHER", tmp_path / "inbox_watcher.py"):
                with patch("hub.inbox.INBOX_PID_FILE", tmp_path / "pid"):
                    success, msg = handler._status()
                    assert success is True
                    assert "[STOPPED]" in msg

    def test_status_running(self, tmp_path):
        handler = InboxHandler(base_path=tmp_path)
        with patch.object(handler, "_is_running", return_value=(True, 9999)):
            with patch("hub.inbox.INBOX_WATCHER", tmp_path / "inbox_watcher.py"):
                with patch("hub.inbox.INBOX_PID_FILE", tmp_path / "pid"):
                    success, msg = handler._status()
                    assert success is True
                    assert "[RUNNING]" in msg
                    assert "9999" in msg
