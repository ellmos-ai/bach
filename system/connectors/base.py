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
Connector Base Interface
========================

Abstrakte Basisklasse fuer alle BACH-Connectors (Signal, Discord, etc.).
Jeder Connector implementiert dieses Interface.

Verwendung:
    class SignalConnector(BaseConnector):
        def connect(self) -> bool: ...
        def send_message(self, recipient, content) -> bool: ...
        ...
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class ConnectorStatus(Enum):
    """Status eines Connectors."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class Message:
    """Einheitliches Nachrichtenformat fuer alle Channels."""
    channel: str            # "signal", "whatsapp", "discord", "telegram"
    sender: str             # Absender-ID (Telefonnummer, User-ID, etc.)
    content: str            # Nachrichtentext
    timestamp: str          # ISO-8601
    attachments: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    direction: str = "in"   # "in" oder "out"
    message_id: str = ""    # Channel-spezifische ID


@dataclass
class ConnectorConfig:
    """Konfiguration fuer einen Connector."""
    name: str               # Eindeutiger Name (z.B. "signal_main")
    connector_type: str     # "signal", "discord", "whatsapp", etc.
    endpoint: str = ""      # URL oder Pfad
    auth_type: str = "none" # "none", "api_key", "oauth", "token"
    # repr=False: auth_config enthaelt Secrets — darf nie in repr()/Logs landen
    # (Rueckangleichung aus .MODULES/connectors v1.1.0, 2026-07-04)
    auth_config: Dict[str, str] = field(default_factory=dict, repr=False)
    options: Dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Abstrakte Basisklasse fuer BACH Connectors."""

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._status = ConnectorStatus.DISCONNECTED

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def connector_type(self) -> str:
        return self.config.connector_type

    @property
    def status(self) -> ConnectorStatus:
        return self._status

    @abstractmethod
    def connect(self) -> bool:
        """Verbindung herstellen. Returns True bei Erfolg."""
        ...

    @abstractmethod
    def disconnect(self) -> bool:
        """Verbindung trennen. Returns True bei Erfolg."""
        ...

    @abstractmethod
    def send_message(self, recipient: str, content: str,
                     attachments: Optional[List[str]] = None) -> bool:
        """Nachricht senden. Returns True bei Erfolg."""
        ...

    @abstractmethod
    def get_messages(self, since: Optional[str] = None,
                     limit: int = 50) -> List[Message]:
        """Nachrichten abrufen seit Zeitstempel (ISO-8601)."""
        ...

    def get_status(self) -> ConnectorStatus:
        """Aktuellen Status abfragen."""
        return self._status

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} status={self._status.value}>"
