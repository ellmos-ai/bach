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
Messages REST-API Router
=========================

FastAPI-Router fuer das BACH Message-System.
Wird in headless.py eingebunden.

Endpoints:
  POST /api/v1/messages/send      Nachricht in Queue einreihen
  GET  /api/v1/messages/queue     Queue-Status (pending/failed/dead)
  GET  /api/v1/messages/inbox     Inbox lesen (Paginierung, Filter)
  POST /api/v1/messages/route     Routing manuell ausloesen

Datum: 2026-02-08
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# BACH Root fuer Imports
BACH_ROOT = Path(__file__).parent.parent.parent
if str(BACH_ROOT) not in sys.path:
    sys.path.insert(0, str(BACH_ROOT))

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

# Auth + DB aus headless importieren
from gui.api.headless import verify_auth, _get_db

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])


# ── Models ────────────────────────────────────────────────────

class MessageSend(BaseModel):
    connector: str
    recipient: str
    content: str


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/send", status_code=201)
async def send_message(msg: MessageSend, _=Depends(verify_auth)):
    """Nachricht in die ausgehende Queue einreihen."""
    conn = _get_db()
    try:
        # Connector pruefen
        row = conn.execute(
            "SELECT is_active FROM connections WHERE name = ? AND category = 'connector'",
            (msg.connector,)
        ).fetchone()

        if not row:
            raise HTTPException(404, f"Connector '{msg.connector}' nicht gefunden.")
        if not row['is_active']:
            raise HTTPException(400, f"Connector '{msg.connector}' ist deaktiviert.")

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        cur = conn.execute("""
            INSERT INTO connector_messages
                (connector_name, direction, sender, recipient, content,
                 status, created_at)
            VALUES (?, 'out', 'bach', ?, ?, 'pending', ?)
        """, (msg.connector, msg.recipient, msg.content, now))
        conn.commit()

        return {
            "id": cur.lastrowid,
            "connector": msg.connector,
            "recipient": msg.recipient,
            "status": "pending",
            "queued_at": now,
        }
    finally:
        conn.close()


@router.get("/queue")
async def queue_status(_=Depends(verify_auth)):
    """Queue-Statistiken: pending/failed/dead pro Connector."""
    from hub._services.connector.queue_processor import get_queue_status
    return get_queue_status()


@router.get("/inbox")
async def inbox(
    status: str = "unread",
    sender: str = "",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    _=Depends(verify_auth),
):
    """Inbox lesen mit Paginierung und Filter."""
    conn = _get_db()
    try:
        query = """
            SELECT id, direction, sender, recipient, subject, body,
                   body_type, priority, status, metadata, created_at
            FROM messages
            WHERE direction = 'inbox'
        """
        params = []

        if status != "all":
            query += " AND status = ?"
            params.append(status)

        if sender:
            query += " AND sender LIKE ?"
            params.append(f"%{sender}%")

        # Count total
        count_query = query.replace(
            "SELECT id, direction, sender, recipient, subject, body,\n"
            "                   body_type, priority, status, metadata, created_at",
            "SELECT COUNT(*)"
        )
        total = conn.execute(count_query, params).fetchone()[0]

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

        messages = []
        for r in rows:
            msg = dict(r)
            # metadata als JSON parsen wenn vorhanden
            if msg.get('metadata'):
                try:
                    msg['metadata'] = json.loads(msg['metadata'])
                except (json.JSONDecodeError, TypeError):
                    pass
            messages.append(msg)

        return {
            "messages": messages,
            "count": len(messages),
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    finally:
        conn.close()


@router.post("/route")
async def route_messages(_=Depends(verify_auth)):
    """Routing manuell ausloesen: connector_messages(in) → messages(inbox)."""
    from hub._services.connector.queue_processor import route_incoming
    result = route_incoming()
    return {
        "routed": int(result.get("routed") or 0),
    }
