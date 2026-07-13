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
Queue Processor - Zuverlaessige Nachrichtenzustellung
=====================================================

Kern-Modul fuer automatisches Polling, Routing und Dispatching
von Connector-Nachrichten mit Retry/Backoff und Circuit Breaker.

Drei Hauptfunktionen:
  poll_all_connectors()  - Aktive Connectors pollen (eingehend)
  route_incoming()       - connector_messages(in) → messages(inbox)
  dispatch_outgoing()    - Ausgehende Queue mit Retry/Backoff versenden

Integration:
  - Daemon: 2 Jobs (poll_and_route alle 2min, dispatch alle 1min)
  - Injektoren: ContextInjector + context_triggers beim Routing
  - CLI: python queue_processor.py --action poll_and_route|dispatch|setup

Datum: 2026-02-08
"""

import os
import json
import sys
import sqlite3
import logging

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# Pfade
_THIS_DIR = Path(__file__).resolve().parent
SYSTEM_DIR = _THIS_DIR.parent.parent.parent  # hub/_services/connector → system/
DB_PATH = BACH_DB

# sys.path fuer Imports
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

logger = logging.getLogger("BACH-QueueProcessor")

# ── Konfiguration ──────────────────────────────────────────────

# Default Poll-Intervalle pro Connector-Typ (Sekunden)
DEFAULT_POLL_INTERVALS = {
    "telegram": 15,
    "discord": 60,
    "signal": 30,
    "whatsapp": 60,
    "homeassistant": 300,
    "webhook": 0,  # Push-basiert, kein Polling
}

# Retry-Backoff-Stufen (Sekunden): 30s, 60s, 120s, 240s, 480s (~15 Min gesamt)
BACKOFF_SCHEDULE = [30, 60, 120, 240, 480]

# Circuit Breaker: Nach N Fehlern Connector fuer M Sekunden sperren
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN = 300  # 5 Minuten


# ── Hilfsfunktionen ───────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    """Erstellt DB-Verbindung mit Row-Factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _instantiate_connector(name: str, conn: sqlite3.Connection):
    """Connector-Instanz aus DB-Config erstellen.

    Returns:
        (connector_instance, connector_type, error_string)
    """
    row = conn.execute("""
        SELECT name, type, endpoint, is_active, auth_type, auth_config,
               consecutive_failures, disabled_until
        FROM connections
        WHERE name = ? AND category = 'connector'
    """, (name,)).fetchone()

    if not row:
        return None, None, f"Connector '{name}' nicht gefunden."
    if not row['is_active']:
        return None, None, f"Connector '{name}' ist deaktiviert."

    # Circuit Breaker pruefen
    if row['disabled_until']:
        try:
            disabled_until = datetime.fromisoformat(row['disabled_until'])
            if datetime.now() < disabled_until:
                remaining = int((disabled_until - datetime.now()).total_seconds())
                return None, None, f"Connector '{name}' gesperrt (Circuit Breaker, noch {remaining}s)"
            else:
                # Cooldown abgelaufen → Reset
                conn.execute("""
                    UPDATE connections SET consecutive_failures = 0, disabled_until = NULL
                    WHERE name = ?
                """, (name,))
                conn.commit()
        except (ValueError, TypeError):
            pass

    conn_type = row['type']
    endpoint = row['endpoint'] or ""
    auth_type = row['auth_type'] or "api_key"
    auth_data = json.loads(row['auth_config']) if row['auth_config'] else {}

    try:
        from connectors.base import ConnectorConfig

        config = ConnectorConfig(
            name=row['name'],
            connector_type=conn_type,
            endpoint=endpoint,
            auth_type=auth_type,
            auth_config=auth_data,
            options=auth_data,
        )

        if conn_type == "telegram":
            from connectors.telegram_connector import TelegramConnector
            return TelegramConnector(config), conn_type, ""
        elif conn_type == "discord":
            from connectors.discord_connector import DiscordConnector
            return DiscordConnector(config), conn_type, ""
        elif conn_type == "signal":
            from connectors.signal_connector import SignalConnector
            return SignalConnector(config), conn_type, ""
        elif conn_type == "whatsapp":
            from connectors.whatsapp_connector import WhatsAppConnector
            return WhatsAppConnector(config), conn_type, ""
        elif conn_type == "homeassistant":
            from connectors.homeassistant_connector import HomeAssistantConnector
            return HomeAssistantConnector(config), conn_type, ""
        else:
            return None, conn_type, f"Kein Runtime-Adapter fuer Typ '{conn_type}'."
    except ImportError as e:
        return None, conn_type, f"Import-Fehler fuer '{conn_type}': {e}"


