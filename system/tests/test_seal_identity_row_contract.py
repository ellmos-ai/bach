"""T211214113: real handler/identity writer, synthetic private SQLite only."""
import importlib.util
import re
import socket
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SYSTEM = Path(__file__).resolve().parents[1]
NEW_HASH = "ab" * 32


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "fixture"
    data = root / "data"
    data.mkdir(parents=True)
    db = data / "bach.db"
    original_connect = sqlite3.connect

    def no_home(cls):
        raise AssertionError("HOME access forbidden")

    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden")

    def guarded_connect(database, *args, **kwargs):
        path = Path(database).resolve()
        assert root.resolve() in path.parents, "non-fixture DB access"
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(Path, "home", classmethod(no_home))
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    package = ModuleType("_seal_identity_contract")
    package.__path__ = [str(SYSTEM / "hub")]
    paths = ModuleType("_seal_identity_contract.bach_paths")
    paths.BACH_DB = db
    with monkeypatch.context() as scope:
        scope.setitem(sys.modules, package.__name__, package)
        scope.setitem(sys.modules, paths.__name__, paths)
        seal = load_module(package.__name__ + ".seal", SYSTEM / "hub/seal.py")
    schema = (SYSTEM / "data/schema/schema_distribution.sql").read_text(encoding="utf-8")
    statement = re.search(r"CREATE TABLE IF NOT EXISTS instance_identity\s*\(.*?\);", schema, re.DOTALL)
    assert statement is not None
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(statement.group(0))
        conn.execute("CREATE TABLE caller_audit(note TEXT)")
        conn.commit()
    handler = seal.SealHandler(root)
    assert handler.db_path == db

    def writer():
        hub = ModuleType("hub")
        hub.__path__ = []
        provider = ModuleType("hub.bach_paths")
        provider.BACH_DB, provider.BACH_ROOT, provider.DATA_DIR = db, root, data
        with monkeypatch.context() as scope:
            scope.setitem(sys.modules, "hub", hub)
            scope.setitem(sys.modules, "hub.bach_paths", provider)
            module = load_module("_distribution_identity_contract", SYSTEM / "tools/distribution.py")
            return module.DistributionManager(db_path=db, root_path=root)

    return SimpleNamespace(root=root, db=db, handler=handler, writer=writer)


