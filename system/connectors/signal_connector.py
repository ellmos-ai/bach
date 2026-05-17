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
SignalConnector - Signal Messenger Connector fuer BACH
========================================================

Implementiert BaseConnector fuer Signal Messenger via signal-cli.
Benoetigt: signal-cli installiert und konfiguriert auf dem System.

Verwendung:
    from connectors.signal_connector import SignalConnector
    from connectors.base import ConnectorConfig

    config = ConnectorConfig(
        name="signal_main",
        connector_type="signal",
        auth_type="none",
        auth_config={"phone_number": "+491234567890"},
        options={"signal_cli_path": "/usr/local/bin/signal-cli"}
    )
    connector = SignalConnector(config)
    connector.connect()
    messages = connector.get_messages()
    connector.send_message("+491234567890", "Hallo von BACH!")
"""

import os
import sys
import json
import time
import threading
import subprocess
from datetime import datetime
from typing import List, Optional, Callable, Tuple

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from connectors.base import BaseConnector, ConnectorConfig, ConnectorStatus, Message


class SignalConnector(BaseConnector):
    """Signal Messenger Connector mit signal-cli."""

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self._phone_number = config.auth_config.get("phone_number", "")
        self._signal_cli_path = config.options.get("signal_cli_path", "signal-cli")
        self._last_timestamp = config.options.get("last_timestamp", 0)
        self._polling = False

    def connect(self) -> bool:
        """Verbindung pruefen via signal-cli."""
        if not self._phone_number:
            self._status = ConnectorStatus.ERROR
            return False

        self._status = ConnectorStatus.CONNECTING
        try:
            # Pruefen ob signal-cli verfuegbar ist
            result = subprocess.run(
                [self._signal_cli_path, "--version"],
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=5
            )
            if result.returncode == 0:
                self._status = ConnectorStatus.CONNECTED
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"[Signal connect Error] signal-cli nicht gefunden oder Timeout: {e}", file=sys.stderr)

        self._status = ConnectorStatus.ERROR
        return False

    def disconnect(self) -> bool:
        """Verbindung trennen."""
        self._polling = False
        self._status = ConnectorStatus.DISCONNECTED
        return True

    def send_message(self, recipient: str, content: str,
                     attachments: Optional[List[str]] = None) -> bool:
        """Nachricht senden via signal-cli."""
        try:
            cmd = [
                self._signal_cli_path,
                "-a", self._phone_number,
                "send",
                "-m", content,
                recipient
            ]

            # Attachments hinzufuegen wenn vorhanden
            if attachments:
                for attachment in attachments:
                    cmd.extend(["-a", attachment])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            print(f"[Signal send_message Error] {type(e).__name__}: {e}", file=sys.stderr)
            return False

    def get_messages(self, since: Optional[str] = None,
                     limit: int = 50) -> List[Message]:
        """Neue Nachrichten abrufen via signal-cli receive."""
        try:
            cmd = [
                self._signal_cli_path,
                "-a", self._phone_number,
                "receive",
                "--json"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                timeout=30
            )

            if result.returncode != 0:
                return []

            messages = []

            # signal-cli gibt JSON-Lines zurueck (eine JSON-Zeile pro Nachricht)
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue

                try:
                    envelope = json.loads(line)

                    # Nur sync- und data-Messages verarbeiten
                    if 'envelope' not in envelope:
                        continue

                    env = envelope['envelope']

                    # Timestamp pruefen (Signal verwendet Millisekunden)
                    timestamp = env.get('timestamp', 0)
                    if timestamp <= self._last_timestamp:
                        continue

                    self._last_timestamp = max(self._last_timestamp, timestamp)

                    # Data-Message extrahieren
                    data_msg = env.get('dataMessage')
                    if not data_msg:
                        continue

                    msg_text = data_msg.get('message', '')
                    if not msg_text:
                        continue

                    sender = env.get('source', '') or env.get('sourceNumber', '')

                    messages.append(Message(
                        channel="signal",
                        sender=sender,
                        content=msg_text,
                        timestamp=datetime.fromtimestamp(timestamp / 1000).isoformat(),
                        direction="in",
                        message_id=str(timestamp),
                        metadata={
                            "source_device": env.get('sourceDevice', 0),
                            "timestamp_ms": timestamp
                        }
                    ))

                except json.JSONDecodeError:
                    continue

            return messages[:limit]

        except Exception as e:
            print(f"[Signal get_messages Error] {type(e).__name__}: {e}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Polling Runtime
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
                        print(f"[Signal on_message callback Error] {type(e).__name__}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[Signal poll_loop Error] {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(interval)

    def poll_threaded(self, on_message: Callable[[Message], None],
                      interval: float = 5.0) -> Tuple[threading.Thread, threading.Event]:
        """Startet Polling in eigenem Thread. Gibt (Thread, StopEvent) zurueck."""
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self.poll_loop,
            args=(on_message, interval, stop_event),
            daemon=True, name="bach-signal-poll")
        thread.start()
        return thread, stop_event
