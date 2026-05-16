# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the BACH ConnectorHandler — CRUD, polling, dispatch, routing, queue management."""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.connector import ConnectorHandler


# ===================================================================
# FIXTURES
# ===================================================================

def _create_db(db_path: Path):
    """Create minimal schema for connections + connector_messages + messages."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE connections (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,
            category TEXT,
            endpoint TEXT,
            auth_type TEXT,
            auth_config TEXT,
            is_active INTEGER DEFAULT 1,
            last_used TEXT,
            success_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE connector_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector_name TEXT NOT NULL,
            direction TEXT NOT NULL,
            sender TEXT,
            recipient TEXT,
            content TEXT,
            processed INTEGER DEFAULT 0,
            error TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT,
            body TEXT NOT NULL,
            body_type TEXT DEFAULT 'text',
            status TEXT DEFAULT 'unread',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE secrets (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def handler(tmp_path):
    """ConnectorHandler with empty DB."""
    system_dir = tmp_path / "system"
    system_dir.mkdir()
    data_dir = system_dir / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    _create_db(db_path)
    return ConnectorHandler(system_dir)


@pytest.fixture
def handler_with_connector(handler):
    """Handler with one telegram connector pre-registered."""
    conn = sqlite3.connect(str(handler.db_path))
    conn.execute("""
        INSERT INTO connections (name, type, category, endpoint, auth_type, auth_config, is_active, created_at)
        VALUES ('tg_main', 'telegram', 'connector', '', 'api_key',
                '{"bot_token": "test:TOKEN", "owner_chat_id": "12345"}', 1, '2026-01-01 00:00:00')
    """)
    conn.commit()
    conn.close()
    return handler


@pytest.fixture
def handler_with_messages(handler_with_connector):
    """Handler with connector + some messages in DB."""
    h = handler_with_connector
    conn = sqlite3.connect(str(h.db_path))
    conn.executescript("""
        INSERT INTO connector_messages (connector_name, direction, sender, recipient, content, processed, created_at)
        VALUES ('tg_main', 'in', 'user123', '', 'Hallo BACH', 0, '2026-01-01 10:00:00');
        INSERT INTO connector_messages (connector_name, direction, sender, recipient, content, processed, created_at)
        VALUES ('tg_main', 'in', 'user456', '', 'Zweite Nachricht', 0, '2026-01-01 10:01:00');
        INSERT INTO connector_messages (connector_name, direction, sender, recipient, content, processed, created_at)
        VALUES ('tg_main', 'out', 'bach', 'user123', 'Antwort', 0, '2026-01-01 10:02:00');
        INSERT INTO connector_messages (connector_name, direction, sender, recipient, content, processed, created_at)
        VALUES ('tg_main', 'in', 'user789', '', 'Alte Nachricht', 1, '2026-01-01 09:00:00');
    """)
    conn.commit()
    conn.close()
    return h


# ===================================================================
# BASIC PROPERTIES
# ===================================================================

class TestConnectorHandlerInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "connector"

    def test_target_file_is_db(self, handler):
        assert handler.target_file == handler.db_path

    def test_supported_types(self, handler):
        assert "telegram" in handler.SUPPORTED_TYPES
        assert "discord" in handler.SUPPORTED_TYPES
        assert "homeassistant" in handler.SUPPORTED_TYPES

    def test_get_operations_returns_dict(self, handler):
        ops = handler.get_operations()
        assert isinstance(ops, dict)
        assert "list" in ops
        assert "poll" in ops
        assert "dispatch" in ops

    def test_handle_unknown_operation(self, handler):
        ok, msg = handler.handle("nonexistent", [])
        assert not ok
        assert "Unbekannte Operation" in msg


# ===================================================================
# LIST + STATUS
# ===================================================================

class TestList:
    def test_empty_list(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "Keine Connectors" in msg

    def test_list_with_connector(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("list", [])
        assert ok
        assert "tg_main" in msg
        assert "telegram" in msg
        assert "aktiv" in msg


class TestStatus:
    def test_status_empty(self, handler):
        ok, msg = handler.handle("status", [])
        assert ok
        assert "Aktive Connectors: 0" in msg

    def test_status_with_connector_and_messages(self, handler_with_messages):
        ok, msg = handler_with_messages.handle("status", [])
        assert ok
        assert "Aktive Connectors: 1" in msg
        assert "tg_main" in msg
        assert "Unverarbeitete Nachrichten" in msg


# ===================================================================
# ADD / REMOVE / ENABLE / DISABLE
# ===================================================================

class TestAdd:
    def test_add_success(self, handler):
        ok, msg = handler.handle("add", ["telegram", "my_bot"])
        assert ok
        assert "registriert" in msg

    def test_add_with_endpoint(self, handler):
        ok, msg = handler.handle("add", ["webhook", "wh_test", "https://example.com"])
        assert ok
        # Verify in DB
        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT endpoint FROM connections WHERE name='wh_test'").fetchone()
        conn.close()
        assert row[0] == "https://example.com"

    def test_add_invalid_type(self, handler):
        ok, msg = handler.handle("add", ["fax", "old_school"])
        assert not ok
        assert "Unbekannter Typ" in msg

    def test_add_missing_args(self, handler):
        ok, msg = handler.handle("add", ["telegram"])
        assert not ok
        assert "Verwendung" in msg

    def test_add_duplicate(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("add", ["telegram", "tg_main"])
        assert not ok
        assert "existiert bereits" in msg

    def test_add_dry_run(self, handler):
        ok, msg = handler.handle("add", ["telegram", "test_bot"], dry_run=True)
        assert ok
        assert "[DRY]" in msg
        # Not actually in DB
        conn = sqlite3.connect(str(handler.db_path))
        row = conn.execute("SELECT * FROM connections WHERE name='test_bot'").fetchone()
        conn.close()
        assert row is None


class TestRemove:
    def test_remove_success(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("remove", ["tg_main"])
        assert ok
        assert "entfernt" in msg

    def test_remove_not_found(self, handler):
        ok, msg = handler.handle("remove", ["ghost"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_remove_no_args(self, handler):
        ok, msg = handler.handle("remove", [])
        assert not ok
        assert "Verwendung" in msg

    def test_remove_dry_run(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("remove", ["tg_main"], dry_run=True)
        assert ok
        assert "[DRY]" in msg


class TestEnableDisable:
    def test_enable_already_active(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("enable", ["tg_main"])
        assert ok
        assert "aktiviert" in msg

    def test_disable(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("disable", ["tg_main"])
        assert ok
        assert "deaktiviert" in msg
        # Verify in DB
        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute("SELECT is_active FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        assert row[0] == 0

    def test_enable_after_disable(self, handler_with_connector):
        handler_with_connector.handle("disable", ["tg_main"])
        ok, msg = handler_with_connector.handle("enable", ["tg_main"])
        assert ok
        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute("SELECT is_active FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        assert row[0] == 1

    def test_toggle_not_found(self, handler):
        ok, msg = handler.handle("enable", ["ghost"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_toggle_no_args(self, handler):
        ok, msg = handler.handle("disable", [])
        assert not ok
        assert "Verwendung" in msg


# ===================================================================
# MESSAGES + UNPROCESSED
# ===================================================================

class TestMessages:
    def test_messages_empty(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("messages", [])
        assert ok
        assert "Keine Nachrichten" in msg

    def test_messages_with_data(self, handler_with_messages):
        ok, msg = handler_with_messages.handle("messages", [])
        assert ok
        assert "Hallo BACH" in msg or "Connector-Nachrichten" in msg

    def test_messages_filtered_by_connector(self, handler_with_messages):
        ok, msg = handler_with_messages.handle("messages", ["tg_main"])
        assert ok
        assert "tg_main" in msg

    def test_messages_with_limit(self, handler_with_messages):
        ok, msg = handler_with_messages.handle("messages", ["--limit", "2"])
        assert ok
        assert "Connector-Nachrichten (2)" in msg

    def test_messages_invalid_limit(self, handler_with_messages):
        ok, msg = handler_with_messages.handle("messages", ["--limit", "abc"])
        assert not ok
        assert "Ungueltige Zahl" in msg


class TestUnprocessed:
    def test_unprocessed_empty(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("unprocessed", [])
        assert ok
        assert "Keine unverarbeiteten" in msg

    def test_unprocessed_shows_sender(self, handler_with_messages):
        """Bug fix verification: _unprocessed should show sender (r[3]), not direction (r[2])."""
        ok, msg = handler_with_messages.handle("unprocessed", [])
        assert ok
        assert "user123" in msg
        assert "user456" in msg
        # direction 'in' should NOT appear as the sender label
        assert "von in:" not in msg


# ===================================================================
# ROUTE
# ===================================================================

class TestRoute:
    def test_route_no_messages(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("route", [])
        assert ok
        assert "Keine Nachrichten zum Routen" in msg

    def test_route_processes_messages(self, handler_with_messages):
        ok, msg = handler_with_messages.handle("route", [])
        assert ok
        assert "geroutet" in msg
        # The 2 unprocessed 'in' messages should be routed, the 'out' should not
        assert "2/2" in msg or "Nachrichten geroutet" in msg

    def test_route_marks_processed(self, handler_with_messages):
        handler_with_messages.handle("route", [])
        conn = sqlite3.connect(str(handler_with_messages.db_path))
        unproc = conn.execute(
            "SELECT COUNT(*) FROM connector_messages WHERE processed=0 AND direction='in'"
        ).fetchone()[0]
        conn.close()
        assert unproc == 0

    def test_route_creates_inbox_messages(self, handler_with_messages):
        handler_with_messages.handle("route", [])
        conn = sqlite3.connect(str(handler_with_messages.db_path))
        inbox = conn.execute("SELECT COUNT(*) FROM messages WHERE direction='inbox'").fetchone()[0]
        conn.close()
        assert inbox == 2

    def test_route_duplicate_detection(self, handler_with_messages):
        handler_with_messages.handle("route", [])
        # Reset processed flags to simulate re-route
        conn = sqlite3.connect(str(handler_with_messages.db_path))
        conn.execute("UPDATE connector_messages SET processed=0 WHERE direction='in'")
        conn.commit()
        conn.close()
        ok, msg = handler_with_messages.handle("route", [])
        assert ok
        assert "Duplikate" in msg

    def test_route_dry_run(self, handler_with_messages):
        ok, msg = handler_with_messages.handle("route", [], dry_run=True)
        assert ok
        assert "[DRY]" in msg
        # Nothing should be modified
        conn = sqlite3.connect(str(handler_with_messages.db_path))
        unproc = conn.execute(
            "SELECT COUNT(*) FROM connector_messages WHERE processed=0 AND direction='in'"
        ).fetchone()[0]
        conn.close()
        assert unproc == 2


# ===================================================================
# SEND (Queue-based)
# ===================================================================

class TestSend:
    def test_send_queues_message(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("send", ["tg_main", "user123", "Hallo", "Welt"])
        assert ok
        assert "Queue" in msg
        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute(
            "SELECT direction, content FROM connector_messages WHERE connector_name='tg_main' AND direction='out'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[1] == "Hallo Welt"

    def test_send_missing_args(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("send", ["tg_main", "user123"])
        assert not ok
        assert "Verwendung" in msg

    def test_send_connector_not_found(self, handler):
        ok, msg = handler.handle("send", ["ghost", "user", "hello"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_send_connector_disabled(self, handler_with_connector):
        handler_with_connector.handle("disable", ["tg_main"])
        ok, msg = handler_with_connector.handle("send", ["tg_main", "user123", "test"])
        assert not ok
        assert "deaktiviert" in msg

    def test_send_dry_run(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("send", ["tg_main", "user123", "test"], dry_run=True)
        assert ok
        assert "[DRY]" in msg


# ===================================================================
# CONFIGURE
# ===================================================================

class TestConfigure:
    def test_configure_sets_value(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("configure", ["tg_main", "sender_tag", "BACH"])
        assert ok
        assert "BACH" in msg
        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute("SELECT auth_config FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        data = json.loads(row[0])
        assert data["sender_tag"] == "BACH"

    def test_configure_bool_conversion(self, handler_with_connector):
        handler_with_connector.handle("configure", ["tg_main", "debug", "true"])
        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute("SELECT auth_config FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        data = json.loads(row[0])
        assert data["debug"] is True

    def test_configure_int_conversion(self, handler_with_connector):
        handler_with_connector.handle("configure", ["tg_main", "timeout", "30"])
        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute("SELECT auth_config FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        data = json.loads(row[0])
        assert data["timeout"] == 30

    def test_configure_missing_args(self, handler):
        ok, msg = handler.handle("configure", ["tg_main", "key"])
        assert not ok
        assert "Verwendung" in msg

    def test_configure_not_found(self, handler):
        ok, msg = handler.handle("configure", ["ghost", "key", "val"])
        assert not ok
        assert "nicht gefunden" in msg


# ===================================================================
# INSTANTIATE
# ===================================================================

class TestInstantiate:
    def test_instantiate_not_found(self, handler):
        instance, err = handler._instantiate("ghost")
        assert instance is None
        assert "nicht gefunden" in err

    def test_instantiate_disabled(self, handler_with_connector):
        handler_with_connector.handle("disable", ["tg_main"])
        instance, err = handler_with_connector._instantiate("tg_main")
        assert instance is None
        assert "deaktiviert" in err

    def test_instantiate_telegram(self, handler_with_connector):
        instance, err = handler_with_connector._instantiate("tg_main")
        assert instance is not None
        assert err == ""
        from connectors.telegram_connector import TelegramConnector
        assert isinstance(instance, TelegramConnector)

    def test_instantiate_discord(self, handler):
        handler.handle("add", ["discord", "dc_bot"])
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute(
            "UPDATE connections SET auth_config = ? WHERE name = 'dc_bot'",
            (json.dumps({"bot_token": "test", "mode": "bot"}),))
        conn.commit()
        conn.close()
        instance, err = handler._instantiate("dc_bot")
        assert instance is not None
        from connectors.discord_connector import DiscordConnector
        assert isinstance(instance, DiscordConnector)

    def test_instantiate_secret_ref(self, handler):
        handler.handle("add", ["telegram", "tg_secret"])
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("INSERT INTO secrets (key, value) VALUES ('tg_tok', 'resolved:TOKEN')")
        conn.execute(
            "UPDATE connections SET auth_config = ? WHERE name = 'tg_secret'",
            (json.dumps({"_secret_refs": {"bot_token": "tg_tok"}, "owner_chat_id": "999"}),))
        conn.commit()
        conn.close()
        instance, err = handler._instantiate("tg_secret")
        assert instance is not None
        assert instance._bot_token == "resolved:TOKEN"

    def test_instantiate_unknown_type(self, handler):
        conn = sqlite3.connect(str(handler.db_path))
        conn.execute("""
            INSERT INTO connections (name, type, category, is_active, created_at)
            VALUES ('custom', 'ftp', 'connector', 1, '2026-01-01')
        """)
        conn.commit()
        conn.close()
        instance, err = handler._instantiate("custom")
        assert instance is None
        assert "Kein Runtime-Adapter" in err


# ===================================================================
# POLL (with mocked connector)
# ===================================================================

class TestPoll:
    def test_poll_no_args(self, handler):
        ok, msg = handler.handle("poll", [])
        assert not ok
        assert "Verwendung" in msg

    def test_poll_dry_run(self, handler):
        ok, msg = handler.handle("poll", ["tg_main"], dry_run=True)
        assert ok
        assert "[DRY]" in msg

    def test_poll_connector_not_found(self, handler):
        ok, msg = handler.handle("poll", ["ghost"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_poll_no_new_messages(self, handler_with_connector):
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        mock_instance.get_messages.return_value = []
        with patch.object(handler_with_connector, '_instantiate', return_value=(mock_instance, "")):
            ok, msg = handler_with_connector.handle("poll", ["tg_main"])
        assert ok
        assert "Keine neuen Nachrichten" in msg
        mock_instance.disconnect.assert_called_once()

    def test_poll_stores_messages(self, handler_with_connector):
        from connectors.base import Message
        msgs = [
            Message(channel="telegram", sender="u1", content="Test1",
                    timestamp="2026-01-01T12:00:00", direction="in"),
            Message(channel="telegram", sender="u2", content="Test2",
                    timestamp="2026-01-01T12:00:01", direction="in"),
        ]
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        mock_instance.get_messages.return_value = msgs
        mock_instance._last_update_id = 0

        with patch.object(handler_with_connector, '_instantiate', return_value=(mock_instance, "")):
            ok, msg = handler_with_connector.handle("poll", ["tg_main"])

        assert ok
        assert "2 Nachrichten gespeichert" in msg

        conn = sqlite3.connect(str(handler_with_connector.db_path))
        count = conn.execute("SELECT COUNT(*) FROM connector_messages").fetchone()[0]
        conn.close()
        assert count == 2

    def test_poll_connect_failure(self, handler_with_connector):
        mock_instance = MagicMock()
        mock_instance.connect.return_value = False
        with patch.object(handler_with_connector, '_instantiate', return_value=(mock_instance, "")):
            ok, msg = handler_with_connector.handle("poll", ["tg_main"])
        assert not ok
        assert "konnte nicht verbinden" in msg

    def test_poll_updates_success_count(self, handler_with_connector):
        from connectors.base import Message
        msgs = [Message(channel="t", sender="s", content="c", timestamp="t", direction="in")]
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        mock_instance.get_messages.return_value = msgs
        mock_instance._last_update_id = 0

        with patch.object(handler_with_connector, '_instantiate', return_value=(mock_instance, "")):
            handler_with_connector.handle("poll", ["tg_main"])

        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute("SELECT success_count FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        assert row[0] == 1

    def test_poll_saves_last_update_id(self, handler_with_connector):
        from connectors.base import Message
        msgs = [Message(channel="t", sender="s", content="c", timestamp="t", direction="in")]
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        mock_instance.get_messages.return_value = msgs
        mock_instance._last_update_id = 42

        with patch.object(handler_with_connector, '_instantiate', return_value=(mock_instance, "")):
            handler_with_connector.handle("poll", ["tg_main"])

        conn = sqlite3.connect(str(handler_with_connector.db_path))
        row = conn.execute("SELECT auth_config FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        data = json.loads(row[0])
        assert data["last_update_id"] == 42


# ===================================================================
# DISPATCH (with mocked connector)
# ===================================================================

class TestDispatch:
    def test_dispatch_no_args(self, handler):
        ok, msg = handler.handle("dispatch", [])
        assert not ok
        assert "Verwendung" in msg

    def test_dispatch_empty_queue(self, handler_with_connector):
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        with patch.object(handler_with_connector, '_instantiate', return_value=(mock_instance, "")):
            ok, msg = handler_with_connector.handle("dispatch", ["tg_main"])
        assert ok
        assert "Keine ausgehenden" in msg

    def test_dispatch_sends_messages(self, handler_with_messages):
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        mock_instance.send_message.return_value = True

        with patch.object(handler_with_messages, '_instantiate', return_value=(mock_instance, "")):
            ok, msg = handler_with_messages.handle("dispatch", ["tg_main"])

        assert ok
        assert "1 gesendet" in msg
        mock_instance.send_message.assert_called_once_with("user123", "Antwort")

    def test_dispatch_handles_send_failure(self, handler_with_messages):
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        mock_instance.send_message.return_value = False

        with patch.object(handler_with_messages, '_instantiate', return_value=(mock_instance, "")):
            ok, msg = handler_with_messages.handle("dispatch", ["tg_main"])

        assert ok
        assert "1 Fehler" in msg

    def test_dispatch_updates_counters(self, handler_with_messages):
        mock_instance = MagicMock()
        mock_instance.connect.return_value = True
        mock_instance.send_message.return_value = True

        with patch.object(handler_with_messages, '_instantiate', return_value=(mock_instance, "")):
            handler_with_messages.handle("dispatch", ["tg_main"])

        conn = sqlite3.connect(str(handler_with_messages.db_path))
        row = conn.execute("SELECT success_count FROM connections WHERE name='tg_main'").fetchone()
        conn.close()
        assert row[0] == 1


# ===================================================================
# SEND-FILE
# ===================================================================

class TestSendFile:
    def test_send_file_missing_args(self, handler):
        ok, msg = handler.handle("send-file", ["tg_main", "user123"])
        assert not ok
        assert "Verwendung" in msg

    def test_send_file_not_found(self, handler_with_connector):
        ok, msg = handler_with_connector.handle("send-file", ["tg_main", "user123", "/nonexistent.jpg"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_send_file_dry_run(self, handler_with_connector, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        ok, msg = handler_with_connector.handle("send-file", ["tg_main", "user123", str(f)], dry_run=True)
        assert ok
        assert "[DRY]" in msg

    def test_send_file_no_send_file_method(self, handler_with_connector, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        mock_instance = MagicMock(spec=["connect", "disconnect", "send_message"])
        mock_instance.connect.return_value = True
        mock_instance.send_message.return_value = True

        with patch.object(handler_with_connector, '_instantiate', return_value=(mock_instance, "")):
            ok, msg = handler_with_connector.handle(
                "send-file", ["tg_main", "user123", str(f), "--caption", "Mein Bild"])

        assert ok
        assert "nicht unterstuetzt" in msg
        mock_instance.send_message.assert_called_once_with("user123", "Mein Bild")


# ===================================================================
# HELP
# ===================================================================

class TestHelp:
    def test_help_returns_text(self, handler):
        ok, msg = handler.handle("help", [])
        assert ok
        assert "Connector-System" in msg
        assert "poll" in msg
        assert "dispatch" in msg
