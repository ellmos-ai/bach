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
ConnectorHandler - Connector-Verwaltung, Runtime und Message-Routing
=====================================================================

Operationen:
  list              Alle Connectors anzeigen
  status            Status aller aktiven Connectors
  add <type> <name> Neuen Connector registrieren
  remove <name>     Connector entfernen
  enable <name>     Connector aktivieren
  disable <name>    Connector deaktivieren
  messages [name]   Nachrichten anzeigen (optional gefiltert)
  route             Unverarbeitete Nachrichten routen
  send <name> <recipient> <text>  Nachricht ueber Connector senden
  poll <name>       Einmal pollen: Connector instanziieren, Nachrichten holen, in DB speichern
  dispatch <name>   Ausgehende Queue abarbeiten: Nachrichten tatsaechlich versenden

Nutzt: bach.db / connections, connector_messages
Runtime: Instanziiert echte Connector-Objekte (TelegramConnector, DiscordConnector, etc.)
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional
from hub.base import BaseHandler

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class ConnectorHandler(BaseHandler):

    SUPPORTED_TYPES = ("telegram", "signal", "discord", "whatsapp", "webhook", "homeassistant")

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        self.db_path = self._canonical_db

    @property
    def profile_name(self) -> str:
        return "connector"

    @property
    def target_file(self) -> Path:
        return self.db_path

    def get_operations(self) -> dict:
        return {
            "list": "Alle Connectors anzeigen",
            "status": "Status aktiver Connectors",
            "add": "Neuen Connector registrieren: add <type> <name> [endpoint]",
            "remove": "Connector entfernen: remove <name>",
            "enable": "Connector aktivieren: enable <name>",
            "disable": "Connector deaktivieren: disable <name>",
            "messages": "Nachrichten anzeigen: messages [connector_name] [--limit N]",
            "unprocessed": "Unverarbeitete Nachrichten anzeigen",
            "route": "Unverarbeitete Nachrichten routen",
            "smart-route": "Smart-Routing mit Launcher (Commands automatisch ausfuehren)",
            "send": "Nachricht senden: send <connector> <recipient> <text>",
            "send-file": "Datei senden: send-file <connector> <recipient> <filepath> [--caption <text>]",
            "poll": "Einmal pollen: poll <name> - Nachrichten holen und in DB speichern",
            "dispatch": "Queue abarbeiten: dispatch <name> - Ausgehende Nachrichten versenden",
            "setup-scheduler": "Scheduler-Jobs registrieren (poll_and_route + dispatch)",
            "setup-daemon": "Alias fuer setup-scheduler (Rueckwaertskompatibilitaet)",
            "queue-status": "Queue-Statistiken anzeigen (pending/failed/dead pro Connector)",
            "retry": "Dead-Letter zuruecksetzen: retry [msg_id|all]",
            "configure": "Config-Wert setzen: configure <name> <key> <value>",
            "setup-wizard": "Interaktiver Setup-Wizard fuer neue Connectors aus Templates",
            "help": "Hilfe anzeigen",
        }

    def handle(self, operation: str, args: List[str], dry_run: bool = False) -> Tuple[bool, str]:
        ops = {
            "list": self._list,
            "status": self._status,
            "add": self._add,
            "remove": self._remove,
            "enable": self._enable,
            "disable": self._disable,
            "messages": self._messages,
            "unprocessed": self._unprocessed,
            "route": self._route,
            "smart-route": self._smart_route,
            "send": self._send,
            "send-file": self._send_file,
            "poll": self._poll,
            "dispatch": self._dispatch,
            "configure": self._configure,
            "setup-scheduler": self._setup_daemon,
            "setup-daemon": self._setup_daemon,
            "queue-status": self._queue_status,
            "retry": self._retry,
            "setup-wizard": self._setup_wizard,
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

    def _list(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT name, type, category, endpoint, is_active, last_used,
                       success_count, error_count
                FROM connections
                WHERE category = 'connector'
                ORDER BY name
            """).fetchall()

            if not rows:
                return True, "Keine Connectors registriert.\nHinweis: bach connector add <type> <name> [endpoint]"

            lines = [f"Connectors ({len(rows)})", "=" * 50]
            for r in rows:
                status = "aktiv" if r[4] else "inaktiv"
                endpoint = f" -> {r[3]}" if r[3] else ""
                stats = f" (ok:{r[6]} err:{r[7]})" if r[6] or r[7] else ""
                lines.append(f"  [{status:>7}] {r[0]} ({r[1]}){endpoint}{stats}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            active = conn.execute("""
                SELECT name, type, endpoint, last_used, success_count, error_count
                FROM connections
                WHERE category = 'connector' AND is_active = 1
                ORDER BY name
            """).fetchall()

            unprocessed = conn.execute("""
                SELECT connector_name, COUNT(*) as cnt
                FROM connector_messages
                WHERE processed = 0
                GROUP BY connector_name
            """).fetchall()

            total_msgs = conn.execute("SELECT COUNT(*) FROM connector_messages").fetchone()[0]

            lines = ["Connector Status", "=" * 50]
            lines.append(f"  Aktive Connectors: {len(active)}")
            lines.append(f"  Nachrichten gesamt: {total_msgs}")

            if active:
                lines.append("\n  Aktive Connectors:")
                for r in active:
                    last = r[3] or "nie"
                    lines.append(f"    {r[0]} ({r[1]}): ok={r[4]} err={r[5]} letzter={last}")

            if unprocessed:
                lines.append("\n  Unverarbeitete Nachrichten:")
                for name, cnt in unprocessed:
                    lines.append(f"    {name}: {cnt}")

            return True, "\n".join(lines)
        finally:
            conn.close()

    def _add(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, f"Verwendung: connector add <type> <name> [endpoint]\nTypen: {', '.join(self.SUPPORTED_TYPES)}"

        conn_type = args[0].lower()
        name = args[1]
        endpoint = args[2] if len(args) > 2 else ""

        if conn_type not in self.SUPPORTED_TYPES:
            return False, f"Unbekannter Typ: {conn_type}\nErlaubt: {', '.join(self.SUPPORTED_TYPES)}"

        if dry_run:
            return True, f"[DRY] Wuerde Connector erstellen: {name} ({conn_type})"

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO connections (name, type, category, endpoint, is_active, created_at, updated_at)
                VALUES (?, ?, 'connector', ?, 1, ?, ?)
            """, (name, conn_type, endpoint, now, now))
            conn.commit()
            return True, f"[OK] Connector '{name}' ({conn_type}) registriert."
        except sqlite3.IntegrityError:
            return False, f"Connector '{name}' existiert bereits."
        finally:
            conn.close()

    def _remove(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: connector remove <name>"

        name = args[0]
        if dry_run:
            return True, f"[DRY] Wuerde Connector '{name}' entfernen."

        conn = sqlite3.connect(str(self.db_path))
        try:
            result = conn.execute(
                "DELETE FROM connections WHERE name = ? AND category = 'connector'", (name,))
            conn.commit()
            if result.rowcount == 0:
                return False, f"Connector '{name}' nicht gefunden."
            return True, f"[OK] Connector '{name}' entfernt."
        finally:
            conn.close()

    def _enable(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        return self._toggle(args, dry_run, active=True)

    def _disable(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        return self._toggle(args, dry_run, active=False)

    def _toggle(self, args: List[str], dry_run: bool, active: bool) -> Tuple[bool, str]:
        if not args:
            return False, "Verwendung: connector enable/disable <name>"

        name = args[0]
        state = "aktiviert" if active else "deaktiviert"

        if dry_run:
            return True, f"[DRY] Wuerde Connector '{name}' {state}."

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result = conn.execute(
                "UPDATE connections SET is_active = ?, updated_at = ? WHERE name = ? AND category = 'connector'",
                (1 if active else 0, now, name))
            conn.commit()
            if result.rowcount == 0:
                return False, f"Connector '{name}' nicht gefunden."
            return True, f"[OK] Connector '{name}' {state}."
        finally:
            conn.close()

    def _messages(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        limit = 20
        connector_name = None

        for i, a in enumerate(args):
            if a == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
            elif not a.startswith("--"):
                connector_name = a

        conn = sqlite3.connect(str(self.db_path))
        try:
            if connector_name:
                rows = conn.execute("""
                    SELECT id, connector_name, direction, sender, recipient,
                           content, processed, created_at
                    FROM connector_messages
                    WHERE connector_name = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (connector_name, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, connector_name, direction, sender, recipient,
                           content, processed, created_at
                    FROM connector_messages
                    ORDER BY created_at DESC LIMIT ?
                """, (limit,)).fetchall()

            if not rows:
                return True, "Keine Nachrichten vorhanden."

            lines = [f"Connector-Nachrichten ({len(rows)})", "=" * 50]
            for r in rows:
                proc = " [verarbeitet]" if r[6] else ""
                direction = "<<" if r[2] == "in" else ">>"
                lines.append(
                    f"  #{r[0]} [{r[1]}] {direction} {r[3] or '?'} -> {r[4] or '?'}: "
                    f"{(r[5] or '')[:60]}{proc}"
                )
                lines.append(f"       {r[7]}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _unprocessed(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT id, connector_name, direction, sender, content, created_at
                FROM connector_messages
                WHERE processed = 0
                ORDER BY created_at ASC
            """).fetchall()

            if not rows:
                return True, "Keine unverarbeiteten Nachrichten."

            lines = [f"Unverarbeitete Nachrichten ({len(rows)})", "=" * 50]
            for r in rows:
                lines.append(f"  #{r[0]} [{r[1]}] von {r[2]}: {(r[4] or '')[:80]}")
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _route(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Verarbeite unverarbeitete eingehende Nachrichten."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT id, connector_name, sender, content
                FROM connector_messages
                WHERE processed = 0 AND direction = 'in'
                ORDER BY created_at ASC
            """).fetchall()

            if not rows:
                return True, "Keine Nachrichten zum Routen."

            processed = 0
            skipped = 0
            lines = [f"Routing {len(rows)} Nachrichten..."]

            for r in rows:
                msg_id, connector, sender, content = r
                if dry_run:
                    lines.append(f"  [DRY] #{msg_id} von {sender}: {(content or '')[:60]}")
                    continue

                sender_full = f"{connector}:{sender}"
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                try:
                    # Duplikat-Check: gleicher Sender+Body in messages
                    existing = conn.execute("""
                        SELECT id FROM messages
                        WHERE sender = ? AND body = ? AND direction = 'inbox'
                        LIMIT 1
                    """, (sender_full, content)).fetchone()

                    if existing:
                        # Duplikat - nur als processed markieren, nicht nochmal routen
                        conn.execute(
                            "UPDATE connector_messages SET processed = 1 WHERE id = ?",
                            (msg_id,))
                        skipped += 1
                        continue

                    conn.execute("""
                        INSERT INTO messages (direction, sender, recipient, subject, body,
                                            body_type, status, created_at)
                        VALUES ('inbox', ?, 'bach', ?, ?, 'text', 'unread', ?)
                    """, (sender_full, f"Connector: {connector}",
                          content, now))

                    conn.execute(
                        "UPDATE connector_messages SET processed = 1 WHERE id = ?",
                        (msg_id,))
                    processed += 1
                    lines.append(f"  [OK] #{msg_id} -> inbox")
                except Exception as e:
                    conn.execute(
                        "UPDATE connector_messages SET error = ? WHERE id = ?",
                        (str(e), msg_id))
                    lines.append(f"  [ERR] #{msg_id}: {e}")

            conn.commit()
            info = f"\n{processed}/{len(rows)} Nachrichten geroutet."
            if skipped:
                info += f" ({skipped} Duplikate uebersprungen)"
            lines.append(info)
            return True, "\n".join(lines)
        finally:
            conn.close()

    def _smart_route(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Smart-Routing mit Launcher-Integration."""
        connector_name = args[0] if args else None

        try:
            from hub._services.connector.smart_router import smart_route_messages
            return smart_route_messages(self.base_path, connector_name, dry_run)
        except Exception as e:
            return False, f"[ERROR] Smart-Routing: {e}"

    def _send(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        if len(args) < 3:
            return False, "Verwendung: connector send <connector_name> <recipient> <text>"

        connector_name = args[0]
        recipient = args[1]
        text = " ".join(args[2:])

        # Encoding-Sanitierung
        try:
            from tools.encoding_fix import sanitize_outbound
            text = sanitize_outbound(text)
        except ImportError:
            pass

        if dry_run:
            return True, f"[DRY] Wuerde senden via {connector_name} an {recipient}: {text[:60]}"

        conn = sqlite3.connect(str(self.db_path))
        try:
            # Pruefen ob Connector existiert und aktiv ist
            row = conn.execute(
                "SELECT is_active FROM connections WHERE name = ? AND category = 'connector'",
                (connector_name,)).fetchone()
            if not row:
                return False, f"Connector '{connector_name}' nicht gefunden."
            if not row[0]:
                return False, f"Connector '{connector_name}' ist deaktiviert."

            # Nachricht in Queue eintragen (wird vom Daemon versendet)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO connector_messages
                    (connector_name, direction, sender, recipient, content, created_at)
                VALUES (?, 'out', 'bach', ?, ?, ?)
            """, (connector_name, recipient, text, now))
            conn.commit()
            return True, f"[OK] Nachricht in Queue fuer {connector_name} -> {recipient}"
        finally:
            conn.close()

    def _send_file(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Datei ueber Connector senden."""
        if len(args) < 3:
            return False, "Verwendung: connector send-file <connector_name> <recipient> <filepath> [--caption <text>]"

        connector_name = args[0]
        recipient = args[1]
        filepath = args[2]

        # Caption extrahieren falls vorhanden
        caption = ""
        if "--caption" in args:
            caption_idx = args.index("--caption")
            if caption_idx + 1 < len(args):
                caption = " ".join(args[caption_idx + 1:])

        # Pruefen ob Datei existiert
        from pathlib import Path
        file_path = Path(filepath)
        if not file_path.exists():
            return False, f"Datei nicht gefunden: {filepath}"

        if dry_run:
            return True, f"[DRY] Wuerde Datei senden via {connector_name} an {recipient}: {filepath}"

        # Connector instanziieren und direkt senden (nicht queue-basiert fuer Dateien)
        instance, err = self._instantiate(connector_name)
        if not instance:
            return False, err

        if not instance.connect():
            return False, f"Connector '{connector_name}' konnte nicht verbinden."

        try:
            # Pruefen ob Connector send_file unterstuetzt
            if not hasattr(instance, 'send_file'):
                # Fallback: Caption als Nachricht senden
                if caption:
                    ok = instance.send_message(recipient, caption)
                    return ok, f"[OK] Nachricht gesendet (Datei-Upload nicht unterstuetzt)" if ok else "[ERR] Senden fehlgeschlagen"
                else:
                    return False, f"Connector '{connector_name}' unterstuetzt kein Datei-Upload."

            ok = instance.send_file(recipient, str(file_path), caption=caption)
            return ok, f"[OK] Datei gesendet: {filepath}" if ok else "[ERR] Datei-Upload fehlgeschlagen"
        except Exception as e:
            return False, f"Fehler beim Senden: {e}"
        finally:
            instance.disconnect()

    # ------------------------------------------------------------------
    # Runtime: Connector instanziieren, pollen, dispatchen
    # ------------------------------------------------------------------

    def _instantiate(self, name: str) -> Tuple[Optional[object], str]:
        """Connector-Instanz aus DB-Config erstellen.

        auth_config-Feld in connections speichert JSON mit:
          {"bot_token": "...", "owner_chat_id": "...", "default_channel": "...", ...}
        """
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("""
                SELECT name, type, endpoint, is_active, auth_type, auth_config
                FROM connections
                WHERE name = ? AND category = 'connector'
            """, (name,)).fetchone()

            if not row:
                return None, f"Connector '{name}' nicht gefunden."
            if not row[3]:
                return None, f"Connector '{name}' ist deaktiviert."

            conn_type = row[1]
            endpoint = row[2] or ""
            auth_type = row[4] or "api_key"
            auth_data = json.loads(row[5]) if row[5] else {}

            # _secret_refs auflösen: Tokens aus secrets-Tabelle nachladen (ENT-44)
            # Format: {"_secret_refs": {"bot_token": "telegram_main_bot_token"}}
            secret_refs = auth_data.pop("_secret_refs", {})
            if secret_refs:
                try:
                    for field_name, secret_key in secret_refs.items():
                        sec_row = conn.execute(
                            "SELECT value FROM secrets WHERE key = ?", (secret_key,)
                        ).fetchone()
                        if sec_row and sec_row[0]:
                            auth_data[field_name] = sec_row[0]
                except Exception:
                    pass  # secrets-Tabelle nicht vorhanden oder leer

            from connectors.base import ConnectorConfig

            config = ConnectorConfig(
                name=row[0],
                connector_type=conn_type,
                endpoint=endpoint,
                auth_type=auth_type,
                auth_config=auth_data,
                options=auth_data,  # Options sind Teil von auth_config
            )

            if conn_type == "telegram":
                from connectors.telegram_connector import TelegramConnector
                return TelegramConnector(config), ""
            elif conn_type == "discord":
                from connectors.discord_connector import DiscordConnector
                return DiscordConnector(config), ""
            elif conn_type == "signal":
                from connectors.signal_connector import SignalConnector
                return SignalConnector(config), ""
            elif conn_type == "whatsapp":
                from connectors.whatsapp_connector import WhatsAppConnector
                return WhatsAppConnector(config), ""
            elif conn_type == "homeassistant":
                from connectors.homeassistant_connector import HomeAssistantConnector
                return HomeAssistantConnector(config), ""
            else:
                return None, f"Kein Runtime-Adapter fuer Typ '{conn_type}'. Verfuegbar: telegram, discord, signal, whatsapp, homeassistant"
        finally:
            conn.close()

    def _poll(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Einmal pollen: Connector instanziieren, verbinden, Nachrichten holen, in DB speichern."""
        if not args:
            return False, "Verwendung: connector poll <name>"

        name = args[0]
        if dry_run:
            return True, f"[DRY] Wuerde Connector '{name}' pollen."

        instance, err = self._instantiate(name)
        if not instance:
            return False, err

        if not instance.connect():
            return False, f"Connector '{name}' konnte nicht verbinden."

        try:
            messages = instance.get_messages()
        except Exception as e:
            return False, f"Poll-Fehler: {e}"
        finally:
            instance.disconnect()

        if not messages:
            return True, f"[OK] Poll '{name}': Keine neuen Nachrichten."

        # Nachrichten in connector_messages speichern (mit Duplikat-Schutz)
        conn = sqlite3.connect(str(self.db_path))
        stored = 0
        skipped = 0
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for msg in messages:
                try:
                    # Duplikat-Check: gleicher Sender+Inhalt innerhalb 60s
                    existing = conn.execute("""
                        SELECT id FROM connector_messages
                        WHERE connector_name = ? AND sender = ? AND content = ?
                          AND direction = 'in'
                          AND created_at >= datetime(?, '-60 seconds')
                        LIMIT 1
                    """, (name, msg.sender, msg.content, now)).fetchone()
                    if existing:
                        skipped += 1
                        continue

                    conn.execute("""
                        INSERT INTO connector_messages
                            (connector_name, direction, sender, recipient, content,
                             status, created_at)
                        VALUES (?, ?, ?, ?, ?, 'pending', ?)
                    """, (name, msg.direction, msg.sender, "", msg.content, now))
                    stored += 1
                except Exception:
                    pass

            # last_update_id persistent speichern (verhindert Re-Fetch von Telegram)
            if hasattr(instance, '_last_update_id') and instance._last_update_id > 0:
                auth_row = conn.execute(
                    "SELECT auth_config FROM connections WHERE name = ?", (name,)
                ).fetchone()
                if auth_row:
                    auth_data = json.loads(auth_row[0]) if auth_row[0] else {}
                    auth_data['last_update_id'] = instance._last_update_id
                    conn.execute(
                        "UPDATE connections SET auth_config = ? WHERE name = ?",
                        (json.dumps(auth_data, ensure_ascii=True), name))

            # success_count aktualisieren
            conn.execute("""
                UPDATE connections SET success_count = success_count + ?, last_used = ?
                WHERE name = ? AND category = 'connector'
            """, (stored, now, name))
            conn.commit()
        finally:
            conn.close()

        info = f"[OK] Poll '{name}': {stored} Nachrichten gespeichert."
        if skipped:
            info += f" ({skipped} Duplikate uebersprungen)"
        return True, info

    def _dispatch(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Ausgehende Queue abarbeiten: Nachrichten tatsaechlich ueber Connector versenden."""
        if not args:
            return False, "Verwendung: connector dispatch <name>"

        name = args[0]
        if dry_run:
            return True, f"[DRY] Wuerde ausgehende Queue fuer '{name}' abarbeiten."

        # Ausgehende, unverarbeitete Nachrichten holen
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("""
                SELECT id, recipient, content
                FROM connector_messages
                WHERE connector_name = ? AND direction = 'out' AND processed = 0
                ORDER BY created_at ASC
            """, (name,)).fetchall()
        finally:
            conn.close()

        if not rows:
            return True, f"[OK] Dispatch '{name}': Keine ausgehenden Nachrichten."

        instance, err = self._instantiate(name)
        if not instance:
            return False, err

        if not instance.connect():
            return False, f"Connector '{name}' konnte nicht verbinden."

        sent = 0
        errors = 0
        lines = [f"Dispatch '{name}': {len(rows)} Nachrichten..."]

        conn = sqlite3.connect(str(self.db_path))
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for msg_id, recipient, content in rows:
                try:
                    ok = instance.send_message(recipient, content)
                    if ok:
                        conn.execute("UPDATE connector_messages SET processed = 1 WHERE id = ?", (msg_id,))
                        sent += 1
                        lines.append(f"  [OK] #{msg_id} -> {recipient}")
                    else:
                        conn.execute("UPDATE connector_messages SET error = 'send_failed' WHERE id = ?", (msg_id,))
                        errors += 1
                        lines.append(f"  [ERR] #{msg_id} -> {recipient}: send_failed")
                except Exception as e:
                    conn.execute("UPDATE connector_messages SET error = ? WHERE id = ?", (str(e)[:200], msg_id))
                    errors += 1

            conn.execute("""
                UPDATE connections SET success_count = success_count + ?, error_count = error_count + ?, last_used = ?
                WHERE name = ? AND category = 'connector'
            """, (sent, errors, now, name))
            conn.commit()
        finally:
            conn.close()
            instance.disconnect()

        lines.append(f"\n{sent} gesendet, {errors} Fehler.")
        return True, "\n".join(lines)

    def _configure(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Config-Wert in auth_config eines Connectors setzen/aendern.

        Verwendung: connector configure <name> <key> <value>
        Beispiel:   connector configure telegram_main sender_tag BACH
        """
        if len(args) < 3:
            return False, "Verwendung: connector configure <name> <key> <value>"

        name = args[0]
        key = args[1]
        value = " ".join(args[2:])

        # Typ-Konversion: Zahlen und Booleans
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        else:
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass  # String bleibt String

        if dry_run:
            return True, f"[DRY] Wuerde {name}.{key} = {value} setzen."

        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT auth_config FROM connections WHERE name = ? AND category = 'connector'",
                (name,)).fetchone()
            if not row:
                return False, f"Connector '{name}' nicht gefunden."

            auth = json.loads(row[0]) if row[0] else {}
            old_value = auth.get(key, "<nicht gesetzt>")
            auth[key] = value

            conn.execute(
                "UPDATE connections SET auth_config = ?, updated_at = ? WHERE name = ?",
                (json.dumps(auth, ensure_ascii=False),
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name))
            conn.commit()
            return True, f"[OK] {name}.{key}: {old_value} -> {value}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Queue Management: setup-daemon, queue-status, retry
    # ------------------------------------------------------------------

    def _setup_daemon(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Registriert die 2 Daemon-Jobs fuer automatisches Polling und Dispatching."""
        if dry_run:
            return True, "[DRY] Wuerde 2 Daemon-Jobs registrieren (poll_and_route, dispatch)."

        from hub._services.connector.queue_processor import ensure_scheduler_jobs
        return ensure_scheduler_jobs()

    def _queue_status(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Zeigt Queue-Statistiken pro Connector."""
        from hub._services.connector.queue_processor import get_queue_status

        status = get_queue_status()
        totals = status["totals"]
        connectors = status["connectors"]

        lines = [
            "Queue Status",
            "=" * 50,
            f"  Outbound Pending: {totals['pending']}",
            f"  Outbound Sent:    {totals['sent']}",
            f"  Outbound Failed:  {totals['failed']}",
            f"  Outbound Dead:    {totals['dead']}",
        ]

        if connectors:
            lines.append("\nPro Connector:")
            for name, dirs in connectors.items():
                lines.append(f"  {name}:")
                for direction, statuses in dirs.items():
                    if statuses:
                        parts = [f"{s}={c}" for s, c in statuses.items()]
                        arrow = "<<" if direction == "in" else ">>"
                        lines.append(f"    {arrow} {', '.join(parts)}")
        else:
            lines.append("\nKeine Nachrichten in der Queue.")

        return True, "\n".join(lines)

    def _retry(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Setzt Dead-Letter-Nachrichten zurueck auf 'pending'."""
        if not args:
            return False, "Verwendung: connector retry <msg_id|all>"

        target = args[0]

        if dry_run:
            return True, f"[DRY] Wuerde Dead-Letter zuruecksetzen: {target}"

        from hub._services.connector.queue_processor import retry_dead_letters

        if target.lower() == "all":
            return retry_dead_letters(msg_id=None)
        else:
            try:
                msg_id = int(target)
                return retry_dead_letters(msg_id=msg_id)
            except ValueError:
                return False, f"Ungueltige Nachricht-ID: {target}. Verwende eine Zahl oder 'all'."

    def _setup_wizard(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        """Interaktiver Setup-Wizard fuer neue Connectors."""
        if dry_run:
            return True, "[DRY] Wuerde Setup-Wizard starten."

        try:
            from connectors.templates.setup_wizard import SetupWizard
            wizard = SetupWizard(base_path=self.base_path)
            wizard.run()
            return True, "[OK] Setup-Wizard abgeschlossen."
        except KeyboardInterrupt:
            return False, "[Abbruch] Setup-Wizard abgebrochen."
        except Exception as e:
            return False, f"[Fehler] Setup-Wizard fehlgeschlagen: {e}"

    def _help(self, args: List[str], dry_run: bool) -> Tuple[bool, str]:
        lines = [
            "Connector-System",
            "=" * 50,
            "",
            "Verwaltet externe Kommunikationsverbindungen und fuehrt sie aus.",
            "",
            "Verwaltung:",
            "  bach connector list                    Alle Connectors",
            "  bach connector status                  Status + Statistiken",
            "  bach connector add <type> <name> [url] Neuen Connector registrieren",
            "  bach connector remove <name>           Connector entfernen",
            "  bach connector enable <name>           Aktivieren",
            "  bach connector disable <name>          Deaktivieren",
            "",
            "Nachrichten:",
            "  bach connector messages [name]         Nachrichten anzeigen",
            "  bach connector unprocessed             Unverarbeitete Nachrichten",
            "  bach connector route                   Nachrichten routen (inbox)",
            "  bach connector send <name> <to> <text> In ausgehende Queue einreihen",
            "",
            "Runtime:",
            "  bach connector poll <name>             Einmal pollen (Nachrichten holen + speichern)",
            "  bach connector dispatch <name>         Ausgehende Queue versenden",
            "",
            "Queue-Management:",
            "  bach connector setup-daemon            Daemon-Jobs registrieren (einmalig)",
            "  bach connector queue-status            Queue-Statistiken (pending/failed/dead)",
            "  bach connector retry <id|all>          Dead-Letter zuruecksetzen",
            "",
            "Konfiguration:",
            "  bach connector configure <name> <key> <value>  Config-Wert setzen",
            "  Beispiel: bach connector configure telegram_main sender_tag BACH",
            "",
            "Setup:",
            "  bach connector setup-wizard            Interaktiver Wizard fuer neue Connectors",
            "",
            f"Unterstuetzte Typen: {', '.join(self.SUPPORTED_TYPES)}",
            "",
            "Runtime-Adapter verfuegbar: telegram, discord, signal, whatsapp, homeassistant",
            "Templates verfuegbar: telegram, signal, whatsapp, discord",
        ]
        return True, "\n".join(lines)
