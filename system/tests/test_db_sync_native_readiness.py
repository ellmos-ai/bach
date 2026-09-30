# SPDX-License-Identifier: MIT
"""T903 native preparation: actual schema0, explicit paths, no stale copies.

These fixtures prove a bounded schema.sql profile, not host schema freshness,
FTS credential coverage, shared parity or runtime activation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[1]
PACKAGE = "_t903_native_readiness_test"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", SYSTEM / "hub" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(tmp_path, monkeypatch):
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(SYSTEM / "hub")]
    monkeypatch.setitem(sys.modules, PACKAGE, package)
    paths = types.ModuleType(f"{PACKAGE}.bach_paths")
    paths.BACH_DB = tmp_path / "selected" / "native.db"
    paths.PROSYNC_TRANSIT_DIR = tmp_path / "transit"
    paths.LOCAL_BACH_DIR = tmp_path / "local-state"
    monkeypatch.setitem(sys.modules, paths.__name__, paths)
    base = types.ModuleType(f"{PACKAGE}.base")
    class Base:
        def __init__(self, root):
            self.base_path = root
            self._canonical_db = paths.BACH_DB
    base.BaseHandler = Base
    monkeypatch.setitem(sys.modules, base.__name__, base)
    calls = []
    provider = types.ModuleType(f"{PACKAGE}.transit_sync_provider")
    def factory(**kwargs):
        calls.append(kwargs)
    provider.create_external_engine_if_active = factory
    monkeypatch.setitem(sys.modules, provider.__name__, provider)
    readiness = _load("db_sync_readiness")
    module = _load("db_sync")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: pytest.fail("HOME accessed")))
    original = sqlite3.connect
    def connect(db, *args, **kwargs):
        text = str(db)
        if text != ":memory:":
            assert str(tmp_path) in text or tmp_path.as_uri() in text, "DB outside TEMP"
        return original(db, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(module.socket, "socket", lambda *a, **k: pytest.fail("network accessed"))
    yield types.SimpleNamespace(root=tmp_path, paths=paths, m=module, r=readiness, calls=calls)
    for name in (f"{PACKAGE}.db_sync", f"{PACKAGE}.db_sync_readiness"):
        sys.modules.pop(name, None)


def _canonical(env, *, metadata=False):
    db = env.paths.BACH_DB
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript((SYSTEM / "data/schema/schema.sql").read_text(encoding="utf-8"))
        if metadata:
            conn.execute(env.r.MIGRATIONS_DDL)
            conn.execute("INSERT INTO _migrations(filename,applied_at) VALUES ('stamp-only.sql','synthetic')")
        conn.execute("INSERT INTO memory_facts(category,key,value) VALUES ('system','äöü','Größe')")
        conn.commit()
        assert conn.execute("PRAGMA user_version").fetchone() == (0,)
    finally:
        conn.close()
    return db


def _manager(env):
    return env.m.DBSyncManager(db_path=env.paths.BACH_DB, transit_dir=env.paths.PROSYNC_TRANSIT_DIR)


def _tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("metadata", [False, True])
def test_real_source_schema0_ready_readonly(env, metadata):
    db = _canonical(env, metadata=metadata)
    before = _tree(env.root)
    result = env.r.validate_native_db(db)
    assert result.ready and result.profile == "bach-schema-sql-v1"
    assert _tree(env.root) == before
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (0,)


def test_constructor_explicit_no_home_no_mkdir(env):
    before = _tree(env.root)
    m = _manager(env)
    assert m.db_path == env.paths.BACH_DB
    assert _tree(env.root) == before
    assert not env.paths.PROSYNC_TRANSIT_DIR.exists()
    assert not env.paths.LOCAL_BACH_DIR.exists()


def test_ensure_uses_actual_explicit_path(env):
    _canonical(env)
    m = _manager(env)
    m.local_bach_dir = env.root / "different-state-parent"
    before = _tree(env.root)
    assert m.ensure_local_db()
    assert _tree(env.root) == before
    assert not m.local_bach_dir.exists()


def test_stale_source_never_initializes(env):
    m = _manager(env)
    m.base_path = env.root / "stale-system"
    source = m.base_path / "data/bach.db"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"PRIVATE STALE SENTINEL")
    before = _tree(env.root)
    assert not m.ensure_local_db()
    assert _tree(env.root) == before
    assert not env.paths.BACH_DB.exists()


@pytest.mark.parametrize("method", ["sync_on_start", "sync_on_exit", "sync"])
def test_missing_precedes_engine_heartbeat_state(env, method):
    m = _manager(env)
    before = _tree(env.root)
    ok, message = getattr(m, method)()
    assert ok is False and "bereit" in message.lower()
    assert env.calls == []
    assert _tree(env.root) == before


@pytest.mark.parametrize("method", ["create_backup", "create_backup_if_needed", "cleanup_old_backups"])
def test_direct_mutating_methods_refuse_missing(env, method):
    m = _manager(env)
    before = _tree(env.root)
    with pytest.raises(env.r.DBSyncReadinessError):
        getattr(m, method)()
    assert _tree(env.root) == before and env.calls == []


def test_direct_merge_never_first_copies(env):
    remote = env.root / "remote.bachdb"
    with sqlite3.connect(str(remote)) as conn:
        conn.execute("CREATE TABLE sentinels(value)")
        conn.execute("INSERT INTO sentinels VALUES ('foreign')")
    m = _manager(env)
    before = _tree(env.root)
    with pytest.raises(env.r.DBSyncReadinessError):
        m.merge_backup(remote)
    assert _tree(env.root) == before


@pytest.mark.parametrize("mutation", ["empty", "bytes", "partial", "table", "view", "trigger", "index", "column", "version1", "generated", "fts"])
def test_unknown_or_stale_shapes_refused_unchanged(env, mutation):
    db = _canonical(env)
    if mutation in ("empty", "bytes"):
        db.write_bytes(b"" if mutation == "empty" else b"not SQLite")
    else:
        statements = {
            "partial": "DROP TABLE secrets", "table": "CREATE TABLE alien(id)",
            "view": "CREATE VIEW alien AS SELECT 1", "trigger": "DROP TRIGGER trg_memory_facts_session_provenance_insert",
            "index": "DROP INDEX idx_tasks_due_date", "column": "ALTER TABLE tasks ADD COLUMN alien TEXT",
            "version1": "PRAGMA user_version=1", "generated": "CREATE TABLE alien(v TEXT,n TEXT GENERATED ALWAYS AS (v) STORED)",
            "fts": "CREATE VIRTUAL TABLE alien USING fts5(v)",
        }
        with sqlite3.connect(str(db)) as conn:
            conn.execute(statements[mutation])
    before = _tree(env.root)
    assert not env.r.validate_native_db(db).ready
    assert _tree(env.root) == before


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_literal_sidecars_refused_no_recovery(env, suffix):
    db = _canonical(env)
    target = db.with_name("native[1].db")
    db.rename(target)
    target.with_name(target.name + suffix).write_bytes(b"SIDECAR SENTINEL")
    before = _tree(env.root)
    assert not env.r.validate_native_db(target).ready
    assert _tree(env.root) == before


def test_hash_bound_source_refusal(env):
    db = _canonical(env)
    source = env.root / "schema.sql"
    source.write_text("CREATE TABLE tasks(id);", encoding="utf-8")
    assert env.r.validate_native_db(db, schema_path=source).reason == "schema-source-pin-mismatch"


def test_source_read_error_refused(env):
    db = _canonical(env)
    assert not env.r.validate_native_db(db, schema_path=env.root / "missing").ready


def test_hardlink_refused(env):
    db = _canonical(env)
    alias = env.root / "alias.db"
    alias.hardlink_to(db)
    before = _tree(env.root)
    assert not env.r.validate_native_db(db).ready
    assert _tree(env.root) == before


def test_changed_during_read_refused(env, monkeypatch):
    db = _canonical(env)
    original = env.r._file_state
    calls = []
    def state(path):
        value = original(path)
        calls.append(value)
        return value if len(calls) == 1 else (*value[:-1], value[-1] + 1)
    monkeypatch.setattr(env.r, "_file_state", state)
    assert env.r.validate_native_db(db).reason == "database-changed"


@pytest.mark.parametrize("operation", ["backup", "push", "pull", "sync", "init", "cleanup", "enable", "disable"])
def test_native_dry_run_no_mkdir_marker_provider(env, operation):
    _canonical(env)
    h = env.m.DBSyncHandler(env.root / "system")
    before = _tree(env.root)
    ok, message = h.handle(operation, [], dry_run=True)
    assert ok and "dry-run" in message.lower()
    assert _tree(env.root) == before and env.calls == []
    assert not env.paths.PROSYNC_TRANSIT_DIR.exists()


def test_enable_missing_db_refuses_without_marker(env):
    h = env.m.DBSyncHandler(env.root / "system")
    before = _tree(env.root)
    ok, _ = h.handle("enable", [])
    assert not ok and _tree(env.root) == before and env.calls == []


def test_status_refusal_remains_readonly(env):
    m = _manager(env)
    before = _tree(env.root)
    assert "bereit" in m.get_status().lower()
    assert _tree(env.root) == before and env.calls == []


def test_init_reports_explicit_path(env):
    _canonical(env)
    h = env.m.DBSyncHandler(env.root / "system")
    before = _tree(env.root)
    ok, message = h.handle("init", [])
    assert ok and str(env.paths.BACH_DB) in message
    assert _tree(env.root) == before and env.calls == []


def test_actual_wal_with_writer_refused_without_touch(env):
    db = _canonical(env)
    writer = sqlite3.connect(str(db))
    try:
        writer.execute("INSERT INTO memory_facts(category,key,value) VALUES ('system','WAL','sentinel')")
        writer.commit()
        assert db.with_name(db.name + "-wal").exists()
        before = _tree(env.root)
        assert not env.r.validate_native_db(db).ready
        assert _tree(env.root) == before
    finally:
        writer.close()


@pytest.mark.parametrize("operation", ["backup", "push", "pull", "sync", "init", "cleanup", "enable"])
def test_missing_dryrun_before_all_preparation(env, operation):
    h = env.m.DBSyncHandler(env.root / "system")
    ok, _ = h.handle(operation, [], dry_run=True)
    assert not ok and env.calls == [] and _tree(env.root) == {}
    assert not env.paths.PROSYNC_TRANSIT_DIR.exists()
    assert not env.paths.LOCAL_BACH_DIR.exists()


@pytest.mark.parametrize("method", ["find_newer_backups", "_update_heartbeat", "_get_external_engine"])
def test_direct_internal_write_boundary_missing(env, method):
    m = _manager(env)
    with pytest.raises(env.r.DBSyncReadinessError):
        getattr(m, method)()
    assert env.calls == [] and _tree(env.root) == {}


def test_apply_actual_native_backup_preserves_source(env):
    db = _canonical(env)
    m = _manager(env)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    path = m.create_backup()
    assert path.is_file() and m.heartbeat_file.is_file()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    with sqlite3.connect(str(path)) as conn:
        assert conn.execute("SELECT value FROM memory_facts WHERE key='äöü'").fetchone() == ("Größe",)
        assert conn.execute("PRAGMA user_version").fetchone() == (0,)


def test_apply_enable_disable_no_database_creation(env):
    _canonical(env)
    h = env.m.DBSyncHandler(env.root / "system")
    ok, _ = h.handle("enable", [])
    marker = h.base_path / "data/config/db_sync_enabled"
    assert ok and marker.read_text() == "enabled"
    ok, _ = h.handle("disable", [])
    assert ok and not marker.exists() and env.calls == []


def test_valid_selection_precedes_provider_pull(env):
    _canonical(env)
    m = _manager(env)
    class Engine:
        def pull(self):
            return 0, []
    provider = sys.modules[f"{PACKAGE}.transit_sync_provider"]
    def factory(**kwargs):
        assert kwargs['db_path'] == env.paths.BACH_DB
        assert m.ensure_local_db()
        env.calls.append(kwargs)
        return Engine()
    provider.create_external_engine_if_active = factory
    ok, _ = m.sync_on_start()
    assert ok and len(env.calls) == 1 and m.heartbeat_file.exists()


def test_missing_db_not_masked_by_existing_default(env):
    db = _canonical(env)
    m = _manager(env)
    m.db_path = env.root / "missing-selected.db"
    before = _tree(env.root)
    assert not m.ensure_local_db() and db.exists()
    assert _tree(env.root) == before


def test_actual_retention_read_creates_no_wal_or_connection_leak(env):
    db = _canonical(env)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT INTO system_config(key,value) VALUES ('backup_retention_days','17')")
    conn.close()
    m = _manager(env)
    before = _tree(env.root)
    assert m._get_retention_days() == 17
    assert m.ensure_local_db() and _tree(env.root) == before


def test_accepted_identity_epoch_not_silently_profiled(env):
    db = _canonical(env)
    conn = sqlite3.connect(str(db))
    conn.execute("ALTER TABLE instance_identity DROP COLUMN current_mode")
    conn.commit()
    conn.close()
    before = _tree(env.root)
    result = env.r.validate_native_db(db)
    assert not result.ready and result.reason == "unsupported-schema-shape"
    assert _tree(env.root) == before


def test_readiness_is_not_credential_clearance(env):
    db = _canonical(env)
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO secrets(key,value) VALUES ('synthetic','sk-proj-FAKE_TEST_ONLY_SENTINEL')")
    conn.commit()
    conn.close()
    before = _tree(env.root)
    assert env.r.validate_native_db(db).ready  # structure only, never sync/backup approval
    assert _tree(env.root) == before and env.calls == []


def test_sql_read_failure_is_refusal(env, monkeypatch):
    db = _canonical(env)
    def broken(_conn):
        raise sqlite3.DatabaseError("PRIVATE_ERROR_MUST_NOT_BE_EXPOSED")
    monkeypatch.setattr(env.r, "_structure", broken)
    result = env.r.validate_native_db(db)
    assert not result.ready and "PRIVATE" not in result.reason


def test_relative_path_refused(env):
    assert env.r.validate_native_db(Path("bach.db")).reason == "absolute-db-path-required"


def test_linked_path_refused_before_sqlite(env, monkeypatch):
    db = _canonical(env)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == db.parent or original(p))
    before = _tree(env.root)
    assert env.r.validate_native_db(db).reason == "linked-path"
    assert _tree(env.root) == before


@pytest.mark.parametrize("operation", ["backup", "merge"])
def test_file_removed_after_readiness_not_recreated(env, monkeypatch, operation):
    db = _canonical(env)
    m = _manager(env)
    remote = env.root / "remote.bachdb"
    remote.write_bytes(db.read_bytes())
    prepare = m._prepare_io
    def remove_after_preparation():
        prepare()
        db.unlink()
    monkeypatch.setattr(m, "_prepare_io", remove_after_preparation)
    with pytest.raises(sqlite3.OperationalError):
        m.create_backup() if operation == "backup" else m.merge_backup(remote)
    assert not db.exists() and not m.heartbeat_file.exists()
