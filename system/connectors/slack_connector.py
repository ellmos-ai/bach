#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SlackConnector — Slack Bot API & Incoming Webhook Connector
===========================================================

Implementiert BaseConnector für Slack (inspiriert von OpenClaw und Hermes Agent).
Dual-Modus:
1. Bot-Modus (bidirektional): Nutzt Bot Token (xoxb-...) für chat.postMessage
   und conversations.history.
2. Webhook-Modus (nur senden): Nutzt Incoming Webhook URL (https://hooks.slack.com/...).

Nur Python Standardbibliothek (urllib, json, threading) — keine externen Abhängigkeiten.

Schnellstart Bot-Modus:

    import os
    from connectors.base import ConnectorConfig
    from connectors.slack_connector import SlackConnector

    config = ConnectorConfig(
        name="slack_main",
        connector_type="slack",
        auth_type="token",
        auth_config={"bot_token": os.environ["SLACK_BOT_TOKEN"]},
        options={"default_channel": "C12345678"},
    )
    bot = SlackConnector(config)
    if bot.connect():
        bot.send_message("C12345678", "Hallo aus ELLMOS!")
        thread, stop = bot.poll_threaded(on_message=lambda m: print(m.content))

Schnellstart Webhook-Modus:

    config = ConnectorConfig(
        name="slack_webhook",
        connector_type="slack",
        endpoint=os.environ["SLACK_WEBHOOK_URL"],
    )
    bot = SlackConnector(config)
    bot.connect()
    bot.send_message("", "Hallo via Slack Webhook!")

MIT License — siehe LICENSE
"""

import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import List, Optional, Callable, Tuple, Dict, Any

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    Message,
    SecretAdapter,
)


class SlackConnector(BaseConnector):
    """Slack Bot API und Webhook Connector."""

    API_BASE = "https://slack.com/api"

    def __init__(
        self,
        config: ConnectorConfig,
        secret_adapter: Optional[SecretAdapter] = None,
    ):
        super().__init__(config, secret_adapter)
        self._bot_token = self._resolve_secret(config.auth_config, "bot_token")
        self._webhook_url = config.endpoint or self._resolve_secret(
            config.auth_config, "webhook_url"
        )
        self._default_channel = config.options.get("default_channel", "")
        self._bot_info: Optional[Dict[str, Any]] = None
        self._last_ts = config.options.get("last_ts", "")
        self._polling = False

    def connect(self) -> bool:
        """Verbindung prüfen.

        Bot-Modus: Ruft https://slack.com/api/auth.test auf.
        Webhook-Modus: Prüft Vorhandensein der Hook-URL.
        """
        if self._bot_token:
            url = f"{self.API_BASE}/auth.test"
            headers = {
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("ok"):
                        self._bot_info = data
                        self._status = ConnectorStatus.CONNECTED
                        return True
                    self._status = ConnectorStatus.ERROR
                    return False
            except Exception:
                self._status = ConnectorStatus.ERROR
                return False

        if self._webhook_url and self._webhook_url.startswith("https://hooks.slack.com/"):
            self._status = ConnectorStatus.CONNECTED
            return True

        self._status = ConnectorStatus.ERROR
        return False

    def disconnect(self) -> bool:
        """Verbindung trennen."""
        self._polling = False
        self._status = ConnectorStatus.DISCONNECTED
        return True

    def send_message(
        self,
        recipient: str,
        content: str,
        attachments: Optional[List[str]] = None,
    ) -> bool:
        """Nachricht an Channel oder Webhook senden."""
        self._warn_attachments_unsupported(attachments)

        # 1. Bot-Modus hat Vorrang wenn Token vorhanden
        if self._bot_token:
            channel = recipient or self._default_channel
            if not channel:
                return False
            url = f"{self.API_BASE}/chat.postMessage"
            payload = json.dumps({"channel": channel, "text": content}).encode("utf-8")
            headers = {
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    return bool(res.get("ok"))
            except Exception:
                return False

        # 2. Webhook-Modus
        if self._webhook_url:
            data_dict: Dict[str, Any] = {"text": content}
            if recipient:
                data_dict["channel"] = recipient
            payload = json.dumps(data_dict).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=utf-8"}
            req = urllib.request.Request(
                self._webhook_url, data=payload, headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return resp.status == 200
            except Exception:
                return False

        return False

    def get_messages(
        self, since: Optional[str] = None, limit: int = 50
    ) -> List[Message]:
        """Nachrichten aus dem konfigurierten default_channel abrufen."""
        if not self._bot_token or not self._default_channel:
            return []

        url = f"{self.API_BASE}/conversations.history?channel={self._default_channel}&limit={min(limit, 100)}"
        if since:
            try:
                dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                url += f"&oldest={dt.timestamp()}"
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data.get("ok"):
                    return []
                raw_msgs = data.get("messages", [])
                result: List[Message] = []
                for m in reversed(raw_msgs):
                    ts = m.get("ts", "")
                    if m.get("type") == "message" and not m.get("subtype"):
                        iso_ts = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
                        result.append(
                            Message(
                                channel="slack",
                                sender=m.get("user", ""),
                                content=m.get("text", ""),
                                timestamp=iso_ts,
                                direction="in",
                                message_id=ts,
                                metadata={"team": self._bot_info.get("team_id", "") if self._bot_info else ""},
                            )
                        )
                        self._last_ts = ts
                return result
        except Exception:
            return []

    def poll_threaded(
        self, on_message: Callable[[Message], None], interval: float = 5.0
    ) -> Tuple[threading.Thread, Callable[[], None]]:
        """Startet einen Hintergrundthread für Polling."""
        self._polling = True

        def _worker():
            while self._polling:
                try:
                    msgs = self.get_messages(limit=20)
                    for msg in msgs:
                        on_message(msg)
                except Exception:
                    pass
                time.sleep(interval)

        thread = threading.Thread(target=_worker, daemon=True, name="SlackPollThread")
        thread.start()

        def stop():
            self._polling = False

        return thread, stop
