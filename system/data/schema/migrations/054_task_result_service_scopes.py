# SPDX-License-Identifier: MIT
"""Add scoped result-review service records without provisioning a service."""

from __future__ import annotations

import sqlite3

_CORRECTION_COLUMNS = (
    "id", "task_id", "request_id", "correction_round", "source_result_id",
    "source_result_sha256", "source_generation", "source_fence",
    "source_task_version", "source_status_revision", "correction_note",
    "requested_by_device_id", "requested_at", "event_id", "next_task_version",
)


def _create_corrections(conn: sqlite3.Connection, table: str = "task_result_corrections") -> None:
    if table not in {"task_result_corrections", "task_result_corrections_054"}:
        raise ValueError("invalid migration table")
    conn.execute(f"""CREATE TABLE {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        request_id TEXT NOT NULL,
        correction_round INTEGER NOT NULL,
        source_result_id INTEGER NOT NULL,
        source_result_sha256 TEXT NOT NULL,
        source_generation TEXT NOT NULL,
        source_fence INTEGER NOT NULL,
        source_task_version TEXT NOT NULL,
        source_status_revision INTEGER NOT NULL,
        correction_note TEXT NOT NULL,
        requested_by_device_id INTEGER,
        requested_by_service_id TEXT,
        requested_at TEXT NOT NULL,
        event_id INTEGER,
        next_task_version TEXT,
        CHECK ((requested_by_device_id IS NOT NULL AND requested_by_service_id IS NULL)
            OR (requested_by_device_id IS NULL AND requested_by_service_id IS NOT NULL)),
        UNIQUE(task_id, request_id),
        UNIQUE(task_id, correction_round)
    )""")


def _migrate_corrections(conn: sqlite3.Connection) -> None:
    current = conn.execute(
        "SELECT type, sql FROM sqlite_master WHERE name='task_result_corrections'"
    ).fetchone()
    if current is None:
        _create_corrections(conn)
        return
    if current[0] != "table":
        raise RuntimeError("task_result_corrections is not a table")
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(task_result_corrections)")}
    required = set(_CORRECTION_COLUMNS)
    if not required <= set(columns):
        raise RuntimeError("task_result_corrections has an unknown legacy layout")
    allowed = required | {"requested_by_service_id"}
    if set(columns) - allowed:
        raise RuntimeError("task_result_corrections has unknown columns")
    check_sql = str(current[1] or "").replace(" ", "").casefold()
    already_current = (
        "requested_by_service_id" in columns
        and columns["requested_by_device_id"][3] == 0
        and "requested_by_device_idisnotnull" in check_sql
        and "requested_by_service_idisnotnull" in check_sql
    )
    if already_current:
        return

    _create_corrections(conn, "task_result_corrections_054")
    old_names = ",".join(_CORRECTION_COLUMNS)
    if "requested_by_service_id" in columns:
        service_expr = "requested_by_service_id"
    else:
        service_expr = "NULL"
    conn.execute(
        "INSERT INTO task_result_corrections_054 (" + old_names + ",requested_by_service_id) "
        "SELECT " + old_names + "," + service_expr + " FROM task_result_corrections"
    )
    conn.execute("DROP TABLE task_result_corrections")
    conn.execute("ALTER TABLE task_result_corrections_054 RENAME TO task_result_corrections")


def _ensure_tables(conn: sqlite3.Connection) -> None:
    staged = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='task_result_corrections_054'"
    ).fetchone()
    if staged is not None:
        raise RuntimeError("task_result_corrections_054 already exists")
    existing_service = conn.execute(
        "SELECT type FROM sqlite_master WHERE name='task_result_services'"
    ).fetchone()
    if existing_service is not None:
        if existing_service[0] != "table":
            raise RuntimeError("task_result_services has an unknown legacy layout")
        service_info = list(conn.execute("PRAGMA table_info(task_result_services)"))
        service_columns = {row[1] for row in service_info}
        expected_service_columns = {
            "service_id", "credential_scheme", "credential_salt", "credential_verifier",
            "issuer_id", "principal_id", "generation", "revision", "status", "created_at", "revoked_at",
        }
        service_primary_key = [row[1] for row in service_info if row[5]]
        if service_columns != expected_service_columns or service_primary_key != ["service_id"]:
            raise RuntimeError("task_result_services has an incompatible credential layout")
    task_columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
    if not task_columns:
        raise RuntimeError("tasks table is unavailable")
    if "result_correction_request_id" not in task_columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN result_correction_request_id INTEGER")

    _migrate_corrections(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS task_result_services (
        service_id TEXT PRIMARY KEY,
        credential_scheme TEXT NOT NULL CHECK (credential_scheme = 'argon2id-v1'),
        credential_salt BLOB NOT NULL CHECK (length(credential_salt) = 16),
        credential_verifier BLOB NOT NULL CHECK (length(credential_verifier) = 32),
        issuer_id TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        generation TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        status TEXT NOT NULL CHECK (status IN ('active','revoked')),
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS task_result_service_scopes (
        scope_id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        action TEXT NOT NULL CHECK (action IN ('read','history','accept','correction')),
        task_id INTEGER,
        category TEXT,
        created_at TEXT NOT NULL,
        CHECK ((task_id IS NOT NULL AND category IS NULL)
            OR (task_id IS NULL AND category IS NOT NULL)),
        FOREIGN KEY(service_id) REFERENCES task_result_services(service_id) ON DELETE CASCADE
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_result_service_scopes_revision "
                 "ON task_result_service_scopes(service_id, revision, action, task_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS task_result_service_producer_bindings (
        result_id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL,
        result_sha256 TEXT NOT NULL,
        generation TEXT NOT NULL,
        fence INTEGER NOT NULL CHECK (fence > 0),
        task_version TEXT NOT NULL,
        producer_principal TEXT NOT NULL,
        issuer_id TEXT NOT NULL,
        submission_event_id INTEGER,
        bound_at TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_result_service_producer_task "
                 "ON task_result_service_producer_bindings(task_id, result_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS task_result_service_audit (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id TEXT NOT NULL,
        service_revision INTEGER NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('accept','correction')),
        task_id INTEGER NOT NULL,
        result_id INTEGER NOT NULL,
        result_sha256 TEXT NOT NULL,
        task_version TEXT NOT NULL,
        status_revision INTEGER NOT NULL,
        decision_schema TEXT NOT NULL,
        decision_reason TEXT NOT NULL CHECK (decision_reason='allow'),
        policy_distribution TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        policy_sha256 TEXT NOT NULL,
        event_id INTEGER,
        occurred_at TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_result_service_audit_task "
                 "ON task_result_service_audit(task_id, audit_id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_result_corrections_event "
                 "ON task_result_corrections(task_id, event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_result_corrections_task_event_desc "
                 "ON task_result_corrections(task_id, event_id DESC)")


def run_migration(conn: sqlite3.Connection | None = None) -> None:
    owns_connection = conn is None
    if owns_connection:
        from hub.bach_paths import BACH_DB
        conn = sqlite3.connect(str(BACH_DB))
    savepoint = "task_result_service_scopes_054"
    try:
        conn.execute("SAVEPOINT " + savepoint)
        _ensure_tables(conn)
        conn.execute("RELEASE SAVEPOINT " + savepoint)
        if owns_connection:
            conn.commit()
    except BaseException:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT " + savepoint)
            conn.execute("RELEASE SAVEPOINT " + savepoint)
        except sqlite3.Error:
            pass
        raise
    finally:
        if owns_connection:
            conn.close()


if __name__ == "__main__":
    run_migration()
