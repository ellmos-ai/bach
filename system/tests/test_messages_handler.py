# -*- coding: utf-8 -*-
"""Tests for MessagesHandler (hub/messages.py)."""

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hub.messages import MessagesHandler


def _create_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            sender TEXT,
            recipient TEXT,
            subject TEXT,
            body TEXT,
            status TEXT DEFAULT 'unread',
            created_at TEXT,
            read_at TEXT,
            archived_at TEXT
        );
        CREATE TABLE IF NOT EXISTS partner_presence (
            partner_name TEXT PRIMARY KEY,
            status TEXT DEFAULT 'offline',
            clocked_in TEXT,
            clocked_out TEXT
        );
    """)
    conn.commit()


@pytest.fixture
def msg_env(tmp_path):
    base = tmp_path / "bach" / "system"
    (base / "data").mkdir(parents=True)
    (base / "hub").mkdir()

    db_path = base / "data" / "bach.db"
    conn = sqlite3.connect(str(db_path))
    _create_schema(conn)
    conn.close()

    h = MessagesHandler(base)
    h.bach_db = db_path
    return h, base, db_path


def _add_message(db_path, sender="user", recipient="claude", body="Hello",
                  direction="outbox", status="read", subject=None):
    conn = sqlite3.connect(str(db_path))
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO messages (direction, sender, recipient, subject, body, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (direction, sender, recipient, subject, body, status, now))
    conn.commit()
    mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return mid


def _add_partner(db_path, name="claude", status="online"):
    conn = sqlite3.connect(str(db_path))
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO partner_presence (partner_name, status, clocked_in)
        VALUES (?, ?, ?)
    """, (name, status, now))
    conn.commit()
    conn.close()


class TestInit:
    def test_profile_name(self, msg_env):
        h, _, _ = msg_env
        assert h.profile_name == "msg"

    def test_operations(self, msg_env):
        h, _, _ = msg_env
        ops = h.get_operations()
        assert "list" in ops
        assert "send" in ops
        assert "read" in ops
        assert "unread" in ops
        assert "inbox" in ops
        assert "outbox" in ops
        assert "ping" in ops
        assert "count" in ops
        assert "delete" in ops
        assert "archive" in ops

    def test_target_file(self, msg_env):
        h, _, db_path = msg_env
        assert h.target_file == db_path


