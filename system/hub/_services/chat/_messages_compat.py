# SPDX-License-Identifier: MIT
"""Lokale Fallback-Implementierung fuer ``assistant_core.messages``.

Bis assistant-core seine Nachrichten-Domain (Wave 2/3) ausliefert, stellt dieses
Modul eine minimal aber voll funktionsfaehige lokale Variante bereit. Sie
verwendet das gleiche ``messages``-Schema und die gleichen Signaturen wie
``assistant_core.messages``, damit ``hub._services.chat.message_worker`` ohne
Code-Aenderungen auf beide Implementierungen zurueckgreifen kann.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterable
from typing import Any

log = logging.getLogger("hub._services.chat._messages_compat")

DEFAULT_RECIPIENTS = ("ollama", "buddha", "bach")
POLL_SECONDS = 30.0
ProcessFn = Callable[[str, str], str]


def pending_orders(
    conn: sqlite3.Connection,
    recipients: Iterable[str] = DEFAULT_RECIPIENTS,
) -> list[dict[str, Any]]:
    """Outbox-Auftraege an ``recipients``, die noch keine Inbox-Antwort haben."""
    names = [r.lower() for r in recipients]
    if not names:
        return []
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
    return [dict(zip(keys, tuple(row))) for row in rows]


def file_reply(conn: sqlite3.Connection, order: dict, answer: str) -> int:
    """Speichert ``answer`` als Inbox-Antwort zu ``order``; gibt die Reply-ID zurueck."""
    subject = order.get("subject") or order.get("body", "")[:60]
    cur = conn.execute(
        """
        INSERT INTO messages (direction, sender, recipient, subject, body, parent_id, thread_id)
        VALUES ('inbox', ?, 'user', ?, ?, ?, ?)
        """,
        (
            order.get("recipient", "bach"),
            f"Re: {subject}",
            answer,
            order["id"],
            order.get("thread_id"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def run_once(
    db_path: str,
    process: ProcessFn,
    recipients: Iterable[str] = DEFAULT_RECIPIENTS,
) -> int:
    """Beantwortet alle ausstehenden Auftraege einmal; gibt Anzahl zurueck."""
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        answered = 0
        for order in pending_orders(conn, recipients):
            try:
                answer = process(order.get("body", ""), f"msg-{order['id']}")
            except Exception as exc:  # noqa: BLE001 - polling darf nicht sterben
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
    name: str = "message-worker",
) -> threading.Thread:
    """Startet einen Daemon-Thread, der ``run_once`` im Intervall aufruft."""
    stop_event = stop or threading.Event()

    def _loop() -> None:
        while not stop_event.is_set():
            try:
                answered = run_once(db_path, process, recipients)
                if answered:
                    log.info("%d Auftragsnachricht(en) beantwortet", answered)
            except Exception as exc:  # noqa: BLE001
                log.warning("Order-Worker: %s", exc)
            stop_event.wait(interval)

    thread = threading.Thread(target=_loop, name=name, daemon=True)
    thread.start()
    return thread
