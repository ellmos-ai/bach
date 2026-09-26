# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Focused tests for the read-only session-checkpoint payload collector.

These tests use ONLY temporary SQLite databases. They never open or modify the
canonical live BACH database.

Covered:
- six-field / current-value equivalence with stored snapshot_data JSON
- exact limits and ordering
- missing optional legacy tables (files_truth, monitor_tokens) compatibility
- read-only / no-write behaviour
- a stable, deterministic timestamp seam
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.snapshot_payload import (
    _open_readonly,
    collect_snapshot_payload,
)

EXPECTED_FIELDS = {
    "session_id",
    "open_tasks",
    "recent_memory",
    "active_files",
    "token_usage",
    "created_at",
}


def _make_db(path, *, with_optional=True, session="sess-eq"):
    """Create a temporary BACH-like SQLite DB with deterministic data."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE system_config "
        "(key TEXT PRIMARY KEY, value TEXT, category TEXT, description TEXT)"
    )
    conn.execute(
        "CREATE TABLE tasks "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "title TEXT, status TEXT, priority TEXT)"
    )
    conn.execute(
        "CREATE TABLE memory_working "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content TEXT, created_at TEXT, is_active INTEGER DEFAULT 1)"
    )
    conn.execute(
        "CREATE TABLE session_snapshots "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT, snapshot_type TEXT, name TEXT, "
        "snapshot_data TEXT, created_at TEXT)"
    )
    if with_optional:
        conn.execute(
            "CREATE TABLE files_truth "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "path TEXT, file_exists INTEGER DEFAULT 1, modified_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE monitor_tokens "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, tokens_total INTEGER)"
        )

    if session is not None:
        conn.execute(
            "INSERT INTO system_config (key, value) VALUES (?, ?)",
            ("current_session", session),
        )

    # 12 pending tasks -> only 10 should be collected.
    for i in range(1, 13):
        conn.execute(
            "INSERT INTO tasks (title, status) VALUES (?, ?)",
            ("task-%02d" % i, "pending"),
        )
    # 1 completed task -> must be excluded by the status filter.
    conn.execute(
        "INSERT INTO tasks (title, status) VALUES (?, ?)",
        ("done-task", "done"),
    )

    # 7 active memory entries, distinct created_at (mem-07 newest).
    for i in range(1, 8):
        conn.execute(
            "INSERT INTO memory_working (content, created_at, is_active) "
            "VALUES (?, ?, 1)",
            ("mem-%02d" % i, "2026-09-21T10:00:0%d" % i),
        )
    # 1 inactive memory entry -> must be excluded.
    conn.execute(
        "INSERT INTO memory_working (content, created_at, is_active) "
        "VALUES (?, ?, 0)",
        ("mem-inactive", "2026-09-21T11:00:00"),
    )

    if with_optional:
        # 12 existing files, distinct modified_at (/f/12 newest).
        for i in range(1, 13):
            conn.execute(
                "INSERT INTO files_truth (path, file_exists, modified_at) "
                "VALUES (?, 1, ?)",
                ("/f/%02d" % i, "2026-09-21T09:%02d:00" % i),
            )
        # 1 non-existing file -> excluded by file_exists filter.
        conn.execute(
            "INSERT INTO files_truth (path, file_exists, modified_at) "
            "VALUES (?, 0, ?)",
            ("/f/gone", "2026-09-21T12:00:00"),
        )
        # monitor_tokens; newest by id = 500.
        for i in range(1, 6):
            conn.execute(
                "INSERT INTO monitor_tokens (tokens_total) VALUES (?)",
                (i * 100,),
            )

    conn.commit()
    conn.close()


class TestSixFieldEquivalence:
    def test_exactly_six_fields(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        payload = collect_snapshot_payload(db, created_at="2026-09-21T00:00:00")

        assert set(payload.keys()) == EXPECTED_FIELDS
        assert len(payload) == 6

    def test_current_values_match_handler_snapshot_data(self, tmp_path):
        """Collector output must match a stored snapshot_data JSON."""
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        conn = sqlite3.connect(str(db))
        stored = {
            "session_id": "sess-eq",
            "open_tasks": [
                {"id": i, "title": "task-%02d" % i}
                for i in range(1, 11)
            ],
            "recent_memory": ["mem-07", "mem-06", "mem-05", "mem-04", "mem-03"],
            "active_files": [
                "/f/%02d" % i for i in range(12, 2, -1)
            ],
            "token_usage": 500,
            "created_at": "2026-09-21T00:00:00",
        }
        conn.execute(
            "INSERT INTO session_snapshots "
            "(session_id, snapshot_type, name, snapshot_data, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "sess-eq", "checkpoint", "equiv",
                json.dumps(stored), stored["created_at"],
            ),
        )
        conn.commit()
        conn.close()

        payload = collect_snapshot_payload(db, created_at="2026-09-21T00:00:00")

        assert payload["session_id"] == stored["session_id"] == "sess-eq"
        assert payload["open_tasks"] == stored["open_tasks"]
        assert payload["recent_memory"] == stored["recent_memory"]
        assert payload["active_files"] == stored["active_files"]
        assert payload["token_usage"] == stored["token_usage"] == 500
        assert payload["created_at"] == stored["created_at"]
        assert set(payload.keys()) == set(stored.keys()) == EXPECTED_FIELDS
class TestLimitsAndOrder:
    def test_open_tasks_limit_and_shape(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        payload = collect_snapshot_payload(db)

        tasks = payload["open_tasks"]
        assert len(tasks) == 10  # 12 pending, capped at 10
        # Only pending tasks, none of the completed one.
        assert all(t["title"].startswith("task-") for t in tasks)
        assert all(set(t.keys()) == {"id", "title"} for t in tasks)
        assert tasks[0] == {"id": 1, "title": "task-01"}
        assert tasks[-1] == {"id": 10, "title": "task-10"}
        assert "done-task" not in [t["title"] for t in tasks]

    def test_recent_memory_limit_and_order(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        payload = collect_snapshot_payload(db)

        memory = payload["recent_memory"]
        assert len(memory) == 5  # 7 active, capped at 5
        # Newest by created_at first; inactive excluded.
        assert memory == ["mem-07", "mem-06", "mem-05", "mem-04", "mem-03"]
        assert "mem-inactive" not in memory

    def test_active_files_limit_and_order(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        payload = collect_snapshot_payload(db)

        files = payload["active_files"]
        assert len(files) == 10  # 12 existing, capped at 10
        # Newest by modified_at first; non-existing excluded.
        assert files == ["/f/%02d" % i for i in range(12, 2, -1)]
        assert "/f/gone" not in files

    def test_token_usage_newest_by_id(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        payload = collect_snapshot_payload(db)

        assert payload["token_usage"] == 500  # id=5, newest


class TestMissingOptionalTables:
    def test_missing_optional_tables_yield_empty_and_none(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db, with_optional=False)

        payload = collect_snapshot_payload(db, created_at="2026-09-21T00:00:00")

        assert payload["active_files"] == []
        assert payload["token_usage"] is None
        # Core fields still collected normally.
        assert payload["session_id"] == "sess-eq"
        assert len(payload["open_tasks"]) == 10
        assert len(payload["recent_memory"]) == 5

    def test_missing_session_config_falls_back_to_unknown(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db, with_optional=False, session=None)

        payload = collect_snapshot_payload(db)

        assert payload["session_id"] == "unknown"


class TestReadOnlyBehaviour:
    def test_open_readonly_connection_refuses_writes(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        conn = _open_readonly(db)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO system_config (key, value) VALUES ('k', 'v')"
                )
        finally:
            conn.close()

    def test_collect_does_not_modify_database_bytes(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        before = db.read_bytes()
        collect_snapshot_payload(db, created_at="2026-09-21T00:00:00")
        after = db.read_bytes()

        assert before == after  # database file untouched

        # No journal/wal sidecars were created in the db directory.
        siblings = sorted(p.name for p in db.parent.iterdir())
        assert siblings == ["bach.db"]

    def test_canonical_live_db_not_touched(self, tmp_path):
        """The collector only ever opens the explicit path passed to it."""
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        # Reading the explicit db works.
        payload = collect_snapshot_payload(db)
        assert payload["session_id"] == "sess-eq"

        # A non-existent path is not silently mapped to any live DB.
        missing = tmp_path / "does-not-exist.db"
        with pytest.raises(Exception):
            collect_snapshot_payload(missing)


class TestTimestampSeam:
    def test_created_at_is_injected_value(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        fixed = "2026-09-21T00:00:00"
        p1 = collect_snapshot_payload(db, created_at=fixed)
        p2 = collect_snapshot_payload(db, created_at=fixed)

        assert p1["created_at"] == fixed
        assert p2["created_at"] == fixed  # deterministic / stable

    def test_created_at_defaults_to_iso_timestamp(self, tmp_path):
        db = tmp_path / "sub" / "bach.db"
        db.parent.mkdir(parents=True)
        _make_db(db)

        payload = collect_snapshot_payload(db)

        # Default is a parseable ISO 8601 timestamp (production behaviour).
        from datetime import datetime

        parsed = datetime.fromisoformat(payload["created_at"])
        assert parsed is not None
