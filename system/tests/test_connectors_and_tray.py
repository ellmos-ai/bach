# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for BACH Connectors (base, telegram, signal, discord, whatsapp, HA) and Chat Tray."""

import json
import os
import socket
import sys
import threading
import time
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from connectors.base import BaseConnector, ConnectorConfig, ConnectorStatus, Message


# ===================================================================
# BASE CLASSES
# ===================================================================


class TestConnectorStatus:
    def test_status_values(self):
        assert ConnectorStatus.DISCONNECTED.value == "disconnected"
        assert ConnectorStatus.CONNECTING.value == "connecting"
        assert ConnectorStatus.CONNECTED.value == "connected"
        assert ConnectorStatus.ERROR.value == "error"


class TestMessage:
    def test_default_fields(self):
        msg = Message(channel="test", sender="s1", content="hi", timestamp="2026-01-01T00:00:00")
        assert msg.attachments == []
        assert msg.metadata == {}
        assert msg.direction == "in"
        assert msg.message_id == ""

    def test_full_construction(self):
        msg = Message(
            channel="telegram", sender="123", content="hello",
            timestamp="2026-01-01T00:00:00",
            attachments=["/tmp/a.jpg"], metadata={"key": "val"},
            direction="out", message_id="msg-42",
        )
        assert msg.channel == "telegram"
        assert msg.attachments == ["/tmp/a.jpg"]
        assert msg.metadata["key"] == "val"
        assert msg.direction == "out"


class TestConnectorConfig:
    def test_defaults(self):
        cfg = ConnectorConfig(name="test", connector_type="signal")
        assert cfg.endpoint == ""
        assert cfg.auth_type == "none"
        assert cfg.auth_config == {}
        assert cfg.options == {}

    def test_full_construction(self):
        cfg = ConnectorConfig(
            name="tg", connector_type="telegram",
            endpoint="https://api.telegram.org",
            auth_type="api_key",
            auth_config={"bot_token": "xyz"},
            options={"owner_chat_id": "123"},
        )
        assert cfg.auth_config["bot_token"] == "xyz"


class TestBaseConnector:
    def test_cannot_instantiate_abstract(self):
        cfg = ConnectorConfig(name="t", connector_type="t")
        with pytest.raises(TypeError):
            BaseConnector(cfg)

    def test_concrete_subclass(self):
        class Dummy(BaseConnector):
            def connect(self): return True
            def disconnect(self): return True
            def send_message(self, r, c, a=None): return True
            def get_messages(self, s=None, l=50): return []

        cfg = ConnectorConfig(name="dummy", connector_type="test")
        d = Dummy(cfg)
        assert d.name == "dummy"
        assert d.connector_type == "test"
        assert d.status == ConnectorStatus.DISCONNECTED
        assert d.get_status() == ConnectorStatus.DISCONNECTED
        assert "Dummy" in repr(d)


# ===================================================================
# TELEGRAM CONNECTOR
# ===================================================================


@pytest.fixture
def tg_config():
    return ConnectorConfig(
        name="tg_test", connector_type="telegram",
        auth_type="api_key",
        auth_config={"bot_token": "123456:ABC-DEF"},
        options={"owner_chat_id": "999"},
    )


@pytest.fixture
def tg(tg_config):
    from connectors.telegram_connector import TelegramConnector
    return TelegramConnector(tg_config)


class TestTelegramInit:
    def test_token_from_config(self, tg):
        assert tg._bot_token == "123456:ABC-DEF"
        assert tg._owner_chat_id == "999"
        assert tg._last_update_id == 0
        assert tg._polling is False

    def test_missing_token(self):
        from connectors.telegram_connector import TelegramConnector
        cfg = ConnectorConfig(name="t", connector_type="telegram")
        t = TelegramConnector(cfg)
        assert t._bot_token == ""

    def test_secret_ref_fallback(self):
        from connectors.telegram_connector import TelegramConnector
        cfg = ConnectorConfig(
            name="t", connector_type="telegram",
            auth_config={"_secret_refs": {"bot_token": "telegram_bot_token"}},
        )
        with patch.object(TelegramConnector, '_load_from_secrets_table', return_value="secret-token"):
            t = TelegramConnector(cfg)
            assert t._bot_token == "secret-token"


