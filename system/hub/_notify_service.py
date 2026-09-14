# SPDX-License-Identifier: MIT
"""Lokale NotificationService-Implementierung fuer BACH.

Dient als Fallback, solange ``assistant_core.NotificationService`` noch nicht
verfuegbar ist. Nutzt ``hub.notify_storage.BachNotifyStorage`` fuer die
Persistenz und ``hub._notify_dispatcher`` fuer den eigentlichen Versand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from hub._notify_dispatcher import (
    CHANNELS,
    resolve_secret_refs,
    send_discord_webhook,
    send_email,
    send_slack,
    send_telegram,
    send_webhook,
    tag_text,
)


@dataclass
class SendResult:
    status: str  # 'sent', 'queued', 'disabled', 'unconfigured', 'dry-run'


class NotificationService:
    """Minimaler, voll funktionsfaehiger NotificationService fuer BACH."""

    def __init__(
        self,
        storage,
        dispatch: Optional[Callable[[str, str, str, str], bool]] = None,
    ) -> None:
        self.storage = storage
        self._dispatch = dispatch

    def send(self, channel: str, text: str, dry_run: bool = False) -> SendResult:
        channel = channel.lower()
        if channel not in CHANNELS:
            return SendResult("unconfigured")

        cfg = self.storage.get_channel(channel)
        if cfg is None:
            return SendResult("unconfigured")
        if not cfg.is_active:
            return SendResult("disabled")
        if dry_run:
            return SendResult("dry-run")

        tagged = tag_text(text, channel, self.storage)
        dispatch = self._dispatch or self._default_dispatch
        ok = dispatch(channel, cfg.endpoint, cfg.auth_config, tagged)
        now = datetime.now().isoformat()
        if ok:
            # Markieren als versucht (message_id 0 = Direktversand)
            self.storage.mark_sent(0, f"notify_{channel}", now)
            return SendResult("sent")
        # Fallback: In Queue legen
        self.storage.enqueue(f"notify_{channel}", "", tagged, now)
        return SendResult("queued")

    def setup(
        self,
        channel: str,
        endpoint: str = "",
        token_ref: str = "",
        email: str = "",
        dry_run: bool = False,
    ):
        from hub.notify_storage import ChannelConfig

        channel = channel.lower()
        if channel not in CHANNELS:
            raise ValueError(f"Unknown channel: {channel}")

        if dry_run:
            return ChannelConfig(
                name=f"notify_{channel}",
                channel=channel,
                endpoint=endpoint,
                auth_config="",
                is_active=True,
                last_used=None,
                success_count=0,
            )

        auth_type = "none"
        auth_config: dict = {}
        if token_ref:
            auth_config["_secret_refs"] = {"token": token_ref}
            auth_type = "api_key"
        if email:
            auth_config["to"] = email
            auth_type = "smtp"
        elif channel == "email":
            auth_type = "smtp"

        self.storage.upsert_channel(
            channel,
            endpoint=endpoint,
            auth_type=auth_type,
            auth_config=json.dumps(auth_config) if auth_config else "",
            updated_at=datetime.now().isoformat(),
        )
        return self.storage.get_channel(channel)

    def list_channels(self) -> list:
        return self.storage.list_channels()

    def history(self, limit: int = 20) -> list:
        return self.storage.history(limit)

    def _default_dispatch(self, channel: str, endpoint: str, auth_config: str, text: str) -> bool:
        from hub.secrets_handler import get_secret_value

        if channel == "telegram":
            from hub.connector import ConnectorHandler

            def connector_factory():
                # Wir haben nur den storage; base_path ist dessen DB-Verzeichnis.
                base = self.storage.db_path.parent if hasattr(self.storage, "db_path") else None
                handler = ConnectorHandler(base)
                connector, _ = handler._instantiate("telegram_main")
                return connector

            return send_telegram(text, self.storage, connector_factory)

        if channel == "webhook" and endpoint:
            return send_webhook(endpoint, text)
        if channel == "discord" and endpoint:
            return send_discord_webhook(endpoint, text)
        if channel == "slack" and endpoint:
            return send_slack(endpoint, text)
        if channel == "email" and endpoint:
            return send_email(
                endpoint,
                auth_config,
                text,
                secret_resolver=lambda key: get_secret_value(key),
                subject="BACH Benachrichtigung",
            )
        return False
