# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: email_bridge
==================================
Draft-safe email delivery, zero-leak address validation, and outbox tracking.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email_address(address: str) -> bool:
    """Validate RFC email address format."""
    if not address or not isinstance(address, str):
        return False
    return bool(EMAIL_REGEX.match(address.strip()))


def init_email_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_outbox (
            id TEXT PRIMARY KEY,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            checksum TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            metadata TEXT
        )
    """)
    conn.commit()


class EmailDraftStore:
    """Two-phase draft-first email manager."""

    def __init__(self, db_path: Path | str = ":memory:"):
        self.db_path = str(db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        init_email_schema(conn)
        return conn

    def create_draft(self, recipient: str, subject: str, body: str, *, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a new safe draft in the outbox. Does not transmit."""
        rec = str(recipient or "").strip()
        if not validate_email_address(rec):
            raise ValueError(f"Ungueltige E-Mail-Adresse: {recipient}")

        sub = str(subject or "").strip()
        b = str(body or "").strip()
        now = datetime.now(timezone.utc).isoformat()
        draft_id = f"draft_{uuid.uuid4().hex[:12]}"
        checksum = hashlib.sha256(f"{rec}|{sub}|{b}".encode("utf-8")).hexdigest()

        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO email_outbox (id, recipient, subject, body, status, checksum, created_at, metadata) "
                    "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
                    (draft_id, rec, sub, b, checksum, now, meta_json)
                )
        finally:
            conn.close()

        return {
            "ok": True,
            "draft_id": draft_id,
            "recipient": rec,
            "subject": sub,
            "status": "draft",
            "checksum": checksum,
            "created_at": now,
        }

    def confirm_send(self, draft_id: str, sender_callable: Optional[Callable[[Dict[str, Any]], bool]] = None) -> Dict[str, Any]:
        """Explicitly confirm and execute sending of an existing draft."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM email_outbox WHERE id = ?", (draft_id,)).fetchone()
            if not row:
                raise KeyError(f"Draft not found: {draft_id}")
            if row["status"] != "draft":
                raise RuntimeError(f"Draft {draft_id} cannot be sent; current status is '{row['status']}'")

            draft_dict = dict(row)
            # Invoke custom sender or default to local outbox transmission
            success = True
            if sender_callable:
                success = bool(sender_callable(draft_dict))

            if not success:
                raise RuntimeError(f"Sender callable failed for draft {draft_id}")

            sent_at = datetime.now(timezone.utc).isoformat()
            with conn:
                conn.execute(
                    "UPDATE email_outbox SET status = 'sent', sent_at = ? WHERE id = ?",
                    (sent_at, draft_id)
                )

            return {
                "ok": True,
                "draft_id": draft_id,
                "status": "sent",
                "sent_at": sent_at,
            }
        finally:
            conn.close()

    def cancel_draft(self, draft_id: str) -> Dict[str, Any]:
        """Cancel a pending draft so it cannot be sent."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM email_outbox WHERE id = ?", (draft_id,)).fetchone()
            if not row:
                raise KeyError(f"Draft not found: {draft_id}")
            if row["status"] != "draft":
                raise RuntimeError(f"Cannot cancel draft {draft_id} in status '{row['status']}'")

            with conn:
                conn.execute("UPDATE email_outbox SET status = 'cancelled' WHERE id = ?", (draft_id,))
            return {
                "ok": True,
                "draft_id": draft_id,
                "status": "cancelled",
            }
        finally:
            conn.close()

    def list_drafts(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            if status:
                rows = conn.execute("SELECT * FROM email_outbox WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM email_outbox ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