class TestTelegramConnect:
    def test_connect_success(self, tg):
        with patch.object(tg, '_api_call', return_value={"id": 123, "first_name": "Bot"}):
            assert tg.connect() is True
            assert tg.status == ConnectorStatus.CONNECTED
            assert tg._bot_info["id"] == 123

    def test_connect_failure(self, tg):
        with patch.object(tg, '_api_call', return_value=None):
            assert tg.connect() is False
            assert tg.status == ConnectorStatus.ERROR

    def test_connect_no_token(self):
        from connectors.telegram_connector import TelegramConnector
        cfg = ConnectorConfig(name="t", connector_type="telegram")
        t = TelegramConnector(cfg)
        assert t.connect() is False
        assert t.status == ConnectorStatus.ERROR

    def test_connect_exception(self, tg):
        with patch.object(tg, '_api_call', side_effect=Exception("boom")):
            assert tg.connect() is False
            assert tg.status == ConnectorStatus.ERROR


class TestTelegramDisconnect:
    def test_disconnect(self, tg):
        tg._polling = True
        assert tg.disconnect() is True
        assert tg._polling is False
        assert tg.status == ConnectorStatus.DISCONNECTED


class TestTelegramSendMessage:
    def test_send_with_markdown_success(self, tg):
        with patch.object(tg, '_api_call', return_value={"message_id": 42}):
            assert tg.send_message("999", "Hello *world*") is True

    def test_send_markdown_fallback_to_plain(self, tg):
        call_count = [0]
        def mock_api(method, params=None, retries=3, timeout=15):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # Markdown parse failure
            return {"message_id": 43}  # Plain text success
        with patch.object(tg, '_api_call', side_effect=mock_api):
            assert tg.send_message("999", "bad *markdown") is True
            assert call_count[0] == 2

    def test_send_uses_owner_chat_id_when_empty(self, tg):
        with patch.object(tg, '_api_call', return_value={"message_id": 1}) as mock:
            tg.send_message("", "test")
            call_args = mock.call_args[1] if mock.call_args[1] else {}
            params = mock.call_args[0][1] if len(mock.call_args[0]) > 1 else call_args.get('params', {})
            assert params.get("chat_id") == "999"


class TestTelegramGetMessages:
    def test_parses_text_message(self, tg):
        updates = [{
            "update_id": 100,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 999, "type": "private"},
                "from": {"first_name": "Test", "last_name": "User"},
                "text": "Hello BACH",
            },
        }]
        with patch.object(tg, '_api_call', return_value=updates):
            msgs = tg.get_messages()
            assert len(msgs) == 1
            assert msgs[0].content == "Hello BACH"
            assert msgs[0].channel == "telegram"
            assert msgs[0].metadata["message_type"] == "text"

    def test_filters_non_owner_messages(self, tg):
        updates = [{
            "update_id": 101,
            "message": {
                "message_id": 2,
                "date": 1700000000,
                "chat": {"id": 888, "type": "private"},
                "from": {"first_name": "Stranger", "last_name": ""},
                "text": "I should be filtered",
            },
        }]
        with patch.object(tg, '_api_call', return_value=updates):
            msgs = tg.get_messages()
            assert len(msgs) == 0

    def test_skips_empty_messages(self, tg):
        updates = [{
            "update_id": 102,
            "message": {
                "message_id": 3,
                "date": 1700000000,
                "chat": {"id": 999, "type": "private"},
                "from": {"first_name": "Test", "last_name": ""},
            },
        }]
        with patch.object(tg, '_api_call', return_value=updates):
            msgs = tg.get_messages()
            assert len(msgs) == 0

    def test_tracks_last_update_id(self, tg):
        updates = [
            {"update_id": 200, "message": {"message_id": 1, "date": 1700000000,
             "chat": {"id": 999}, "from": {"first_name": ""}, "text": "a"}},
            {"update_id": 205, "message": {"message_id": 2, "date": 1700000001,
             "chat": {"id": 999}, "from": {"first_name": ""}, "text": "b"}},
        ]
        with patch.object(tg, '_api_call', return_value=updates):
            tg.get_messages()
            assert tg._last_update_id == 205

    def test_api_failure_returns_empty(self, tg):
        with patch.object(tg, '_api_call', return_value=None):
            assert tg.get_messages() == []

    def test_caption_message(self, tg):
        updates = [{
            "update_id": 103,
            "message": {
                "message_id": 4, "date": 1700000000,
                "chat": {"id": 999, "type": "private"},
                "from": {"first_name": "Test", "last_name": ""},
                "caption": "Photo caption",
            },
        }]
        with patch.object(tg, '_api_call', return_value=updates):
            msgs = tg.get_messages()
            assert len(msgs) == 1
            assert msgs[0].content == "Photo caption"
            assert msgs[0].metadata["message_type"] == "caption"


