"""Tests für die fail-closed, idempotente Distribution-Unify-Migration
(T-20260926-357988320)."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).parents[1]
    / "data"
    / "schema"
    / "migrations"
    / "migrate_unify_distribution.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migrate_unify_distribution", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _old_schema_with_seal_row(conn):
    """Alte (current_mode-haltige) instance_identity-Form + 1 Bestandszeile,
    plus einige der zu droppenden Legacy-Tabellen -- teils leer, teils mit
    echten Zeilen, wie auf Laptop/Mac vorgefunden (T-20260926-598278998)."""
    conn.execute(
        """
        CREATE TABLE instance_identity (
            instance_id TEXT PRIMARY KEY,
            instance_name TEXT NOT NULL,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            forked_from TEXT,
            seal_status TEXT DEFAULT 'intact',
            seal_broken_at TIMESTAMP,
            seal_broken_by TEXT,
            seal_broken_reason TEXT,
            kernel_hash TEXT,
            kernel_version TEXT,
            seal_last_verified TIMESTAMP,
            current_mode TEXT DEFAULT 'developer',
            base_release TEXT,
            base_release_date TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO instance_identity
            (instance_id, instance_name, forked_from, seal_status,
             kernel_hash, kernel_version, seal_last_verified,
             current_mode, base_release)
        VALUES
            ('inst-abc123', 'ASUS-GEI', NULL, 'intact',
             'deadbeef' || 'cafe0000', 'v3.5.0', '2026-09-20T10:00:00',
             'developer', 'v3.4.0')
        """
    )
    conn.execute(
        "CREATE TABLE tiers (id INTEGER PRIMARY KEY, name TEXT)"
    )
    conn.execute(
        "CREATE TABLE filesystem_entries (id INTEGER PRIMARY KEY, path TEXT)"
    )
    conn.execute("CREATE VIEW v_files_with_tiers AS SELECT id FROM tiers")
    conn.execute("CREATE VIEW v_latest_versions AS SELECT id FROM filesystem_entries")
    for table in ("skills", "tools", "tasks", "distribution_manifest"):
        conn.execute(
            f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0)"
        )


def test_instance_identity_row_survives_with_seal_fields_intact():
    conn = sqlite3.connect(":memory:")
    _old_schema_with_seal_row(conn)
    # Alle Legacy-Tabellen bleiben in diesem Test leer -> keine Abbruchbedingung.

    _load_migration().run_migration(conn)

    row = conn.execute(
        "SELECT instance_id, instance_name, seal_status, kernel_hash, "
        "kernel_version, seal_last_verified, base_release "
        "FROM instance_identity"
    ).fetchall()
    assert len(row) == 1
    (instance_id, instance_name, seal_status, kernel_hash,
     kernel_version, seal_last_verified, base_release) = row[0]
    assert instance_id == "inst-abc123"
    assert instance_name == "ASUS-GEI"
    assert seal_status == "intact"
    assert kernel_hash == "deadbeefcafe0000"
    assert kernel_version == "v3.5.0"
    assert seal_last_verified == "2026-09-20T10:00:00"
    assert base_release == "v3.4.0"

    # current_mode ist bewusst weg (toter Spalte, kein Aufrufer liest sie).
    columns = [r[1] for r in conn.execute('PRAGMA table_info("instance_identity")')]
    assert "current_mode" not in columns
    assert columns == _load_migration().NEW_INSTANCE_IDENTITY_COLUMNS

    # Legacy-Tabellen/-Views weg, neue Distribution-Tabellen da.
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tiers'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='distribution_snapshots'"
    ).fetchone() is not None


def test_nonempty_legacy_table_aborts_and_changes_nothing():
    conn = sqlite3.connect(":memory:")
    _old_schema_with_seal_row(conn)
    # filesystem_entries hat noch echten Bestand -- muss den Abbruch ausloesen.
    conn.execute("INSERT INTO filesystem_entries (id, path) VALUES (1, '/etc/passwd')")

    with pytest.raises(RuntimeError, match="filesystem_entries.*1 Zeile"):
        _load_migration().run_migration(conn)

    # Nichts veraendert: instance_identity noch in ALTER Form mit der Zeile,
    # tiers (leer, waere an sich droppable gewesen) noch da, die
    # Legacy-Views noch da, keine neuen distribution_*-Tabellen.
    old_columns = [r[1] for r in conn.execute('PRAGMA table_info("instance_identity")')]
    assert "current_mode" in old_columns
    assert conn.execute(
        "SELECT COUNT(*) FROM instance_identity"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tiers'"
    ).fetchone() is not None
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' "
        "AND name='v_files_with_tiers'"
    ).fetchone() is not None
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='distribution_snapshots'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT path FROM filesystem_entries WHERE id=1"
    ).fetchone()[0] == "/etc/passwd"


def test_second_run_is_a_no_op():
    conn = sqlite3.connect(":memory:")
    _old_schema_with_seal_row(conn)

    migration = _load_migration()
    migration.run_migration(conn)

    after_first = {
        name: sql for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    row_after_first = conn.execute(
        "SELECT * FROM instance_identity"
    ).fetchone()

    migration.run_migration(conn)  # zweiter Lauf -- muss No-Op sein

    after_second = {
        name: sql for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    row_after_second = conn.execute(
        "SELECT * FROM instance_identity"
    ).fetchone()

    assert after_first == after_second
    assert row_after_first == row_after_second


def test_fresh_schema_without_instance_identity_creates_it_empty():
    # Kein Bestand, keine Legacy-Tabellen ueberhaupt vorhanden (frische DB).
    conn = sqlite3.connect(":memory:")
    for table in ("skills", "tools", "tasks", "distribution_manifest"):
        conn.execute(
            f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, dist_type INTEGER DEFAULT 0)"
        )

    _load_migration().run_migration(conn)

    assert conn.execute(
        "SELECT COUNT(*) FROM instance_identity"
    ).fetchone()[0] == 0
    columns = [r[1] for r in conn.execute('PRAGMA table_info("instance_identity")')]
    assert columns == _load_migration().NEW_INSTANCE_IDENTITY_COLUMNS
