# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SnapshotHandler."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.snapshot import SnapshotHandler


@pytest.fixture
def snap_env(tmp_path, monkeypatch):
    """SnapshotHandler with temporary DB."""
    base = tmp_path / "bach"
    system = base / "system"
    data = system / "data"
    data.mkdir(parents=True)
    db_path = data / "bach.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE session_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, snapshot_type TEXT, name TEXT,
            snapshot_data TEXT, created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE system_config (
            key TEXT PRIMARY KEY, value TEXT, category TEXT, description TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, status TEXT, priority TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE memory_working (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT, created_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO system_config (key, value) VALUES (?, ?)",
        ("current_session", "sess-001"),
    )
    conn.commit()
    conn.close()

    handler = SnapshotHandler(base)
    monkeypatch.setattr(handler, "db_path", db_path)
    return handler, base, db_path


class TestSnapshotBasic:
    def test_profile_name(self, snap_env):
        handler, _, _ = snap_env
        assert handler.profile_name == "snapshot"

    def test_operations(self, snap_env):
        handler, _, _ = snap_env
        ops = handler.get_operations()
        assert "create" in ops
        assert "load" in ops
        assert "list" in ops
        assert "delete" in ops


class TestSnapshotCreate:
    def test_create_default_name(self, snap_env):
        handler, _, db_path = snap_env
        ok, msg = handler.handle("create", [])
        assert ok is True
        assert "snapshot_" in msg

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM session_snapshots").fetchone()[0]
        conn.close()
        assert count == 1

    def test_create_custom_name(self, snap_env):
        handler, _, db_path = snap_env
        ok, msg = handler.handle("create", ["my-checkpoint"])
        assert ok is True
        assert "my-checkpoint" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT name FROM session_snapshots").fetchone()
        conn.close()
        assert row[0] == "my-checkpoint"

    def test_create_captures_session_id(self, snap_env):
        handler, _, db_path = snap_env
        handler.handle("create", ["test"])

        conn = sqlite3.connect(str(db_path))
        data = conn.execute("SELECT snapshot_data FROM session_snapshots").fetchone()[0]
        conn.close()
        parsed = json.loads(data)
        assert parsed["session_id"] == "sess-001"

    def test_create_captures_open_tasks(self, snap_env):
        handler, _, db_path = snap_env
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO tasks (title, status) VALUES (?, ?)", ("Fix bug", "pending"))
        conn.execute("INSERT INTO tasks (title, status) VALUES (?, ?)", ("Done thing", "done"))
        conn.commit()
        conn.close()

        handler.handle("create", ["with-tasks"])
        conn = sqlite3.connect(str(db_path))
        data = conn.execute("SELECT snapshot_data FROM session_snapshots").fetchone()[0]
        conn.close()
        parsed = json.loads(data)
        assert len(parsed["open_tasks"]) == 1
        assert parsed["open_tasks"][0]["title"] == "Fix bug"

    def test_dry_run(self, snap_env):
        handler, _, db_path = snap_env
        ok, msg = handler.handle("create", ["dry"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM session_snapshots").fetchone()[0]
        conn.close()
        assert count == 0


class TestSnapshotLoad:
    def test_load_empty(self, snap_env):
        handler, _, _ = snap_env
        ok, msg = handler.handle("load", [])
        assert ok is False
        assert "Kein Snapshot" in msg

    def test_load_latest(self, snap_env):
        handler, _, db_path = snap_env
        import time
        handler.handle("create", ["first"])
        time.sleep(0.05)
        handler.handle("create", ["second"])

        ok, msg = handler.handle("load", [])
        assert ok is True
        assert "second" in msg

    def test_load_by_id(self, snap_env):
        handler, _, db_path = snap_env
        handler.handle("create", ["target"])

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT id FROM session_snapshots WHERE name='target'").fetchone()
        conn.close()

        ok, msg = handler.handle("load", [str(row[0])])
        assert ok is True
        assert "target" in msg

    def test_load_dry_run(self, snap_env):
        handler, _, _ = snap_env
        ok, msg = handler.handle("load", [], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg


class TestSnapshotList:
    def test_list_empty(self, snap_env):
        handler, _, _ = snap_env
        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "Keine Snapshots" in msg

    def test_list_shows_entries(self, snap_env):
        handler, _, _ = snap_env
        handler.handle("create", ["alpha"])
        handler.handle("create", ["beta"])

        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "alpha" in msg
        assert "beta" in msg


class TestSnapshotDelete:
    def test_delete_existing(self, snap_env):
        handler, _, db_path = snap_env
        handler.handle("create", ["doomed"])

        conn = sqlite3.connect(str(db_path))
        snap_id = conn.execute("SELECT id FROM session_snapshots").fetchone()[0]
        conn.close()

        ok, msg = handler.handle("delete", [str(snap_id)])
        assert ok is True
        assert "geloescht" in msg

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM session_snapshots").fetchone()[0]
        conn.close()
        assert count == 0

    def test_delete_nonexistent(self, snap_env):
        handler, _, _ = snap_env
        ok, msg = handler.handle("delete", ["999"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_delete_dry_run(self, snap_env):
        handler, _, db_path = snap_env
        handler.handle("create", ["keep"])

        ok, msg = handler.handle("delete", ["1"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM session_snapshots").fetchone()[0]
        conn.close()
        assert count == 1
