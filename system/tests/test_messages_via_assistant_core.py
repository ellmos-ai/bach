# -*- coding: utf-8 -*-
"""BACH message seam regression test.

The original contract assumed that ``assistant-core`` provides the message
domain (decision D-20260830-002). In practice the editable ``assistant-core``
checkout is frequently missing, so BACH must keep its seam and fall back to a
local implementation. This test verifies the seam works with or without
``assistant_core`` installed.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat import message_worker  # noqa: E402


def _make_message_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "direction TEXT, sender TEXT, recipient TEXT, subject TEXT, "
            "body TEXT, status TEXT DEFAULT 'unread', parent_id INTEGER, "
            "thread_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )


def test_gui_server_does_not_import_optional_cores():
    """gui/server.py must not hard-depend on missing editable packages."""
    src = (SYSTEM_ROOT / "gui" / "server.py").read_text(encoding="utf-8")
    assert "from assistant_core import" not in src
    assert "from accounts_core import" not in src


def test_message_worker_seam_exports_required_api():
    """BACH's import path stays stable; fallback provides the same contract."""
    assert callable(message_worker.pending_orders)
    assert callable(message_worker.file_reply)
    assert callable(message_worker.run_once)
    assert message_worker.DEFAULT_RECIPIENTS == ("ollama", "buddha", "bach")


def test_seam_keeps_bach_thread_name(tmp_path):
    db = tmp_path / "bach.db"
    _make_message_db(db)
    stop = threading.Event()
    thread = message_worker.start_worker(str(db), lambda text, chat_id: "ok", interval=0.05, stop=stop)
    try:
        assert thread.name == "bach-message-worker"
    finally:
        stop.set()
        thread.join(2.0)
    assert not thread.is_alive()


def test_message_worker_run_once_processes_pending_order(tmp_path):
    db = tmp_path / "bach.db"
    _make_message_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO messages (direction, sender, recipient, body, status) VALUES (?, ?, ?, ?, ?)",
            ("outbox", "user", "bach", "hello", "unread"),
        )
        conn.commit()

    processed = []

    def process(body: str, chat_id: str) -> str:
        processed.append((body, chat_id))
        return "ack"

    answered = message_worker.run_once(str(db), process, recipients=("bach",))
    assert answered == 1
    assert processed == [("hello", "msg-1")]

    with sqlite3.connect(db) as conn:
        reply = conn.execute(
            "SELECT direction, sender, parent_id, body FROM messages WHERE id = 2"
        ).fetchone()
        assert reply == ("inbox", "bach", 1, "ack")
