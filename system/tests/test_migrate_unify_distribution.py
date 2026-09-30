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


@pytest.fixture
def committed_legacy_db(tmp_path):
    """Persisted rows expose DDL that a caller rollback cannot undo."""
    with sqlite3.connect(tmp_path / "legacy.db") as conn:
        _old_schema_with_seal_row(conn)
        conn.commit()
        yield conn


def _snapshot(conn):
    return list(conn.iterdump())


@pytest.mark.parametrize("view", ["v_files_with_tiers", "v_latest_versions"])
def test_legacy_view_name_collision_preserves_committed_identity(committed_legacy_db, view):
    conn = committed_legacy_db
    conn.execute(f'DROP VIEW "{view}"')
    conn.execute(f'CREATE TABLE "{view}" (keep TEXT)')
    conn.execute(f'INSERT INTO "{view}" VALUES (?)', ("preserve me",))
    conn.commit()
    before = _snapshot(conn)
    with pytest.raises(RuntimeError, match=view):
        _load_migration().run_migration(conn)
    conn.rollback()
    assert _snapshot(conn) == before


def test_missing_required_identity_column_preserves_original(committed_legacy_db):
    conn = committed_legacy_db
    conn.execute("ALTER TABLE instance_identity DROP COLUMN instance_name")
    conn.commit()
    before = _snapshot(conn)
    with pytest.raises(RuntimeError, match="instance_name"):
        _load_migration().run_migration(conn)
    conn.rollback()
    assert _snapshot(conn) == before


@pytest.mark.parametrize("in_outer_transaction", [False, True])
def test_late_failure_rolls_back_all_mutations(committed_legacy_db, monkeypatch, in_outer_transaction):
    conn = committed_legacy_db
    migration = _load_migration()
    if in_outer_transaction:
        conn.execute("INSERT INTO tasks (id) VALUES (42)")
    before = _snapshot(conn)
    monkeypatch.setattr(migration, "DISTRIBUTION_STATS_VIEW_SQL", "INVALID SQL")
    with pytest.raises(sqlite3.OperationalError):
        migration.run_migration(conn)
    assert conn.in_transaction == in_outer_transaction
    assert _snapshot(conn) == before


def test_success_does_not_commit_callers_transaction(committed_legacy_db):
    conn = committed_legacy_db
    before = _snapshot(conn)
    conn.execute("INSERT INTO tasks (id) VALUES (42)")
    _load_migration().run_migration(conn)
    assert conn.in_transaction
    conn.rollback()
    assert _snapshot(conn) == before


@pytest.mark.parametrize("table", _load_migration().LEGACY_TABLES)
def test_each_nonempty_legacy_table_aborts_without_changes(committed_legacy_db, table):
    conn = committed_legacy_db
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
        conn.execute(f'CREATE TABLE "{table}" (id INTEGER)')
    conn.execute(f'INSERT INTO "{table}" (id) VALUES (1)')
    conn.commit()
    before = _snapshot(conn)
    with pytest.raises(RuntimeError, match=table):
        _load_migration().run_migration(conn)
    assert _snapshot(conn) == before


@pytest.mark.parametrize("name,ddl", [
    ("distribution_snapshots", "CREATE VIEW distribution_snapshots AS SELECT 1 AS id"),
    ("distribution_snapshot_files", "CREATE VIEW distribution_snapshot_files AS SELECT 1 AS id"),
    ("distribution_releases", "CREATE VIEW distribution_releases AS SELECT 1 AS id"),
    ("distribution_file_versions", "CREATE VIEW distribution_file_versions AS SELECT 1 AS id"),
    ("v_distribution_stats", "CREATE TABLE v_distribution_stats (id INTEGER)"),
    ("instance_identity_pre_unify", "CREATE TABLE instance_identity_pre_unify (keep TEXT)"),
])
def test_conflicting_target_objects_preserve_database(committed_legacy_db, name, ddl):
    conn = committed_legacy_db
    conn.execute(ddl)
    conn.commit()
    before = _snapshot(conn)
    with pytest.raises(RuntimeError, match=name):
        _load_migration().run_migration(conn)
    assert _snapshot(conn) == before


def test_unknown_identity_column_is_not_silently_lost(committed_legacy_db):
    conn = committed_legacy_db
    conn.execute("ALTER TABLE instance_identity ADD COLUMN private_note TEXT")
    conn.execute("UPDATE instance_identity SET private_note='preserve me'")
    conn.commit()
    before = _snapshot(conn)
    with pytest.raises(RuntimeError, match="private_note"):
        _load_migration().run_migration(conn)
    assert _snapshot(conn) == before


def test_runner_late_failure_preserves_persisted_database(tmp_path):
    """Exercise the actual migration connection and bookkeeping contract."""
    from core.db import Database

    schema = tmp_path / "schema"
    (schema / "migrations").mkdir(parents=True)
    target = schema / "migrations" / MIGRATION.name
    target.write_bytes(MIGRATION.read_bytes())
    db_path = tmp_path / "runner.db"
    with sqlite3.connect(db_path) as conn:
        _old_schema_with_seal_row(conn)
        conn.execute("CREATE TABLE _migrations (filename TEXT UNIQUE, applied_at TEXT)")
        conn.commit()
        before = _snapshot(conn)

    # Force a failure after the table rebuild and legacy-table drops.
    source = target.read_text(encoding="utf-8")
    source = source.replace("conn.execute(DISTRIBUTION_STATS_VIEW_SQL)", "conn.execute('INVALID SQL')")
    target.write_text(source, encoding="utf-8")
    db = Database(db_path, schema)
    applied, error = db.run_migrations()
    assert applied == [] and "fehlgeschlagen" in error
    with sqlite3.connect(db_path) as conn:
        assert _snapshot(conn) == before
        assert conn.execute("SELECT COUNT(*) FROM instance_identity").fetchone()[0] == 1


def test_all_identity_fields_and_multiple_rows_survive(committed_legacy_db):
    conn = committed_legacy_db
    migration = _load_migration()
    columns = migration.NEW_INSTANCE_IDENTITY_COLUMNS
    rows = [tuple(f"value-{number}-{column}" for column in columns) for number in range(3)]
    conn.execute("DELETE FROM instance_identity")
    conn.executemany(
        f"INSERT INTO instance_identity ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})", rows)
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    migration.run_migration(conn)
    assert conn.execute(
        f"SELECT {', '.join(columns)} FROM instance_identity ORDER BY instance_id"
    ).fetchall() == rows
