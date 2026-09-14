# SPDX-License-Identifier: MIT
"""Regressionstests fuer die lokale Notify-Fallback-Implementierung."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hub._notify_dispatcher import CHANNELS
from hub._notify_service import NotificationService, SendResult
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


@pytest.fixture
def storage(tmp_path: Path) -> BachNotifyStorage:
    db_path = tmp_path / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(DDL)
    return BachNotifyStorage(db_path)


def test_channels_set_contains_expected_channels():
    assert CHANNELS == {"telegram", "discord", "slack", "webhook", "email"}


def test_setup_creates_channel_config(storage: BachNotifyStorage) -> None:
    service = NotificationService(storage)
    cfg = service.setup("webhook", endpoint="https://example.test/hook")
    assert cfg is not None
    assert cfg.channel == "webhook"
    assert cfg.endpoint == "https://example.test/hook"
    assert cfg.is_active is True


def test_setup_unknown_channel_raises(storage: BachNotifyStorage) -> None:
    service = NotificationService(storage)
    with pytest.raises(ValueError, match="Unknown channel"):
        service.setup("sms")


def test_send_unconfigured_channel_returns_unconfigured(storage: BachNotifyStorage) -> None:
    service = NotificationService(storage)
    result = service.send("webhook", "Hallo")
    assert isinstance(result, SendResult)
    assert result.status == "unconfigured"


def test_send_disabled_channel_returns_disabled(storage: BachNotifyStorage) -> None:
    db_path = Path(storage.db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) VALUES (?, ?, ?, ?, ?)",
            ("notify_webhook", "webhook", "notification", "https://example.test", 0),
        )
    service = NotificationService(storage)
    result = service.send("webhook", "Hallo")
    assert result.status == "disabled"


def test_send_dry_run(storage: BachNotifyStorage) -> None:
    db_path = Path(storage.db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, is_active) VALUES (?, ?, ?, ?, ?)",
            ("notify_webhook", "webhook", "notification", "https://example.test", 1),
        )
    service = NotificationService(storage)
    result = service.send("webhook", "Hallo", dry_run=True)
    assert result.status == "dry-run"


def test_list_channels_and_history(storage: BachNotifyStorage) -> None:
    service = NotificationService(storage)
    service.setup("slack", endpoint="https://hooks.slack.com/test")
    channels = service.list_channels()
    assert len(channels) == 1
    assert channels[0].channel == "slack"

    history = service.history(limit=10)
    assert history == []


def test_tag_text_uses_sender_tag(storage: BachNotifyStorage) -> None:
    db_path = Path(storage.db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO connections (name, type, category, endpoint, auth_config) VALUES (?, ?, ?, ?, ?)",
            ("notify_webhook", "webhook", "notification", "", '{"sender_tag": "BACH"}'),
        )
    from hub._notify_dispatcher import tag_text

    assert tag_text("Hello", "webhook", storage) == "[BACH] Hello"
