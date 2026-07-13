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
Smart Router - Intelligentes Nachrichten-Routing mit Launcher
==============================================================

Erweitert das Standard-Routing um:
  1. Command-Parsing aus Nachrichten
  2. Launcher-basierte Ausführung
  3. Response-Routing zurück zum Sender

Usage:
    from hub._services.connector.smart_router import smart_route_messages

    success, msg = smart_route_messages(base_path, connector_name="telegram")

Autor: Claude Worker-Agent
Datum: 2026-02-14
"""

import os
import sys
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Optional

# Den DB-Pfad zentral erfragen, nicht selbst bauen: ein repo-relativer Pfad zeigt auf die
# veraltete Kopie im OneDrive-Ordner (bzw. auf ein Verzeichnis, das es gar nicht gibt —
# dort legt sqlite3.connect() still eine leere 0-KB-Datenbank an).
_SYSTEM_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "hub" / "bach_paths.py").exists()
)
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))
from hub.bach_paths import BACH_DB

# UTF-8 Encoding fix
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def parse_command(text: str) -> Optional[Tuple[str, str, List[str]]]:
    """
    Parsed Command aus Nachricht.

    Args:
        text: Nachrichtentext

    Returns:
        (command, operation, args) oder None

    Examples:
        "task add Test" → ("task", "add", ["Test"])
        "/steuer status" → ("steuer", "status", [])
        "Zeige Tasks" → None (kein Command)
    """
    text = text.strip()

    # Pattern 1: /command operation args
    match = re.match(r'^/(\w+)(?:\s+(\w+))?(?:\s+(.+))?$', text)
    if match:
        cmd = match.group(1)
        op = match.group(2) or ""
        args_str = match.group(3) or ""
        args = args_str.split() if args_str else []
        return (cmd, op, args)

    # Pattern 2: command operation args (ohne Slash)
    match = re.match(r'^(\w+)(?:\s+(\w+))?(?:\s+(.+))?$', text)
    if match:
        cmd = match.group(1).lower()

        # Nur wenn command ein bekannter Handler ist
        known_commands = ["task", "steuer", "mem", "backup", "partner", "connector"]
        if cmd in known_commands:
            op = match.group(2) or ""
            args_str = match.group(3) or ""
            args = [args_str] if args_str else []
            return (cmd, op, args)

    return None


def smart_route_messages(base_path: Path,
                         connector_name: Optional[str] = None,
                         dry_run: bool = False) -> Tuple[bool, str]:
    """
    Routet unverarbeitete Nachrichten mit Launcher-Integration.

    Args:
        base_path: system/ Verzeichnis
        connector_name: Optional: Nur Nachrichten von diesem Connector
        dry_run: Nur simulieren

    Returns:
        (success, message) Tuple
    """
    db_path = BACH_DB

    if not db_path.exists():
        return False, "[ERROR] Datenbank nicht gefunden"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Unverarbeitete eingehende Nachrichten holen
        if connector_name:
            rows = conn.execute("""
                SELECT id, connector_name, sender, recipient, content
                FROM connector_messages
                WHERE processed = 0 AND direction = 'in' AND connector_name = ?
                ORDER BY created_at ASC
            """, (connector_name,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, connector_name, sender, recipient, content
                FROM connector_messages
                WHERE processed = 0 AND direction = 'in'
                ORDER BY created_at ASC
            """).fetchall()

        if not rows:
            return True, "[OK] Keine Nachrichten zum Routen"

        processed = 0
        executed = 0
        routed_to_inbox = 0
        errors = 0

        lines = [f"Smart-Routing: {len(rows)} Nachrichten...", ""]

        for row in rows:
            msg_id = row['id']
            connector = row['connector_name']
            sender = row['sender']
            content = row['content'] or ""

            if dry_run:
                lines.append(f"  [DRY] #{msg_id} von {sender}: {content[:60]}")
                continue

            # Versuche Command zu parsen
            parsed = parse_command(content)

            if parsed:
                # Command gefunden → Über Launcher ausführen
                cmd, op, args = parsed

                try:
                    from core.launcher import route_command

                    success, response = route_command(
                        command=cmd,
                        operation=op,
                        args=args,
                        source=connector,
                        user=sender,
                        base_path=base_path
                    )

                    # Response zurück über Connector senden
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute("""
                        INSERT INTO connector_messages
                        (connector_name, direction, sender, recipient, content, created_at)
                        VALUES (?, 'out', 'bach', ?, ?, ?)
                    """, (connector, sender, response, now))

                    # Nachricht als verarbeitet markieren
                    conn.execute("""
                        UPDATE connector_messages SET processed = 1 WHERE id = ?
                    """, (msg_id,))

                    processed += 1
                    executed += 1
                    lines.append(f"  [EXEC] #{msg_id}: {cmd} {op} → {success}")

                except Exception as e:
                    # Fehler bei Ausführung
                    conn.execute("""
                        UPDATE connector_messages SET error = ? WHERE id = ?
                    """, (str(e)[:200], msg_id))
                    errors += 1
                    lines.append(f"  [ERR] #{msg_id}: {e}")

            else:
                # Kein Command → Normal in inbox routen
                sender_full = f"{connector}:{sender}"
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                try:
                    # Duplikat-Check
                    existing = conn.execute("""
                        SELECT id FROM messages
                        WHERE sender = ? AND body = ? AND direction = 'inbox'
                        LIMIT 1
                    """, (sender_full, content)).fetchone()

                    if existing:
                        # Duplikat - überspringen
                        conn.execute("""
                            UPDATE connector_messages SET processed = 1 WHERE id = ?
                        """, (msg_id,))
                        continue

                    # In messages eintragen
                    conn.execute("""
                        INSERT INTO messages (direction, sender, recipient, subject, body,
                                            body_type, status, created_at)
                        VALUES ('inbox', ?, 'bach', ?, ?, 'text', 'unread', ?)
                    """, (sender_full, f"Connector: {connector}", content, now))

                    conn.execute("""
                        UPDATE connector_messages SET processed = 1 WHERE id = ?
                    """, (msg_id,))

                    processed += 1
                    routed_to_inbox += 1
                    lines.append(f"  [INBOX] #{msg_id}")

                except Exception as e:
                    conn.execute("""
                        UPDATE connector_messages SET error = ? WHERE id = ?
                    """, (str(e)[:200], msg_id))
                    errors += 1
                    lines.append(f"  [ERR] #{msg_id}: {e}")

        conn.commit()

        # Summary
        lines.append("")
        lines.append(f"Verarbeitet: {processed}/{len(rows)}")
        lines.append(f"  - Commands ausgeführt: {executed}")
        lines.append(f"  - An Inbox: {routed_to_inbox}")
        if errors:
            lines.append(f"  - Fehler: {errors}")

        return True, "\n".join(lines)

    finally:
        conn.close()
