# -*- coding: utf-8 -*-
"""Tests for hub/_services/chat/message_worker.py -- the consumer for order
messages the GUI writes into `messages` (FABLE-SOL-PLAN 1.1.4)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.message_worker import file_reply, pending_orders, run_once  # noqa: E402
from hub._services.chat._messages_compat import (  # noqa: E402
    file_reply as compat_file_reply,
    pending_orders as compat_pending_orders,
    run_once as compat_run_once,
)
from hub._services.chat.chat_runtime import (  # noqa: E402
    FailedAnswer,
    SuccessfulAnswer,
)

SCHEMA = """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT, sender TEXT, recipient TEXT, subject TEXT, body TEXT,
    body_type TEXT DEFAULT 'text', priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'unread', tags TEXT, parent_id INTEGER, thread_id TEXT,
    topic TEXT, attachments TEXT, metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, read_at TIMESTAMP, archived_at TIMESTAMP,
    dist_type INTEGER DEFAULT 0
)
"""


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "bach.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return str(path)


def _order(db, recipient, body, subject=None, status="read"):
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO messages (direction, sender, recipient, subject, body, status) VALUES ('outbox', 'user', ?, ?, ?, ?)",
        (recipient, subject, body, status),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def test_pending_orders_only_unanswered_orders_to_local_agents(db):
    """Recipient filter is case-insensitive; foreign agents, empty bodies and
    already-answered orders are left alone."""
    keep = _order(db, "ollama", "Fasse den Tag zusammen")
    _order(db, "gemini", "not for us")
    _order(db, "Buddha", "")  # empty body -> skipped
    answered = _order(db, "bach", "already done")
    conn = sqlite3.connect(db)
    file_reply(conn, {"id": answered, "recipient": "bach", "subject": None, "body": "already done"}, "ok")
    ids = [o["id"] for o in pending_orders(conn)]
    conn.close()
    assert ids == [keep]


def test_run_once_answers_via_runtime_and_files_inbox_reply(db):
    """The reply is an inbox message to the user with parent_id = order id --
    that link is the 'answered' marker (no new status, no new table)."""
    order_id = _order(db, "ollama", "Wie spät ist es?", subject="Frage")
    seen = []

    def process(text, chat_id):
        seen.append((text, chat_id))
        return "Es ist spät."

    assert run_once(db, process) == 1
    assert seen == [("Wie spät ist es?", f"msg-{order_id}")]
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT direction, sender, recipient, subject, body, parent_id FROM messages WHERE parent_id = ?",
        (order_id,),
    ).fetchone()
    conn.close()
    assert row == ("inbox", "ollama", "user", "Re: Frage", "Es ist spät.", order_id)
    # second poll: nothing left, and the runtime is not called again
    assert run_once(db, process) == 0
    assert len(seen) == 1


def test_failed_processing_keeps_the_order_pending(db):
    order_id = _order(db, "buddha", "kaputt")

    def boom(text, chat_id):
        raise RuntimeError("backend down")

    assert run_once(db, boom) == 0
    conn = sqlite3.connect(db)
    assert [o["id"] for o in pending_orders(conn)] == [order_id]
    conn.close()


@pytest.mark.parametrize("error_text", [
    "Backend-Fehler: ReadTimeout",
    "Backend-Fehler: CLI exit 1",
])
def test_compat_failed_answer_keeps_the_order_pending(db, error_text):
    order_id = _order(db, "bach", "noch einmal versuchen")

    def process(_text, _chat_id):
        return FailedAnswer(error_text)

    assert compat_run_once(db, process) == 0
    conn = sqlite3.connect(db)
    assert [o["id"] for o in compat_pending_orders(conn)] == [order_id]
    order = compat_pending_orders(conn)[0]
    assert compat_file_reply(conn, order, process("", "")) == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM messages WHERE parent_id = ?", (order_id,)
    ).fetchone()[0] == 0
    conn.close()


def test_compat_successful_legacy_prefix_is_filed(db):
    """The text-only worker honours an explicit successful collision status."""
    order_id = _order(db, "bach", "CLI-Ausgabe abholen")

    def process(_text, _chat_id):
        return SuccessfulAnswer("Backend-Fehler: legitime CLI-Ausgabe")

    assert compat_run_once(db, process) == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT direction, body, parent_id FROM messages WHERE parent_id = ?",
        (order_id,),
    ).fetchone()
    conn.close()
    assert row == ("inbox", "Backend-Fehler: legitime CLI-Ausgabe", order_id)