class TestHandle:
    def test_unknown_operation(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("nope", [])
        assert ok is True
        assert "HILFE" in msg

    def test_send_no_args(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("send", [])
        assert ok is False
        assert "Usage" in msg

    def test_send_one_arg(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("send", ["claude"])
        assert ok is False

    def test_read_no_args(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("read", [])
        assert ok is False

    def test_delete_no_args(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("delete", [])
        assert ok is False

    def test_archive_no_args(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("archive", [])
        assert ok is False


class TestList:
    def test_list_empty(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("list", [])
        assert ok is True
        assert "Keine Nachrichten" in msg

    def test_list_with_messages(self, msg_env):
        h, _, db_path = msg_env
        _add_message(db_path, body="Test msg 1")
        _add_message(db_path, body="Test msg 2")

        ok, msg = h.handle("list", [])
        assert ok is True
        assert "NACHRICHTEN (2)" in msg

    def test_inbox_filter(self, msg_env):
        h, _, db_path = msg_env
        _add_message(db_path, direction="inbox", sender="claude", recipient="user", body="Hi")
        _add_message(db_path, direction="outbox", sender="user", recipient="claude", body="Reply")

        ok, msg = h.handle("inbox", [])
        assert ok is True
        assert "NACHRICHTEN (1)" in msg

    def test_outbox_filter(self, msg_env):
        h, _, db_path = msg_env
        _add_message(db_path, direction="inbox", sender="claude", body="Hi")
        _add_message(db_path, direction="outbox", sender="user", body="Reply")

        ok, msg = h.handle("outbox", [])
        assert ok is True
        assert "NACHRICHTEN (1)" in msg

    def test_list_with_limit(self, msg_env):
        h, _, db_path = msg_env
        for i in range(5):
            _add_message(db_path, body=f"Msg {i}")

        ok, msg = h.handle("list", ["--limit", "2"])
        assert ok is True
        assert "NACHRICHTEN (2)" in msg


class TestUnread:
    def test_no_unread(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("unread", [])
        assert ok is True
        assert "Keine ungelesenen" in msg

    def test_with_unread(self, msg_env):
        h, _, db_path = msg_env
        _add_message(db_path, status="unread", body="Neue Nachricht")

        ok, msg = h.handle("unread", [])
        assert ok is True
        assert "UNGELESEN (1)" in msg


class TestSend:
    def test_send_dry_run(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("send", ["claude", "Testnachricht"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

    def test_send_message(self, msg_env):
        h, _, db_path = msg_env
        ok, msg = h.handle("send", ["claude", "Hallo", "Welt"])
        assert ok is True
        assert "gesendet" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row["recipient"] == "claude"
        assert row["body"] == "Hallo Welt"
        assert row["direction"] == "outbox"

    def test_send_from_partner(self, msg_env):
        h, _, db_path = msg_env
        ok, msg = h.handle("send", ["user", "Hi", "--from", "gemini"])
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row["sender"] == "gemini"
        assert row["direction"] == "inbox"
        assert row["status"] == "unread"

    def test_send_auto_detects_partner(self, msg_env):
        h, _, db_path = msg_env
        _add_partner(db_path, "claude", "online")

        ok, msg = h.handle("send", ["user", "Auto-detected sender"])
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row["sender"] == "claude"


class TestRead:
    def test_read_invalid_id(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("read", ["abc"])
        assert ok is False
        assert "Ungueltige ID" in msg

    def test_read_not_found(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("read", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_read_message(self, msg_env):
        h, _, db_path = msg_env
        mid = _add_message(db_path, direction="inbox", sender="claude",
                            recipient="user", body="Hallo User!", status="unread")

        ok, msg = h.handle("read", [str(mid)])
        assert ok is True
        assert "Hallo User!" in msg
        assert "claude" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM messages WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row["status"] == "read"

    def test_read_dry_run_keeps_unread(self, msg_env):
        h, _, db_path = msg_env
        mid = _add_message(db_path, status="unread", body="Unread msg")

        ok, msg = h.handle("read", [str(mid)], dry_run=True)
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM messages WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row["status"] == "unread"


class TestCount:
    def test_count_empty(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("count", [])
        assert ok is True
        assert "Gesamt:    0" in msg

    def test_count_with_messages(self, msg_env):
        h, _, db_path = msg_env
        _add_message(db_path, direction="inbox", status="unread")
        _add_message(db_path, direction="outbox", status="read")
        _add_message(db_path, direction="inbox", status="read")

        ok, msg = h.handle("count", [])
        assert ok is True
        assert "Gesamt:    3" in msg
        assert "Inbox:     2" in msg
        assert "Outbox:    1" in msg
        assert "Ungelesen: 1" in msg


class TestDelete:
    def test_delete_message(self, msg_env):
        h, _, db_path = msg_env
        mid = _add_message(db_path, body="To be deleted")

        ok, msg = h.handle("delete", [str(mid)])
        assert ok is True
        assert "Geloescht" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM messages WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row is None

    def test_delete_not_found(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("delete", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_delete_invalid_id(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("delete", ["abc"])
        assert ok is False
        assert "Ungueltige ID" in msg

    def test_delete_dry_run(self, msg_env):
        h, _, db_path = msg_env
        mid = _add_message(db_path, body="Keep this")

        ok, msg = h.handle("delete", [str(mid), "--dry-run"])
        assert ok is True
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM messages WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row is not None

    def test_delete_multiple(self, msg_env):
        h, _, db_path = msg_env
        m1 = _add_message(db_path, body="Del 1")
        m2 = _add_message(db_path, body="Del 2")

        ok, msg = h.handle("delete", [str(m1), str(m2)])
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        assert count == 0


class TestArchive:
    def test_archive_message(self, msg_env):
        h, _, db_path = msg_env
        mid = _add_message(db_path, status="read", body="To archive")

        ok, msg = h.handle("archive", [str(mid)])
        assert ok is True
        assert "Archiviert" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, archived_at FROM messages WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row["status"] == "archived"
        assert row["archived_at"] is not None

    def test_archive_already_archived(self, msg_env):
        h, _, db_path = msg_env
        mid = _add_message(db_path, status="archived", body="Already archived")

        ok, msg = h.handle("archive", [str(mid)])
        assert ok is False
        assert "bereits archiviert" in msg

    def test_archive_not_found(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("archive", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_archive_dry_run(self, msg_env):
        h, _, db_path = msg_env
        mid = _add_message(db_path, status="read", body="Keep")

        ok, msg = h.handle("archive", [str(mid), "--dry-run"])
        assert ok is True
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM messages WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row["status"] == "read"


class TestPing:
    def test_ping_no_partner(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("ping", [])
        assert ok is False
        assert "Kein Partner" in msg

    def test_ping_with_explicit_partner(self, msg_env):
        h, _, db_path = msg_env
        _add_message(db_path, direction="inbox", sender="user", recipient="claude",
                      body="Hey Claude", status="unread")

        ok, msg = h.handle("ping", ["--from", "claude"])
        assert ok is True
        assert "Hey Claude" in msg

    def test_ping_no_messages(self, msg_env):
        h, _, db_path = msg_env
        ok, msg = h.handle("ping", ["--from", "claude"])
        assert ok is True
        assert "Keine neuen Nachrichten" in msg


class TestActivePartner:
    def test_no_partner(self, msg_env):
        h, _, _ = msg_env
        assert h._get_active_partner() is None

    def test_partner_online(self, msg_env):
        h, _, db_path = msg_env
        _add_partner(db_path, "claude", "online")

        result = h._get_active_partner()
        assert result == "claude"

    def test_partner_offline(self, msg_env):
        h, _, db_path = msg_env
        _add_partner(db_path, "claude", "offline")

        result = h._get_active_partner()
        assert result is None


class TestHelp:
    def test_help_content(self, msg_env):
        h, _, _ = msg_env
        ok, msg = h.handle("help", [])
        assert ok is True
        assert "MESSAGES HILFE" in msg
        assert "send" in msg
        assert "read" in msg