def _update_circuit_breaker(conn: sqlite3.Connection, name: str, success: bool):
    """Circuit Breaker aktualisieren nach Poll/Dispatch."""
    if success:
        conn.execute("""
            UPDATE connections SET consecutive_failures = 0, disabled_until = NULL
            WHERE name = ?
        """, (name,))
    else:
        conn.execute("""
            UPDATE connections SET consecutive_failures = consecutive_failures + 1
            WHERE name = ?
        """, (name,))

        row = conn.execute(
            "SELECT consecutive_failures FROM connections WHERE name = ?",
            (name,)
        ).fetchone()

        if row and row['consecutive_failures'] >= CIRCUIT_BREAKER_THRESHOLD:
            disabled_until = (datetime.now() + timedelta(seconds=CIRCUIT_BREAKER_COOLDOWN)).isoformat()
            conn.execute("""
                UPDATE connections SET disabled_until = ?
                WHERE name = ?
            """, (disabled_until, name))
            logger.warning(f"Circuit Breaker: '{name}' fuer {CIRCUIT_BREAKER_COOLDOWN}s gesperrt")

    conn.commit()


# ── Hauptfunktionen ───────────────────────────────────────────

def poll_all_connectors() -> Dict[str, Any]:
    """Pollt alle aktiven Connectors und speichert eingehende Nachrichten.

    Prueft Poll-Intervall pro Connector (aus auth_config oder Default).

    Returns:
        dict mit polled, messages_stored, errors
    """
    result = {"polled": [], "messages_stored": 0, "errors": []}
    conn = _get_db()

    try:
        connectors = conn.execute("""
            SELECT name, type, auth_config, last_used
            FROM connections
            WHERE category = 'connector' AND is_active = 1
              AND (disabled_until IS NULL OR disabled_until < ?)
        """, (_now_iso(),)).fetchall()

        for c in connectors:
            name = c['name']
            conn_type = c['type']

            # Poll-Intervall bestimmen
            auth_data = json.loads(c['auth_config']) if c['auth_config'] else {}
            poll_interval = auth_data.get("poll_interval",
                                          DEFAULT_POLL_INTERVALS.get(conn_type, 120))

            if poll_interval <= 0:
                continue  # Push-basiert (webhook), kein Polling

            # Pruefen ob Poll faellig
            if c['last_used']:
                try:
                    last_used = datetime.fromisoformat(c['last_used'])
                    if (datetime.now() - last_used).total_seconds() < poll_interval:
                        continue  # Noch nicht faellig
                except (ValueError, TypeError):
                    pass

            # Connector instanziieren und pollen
            instance, _, err = _instantiate_connector(name, conn)
            if not instance:
                result["errors"].append(f"{name}: {err}")
                continue

            try:
                if not instance.connect():
                    result["errors"].append(f"{name}: Verbindung fehlgeschlagen")
                    _update_circuit_breaker(conn, name, False)
                    continue

                messages = instance.get_messages()
            except Exception as e:
                result["errors"].append(f"{name}: Poll-Fehler: {type(e).__name__}: {e}")
                _update_circuit_breaker(conn, name, False)
                try:
                    instance.disconnect()
                except Exception:
                    pass
                continue

            # Disconnect erst nach erfolgreichem Poll
            try:
                instance.disconnect()
            except Exception as e:
                logger.warning(f"Disconnect-Fehler bei {name}: {e}")

            # Nachrichten speichern (mit Duplikat-Schutz)
            try:
                now = _now_iso()
                stored = 0
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
                            continue

                        conn.execute("""
                            INSERT INTO connector_messages
                                (connector_name, direction, sender, recipient, content,
                                 status, created_at)
                            VALUES (?, ?, ?, ?, ?, 'pending', ?)
                        """, (name, msg.direction, msg.sender, "", msg.content, now))
                        stored += 1
                    except Exception as e:
                        logger.warning(f"Nachricht speichern fehlgeschlagen: {e}")

                # last_update_id persistent speichern (verhindert Duplikate)
                if hasattr(instance, '_last_update_id') and instance._last_update_id > 0:
                    auth_data['last_update_id'] = instance._last_update_id
                    conn.execute(
                        "UPDATE connections SET auth_config = ? WHERE name = ?",
                        (json.dumps(auth_data, ensure_ascii=True), name))

                # Stats aktualisieren
                conn.execute("""
                    UPDATE connections
                    SET success_count = success_count + ?, last_used = ?
                    WHERE name = ?
                """, (stored, now, name))

                _update_circuit_breaker(conn, name, True)
                result["polled"].append(name)
                result["messages_stored"] += stored
                logger.info(f"Poll '{name}': {stored} Nachrichten")

            except Exception as save_error:
                logger.error(f"Fehler beim Speichern von Nachrichten fuer {name}: {type(save_error).__name__}: {save_error}")
                result["errors"].append(f"{name}: Speichern fehlgeschlagen: {save_error}")
                _update_circuit_breaker(conn, name, False)

        conn.commit()

    finally:
        conn.close()

    return result


