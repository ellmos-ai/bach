# -*- coding: utf-8 -*-
"""
iMessageConnector — macOS Messages (iMessage & SMS) Connector
============================================================

Implementiert BaseConnector für macOS iMessage (inspiriert von OpenClaw).
Ermöglicht das Senden von iMessages via AppleScript (osascript) und das
Auslesen von Nachrichten direkt aus der lokalen SQLite-Datenbank (~/Library/Messages/chat.db).

Plattform-Anforderung: macOS (Darwin) für Live-Betrieb.
Auf Nicht-macOS-Systemen (Windows, Linux) wird der Connector als inaktiv
geführt (fail-closed, ConnectorStatus.DISCONNECTED / ERROR), es sei denn,
ein custom chat_db_path und Mock-Subprozesse werden für Tests übergeben.

Nur Python Standardbibliothek (sqlite3, subprocess, os, datetime) — keine externen Abhängigkeiten.

Schnellstart:

    from connectors.base import ConnectorConfig
    from connectors.imessage_connector import iMessageConnector

    config = ConnectorConfig(
        name="imessage_mac",
        connector_type="imessage",
        options={"default_recipient": "+491701234567"},
    )
    conn = iMessageConnector(config)
    if conn.connect():
        conn.send_message("+491701234567", "Hallo aus ELLMOS / BACH!")
        msgs = conn.get_messages(limit=10)

MIT License — siehe LICENSE / THIRD_PARTY_LICENSES.md
"""

import os
import sys
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Callable, Tuple, Dict, Any

from connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    Message,
    SecretAdapter,
)

# Apple Cocoa Core Data Epoch Offset (2001-01-01 00:00:00 UTC in Unix seconds)
APPLE_EPOCH_OFFSET = 978307200.0


