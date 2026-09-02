# -*- coding: utf-8 -*-
"""Wave 1 of the BACH-GUI module cut (D-20260830-002): the message domain lives in
``assistant-core``; BACH keeps its import seam and no raw ``messages`` SQL in the GUI."""
from __future__ import annotations

import re
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

import assistant_core  # noqa: E402
from hub._services.chat import message_worker  # noqa: E402


def test_gui_server_has_no_raw_messages_sql():
    """Acceptance criterion 1: the /api/messages endpoints go through MessageStore."""
    src = (SYSTEM_ROOT / "gui" / "server.py").read_text(encoding="utf-8")
    hits = re.findall(r"(?i)(?:FROM|INTO|UPDATE)\s+messages\b", src)
    assert hits == [], hits
    assert "_messages().list(" in src and "MessageStore" in src


def test_message_worker_seam_reexports_assistant_core():
    """BACH's import path stays stable; the implementation is the module's."""
    assert message_worker.pending_orders is assistant_core.pending_orders
    assert message_worker.file_reply is assistant_core.file_reply
    assert message_worker.run_once is assistant_core.run_once
    assert message_worker.DEFAULT_RECIPIENTS == ("ollama", "buddha", "bach")


def test_seam_keeps_bach_thread_name(tmp_path):
    import sqlite3
    import threading

    db = tmp_path / "bach.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT, sender TEXT, "
                     "recipient TEXT, subject TEXT, body TEXT, status TEXT DEFAULT 'unread', parent_id INTEGER, "
                     "thread_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    stop = threading.Event()
    thread = message_worker.start_worker(str(db), lambda text, chat_id: "ok", interval=0.05, stop=stop)
    try:
        assert thread.name == "bach-message-worker"
    finally:
        stop.set()
        thread.join(2.0)
    assert not thread.is_alive()
