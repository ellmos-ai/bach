"""User Inbox projection on assistant-core's canonical messages connection."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

class InboxChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unread", "read", "archived"]
    expected_status: Literal["unread", "read", "archived"]

def build_router(store_factory):
    router = APIRouter(prefix="/api/user-inbox", tags=["User Inbox"])
    # Recipient restriction is applied before counts and pagination.
    base = "direction = 'inbox' AND LOWER(TRIM(COALESCE(recipient, ''))) = 'user' AND COALESCE(status, 'unread') != 'deleted'"

    @router.get("")
    def list_inbox(status: Literal["all", "unread", "read", "archived"] = "all",
                   search: str = Query("", max_length=300),
                   offset: int = Query(0, ge=0),
                   limit: int = Query(50, ge=1, le=100)):
        where = base
        args = []
        if status == "all":
            where += " AND COALESCE(status, 'unread') != 'archived'"
        else:
            where += " AND COALESCE(status, 'unread') = ?"
            args.append(status)
        if search.strip():
            where += " AND (COALESCE(subject, '') LIKE ? ESCAPE '\\' OR COALESCE(body, '') LIKE ? ESCAPE '\\' OR COALESCE(sender, '') LIKE ? ESCAPE '\\')"
            term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args.extend(["%" + term + "%"] * 3)
        with store_factory().connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM messages WHERE " + where, args).fetchone()[0]
            rows = [dict(row) for row in conn.execute(
                "SELECT id, sender, recipient, subject, body, COALESCE(status, 'unread') AS status, created_at, read_at FROM messages WHERE " + where +
                " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", [*args, limit, offset])]
            unread = conn.execute("SELECT COUNT(*) FROM messages WHERE " + base + " AND COALESCE(status, 'unread') = 'unread'").fetchone()[0]
        return {"schema": "bach.user-inbox.v1", "source": "assistant-core.messages",
                "recipient": "user", "messages": rows, "total": total, "unread": unread,
                "offset": offset, "limit": limit, "has_more": offset + len(rows) < total}

    @router.patch("/{message_id}")
    def change_status(message_id: int, change: InboxChange):
        if message_id < 1:
            raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")
        with store_factory().connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT id, COALESCE(status, 'unread') AS status FROM messages WHERE id = ? AND " + base, (message_id,)).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Nachricht nicht gefunden")
            if current["status"] != change.expected_status:
                raise HTTPException(status_code=409, detail="Nachrichtenstatus wurde inzwischen geändert. Bitte aktualisieren.")
            if change.status == "read":
                conn.execute("UPDATE messages SET status = ?, read_at = ? WHERE id = ? AND " + base,
                             (change.status, datetime.now().isoformat(), message_id))
            elif change.status == "unread":
                conn.execute("UPDATE messages SET status = ?, read_at = NULL WHERE id = ? AND " + base, (change.status, message_id))
            else:
                conn.execute("UPDATE messages SET status = ? WHERE id = ? AND " + base, (change.status, message_id))
        return {"id": message_id, "recipient": "user", "status": change.status}

    return router
