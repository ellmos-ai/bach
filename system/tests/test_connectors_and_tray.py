# SPDX-License-Identifier: MIT
"""Tests for BACH Connectors (base, telegram, signal, discord, whatsapp, HA) and Chat Tray."""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

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
                raise TimeoutError("timed out")
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
            raise TimeoutError("timed out")

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
    def test_startspine_ready_receipt_is_written_after_icon_setup(self, tmp_path, monkeypatch):
        from hub._services.chat.chat_tray import mark_tray_ready

        receipt = tmp_path / "receipts" / "tray.ready.json"
        monkeypatch.setenv("BACH_STARTSPINE_READY_RECEIPT", str(receipt))
        monkeypatch.setenv("BACH_STARTSPINE_LAUNCH_ID", "test-launch")
        icon = MagicMock()
        mark_tray_ready(icon)

        assert icon.visible is True
        assert json.loads(receipt.read_text(encoding="utf-8")) == {
            "launch_id": "test-launch", "pid": os.getpid(),
        }
        assert not list(receipt.parent.glob("*.tmp"))

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
        assert tray.activity_url == "http://testhost:8000/agenten/running"
        # Das :8080-Relikt des stillgelegten claude_bridge darf nicht zurückkehren.
        assert not hasattr(tray, "webchat_url")

    def test_always_on_starts_immediately_while_foreground_session_is_active(self, tray, monkeypatch):
        from hub._services.chat import chat_tray

        tray.slots = {"buddha_always_on": {"enabled": True}}
        tray.state = {"active_sessions": 1}
        tray.idle_enabled = True
        tray.idle_processing = False
        tray.idle_consecutive = 0
        tray._recurring_tick = 0
        tray.icon = None
        starts = []

        class FakeThread:
            def __init__(self, *, target, daemon):
                self.target = target

            def start(self):
                starts.append(self.target)

        monkeypatch.setattr(chat_tray, "get_slot", lambda _slot_id: {"enabled": True})
        monkeypatch.setattr(chat_tray, "is_slot_paused", lambda _slot: False)
        monkeypatch.setattr(chat_tray.threading, "Thread", FakeThread)

        tray._idle_tick()

        assert tray.IDLE_THRESHOLD == 1
        assert starts == [tray._process_idle_task]

    def test_branding_support(self):
        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }):
            from hub._services.chat.chat_tray import BACHTray
            tray_bach = BACHTray(brand="bach")
            assert tray_bach.brand == "bach"
            tray_ocean = BACHTray(brand="ocean")
            assert tray_ocean.brand == "ocean"

    def test_custom_activity_and_gui_urls(self):
        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }):
            from hub._services.chat.chat_tray import BACHTray
            tray = BACHTray(
                host="testhost", port=9999,
                activity_url="http://custom-host:8081/activity",
                gui_url="http://custom-gui:8000",
            )
            assert tray.activity_url == "http://custom-host:8081/activity"
            assert tray.gui_url == "http://custom-gui:8000"

    def test_activity_and_gui_urls_from_env(self, monkeypatch):
        monkeypatch.setenv("BACH_ACTIVITY_URL", "http://env-host:8081/custom-activity")
        monkeypatch.setenv("BACH_GUI_URL", "http://env-host:8000/dashboard")
        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }):
            from hub._services.chat.chat_tray import BACHTray
            tray = BACHTray(host="testhost", port=9999)
            assert tray.activity_url == "http://env-host:8081/custom-activity"
            assert tray.gui_url == "http://env-host:8000/dashboard"

    def test_open_activity_opens_configured_url(self, tray):
        tray.activity_url = "http://my-activity-url:9999/activity"
        with patch("webbrowser.open") as opened:
            tray._open_activity()
        opened.assert_called_once_with("http://my-activity-url:9999/activity")

    def test_open_gui_opens_configured_url(self, tray):
        tray.gui_url = "http://my-gui-url:8000"
        with patch("webbrowser.open") as opened:
            tray._open_gui()
        opened.assert_called_once_with("http://my-gui-url:8000")

    def test_open_running_and_blueprints_opens_gui_pages(self, tray):
        tray.gui_url = "http://my-gui-url:8000"
        with patch("webbrowser.open") as opened:
            tray._open_running()
            tray._open_blueprints()
        from unittest.mock import call
        assert opened.call_args_list == [
            call("http://my-gui-url:8000/agenten/running"),
            call("http://my-gui-url:8000/agenten/blueprints"),
        ]

    def test_buddha_chat_opens_the_gui_chat_page(self, tray):
        """The :8080 webchat no longer exists; the tray must open the GUI chat (1.1.6)."""
        with patch("webbrowser.open") as opened:
            tray._open_webchat()
        opened.assert_called_once_with("http://testhost:8000/chat")

    def test_initial_state(self, tray):
        assert tray.state["backend"] == "?"
        assert tray.state["mode"] == "safe"
        assert tray.state["connected"] is False
        assert tray.state["think"] is True

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
        tray._api = MagicMock(side_effect=[
            {"backend": "ollama", "model": "qwen", "mode": "full", "connected": True,
             "think": False, "bach": True, "sessions": 2, "max_tool_rounds": 10,
             "backend_cli": ""},
            {"ollama": {"status": "ok"}},
            {"models": ["qwen3.5", "llama3"]},
            {"ok": True, "slots": {"buddha_chat": {"model": "qwen3.5"}}, "dynamic_workers": []},
        ])
        tray._refresh()
        assert tray.state["backend"] == "ollama"
        assert tray.state["mode"] == "full"
        assert tray.state["connected"] is True
        assert tray.models == ["qwen3.5", "llama3"]
        assert "buddha_chat" in tray.slots

    def test_refresh_marks_disconnected_on_failure(self, tray):
        tray.state["connected"] = True
        tray._api = MagicMock(return_value=None)
        # First failure: debounced, still connected
        tray._refresh()
        assert tray.state["connected"] is True
        assert tray._failed_status_count == 1
        # Second failure: still connected
        tray._refresh()
        assert tray.state["connected"] is True
        # Third failure: threshold reached, marked disconnected
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

    def test_prompt_failure_shows_the_backend_reason(self, tray):
        """ok=False traegt seit T-20260906-743610852 die Ursache im Antworttext."""
        tray.icon = MagicMock()
        tray._api = MagicMock(return_value={"ok": False,
                                            "answer": "Backend-Fehler: Ollama weg"})
        tray._send_prompt("Was geht?")
        tray.icon.notify.assert_called_once_with("Backend-Fehler: Ollama weg",
                                                 "BACH Fehler")

    def test_prompt_without_any_response_still_reports_failure(self, tray):
        tray.icon = MagicMock()
        tray._api = MagicMock(return_value=None)
        tray._send_prompt("Was geht?")
        tray.icon.notify.assert_called_once_with("Senden fehlgeschlagen", "BACH Fehler")

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

    def test_fackel_preference_default(self, tray):
        assert tray.state["fackel_preference"] == "compute"

    def test_set_fackel_via_api(self, tray):
        with patch.object(tray, "_api", return_value={"ok": True, "fackel_preference": "ollama"}) as mock_api, \
             patch.object(tray, "_refresh"), \
             patch.object(tray, "_update_icon"):
            tray.icon = MagicMock()
            tray._set_fackel("ollama")
            mock_api.assert_called_once_with("POST", "/api/fackel", {"preference": "ollama"})
            assert tray.state["fackel_preference"] == "ollama"
            tray.icon.notify.assert_called_once()
            assert "Ollama" in tray.icon.notify.call_args[0][0]

    def test_set_fackel_fallback_local(self, tray, tmp_path):
        fpath = str(tmp_path / "fackel.json")
        with patch.object(tray, "_api", return_value=None), \
             patch.dict(os.environ, {"BACH_FACKEL_PREFERENCE_PATH": fpath}), \
             patch.object(tray, "_refresh"), \
             patch.object(tray, "_update_icon"):
            tray.icon = MagicMock()
            tray._set_fackel("compute")
            assert tray.state["fackel_preference"] == "compute"

    def test_remote_fackel_failure_never_writes_laptop_preference(self, tray):
        tray.remote = True
        original = tray.state["fackel_preference"]
        with patch.object(tray, "_api", return_value=None), \
             patch("hub.compute_lock.set_fackel_preference") as local_write, \
             patch.object(tray, "_notify_error") as notify:
            tray._set_fackel("ollama")
        local_write.assert_not_called()
        notify.assert_called_once()
        assert tray.state["fackel_preference"] == original

    def test_build_menu_contains_fackel_submenu(self, tray):
        tray.state["connected"] = True
        tray.state["fackel_preference"] = "ollama"
        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
        }):
            menu = tray._build_menu()
            # _build_menu creates items including Fackel
            assert menu is not None

    def test_remote_tray_menu_reports_server_target_and_server_worker_config(self, tray):
        from hub._services.chat import chat_tray

        tray.remote = True
        tray.state["connected"] = True
        tray.slots = {"buddha_always_on": {"enabled": True}}
        pystray_mock = MagicMock()
        with patch.object(chat_tray, "pystray", pystray_mock):
            menu = tray._build_menu()

        labels = [call.args[0] for call in pystray_mock.MenuItem.call_args_list if call.args]
        assert menu is not None
        assert "Ziel: Server (Tunnel)" in labels
        assert "Buddha Always-On: Living · aktiviert; Laufstatus nicht geprüft" in labels
        assert "Buddha Always-On aktiviert" in labels
        assert labels.count("Buddha Always-On aktiviert") == 1

    def test_disconnected_menu_reports_unverified_always_on_status(self, tray):
        from hub._services.chat import chat_tray

        tray.state["connected"] = False
        tray.state["compute_turn"] = {
            "active": True, "chat_id": "idle-worker", "priority": "background",
        }
        tray.slots = {"buddha_always_on": {"enabled": True}}
        pystray_mock = MagicMock()
        with patch.object(chat_tray, "pystray", pystray_mock):
            menu = tray._build_menu()

        menu_calls = [call for call in pystray_mock.MenuItem.call_args_list if call.args]
        labels = [call.args[0] for call in menu_calls]
        assert menu is not None
        assert "Buddha Always-On: Nicht verbunden · Status nicht geprüft" in labels
        toggle = next(call for call in menu_calls if call.args[0] == "Buddha Always-On aktiviert")
        assert toggle.kwargs["enabled"] is False

    def test_always_on_toggle_updates_persistent_server_slot(self, tray):
        tray.remote = True
        tray.state["connected"] = True
        tray.slots = {"buddha_always_on": {"enabled": True}}
        with patch.object(tray, "_api", return_value={"ok": True}) as api, \
             patch.object(tray, "_refresh") as refresh, \
             patch.object(tray, "_update_icon") as update_icon:
            tray._toggle_idle()

        api.assert_called_once_with(
            "POST", "/api/slots",
            {"slot_id": "buddha_always_on", "updates": {"enabled": False}},
        )
        refresh.assert_called_once()
        update_icon.assert_called_once()

    def test_always_on_toggle_fails_closed_when_disconnected(self, tray):
        tray.remote = True
        tray.state["connected"] = False
        tray.slots = {"buddha_always_on": {"enabled": True}}
        with patch.object(tray, "_api") as api, \
             patch.object(tray, "_notify_error") as notify:
            tray._toggle_idle()

        api.assert_not_called()
        notify.assert_called_once()

    def test_always_on_runtime_label_uses_compute_turn_evidence(self, tray):
        slot = {"enabled": True}
        tray.state["connected"] = True
        tray.state["compute_turn"] = {
            "active": True, "chat_id": "idle-worker", "priority": "background",
        }
        assert tray._always_on_runtime_label(slot) == "Running · bearbeitet eine Aufgabe"

        tray.state["compute_turn"] = {
            "active": False, "chat_id": None, "priority": None,
        }
        assert tray._always_on_runtime_label(slot) == "Living · aktiviert, wartet"



