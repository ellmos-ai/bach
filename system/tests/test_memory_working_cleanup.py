# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT

import sqlite3
import sys
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
TOOLS_ROOT = SYSTEM_ROOT / "tools"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import memory_working_cleanup as cleanup_module


def _create_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memory_working (
            id INTEGER PRIMARY KEY,
            type TEXT,
            content TEXT,
            priority INTEGER,
            tags TEXT,
            created_at TEXT,
            updated_at TEXT,
            expires_at TEXT,
            is_active INTEGER,
            created_by_session_id TEXT,
            updated_by_session_id TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _insert_note(db_path: Path, days_old: int, content: str) -> None:
    created_at = (datetime.now() - timedelta(days=days_old)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO memory_working (type, content, priority, created_at, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("note", content, 1, created_at, None, 1),
    )
    conn.commit()
    conn.close()


def _apply_archive_migration(db_path: Path) -> None:
    migration_path = (
        SYSTEM_ROOT / "data" / "schema" / "migrations"
        / "042_archived_memory_source_record.py"
    )
    spec = importlib.util.spec_from_file_location("migration_042_archive", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with sqlite3.connect(db_path) as conn:
        module.run_migration(conn)


def test_analyze_stats_classifies_entries(tmp_path):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _insert_note(db_path, 1, "recent")
    _insert_note(db_path, 10, "review")
    _insert_note(db_path, 20, "archive")

    cleanup = cleanup_module.WorkingMemoryCleanup(db_path)
    stats = cleanup.analyze_stats()

    assert stats["total"] == 3
    assert stats["keep"] == 1
    assert stats["review"] == 1
    assert stats["archive"] == 1


def test_main_analyze_prints_stats(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "working.db"
    db_path.touch()
    monkeypatch.setenv("BACH_DB", str(db_path))
    monkeypatch.setattr(
        cleanup_module.WorkingMemoryCleanup,
        "analyze_stats",
        lambda self: {
            "total": 2,
            "keep": 1,
            "review": 1,
            "archive": 0,
            "by_age": {"< 7d": 1, "7-14d": 1, "> 14d": 0},
            "entries": [
                {"age_days": 10.0, "action": "REVIEW", "content": "older note"},
                {"age_days": 1.0, "action": "KEEP", "content": "recent note"},
            ],
        },
    )
    monkeypatch.setattr(sys, "argv", ["memory_working_cleanup.py", "analyze"])

    cleanup_module.main()

    out = capsys.readouterr().out
    assert "WORKING MEMORY ANALYSE" in out
    assert "Total Eintraege:  2" in out
    assert "older note" in out


def test_cleanup_alias_delegates_to_cleanup_soft(monkeypatch, tmp_path):
    db_path = tmp_path / "working.db"
    cleanup = cleanup_module.WorkingMemoryCleanup(db_path)
    calls = []

    def fake_cleanup_soft(self, dry_run=True):
        calls.append(dry_run)
        return True, "ok"

    monkeypatch.setattr(cleanup_module.WorkingMemoryCleanup, "cleanup_soft", fake_cleanup_soft)

    success, message = cleanup.cleanup(dry_run=False)

    assert success is True
    assert message == "ok"
    assert calls == [False]


def test_archive_defaults_to_dry_run_and_preserves_source(tmp_path):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _apply_archive_migration(db_path)
    _insert_note(db_path, 40, "bleibt erhalten")

    success, message = cleanup_module.WorkingMemoryCleanup(db_path).archive(days=30)

    assert success is True
    assert "[DRY-RUN]" in message
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM archived_memory").fetchone()[0] == 0


def test_archive_restore_is_lossless_and_atomic(tmp_path):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _apply_archive_migration(db_path)
    created_at = (datetime.now() - timedelta(days=45)).isoformat()
    original = (
        17,
        "context",
        "Umlaute: äöü",
        7,
        '["alpha","beta"]',
        created_at,
        "2026-08-08T08:08:08",
        "2026-08-09T09:09:09",
        0,
        "session-create",
        "session-update",
    )
    columns = (
        "id, type, content, priority, tags, created_at, updated_at, expires_at, "
        "is_active, created_by_session_id, updated_by_session_id"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO memory_working ({columns}) VALUES ({','.join('?' * 11)})",
            original,
        )

    cleanup = cleanup_module.WorkingMemoryCleanup(db_path)
    success, message = cleanup.archive(days=30, dry_run=False)
    assert success is True, message

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0] == 0
        archive_id, source_record = conn.execute(
            "SELECT archive_id, source_record FROM archived_memory"
        ).fetchone()
        assert '"priority":7' in source_record
        assert '"tags":"[\\"alpha\\",\\"beta\\"]"' in source_record
        assert '"is_active":0' in source_record

    success, message = cleanup.restore(archive_id, dry_run=False)
    assert success is True, message

    with sqlite3.connect(db_path) as conn:
        restored = conn.execute(
            f"SELECT {columns} FROM memory_working WHERE id = 17"
        ).fetchone()
        assert restored == original
        assert conn.execute("SELECT COUNT(*) FROM archived_memory").fetchone()[0] == 0
        log = conn.execute(
            "SELECT archive_table, archive_id, target_id, success FROM restore_log"
        ).fetchone()
        assert log == ("archived_memory", archive_id, 17, 1)


def test_archive_locks_before_snapshot_so_concurrent_update_cannot_be_lost(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _apply_archive_migration(db_path)
    _insert_note(db_path, 40, "snapshot")
    real_connect = sqlite3.connect
    concurrent = {"attempted": False, "blocked": False}

    class CursorProxy:
        def __init__(self, cursor):
            self._cursor = cursor
            self._sql = ""

        def execute(self, sql, parameters=()):
            self._sql = sql
            self._cursor.execute(sql, parameters)
            return self

        def executemany(self, sql, parameters):
            self._sql = sql
            self._cursor.executemany(sql, parameters)
            return self

        def fetchone(self):
            return self._cursor.fetchone()

        def fetchall(self):
            rows = self._cursor.fetchall()
            if "FROM memory_working" in self._sql and not concurrent["attempted"]:
                concurrent["attempted"] = True
                try:
                    with real_connect(db_path, timeout=0) as other:
                        other.execute(
                            "UPDATE memory_working SET content='newer' WHERE id=1"
                        )
                except sqlite3.OperationalError as exc:
                    concurrent["blocked"] = "locked" in str(exc).lower()
            return rows

        @property
        def rowcount(self):
            return self._cursor.rowcount

        def __iter__(self):
            return iter(self._cursor)

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def cursor(self):
            return CursorProxy(self._connection.cursor())

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        cleanup_module.sqlite3,
        "connect",
        lambda *args, **kwargs: ConnectionProxy(real_connect(*args, **kwargs)),
    )

    success, message = cleanup_module.WorkingMemoryCleanup(db_path).archive(
        days=30, dry_run=False
    )

    assert success is True, message
    assert concurrent == {"attempted": True, "blocked": True}
    with real_connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0] == 0
        assert '"content":"snapshot"' in conn.execute(
            "SELECT source_record FROM archived_memory"
        ).fetchone()[0]


def test_restore_collision_keeps_archive_and_source_unchanged(tmp_path):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _apply_archive_migration(db_path)
    _insert_note(db_path, 40, "original")
    cleanup = cleanup_module.WorkingMemoryCleanup(db_path)
    assert cleanup.archive(days=30, dry_run=False)[0] is True

    with sqlite3.connect(db_path) as conn:
        archive_id, original_id = conn.execute(
            "SELECT archive_id, original_id FROM archived_memory"
        ).fetchone()
        conn.execute(
            "INSERT INTO memory_working (id, type, content, created_at, is_active) "
            "VALUES (?, 'note', 'collision', CURRENT_TIMESTAMP, 1)",
            (original_id,),
        )

    success, message = cleanup.restore(archive_id, dry_run=False)

    assert success is False
    assert "bereits belegt" in message
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT content FROM memory_working").fetchone()[0] == "collision"
        assert conn.execute("SELECT COUNT(*) FROM archived_memory").fetchone()[0] == 1


@pytest.mark.parametrize("days", [0, -1])
def test_archive_rejects_nonpositive_days_without_mutation(tmp_path, days):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _apply_archive_migration(db_path)
    _insert_note(db_path, 40, "protected")

    success, message = cleanup_module.WorkingMemoryCleanup(db_path).archive(
        days=days, dry_run=False
    )

    assert success is False
    assert "größer als 0" in message
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM archived_memory").fetchone()[0] == 0


def test_archive_without_lossless_schema_fails_before_delete(tmp_path):
    db_path = tmp_path / "working.db"
    _create_db(db_path)
    _insert_note(db_path, 40, "protected")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE archived_memory (archive_id INTEGER PRIMARY KEY, "
            "original_id INTEGER, memory_type TEXT NOT NULL)"
        )

    success, message = cleanup_module.WorkingMemoryCleanup(db_path).archive(
        days=30, dry_run=False
    )

    assert success is False
    assert "source_record fehlt" in message
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_working").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("command", "method", "identifier"),
    [
        ("archive", "archive", None),
        ("restore", "restore", "7"),
    ],
)
@pytest.mark.parametrize(
    "flags", [["--apply", "--dry-run"], ["--dry-run", "--apply"]]
)
def test_cli_dry_run_wins_over_apply(
    tmp_path, monkeypatch, command, method, identifier, flags
):
    db_path = tmp_path / "working.db"
    db_path.touch()
    calls = []

    def fake_archive(self, days=30, dry_run=True):
        calls.append(("archive", days, dry_run))
        return True, "ok"

    def fake_restore(self, archive_id, dry_run=True):
        calls.append(("restore", archive_id, dry_run))
        return True, "ok"

    monkeypatch.setenv("BACH_DB", str(db_path))
    monkeypatch.setattr(cleanup_module.WorkingMemoryCleanup, "archive", fake_archive)
    monkeypatch.setattr(cleanup_module.WorkingMemoryCleanup, "restore", fake_restore)
    argv = ["memory_working_cleanup.py", command]
    if identifier is not None:
        argv.append(identifier)
    argv.extend(flags)
    monkeypatch.setattr(sys, "argv", argv)

    cleanup_module.main()

    assert calls[0][0] == method
    assert calls[0][-1] is True


def test_fresh_schema_roundtrip_preserves_null_provenance_with_active_session(tmp_path):
    db_path = tmp_path / "fresh.db"
    schema = (SYSTEM_ROOT / "data" / "schema" / "schema.sql").read_text(
        encoding="utf-8"
    )
    old = (datetime.now() - timedelta(days=45)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        conn.execute(
            "INSERT INTO memory_sessions (session_id, started_at) VALUES (?, ?)",
            ("active-session", datetime.now().isoformat()),
        )
        conn.execute(
            """
            INSERT INTO memory_working
                (id, type, content, priority, tags, created_at, updated_at,
                 expires_at, is_active, created_by_session_id, updated_by_session_id)
            VALUES (17, 'context', 'historisch', 4, '["tag"]', ?, ?, NULL, 0,
                    NULL, NULL)
            """,
            (old, old),
        )
        # Der Provenienz-Trigger fuellt beim normalen Insert die aktive Session.
        # Fuer den Test stellen wir den tatsaechlich archivierten Altzustand her.
        conn.execute(
            """
            UPDATE memory_working
            SET created_by_session_id = NULL, updated_by_session_id = NULL
            WHERE id = 17
            """
        )

    cleanup = cleanup_module.WorkingMemoryCleanup(db_path)
    assert cleanup.archive(days=30, dry_run=False)[0] is True
    with sqlite3.connect(db_path) as conn:
        archive_id = conn.execute(
            "SELECT archive_id FROM archived_memory WHERE original_id = 17"
        ).fetchone()[0]

    success, message = cleanup.restore(archive_id, dry_run=False)
    assert success is True, message
    with sqlite3.connect(db_path) as conn:
        provenance = conn.execute(
            """
            SELECT created_by_session_id, updated_by_session_id
            FROM memory_working WHERE id = 17
            """
        ).fetchone()
        assert provenance == (None, None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
