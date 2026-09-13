# SPDX-License-Identifier: MIT
"""Lokale Notify-Dispatcher-Funktionen fuer BACH.

Dieses Modul ersetzt den Import aus ``assistant_core`` fuer die Notify-Wave,
solange assistant-core selbst diese Domain noch nicht exportiert (Wave 1).
Es verwendet ausschliesslich die Python-Standardbibliothek und existierende
BACH-Komponenten (z.B. hub.connector fuer Telegram).
"""

from __future__ import annotations

import json
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Callable, Optional

# Kanonische Notification-Channels
CHANNELS = {"telegram", "discord", "slack", "webhook", "email"}


def resolve_secret_refs(
    auth_config: str | dict,
    secret_resolver: Callable[[str], Optional[str]],
) -> dict:
    """Liest JSON-Config und ersetzt ``${KEY}``-Referenzen via secret_resolver."""
    data: dict = {}
    if auth_config:
        try:
            data = json.loads(auth_config) if isinstance(auth_config, str) else dict(auth_config)
        except (TypeError, json.JSONDecodeError):
            data = {}
    if not isinstance(data, dict):
        data = {}

    def _replace(value):
        if not isinstance(value, str):
            return value
        return re.sub(
            r"\$\{([^}]+)\}",
            lambda m: secret_resolver(m.group(1)) or m.group(0),
            value,
        )

    return {k: _replace(v) for k, v in data.items()}


def tag_text(text: str, channel: str, storage) -> str:
    """Haengt sender_tag aus dem Storage an den Text an."""
    try:
        tag = storage.sender_tag(channel)
    except Exception:
        tag = ""
    if tag:
        return f"[{tag}] {text}"
    return text


def _http_post_json(url: str, payload: dict) -> bool:
    """Sendet JSON per POST an URL; True bei HTTP 2xx."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BACH-Notify/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def send_webhook(url: str, text: str, source: str = "bach") -> bool:
    return _http_post_json(url, {"text": text, "source": source})


def send_discord_webhook(url: str, text: str) -> bool:
    return _http_post_json(url, {"content": text})


def send_slack(webhook_url: str, text: str) -> bool:
    return _http_post_json(webhook_url, {"text": text})


def send_telegram(text: str, storage, connector_factory: Callable[[], object]) -> bool:
    """Sendet ueber einen BACH-Telegram-Connector.

    ``connector_factory`` sollte eine Callable sein, die einen TelegramConnector
    zurueckgibt (inklusive Bot-Token und owner_chat_id in der Config).
    """
    try:
        connector = connector_factory()
        if connector is None:
            return False
        if hasattr(connector, "connect"):
            connector.connect()
        if hasattr(connector, "send_message"):
            return connector.send_message("", text)
        return False
    except Exception:
        return False


def send_email(
    smtp_server: str,
    auth_config: str,
    text: str,
    secret_resolver: Callable[[str], Optional[str]],
    subject: str = "BACH Benachrichtigung",
) -> bool:
    """Sendet E-Mail via SMTP."""
    try:
        cfg = resolve_secret_refs(auth_config, secret_resolver)
        port = int(cfg.get("port", 587))
        username = cfg.get("username", "")
        password = cfg.get("password", "")
        sender = cfg.get("from", username) or username
        recipient = cfg.get("to", "")
        if not recipient:
            return False

        msg = EmailMessage()
        msg.set_content(text)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient

        with smtplib.SMTP(smtp_server, port, timeout=30) as server:
            server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(msg)
        return True
    except Exception:
        return False