class TestTelegramApiCallRetry:
    """Verifies the retry logic in _api_call works for transient errors."""

    def test_url_error_retries(self, tg):
        """URLError should be retried, not immediately return None."""
        attempts = []
        original_urlopen = urllib.request.urlopen

        def mock_urlopen(req, timeout=None):
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.URLError("Connection refused")
            resp = MagicMock()
            resp.read.return_value = json.dumps({"ok": True, "result": "success"}).encode()
            resp.__enter__ = lambda s: resp
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            with patch('time.sleep'):
                result = tg._api_call("getMe", retries=3)
                assert result == "success"
                assert len(attempts) == 3

    def test_http_5xx_retries(self, tg):
        """5xx HTTP errors should be retried."""
        attempts = []

        def mock_urlopen(req, timeout=None):
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.HTTPError(
                    "http://test", 502, "Bad Gateway", {}, BytesIO(b""))
            resp = MagicMock()
            resp.read.return_value = json.dumps({"ok": True, "result": "ok"}).encode()
            resp.__enter__ = lambda s: resp
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            with patch('time.sleep'):
                result = tg._api_call("sendMessage", retries=3)
                assert result == "ok"
                assert len(attempts) == 3

    def test_http_4xx_no_retry(self, tg, capsys):
        """4xx HTTP errors should NOT be retried, but should print."""
        attempts = []

        def mock_urlopen(req, timeout=None):
            attempts.append(1)
            raise urllib.error.HTTPError(
                "http://test", 400, "Bad Request", {}, BytesIO(b""))

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            result = tg._api_call("sendMessage", retries=3)
            assert result is None
            assert len(attempts) == 1
        captured = capsys.readouterr()
        assert "HTTP 400" in captured.err

    def test_socket_timeout_retries_non_getupdates(self, tg):
        """socket.timeout should be retried for non-getUpdates methods."""
        attempts = []

        def mock_urlopen(req, timeout=None):
            attempts.append(1)
            if len(attempts) < 3:
                raise socket.timeout("timed out")
            resp = MagicMock()
            resp.read.return_value = json.dumps({"ok": True, "result": "ok"}).encode()
            resp.__enter__ = lambda s: resp
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            with patch('time.sleep'):
                result = tg._api_call("sendMessage", retries=3)
                assert result == "ok"
                assert len(attempts) == 3

    def test_socket_timeout_getupdates_returns_empty(self, tg):
        """getUpdates timeout returns empty list immediately (long-polling normal)."""
        def mock_urlopen(req, timeout=None):
            raise socket.timeout("timed out")

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            result = tg._api_call("getUpdates", retries=3)
            assert result == []

    def test_all_retries_exhausted(self, tg):
        """After all retries fail, returns None."""
        def mock_urlopen(req, timeout=None):
            raise urllib.error.URLError("Connection refused")

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            with patch('time.sleep'):
                result = tg._api_call("sendMessage", retries=3)
                assert result is None


