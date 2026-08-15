# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for DailyAgentHandler (hub/daily_agent.py)."""

import sys
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

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
    h.db_path = daily_env / "data" / "bach.db"
    return h


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "daily-agent"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "start" in ops
        assert "stop" in ops
        assert "briefing" in ops
        assert "deliver" in ops


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


def _make_briefing_db(path: Path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tasks (id INTEGER, title TEXT, priority TEXT, status TEXT);
        CREATE TABLE scheduler_jobs (id INTEGER, name TEXT, is_active INTEGER);
        CREATE TABLE messages (id INTEGER, status TEXT);
        CREATE TABLE memory_sessions (id INTEGER, summary TEXT);
        CREATE TABLE household_routines (
            id INTEGER, name TEXT, next_due TEXT, is_active INTEGER
        );
        CREATE TABLE fin_insurances (
            id INTEGER, anbieter TEXT, sparte TEXT, status TEXT,
            naechste_kuendigung TEXT
        );
        CREATE TABLE abo_subscriptions (id INTEGER, aktiv INTEGER);
        CREATE TABLE connections (
            id INTEGER PRIMARY KEY, name TEXT, type TEXT, category TEXT,
            endpoint TEXT, is_active INTEGER, auth_type TEXT, auth_config TEXT
        );
        CREATE TABLE connector_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector_name TEXT, direction TEXT, sender TEXT, recipient TEXT,
            content TEXT, processed INTEGER DEFAULT 0, error TEXT,
            retry_count INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 5,
            status TEXT DEFAULT 'pending', updated_at TEXT, created_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


class TestBriefingDelivery:
    def test_commitments_are_claim_neutral(self, handler):
        _make_briefing_db(handler.db_path)
        conn = sqlite3.connect(handler.db_path)
        conn.executescript(
            """
            INSERT INTO household_routines VALUES (1, 'Küche', '2000-01-01 09:00', 1);
            INSERT INTO fin_insurances VALUES (1, 'HUK', 'Haftpflicht', 'aktiv', date('now', '+5 days'));
            INSERT INTO abo_subscriptions VALUES (1, 1);
            """
        )
        conn.commit()
        conn.close()

        ok, text = handler.handle("briefing", [])

        assert ok is True
        assert "FÄLLIGE ROUTINEN (1)" in text
        assert "VERSICHERUNGSFRISTEN BIS 90 TAGE (1)" in text
        assert "ABOS: 1 aktiv; im Kanon sind keine Fälligkeitsdaten gespeichert." in text

    def test_deliver_dry_run_has_no_db_side_effect(self, handler):
        _make_briefing_db(handler.db_path)

        ok, text = handler.handle("deliver", [], dry_run=True)

        assert ok is True
        assert "[DRY-RUN]" in text
        conn = sqlite3.connect(handler.db_path)
        count = conn.execute("SELECT COUNT(*) FROM connector_messages").fetchone()[0]
        config_table = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'briefing_config'"
        ).fetchone()[0]
        conn.close()
        assert count == 0
        assert config_table == 0

    def test_deliver_sends_once_without_dispatching_foreign_queue(self, handler):
        _make_briefing_db(handler.db_path)
        conn = sqlite3.connect(handler.db_path)
        conn.execute(
            "INSERT INTO connector_messages "
            "(connector_name, direction, sender, recipient, content) "
            "VALUES ('telegram_main', 'out', 'foreign', '123', 'fremd')"
        )
        conn.commit()
        conn.close()

        connector = MagicMock()
        connector.send_message.return_value = True
        with patch("hub.connector.ConnectorHandler._instantiate", return_value=(connector, "")):
            ok_first, first = handler.handle("deliver", [])
            ok_second, second = handler.handle("deliver", [])

        assert ok_first is True
        assert "gesendet" in first
        assert ok_second is True
        assert "[SKIP]" in second
        connector.send_message.assert_called_once()
        connector.disconnect.assert_called_once()

        conn = sqlite3.connect(handler.db_path)
        foreign = conn.execute(
            "SELECT processed FROM connector_messages WHERE sender = 'foreign'"
        ).fetchone()[0]
        own = conn.execute(
            "SELECT processed, status, max_retries FROM connector_messages "
            "WHERE sender = 'daily-agent'"
        ).fetchone()
        conn.close()
        assert foreign == 0
        assert own == (1, "sent", 0)

    def test_deliver_failure_is_recorded_without_retry(self, handler):
        _make_briefing_db(handler.db_path)
        connector = MagicMock()
        connector.send_message.return_value = False
        with patch("hub.connector.ConnectorHandler._instantiate", return_value=(connector, "")):
            ok, text = handler.handle("deliver", [])

        assert ok is False
        assert "kein Retry" in text
        conn = sqlite3.connect(handler.db_path)
        row = conn.execute(
            "SELECT processed, status, error, max_retries FROM connector_messages "
            "WHERE sender = 'daily-agent'"
        ).fetchone()
        conn.close()
        assert row == (1, "failed", "send_failed", 0)
