# -*- coding: utf-8 -*-
"""Tests for bridge_tray.py cross-platform compatibility."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

import pytest


# bridge_tray imports pystray and PIL at module level — mock them before import
@pytest.fixture(autouse=True)
def _mock_pystray_and_pil(monkeypatch):
    """Ensure pystray/PIL mocks are in place for every test."""
    pass


def _get_bridge_module():
    """Import bridge_tray with heavy deps mocked out."""
    mocks = {}
    for mod_name in ("pystray", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont"):
        if mod_name not in sys.modules:
            mocks[mod_name] = MagicMock()
            sys.modules[mod_name] = mocks[mod_name]

    if sys.platform != "win32":
        pass  # fcntl is available natively
    else:
        if "fcntl" not in sys.modules:
            mocks["fcntl"] = MagicMock()
            sys.modules["fcntl"] = mocks["fcntl"]

    from hub._services.claude_bridge import bridge_tray
    return bridge_tray, mocks


# ============ _on_logs tests ============

class TestOnLogs:
    """Tests for BridgeTray._on_logs cross-platform file opening."""

    def test_windows_uses_startfile(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        log_file = tmp_path / "test.log"
        log_file.write_text("test")

        icon = MagicMock()
        tray = MagicMock(spec=bridge_tray.BridgeTray)
        tray._on_logs = bridge_tray.BridgeTray._on_logs.__get__(tray)

        with patch.object(bridge_tray, "LOG_FILE", log_file), \
             patch("sys.platform", "win32"), \
             patch("os.startfile") as mock_start:
            tray._on_logs(icon, None)
            mock_start.assert_called_once_with(str(log_file))

    def test_macos_uses_open(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        log_file = tmp_path / "test.log"
        log_file.write_text("test")

        icon = MagicMock()
        tray = MagicMock(spec=bridge_tray.BridgeTray)
        tray._on_logs = bridge_tray.BridgeTray._on_logs.__get__(tray)

        with patch.object(bridge_tray, "LOG_FILE", log_file), \
             patch("sys.platform", "darwin"), \
             patch("subprocess.Popen") as mock_popen:
            tray._on_logs(icon, None)
            mock_popen.assert_called_once_with(["open", str(log_file)])

    def test_linux_uses_xdg_open(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        log_file = tmp_path / "test.log"
        log_file.write_text("test")

        icon = MagicMock()
        tray = MagicMock(spec=bridge_tray.BridgeTray)
        tray._on_logs = bridge_tray.BridgeTray._on_logs.__get__(tray)

        with patch.object(bridge_tray, "LOG_FILE", log_file), \
             patch("sys.platform", "linux"), \
             patch("subprocess.Popen") as mock_popen:
            tray._on_logs(icon, None)
            mock_popen.assert_called_once_with(["xdg-open", str(log_file)])

    def test_missing_log_notifies(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        missing = tmp_path / "nonexistent.log"

        icon = MagicMock()
        tray = MagicMock(spec=bridge_tray.BridgeTray)
        tray._on_logs = bridge_tray.BridgeTray._on_logs.__get__(tray)

        with patch.object(bridge_tray, "LOG_FILE", missing):
            tray._on_logs(icon, None)
            icon.notify.assert_called_once()
            assert "Keine Logs" in icon.notify.call_args[0][0]


# ============ _check_single_instance tests ============

class TestCheckSingleInstance:
    """Tests for cross-platform advisory locking."""

    def test_windows_uses_msvcrt(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        lock = tmp_path / "test.lock"

        mock_msvcrt = MagicMock()

        with patch.object(bridge_tray, "LOCK_FILE", lock), \
             patch("sys.platform", "win32"), \
             patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
            bridge_tray._tray_lock_handle = None
            result = bridge_tray._check_single_instance()
            assert result is True
            mock_msvcrt.locking.assert_called_once()
            assert mock_msvcrt.LK_NBLCK in mock_msvcrt.locking.call_args[0]

        # Cleanup
        if bridge_tray._tray_lock_handle:
            bridge_tray._tray_lock_handle.close()
            bridge_tray._tray_lock_handle = None

    def test_unix_uses_fcntl(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        lock = tmp_path / "test.lock"

        mock_fcntl = MagicMock()
        mock_fcntl.LOCK_EX = 2
        mock_fcntl.LOCK_NB = 4

        with patch.object(bridge_tray, "LOCK_FILE", lock), \
             patch("sys.platform", "linux"), \
             patch.dict("sys.modules", {"fcntl": mock_fcntl}):
            bridge_tray._tray_lock_handle = None
            result = bridge_tray._check_single_instance()
            assert result is True
            mock_fcntl.flock.assert_called_once()

        if bridge_tray._tray_lock_handle:
            bridge_tray._tray_lock_handle.close()
            bridge_tray._tray_lock_handle = None

    def test_lock_failure_returns_false(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        lock = tmp_path / "test.lock"

        mock_msvcrt = MagicMock()
        mock_msvcrt.locking.side_effect = OSError("locked")

        with patch.object(bridge_tray, "LOCK_FILE", lock), \
             patch("sys.platform", "win32"), \
             patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
            bridge_tray._tray_lock_handle = None
            result = bridge_tray._check_single_instance()
            assert result is False
            assert bridge_tray._tray_lock_handle is None

    def test_writes_pid_on_success(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        lock = tmp_path / "test.lock"

        mock_msvcrt = MagicMock()

        with patch.object(bridge_tray, "LOCK_FILE", lock), \
             patch("sys.platform", "win32"), \
             patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
            bridge_tray._tray_lock_handle = None
            bridge_tray._check_single_instance()
            assert lock.read_text().strip() == str(os.getpid())

        if bridge_tray._tray_lock_handle:
            bridge_tray._tray_lock_handle.close()
            bridge_tray._tray_lock_handle = None


# ============ _cleanup_lock tests ============

class TestCleanupLock:
    """Tests for cross-platform lock cleanup."""

    def test_windows_cleanup_uses_msvcrt(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        lock = tmp_path / "test.lock"
        lock.write_text("1234")

        handle = open(lock, "a+")
        bridge_tray._tray_lock_handle = handle

        mock_msvcrt = MagicMock()

        with patch("sys.platform", "win32"), \
             patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
            bridge_tray._cleanup_lock()
            mock_msvcrt.locking.assert_called_once()
            assert mock_msvcrt.LK_UNLCK in mock_msvcrt.locking.call_args[0]

        assert bridge_tray._tray_lock_handle is None

    def test_unix_cleanup_uses_fcntl(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        lock = tmp_path / "test.lock"
        lock.write_text("1234")

        handle = open(lock, "a+")
        bridge_tray._tray_lock_handle = handle

        mock_fcntl = MagicMock()
        mock_fcntl.LOCK_UN = 8

        with patch("sys.platform", "linux"), \
             patch.dict("sys.modules", {"fcntl": mock_fcntl}):
            bridge_tray._cleanup_lock()
            mock_fcntl.flock.assert_called_once()

        assert bridge_tray._tray_lock_handle is None

    def test_cleanup_removes_lock_file(self, tmp_path):
        bridge_tray, _ = _get_bridge_module()
        lock = tmp_path / "test.lock"
        lock.write_text("1234")

        handle = open(lock, "a+")
        bridge_tray._tray_lock_handle = handle

        mock_msvcrt = MagicMock()

        with patch("sys.platform", "win32"), \
             patch.object(bridge_tray, "LOCK_FILE", lock), \
             patch.dict("sys.modules", {"msvcrt": mock_msvcrt}):
            bridge_tray._cleanup_lock()

        assert not lock.exists()
        assert bridge_tray._tray_lock_handle is None

    def test_cleanup_no_handle_is_noop(self):
        bridge_tray, _ = _get_bridge_module()
        bridge_tray._tray_lock_handle = None
        bridge_tray._cleanup_lock()
        assert bridge_tray._tray_lock_handle is None


# ============ create_icon smoke test ============

class TestCreateIcon:
    def test_returns_image(self):
        bridge_tray, _ = _get_bridge_module()
        img = bridge_tray.create_icon("green")
        assert img is not None
