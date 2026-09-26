# -*- coding: utf-8 -*-
"""Sicherung vor jeder Migrationsrunde, keine Auto-Migration bei Lesebefehlen.

T-20260926-958264544: Jeder BACH-CLI-Start (sogar ``update migrations list``)
fuehrte ausstehende Migrationen ungefragt und ohne Sicherung aus (Laptop,
2026-09-26 20:09, 043+044).
"""
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
    out = capsys.readouterr().out
    assert "Sicherung vor Migration fehlgeschlagen" in out and "Migrationslauf unvollstaendig" in out
