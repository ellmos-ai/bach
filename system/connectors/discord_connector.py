#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
Tool: discord_connector
Version: 1.1.0
Author: BACH Team
Created: 2026-02-08
Updated: 2026-02-08
Anthropic-Compatible: True

Description:
    Discord Bot Connector fuer BACH auf Basis BaseConnector.
    Dual-Modus: Bot-API (bidirektional) oder Webhook (nur senden).
    Bot-Modus unterstuetzt Polling-Loop fuer eingehende Nachrichten.

Verwendung:
    from connectors.discord_connector import DiscordConnector
    from connectors.base import ConnectorConfig

    # Bot-Modus (bidirektional):
    config = ConnectorConfig(
        name="discord_main",
        connector_type="discord",
        auth_type="api_key",
        auth_config={"bot_token": "YOUR_BOT_TOKEN"},
        options={"default_channel": "CHANNEL_ID"}
    )
    bot = DiscordConnector(config)
    bot.connect()
    bot.send_message("channel_id", "Hallo von BACH!")
    thread, stop = bot.poll_threaded(on_message=callback, interval=10)

    # Webhook-Modus (nur senden):
    config = ConnectorConfig(
        name="discord_webhook",
        connector_type="discord",
        endpoint="https://discord.com/api/webhooks/...",
    )
"""

import os
import sys
import json
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime
from typing import List, Optional, Callable, Tuple

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from connectors.base import BaseConnector, ConnectorConfig, ConnectorStatus, Message


class DiscordConnector(BaseConnector):
    """Discord Bot/Webhook Connector mit Polling-Runtime."""

    API_BASE = "https://discord.com/api/v10"

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self._bot_token = config.auth_config.get("bot_token", "")
        self._webhook_url = config.endpoint  # Optional: Discord Webhook URL
        self._bot_info = None
        self._last_message_id = config.options.get("last_message_id", "")
        self._polling = False

    def connect(self) -> bool:
        """Verbindung pruefen via /users/@me."""
        if not self._bot_token and not self._webhook_url:
            self._status = ConnectorStatus.ERROR
            return False

        self._status = ConnectorStatus.CONNECTING

        if self._bot_token:
            try:
                result = self._api_call("GET", "/users/@me")
                if result:
                    self._bot_info = result
                    self._status = ConnectorStatus.CONNECTED
                    return True
            except Exception:
                pass
        elif self._webhook_url:
            # Webhook-Modus: Nur senden moeglich
            self._status = ConnectorStatus.CONNECTED
            return True

        self._status = ConnectorStatus.ERROR
        return False

    def disconnect(self) -> bool:
        self._polling = False
        self._status = ConnectorStatus.DISCONNECTED
        return True

    def send_message(self, recipient: str, content: str,
                     attachments: Optional[List[str]] = None) -> bool:
        """Nachricht an Channel senden (via Bot oder Webhook)."""
        if self._webhook_url:
            return self._send_webhook(content)

        if self._bot_token:
            return self._send_bot(recipient, content)

        return False

    def get_messages(self, since: Optional[str] = None,
                     limit: int = 50) -> List[Message]:
        """Nachrichten aus einem Channel abrufen (nur Bot-Modus)."""
        if not self._bot_token:
            return []

        # Braucht Channel-ID - aus config.options holen
        channel_id = self.config.options.get("default_channel", "")
        if not channel_id:
            return []

        try:
            params = f"?limit={min(limit, 100)}"
            if since:
                params += f"&after={since}"

            result = self._api_call("GET", f"/channels/{channel_id}/messages{params}")
            if not result or not isinstance(result, list):
                return []

            messages = []
            for msg in result:
                author = msg.get("author", {})
                # Eigene Bot-Nachrichten ignorieren
                if self._bot_info and author.get("id") == self._bot_info.get("id"):
                    continue
                msg_id = msg.get("id", "")
                messages.append(Message(
                    channel="discord",
                    sender=author.get("username", "unknown"),
                    content=msg.get("content", ""),
                    timestamp=msg.get("timestamp", ""),
                    direction="in",
                    message_id=msg_id,
                    metadata={
                        "channel_id": msg.get("channel_id", ""),
                        "author_id": author.get("id", ""),
                        "guild_id": msg.get("guild_id", ""),
                    }
                ))
                # Letzten Message-ID tracken fuer inkrementelles Polling
                if msg_id:
                    self._last_message_id = msg_id

            return messages
        except Exception:
            return []

    def get_new_messages(self) -> List[Message]:
        """Nur neue Nachrichten seit letztem Poll abrufen (inkrementell)."""
        if not self._bot_token:
            return []

        channel_id = self.config.options.get("default_channel", "")
        if not channel_id:
            return []

        try:
            params = "?limit=50"
            if self._last_message_id:
                params += f"&after={self._last_message_id}"

            result = self._api_call("GET", f"/channels/{channel_id}/messages{params}")
            if not result or not isinstance(result, list):
                return []

            messages = []
            for msg in result:
                author = msg.get("author", {})
                if self._bot_info and author.get("id") == self._bot_info.get("id"):
                    continue
                msg_id = msg.get("id", "")
                messages.append(Message(
                    channel="discord",
                    sender=author.get("username", "unknown"),
                    content=msg.get("content", ""),
                    timestamp=msg.get("timestamp", ""),
                    direction="in",
                    message_id=msg_id,
                    metadata={
                        "channel_id": msg.get("channel_id", ""),
                        "author_id": author.get("id", ""),
                        "guild_id": msg.get("guild_id", ""),
                    }
                ))
                if msg_id:
                    self._last_message_id = msg_id

            return messages
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Polling Runtime
    # ------------------------------------------------------------------

    def poll_loop(self, on_message: Callable[[Message], None],
                  interval: float = 10.0, stop_event: threading.Event = None):
        """Blockierender Polling-Loop fuer eingehende Nachrichten.

        interval: Sekunden zwischen Polls (Standard: 10, Discord Rate-Limit beachten)
        stop_event: threading.Event zum Stoppen
        """
        self._polling = True
        while self._polling and not (stop_event and stop_event.is_set()):
            try:
                messages = self.get_new_messages()
                for msg in messages:
                    try:
                        on_message(msg)
                    except Exception as e:
                        print(f"[Discord on_message callback Error] {type(e).__name__}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[Discord poll_loop Error] {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(interval)

    def poll_threaded(self, on_message: Callable[[Message], None],
                      interval: float = 10.0) -> Tuple[threading.Thread, threading.Event]:
        """Startet Polling in eigenem Thread. Gibt (Thread, StopEvent) zurueck."""
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.poll_loop,
            args=(on_message, interval, stop_event),
            daemon=True, name="bach-discord-poll")
        thread.start()
        return thread, stop_event

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _api_call(self, method: str, endpoint: str, data: dict = None):
        url = f"{self.API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bot {self._bot_token}",
            "Content-Type": "application/json",
        }

        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            return None
        except urllib.error.URLError:
            return None

    def _send_bot(self, channel_id: str, content: str) -> bool:
        result = self._api_call("POST", f"/channels/{channel_id}/messages",
                                {"content": content})
        return result is not None

    def _send_webhook(self, content: str) -> bool:
        data = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._webhook_url, data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except Exception:
            return False