class TestTraySingleInstance:
    """Single-instance contract (FABLE-SOL-PLAN 1.2.3): a second tray must not start."""

    @staticmethod
    def _mod():
        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }):
            from hub._services.chat import chat_tray
            return chat_tray

    def test_second_acquire_fails_until_first_releases(self, tmp_path):
        mod = self._mod()
        lock_path = tmp_path / "tray.lock"
        first = mod.acquire_single_instance_lock(lock_path)
        assert first is not None
        assert mod.acquire_single_instance_lock(lock_path) is None
        first.close()
        second = mod.acquire_single_instance_lock(lock_path)
        assert second is not None
        second.close()

    def test_default_lock_path_is_stable_across_tmpdirs(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        session_tmpdirs = [tmp_path / "launchd-tmp", tmp_path / "ssh-tmp"]
        for temp_dir in session_tmpdirs:
            temp_dir.mkdir()

        script = """
import sys
import types

modules = {
    name: types.ModuleType(name)
    for name in ("pystray", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont")
}
modules["PIL"].__path__ = []
sys.modules.update(modules)
from hub._services.chat.chat_tray import TRAY_LOCK_FILE
print(TRAY_LOCK_FILE)
"""

        lock_paths = []
        for temp_dir in session_tmpdirs:
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "USERPROFILE": str(home),
                "TMPDIR": str(temp_dir),
                "TEMP": str(temp_dir),
                "TMP": str(temp_dir),
            })
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=SYSTEM_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            lock_paths.append(Path(result.stdout.strip()))

        assert lock_paths == [home / ".bach" / "chat_tray.lock"] * 2

    def test_acquire_creates_lock_parent(self, tmp_path):
        mod = self._mod()
        lock_path = tmp_path / "home" / ".bach" / "chat_tray.lock"

        lock = mod.acquire_single_instance_lock(lock_path)

        assert lock is not None
        assert lock_path.parent.is_dir()
        lock.close()

    def test_main_refuses_a_second_tray_without_running_it(self, monkeypatch, capsys):
        mod = self._mod()
        monkeypatch.setattr(sys, "argv", ["chat_tray.py"])
        monkeypatch.setattr(mod, "acquire_single_instance_lock", lambda *a, **k: None)
        monkeypatch.setattr(mod.BACHTray, "run", lambda self: pytest.fail("run() must not be called"))
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 3
        assert "läuft bereits" in capsys.readouterr().err


