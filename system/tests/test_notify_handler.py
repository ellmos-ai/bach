# -*- coding: utf-8 -*-
"""Tests for NotifyHandler (hub/notify.py)."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hub.notify import NotifyHandler


def _create_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS connections (
            name TEXT PRIMARY KEY,
            type TEXT,
            category TEXT,
            endpoint TEXT,
            auth_type TEXT DEFAULT 'none',
            auth_config TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            last_used TEXT,
            success_count INTEGER DEFAULT 0,
            help_text TEXT
        );
        CREATE TABLE IF NOT EXISTS connector_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector_name TEXT,
            direction TEXT,
            sender TEXT,
            recipient TEXT,
            content TEXT,
            processed INTEGER DEFAULT 0,
            created_at TEXT
        );
    """)
    conn.commit()


@pytest.fixture
def notify_env(tmp_path):
    base = tmp_path / "bach" / "system"
    (base / "data").mkdir(parents=True)
    (base / "hub").mkdir()
    (base / "user" / "secrets").mkdir(parents=True)

    db_path = base / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_schema(conn)
    conn.close()

    h = NotifyHandler(base)
    h.db_path = db_path
    return h, base, db_path


def _add_channel(db_path, channel, endpoint="", active=1, auth_config=""):
    conn = sqlite3.connect(str(db_path))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        INSERT INTO connections (name, type, category, endpoint, auth_config, is_active, created_at, updated_at, success_count)
        VALUES (?, ?, 'notification', ?, ?, ?, ?, ?, 0)
    """, (f"notify_{channel}", channel, endpoint, auth_config, active, now, now))
    conn.commit()
    conn.close()


class TestInit:
    def test_profile_name(self, notify_env):
        h, _, _ = notify_env
        assert h.profile_name == "notify"

    def test_operations(self, notify_env):
        h, _, _ = notify_env
        ops = h.get_operations()
        assert "send" in ops
        assert "setup" in ops
        assert "test" in ops
        assert "list" in ops
        assert "status" in ops
        assert "history" in ops
        assert "help" in ops

    def test_channels_constant(self, notify_env):
        h, _, _ = notify_env
        assert "telegram" in h.CHANNELS
        assert "discord" in h.CHANNELS
        assert "slack" in h.CHANNELS


class TestHandle:
    def test_unknown_operation(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("nope", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_dispatches_send(self, notify_env):
        h, _, _ = notify_env
        with patch.object(h, "_send", return_value=(True, "OK")) as mock:
            h.handle("send", ["telegram", "test"])
        mock.assert_called_once()

    def test_dispatches_help(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("help", [])
        assert ok is True
        assert "Notification-System" in msg


class TestSend:
    def test_send_no_args(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("send", [])
        assert ok is False
        assert "Verwendung" in msg

    def test_send_one_arg(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("send", ["telegram"])
        assert ok is False

    def test_send_dry_run(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("send", ["telegram", "Hello"], dry_run=True)
        assert ok is True
        assert "DRY" in msg

    def test_send_unconfigured_channel(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("send", ["telegram", "Hello"])
        assert ok is False
        assert "nicht konfiguriert" in msg

    def test_send_disabled_channel(self, notify_env):
        h, _, db_path = notify_env
        _add_channel(db_path, "telegram", active=0)
        ok, msg = h.handle("send", ["telegram", "Hello"])
        assert ok is False
        assert "deaktiviert" in msg

    def test_send_queues_message(self, notify_env):
        h, _, db_path = notify_env
        _add_channel(db_path, "webhook", endpoint="https://example.com")

        with patch.object(h, "_dispatch", return_value=False):
            ok, msg = h.handle("send", ["webhook", "Testmsg"])

        assert ok is True
        assert "QUEUED" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT content, processed FROM connector_messages").fetchone()
        conn.close()
        assert row[0] == "Testmsg"
        assert row[1] == 0

    def test_send_success_updates_counters(self, notify_env):
        h, _, db_path = notify_env
        _add_channel(db_path, "discord", endpoint="https://discord.webhook")

        with patch.object(h, "_dispatch", return_value=True):
            ok, msg = h.handle("send", ["discord", "Erfolg!"])

        assert ok is True
        assert "gesendet" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT success_count FROM connections WHERE name='notify_discord'").fetchone()
        msg_row = conn.execute("SELECT processed FROM connector_messages").fetchone()
        conn.close()
        assert row[0] == 1
        assert msg_row[0] == 1


class TestSetup:
    def test_setup_no_args(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("setup", [])
        assert ok is False
        assert "Verwendung" in msg

    def test_setup_unknown_channel(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("setup", ["fax"])
        assert ok is False
        assert "Unbekannter Channel" in msg

    def test_setup_dry_run(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("setup", ["telegram"], dry_run=True)
        assert ok is True
        assert "DRY" in msg

    def test_setup_creates_channel(self, notify_env):
        h, _, db_path = notify_env
        ok, msg = h.handle(
            "setup",
            ["discord", "https://discord.webhook", "--token-ref=notify_discord_token"],
        )
        assert ok is True
        assert "konfiguriert" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT endpoint, auth_config FROM connections WHERE name='notify_discord'").fetchone()
        conn.close()
        assert row[0] == "https://discord.webhook"
        auth = json.loads(row[1])
        assert auth["_secret_refs"]["token"] == "notify_discord_token"

    def test_setup_rejects_secret_in_process_arguments(self, notify_env):
        h, _, db_path = notify_env

        ok, msg = h.handle("setup", ["telegram", "--token=abc123"])

        assert ok is False
        assert "Prozessargumente" in msg
        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM connections WHERE auth_config LIKE '%abc123%'"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_setup_upserts_existing(self, notify_env):
        h, _, db_path = notify_env
        _add_channel(db_path, "slack", endpoint="https://old-webhook")

        ok, msg = h.handle("setup", ["slack", "https://new-webhook"])
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT endpoint FROM connections WHERE name='notify_slack'").fetchone()
        conn.close()
        assert row[0] == "https://new-webhook"

    def test_setup_email_with_token_and_email(self, notify_env):
        h, _, db_path = notify_env
        ok, msg = h.handle(
            "setup",
            [
                "email", "smtp.gmail.com", "--token-ref=notify_email_password",
                "--email=user@test.com",
            ],
        )
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT auth_config FROM connections WHERE name='notify_email'").fetchone()
        conn.close()
        auth = json.loads(row[0])
        assert auth["_secret_refs"]["token"] == "notify_email_password"
        assert auth["email"] == "user@test.com"


class TestTest:
    def test_test_no_args(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("test", [])
        assert ok is False
        assert "Verwendung" in msg

    def test_test_delegates_to_send(self, notify_env):
        h, _, db_path = notify_env
        _add_channel(db_path, "telegram")

        with patch.object(h, "_dispatch", return_value=False):
            ok, msg = h.handle("test", ["telegram"])
        assert ok is True


class TestList:
    def test_list_empty(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("list", [])
        assert ok is True
        assert "Keine" in msg

    def test_list_with_channels(self, notify_env):
        h, _, db_path = notify_env
        _add_channel(db_path, "telegram", endpoint="bot")
        _add_channel(db_path, "discord", endpoint="webhook")

        ok, msg = h.handle("list", [])
        assert ok is True
        assert "2" in msg
        assert "telegram" in msg
        assert "discord" in msg


class TestStatus:
    def test_status_aliases_list(self, notify_env):
        h, _, _ = notify_env
        ok1, msg1 = h.handle("list", [])
        ok2, msg2 = h.handle("status", [])
        assert ok1 == ok2
        assert msg1 == msg2


class TestHistory:
    def test_history_empty(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("history", [])
        assert ok is True
        assert "Keine" in msg

    def test_history_shows_messages(self, notify_env):
        h, _, db_path = notify_env
        conn = sqlite3.connect(str(db_path))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO connector_messages (connector_name, direction, sender, recipient, content, processed, created_at)
            VALUES (?, 'out', 'bach', 'webhook', ?, 1, ?)
        """, ("notify_webhook", "Test-Nachricht", now))
        conn.commit()
        conn.close()

        ok, msg = h.handle("history", [])
        assert ok is True
        assert "Test-Nachricht" in msg
        assert "gesendet" in msg

    def test_history_limit(self, notify_env):
        h, _, db_path = notify_env
        conn = sqlite3.connect(str(db_path))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for i in range(5):
            conn.execute("""
                INSERT INTO connector_messages (connector_name, direction, sender, recipient, content, processed, created_at)
                VALUES (?, 'out', 'bach', 'x', ?, 0, ?)
            """, ("notify_webhook", f"msg_{i}", now))
        conn.commit()
        conn.close()

        ok, msg = h.handle("history", ["--limit", "2"])
        assert ok is True
        assert "(2)" in msg


