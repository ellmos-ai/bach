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
WhatsAppConnector - WhatsApp Business API Connector fuer BACH
==============================================================

Implementiert BaseConnector fuer WhatsApp Business API.
Unterstuetzt Baileys (WhatsApp Web) oder offizielle Business API.

Implementiert BaseConnector fuer WhatsApp Business API.

Verwendung:
    from connectors.whatsapp_connector import WhatsAppConnector
    from connectors.base import ConnectorConfig

    config = ConnectorConfig(
        name="whatsapp_main",
        connector_type="whatsapp",
        auth_type="api_key",
        auth_config={"api_token": "YOUR_BUSINESS_API_TOKEN", "phone_number_id": "123456789"},
        options={"mode": "business_api", "webhook_verify_token": "your_verify_token"}
    )
    connector = WhatsAppConnector(config)
    connector.connect()
    messages = connector.get_messages()
    connector.send_message("49123456789@s.whatsapp.net", "Hallo von BACH!")
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


class WhatsAppConnector(BaseConnector):
    """WhatsApp Business API Connector mit Polling-Runtime."""

    # WhatsApp Business API
    API_BASE = "https://graph.facebook.com/v18.0"

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self._api_token = config.auth_config.get("api_token", "")
        self._phone_number_id = config.auth_config.get("phone_number_id", "")
        self._mode = config.options.get("mode", "business_api")  # oder "baileys"
        self._session_data = None
        self._polling = False

    def connect(self) -> bool:
        """Verbindung pruefen."""
        if not self._api_token or not self._phone_number_id:
            self._status = ConnectorStatus.ERROR
            return False

        self._status = ConnectorStatus.CONNECTING
        try:
            # Verbindung testen via Account-Info
            url = f"{self.API_BASE}/{self._phone_number_id}"
            headers = {"Authorization": f"Bearer {self._api_token}"}
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result:
                    self._session_data = result
            self._status = ConnectorStatus.CONNECTED
            return True
        except Exception as e:
            print(f"[WhatsApp connect Error] {type(e).__name__}: {e}", file=sys.stderr)

        self._status = ConnectorStatus.ERROR
        return False

    def disconnect(self) -> bool:
        """Verbindung trennen."""
        self._polling = False
        self._status = ConnectorStatus.DISCONNECTED
        return True

    def send_message(self, recipient: str, content: str,
                     attachments: Optional[List[str]] = None) -> bool:
        """Nachricht senden."""
        try:
            url = f"{self.API_BASE}/{self._phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": content}
            }

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers)

            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result is not None
        except Exception as e:
            print(f"[WhatsApp send_message Error] {type(e).__name__}: {e}", file=sys.stderr)
            return False

    def get_messages(self, since: Optional[str] = None,
                     limit: int = 50) -> List[Message]:
        """Neue Nachrichten abrufen."""
        try:
            # WhatsApp Business API verwendet Webhooks fuer eingehende Nachrichten
            return []
        except Exception as e:
            print(f"[WhatsApp get_messages Error] {type(e).__name__}: {e}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Polling Runtime (optional - kann entfernt werden wenn nicht benoetigt)
    # ------------------------------------------------------------------

    def poll_loop(self, on_message: Callable[[Message], None],
                  interval: float = 5.0, stop_event: threading.Event = None):
        """Blockierender Polling-Loop. Ruft on_message() fuer jede neue Nachricht auf."""
        self._polling = True
        while self._polling and not (stop_event and stop_event.is_set()):
            try:
                messages = self.get_messages()
                for msg in messages:
                    try:
                        on_message(msg)
                    except Exception as e:
                        print(f"[WhatsApp on_message callback Error] {type(e).__name__}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[WhatsApp poll_loop Error] {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(interval)

    def poll_threaded(self, on_message: Callable[[Message], None],
                      interval: float = 5.0) -> Tuple[threading.Thread, threading.Event]:
        """Startet Polling in eigenem Thread. Gibt (Thread, StopEvent) zurueck."""
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.poll_loop,
            args=(on_message, interval, stop_event),
            daemon=True, name="bach-whatsapp-poll")
        thread.start()
        return thread, stop_event

    # ------------------------------------------------------------------
    # Internal Helper Methods
    # ------------------------------------------------------------------

    def _api_call(self, method: str, endpoint: str, data: dict = None) -> any:
        """WhatsApp Business API aufrufen."""
        url = f"{self.API_BASE}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json"
        }

        if data:
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        else:
            req = urllib.request.Request(url, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[WhatsApp API Error] {endpoint}: {e}", file=sys.stderr)
            return None

    def process_webhook(self, webhook_data: dict) -> List[Message]:
        """Webhook-Daten von WhatsApp Business API verarbeiten."""
        messages = []

        try:
            entry = webhook_data.get("entry", [])
            for e in entry:
                changes = e.get("changes", [])
                for change in changes:
                    value = change.get("value", {})
                    msgs = value.get("messages", [])

                    for msg in msgs:
                        if msg.get("type") == "text":
                            messages.append(Message(
                                channel="whatsapp",
                                sender=msg.get("from", ""),
                                content=msg.get("text", {}).get("body", ""),
                                timestamp=datetime.fromtimestamp(int(msg.get("timestamp", 0))).isoformat(),
                                direction="in",
                                message_id=msg.get("id", ""),
                                metadata={"type": msg.get("type", "text")}
                            ))
        except Exception as e:
            print(f"[WhatsApp Webhook Error] {e}", file=sys.stderr)

        return messages
