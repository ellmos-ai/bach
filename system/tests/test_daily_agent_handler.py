# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for DailyAgentHandler (hub/daily_agent.py)."""

import hashlib
import json
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
from hub._services.routinika_projection import (
    RoutinikaProjectionError,
    read_routinika_projection,
)


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


def _create_routinika_projection(
    path: Path,
    *,
    rows: list[tuple] | None = None,
    tombstones: list[tuple] | None = None,
) -> None:
    """Materialize the ratified C1 schema with synthetic, opaque records."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE projection_metadata (
            contract_id TEXT NOT NULL PRIMARY KEY,
            contract_version TEXT NOT NULL,
            publisher_component TEXT NOT NULL,
            publisher_instance TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            source_checkpoint INTEGER NOT NULL
        );
        CREATE TABLE routine_due (
            record_ref TEXT NOT NULL PRIMARY KEY,
            due_at TEXT NOT NULL,
            window_end_at TEXT NOT NULL,
            state TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL
        );
        CREATE TABLE projection_tombstones (
            record_type TEXT NOT NULL,
            record_ref TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            retain_until TEXT NOT NULL,
            record_version INTEGER NOT NULL,
            source_checkpoint INTEGER NOT NULL,
            publisher_instance TEXT NOT NULL,
            PRIMARY KEY (record_type, record_ref)
        );
        """
    )
    conn.execute(
        "INSERT INTO projection_metadata VALUES (?, ?, ?, ?, ?, ?)",
        (
            "org.ellmos.routinika.reminder-projection",
            "1.0.0",
            "routinika-projection-adapter",
            "routinika-primary",
            "2026-08-22T07:00:00Z",
            6,
        ),
    )
    for row in rows or [
        (
            "cccccccccccccccccccccccccccccccc",
            "2026-08-22T07:30:00Z",
            "2026-08-22T08:00:00Z",
            "due",
            1,
            6,
            "routinika-primary",
        )
    ]:
        conn.execute("INSERT INTO routine_due VALUES (?, ?, ?, ?, ?, ?, ?)", row)
    for row in tombstones or []:
        conn.execute(
            "INSERT INTO projection_tombstones VALUES (?, ?, ?, ?, ?, ?, ?)", row
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


class TestRoutinikaProjectionBriefing:
    def test_dry_run_is_read_only_and_emits_non_personal_receipt(self, handler, tmp_path):
        _make_briefing_db(handler.db_path)
        projection = tmp_path / "routinika-projection.sqlite"
        _create_routinika_projection(projection)
        before = hashlib.sha256(projection.read_bytes()).hexdigest()

        ok, text = handler.handle(
            "briefing",
            [
                f"--routinika-projection={projection}",
                "--routinika-receipt",
                "--dry-run",
            ],
            dry_run=True,
        )

        assert ok is True
        assert "[DRY-RUN] Read-only" in text
        assert "ROUTINIKA-FÄLLIGKEITEN (1)" in text
        assert "Routine cccccccccccc…" in text
        assert "contract=org.ellmos.routinika.reminder-projection@1.0.0" in text
        assert "publisher=routinika-primary" in text
        assert "checkpoint=6" in text
        assert "read_only=true" in text
        assert hashlib.sha256(projection.read_bytes()).hexdigest() == before

        conn = sqlite3.connect(handler.db_path)
        config_table = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'briefing_config'"
        ).fetchone()[0]
        conn.close()
        assert config_table == 0

    def test_terminal_rows_are_not_briefed(self, handler, tmp_path):
        _make_briefing_db(handler.db_path)
        projection = tmp_path / "routinika-projection.sqlite"
        _create_routinika_projection(
            projection,
            rows=[
                (
                    "cccccccccccccccccccccccccccccccc",
                    "2026-08-22T07:30:00Z",
                    "2026-08-22T08:00:00Z",
                    "due",
                    1,
                    6,
                    "routinika-primary",
                ),
                (
                    "dddddddddddddddddddddddddddddddd",
                    "2026-08-22T08:30:00Z",
                    "2026-08-22T09:00:00Z",
                    "completed",
                    1,
                    6,
                    "routinika-primary",
                ),
            ],
        )

        ok, text = handler.handle(
            "briefing", [f"--routinika-projection={projection}", "--dry-run"], dry_run=True
        )

        assert ok is True
        assert "ROUTINIKA-FÄLLIGKEITEN (1)" in text
        assert "cccccccccccc" in text
        assert "dddddddddddd" not in text

    def test_exact_allowlist_rejects_privacy_expansion(self, tmp_path):
        projection = tmp_path / "routinika-projection.sqlite"
        _create_routinika_projection(projection)
        conn = sqlite3.connect(projection)
        conn.execute("ALTER TABLE routine_due ADD COLUMN routine_title TEXT")
        conn.commit()
        conn.close()

        with pytest.raises(RoutinikaProjectionError, match="Spalten-Allowlist"):
            read_routinika_projection(projection)

    def test_unclosed_sidecar_fails_closed(self, tmp_path):
        projection = tmp_path / "routinika-projection.sqlite"
        _create_routinika_projection(projection)
        Path(f"{projection}-wal").write_bytes(b"synthetic")

        with pytest.raises(RoutinikaProjectionError, match="nicht geschlossen"):
            read_routinika_projection(projection)

    def test_config_persists_only_consumer_settings_and_stays_inactive(self, handler, tmp_path):
        _make_briefing_db(handler.db_path)
        projection = tmp_path / "future-routinika-projection.sqlite"

        ok, text = handler.handle(
            "config",
            [
                "routinika_briefing",
                f"--projection={projection}",
                "--minimum-offline-seconds=2592000",
            ],
        )

        assert ok is True
        assert "bleibt deaktiviert" in text
        conn = sqlite3.connect(handler.db_path)
        row = conn.execute(
            "SELECT is_active, settings_json FROM briefing_config "
            "WHERE module_name = 'routinika_briefing'"
        ).fetchone()
        conn.close()
        assert row[0] == 0
        assert json.loads(row[1]) == {
            "minimum_offline_seconds": 2592000,
            "projection_path": str(projection.resolve()),
        }