class TestHelp:
    def test_help_content(self, notify_env):
        h, _, _ = notify_env
        ok, msg = h.handle("help", [])
        assert ok is True
        assert "discord" in msg
        assert "telegram" in msg
        assert "Setup:" in msg


class TestDispatch:
    def test_dispatch_telegram(self, notify_env):
        h, _, _ = notify_env
        with patch.object(h, "_send_telegram", return_value=True) as mock:
            result = h._dispatch("telegram", "", '{"token":"x"}', "test")
        assert result is True
        mock.assert_called_once()

    def test_dispatch_webhook(self, notify_env):
        h, _, _ = notify_env
        with patch.object(h, "_send_webhook", return_value=True) as mock:
            result = h._dispatch("webhook", "https://example.com", "", "test")
        assert result is True

    def test_dispatch_discord(self, notify_env):
        h, _, _ = notify_env
        with patch.object(h, "_send_discord_webhook", return_value=True) as mock:
            result = h._dispatch("discord", "https://discord.webhook", "", "test")
        assert result is True

    def test_dispatch_slack(self, notify_env):
        h, _, _ = notify_env
        with patch.object(h, "_send_slack", return_value=True) as mock:
            result = h._dispatch("slack", "https://slack.webhook", "", "test")
        assert result is True

    def test_dispatch_unknown_returns_false(self, notify_env):
        h, _, _ = notify_env
        result = h._dispatch("carrier_pigeon", "", "", "test")
        assert result is False

    def test_dispatch_exception_returns_false(self, notify_env):
        h, _, _ = notify_env
        with patch.object(h, "_send_telegram", side_effect=RuntimeError("boom")):
            result = h._dispatch("telegram", "", "", "test")
        assert result is False