def route_incoming() -> Dict[str, Any]:
    """Routet eingehende connector_messages in die messages-Inbox.

    Wendet ContextInjector + context_triggers an fuer Kontext-Hints.

    Returns:
        dict mit routed, errors
    """
    result = {"routed": 0, "errors": []}
    conn = _get_db()

    try:
        rows = conn.execute("""
            SELECT id, connector_name, sender, content
            FROM connector_messages
            WHERE direction = 'in' AND status = 'pending' AND processed = 0
            ORDER BY created_at ASC
        """).fetchall()

        if not rows:
            return result

        # ContextInjector laden (optional)
        injector_hint_fn = None
        try:
            from tools.injectors import ContextInjector
            ContextInjector.base_path = SYSTEM_DIR
            injector_hint_fn = ContextInjector.check
        except ImportError:
            logger.debug("ContextInjector nicht verfuegbar")

        now = _now_iso()

        for row in rows:
            msg_id = row['id']
            connector = row['connector_name']
            sender_raw = row['sender'] or "unknown"
            content = row['content'] or ""

            # Sender-Format: "connector:sender_id"
            sender = f"{connector}:{sender_raw}"

            # Kontext-Hints sammeln
            metadata = {
                "source": sender,
                "routed_at": now,
            }

            # a) ContextInjector (hardcoded ~100 Trigger + DB cache)
            if injector_hint_fn:
                try:
                    hint = injector_hint_fn(content)
                    if hint:
                        metadata["injector_hint"] = hint
                except Exception:
                    pass

            # b) context_triggers Tabelle (900+ dynamische Trigger)
            try:
                content_lower = content.lower()
                triggers = conn.execute("""
                    SELECT trigger_phrase, hint_text FROM context_triggers
                    WHERE is_active = 1
                """).fetchall()
                matched = [t['trigger_phrase'] for t in triggers
                           if t['trigger_phrase'] in content_lower]
                if matched:
                    metadata["context_triggers"] = matched
            except Exception:
                pass  # Tabelle existiert evtl. nicht

            try:
                # Duplikat-Check: gleicher Sender+Body bereits in messages?
                existing = conn.execute("""
                    SELECT id FROM messages
                    WHERE sender = ? AND body = ? AND direction = 'inbox'
                    LIMIT 1
                """, (sender, content)).fetchone()

                if existing:
                    # Duplikat - nur als verarbeitet markieren
                    conn.execute("""
                        UPDATE connector_messages
                        SET processed = 1, status = 'sent', updated_at = ?
                        WHERE id = ?
                    """, (now, msg_id))
                    continue

                conn.execute("""
                    INSERT INTO messages
                        (direction, sender, recipient, subject, body,
                         body_type, status, metadata, created_at)
                    VALUES ('inbox', ?, 'bach', ?, ?, 'text', 'unread', ?, ?)
                """, (sender, f"Connector: {connector}", content,
                      json.dumps(metadata, ensure_ascii=False), now))

                conn.execute("""
                    UPDATE connector_messages
                    SET processed = 1, status = 'sent', updated_at = ?
                    WHERE id = ?
                """, (now, msg_id))

                result["routed"] += 1

            except Exception as e:
                conn.execute("""
                    UPDATE connector_messages
                    SET error = ?, updated_at = ?
                    WHERE id = ?
                """, (str(e)[:200], now, msg_id))
                result["errors"].append(f"#{msg_id}: {e}")

        conn.commit()
        logger.info(f"Route: {result['routed']}/{len(rows)} Nachrichten geroutet")

    finally:
        conn.close()

    return result


