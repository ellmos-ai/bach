#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""BACH CLI facade for the neutral assistant-core notification service.

The BACH-owned SQLite adapter lives in ``hub.notify_storage``.  Channel senders
and queue orchestration live in ``assistant-core``.  Existing CLI and private
method signatures remain available for press/newspaper callers and tests.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from assistant_core import (
    CHANNELS,
    NotificationService,
    resolve_secret_refs,
    send_discord_webhook,
    send_email,
    send_slack,
    send_telegram,
    send_webhook,
    tag_text,
)
from hub.base import BaseHandler
from hub.notify_storage import BachNotifyStorage


class NotifyHandler(BaseHandler):
    """Preserve the ``bach notify`` surface while delegating neutral logic."""

    CHANNELS = CHANNELS

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "notify"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "send": "Benachrichtigung senden: send <channel> <text>",
            "setup": "Channel konfigurieren: setup <channel> [endpoint] [--token-ref=KEY]",
            "test": "Test-Benachrichtigung: test <channel>",
            "list": "Konfigurierte Channels anzeigen",
            "status": "Status aller Channels",
            "history": "Letzte Benachrichtigungen: history [--limit N]",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        operations = {
            "send": self._send,
            "setup": self._setup,
            "test": self._test,
            "list": self._list,
            "status": self._status,
            "history": self._history,
            "help": self._help,
        }
        operation_fn = operations.get(operation)
        if not operation_fn:
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {', '.join(operations)}"
        return operation_fn(args, dry_run)

    def _storage(self) -> BachNotifyStorage:
        return BachNotifyStorage(self.db_path)

    def _service(self) -> NotificationService:
        return NotificationService(self._storage(), self._dispatch)

    def _send(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, "Verwendung: notify send <channel> <text>"

        channel = args[0].lower()
        text = " ".join(args[1:])
        result = self._service().send(channel, text, dry_run=dry_run)
        if result.status == "dry-run":
            return True, f"[DRY] Wuerde senden via {channel}: {text[:60]}"
        if result.status == "unconfigured":
            return False, (
                f"Channel '{channel}' nicht konfiguriert.\n"
                f"Hinweis: bach notify setup {channel} <endpoint>"
            )
        if result.status == "disabled":
            return False, f"Channel '{channel}' ist deaktiviert."
        if result.status == "sent":
            return True, f"[OK] Benachrichtigung gesendet via {channel}"
        if result.status == "queued":
            return True, "[QUEUED] Benachrichtigung in Queue (Versand ausstehend)"
        return False, "Verwendung: notify send <channel> <text>"

    def _setup(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Verwendung: notify setup <channel> [endpoint] [--token-ref=KEY]\n"
                f"Channels: {', '.join(self.CHANNELS)}"
            )

        channel = args[0].lower()
        if channel not in self.CHANNELS:
            return False, f"Unbekannter Channel: {channel}\nErlaubt: {', '.join(self.CHANNELS)}"

        endpoint = ""
        token_ref = ""
        email_addr = ""
        for argument in args[1:]:
            if argument.startswith("--token="):
                return False, (
                    "Secrets dürfen nicht über Prozessargumente übergeben werden. "
                    "Nutze 'bach secrets set <key> --stdin' und danach "
                    "'--token-ref=<key>'."
                )
            if argument.startswith("--token-ref="):
                token_ref = argument.split("=", 1)[1].strip()
            elif argument.startswith("--email="):
                email_addr = argument.split("=", 1)[1]
            elif not argument.startswith("--"):
                endpoint = argument

        config = self._service().setup(
            channel,
            endpoint=endpoint,
            token_ref=token_ref,
            email=email_addr,
            dry_run=dry_run,
        )
        if dry_run:
            return True, f"[DRY] Wuerde Channel '{channel}' konfigurieren"
        return True, f"[OK] Channel '{channel}' konfiguriert (endpoint: {config.endpoint or 'default'})"

    def _test(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: notify test <channel>"
        message = f"BACH Test-Benachrichtigung ({datetime.now().strftime('%H:%M:%S')})"
        return self._send([args[0], message], dry_run)

    def _list(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        channels = self._service().list_channels()
        if not channels:
            return True, (
                "Keine Notification-Channels konfiguriert.\n"
                "Hinweis: bach notify setup <channel> [endpoint]"
            )

        lines = [f"Notification Channels ({len(channels)})", "=" * 50]
        for channel in channels:
            status = "aktiv" if channel.is_active else "inaktiv"
            last_used = channel.last_used or "nie"
            lines.append(
                f"  [{status:>7}] {channel.name} ({channel.channel}) -> "
                f"{channel.endpoint or 'default'} "
                f"[{channel.success_count}x gesendet, letzter: {last_used}]"
            )
        return True, "\n".join(lines)

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        return self._list(args, dry_run)

    def _history(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        limit = 20
        for index, argument in enumerate(args):
            if argument == "--limit" and index + 1 < len(args):
                limit = int(args[index + 1])

        records = self._service().history(limit)
        if not records:
            return True, "Keine Benachrichtigungs-History."

        lines = [f"Benachrichtigungs-History ({len(records)})", "=" * 50]
        for record in records:
            status = "gesendet" if record.processed else "ausstehend"
            channel = record.connector_name.removeprefix("notify_")
            lines.append(
                f"  [{status:>10}] {record.created_at} [{channel}] {record.content[:60]}"
            )
        return True, "\n".join(lines)

    def _help(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = [
            "Notification-System",
            "=" * 50,
            "",
            "Versendet Benachrichtigungen ueber verschiedene Channels.",
            "",
            "Setup:",
            "  bach notify setup discord https://discord.com/api/webhooks/...",
            "  bach notify setup telegram  # nutzt den keyring-basierten telegram_main-Connector",
            "  bach notify setup email smtp.gmail.com --token-ref=notify_email_password --email=user@gmail.com",
            "  bach notify setup slack https://hooks.slack.com/services/T.../B.../...",
            "  bach notify setup webhook https://your-endpoint.com/notify",
            "",
            "Senden:",
            '  bach notify send discord "Backup abgeschlossen!"',
            "  bach notify test telegram",
            "",
            "Verwaltung:",
            "  bach notify list       Konfigurierte Channels",
            "  bach notify history    Sende-History",
            "",
            f"Unterstuetzte Channels: {', '.join(self.CHANNELS)}",
        ]
        return True, "\n".join(lines)

    def _resolve_secret_refs(self, auth_config: str) -> dict:
        from hub.secrets_handler import get_secret_value

        return resolve_secret_refs(auth_config, lambda key: get_secret_value(key))

    def _dispatch(self, channel: str, endpoint: str, auth_config: str, text: str) -> bool:
        try:
            if channel == "telegram":
                return self._send_telegram(text, auth_config)
            if channel == "webhook" and endpoint:
                return self._send_webhook(endpoint, text)
            if channel == "discord" and endpoint:
                return self._send_discord_webhook(endpoint, text)
            if channel == "slack" and endpoint:
                return self._send_slack(endpoint, text)
            if channel == "email" and endpoint:
                return self._send_email(endpoint, auth_config, text)
        except Exception:
            pass
        return False

    def _get_sender_tag(self, channel: str) -> str:
        return self._storage().sender_tag(channel)

    def _tag_text(self, text: str, channel: str) -> str:
        return tag_text(text, channel, self._storage())

    def _send_telegram(self, text: str, auth_config: str = "") -> bool:
        from hub.connector import ConnectorHandler

        def connector_factory():
            connector, _ = ConnectorHandler(self.base_path)._instantiate("telegram_main")
            return connector

        return send_telegram(text, self._storage(), connector_factory)

    def _send_webhook(self, url: str, text: str) -> bool:
        return send_webhook(url, text, source="bach")

    def _send_discord_webhook(self, url: str, text: str) -> bool:
        return send_discord_webhook(url, text)

    def _send_slack(self, webhook_url: str, text: str) -> bool:
        return send_slack(webhook_url, text)

    def _send_email(self, smtp_server: str, auth_config: str, text: str) -> bool:
        from hub.secrets_handler import get_secret_value

        return send_email(
            smtp_server,
            auth_config,
            text,
            secret_resolver=lambda key: get_secret_value(key),
            subject="BACH Benachrichtigung",
        )
