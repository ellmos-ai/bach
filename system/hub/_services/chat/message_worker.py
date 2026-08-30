"""Consumer for order messages ("Auftragsnachrichten") in the BACH `messages` table.

The GUI and `bach msg` store a user order as
``messages(direction='outbox', sender='user', recipient=<agent>)`` -- but until
now nothing ever read those rows for the local chat runtime, so an order to
``ollama``/``buddha``/``bach`` sat there forever (FABLE-SOL-PLAN 1.1.4, measured
2026-08-30 on the Mac Studio: order #939 unanswered since 2026-08-27).

This worker answers such orders through the same ``ChatRuntime.process`` the
Control API uses and files the reply as an *inbox* message whose ``parent_id``
points at the order. That link is the "answered" marker: no new table, no new
status value, no second message store (plan item 1.2.4/1.2.5 spirit).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Callable, Iterable

log = logging.getLogger("bach.chat.messages")

DEFAULT_RECIPIENTS = ("ollama", "buddha", "bach")
POLL_SECONDS = 30

ProcessFn = Callable[[str, str], str]


def pending_orders(conn: sqlite3.Connection, recipients: Iterable[str] = DEFAULT_RECIPIENTS) -> list[dict]:
    """Outbox orders to ``recipients`` that have no inbox reply yet (oldest first)."""
    names = [r.lower() for r in recipients]
    marks = ",".join("?" * len(names))
    rows = conn.execute(
        f"""
        SELECT o.id, o.recipient, o.subject, o.body, o.thread_id
        FROM messages o
        WHERE o.direction = 'outbox'
          AND LOWER(o.recipient) IN ({marks})
          AND COALESCE(o.status, '') != 'deleted'
          AND COALESCE(o.body, '') != ''
          AND NOT EXISTS (
              SELECT 1 FROM messages r WHERE r.parent_id = o.id AND r.direction = 'inbox'
          )
        ORDER BY o.id
        """,
        names,
    ).fetchall()
    keys = ("id", "recipient", "subject", "body", "thread_id")
    return [dict(zip(keys, row)) for row in rows]


def file_reply(conn: sqlite3.Connection, order: dict, answer: str) -> int:
    """Store ``answer`` as the inbox reply to ``order``; returns the reply id."""
    subject = order.get("subject") or order["body"][:60]
    cur = conn.execute(
        """
        INSERT INTO messages (direction, sender, recipient, subject, body, parent_id, thread_id)
        VALUES ('inbox', ?, 'user', ?, ?, ?, ?)
        """,
        (order["recipient"], f"Re: {subject}", answer, order["id"], order.get("thread_id")),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def run_once(db_path: str, process: ProcessFn, recipients: Iterable[str] = DEFAULT_RECIPIENTS) -> int:
    """Answer every pending order once. Returns how many were answered.

    ``process(text, chat_id)`` is the synchronous runtime call; an exception
    leaves the order pending (it is retried on the next poll), an answer string
    -- including the runtime's own "Backend-Fehler: ..." text -- is filed.
    """
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        answered = 0
        for order in pending_orders(conn, recipients):
            try:
                answer = process(order["body"], f"msg-{order['id']}")
            except Exception as exc:  # noqa: BLE001 - keep polling, report once per round
                log.warning("Auftragsnachricht #%s nicht beantwortet: %s", order["id"], exc)
                continue
            file_reply(conn, order, answer)
            answered += 1
        return answered
    finally:
        conn.close()


def start_worker(
    db_path: str,
    process: ProcessFn,
    recipients: Iterable[str] = DEFAULT_RECIPIENTS,
    interval: float = POLL_SECONDS,
    stop: threading.Event | None = None,
) -> threading.Thread:
    """Poll ``db_path`` every ``interval`` seconds in a daemon thread."""
    stop = stop or threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                answered = run_once(db_path, process, recipients)
                if answered:
                    log.info("%d Auftragsnachricht(en) beantwortet", answered)
            except Exception as exc:  # noqa: BLE001 - a poll failure must not kill the bot
                log.warning("Message-Worker: %s", exc)
            stop.wait(interval)

    thread = threading.Thread(target=_loop, name="bach-message-worker", daemon=True)
    thread.start()
    return thread