class TestTelegramPolling:
    def test_poll_threaded_starts_thread(self, tg):
        tg._status = ConnectorStatus.CONNECTED
        received = []

        def callback(msg):
            received.append(msg)

        with patch.object(tg, 'get_messages', return_value=[]):
            thread, stop = tg.poll_threaded(callback, interval=0.1)
            assert thread.is_alive()
            time.sleep(0.3)
            stop.set()
            thread.join(timeout=2)
            assert not thread.is_alive()

    def test_poll_loop_stops_on_event(self, tg):
        stop = threading.Event()
        stop.set()
        tg.poll_loop(lambda m: None, interval=0.1, stop_event=stop)


# ===================================================================
# SIGNAL CONNECTOR
# ===================================================================


@pytest.fixture
def signal_config():
    return ConnectorConfig(
        name="sig_test", connector_type="signal",
        auth_config={"phone_number": "+491234567890"},
        options={"signal_cli_path": "signal-cli"},
    )


@pytest.fixture
def sig(signal_config):
    from connectors.signal_connector import SignalConnector
    return SignalConnector(signal_config)


class TestSignalInit:
    def test_fields(self, sig):
        assert sig._phone_number == "+491234567890"
        assert sig._signal_cli_path == "signal-cli"


class TestSignalConnect:
    def test_connect_no_phone(self):
        from connectors.signal_connector import SignalConnector
        cfg = ConnectorConfig(name="s", connector_type="signal")
        s = SignalConnector(cfg)
        assert s.connect() is False

    def test_connect_cli_found(self, sig):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert sig.connect() is True
            assert sig.status == ConnectorStatus.CONNECTED

    def test_connect_cli_not_found(self, sig):
        with patch('subprocess.run', side_effect=FileNotFoundError):
            assert sig.connect() is False
            assert sig.status == ConnectorStatus.ERROR


class TestSignalSendMessage:
    def test_send_success(self, sig):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert sig.send_message("+499876", "Hello") is True

    def test_send_failure(self, sig):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert sig.send_message("+499876", "Hello") is False


class TestSignalGetMessages:
    def test_parses_json_lines(self, sig):
        output = json.dumps({
            "envelope": {
                "source": "+491111111",
                "timestamp": 1700000000000,
                "dataMessage": {"message": "Hello Signal"},
            }
        })
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            msgs = sig.get_messages()
            assert len(msgs) == 1
            assert msgs[0].content == "Hello Signal"
            assert msgs[0].channel == "signal"

    def test_empty_output(self, sig):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            assert sig.get_messages() == []


# ===================================================================
# DISCORD CONNECTOR
# ===================================================================


@pytest.fixture
def discord_config():
    return ConnectorConfig(
        name="dc_test", connector_type="discord",
        auth_type="api_key",
        auth_config={"bot_token": "discord-token"},
        options={"default_channel": "12345"},
    )


@pytest.fixture
def dc(discord_config):
    from connectors.discord_connector import DiscordConnector
    return DiscordConnector(discord_config)