def dispatch_outgoing() -> Dict[str, Any]:
    """Versendet ausgehende Queue mit Retry und exponentiellem Backoff.

    Nachrichten werden pro Connector gruppiert (1x connect/disconnect).

    Returns:
        dict mit sent, retried, dead, errors
    """
    result = {"sent": 0, "retried": 0, "dead": 0, "errors": []}
    conn = _get_db()

    try:
        now = _now_iso()
        now_dt = datetime.now()

        # Pending + Failed (mit faelligem Retry) holen, gruppiert pro Connector
        rows = conn.execute("""
            SELECT id, connector_name, recipient, content, retry_count, max_retries
            FROM connector_messages
            WHERE direction = 'out'
              AND status IN ('pending', 'failed')
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY connector_name, created_at ASC
        """, (now,)).fetchall()

        if not rows:
            return result

        # Pro Connector gruppieren
        by_connector: Dict[str, list] = {}
        for row in rows:
            name = row['connector_name']
            by_connector.setdefault(name, []).append(row)

        for connector_name, messages in by_connector.items():
            instance, _, err = _instantiate_connector(connector_name, conn)
            if not instance:
                # Alle Nachrichten als failed markieren
                for msg in messages:
                    _schedule_retry(conn, msg, err)
                    result["retried"] += 1
                result["errors"].append(f"{connector_name}: {err}")
                continue

            connected = False
            try:
                connected = instance.connect()
            except Exception as e:
                result["errors"].append(f"{connector_name}: connect failed: {e}")

            if not connected:
                _update_circuit_breaker(conn, connector_name, False)
                for msg in messages:
                    _schedule_retry(conn, msg, "connect failed")
                    result["retried"] += 1
                continue

            sent_count = 0
            error_count = 0

            for msg in messages:
                msg_id = msg['id']
                try:
                    # Encoding-Sanitierung vor dem Versand
                    try:
                        from tools.encoding_fix import sanitize_outbound
                        send_content = sanitize_outbound(msg['content'] or "")
                    except ImportError:
                        send_content = msg['content'] or ""
                    ok = instance.send_message(msg['recipient'], send_content)
                    if ok:
                        conn.execute("""
                            UPDATE connector_messages
                            SET processed = 1, status = 'sent', updated_at = ?
                            WHERE id = ?
                        """, (now, msg_id))
                        sent_count += 1
                        result["sent"] += 1
                    else:
                        dead = _schedule_retry(conn, msg, "send_failed")
                        if dead:
                            result["dead"] += 1
                        else:
                            result["retried"] += 1
                        error_count += 1

                except Exception as e:
                    dead = _schedule_retry(conn, msg, str(e)[:200])
                    if dead:
                        result["dead"] += 1
                    else:
                        result["retried"] += 1
                    error_count += 1

            # Stats aktualisieren
            conn.execute("""
                UPDATE connections
                SET success_count = success_count + ?,
                    error_count = error_count + ?,
                    last_used = ?
                WHERE name = ?
            """, (sent_count, error_count, now, connector_name))

            _update_circuit_breaker(conn, connector_name, error_count == 0)

            try:
                instance.disconnect()
            except Exception:
                pass

        conn.commit()
        logger.info(f"Dispatch: {result['sent']} sent, {result['retried']} retried, {result['dead']} dead")

    finally:
        conn.close()

    return result