class TestTrayIdleWorker:
    """Plan 1.1.3: the idle worker is the only OLLAMA/BUDDHA task executor and was unusable
    on headless hosts (menu-only toggle) and blind to 'open' tasks."""

    @staticmethod
    def _tray(monkeypatch, env):
        for k in ("BACH_IDLE_WORKER",):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with patch.dict('sys.modules', {
            'pystray': MagicMock(),
            'PIL': MagicMock(),
            'PIL.Image': MagicMock(),
            'PIL.ImageDraw': MagicMock(),
            'PIL.ImageFont': MagicMock(),
        }):
            from hub._services.chat.chat_tray import BACHTray
            return BACHTray(host="testhost", port=9999)

    def test_idle_worker_is_on_by_default_and_off_via_env(self, monkeypatch):
        assert self._tray(monkeypatch, {}).idle_enabled is True
        assert self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"}).idle_enabled is True
        assert self._tray(monkeypatch, {"BACH_IDLE_WORKER": "0"}).idle_enabled is False
        assert self._tray(monkeypatch, {"BACH_IDLE_WORKER": "off"}).idle_enabled is False

    def test_idle_worker_picks_open_ollama_task_and_accepts_tool_receipt(self, monkeypatch):
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if method == "GET":
                if path == "/api/tasks?assigned_to=OLLAMA&status=open":
                    return {"success": True, "tasks": [{"id": 42, "title": "T", "description": "D"}]}
                return {"success": True, "tasks": []}
            if method == "POST":
                return {"ok": True, "answer": "done", "completed_task_ids": [42]}
            return {"success": True}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        gets = [p for m, p, _ in calls if m == "GET"]
        assert gets[:2] == ["/api/tasks?assigned_to=OLLAMA&status=pending", "/api/tasks?assigned_to=OLLAMA&status=open"]
        puts = [(p, d["status"]) for m, p, d in calls if m == "PUT"]
        assert puts == [("/api/tasks/42", "in_progress")]
        assert tray.idle_processing is False

    def test_idle_worker_keeps_task_in_progress_when_chat_outcome_is_unknown(self, monkeypatch):
        """A local timeout does not prove that the server stopped processing the request."""
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if method == "GET":
                if path == "/api/tasks?assigned_to=OLLAMA&status=pending":
                    return {"success": True, "tasks": [{"id": 42, "title": "T", "description": "D"}]}
                return {"success": True, "tasks": []}
            if method == "POST":
                assert kw["timeout"] == 300
                return None
            return {"success": True}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        puts = [(p, d["status"]) for m, p, d in calls if m == "PUT"]
        assert puts == [("/api/tasks/42", "in_progress")]
        assert tray.idle_processing is False

    def test_idle_worker_reopens_task_after_confirmed_chat_failure(self, monkeypatch):
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if method == "GET":
                if path == "/api/tasks?assigned_to=OLLAMA&status=pending":
                    return {"success": True, "tasks": [{"id": 42, "title": "T"}]}
                return {"success": True, "tasks": []}
            if method == "POST":
                return {"error": "backend unavailable"}
            return {"success": True}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        puts = [(p, d["status"]) for m, p, d in calls if m == "PUT"]
        assert puts == [("/api/tasks/42", "in_progress"), ("/api/tasks/42", "open")]

    # --- Nachlese nach dem Client-Timeout (T-20260906-739766716) ---

    def _tray_with_pending(self, monkeypatch, task_id=42):
        """Erster Lauf laeuft in den Client-Timeout; der Task ist danach vorgemerkt."""
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})

        def fake_api(method, path, data=None, **kw):
            if method == "GET" and path.startswith("/api/tasks?"):
                if "OLLAMA" in path and "status=pending" in path:
                    return {"success": True,
                            "tasks": [{"id": task_id, "title": "T", "description": "D"}]}
                return {"success": True, "tasks": []}
            return None if method == "POST" else {"success": True}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()
        assert tray.idle_pending[0] == task_id
        return tray

    def test_repeated_task_runs_use_different_timeout_sessions(self, monkeypatch):
        first = self._tray_with_pending(monkeypatch).idle_pending[3]
        second = self._tray_with_pending(monkeypatch).idle_pending[3]
        assert first.startswith("idle-bach-42-")
        assert second.startswith("idle-bach-42-")
        assert first != second, "A new run must never consume an old run's completion"

    @staticmethod
    def _history(*answers):
        messages = [{"role": "user", "content": "Idle-Modus. Task #42: T"}]
        messages += [{"role": "assistant", "content": c, "ok": ok} for c, ok in answers]
        return {"ok": True, "messages": messages}

    def test_idle_worker_books_a_late_answer_after_the_client_timeout(self, monkeypatch):
        """Der Lauf arbeitet nach dem Timeout weiter -- sein Ergebnis darf nicht verloren gehen."""
        tray = self._tray_with_pending(monkeypatch)
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if path.startswith("/api/history"):
                history = self._history(("Wartungscheck erledigt.", True))
                history["messages"][-1]["completed_task_ids"] = [42]
                return history
            return {"success": True, "tasks": []}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        assert [(p, d["status"]) for m, p, d in calls if m == "PUT"] == []
        assert tray.idle_pending is None

    def test_idle_worker_reopens_a_late_failure_instead_of_completing_it(self, monkeypatch):
        """Die Bewertung kommt aus /api/history und ist dieselbe wie bei /api/chat."""
        tray = self._tray_with_pending(monkeypatch)
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if path.startswith("/api/history"):
                return self._history(("Backend-Fehler: Ollama weg", False))
            if path == "/api/tasks/42":
                return {"status": "in_progress"}
            return {"success": True, "tasks": []}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        assert [(p, d["status"]) for m, p, d in calls if m == "PUT"] == [("/api/tasks/42", "open")]
        assert tray.idle_pending is None

    def test_idle_worker_waits_instead_of_starting_a_second_run(self, monkeypatch):
        """Zwei Laeufe teilen sich die Session -- ihre Antworten waeren nicht zuzuordnen."""
        tray = self._tray_with_pending(monkeypatch)
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if path.startswith("/api/history"):
                return self._history()
            return {"success": True, "tasks": []}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        assert [c for c in calls if c[0] in ("PUT", "POST")] == []
        assert tray.idle_pending is not None

    def test_compute_lock_leaves_the_task_in_its_original_status(self, monkeypatch):
        """Kein Load, kein Ergebnis -- also weder completed noch open.

        Der Task war nie in Arbeit; er geht in den Status zurueck, unter dem er
        gezogen wurde, und wird NICHT zur Nachlese vorgemerkt
        (T-20260907-440775748).
        """
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if method == "GET" and path.startswith("/api/tasks?"):
                if "OLLAMA" in path and "status=pending" in path:
                    return {"success": True,
                            "tasks": [{"id": 42, "title": "T", "description": "D"}]}
                return {"success": True, "tasks": []}
            if method == "POST":
                return {"ok": False, "compute_locked": True,
                        "answer": "Compute-Lock aktiv -- kein Modell-Load"}
            return {"success": True}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        assert [(p, d["status"]) for m, p, d in calls if m == "PUT"] == [
            ("/api/tasks/42", "in_progress"), ("/api/tasks/42", "pending")]
        assert tray.idle_pending is None

    def test_compute_lock_leaves_fallback_task_in_original_status(self, monkeypatch):
        """Fallback tasks (expert roles) must also retain task_status on compute lock."""
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if method == "GET" and path.startswith("/api/tasks?"):
                # Standard assignees return empty
                if any(f"assigned_to={a}" in path for a in ("OLLAMA", "BUDDHA", "BACH")):
                    return {"success": True, "tasks": []}
                if "status=open" in path:
                    return {"success": True, "tasks": [{"id": 99, "title": "Expert Work", "assigned_to": "foerderplaner"}]}
                return {"success": True, "tasks": []}
            if method == "POST":
                return {"ok": False, "compute_locked": True, "answer": "Compute-Lock aktiv"}
            return {"success": True}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        assert [(p, d["status"]) for m, p, d in calls if m == "PUT"] == [
            ("/api/tasks/99", "in_progress"), ("/api/tasks/99", "open")]
        assert tray.idle_pending is None

    def test_expired_pending_stops_waiting_and_frees_the_worker(self, monkeypatch):
        """Nach PENDING_TTL gilt wieder das Verhalten von vor dem Fix."""
        tray = self._tray_with_pending(monkeypatch)
        tray.idle_pending = (42, time.time() - tray.PENDING_TTL - 1)
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if path == "/api/tasks/42":
                return {"status": "in_progress"}
            return self._history() if path.startswith("/api/history") else {"success": True, "tasks": []}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        assert tray.idle_pending is None
        assert any(p.startswith("/api/tasks?") for m, p, d in calls), "Worker sucht wieder Arbeit"

    def test_idle_task_picks_filter_match_before_assignee_scan(self, monkeypatch):
        """Ein aktivierter pickup_filter wird vor dem Standard-Assignee-Scan genutzt."""
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})
        tray.slots = {
            "buddha_always_on": {
                "pickup_filter": {
                    "enabled": True,
                    "categories": ["TEST"],
                    "priorities": [],
                    "tags": [],
                    "exclude_tags": [],
                }
            }
        }
        calls = []

        def fake_api(method, path, data=None, **kw):
            calls.append((method, path, data))
            if method == "GET" and path == "/api/tasks?status=pending":
                return {
                    "success": True,
                    "tasks": [
                        {"id": 42, "title": "Filter Task", "description": "D", "category": "TEST"}
                    ],
                }
            if method == "GET" and path.startswith("/api/tasks?"):
                return {"success": True, "tasks": []}
            if method == "POST":
                return {"ok": True, "answer": "FERTIG"}
            return {"success": True}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()

        gets = [p for m, p, _ in calls if m == "GET"]
        assert "/api/tasks?status=pending" in gets
        assert not any("assigned_to=" in p for p in gets), "Assignee-Scan darf nicht durchlaufen"
        puts = [(p, d["status"]) for m, p, d in calls if m == "PUT"]
        assert ("/api/tasks/42", "in_progress") in puts
        assert tray.idle_processing is False

    @pytest.mark.parametrize("route", ["filter", "assignee", "universal"])
    def test_idle_worker_skips_cloud_bound_task_on_every_route(self, monkeypatch, route):
        tray = self._tray(monkeypatch, {"BACH_IDLE_WORKER": "1"})
        tray.slots = {"buddha_always_on": {
            "id": "buddha_always_on", "model": "qwen3.8:27b-mlx",
            "pickup_filter": {"enabled": route == "filter"},
        }}
        task = {"id": 99, "title": "cloud only", "assigned_to": "OLLAMA",
                "required_model": "kimi-k3:cloud"}
        calls = []

        def fake_api(method, path, data=None, **_kw):
            calls.append((method, path))
            if method == "GET":
                if route == "filter" and path == "/api/tasks?status=pending":
                    return {"success": True, "tasks": [task]}
                if route == "assignee" and path == "/api/tasks?assigned_to=OLLAMA&status=pending":
                    return {"success": True, "tasks": [task]}
                if route == "universal" and path == "/api/tasks?status=pending":
                    return {"success": True, "tasks": [task]}
            return {"success": True, "tasks": []}

        with patch.object(tray, "_api", side_effect=fake_api):
            tray._process_idle_task()
        assert not any(method in ("PUT", "POST") for method, _ in calls)