def _apple_time_to_iso(apple_date: int) -> str:
    """Konvertiert Apple chat.db Timestamp (Nanosekunden oder Sekunden seit 2001) nach ISO-8601."""
    if not apple_date:
        return datetime.now(timezone.utc).isoformat()
    # Moderne macOS Versionen (ab High Sierra) nutzen Nanosekunden
    if apple_date > 10**11:
        seconds = (apple_date / 1_000_000_000.0) + APPLE_EPOCH_OFFSET
    else:
        seconds = float(apple_date) + APPLE_EPOCH_OFFSET
    try:
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _iso_to_apple_time(iso_str: str) -> int:
    """Konvertiert ISO-8601 Timestamp in Apple Nanosekunden seit 2001-01-01."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        unix_ts = dt.timestamp()
        apple_sec = unix_ts - APPLE_EPOCH_OFFSET
        return int(apple_sec * 1_000_000_000)
    except Exception:
        return 0


class iMessageConnector(BaseConnector):
    """macOS iMessage Connector via SQLite chat.db und osascript."""

    DEFAULT_DB_PATH = Path("~/Library/Messages/chat.db").expanduser()

    def __init__(
        self,
        config: ConnectorConfig,
        secret_adapter: Optional[SecretAdapter] = None,
    ):
        super().__init__(config, secret_adapter)
        db_opt = config.options.get("chat_db_path")
        self._db_path = Path(db_opt).expanduser() if db_opt else self.DEFAULT_DB_PATH
        self._default_recipient = config.options.get("default_recipient", "")
        self._service_name = config.options.get("service", "iMessage")
        self._polling = False
        self._last_seen_rowid = 0

    def is_darwin(self) -> bool:
        """Prüft ob die aktuelle Plattform macOS ist."""
        return sys.platform == "darwin"

    def connect(self) -> bool:
        """Prüft Verfügbarkeit von macOS und Lesbarkeit von chat.db."""
        # Auf Darwin: Standardpfad oder custom Pfad prüfen
        # Auf Nicht-Darwin: Erlaubt wenn custom DB-Pfad existiert (z.B. für Tests)
        if not self.is_darwin() and not self._db_path.exists():
            self._status = ConnectorStatus.ERROR
            return False

        if self._db_path.exists():
            try:
                # Prüfe Lesezugriff auf SQLite Datenbank
                conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message';")
                row = cur.fetchone()
                conn.close()
                if row:
                    self._status = ConnectorStatus.CONNECTED
                    return True
            except Exception:
                self._status = ConnectorStatus.ERROR
                return False

        # Wenn auf macOS, aber DB noch nicht existiert / Full Disk Access fehlt
        if self.is_darwin():
            # osascript könnte immer noch für Senden funktionieren
            self._status = ConnectorStatus.CONNECTED
            return True

        self._status = ConnectorStatus.ERROR
        return False

    def disconnect(self) -> bool:
        """Verbindung trennen / Polling stoppen."""
        self._polling = False
        self._status = ConnectorStatus.DISCONNECTED
        return True

    def send_message(
        self,
        recipient: str,
        content: str,
        attachments: Optional[List[str]] = None,
    ) -> bool:
        """Sendet eine iMessage via osascript AppleScript.

        Args:
            recipient: Telefonnummer (z. B. '+491701234567') oder Apple ID E-Mail.
            content: Der Nachrichtentext.
            attachments: Dateianhänge (derzeit noch nicht über AppleScript unterstützt).
        """
        self._warn_attachments_unsupported(attachments)
        target = recipient or self._default_recipient
        if not target or not content:
            return False

        if not self.is_darwin():
            # Auf Nicht-macOS kann AppleScript nicht ausgeführt werden
            return False

        apple_script = """
        on run argv
            set targetRecipient to item 1 of argv
            set targetContent to item 2 of argv
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant targetRecipient of targetService
                send targetContent to targetBuddy
            end tell
        end run
        """
        try:
            res = subprocess.run(
                ["osascript", "-e", apple_script, target, content],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    def get_messages(
        self,
        since: Optional[str] = None,
        limit: int = 50,
    ) -> List[Message]:
        """Liest die neuesten Nachrichten aus chat.db aus.

        Args:
            since: ISO-8601 Zeitstempel oder None.
            limit: Maximale Anzahl zurückzugebender Nachrichten (Standard 50).
        """
        if not self._db_path.exists():
            return []

        try:
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            query = """
                SELECT
                    m.ROWID as row_id,
                    m.guid,
                    m.text,
                    COALESCE(h.id, 'me') as sender,
                    m.date as apple_date,
                    m.is_from_me
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.text IS NOT NULL AND length(m.text) > 0
            """
            params: List[Any] = []

            if since:
                min_apple_nano = _iso_to_apple_time(since)
                if min_apple_nano > 0:
                    query += " AND m.date > ?"
                    params.append(min_apple_nano)

            query += " ORDER BY m.date DESC LIMIT ?"
            params.append(min(limit, 200))

            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()

            messages: List[Message] = []
            for row in reversed(rows):
                iso_ts = _apple_time_to_iso(row["apple_date"])
                direction = "out" if row["is_from_me"] else "in"
                messages.append(
                    Message(
                        channel="imessage",
                        sender=row["sender"] if direction == "in" else "me",
                        content=row["text"],
                        timestamp=iso_ts,
                        direction=direction,
                        message_id=str(row["guid"] or row["row_id"]),
                        metadata={
                            "row_id": row["row_id"],
                            "is_from_me": bool(row["is_from_me"]),
                        },
                    )
                )
                if row["row_id"] > self._last_seen_rowid:
                    self._last_seen_rowid = row["row_id"]

            return messages
        except Exception:
            return []

    def poll_threaded(
        self,
        on_message: Callable[[Message], None],
        interval: float = 3.0,
    ) -> Tuple[threading.Thread, Callable[[], None]]:
        """Startet Polling-Thread für eingehende iMessages."""
        self._polling = True

        def _worker():
            while self._polling:
                try:
                    msgs = self.get_messages(limit=20)
                    for msg in msgs:
                        # Nur eingehende Nachrichten weiterleiten
                        if msg.direction == "in":
                            on_message(msg)
                except Exception:
                    pass
                time.sleep(interval)

        thread = threading.Thread(target=_worker, daemon=True, name="iMessagePollThread")
        thread.start()

        def stop():
            self._polling = False

        return thread, stop