def _schedule_retry(conn: sqlite3.Connection, msg, error: str) -> bool:
    """Plant Retry mit exponentiellem Backoff oder markiert als Dead Letter.

    Returns:
        True wenn Dead Letter (max_retries ueberschritten)
    """
    msg_id = msg['id']
    retry_count = msg['retry_count']
    max_retries = msg['max_retries']
    now = _now_iso()

    if retry_count >= max_retries:
        # Dead Letter
        conn.execute("""
            UPDATE connector_messages
            SET status = 'dead', error = ?, updated_at = ?
            WHERE id = ?
        """, (error, now, msg_id))
        logger.warning(f"Dead Letter: #{msg_id} nach {retry_count} Versuchen")
        return True

    # Naechsten Retry planen
    backoff_idx = min(retry_count, len(BACKOFF_SCHEDULE) - 1)
    backoff_sec = BACKOFF_SCHEDULE[backoff_idx]
    next_retry = (datetime.now() + timedelta(seconds=backoff_sec)).isoformat()

    conn.execute("""
        UPDATE connector_messages
        SET status = 'failed',
            retry_count = retry_count + 1,
            next_retry_at = ?,
            error = ?,
            updated_at = ?
        WHERE id = ?
    """, (next_retry, error, now, msg_id))

    logger.info(f"Retry #{msg_id}: Versuch {retry_count + 1}/{max_retries}, naechster in {backoff_sec}s")
    return False


# ── Daemon-Integration ────────────────────────────────────────

def ensure_scheduler_jobs() -> Tuple[bool, str]:
    """Registriert die 2 Daemon-Jobs (idempotent via INSERT OR IGNORE).

    Jobs:
      1. connector_poll_and_route (interval 2m) - Polling + Routing
      2. connector_dispatch (interval 1m) - Outbound Queue versenden

    Returns:
        (success, message)
    """
    conn = _get_db()
    try:
        now = _now_iso()

        # Job 1: Poll + Route
        conn.execute("""
            INSERT OR IGNORE INTO scheduler_jobs
                (name, description, job_type, schedule, command,
                 script_path, is_active, timeout_seconds, created_at)
            VALUES (
                'connector_poll_and_route',
                'Pollt aktive Connectors und routet eingehende Nachrichten in die Inbox',
                'interval', '2m',
                'python hub/_services/connector/queue_processor.py --action poll_and_route',
                'hub/_services/connector/queue_processor.py',
                1, 120, ?
            )
        """, (now,))

        # Job 2: Dispatch
        conn.execute("""
            INSERT OR IGNORE INTO scheduler_jobs
                (name, description, job_type, schedule, command,
                 script_path, is_active, timeout_seconds, created_at)
            VALUES (
                'connector_dispatch',
                'Versendet ausgehende Nachrichten-Queue mit Retry und Backoff',
                'interval', '1m',
                'python hub/_services/connector/queue_processor.py --action dispatch',
                'hub/_services/connector/queue_processor.py',
                1, 60, ?
            )
        """, (now,))

        conn.commit()

        # Pruefen was angelegt wurde
        jobs = conn.execute("""
            SELECT name, is_active, schedule FROM scheduler_jobs
            WHERE name IN ('connector_poll_and_route', 'connector_dispatch')
        """).fetchall()

        lines = ["Daemon-Jobs registriert:"]
        for j in jobs:
            status = "aktiv" if j['is_active'] else "inaktiv"
            lines.append(f"  {j['name']} ({j['schedule']}) [{status}]")

        return True, "\n".join(lines)

    except Exception as e:
        return False, f"Daemon-Jobs Fehler: {e}"
    finally:
        conn.close()


# ── Queue-Status ──────────────────────────────────────────────