class TestSenderTag:
    def test_no_tag_returns_empty(self, notify_env):
        h, _, _ = notify_env
        assert h._get_sender_tag("telegram") == ""

    def test_tag_from_config(self, notify_env):
        h, _, db_path = notify_env
        auth = json.dumps({"sender_tag": "BACH-BOT"})
        _add_channel(db_path, "telegram", auth_config=auth)

        tag = h._get_sender_tag("telegram")
        assert tag == "BACH-BOT"

    def test_tag_text_prepends(self, notify_env):
        h, _, db_path = notify_env
        auth = json.dumps({"sender_tag": "SYS"})
        _add_channel(db_path, "webhook", auth_config=auth)

        result = h._tag_text("Hello", "webhook")
        assert result == "[SYS] Hello"

    def test_tag_text_no_tag(self, notify_env):
        h, _, _ = notify_env
        result = h._tag_text("Hello", "webhook")
        assert result == "Hello"


class TestSecretRefs:
    def test_plaintext_fallback_is_ignored(self, notify_env):
        h, _, _ = notify_env
        result = h._resolve_secret_refs('{"token":"plaintext","email":"user@test.com"}')
        assert result == {"email": "user@test.com"}

    def test_keyring_reference_is_resolved(self, notify_env):
        h, _, _ = notify_env
        with patch("hub.secrets_handler.get_secret_value", return_value="from-keyring"):
            result = h._resolve_secret_refs(
                '{"_secret_refs":{"token":"notify_email_password"},"email":"user@test.com"}'
            )
        assert result == {"token": "from-keyring", "email": "user@test.com"}

    def test_telegram_uses_canonical_connector(self, notify_env):
        h, _, _ = notify_env
        connector = MagicMock()
        connector.send_message.return_value = True
        with patch(
            "hub.connector.ConnectorHandler._instantiate",
            return_value=(connector, ""),
        ):
            assert h._send_telegram("Hallo", '{"token":"plaintext"}') is True
        connector.send_message.assert_called_once_with("", "Hallo")
        connector.disconnect.assert_called_once()