class TestDiscordInit:
    def test_bot_mode(self, dc):
        assert dc._bot_token == "discord-token"
        assert dc._webhook_url == ""

    def test_webhook_mode(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(
            name="dc_wh", connector_type="discord",
            endpoint="https://discord.com/api/webhooks/123/abc",
        )
        d = DiscordConnector(cfg)
        assert d._webhook_url == "https://discord.com/api/webhooks/123/abc"


class TestDiscordConnect:
    def test_connect_bot_success(self, dc):
        with patch.object(dc, '_api_call', return_value={"id": "bot123"}):
            assert dc.connect() is True
            assert dc.status == ConnectorStatus.CONNECTED

    def test_connect_bot_failure(self, dc):
        with patch.object(dc, '_api_call', return_value=None):
            assert dc.connect() is False

    def test_connect_webhook_always_ok(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(
            name="dc_wh", connector_type="discord",
            endpoint="https://discord.com/api/webhooks/123/abc",
        )
        d = DiscordConnector(cfg)
        assert d.connect() is True

    def test_connect_no_credentials(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(name="dc", connector_type="discord")
        d = DiscordConnector(cfg)
        assert d.connect() is False


class TestDiscordSendMessage:
    def test_send_bot_mode(self, dc):
        with patch.object(dc, '_send_bot', return_value=True):
            assert dc.send_message("12345", "test") is True

    def test_send_webhook_mode(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(
            name="dc_wh", connector_type="discord",
            endpoint="https://discord.com/api/webhooks/123/abc",
        )
        d = DiscordConnector(cfg)
        with patch.object(d, '_send_webhook', return_value=True):
            assert d.send_message("", "test") is True


class TestDiscordGetMessages:
    def test_no_channel_returns_empty(self):
        from connectors.discord_connector import DiscordConnector
        cfg = ConnectorConfig(
            name="dc", connector_type="discord",
            auth_config={"bot_token": "tok"},
        )
        d = DiscordConnector(cfg)
        assert d.get_messages() == []

    def test_filters_own_messages(self, dc):
        dc._bot_info = {"id": "bot123"}
        msgs = [
            {"id": "1", "author": {"id": "bot123", "username": "bot"}, "content": "self", "timestamp": "t"},
            {"id": "2", "author": {"id": "user456", "username": "user"}, "content": "hello", "timestamp": "t"},
        ]
        with patch.object(dc, '_api_call', return_value=msgs):
            result = dc.get_messages()
            assert len(result) == 1
            assert result[0].content == "hello"


# ===================================================================
# WHATSAPP CONNECTOR
# ===================================================================


class TestWhatsAppConnector:
    def test_init(self):
        from connectors.whatsapp_connector import WhatsAppConnector
        cfg = ConnectorConfig(
            name="wa", connector_type="whatsapp",
            auth_config={"api_token": "tok", "phone_number_id": "123"},
        )
        wa = WhatsAppConnector(cfg)
        assert wa._api_token == "tok"
        assert wa._phone_number_id == "123"

    def test_connect_no_credentials(self):
        from connectors.whatsapp_connector import WhatsAppConnector
        cfg = ConnectorConfig(name="wa", connector_type="whatsapp")
        wa = WhatsAppConnector(cfg)
        assert wa.connect() is False

    def test_get_messages_returns_empty(self):
        from connectors.whatsapp_connector import WhatsAppConnector
        cfg = ConnectorConfig(
            name="wa", connector_type="whatsapp",
            auth_config={"api_token": "tok", "phone_number_id": "123"},
        )
        wa = WhatsAppConnector(cfg)
        assert wa.get_messages() == []

    def test_process_webhook(self):
        from connectors.whatsapp_connector import WhatsAppConnector
        cfg = ConnectorConfig(
            name="wa", connector_type="whatsapp",
            auth_config={"api_token": "tok", "phone_number_id": "123"},
        )
        wa = WhatsAppConnector(cfg)
        webhook = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "type": "text",
                            "from": "491234",
                            "text": {"body": "Hallo"},
                            "timestamp": "1700000000",
                            "id": "wamid.123",
                        }],
                    },
                }],
            }],
        }
        msgs = wa.process_webhook(webhook)
        assert len(msgs) == 1
        assert msgs[0].content == "Hallo"
        assert msgs[0].channel == "whatsapp"


# ===================================================================
# HOME ASSISTANT CONNECTOR
# ===================================================================


class TestHomeAssistantConnector:
    def test_init(self):
        from connectors.homeassistant_connector import HomeAssistantConnector
        cfg = ConnectorConfig(
            name="ha", connector_type="homeassistant",
            endpoint="http://ha.local:8123",
            auth_config={"access_token": "mytoken"},
        )
        ha = HomeAssistantConnector(cfg)
        assert ha._token == "mytoken"
        assert ha._base_url == "http://ha.local:8123"

    def test_connect_success(self):
        from connectors.homeassistant_connector import HomeAssistantConnector
        cfg = ConnectorConfig(
            name="ha", connector_type="homeassistant",
            endpoint="http://ha.local:8123/",
            auth_config={"access_token": "tok"},
        )
        ha = HomeAssistantConnector(cfg)
        with patch.object(ha, '_api_call', return_value={"message": "API running."}):
            assert ha.connect() is True
            assert ha.status == ConnectorStatus.CONNECTED

    def test_connect_no_token(self):
        from connectors.homeassistant_connector import HomeAssistantConnector
        cfg = ConnectorConfig(name="ha", connector_type="homeassistant", endpoint="http://ha:8123")
        ha = HomeAssistantConnector(cfg)
        assert ha.connect() is False

    def test_get_states(self):
        from connectors.homeassistant_connector import HomeAssistantConnector
        cfg = ConnectorConfig(
            name="ha", connector_type="homeassistant",
            endpoint="http://ha:8123",
            auth_config={"access_token": "tok"},
        )
        ha = HomeAssistantConnector(cfg)
        with patch.object(ha, '_api_call', return_value=[{"entity_id": "light.lamp", "state": "on"}]):
            states = ha.get_states()
            assert len(states) == 1
            assert states[0]["entity_id"] == "light.lamp"

    def test_get_messages_returns_empty(self):
        from connectors.homeassistant_connector import HomeAssistantConnector
        cfg = ConnectorConfig(
            name="ha", connector_type="homeassistant",
            endpoint="http://ha:8123",
            auth_config={"access_token": "tok"},
        )
        ha = HomeAssistantConnector(cfg)
        assert ha.get_messages() == []


