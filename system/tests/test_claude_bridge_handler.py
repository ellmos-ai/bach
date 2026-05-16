# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ClaudeBridgeHandler (hub/claude_bridge.py)."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.claude_bridge import ClaudeBridgeHandler


@pytest.fixture
def bridge_env(tmp_path):
    """Minimal environment for ClaudeBridgeHandler."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "data").mkdir()

    service_dir = system_dir / "hub" / "_services" / "claude_bridge"
    service_dir.mkdir(parents=True)
    (service_dir / "bridge_daemon.py").write_text("# daemon", encoding="utf-8")

    return system_dir


@pytest.fixture
def handler(bridge_env):
    return ClaudeBridgeHandler(bridge_env)


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "claude-bridge"

    def test_target_file(self, handler, bridge_env):
        assert handler.target_file == bridge_env / "hub" / "_services" / "claude_bridge"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "start" in ops
        assert "stop" in ops
        assert "status" in ops


class TestRouting:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_start_missing_daemon(self, handler, bridge_env):
        (bridge_env / "hub" / "_services" / "claude_bridge" / "bridge_daemon.py").unlink()
        ok, msg = handler.handle("start", [])
        assert ok is False
        assert "nicht gefunden" in msg


class TestStartPopen:
    @patch("subprocess.Popen")
    def test_start_win32_creationflags(self, mock_popen, handler):
        """Regression: Popen must pass CREATE_NO_WINDOW on Windows."""
        mock_popen.return_value = MagicMock(pid=1234)
        with patch("hub.claude_bridge.sys.platform", "win32"):
            ok, msg = handler.handle("start", [])
        assert ok is True
        assert "gestartet" in msg
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("creationflags") == 0x08000000
        assert "start_new_session" not in call_kwargs

    @patch("subprocess.Popen")
    def test_start_unix_start_new_session(self, mock_popen, handler):
        """Regression: Popen must pass start_new_session on Unix."""
        mock_popen.return_value = MagicMock(pid=1234)
        with patch("hub.claude_bridge.sys.platform", "linux"):
            ok, msg = handler.handle("start", [])
        assert ok is True
        assert "gestartet" in msg
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("start_new_session") is True
        assert "creationflags" not in call_kwargs

    @patch("subprocess.Popen", side_effect=OSError("exec failed"))
    def test_start_popen_error(self, mock_popen, handler):
        ok, msg = handler.handle("start", [])
        assert ok is False
        assert "fehlgeschlagen" in msg
