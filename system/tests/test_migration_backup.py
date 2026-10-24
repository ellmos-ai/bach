# -*- coding: utf-8 -*-
"""Sicherung vor jeder Migrationsrunde, keine Auto-Migration bei Lesebefehlen.

T-20260926-958264544: Jeder BACH-CLI-Start (sogar ``update migrations list``)
fuehrte ausstehende Migrationen ungefragt und ohne Sicherung aus (Laptop,
2026-09-26 20:09, 043+044).
"""
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest

import core.db as core_db
from core.db import Database

SYSTEM_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def db_with_pending(tmp_path):
    schema = tmp_path / "schema"
    (schema / "migrations").mkdir(parents=True)
    (schema / "schema.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);", encoding="utf-8")
    (schema / "migrations" / "001_add.sql").write_text("ALTER TABLE t ADD COLUMN email TEXT;", encoding="utf-8")
    db = Database(tmp_path / "bach.db", schema)
    db.init_schema()
    db.execute_write("INSERT INTO t (name) VALUES ('x')")
    return db, tmp_path


def _columns(path):
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(t)")]
    conn.close()
    return cols


def test_run_migrations_backs_up_first(db_with_pending):
    db, tmp = db_with_pending
    applied, error = db.run_migrations()
    assert (applied, error) == (["001_add.sql"], None)
    backups = list(tmp.glob("bach.db.premig-001_add-*.bak"))
    assert len(backups) == 1
    assert _columns(backups[0]) == ["id", "name"]          # Vorzustand gesichert
    assert _columns(tmp / "bach.db") == ["id", "name", "email"]


