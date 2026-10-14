# SPDX-License-Identifier: MIT
"""Isolated upgrade tests for scoped result-review service records."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
MIGRATION_PATH = SYSTEM_ROOT / "data" / "schema" / "migrations" / "054_task_result_service_scopes.py"
SPEC = importlib.util.spec_from_file_location("migration_054_task_result_service_scopes", MIGRATION_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def _legacy_connection():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL)")
    conn.execute("CREATE TABLE task_history (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL)")
    conn.execute("""CREATE TABLE task_result_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, request_id TEXT NOT NULL,
        correction_round INTEGER NOT NULL, source_result_id INTEGER NOT NULL,
        source_result_sha256 TEXT NOT NULL, source_generation TEXT NOT NULL,
        source_fence INTEGER NOT NULL, source_task_version TEXT NOT NULL,
        source_status_revision INTEGER NOT NULL, correction_note TEXT NOT NULL,
        requested_by_device_id INTEGER NOT NULL, requested_at TEXT NOT NULL,
        event_id INTEGER, next_task_version TEXT, UNIQUE(task_id, request_id),
        UNIQUE(task_id, correction_round))""")
    conn.execute("""INSERT INTO task_result_corrections
        (task_id,request_id,correction_round,source_result_id,source_result_sha256,
         source_generation,source_fence,source_task_version,source_status_revision,
         correction_note,requested_by_device_id,requested_at,event_id,next_task_version)
        VALUES (17,'legacy-request',1,9,?, 'worker-gen',4,?,2,'review note',3,
                '2026-10-14T01:00:00',44,?)""", ("a" * 64, "b" * 64, "c" * 64))
    conn.commit()
    return conn


def test_upgrade_preserves_legacy_corrections_and_is_idempotent():
    conn = _legacy_connection()
    try:
        legacy_columns = MIGRATION._CORRECTION_COLUMNS
        selected = ",".join(legacy_columns)
        before = tuple(conn.execute(f"SELECT {selected} FROM task_result_corrections").fetchone())
        MIGRATION.run_migration(conn)
        once_legacy = tuple(
            conn.execute(f"SELECT {selected} FROM task_result_corrections").fetchone()
        )
        once = tuple(conn.execute("SELECT * FROM task_result_corrections").fetchone())
        assert once_legacy == before
        assert conn.execute(
            "SELECT requested_by_service_id FROM task_result_corrections WHERE id=1"
        ).fetchone()[0] is None
        assert "result_correction_request_id" in {
            row[1] for row in conn.execute("PRAGMA table_info(tasks)")
        }
        MIGRATION.run_migration(conn)
        assert tuple(conn.execute("SELECT * FROM task_result_corrections").fetchone()) == once
        assert conn.execute("SELECT COUNT(*) FROM task_result_services").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM task_result_service_scopes").fetchone()[0] == 0
        audit_columns = {row[1] for row in conn.execute("PRAGMA table_info(task_result_service_audit)")}
        assert not {"token", "token_hash", "correction_note"} & audit_columns
    finally:
        conn.close()


def test_correction_actor_constraint_requires_exactly_one_identity():
    conn = _legacy_connection()
    try:
        MIGRATION.run_migration(conn)
        base = (18, "service-request", 1, 11, "d" * 64, "worker-gen", 5,
                "e" * 64, 0, "note", None, None, "2026-10-14T01:01:00", None, None)
        for device_id, service_id in ((None, None), (3, "service-1")):
            with __import__("pytest").raises(sqlite3.IntegrityError):
                conn.execute("""INSERT INTO task_result_corrections
                    (task_id,request_id,correction_round,source_result_id,source_result_sha256,
                     source_generation,source_fence,source_task_version,source_status_revision,
                     correction_note,requested_by_device_id,requested_by_service_id,requested_at,
                     event_id,next_task_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*base[:10], device_id, service_id, *base[12:]))
        conn.rollback()
    finally:
        conn.close()


def test_unknown_legacy_correction_layout_rolls_back_without_partial_tables():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        conn.execute("CREATE TABLE task_result_corrections (id INTEGER PRIMARY KEY, mystery TEXT)")
        try:
            MIGRATION.run_migration(conn)
        except RuntimeError as exc:
            assert "unknown legacy layout" in str(exc)
        else:
            raise AssertionError("unknown correction schema should fail closed")
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "task_result_services" not in names
        assert "result_correction_request_id" not in {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    finally:
        conn.close()


def test_upgrade_refuses_preexisting_correction_stage_table_without_mutation():
    conn = _legacy_connection()
    try:
        conn.execute("CREATE TABLE task_result_corrections_054 (sentinel TEXT NOT NULL)")
        conn.execute("INSERT INTO task_result_corrections_054 VALUES ('preserve-me')")
        conn.commit()
        before_schema = tuple(conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ))
        before_tasks = tuple(conn.execute("SELECT * FROM tasks ORDER BY id"))
        before_corrections = tuple(conn.execute("SELECT * FROM task_result_corrections ORDER BY id"))
        before_stage = tuple(conn.execute("SELECT * FROM task_result_corrections_054"))
        with __import__("pytest").raises(RuntimeError, match="task_result_corrections_054 already exists"):
            MIGRATION.run_migration(conn)
        assert conn.in_transaction is False
        assert tuple(conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        )) == before_schema
        assert tuple(conn.execute("SELECT * FROM tasks ORDER BY id")) == before_tasks
        assert tuple(conn.execute("SELECT * FROM task_result_corrections ORDER BY id")) == before_corrections
        assert tuple(conn.execute("SELECT * FROM task_result_corrections_054")) == before_stage
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='task_result_services'"
        ).fetchone()[0] == 0
    finally:
        conn.close()
