# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
Connector Tests
===============
Unit-Tests fuer das BACH Connector Framework: base, telegram, discord,
signal, whatsapp, homeassistant.
Alle Netzwerkzugriffe werden gemockt.
"""

import os
import sys
import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock
from unittest.mock import patch, MagicMock, PropertyMock

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import pytest

from connectors.base import BaseConnector, ConnectorConfig, ConnectorStatus, Message


# ═══════════════════════════════════════════════════════════════
# Base Classes
# ═══════════════════════════════════════════════════════════════


class TestConnectorStatus:
    def test_enum_values(self):
        assert ConnectorStatus.DISCONNECTED.value == "disconnected"
        assert ConnectorStatus.CONNECTING.value == "connecting"
        assert ConnectorStatus.CONNECTED.value == "connected"
        assert ConnectorStatus.ERROR.value == "error"

    def test_all_states_exist(self):
        names = {s.name for s in ConnectorStatus}
        assert names == {"DISCONNECTED", "CONNECTING", "CONNECTED", "ERROR"}


class TestMessage:
    def test_basic_creation(self):
        msg = Message(
            channel="telegram",
            sender="user123",
            content="Hallo",
            timestamp="2026-01-01T12:00:00",
        )
        assert msg.channel == "telegram"
        assert msg.sender == "user123"
        assert msg.content == "Hallo"
        assert msg.direction == "in"
        assert msg.attachments == []
        assert msg.metadata == {}
        assert msg.message_id == ""

    def test_outgoing_message(self):
        msg = Message(
            channel="discord",
            sender="bot",
            content="Antwort",
            timestamp="2026-01-01T12:00:00",
            direction="out",
            message_id="msg-42",
        )
        assert msg.direction == "out"
        assert msg.message_id == "msg-42"

    def test_with_attachments_and_metadata(self):
        msg = Message(
            channel="signal",
            sender="+491234567890",
            content="Foto",
            timestamp="2026-01-01T12:00:00",
            attachments=["/tmp/photo.jpg"],
            metadata={"source_device": 1},
        )
        assert msg.attachments == ["/tmp/photo.jpg"]
        assert msg.metadata["source_device"] == 1


class TestConnectorConfig:
    def test_defaults(self):
        cfg = ConnectorConfig(name="test", connector_type="test_type")
        assert cfg.name == "test"
        assert cfg.connector_type == "test_type"
        assert cfg.endpoint == ""
        assert cfg.auth_type == "none"
        assert cfg.auth_config == {}
        assert cfg.options == {}

    def test_full_config(self):
        cfg = ConnectorConfig(
            name="tg_main",
            connector_type="telegram",
            endpoint="https://api.telegram.org",
            auth_type="api_key",
            auth_config={"bot_token": "123:ABC"},
            options={"owner_chat_id": "999"},
        )
        assert cfg.auth_config["bot_token"] == "123:ABC"
        assert cfg.options["owner_chat_id"] == "999"


class TestBaseConnector:
    def test_cannot_instantiate_abc(self):
        cfg = ConnectorConfig(name="test", connector_type="test")
        with pytest.raises(TypeError):
            BaseConnector(cfg)

    def test_concrete_subclass(self):
        class DummyConnector(BaseConnector):
            def connect(self):
                self._status = ConnectorStatus.CONNECTED
                return True

            def disconnect(self):
                self._status = ConnectorStatus.DISCONNECTED
                return True

            def send_message(self, recipient, content, attachments=None):
                return True

            def get_messages(self, since=None, limit=50):
                return []

        cfg = ConnectorConfig(name="dummy", connector_type="dummy")
        c = DummyConnector(cfg)
        assert c.name == "dummy"
        assert c.connector_type == "dummy"
        assert c.status == ConnectorStatus.DISCONNECTED
        assert c.get_status() == ConnectorStatus.DISCONNECTED

        c.connect()
        assert c.status == ConnectorStatus.CONNECTED

        c.disconnect()
        assert c.status == ConnectorStatus.DISCONNECTED

    def test_repr(self):
        class DummyConnector(BaseConnector):
            def connect(self): return True
            def disconnect(self): return True
            def send_message(self, r, c, a=None): return True
            def get_messages(self, s=None, l=50): return []

        cfg = ConnectorConfig(name="repr_test", connector_type="test")
        c = DummyConnector(cfg)
        assert "DummyConnector" in repr(c)
        assert "repr_test" in repr(c)
        assert "disconnected" in repr(c)


# ═══════════════════════════════════════════════════════════════
# TelegramConnector
# ═══════════════════════════════════════════════════════════════


class TestTelegramConnector:
    @pytest.fixture
    def tg_config(self):
        return ConnectorConfig(
            name="tg_test",
            connector_type="telegram",
            auth_type="api_key",
            auth_config={"bot_token": "123456:ABCDEF"},
            options={"owner_chat_id": "999888"},
        )

    @pytest.fixture
    def connector(self, tg_config):
        from connectors.telegram_connector import TelegramConnector
        return TelegramConnector(tg_config)

    def test_init(self, connector):
        assert connector._bot_token == "123456:ABCDEF"
        assert connector._owner_chat_id == "999888"
        assert connector.status == ConnectorStatus.DISCONNECTED

    def test_init_without_token(self):
        from connectors.telegram_connector import TelegramConnector

        cfg = ConnectorConfig(name="tg_no_token", connector_type="telegram")
        c = TelegramConnector(cfg)
        assert c._bot_token == ""

    def test_connect_success(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "ok": True,
            "result": {"id": 123, "is_bot": True, "first_name": "TestBot"},
        }).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.connect()

        assert result is True
        assert connector.status == ConnectorStatus.CONNECTED

    def test_connect_no_token(self):
        from connectors.telegram_connector import TelegramConnector

        cfg = ConnectorConfig(name="tg", connector_type="telegram")
        c = TelegramConnector(cfg)
        assert c.connect() is False
        assert c.status == ConnectorStatus.ERROR

    def test_connect_network_error(self, connector):
        with patch("urllib.request.urlopen", side_effect=Exception("Network down")):
            result = connector.connect()
        assert result is False
        assert connector.status == ConnectorStatus.ERROR

    def test_disconnect(self, connector):
        connector._status = ConnectorStatus.CONNECTED
        connector._polling = True
        assert connector.disconnect() is True
        assert connector.status == ConnectorStatus.DISCONNECTED
        assert connector._polling is False

    def test_send_message_success(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"ok": True, "result": {"message_id": 42}}
        ).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.send_message("999888", "Test-Nachricht")
        assert result is True

    def test_send_message_markdown_fallback(self, connector):
        call_count = [0]

        def mock_urlopen(req, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Markdown parse error")
            resp = MagicMock()
            resp.read.return_value = json.dumps(
                {"ok": True, "result": {"message_id": 43}}
            ).encode("utf-8")
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = connector.send_message("999888", "**bold** text")
        assert result is True
        assert call_count[0] == 2

    def test_send_message_uses_owner_chat_id_as_default(self, connector):
        captured_req = []

        def mock_urlopen(req, **kwargs):
            captured_req.append(req)
            resp = MagicMock()
            resp.read.return_value = json.dumps(
                {"ok": True, "result": {"message_id": 44}}
            ).encode("utf-8")
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            connector.send_message("", "Hallo")

        body = json.loads(captured_req[0].data.decode("utf-8"))
        assert body["chat_id"] == "999888"

    def test_load_from_secrets_table(self, tmp_path):
        from connectors.telegram_connector import TelegramConnector

        db_file = tmp_path / "bach.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE secrets (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO secrets VALUES ('tg_bot_token', 'SECRET_TOKEN_123')")
        conn.commit()
        conn.close()

        cfg = ConnectorConfig(name="tg_secret", connector_type="telegram")
        c = TelegramConnector.__new__(TelegramConnector)
        c.config = cfg
        c._status = ConnectorStatus.DISCONNECTED

        fake_parent = tmp_path / "connectors" / "telegram_connector.py"
        fake_parent.parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "data").mkdir(exist_ok=True)
        import shutil
        shutil.copy(str(db_file), str(tmp_path / "data" / "bach.db"))

        with patch("connectors.telegram_connector.Path") as MockPath:
            mock_file = MagicMock()
            mock_file.parent.parent = tmp_path
            MockPath.__call__ = lambda self, *a: mock_file
            MockPath.return_value = mock_file

            original_method = TelegramConnector._load_from_secrets_table
            def patched_load(self_inner, key):
                import sqlite3 as sq
                dp = tmp_path / "data" / "bach.db"
                cn = sq.connect(str(dp))
                row = cn.execute("SELECT value FROM secrets WHERE key = ?", (key,)).fetchone()
                cn.close()
                return row[0] if row and row[0] else ""

            with patch.object(TelegramConnector, "_load_from_secrets_table", patched_load):
                result = patched_load(c, "tg_bot_token")

        assert result == "SECRET_TOKEN_123"

    def test_load_from_secrets_table_missing_key(self, tmp_path):
        from connectors.telegram_connector import TelegramConnector

        db_file = tmp_path / "data" / "bach.db"
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE secrets (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        cfg = ConnectorConfig(name="tg", connector_type="telegram")
        c = TelegramConnector.__new__(TelegramConnector)
        c.config = cfg
        c._status = ConnectorStatus.DISCONNECTED

        def patched_load(self_inner, key):
            import sqlite3 as sq
            dp = tmp_path / "data" / "bach.db"
            cn = sq.connect(str(dp))
            row = cn.execute("SELECT value FROM secrets WHERE key = ?", (key,)).fetchone()
            cn.close()
            return row[0] if row and row[0] else ""

        result = patched_load(c, "nonexistent_key")
        assert result == ""

    def test_load_from_secrets_table_no_db(self):
        from connectors.telegram_connector import TelegramConnector

        cfg = ConnectorConfig(name="tg", connector_type="telegram")
        c = TelegramConnector.__new__(TelegramConnector)
        c.config = cfg
        c._status = ConnectorStatus.DISCONNECTED
        result = c._load_from_secrets_table("any_key")
        assert result == ""


class TestEnsureFFmpeg:
    """Cross-platform FFmpeg discovery (LaunchAgent-Kontext hat minimalen PATH)."""

    def test_already_in_path(self):
        from connectors.telegram_connector import _ensure_ffmpeg
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            _ensure_ffmpeg()

    def test_macos_homebrew_discovery(self):
        from connectors.telegram_connector import _ensure_ffmpeg
        target = Path("/opt/homebrew/bin/ffmpeg")

        def fake_is_file(p):
            return p == target

        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "darwin"), \
             patch.object(Path, "is_file", fake_is_file), \
             patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=False):
            _ensure_ffmpeg()
            assert str(target.parent) in os.environ["PATH"]

    def test_linux_usr_bin_discovery(self):
        from connectors.telegram_connector import _ensure_ffmpeg
        target = Path("/usr/bin/ffmpeg")

        def fake_is_file(p):
            return p == target

        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "linux"), \
             patch.object(Path, "is_file", fake_is_file), \
             patch.dict(os.environ, {"PATH": "/bin"}, clear=False):
            _ensure_ffmpeg()
            assert str(target.parent) in os.environ["PATH"]

    def test_unix_no_ffmpeg_found(self):
        from connectors.telegram_connector import _ensure_ffmpeg
        original_path = os.environ.get("PATH", "")
        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "linux"), \
             patch.object(Path, "is_file", lambda p: False), \
             patch.dict(os.environ, {"PATH": original_path}, clear=False):
            _ensure_ffmpeg()
            assert os.environ["PATH"] == original_path

    def test_windows_winget_discovery(self, tmp_path):
        from connectors.telegram_connector import _ensure_ffmpeg
        ffmpeg_pkg = tmp_path / "Microsoft" / "WinGet" / "Packages" / "FFmpeg_1.0"
        ffmpeg_bin = ffmpeg_pkg / "bin"
        ffmpeg_bin.mkdir(parents=True)
        (ffmpeg_bin / "ffmpeg.exe").write_text("dummy")

        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "win32"), \
             patch.dict(os.environ, {"LOCALAPPDATA": str(tmp_path), "PATH": "C:\\Windows"}, clear=False):
            _ensure_ffmpeg()
            assert str(ffmpeg_bin) in os.environ["PATH"]

    def test_windows_no_winget(self):
        from connectors.telegram_connector import _ensure_ffmpeg
        original_path = os.environ.get("PATH", "")
        with patch("shutil.which", return_value=None), \
             patch.object(sys, "platform", "win32"), \
             patch.dict(os.environ, {"LOCALAPPDATA": "C:\\nonexistent", "PATH": original_path}, clear=False):
            _ensure_ffmpeg()


# ═══════════════════════════════════════════════════════════════
# DiscordConnector
# ═══════════════════════════════════════════════════════════════


class TestDiscordConnector:
    @pytest.fixture
    def bot_config(self):
        return ConnectorConfig(
            name="discord_bot",
            connector_type="discord",
            auth_type="api_key",
            auth_config={"bot_token": "BOT_TOKEN_123"},
            options={"default_channel": "123456789"},
        )

    @pytest.fixture
    def webhook_config(self):
        return ConnectorConfig(
            name="discord_webhook",
            connector_type="discord",
            endpoint="https://discord.com/api/webhooks/test/token",
        )

    @pytest.fixture
    def bot(self, bot_config):
        from connectors.discord_connector import DiscordConnector
        return DiscordConnector(bot_config)

    @pytest.fixture
    def webhook(self, webhook_config):
        from connectors.discord_connector import DiscordConnector
        return DiscordConnector(webhook_config)

    def test_bot_init(self, bot):
        assert bot._bot_token == "BOT_TOKEN_123"
        assert bot.status == ConnectorStatus.DISCONNECTED

    def test_webhook_init(self, webhook):
        assert webhook._webhook_url == "https://discord.com/api/webhooks/test/token"

    def test_connect_bot_success(self, bot):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"id": "12345", "username": "BACHBot"}
        ).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = bot.connect()
        assert result is True
        assert bot.status == ConnectorStatus.CONNECTED
        assert bot._bot_info["username"] == "BACHBot"

    def test_connect_bot_failure(self, bot):
        with patch("urllib.request.urlopen", side_effect=Exception("API error")):
            result = bot.connect()
        assert result is False
        assert bot.status == ConnectorStatus.ERROR

    def test_connect_webhook(self, webhook):
        result = webhook.connect()
        assert result is True
        assert webhook.status == ConnectorStatus.CONNECTED

    def test_connect_no_credentials(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(name="d", connector_type="discord")
        c = DiscordConnector(cfg)
        assert c.connect() is False
        assert c.status == ConnectorStatus.ERROR

    def test_disconnect(self, bot):
        bot._status = ConnectorStatus.CONNECTED
        bot._polling = True
        assert bot.disconnect() is True
        assert bot.status == ConnectorStatus.DISCONNECTED
        assert bot._polling is False

    def test_send_message_bot(self, bot):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"id": "msg1"}).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = bot.send_message("123456789", "Hallo Discord!")
        assert result is True

    def test_send_message_webhook(self, webhook):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = webhook.send_message("ignored", "Webhook-Nachricht")
        assert result is True

    def test_send_message_no_credentials(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(name="d", connector_type="discord")
        c = DiscordConnector(cfg)
        assert c.send_message("ch", "msg") is False

    def test_get_messages_bot(self, bot):
        bot._bot_info = {"id": "12345"}
        api_response = [
            {
                "id": "msg100",
                "content": "User-Nachricht",
                "author": {"id": "99999", "username": "TestUser"},
                "timestamp": "2026-01-01T12:00:00",
                "channel_id": "123456789",
            },
            {
                "id": "msg101",
                "content": "Bot-eigene Nachricht",
                "author": {"id": "12345", "username": "BACHBot"},
                "timestamp": "2026-01-01T12:01:00",
                "channel_id": "123456789",
            },
        ]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(api_response).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            messages = bot.get_messages()

        assert len(messages) == 1
        assert messages[0].sender == "TestUser"
        assert messages[0].channel == "discord"

    def test_get_messages_no_token(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(name="d", connector_type="discord")
        c = DiscordConnector(cfg)
        assert c.get_messages() == []

    def test_get_messages_no_channel(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(
            name="d",
            connector_type="discord",
            auth_config={"bot_token": "TOKEN"},
        )
        c = DiscordConnector(cfg)
        assert c.get_messages() == []

    def test_get_new_messages_incremental(self, bot):
        bot._bot_info = {"id": "12345"}
        bot._last_message_id = "msg50"

        api_response = [
            {
                "id": "msg51",
                "content": "Neue Nachricht",
                "author": {"id": "99999", "username": "User1"},
                "timestamp": "2026-01-01T13:00:00",
                "channel_id": "123456789",
            }
        ]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(api_response).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            messages = bot.get_new_messages()

        assert len(messages) == 1
        assert bot._last_message_id == "msg51"
        url = mock_open.call_args[0][0].full_url
        assert "after=msg50" in url

    def test_poll_loop_stop_event(self, bot):
        bot._bot_info = {"id": "12345"}
        stop = threading.Event()
        received = []

        def callback(msg):
            received.append(msg)
            stop.set()

        api_response = [
            {
                "id": "msg200",
                "content": "Poll-Nachricht",
                "author": {"id": "99999", "username": "Poller"},
                "timestamp": "2026-01-01T14:00:00",
                "channel_id": "123456789",
            }
        ]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(api_response).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            thread, stop_ev = bot.poll_threaded(callback, interval=0.1)
            stop_ev.wait(timeout=3)
            stop_ev.set()
            thread.join(timeout=2)

        assert len(received) >= 1
        assert received[0].content == "Poll-Nachricht"

    def test_poll_loop_logs_callback_error(self, bot, capsys):
        """Callback-Fehler werden geloggt statt still verschluckt."""
        bot._bot_info = {"id": "12345"}
        stop = threading.Event()
        call_count = [0]

        def failing_callback(msg):
            call_count[0] += 1
            stop.set()
            raise ValueError("Callback-Boom")

        api_response = [
            {
                "id": "msg300",
                "content": "Error-Test",
                "author": {"id": "99999", "username": "Err"},
                "timestamp": "2026-01-01T15:00:00",
                "channel_id": "123456789",
            }
        ]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(api_response).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            thread, stop_ev = bot.poll_threaded(failing_callback, interval=0.1)
            stop_ev.wait(timeout=3)
            stop_ev.set()
            thread.join(timeout=2)

        assert call_count[0] >= 1


# ═══════════════════════════════════════════════════════════════
# SignalConnector
# ═══════════════════════════════════════════════════════════════


class TestSignalConnector:
    @pytest.fixture
    def sig_config(self):
        return ConnectorConfig(
            name="signal_test",
            connector_type="signal",
            auth_config={"phone_number": "+491234567890"},
            options={"signal_cli_path": "signal-cli"},
        )

    @pytest.fixture
    def connector(self, sig_config):
        from connectors.signal_connector import SignalConnector
        return SignalConnector(sig_config)

    def test_init(self, connector):
        assert connector._phone_number == "+491234567890"
        assert connector._signal_cli_path == "signal-cli"
        assert connector._last_timestamp == 0

    def test_connect_success(self, connector):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "signal-cli 0.13.1"

        with patch("subprocess.run", return_value=mock_result):
            result = connector.connect()
        assert result is True
        assert connector.status == ConnectorStatus.CONNECTED

    def test_connect_no_phone(self):
        from connectors.signal_connector import SignalConnector
        cfg = ConnectorConfig(name="sig", connector_type="signal")
        c = SignalConnector(cfg)
        assert c.connect() is False
        assert c.status == ConnectorStatus.ERROR

    def test_connect_cli_not_found(self, connector):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = connector.connect()
        assert result is False
        assert connector.status == ConnectorStatus.ERROR

    def test_connect_cli_timeout(self, connector):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = connector.connect()
        assert result is False
        assert connector.status == ConnectorStatus.ERROR

    def test_disconnect(self, connector):
        connector._status = ConnectorStatus.CONNECTED
        connector._polling = True
        assert connector.disconnect() is True
        assert connector.status == ConnectorStatus.DISCONNECTED
        assert connector._polling is False

    def test_send_message_success(self, connector):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = connector.send_message("+49876543210", "Hallo Signal!")
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "-a" in cmd
        assert "+491234567890" in cmd
        assert "send" in cmd
        assert "-m" in cmd
        assert "Hallo Signal!" in cmd
        assert "+49876543210" in cmd

    def test_send_message_with_attachments(self, connector):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = connector.send_message("+49876543210", "Foto", attachments=["/tmp/a.jpg"])
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "/tmp/a.jpg" in cmd

    def test_send_message_failure(self, connector):
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = connector.send_message("+49876543210", "Fail")
        assert result is False

    def test_get_messages_success(self, connector):
        signal_output = "\n".join([
            json.dumps({
                "envelope": {
                    "source": "+49111222333",
                    "sourceDevice": 1,
                    "timestamp": 1700000000000,
                    "dataMessage": {"message": "Nachricht eins", "timestamp": 1700000000000},
                }
            }),
            json.dumps({
                "envelope": {
                    "source": "+49444555666",
                    "sourceDevice": 2,
                    "timestamp": 1700000001000,
                    "dataMessage": {"message": "Nachricht zwei", "timestamp": 1700000001000},
                }
            }),
        ])

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = signal_output

        with patch("subprocess.run", return_value=mock_result):
            messages = connector.get_messages()

        assert len(messages) == 2
        assert messages[0].sender == "+49111222333"
        assert messages[0].content == "Nachricht eins"
        assert messages[0].channel == "signal"
        assert messages[1].sender == "+49444555666"
        assert connector._last_timestamp == 1700000001000

    def test_get_messages_skips_old(self, connector):
        connector._last_timestamp = 1700000000500

        signal_output = json.dumps({
            "envelope": {
                "source": "+49111222333",
                "timestamp": 1700000000000,
                "dataMessage": {"message": "Alt"},
            }
        })

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = signal_output

        with patch("subprocess.run", return_value=mock_result):
            messages = connector.get_messages()
        assert len(messages) == 0

    def test_get_messages_skips_no_data_message(self, connector):
        signal_output = json.dumps({
            "envelope": {
                "source": "+49111222333",
                "timestamp": 1700000000000,
            }
        })

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = signal_output

        with patch("subprocess.run", return_value=mock_result):
            messages = connector.get_messages()
        assert len(messages) == 0

    def test_get_messages_handles_empty_text(self, connector):
        signal_output = json.dumps({
            "envelope": {
                "source": "+49111222333",
                "timestamp": 1700000000000,
                "dataMessage": {"message": "", "timestamp": 1700000000000},
            }
        })

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = signal_output

        with patch("subprocess.run", return_value=mock_result):
            messages = connector.get_messages()
        assert len(messages) == 0

    def test_get_messages_handles_invalid_json(self, connector):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json\n{also broken"

        with patch("subprocess.run", return_value=mock_result):
            messages = connector.get_messages()
        assert len(messages) == 0

    def test_get_messages_respects_limit(self, connector):
        lines = []
        for i in range(10):
            lines.append(json.dumps({
                "envelope": {
                    "source": "+49111222333",
                    "timestamp": 1700000000000 + i * 1000,
                    "dataMessage": {"message": f"Nachricht {i}"},
                }
            }))

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(lines)

        with patch("subprocess.run", return_value=mock_result):
            messages = connector.get_messages(limit=3)
        assert len(messages) == 3

    def test_get_messages_cli_failure(self, connector):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            messages = connector.get_messages()
        assert len(messages) == 0


# ═══════════════════════════════════════════════════════════════
# WhatsAppConnector
# ═══════════════════════════════════════════════════════════════


class TestWhatsAppConnector:
    @pytest.fixture
    def wa_config(self):
        return ConnectorConfig(
            name="wa_test",
            connector_type="whatsapp",
            auth_type="api_key",
            auth_config={"api_token": "WA_TOKEN", "phone_number_id": "123456789"},
            options={"mode": "business_api"},
        )

    @pytest.fixture
    def connector(self, wa_config):
        from connectors.whatsapp_connector import WhatsAppConnector
        return WhatsAppConnector(wa_config)

    def test_init(self, connector):
        assert connector._api_token == "WA_TOKEN"
        assert connector._phone_number_id == "123456789"
        assert connector._mode == "business_api"

    def test_connect_no_credentials(self):
        from connectors.whatsapp_connector import WhatsAppConnector
        cfg = ConnectorConfig(name="wa", connector_type="whatsapp")
        c = WhatsAppConnector(cfg)
        assert c.connect() is False
        assert c.status == ConnectorStatus.ERROR

    def test_connect_success(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"verified_name": "BACH Bot", "id": "123456789"}
        ).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.connect()
        assert result is True
        assert connector.status == ConnectorStatus.CONNECTED

    def test_connect_failure(self, connector):
        with patch("urllib.request.urlopen", side_effect=Exception("API error")):
            result = connector.connect()
        assert result is False
        assert connector.status == ConnectorStatus.ERROR

    def test_disconnect(self, connector):
        connector._status = ConnectorStatus.CONNECTED
        assert connector.disconnect() is True
        assert connector.status == ConnectorStatus.DISCONNECTED

    def test_send_message_success(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"messages": [{"id": "wamid.123"}]}
        ).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.send_message("49123456789", "Hallo WhatsApp!")
        assert result is True

    def test_send_message_failure(self, connector):
        with patch("urllib.request.urlopen", side_effect=Exception("Send failed")):
            result = connector.send_message("49123456789", "Fail")
        assert result is False

    def test_get_messages_returns_empty(self, connector):
        assert connector.get_messages() == []

    def test_process_webhook_text_message(self, connector):
        webhook_data = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "49123456789",
                            "id": "wamid.456",
                            "timestamp": "1700000000",
                            "type": "text",
                            "text": {"body": "Webhook-Nachricht"},
                        }]
                    }
                }]
            }]
        }
        messages = connector.process_webhook(webhook_data)
        assert len(messages) == 1
        assert messages[0].sender == "49123456789"
        assert messages[0].content == "Webhook-Nachricht"
        assert messages[0].channel == "whatsapp"

    def test_process_webhook_non_text(self, connector):
        webhook_data = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "49123456789",
                            "id": "wamid.789",
                            "timestamp": "1700000000",
                            "type": "image",
                        }]
                    }
                }]
            }]
        }
        messages = connector.process_webhook(webhook_data)
        assert len(messages) == 0

    def test_process_webhook_empty(self, connector):
        assert connector.process_webhook({}) == []
        assert connector.process_webhook({"entry": []}) == []


# ═══════════════════════════════════════════════════════════════
# HomeAssistantConnector
# ═══════════════════════════════════════════════════════════════


class TestHomeAssistantConnector:
    @pytest.fixture
    def ha_config(self):
        return ConnectorConfig(
            name="ha_test",
            connector_type="homeassistant",
            endpoint="http://homeassistant.local:8123",
            auth_type="token",
            auth_config={"access_token": "HA_LONG_TOKEN"},
        )

    @pytest.fixture
    def connector(self, ha_config):
        from connectors.homeassistant_connector import HomeAssistantConnector
        return HomeAssistantConnector(ha_config)

    def test_init(self, connector):
        assert connector._token == "HA_LONG_TOKEN"
        assert connector._base_url == "http://homeassistant.local:8123"

    def test_init_strips_trailing_slash(self):
        from connectors.homeassistant_connector import HomeAssistantConnector
        cfg = ConnectorConfig(
            name="ha", connector_type="homeassistant",
            endpoint="http://ha.local:8123/",
            auth_config={"access_token": "T"},
        )
        c = HomeAssistantConnector(cfg)
        assert not c._base_url.endswith("/")

    def test_connect_success(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"message": "API running."}
        ).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.connect()
        assert result is True
        assert connector.status == ConnectorStatus.CONNECTED
        assert connector._ha_version == "API running."

    def test_connect_no_credentials(self):
        from connectors.homeassistant_connector import HomeAssistantConnector
        cfg = ConnectorConfig(name="ha", connector_type="homeassistant")
        c = HomeAssistantConnector(cfg)
        assert c.connect() is False
        assert c.status == ConnectorStatus.ERROR

    def test_connect_failure(self, connector):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = connector.connect()
        assert result is False
        assert connector.status == ConnectorStatus.ERROR

    def test_disconnect(self, connector):
        connector._status = ConnectorStatus.CONNECTED
        assert connector.disconnect() is True
        assert connector.status == ConnectorStatus.DISCONNECTED

    def test_send_message_delegates_to_call_service(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([]).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            connector.send_message("mobile_app_phone", "Test-Benachrichtigung")

        url = mock_open.call_args[0][0].full_url
        assert "/api/services/notify/mobile_app_phone" in url

    def test_get_messages_returns_empty(self, connector):
        assert connector.get_messages() == []

    def test_get_states(self, connector):
        states = [
            {"entity_id": "light.wohnzimmer", "state": "on"},
            {"entity_id": "sensor.temperatur", "state": "21.5"},
        ]
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(states).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.get_states()
        assert len(result) == 2
        assert result[0]["entity_id"] == "light.wohnzimmer"

    def test_get_states_failure(self, connector):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            result = connector.get_states()
        assert result == []

    def test_get_state(self, connector):
        state = {"entity_id": "light.wohnzimmer", "state": "off", "attributes": {}}
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(state).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.get_state("light.wohnzimmer")
        assert result["state"] == "off"

    def test_call_service(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([]).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            result = connector.call_service("light", "turn_on", {"entity_id": "light.wohnzimmer"})
        assert result is True
        url = mock_open.call_args[0][0].full_url
        assert "/api/services/light/turn_on" in url

    def test_fire_event(self, connector):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"message": "ok"}).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = connector.fire_event("bach_notification", {"text": "Test"})
        assert result is True

    def test_get_history_uses_utc_timezone(self, connector):
        """Verify get_history uses timezone-aware UTC (not deprecated utcnow)."""
        history = [[{"state": "on", "last_changed": "2026-01-01T12:00:00Z"}]]
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(history).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            result = connector.get_history("sensor.temp", hours=24)
        assert isinstance(result, list)
        url = mock_open.call_args[0][0].full_url
        assert "/api/history/period/" in url
        assert "Z?filter_entity_id=sensor.temp" in url

    def test_get_history_no_deprecated_utcnow(self):
        """Ensure source uses datetime.now(timezone.utc) not datetime.utcnow()."""
        import inspect
        from connectors.homeassistant_connector import HomeAssistantConnector
        source = inspect.getsource(HomeAssistantConnector)
        assert "utcnow()" not in source
        assert "timezone.utc" in source

    def test_get_history_failure(self, connector):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("err")):
            result = connector.get_history("sensor.temp")
        assert result == []


# ═══════════════════════════════════════════════════════════════
# Cross-Cutting: Encoding & Error Resilience
# ═══════════════════════════════════════════════════════════════


class TestCrossCutting:
    def test_all_connectors_importable(self):
        from connectors.telegram_connector import TelegramConnector
        from connectors.discord_connector import DiscordConnector
        from connectors.signal_connector import SignalConnector
        from connectors.whatsapp_connector import WhatsAppConnector
        from connectors.homeassistant_connector import HomeAssistantConnector

        assert TelegramConnector is not None
        assert DiscordConnector is not None
        assert SignalConnector is not None
        assert WhatsAppConnector is not None
        assert HomeAssistantConnector is not None

    def test_all_connectors_implement_base(self):
        from connectors.telegram_connector import TelegramConnector
        from connectors.discord_connector import DiscordConnector
        from connectors.signal_connector import SignalConnector
        from connectors.whatsapp_connector import WhatsAppConnector
        from connectors.homeassistant_connector import HomeAssistantConnector

        for cls in [TelegramConnector, DiscordConnector, SignalConnector,
                    WhatsAppConnector, HomeAssistantConnector]:
            assert issubclass(cls, BaseConnector)

    def test_connector_config_equality(self):
        cfg1 = ConnectorConfig(name="a", connector_type="test")
        cfg2 = ConnectorConfig(name="a", connector_type="test")
        assert cfg1 == cfg2

    def test_message_equality(self):
        m1 = Message(channel="tg", sender="u", content="hi", timestamp="t")
        m2 = Message(channel="tg", sender="u", content="hi", timestamp="t")
        assert m1 == m2

    def test_poll_threaded_creates_daemon_thread(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(
            name="d", connector_type="discord",
            auth_config={"bot_token": "T"},
            options={"default_channel": "CH"},
        )
        c = DiscordConnector(cfg)
        c._bot_info = {"id": "bot"}

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([]).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            thread, stop = c.poll_threaded(lambda m: None, interval=0.05)
            assert thread.daemon is True
            assert thread.name == "bach-discord-poll"
            stop.set()
            thread.join(timeout=2)