def seed(env, instance_id="fixture-nöde", legacy=False, kernel="old-hash"):
    with closing(sqlite3.connect(env.db)) as conn:
        if legacy:
            conn.execute("ALTER TABLE instance_identity ADD COLUMN current_mode TEXT DEFAULT 'developer'")
        conn.execute("""
            INSERT INTO instance_identity(instance_id,instance_name,created,forked_from,
                seal_status,seal_broken_at,seal_broken_by,seal_broken_reason,
                kernel_hash,kernel_version,seal_last_verified,base_release,base_release_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (instance_id, "Größe äöü", "fixture-created", "parent", "changed", "broken-at",
              "owner", "reason", kernel, "version", "verified", "release", "release-date"))
        conn.commit()


def read_identity(env):
    with closing(sqlite3.connect(env.db)) as conn:
        names = [r[1] for r in conn.execute("PRAGMA table_info(instance_identity)")]
        rows = conn.execute("SELECT rowid,* FROM instance_identity ORDER BY rowid").fetchall()
    return [(row[0], dict(zip(names, row[1:]))) for row in rows]


def identity_json(values):
    return {
        "instance": {"id": values["instance_id"], "name": values["instance_name"],
                     "created": values["created"], "forked_from": values["forked_from"]},
        "seal": {"status": values["seal_status"], "broken_at": values["seal_broken_at"],
                 "broken_by": values["seal_broken_by"], "broken_reason": values["seal_broken_reason"],
                 "kernel_hash": values["kernel_hash"], "kernel_version": values["kernel_version"],
                 "last_verified": values["seal_last_verified"]},
        "origin": {"release": values["base_release"], "release_date": values["base_release_date"]},
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_actual_identity_replace_then_seal_changes_real_target_and_commits(sandbox, legacy):
    seed(sandbox, legacy=legacy)
    original = read_identity(sandbox)[0][1]
    sandbox.writer()._save_identity_to_db(identity_json(original))
    before = read_identity(sandbox)
    assert before[0][0] == 2  # Real INSERT OR REPLACE, not a fabricated rowid.
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is True
    after = read_identity(sandbox)  # Independent reopen observes committed effect.
    assert after[0][0] == 2
    assert after[0][1] == {**before[0][1], "kernel_hash": NEW_HASH, "seal_status": "intact"}


@pytest.mark.parametrize("rowid", [1, 19])
@pytest.mark.parametrize("kernel", [None, "old-hash", NEW_HASH])
def test_single_valid_identity_at_any_rowid_preserves_non_target_values(sandbox, rowid, kernel):
    seed(sandbox, kernel=kernel)
    with closing(sqlite3.connect(sandbox.db)) as conn:
        conn.execute("UPDATE instance_identity SET rowid=?", (rowid,))
        conn.commit()
    before = read_identity(sandbox)
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is True
    assert read_identity(sandbox) == [(rowid, {**before[0][1], "kernel_hash": NEW_HASH, "seal_status": "intact"})]


@pytest.mark.parametrize("shape", ["empty", "multiple", "null-id", "empty-id", "blank-id", "blob-id", "two-null-ids"])
def test_missing_or_ambiguous_identity_refused_without_mutation(sandbox, shape):
    if shape != "empty":
        seed(sandbox, instance_id={"null-id": None, "empty-id": "", "blank-id": "  ", "blob-id": b"blob", "two-null-ids": None}.get(shape, "one"))
    if shape in ("multiple", "two-null-ids"):
        seed(sandbox, instance_id="two" if shape == "multiple" else None)
    before = sandbox.db.read_bytes()
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
    assert sandbox.db.read_bytes() == before


@pytest.mark.parametrize("invalid", [None, "", "   ", 123, b"hash"])
def test_invalid_new_hash_refused_without_mutation(sandbox, invalid):
    seed(sandbox)
    before = sandbox.db.read_bytes()
    assert sandbox.handler._update_kernel_hash(invalid) is False
    assert sandbox.db.read_bytes() == before


def test_missing_db_is_not_created(sandbox):
    sandbox.handler.db_path = sandbox.root / "missing.db"
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
    assert not sandbox.handler.db_path.exists()


@pytest.mark.parametrize("trigger", [
    "CREATE TRIGGER guard BEFORE UPDATE ON instance_identity BEGIN SELECT RAISE(IGNORE); END",
    "CREATE TRIGGER guard AFTER UPDATE ON instance_identity BEGIN UPDATE instance_identity SET kernel_hash='wrong'; END",
    "CREATE TRIGGER guard AFTER UPDATE ON instance_identity BEGIN UPDATE instance_identity SET instance_name='corrupt'; END",
    "CREATE TRIGGER guard AFTER UPDATE ON instance_identity BEGIN DELETE FROM instance_identity; END",
    "CREATE TRIGGER guard AFTER UPDATE ON instance_identity BEGIN INSERT INTO instance_identity(instance_id,instance_name) VALUES('other','other'); END",
])
def test_no_effect_or_trigger_corruption_rolls_back_and_returns_false(sandbox, trigger):
    seed(sandbox)
    with closing(sqlite3.connect(sandbox.db)) as conn:
        conn.execute(trigger)
        conn.commit()
    before = sandbox.db.read_bytes()
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
    assert sandbox.db.read_bytes() == before


def test_real_deferred_commit_failure_rolls_back(sandbox, monkeypatch):
    seed(sandbox)
    with closing(sqlite3.connect(sandbox.db)) as conn:
        conn.executescript("""
            CREATE TABLE parent_hash(value TEXT PRIMARY KEY);
            CREATE TABLE deferred_hash(value TEXT REFERENCES parent_hash(value) DEFERRABLE INITIALLY DEFERRED);
            CREATE TRIGGER commit_guard AFTER UPDATE ON instance_identity
                BEGIN INSERT INTO deferred_hash VALUES(new.kernel_hash); END;
        """)
    before = sandbox.db.read_bytes()

    def connection():
        conn = sqlite3.connect(sandbox.db)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    monkeypatch.setattr(sandbox.handler, "_get_conn", connection)
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
    assert sandbox.db.read_bytes() == before
    with closing(sqlite3.connect(sandbox.db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM deferred_hash").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["raise", "no-acknowledgement"])
def test_commit_failure_or_noncommit_never_claims_success(sandbox, monkeypatch, failure):
    seed(sandbox)
    before = sandbox.db.read_bytes()
    closed = []

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            if failure == "raise":
                raise sqlite3.OperationalError("injected commit failure")
            # Deliberately omit the actual commit; in_transaction stays true.

        def close(self):
            closed.append(True)
            super().close()

    monkeypatch.setattr(sandbox.handler, "_get_conn", lambda: sqlite3.connect(sandbox.db, factory=FailedCommit))
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
    assert closed == [True]
    assert sandbox.db.read_bytes() == before


def test_missing_identity_table_refused_and_connection_closed(sandbox, monkeypatch):
    with closing(sqlite3.connect(sandbox.db)) as conn:
        conn.execute("DROP TABLE instance_identity")
        conn.commit()
    before = sandbox.db.read_bytes()
    closed = []

    class ObservedConnection(sqlite3.Connection):
        def close(self):
            closed.append(True)
            super().close()

    monkeypatch.setattr(sandbox.handler, "_get_conn", lambda: sqlite3.connect(sandbox.db, factory=ObservedConnection))
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
    assert closed == [True]
    assert sandbox.db.read_bytes() == before


def test_temp_identity_cannot_redirect_main_identity_update(sandbox, monkeypatch):
    seed(sandbox)
    conn = sqlite3.connect(sandbox.db)
    conn.execute("CREATE TEMP TABLE instance_identity(instance_id TEXT,kernel_hash TEXT,seal_status TEXT)")
    conn.execute("INSERT INTO temp.instance_identity VALUES('shadow','keep','keep')")
    conn.commit()

    class ConnectionProxy:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            pass  # Inspect both schemas after the handler's owned transaction.

    monkeypatch.setattr(sandbox.handler, "_get_conn", ConnectionProxy)
    try:
        assert sandbox.handler._update_kernel_hash(NEW_HASH) is True
        assert conn.execute("SELECT * FROM temp.instance_identity").fetchall() == [("shadow", "keep", "keep")]
        assert read_identity(sandbox)[0][1]["kernel_hash"] == NEW_HASH
    finally:
        conn.close()


def test_active_caller_transaction_is_not_committed_rolled_back_or_closed(sandbox, monkeypatch):
    seed(sandbox)
    before = sandbox.db.read_bytes()
    conn = sqlite3.connect(sandbox.db)
    conn.execute("INSERT INTO caller_audit VALUES('outer-pending')")
    monkeypatch.setattr(sandbox.handler, "_get_conn", lambda: conn)
    try:
        assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
        assert conn.in_transaction is True
        assert conn.execute("SELECT note FROM caller_audit").fetchall() == [("outer-pending",)]
        assert conn.execute("SELECT kernel_hash,seal_status FROM instance_identity").fetchone() == ("old-hash", "changed")
        with closing(sqlite3.connect(sandbox.db)) as observer:
            assert observer.execute("SELECT COUNT(*) FROM caller_audit").fetchone()[0] == 0
        conn.rollback()
    finally:
        conn.close()
    assert sandbox.db.read_bytes() == before


def test_identity_selection_is_protected_against_second_writer(sandbox, monkeypatch):
    seed(sandbox)
    blocked = []

    class ContendedConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            cursor = super().execute(sql, *args)
            if "SELECT * FROM main.instance_identity" in sql:
                with closing(sqlite3.connect(sandbox.db, timeout=0)) as contender:
                    try:
                        contender.execute("INSERT INTO instance_identity(instance_id,instance_name) VALUES('race','race')")
                        contender.commit()
                    except sqlite3.OperationalError as exc:
                        blocked.append(str(exc))
            return cursor

    monkeypatch.setattr(sandbox.handler, "_get_conn", lambda: sqlite3.connect(sandbox.db, factory=ContendedConnection))
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is True
    assert blocked and all("locked" in message for message in blocked)
    assert len(read_identity(sandbox)) == 1


def test_existing_repair_caller_reports_failed_or_committed_effect(sandbox, monkeypatch, capsys):
    seed(sandbox)
    monkeypatch.setattr(sandbox.handler, "_calculate_kernel_hash", lambda: (NEW_HASH, 1, 0))
    assert sandbox.handler.repair() == 0
    assert read_identity(sandbox)[0][1]["kernel_hash"] == NEW_HASH
    seed(sandbox, instance_id="second")
    before = sandbox.db.read_bytes()
    assert sandbox.handler.repair() == 1
    assert sandbox.db.read_bytes() == before
    assert "Konnte Hash nicht" in capsys.readouterr().out