def get_queue_status() -> Dict[str, Any]:
    """Liefert Queue-Statistiken pro Connector.

    Returns:
        dict mit connectors, totals
    """
    conn = _get_db()
    try:
        stats = conn.execute("""
            SELECT
                connector_name,
                direction,
                status,
                COUNT(*) as cnt
            FROM connector_messages
            GROUP BY connector_name, direction, status
        """).fetchall()

        by_connector: Dict[str, Dict] = {}
        totals = {"pending": 0, "sent": 0, "failed": 0, "dead": 0}

        for row in stats:
            name = row['connector_name']
            if name not in by_connector:
                by_connector[name] = {"in": {}, "out": {}}

            direction = row['direction']
            status = row['status'] or "pending"
            count = row['cnt']

            by_connector[name][direction][status] = count
            if direction == 'out' and status in totals:
                totals[status] += count

        return {"connectors": by_connector, "totals": totals}

    finally:
        conn.close()


def retry_dead_letters(msg_id: Optional[int] = None) -> Tuple[bool, str]:
    """Setzt Dead-Letter-Nachrichten zurueck auf 'pending'.

    Args:
        msg_id: Spezifische Nachricht oder None fuer alle

    Returns:
        (success, message)
    """
    conn = _get_db()
    try:
        now = _now_iso()

        if msg_id:
            result = conn.execute("""
                UPDATE connector_messages
                SET status = 'pending', retry_count = 0, next_retry_at = NULL,
                    error = NULL, updated_at = ?
                WHERE id = ? AND status = 'dead'
            """, (now, msg_id))
            count = result.rowcount
        else:
            result = conn.execute("""
                UPDATE connector_messages
                SET status = 'pending', retry_count = 0, next_retry_at = NULL,
                    error = NULL, updated_at = ?
                WHERE status = 'dead'
            """, (now,))
            count = result.rowcount

        conn.commit()

        if count == 0:
            return True, "Keine Dead-Letter-Nachrichten gefunden."
        return True, f"[OK] {count} Nachricht(en) zurueckgesetzt auf 'pending'."

    except Exception as e:
        return False, f"Fehler: {e}"
    finally:
        conn.close()


# ── CLI Entry Point ───────────────────────────────────────────

def main():
    """CLI-Einstiegspunkt fuer Daemon-Ausfuehrung."""
    import argparse

    parser = argparse.ArgumentParser(description="BACH Connector Queue Processor")
    parser.add_argument("--action", required=True,
                        choices=["poll_and_route", "dispatch", "setup", "status", "retry"],
                        help="Auszufuehrende Aktion")
    parser.add_argument("--msg-id", type=int, help="Nachricht-ID fuer retry")

    args = parser.parse_args()

    # Logging fuer CLI
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    if args.action == "poll_and_route":
        poll_result = poll_all_connectors()
        route_result = route_incoming()
        print(f"Poll: {len(poll_result['polled'])} Connectors, "
              f"{poll_result['messages_stored']} Nachrichten gespeichert")
        print(f"Route: {route_result['routed']} Nachrichten geroutet")
        if poll_result['errors']:
            print(f"Poll-Fehler: {', '.join(poll_result['errors'])}")
        if route_result['errors']:
            print(f"Route-Fehler: {', '.join(route_result['errors'])}")

    elif args.action == "dispatch":
        result = dispatch_outgoing()
        print(f"Dispatch: {result['sent']} gesendet, "
              f"{result['retried']} retry geplant, "
              f"{result['dead']} dead letter")
        if result['errors']:
            print(f"Fehler: {', '.join(result['errors'])}")

    elif args.action == "setup":
        ok, msg = ensure_scheduler_jobs()
        print(msg)
        sys.exit(0 if ok else 1)

    elif args.action == "status":
        status = get_queue_status()
        print("Queue Status")
        print("=" * 50)
        print(f"  Pending: {status['totals']['pending']}")
        print(f"  Sent:    {status['totals']['sent']}")
        print(f"  Failed:  {status['totals']['failed']}")
        print(f"  Dead:    {status['totals']['dead']}")
        if status['connectors']:
            print("\nPro Connector:")
            for name, dirs in status['connectors'].items():
                print(f"  {name}:")
                for direction, statuses in dirs.items():
                    if statuses:
                        parts = [f"{s}={c}" for s, c in statuses.items()]
                        print(f"    {direction}: {', '.join(parts)}")

    elif args.action == "retry":
        ok, msg = retry_dead_letters(args.msg_id)
        print(msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
