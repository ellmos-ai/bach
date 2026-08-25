# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for DailyAgentHandler (hub/daily_agent.py)."""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.daily_agent import DailyAgentHandler


@pytest.fixture
def daily_env(tmp_path):
    """Minimal environment for DailyAgentHandler."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    (system_dir / "data").mkdir()

    bach_dir = tmp_path / ".bach"
    bach_dir.mkdir()

    return system_dir


@pytest.fixture
def handler(daily_env):
    h = DailyAgentHandler(daily_env)
    h.pid_file = daily_env / "data" / "daily_agent.pid"
    return h


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "daily-agent"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "start" in ops
        assert "stop" in ops
        assert "briefing" in ops


class TestCalendarBriefing:
    def test_reads_canonical_assistant_calendar(self, handler):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE assistant_calendar (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                start_datetime TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO assistant_calendar (title, start_datetime) VALUES (?, ?)",
            ("Jour fixe", f"{datetime.now().astimezone().date().isoformat()} 10:30:00"),
        )

        text = handler._mod_calendar_briefing(conn)

        assert "KALENDER (1 Termine)" in text
        assert "10:30 Jour fixe" in text


class TestStartPopen:
    @patch("subprocess.Popen")
    def test_start_win32_creationflags(self, mock_popen, handler):
        """Regression: Popen must pass CREATE_NO_WINDOW on Windows."""
        mock_popen.return_value = MagicMock(pid=9999)
        with patch.object(handler, "_find_claude_cli", return_value="/usr/bin/claude"), \
             patch("hub.daily_agent.sys.platform", "win32"):
            ok, msg = handler.handle("start", [])
        assert ok is True
        assert "gestartet" in msg
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("creationflags") == 0x08000000
        assert "start_new_session" not in call_kwargs

    @patch("subprocess.Popen")
    def test_start_unix_start_new_session(self, mock_popen, handler):
        """Regression: Popen must pass start_new_session on Unix."""
        mock_popen.return_value = MagicMock(pid=9999)
        with patch.object(handler, "_find_claude_cli", return_value="/usr/bin/claude"), \
             patch("hub.daily_agent.sys.platform", "linux"):
            ok, msg = handler.handle("start", [])
        assert ok is True
        assert "gestartet" in msg
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("start_new_session") is True
        assert "creationflags" not in call_kwargs

    @patch("subprocess.Popen", side_effect=OSError("exec failed"))
    def test_start_popen_error(self, mock_popen, handler):
        with patch.object(handler, "_find_claude_cli", return_value="/usr/bin/claude"):
            ok, msg = handler.handle("start", [])
        assert ok is False
        assert "fehlgeschlagen" in msg

    def test_start_no_claude_cli(self, handler):
        with patch.object(handler, "_find_claude_cli", return_value=""):
            ok, msg = handler.handle("start", [])
        assert ok is False
        assert "nicht gefunden" in msg