def test_no_migration_without_backup(db_with_pending, monkeypatch):
    db, tmp = db_with_pending

    def fail(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(core_db, "backup_before_migration", fail)
    applied, error = db.run_migrations()
    assert applied == [] and "Sicherung vor Migration fehlgeschlagen" in error
    assert _columns(tmp / "bach.db") == ["id", "name"]
    assert db.execute("SELECT filename FROM _migrations") == []


def test_nothing_pending_makes_no_backup(db_with_pending):
    db, tmp = db_with_pending
    db.run_migrations()
    before = set(tmp.glob("*.bak"))
    assert db.run_migrations() == ([], None)
    assert set(tmp.glob("*.bak")) == before


def test_update_handler_run_backs_up(tmp_path, monkeypatch):
    from hub.update import UpdateHandler
    db, tmp = Database(tmp_path / "bach.db", tmp_path), tmp_path
    conn = sqlite3.connect(tmp / "bach.db")
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    handler = UpdateHandler.__new__(UpdateHandler)
    handler.db_path = tmp / "bach.db"
    handler.migrations_dir = tmp / "migrations"
    handler.migrations_dir.mkdir()
    (handler.migrations_dir / "005_x.sql").write_text("ALTER TABLE t ADD COLUMN y TEXT;", encoding="utf-8")
    monkeypatch.setattr(handler, "_applied_migrations", lambda: set(), raising=False)
    monkeypatch.setattr(handler, "_get_available_migrations", lambda: ["005_x.sql"], raising=False)
    monkeypatch.setattr(handler, "_mark_applied", lambda names: None, raising=False)
    ok, message = handler._run_migrations()
    assert ok, message
    assert "Sicherung:" in message and list(tmp.glob("bach.db.premig-005_x-*.bak"))


@pytest.mark.parametrize("argv,flag", [
    (["update", "migrations", "list"], "1"),
    (["update", "migrations"], "1"),
    (["update", "status"], "1"),
    (["task", "list"], None),
])
def test_bach_cli_sets_no_auto_migrate_for_read_commands(monkeypatch, argv, flag):
    import bach as bach_cli
    monkeypatch.setenv(core_db.NO_AUTO_MIGRATE_ENV, "vorher")  # Teardown stellt den Ausgangszustand her
    monkeypatch.delenv(core_db.NO_AUTO_MIGRATE_ENV)
    monkeypatch.setattr(sys, "argv", ["bach.py", *argv, "--help"])  # Hilfe-Pfad: keine Nebenwirkung
    try:
        bach_cli.main()
    except SystemExit:
        pass
    assert os.environ.get(core_db.NO_AUTO_MIGRATE_ENV) == flag


def test_app_does_not_auto_migrate_with_flag(tmp_path, monkeypatch):
    import core.app as core_app
    calls = []
    monkeypatch.setattr(Database, "run_migrations", lambda self: calls.append(1) or ([], None))
    monkeypatch.setattr(Database, "is_empty", lambda self: False)
    monkeypatch.setattr(Database, "migration_backlog", lambda self: [])
    monkeypatch.setenv(core_db.NO_AUTO_MIGRATE_ENV, "1")
    core_app.App(SYSTEM_DIR).db
    assert calls == []
    monkeypatch.delenv(core_db.NO_AUTO_MIGRATE_ENV)
    core_app.App(SYSTEM_DIR).db
    assert calls == [1]


def test_reuse_within_window_and_retention(tmp_path, monkeypatch):
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    manual = tmp_path / "bach.db.pre-handarbeit-20260101-000000.bak"
    manual.write_bytes(b"manuell")
    first = core_db.backup_before_migration(db, ["001_a.sql"])
    assert core_db.backup_before_migration(db, ["001_a.sql"]) == first  # < 10 min, gleiche Liste
    other = core_db.backup_before_migration(db, ["001_a.sql", "002_b.sql"])
    assert other != first
    monkeypatch.setattr(core_db, "MIGRATION_BACKUP_REUSE_SECONDS", 0)
    made = set()
    for i in range(8):
        made.add(core_db.backup_before_migration(db, [f"{i:03d}_x.sql"]))
    kept = list(tmp_path.glob("bach.db.premig-*.bak"))
    assert len(kept) == core_db.MIGRATION_BACKUP_KEEP
    assert manual.exists()  # manuelle Sicherungen bleiben


def test_repeated_failing_migration_does_not_flood(tmp_path):
    schema = tmp_path / "schema"
    (schema / "migrations").mkdir(parents=True)
    (schema / "schema.sql").write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    (schema / "migrations" / "001_kaputt.sql").write_text("ALTER TABLE fehlt ADD COLUMN x;", encoding="utf-8")
    db = Database(tmp_path / "bach.db", schema)
    db.init_schema()
    for _ in range(20):  # 20 Starts hintereinander
        applied, error = db.run_migrations()
        assert applied == [] and "001_kaputt.sql" in error
    assert len(list(tmp_path.glob("bach.db.premig-*.bak"))) == 1


def test_app_starts_normally_when_backup_fails(tmp_path, monkeypatch, capsys):
    """App.db liefert die DB weiter, migriert aber nicht (fail-soft mit Warnung)."""
    import core.app as core_app
    import hub.bach_paths as bach_paths
    schema = SYSTEM_DIR / "data" / "schema"
    live = tmp_path / "bach.db"
    seed = Database(live, schema)
    seed.init_schema()
    seed.baseline_migrations()
    newest = sorted(p.name for p in (schema / "migrations").glob("*.*") if p.name[:3].isdigit())[-1]
    seed.execute_write("DELETE FROM _migrations WHERE filename = ?", (newest,))
    monkeypatch.setattr(bach_paths, "BACH_DB", live)
    monkeypatch.delenv(core_db.NO_AUTO_MIGRATE_ENV, raising=False)

    def fail(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(core_db, "backup_before_migration", fail)
    db = core_app.App(SYSTEM_DIR).db
    assert db is not None and db.table_exists("tasks")
    assert newest not in {r["filename"] for r in db.execute("SELECT filename FROM _migrations")}
    captured = capsys.readouterr()
    out = captured.out + captured.err  # Warnungen laufen seit der Partner-Scope-Aenderung ueber stderr
    assert "Sicherung vor Migration fehlgeschlagen" in out and "Migrationslauf unvollstaendig" in out


def _broken(tmp_path):
    schema = tmp_path / "schema"
    (schema / "migrations").mkdir(parents=True)
    (schema / "schema.sql").write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    (schema / "migrations" / "001_kaputt.sql").write_text("ALTER TABLE fehlt ADD COLUMN x;", encoding="utf-8")
    db = Database(tmp_path / "bach.db", schema)
    db.init_schema()
    return db


def test_repro_broken_migration_5_starts_is_capped(tmp_path, monkeypatch):
    """Repro Review #108: kaputte Migration 5x gestartet -> hoechstens N Sicherungen.

    Mit Wiederverwendungsfenster: genau 1. Ohne Fenster (jeder Start > 10 min
    auseinander, hier simuliert): gedeckelt auf MIGRATION_BACKUP_KEEP.
    """
    db = _broken(tmp_path)
    for _ in range(5):
        db.run_migrations()
    assert len(list(tmp_path.glob("bach.db.premig-*.bak"))) == 1
    monkeypatch.setattr(core_db, "MIGRATION_BACKUP_REUSE_SECONDS", 0)
    monkeypatch.setattr(core_db, "MIGRATION_BACKUP_KEEP", 3)
    for _ in range(5):
        db.run_migrations()
    assert len(list(tmp_path.glob("bach.db.premig-*.bak"))) == 3


def test_same_second_writes_distinct_files(tmp_path, monkeypatch):
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(core_db, "MIGRATION_BACKUP_REUSE_SECONDS", 0)

    class _Frozen(core_db.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 26, 21, 0, 0)

    monkeypatch.setattr(core_db, "datetime", _Frozen)
    a = core_db.backup_before_migration(db, ["001_a.sql"])
    b = core_db.backup_before_migration(db, ["001_a.sql"])
    assert a != b and a.exists() and b.exists()
    assert b.name.endswith("-2.bak")


def test_no_reuse_after_db_write(tmp_path):
    """Review #108 / team-lead: nach einer normalen Schreiboperation wird die
    juengere Sicherung NICHT wiederverwendet, sonst fehlte die Schreibung."""
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    first = core_db.backup_before_migration(db, ["001_a.sql"])
    assert core_db.backup_before_migration(db, ["001_a.sql"]) == first  # nichts geschrieben
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    later = first.stat().st_mtime + 2
    os.utime(db, (later, later))  # Dateisystem-Zeitaufloesung ueberbruecken
    second = core_db.backup_before_migration(db, ["001_a.sql"])
    assert second != first
    check = sqlite3.connect(second)
    assert check.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    check.close()


def test_wal_write_counts_as_db_write(tmp_path):
    db = tmp_path / "bach.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    first = core_db.backup_before_migration(db, ["001_a.sql"])
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()  # bleibt im WAL, Haupt-DB-mtime kann unveraendert sein
    wal = tmp_path / "bach.db-wal"
    assert wal.exists()
    later = first.stat().st_mtime + 2
    os.utime(wal, (later, later))
    assert core_db.backup_before_migration(db, ["001_a.sql"]) != first
    conn.close()




def test_read_only_wal_creation_is_bound_to_the_observed_empty_state(tmp_path):
    """The real read-only backup may create one empty WAL sidecar."""
    db_path = tmp_path / "reader.db"
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    conn.execute("CREATE TABLE t (value TEXT)")
    conn.execute("INSERT INTO t VALUES ('before')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    wal_path = tmp_path / "reader.db-wal"
    assert not wal_path.exists()
    before = core_db._migration_source_state(db_path)
    assert before["wal"] == {"present": False}

    backup = core_db.backup_before_migration(db_path, ["001_reader.sql"])
    after = core_db._migration_source_state(db_path)
    proof = __import__("json").loads(core_db._backup_proof_path(backup).read_text(encoding="utf-8"))

    assert after["db"] == before["db"]
    assert after["wal"]["present"] is True
    assert after["wal"]["size"] == 0
    assert after["wal"]["sha256"] == core_db.hashlib.sha256(b"").hexdigest()
    assert core_db._same_source_state_with_empty_wal_transition(before, after)
    assert proof["source_state"] == after
    assert proof["source_state_sha256"] == core_db._migration_source_state_sha256(after)
    assert core_db._valid_backup_pair(backup, ["001_reader.sql"], expected_source_state=after)



def test_reader_empty_wal_then_writer_absence_reuses_bound_backup(tmp_path):
    db_path = tmp_path / "reader-writer.db"
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    conn.execute("CREATE TABLE t (value TEXT)")
    conn.commit()
    conn.close()
    wal_path = tmp_path / "reader-writer.db-wal"
    assert not wal_path.exists()

    first = core_db.backup_before_migration(db_path, ["001_reader_writer.sql"])
    proof_path = core_db._backup_proof_path(first)
    proof_bytes = proof_path.read_bytes()
    proof = __import__("json").loads(proof_bytes)
    assert proof["source_state"]["wal"]["present"] is True
    assert proof["source_state"]["wal"]["size"] == 0

    writer = sqlite3.connect(db_path)
    assert writer.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    writer.commit()
    writer.close()
    current = core_db._migration_source_state(db_path)
    assert current["wal"] == {"present": False}
    assert current["db"] == proof["source_state"]["db"]

    second = core_db.backup_before_migration(db_path, ["001_reader_writer.sql"])
    assert second == first
    assert proof_path.read_bytes() == proof_bytes
    assert proof["source_state"] != current
    assert core_db._same_source_state_for_backup_reuse(proof["source_state"], current)

def test_nonempty_wal_change_never_reuses_backup(tmp_path):
    db_path = tmp_path / "wal-change.db"
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    first = core_db.backup_before_migration(db_path, ["001_wal.sql"])
    wal_path = tmp_path / "wal-change.db-wal"
    first_state = core_db._migration_source_state(db_path)
    assert first_state["wal"]["present"] and first_state["wal"]["size"] > 0

    conn.execute("INSERT INTO t VALUES (2)")
    conn.commit()
    changed_state = core_db._migration_source_state(db_path)
    assert changed_state["wal"]["size"] > 0
    assert changed_state["wal"]["sha256"] != first_state["wal"]["sha256"]

    second = core_db.backup_before_migration(db_path, ["001_wal.sql"])
    assert second != first
    proof = __import__("json").loads(core_db._backup_proof_path(second).read_text(encoding="utf-8"))
    assert proof["source_state"] == core_db._migration_source_state(db_path)
    backup_conn = sqlite3.connect(second)
    try:
        assert backup_conn.execute("SELECT value FROM t ORDER BY value").fetchall() == [(1,), (2,)]
    finally:
        backup_conn.close()
        conn.close()


def test_recreated_empty_wal_identity_never_reuses_backup(tmp_path):
    db_path = tmp_path / "wal-identity.db"
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    conn.execute("CREATE TABLE t (value TEXT)")
    conn.commit()
    conn.close()

    first = core_db.backup_before_migration(db_path, ["001_identity.sql"])
    wal_path = tmp_path / "wal-identity.db-wal"
    original = wal_path.stat()
    original_state = core_db._migration_source_state(db_path)
    assert original_state["wal"]["present"] and original_state["wal"]["size"] == 0

    held_fd = os.open(wal_path, os.O_RDONLY)
    try:
        wal_path.unlink()
        replacement = tmp_path / "replacement-wal"
        replacement.write_bytes(b"")
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        os.replace(replacement, wal_path)
        replacement_stat = wal_path.stat()
        assert replacement_stat.st_mtime_ns == original.st_mtime_ns
        assert os.fstat(held_fd).st_ino != replacement_stat.st_ino
        replacement_state = core_db._migration_source_state(db_path)
        assert replacement_state != original_state
        assert core_db._same_source_state_for_backup_reuse(original_state, replacement_state) is False

        second = core_db.backup_before_migration(db_path, ["001_identity.sql"])
        assert second != first
        accepted = core_db._migration_source_state(db_path)
        proof = __import__("json").loads(core_db._backup_proof_path(second).read_text(encoding="utf-8"))
        assert proof["source_state"] == accepted
    finally:
        os.close(held_fd)


def test_db_replacement_with_preserved_mtime_never_reuses_backup(tmp_path):
    db_path = tmp_path / "replace.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    first = core_db.backup_before_migration(db_path, ["001_replace.sql"])
    original_stat = db_path.stat()

    replacement = tmp_path / "replacement.db"
    conn = sqlite3.connect(replacement)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.execute("INSERT INTO t VALUES (2)")
    conn.commit()
    conn.close()
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    os.replace(replacement, db_path)
    assert db_path.stat().st_mtime_ns == original_stat.st_mtime_ns

    second = core_db.backup_before_migration(db_path, ["001_replace.sql"])
    assert second != first
    conn = sqlite3.connect(second)
    try:
        assert conn.execute("SELECT value FROM t").fetchall() == [(2,)]
    finally:
        conn.close()


def test_in_place_db_change_with_preserved_mtime_never_reuses_backup(tmp_path):
    db_path = tmp_path / "in-place.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    first = core_db.backup_before_migration(db_path, ["001_inplace.sql"])
    original_stat = db_path.stat()
    original_hash = core_db._migration_source_state(db_path)["db"]["sha256"]

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO t VALUES (2)")
    conn.commit()
    conn.close()
    os.utime(db_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert db_path.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert core_db._migration_source_state(db_path)["db"]["sha256"] != original_hash

    second = core_db.backup_before_migration(db_path, ["001_inplace.sql"])
    assert second != first
    conn = sqlite3.connect(second)
    try:
        assert conn.execute("SELECT value FROM t ORDER BY value").fetchall() == [(1,), (2,)]
    finally:
        conn.close()


def test_v1_proof_is_not_reused_or_rewritten(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.execute("INSERT INTO t VALUES (7)")
    conn.commit()
    conn.close()
    pending = ["001_legacy.sql"]
    key = core_db.hashlib.sha256("\n".join(pending).encode("utf-8")).hexdigest()[:8]
    old = tmp_path / f"legacy.db.premig-old-{key}-20261012-000000.bak"
    old_bytes = db_path.read_bytes()
    old_identity = core_db._create_private_file(old, old_bytes)
    proof_path = core_db._backup_proof_path(old)
    proof = {
        "schema": "bach.migration-backup-proof.v1",
        "backup_name": old.name,
        "pending": pending,
        "pending_sha256": core_db.hashlib.sha256("\n".join(pending).encode("utf-8")).hexdigest(),
        "backup_sha256": core_db._sha256_file(old),
        "created_at": "2026-10-12T00:00:00+00:00",
    }
    proof_bytes = __import__("json").dumps(proof, sort_keys=True, separators=(",", ":")).encode("utf-8")
    proof_identity = core_db._create_private_file(proof_path, proof_bytes)
    os.utime(old, None)
    os.utime(proof_path, None)
    source_state = core_db._migration_source_state(db_path)

    assert core_db._valid_backup_pair(old, pending, expected_source_state=source_state) is False
    assert core_db._valid_backup_pair(old, pending)
    second = core_db.backup_before_migration(db_path, pending)
    assert second != old
    assert old.read_bytes() == old_bytes
    assert proof_path.read_bytes() == proof_bytes
    assert core_db._file_object_identity(old.lstat()) == old_identity.file_identity
    assert core_db._file_object_identity(proof_path.lstat()) == proof_identity.file_identity


@pytest.mark.skipif(os.name != "nt", reason="Windows hard-link checks run on native Windows")
def test_windows_private_file_rejects_hardlinked_backup_artifacts(tmp_path):
    original = tmp_path / "private.bin"
    core_db._create_private_file(original, b"private")
    alias = tmp_path / "alias.bin"
    try:
        os.link(original, alias)
    except (OSError, NotImplementedError):
        pytest.skip("Hard links are unavailable in this Windows test environment")
    assert original.stat().st_nlink > 1
    assert core_db._windows_private_file_status(original) is False
    assert core_db._windows_private_file_status(alias) is False


def test_backup_copy_failure_cleans_its_private_target(tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        core_db.backup_before_migration(db_path, ["001_corrupt.sql"])
    assert not list(tmp_path.glob("corrupt.db.premig-*.bak"))
    assert not list(tmp_path.glob("corrupt.db.premig-*.bak.proof.json"))


def test_backup_quick_check_failure_cleans_its_private_target(tmp_path, monkeypatch):
    db_path = tmp_path / "quick-check.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(core_db, "_quick_check_backup", lambda _path: False)

    with pytest.raises(RuntimeError, match="quick_check"):
        core_db.backup_before_migration(db_path, ["001_quick.sql"])
    assert not list(tmp_path.glob("quick-check.db.premig-*.bak"))
    assert not list(tmp_path.glob("quick-check.db.premig-*.bak.proof.json"))


def test_proof_creation_failure_cleans_only_its_private_backup(tmp_path, monkeypatch):
    db_path = tmp_path / "proof-create.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.commit()
    conn.close()
    create = core_db._create_private_file

    def fail_proof(path, content=b""):
        if Path(path).name.endswith(".proof.json"):
            raise OSError("synthetic proof creation failure")
        return create(path, content)

    monkeypatch.setattr(core_db, "_create_private_file", fail_proof)
    with pytest.raises(OSError, match="synthetic proof creation failure"):
        core_db.backup_before_migration(db_path, ["001_proof.sql"])
    assert not list(tmp_path.glob("proof-create.db.premig-*.bak"))
    assert not list(tmp_path.glob("proof-create.db.premig-*.bak.proof.json"))


def test_proof_readback_failure_cleans_its_private_pair(tmp_path, monkeypatch):
    db_path = tmp_path / "proof-readback.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(core_db, "_valid_backup_pair", lambda *_args, **_kwargs: False)

    with pytest.raises(RuntimeError, match="Sicherungsnachweis"):
        core_db.backup_before_migration(db_path, ["001_readback.sql"])
    assert not list(tmp_path.glob("proof-readback.db.premig-*.bak"))
    assert not list(tmp_path.glob("proof-readback.db.premig-*.bak.proof.json"))


def test_cleanup_keeps_replaced_target_when_identity_is_unproven(tmp_path, monkeypatch):
    db_path = tmp_path / "replacement-target.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.commit()
    conn.close()
    moved = []

    def replace_then_fail(path):
        target = Path(path)
        preserved = target.with_name(target.name + ".preserved")
        os.replace(target, preserved)
        core_db._create_private_file(target, b"foreign replacement")
        moved.append(preserved)
        return False

    monkeypatch.setattr(core_db, "_quick_check_backup", replace_then_fail)
    with pytest.raises(RuntimeError, match="Identität erhalten"):
        core_db.backup_before_migration(db_path, ["001_replacement.sql"])

    assert len(moved) == 1 and moved[0].exists()
    replacements = list(tmp_path.glob("replacement-target.db.premig-*.bak"))
    assert len(replacements) == 1
    assert replacements[0].read_bytes() == b"foreign replacement"
    assert not list(tmp_path.glob("replacement-target.db.premig-*.bak.proof.json"))


def test_cleanup_removes_unchanged_created_private_file_by_recorded_state(tmp_path):
    target = tmp_path / "owned.bin"
    state = core_db._create_private_file(target, b"owned bytes")

    assert isinstance(state, core_db._CreatedPrivateFileState)
    assert state.sha256 == hashlib.sha256(b"owned bytes").hexdigest()
    assert core_db._cleanup_created_private_file(target, state) is True
    assert not target.exists()


def test_cleanup_preserves_in_place_changed_created_file(tmp_path):
    target = tmp_path / "changed-in-place.bin"
    original = b"created by this invocation"
    state = core_db._create_private_file(target, original)
    original_identity = state.file_identity

    target.write_bytes(b"foreign in-place contents")

    assert core_db._file_object_identity(target.lstat()) == original_identity
    assert core_db._cleanup_created_private_file(target, state) is False
    assert target.read_bytes() == b"foreign in-place contents"


@pytest.mark.skipif(os.name != "nt", reason="native handle deletion is Windows-specific")
def test_windows_cleanup_deletes_verified_owned_file_by_handle(tmp_path):
    target = tmp_path / "windows-owned.bin"
    state = core_db._create_private_file(target, b"owned bytes")

    assert core_db._cleanup_created_private_file(target, state) is True
    assert not os.path.lexists(str(target))


@pytest.mark.skipif(os.name != "nt", reason="Windows compares path and handle ctime semantics")
def test_windows_path_and_handle_identity_ignores_unstable_ctime(tmp_path):
    target = tmp_path / "windows-source.db"
    conn = sqlite3.connect(target)
    conn.execute("CREATE TABLE t (value INTEGER)")
    conn.commit()
    conn.close()

    path_stat = target.lstat()
    fd = os.open(str(target), os.O_RDONLY)
    try:
        handle_stat = os.fstat(fd)
        assert core_db._stat_identity(path_stat) == core_db._stat_identity(handle_stat)
        fingerprint = core_db._source_file_fingerprint(target, required=True)
        assert fingerprint["ctime_ns"] == target.lstat().st_ctime_ns
    finally:
        os.close(fd)



def _selection_fixture(tmp_path):
    schema = tmp_path / "schema"
    migrations = schema / "migrations"
    migrations.mkdir(parents=True)
    (schema / "schema.sql").write_text("CREATE TABLE base (id INTEGER);", encoding="utf-8")
    (migrations / "052_blueprint_template_provider.py").write_text(
        "def run_migration(conn):\n    conn.execute('CREATE TABLE py_052 (id INTEGER)')\n",
        encoding="utf-8",
    )
    (migrations / "052_blueprint_template_provider.sql").write_text(
        "CREATE TABLE sql_052 (id INTEGER);", encoding="utf-8"
    )
    (migrations / "053_resource_leases.sql").write_text(
        "CREATE TABLE sql_053 (id INTEGER);", encoding="utf-8"
    )
    (migrations / "migrate_unify_distribution.py").write_text(
        "def run_migration(conn):\n    conn.execute('CREATE TABLE unnumbered (id INTEGER)')\n",
        encoding="utf-8",
    )
    db = Database(tmp_path / "bach.db", schema)
    db.init_schema()
    return db, migrations


def _read_tables(path):
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()


def test_exact_selection_runs_only_canonical_052_and_053(tmp_path):
    db, _ = _selection_fixture(tmp_path)
    applied, error = db.run_migrations(only=[
        "052_blueprint_template_provider.sql",
        "053_resource_leases.sql",
    ])
    assert error is None
    assert applied == ["052_blueprint_template_provider.sql", "053_resource_leases.sql"]
    tables = _read_tables(db.db_path)
    assert "sql_052" in tables and "sql_053" in tables
    assert "py_052" not in tables and "unnumbered" not in tables
    assert core_db.read_applied_migration_filenames(db.db_path) == set(applied)


def test_exact_selection_executes_only_pinned_python_migration(tmp_path):
    db, _ = _selection_fixture(tmp_path)
    selected = "052_blueprint_template_provider.py"

    applied, error = db.run_migrations(only=[selected])

    assert error is None
    assert applied == [selected]
    tables = _read_tables(db.db_path)
    assert "py_052" in tables
    assert "sql_052" not in tables and "unnumbered" not in tables
    assert core_db.read_applied_migration_filenames(db.db_path) == {selected}


@pytest.mark.parametrize("selection", [
    ["../052_blueprint_template_provider.sql"],
    ["missing.sql"],
    ["052_blueprint_template_provider.sql", "052_blueprint_template_provider.sql"],
])
def test_invalid_selection_is_rejected_before_db_or_backup_write(tmp_path, selection):
    db, _migrations = _selection_fixture(tmp_path)
    before = db.db_path.read_bytes()
    applied, error = db.run_migrations(only=selection)
    assert applied == [] and "abgewiesen" in error
    assert db.db_path.read_bytes() == before
    assert not list(tmp_path.glob("bach.db.premig-*.bak"))
    assert "_migrations" not in _read_tables(db.db_path)


def test_already_applied_selection_is_rejected_without_writes(tmp_path):
    db, _migrations = _selection_fixture(tmp_path)
    conn = sqlite3.connect(db.db_path)
    conn.execute("CREATE TABLE _migrations (id INTEGER PRIMARY KEY, filename TEXT UNIQUE NOT NULL, applied_at TEXT NOT NULL)")
    conn.execute("INSERT INTO _migrations (filename, applied_at) VALUES (?, ?)",
                 ("052_blueprint_template_provider.sql", "2026-10-12T00:00:00"))
    conn.commit(); conn.close()
    before = db.db_path.read_bytes()
    applied, error = db.run_migrations(only=["052_blueprint_template_provider.sql"])
    assert applied == [] and "Bereits angewandte" in error
    assert db.db_path.read_bytes() == before
    assert not list(db.db_path.parent.glob("bach.db.premig-*.bak"))


def test_changed_source_aborts_before_backup_or_migration(tmp_path, monkeypatch):
    db, _ = _selection_fixture(tmp_path)
    original = core_db.snapshot_migration_sources
    backup_calls = []
    def mutate_after_snapshot(directory, names):
        result = original(directory, names)
        (Path(directory) / names[0]).write_text("CREATE TABLE changed (id INTEGER);", encoding="utf-8")
        return result
    monkeypatch.setattr(core_db, "snapshot_migration_sources", mutate_after_snapshot)
    monkeypatch.setattr(core_db, "backup_before_migration", lambda *args: backup_calls.append(args))
    before = db.db_path.read_bytes()
    applied, error = db.run_migrations(only=["052_blueprint_template_provider.sql"])
    assert applied == [] and "geändert" in error
    assert backup_calls == []
    assert db.db_path.read_bytes() == before
    assert "changed" not in _read_tables(db.db_path)


def test_symlink_selection_fails_closed_without_backup(tmp_path):
    db, migrations = _selection_fixture(tmp_path)
    target = migrations / "052_blueprint_template_provider.sql"
    link = migrations / "052_link.sql"
    try:
        link.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable in this test environment")
    before = db.db_path.read_bytes()
    applied, error = db.run_migrations(only=[link.name])
    assert applied == [] and "reguläre Datei" in error
    assert db.db_path.read_bytes() == before
    assert not list(db.db_path.parent.glob("bach.db.premig-*.bak"))


def test_backup_proof_and_permissions_are_required_for_reuse(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(db_path); conn.execute("CREATE TABLE t (id INTEGER)"); conn.commit(); conn.close()
    backup = core_db.backup_before_migration(db_path, ["052_exact.sql"])
    proof = core_db._backup_proof_path(backup)
    assert core_db._private_file_status(backup)
    assert core_db._private_file_status(proof)
    if os.name != "nt":
        assert (backup.stat().st_mode & 0o777) == 0o600
        assert (proof.stat().st_mode & 0o777) == 0o600
    data = __import__("json").loads(proof.read_text(encoding="utf-8"))
    data["backup_sha256"] = "0" * 64
    proof.write_text(__import__("json").dumps(data), encoding="utf-8")
    replacement = core_db.backup_before_migration(db_path, ["052_exact.sql"])
    assert replacement != backup
    assert backup.exists()  # unverifizierter Bestand bleibt unangetastet


@pytest.mark.skipif(os.name != "nt", reason="Native Windows DACL readback runs only on Windows")
def test_windows_backup_creation_proves_owner_and_protected_dacl(tmp_path):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()

    backup = core_db.backup_before_migration(db_path, ["052_exact.sql"])
    proof = core_db._backup_proof_path(backup)

    assert core_db._windows_private_file_status(backup)
    assert core_db._windows_private_file_status(proof)
    assert core_db._quick_check_backup(backup)


def test_retention_never_deletes_unverified_runner_looking_backup(tmp_path, monkeypatch):
    db_path = tmp_path / "bach.db"
    conn = sqlite3.connect(db_path); conn.execute("CREATE TABLE t (id INTEGER)"); conn.commit(); conn.close()
    foreign = tmp_path / "bach.db.premig-foreign-deadbeef-20200101-000000.bak"
    foreign.write_bytes(b"unverified foreign backup")
    monkeypatch.setattr(core_db, "MIGRATION_BACKUP_REUSE_SECONDS", 0)
    monkeypatch.setattr(core_db, "MIGRATION_BACKUP_KEEP", 2)
    for index in range(8):
        core_db.backup_before_migration(db_path, [f"{index:03d}_exact.sql"])
    own_backups = [p for p in tmp_path.glob("bach.db.premig-*.bak") if p != foreign]
    assert len(own_backups) == 2
    assert foreign.read_bytes() == b"unverified foreign backup"