# ===================================================================
# CHAT TRAY
# ===================================================================


class TestBACHTray:
    @pytest.fixture
    def tray(self):
        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }):
            from hub._services.chat.chat_tray import BACHTray
            return BACHTray(host="testhost", port=9999)

    def test_init_urls(self, tray):
        assert tray.base_url == "http://testhost:9999"
        assert tray.gui_url == "http://testhost:8000"
        assert tray.webchat_url == "http://testhost:8080"

    def test_init_uses_resolved_gui_port(self):
        from hub._services.chat.chat_tray import BACHTray

        tray = BACHTray(host="testhost", port=9999, gui_port=8123)
        assert tray.control_port == 9999
        assert tray.gui_port == 8123
        assert tray.gui_url == "http://testhost:8123"

    def test_initial_state(self, tray):
        assert tray.state["backend"] == "?"
        assert tray.state["mode"] == "safe"
        assert tray.state["connected"] is False
        assert tray.state["think"] is True
        assert tray.services["webchat"] is False

    def test_loads_promptboard_library_from_env(self, tmp_path):
        library = tmp_path / "library.json"
        library.write_text(
            json.dumps({
                "items": [{
                    "id": "p1",
                    "item_type": "PROMPT",
                    "name": "Review Prompt",
                    "content": "Bitte prüfe diesen Text.",
                    "category": "Review",
                }]
            }),
            encoding="utf-8",
        )

        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }), patch.dict(os.environ, {"BACH_PROMPTBOARD_LIBRARY": str(library)}, clear=False):
            from hub._services.chat.chat_tray import BACHTray
            tray = BACHTray(host="testhost", port=9999)

        assert tray.prompts["Review"]["Review Prompt"] == "Bitte prüfe diesen Text."
        assert tray.prompt_source == str(library)

    def test_loads_promptboard_library_from_home_default(self, tmp_path):
        data_dir = tmp_path / ".promptboard"
        data_dir.mkdir()
        library = data_dir / "library.json"
        library.write_text(
            json.dumps({
                "items": [{
                    "name": "Home Prompt",
                    "content": "Aus dem PromptBoard-Standardpfad.",
                    "category": "Local",
                }]
            }),
            encoding="utf-8",
        )

        legacy_dir = tmp_path / "AppData" / "Roaming" / "PromptBoard"
        legacy_dir.mkdir(parents=True)
        legacy_library = legacy_dir / "library.json"
        legacy_library.write_text(
            json.dumps({
                "items": [{
                    "name": "Legacy Prompt",
                    "content": "Aus dem alten AppData-Pfad.",
                    "category": "Legacy",
                }]
            }),
            encoding="utf-8",
        )

        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }), patch.dict(os.environ, {
            "APPDATA": str(tmp_path / "AppData" / "Roaming"),
            "BACH_PROMPTBOARD_LIBRARY": "",
        }, clear=False), patch("hub._services.chat.chat_tray.Path.home", return_value=tmp_path):
            from hub._services.chat.chat_tray import BACHTray
            tray = BACHTray(host="testhost", port=9999)

        assert tray.prompts["Local"]["Home Prompt"] == "Aus dem PromptBoard-Standardpfad."
        assert tray.prompt_source == str(library)

    def test_promptboard_app_path_from_env(self, tmp_path):
        app_path = tmp_path / "PromptBoard.exe"
        app_path.write_text("", encoding="utf-8")

        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }), patch.dict(os.environ, {"BACH_PROMPTBOARD_APP": str(app_path)}, clear=False):
            from hub._services.chat.chat_tray import BACHTray
            tray = BACHTray(host="testhost", port=9999)
            assert tray._promptboard_app_path() == app_path

    def test_promptboard_smoke_snapshot_reports_app_menu(self, tmp_path):
        app_path = tmp_path / "PromptBoard.exe"
        app_path.write_text("", encoding="utf-8")
        library = tmp_path / "library.json"
        library.write_text(
            json.dumps({
                "items": [{
                    "name": "Smoke Prompt",
                    "content": "Bitte teste PromptBoard.",
                    "category": "Smoke",
                }]
            }),
            encoding="utf-8",
        )

        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }), patch.dict(os.environ, {
            "BACH_PROMPTBOARD_APP": str(app_path),
            "BACH_PROMPTBOARD_LIBRARY": str(library),
        }, clear=False):
            from hub._services.chat.chat_tray import BACHTray
            tray = BACHTray(host="testhost", port=9999)
            snapshot = tray.promptboard_smoke_snapshot()

        assert snapshot["app_path"] == str(app_path)
        assert snapshot["app_found"] is True
        assert snapshot["menu_has_open_app"] is True
        assert snapshot["library_found"] is True
        assert snapshot["prompt_source"] == str(library)
        assert snapshot["using_default_prompts"] is False
        assert snapshot["prompt_categories"] == ["Smoke"]
        assert snapshot["prompt_count"] == 1

    def test_refresh_updates_state(self, tray):
        tray._check_url = MagicMock(return_value=False)
        tray._api = MagicMock(side_effect=[
            {"backend": "ollama", "model": "qwen", "mode": "full", "connected": True,
             "think": False, "bach": True, "sessions": 2, "max_tool_rounds": 10,
             "backend_cli": ""},
            {"ollama": {"status": "ok"}},
            {"models": ["qwen3.5", "llama3"]},
        ])
        tray._refresh()
        assert tray.state["backend"] == "ollama"
        assert tray.state["mode"] == "full"
        assert tray.state["connected"] is True
        assert tray.models == ["qwen3.5", "llama3"]

    def test_refresh_skips_catalog_requests_while_offline(self, tray):
        tray._check_url = MagicMock(return_value=False)
        tray._api = MagicMock(return_value=None)
        tray._refresh()
        assert tray._api.call_count == 1

    def test_refresh_marks_disconnected_on_failure(self, tray):
        tray.state["connected"] = True
        tray._api = MagicMock(return_value=None)
        tray._refresh()
        assert tray.state["connected"] is False

    def test_set_mode(self, tray):
        tray._api = MagicMock(return_value=None)
        tray._update_icon = MagicMock()
        tray._refresh = MagicMock()
        tray._set_mode("full")
        tray._api.assert_any_call("POST", "/api/mode", {"mode": "full"})

    def test_toggle_think(self, tray):
        tray.state["think"] = True
        tray._api = MagicMock(return_value=None)
        tray._update_icon = MagicMock()
        tray._refresh = MagicMock()
        tray._toggle_think()
        tray._api.assert_any_call("POST", "/api/think", {"think": False})

    def test_quit_stops(self, tray):
        tray.icon = MagicMock()
        tray._quit()
        assert tray._stop.is_set()
        tray.icon.stop.assert_called_once()

    def test_api_handles_errors(self, tray):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError("fail")):
            result = tray._api("GET", "/api/status")
            assert result is None

    def test_api_success(self, tray):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"backend": "ollama"}).encode()
        resp.__enter__ = lambda s: resp
        resp.__exit__ = MagicMock(return_value=False)

        with patch('urllib.request.urlopen', return_value=resp):
            result = tray._api("GET", "/api/status")
            assert result["backend"] == "ollama"
