#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
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
NotifyHandler - Notification-System fuer BACH
==============================================

Operationen:
  send <channel> <text>     Benachrichtigung senden
  setup <channel>           Channel konfigurieren
  test <channel>            Test-Benachrichtigung senden
  list                      Konfigurierte Channels anzeigen
  status                    Status aller Channels
  history [--limit N]       Letzte Benachrichtigungen

Channels: discord, signal, email, telegram, webhook, slack

Nutzt: bach.db / connections, connector_messages
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple
from hub.base import BaseHandler

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class NotifyHandler(BaseHandler):

    CHANNELS = ("discord", "signal", "email", "telegram", "webhook", "slack")

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
        ops = {
            "send": self._send,
            "setup": self._setup,
            "test": self._test,
            "list": self._list,
            "status": self._status,
            "history": self._history,
            "help": self._help,
        }

        fn = ops.get(operation)
        if not fn:
            avail = ", ".join(ops.keys())
            return False, f"Unbekannte Operation: {operation}\nVerfuegbar: {avail}"

        return fn(args, dry_run)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _send(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, "Verwendung: notify send <channel> <text>"

        channel = args[0].lower()
        text = " ".join(args[1:])

        if dry_run:
            return True, f"[DRY] Wuerde senden via {channel}: {text[:60]}"

        conn = sqlite3.connect(str(self.db_path))
        try:
            # Pruefe ob Channel konfiguriert ist
            row = conn.execute("""
                SELECT name, endpoint, auth_config, is_active
                FROM connections
                WHERE name = ? AND category = 'notification'
            """, (f"notify_{channel}",)).fetchone()

            if not row:
                return False, f"Channel '{channel}' nicht konfiguriert.\nHinweis: bach notify setup {channel} <endpoint>"

            if not row[3]:
                return False, f"Channel '{channel}' ist deaktiviert."

            endpoint = row[1]
            auth = row[2]

            # Nachricht in Queue
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO connector_messages
                    (connector_name, direction, sender, recipient, content, created_at)
                VALUES (?, 'out', 'bach', ?, ?, ?)
            """, (f"notify_{channel}", endpoint or channel, text, now))
            conn.commit()

            # Versand-Versuch je nach Channel
            sent = self._dispatch(channel, endpoint, auth, text)

            if sent:
                conn.execute("""
                    UPDATE connector_messages SET processed = 1
                    WHERE connector_name = ? AND content = ? AND processed = 0
                """, (f"notify_{channel}", text))
                conn.execute("""
                    UPDATE connections SET last_used = ?, success_count = success_count + 1
                    WHERE name = ?
                """, (now, f"notify_{channel}"))
                conn.commit()
                return True, f"[OK] Benachrichtigung gesendet via {channel}"
            else:
                return True, f"[QUEUED] Benachrichtigung in Queue (Versand ausstehend)"
        finally:
            conn.close()

    def _setup(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, f"Verwendung: notify setup <channel> [endpoint] [--token-ref=KEY]\nChannels: {', '.join(self.CHANNELS)}"

        channel = args[0].lower()
        if channel not in self.CHANNELS:
            return False, f"Unbekannter Channel: {channel}\nErlaubt: {', '.join(self.CHANNELS)}"

        endpoint = ""
        token_ref = ""
        email_addr = ""
        for a in args[1:]:
            if a.startswith("--token="):
                return False, (
                    "Secrets dürfen nicht über Prozessargumente übergeben werden. "
                    "Nutze 'bach secrets set <key> --stdin' und danach "
                    "'--token-ref=<key>'."
                )
            elif a.startswith("--token-ref="):
                token_ref = a.split("=", 1)[1].strip()
            elif a.startswith("--email="):
                email_addr = a.split("=", 1)[1]
            elif not a.startswith("--"):
                endpoint = a

        name = f"notify_{channel}"
        auth_data = {}
        if token_ref:
            auth_data["_secret_refs"] = {"token": token_ref}
        if email_addr:
            auth_data["email"] = email_addr
        auth_config = json.dumps(auth_data, ensure_ascii=False) if auth_data else ""

        if dry_run:
            return True, f"[DRY] Wuerde Channel '{channel}' konfigurieren"

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO connections (name, type, category, endpoint, auth_type, auth_config,
                                       is_active, created_at, updated_at)
                VALUES (?, ?, 'notification', ?, ?, ?, 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    auth_config = CASE WHEN excluded.auth_config != '' THEN excluded.auth_config
                                      ELSE connections.auth_config END,
                    updated_at = excluded.updated_at
            """, (name, channel, endpoint, "keyring" if token_ref else "none", auth_config, now, now))
            conn.commit()
            return True, f"[OK] Channel '{channel}' konfiguriert (endpoint: {endpoint or 'default'})"
        finally:
            conn.close()

    def _test(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: notify test <channel>"
        return self._send([args[0], f"BACH Test-Benachrichtigung ({datetime.now().strftime('%H:%M:%S')})"], dry_run)

    def _list(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT name, type, endpoint, is_active, last_used, success_count
                FROM connections
                WHERE category = 'notification'
                ORDER BY name
            """).fetchall()

            if not rows:
                return True, f"Keine Notification-Channels konfiguriert.\nHinweis: bach notify setup <channel> [endpoint]"

            lines = [f"Notification Channels ({len(rows)})", "=" * 50]
            for r in rows:
                status = "aktiv" if r[3] else "inaktiv"
                last = r[4] or "nie"
                lines.append(f"  [{status:>7}] {r[0]} ({r[1]}) -> {r[2] or 'default'} [{r[5]}x gesendet, letzter: {last}]")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        return self._list(args, dry_run)

    def _history(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        limit = 20
        for i, a in enumerate(args):
            if a == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])

        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT id, connector_name, recipient, content, processed, created_at
                FROM connector_messages
                WHERE connector_name LIKE 'notify_%' AND direction = 'out'
                ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()

            if not rows:
                return True, "Keine Benachrichtigungs-History."

            lines = [f"Benachrichtigungs-History ({len(rows)})", "=" * 50]
            for r in rows:
                status = "gesendet" if r[4] else "ausstehend"
                channel = r[1].replace("notify_", "")
                lines.append(f"  [{status:>10}] {r[5]} [{channel}] {(r[3] or '')[:60]}")
            return True, "\n".join(lines)
        finally:
            conn.close()

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
            "  bach notify send discord \"Backup abgeschlossen!\"",
            "  bach notify test telegram",
            "",
            "Verwaltung:",
            "  bach notify list       Konfigurierte Channels",
            "  bach notify history    Sende-History",
            "",
            f"Unterstuetzte Channels: {', '.join(self.CHANNELS)}",
        ]
        return True, "\n".join(lines)

    # ------------------------------------------------------------------
    # Dispatch (Channel-spezifischer Versand)
    # ------------------------------------------------------------------

    def _resolve_secret_refs(self, auth_config: str) -> dict:
        """Löst ausschließlich Keyring-Referenzen aus einer Channel-Konfiguration."""
        config = json.loads(auth_config) if auth_config else {}
        if not isinstance(config, dict):
            return {}

        refs = config.pop("_secret_refs", {})
        # Alte Klartextfelder dürfen nicht mehr als stiller Fallback wirken.
        for field in ("token", "password", "bot_token", "chat_id", "owner_chat_id"):
            config.pop(field, None)

        if isinstance(refs, dict):
            from hub.secrets_handler import get_secret_value

            for field, secret_key in refs.items():
                value = get_secret_value(str(secret_key))
                if value:
                    config[str(field)] = value
        return config

    def _dispatch(self, channel: str, endpoint: str, auth_config: str, text: str) -> bool:
        """Versucht Nachricht direkt zu senden."""
        try:
            if channel == "telegram":
                return self._send_telegram(text, auth_config)
            elif channel == "webhook" and endpoint:
                return self._send_webhook(endpoint, text)
            elif channel == "discord" and endpoint:
                return self._send_discord_webhook(endpoint, text)
            elif channel == "slack" and endpoint:
                return self._send_slack(endpoint, text)
            elif channel == "email" and endpoint:
                return self._send_email(endpoint, auth_config, text)
        except Exception:
            pass
        return False  # Fuer andere Channels: in Queue belassen

    def _get_sender_tag(self, channel: str) -> str:
        """Liest sender_tag aus der Connector-Config (connections-Tabelle)."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            try:
                row = conn.execute(
                    "SELECT auth_config FROM connections WHERE name = ? OR name = ?",
                    (channel, f"notify_{channel}")
                ).fetchone()
            finally:
                conn.close()
            if row and row[0]:
                config = json.loads(row[0])
                return config.get("sender_tag", "")
        except Exception:
            pass
        return ""

    def _tag_text(self, text: str, channel: str) -> str:
        """Fuegt Sender-Tag vor den Text wenn konfiguriert."""
        tag = self._get_sender_tag(channel)
        if tag and text:
            return f"[{tag}] {text}"
        return text

    def _send_telegram(self, text: str, auth_config: str = "") -> bool:
        """Sendet über den kanonischen, keyring-basierten Telegram-Connector."""
        text = self._tag_text(text, "telegram")
        from hub.connector import ConnectorHandler

        connector, _ = ConnectorHandler(self.base_path)._instantiate("telegram_main")
        if not connector:
            return False
        try:
            return bool(connector.send_message("", text))
        finally:
            connector.disconnect()

    def _send_webhook(self, url: str, text: str) -> bool:
        import urllib.request
        data = json.dumps({"text": text, "source": "bach"}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except Exception:
            return False

    def _send_discord_webhook(self, url: str, text: str) -> bool:
        import urllib.request
        data = json.dumps({"content": text}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except Exception:
            return False

    def _send_slack(self, webhook_url: str, text: str) -> bool:
        """Sendet Nachricht an Slack via Webhook."""
        import urllib.request
        data = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except Exception:
            return False

    def _send_email(self, smtp_server: str, auth_config: str, text: str) -> bool:
        """Sendet Email via SMTP_SSL (basierend auf BachForelle EmailSkill)."""
        import smtplib
        from email.mime.text import MIMEText

        config = self._resolve_secret_refs(auth_config)
        email_addr = config.get("email", "")
        password = config.get("token", "")

        if not all([email_addr, password, smtp_server]):
            return False

        msg = MIMEText(text)
        msg["Subject"] = "BACH Benachrichtigung"
        msg["From"] = email_addr
        msg["To"] = email_addr  # Self-Notification (an eigene Adresse)

        try:
            with smtplib.SMTP_SSL(smtp_server, 465, timeout=15) as smtp:
                smtp.login(email_addr, password)
                smtp.send_message(msg)
            return True
        except Exception:
            return False
