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
    # Schema spiegelt das produktive DB-Schema (Live-DDL, Task #1207):
    # session_snapshots inkl. aller Spalten, memory_working inkl. type/priority/
    # is_active/created_by_session_id, tasks inkl. source/updated_at.
    conn.execute("""
        CREATE TABLE session_snapshots (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            snapshot_type TEXT NOT NULL,
            snapshot_data JSON,
            working_memory JSON,
            open_tasks JSON,
            active_files JSON,
            token_usage INTEGER,
            context_hash TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, name TEXT,
            UNIQUE(session_id, snapshot_type, created_at)
        )
    """)
    conn.execute("""
        CREATE TABLE system_config (
            key TEXT PRIMARY KEY, value TEXT, category TEXT, description TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            priority TEXT DEFAULT 'P3',
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT,
            source TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE memory_working (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('scratchpad', 'context', 'loop', 'note')),
            content TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            created_by_session_id TEXT
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


class TestSnapshotRestore:
    """Echter Restore (Task #1207): Working Memory & Tasks zurueckschreiben."""

    def test_load_restores_working_memory(self, snap_env):
        handler, _, db_path = snap_env
        conn = sqlite3.connect(str(db_path))
        for text in ("Notiz A", "Notiz B"):
            conn.execute(
                "INSERT INTO memory_working (type, content, priority, is_active) "
                "VALUES ('note', ?, 3, 1)", (text,))
        conn.commit(); conn.close()

        handler.handle("create", ["with-memory"])

        # Session-Verlust simulieren: alle aktiven Eintraege deaktivieren
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE memory_working SET is_active = 0")
        conn.commit(); conn.close()

        ok, msg = handler.handle("load", [])
        assert ok is True
        assert "RESTORIERT" in msg
        assert "2 zurueckgeschrieben" in msg

        conn = sqlite3.connect(str(db_path))
        active = conn.execute(
            "SELECT COUNT(*) FROM memory_working WHERE is_active = 1 "
            "AND content IN ('Notiz A', 'Notiz B')").fetchone()[0]
        conn.close()
        assert active == 2

    def test_load_idempotent_no_duplicates(self, snap_env):
        handler, _, db_path = snap_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_working (type, content, priority, is_active) "
            "VALUES ('note', 'Dauernotiz', 3, 1)")
        conn.commit(); conn.close()

        handler.handle("create", ["stable"])

        handler.handle("load", [])
        ok, msg = handler.handle("load", [])

        assert ok is True
        assert "uebersprungen" in msg
        assert "0 zurueckgeschrieben" in msg

        conn = sqlite3.connect(str(db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_working WHERE content = 'Dauernotiz' "
            "AND is_active = 1").fetchone()[0]
        conn.close()
        assert count == 1

    def test_load_reactivates_completed_task(self, snap_env):
        handler, _, db_path = snap_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO tasks (title, status, priority) "
            "VALUES ('Wichtig offen', 'pending', 'P2')")
        conn.commit(); conn.close()

        handler.handle("create", ["before-done"])

        # Task nach dem Snapshot abschliessen
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE tasks SET status = 'done' WHERE title = 'Wichtig offen'")
        conn.commit(); conn.close()

        ok, msg = handler.handle("load", [])
        assert ok is True
        assert "1 reaktiviert" in msg

        conn = sqlite3.connect(str(db_path))
        status = conn.execute(
            "SELECT status FROM tasks WHERE title = 'Wichtig offen'").fetchone()[0]
        conn.close()
        assert status == "pending"

    def test_load_creates_missing_task(self, snap_env):
        handler, _, db_path = snap_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO tasks (title, status) VALUES ('Verschollener Task', 'pending')")
        conn.commit(); conn.close()

        handler.handle("create", ["before-delete"])

        # Task nach dem Snapshot gaenzlich loeschen
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM tasks WHERE title = 'Verschollener Task'")
        conn.commit(); conn.close()

        ok, msg = handler.handle("load", [])
        assert ok is True
        assert "1 neu angelegt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status, source FROM tasks WHERE title = 'Verschollener Task'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "pending"
        assert row[1] == "snapshot-restore"

    def test_load_display_mode_no_write(self, snap_env):
        handler, _, db_path = snap_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_working (type, content, priority, is_active) "
            "VALUES ('note', 'Nur-Anzeige', 3, 1)")
        conn.execute(
            "INSERT INTO tasks (title, status) VALUES ('Anzeige-Task', 'pending')")
        conn.commit(); conn.close()

        handler.handle("create", ["display-snap"])

        # Nach dem Snapshot veraendern ...
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE memory_working SET is_active = 0")
        conn.execute("UPDATE tasks SET status = 'done' WHERE title = 'Anzeige-Task'")
        snap_id = conn.execute(
            "SELECT id FROM session_snapshots WHERE name = 'display-snap'"
        ).fetchone()[0]
        conn.commit(); conn.close()

        ok, msg = handler.handle("load", [str(snap_id), "display"])
        assert ok is True
        assert "Display-Modus" in msg

        # ... darf display NICHT zurueckschreiben
        conn = sqlite3.connect(str(db_path))
        active = conn.execute(
            "SELECT COUNT(*) FROM memory_working WHERE is_active = 1").fetchone()[0]
        status = conn.execute(
            "SELECT status FROM tasks WHERE title = 'Anzeige-Task'").fetchone()[0]
        conn.close()
        assert active == 0
        assert status == "done"

    def test_load_skips_already_open_tasks(self, snap_env):
        handler, _, db_path = snap_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO tasks (title, status) VALUES ('Bleibt offen', 'pending')")
        conn.commit(); conn.close()

        handler.handle("create", ["still-open"])

        ok, msg = handler.handle("load", [])
        assert ok is True
        assert "bereits offen" in msg

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE source = 'snapshot-restore'"
        ).fetchone()[0]
        conn.close()
        assert rows == 0  # kein Duplikat angelegt
