# SPDX-License-Identifier: MIT
"""BACH adapter contract for assistant-core notification wave 3."""

from __future__ import annotations

import inspect
import re
import sqlite3
from pathlib import Path

from assistant_core import NotificationService
from hub import notify as notify_module
from hub.notify import NotifyHandler
from hub.notify_storage import BachNotifyStorage


DDL = """
CREATE TABLE connections (
    name TEXT PRIMARY KEY,
    type TEXT,
    category TEXT,
    endpoint TEXT,
    auth_type TEXT DEFAULT 'none',
    auth_config TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT,
    last_used TEXT,
    success_count INTEGER DEFAULT 0
);
CREATE TABLE connector_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_name TEXT,
    direction TEXT,
    sender TEXT,
    recipient TEXT,
    content TEXT,
    processed INTEGER DEFAULT 0,
    created_at TEXT
);
"""


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(DDL)
        conn.execute(
            "INSERT INTO connections "
            "(name, type, category, endpoint, is_active, created_at, updated_at, success_count) "
            "VALUES ('notify_webhook', 'webhook', 'notification', 'https://example.test', 1, 'old', 'old', 0)"
        )
    return db_path


def test_handler_constructs_the_neutral_service(tmp_path):
    db_path = make_db(tmp_path)
    handler = NotifyHandler(tmp_path)
    handler.db_path = db_path
    service = handler._service()
    assert isinstance(service, NotificationService)
    assert isinstance(service.storage, BachNotifyStorage)


def test_storage_marks_only_the_exact_queued_message(tmp_path):
    db_path = make_db(tmp_path)
    storage = BachNotifyStorage(db_path)
    first = storage.enqueue("notify_webhook", "same", "duplicate", "2026-09-09 07:30:00")
    second = storage.enqueue("notify_webhook", "same", "duplicate", "2026-09-09 07:30:01")

    storage.mark_sent(second, "notify_webhook", "2026-09-09 07:30:02")

    with sqlite3.connect(db_path) as conn:
        processed = conn.execute("SELECT id, processed FROM connector_messages ORDER BY id").fetchall()
        success_count = conn.execute(
            "SELECT success_count FROM connections WHERE name = 'notify_webhook'"
        ).fetchone()[0]
    assert processed == [(first, 0), (second, 1)]
    assert success_count == 1


def test_notify_handler_contains_no_storage_or_network_implementation():
    source = inspect.getsource(notify_module)
    for forbidden in (
        "import sqlite3",
        "urllib.request",
        "import smtplib",
        "INSERT INTO",
        "UPDATE connections",
        "connector.send_message",
        "connector.disconnect",
    ):
        assert forbidden not in source
    assert "return send_telegram(" in source


def test_existing_press_and_newspaper_calls_need_no_signature_change():
    root = Path(__file__).parents[1]
    press = (root / "hub" / "press.py").read_text(encoding="utf-8")
    newspaper = (root / "hub" / "_services" / "newspaper" / "newspaper_generator.py").read_text(encoding="utf-8")
    assert re.search(r'notifier\._send\(\s*\["email",[\s\S]*?\],\s*dry_run\s*\)', press)
    assert re.search(r'notifier\._send\(\s*\["telegram",\s*msg\],\s*False\s*\)', newspaper)
