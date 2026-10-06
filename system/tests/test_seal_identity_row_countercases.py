import sqlite3
import sys
from pathlib import Path
from contextlib import closing
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_seal_identity_row_contract import sandbox, seed, read_identity, NEW_HASH

@pytest.mark.parametrize("mode", [sqlite3.LEGACY_TRANSACTION_CONTROL, True, False])
def test_real_sqlite_modes_have_truthful_effect_and_preserve_caller(sandbox, monkeypatch, mode):
    seed(sandbox)
    before=sandbox.db.read_bytes()
    conn=sqlite3.connect(sandbox.db, autocommit=mode)
    monkeypatch.setattr(sandbox.handler, "_get_conn", lambda:conn)
    result=sandbox.handler._update_kernel_hash(NEW_HASH)
    if mode == sqlite3.LEGACY_TRANSACTION_CONTROL:
        assert result is True
        assert read_identity(sandbox)[0][1]["kernel_hash"] == NEW_HASH
    else:
        assert result is False
        assert sandbox.db.read_bytes() == before
        if mode is False:
            assert conn.in_transaction
            conn.execute("SELECT 1")
            conn.close()

@pytest.mark.parametrize("mode", [sqlite3.LEGACY_TRANSACTION_CONTROL, True, False])
def test_real_modes_keep_foreign_savepoint(sandbox, monkeypatch, mode):
    seed(sandbox)
    before=sandbox.db.read_bytes()
    conn=sqlite3.connect(sandbox.db, autocommit=mode)
    conn.execute("SAVEPOINT external")
    conn.execute("INSERT INTO caller_audit VALUES('pending')")
    monkeypatch.setattr(sandbox.handler,"_get_conn",lambda:conn)
    try:
        assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
        assert conn.in_transaction
        assert conn.execute("SELECT note FROM caller_audit").fetchall()==[("pending",)]
        assert sandbox.db.read_bytes()==before
        conn.execute("ROLLBACK TO external")
        conn.execute("RELEASE external")
    finally:conn.close()
    assert read_identity(sandbox)[0][1]["kernel_hash"]=="old-hash"
    with closing(sqlite3.connect(sandbox.db)) as observer: assert observer.execute("SELECT COUNT(*) FROM caller_audit").fetchone()==(0,)

@pytest.mark.parametrize("key", ["a'; DROP TABLE caller_audit;--", "a\x00b", " Ä identifier "])
def test_key_and_hash_are_parameters(sandbox,key):
    seed(sandbox,instance_id=key)
    before=read_identity(sandbox)[0][1]
    new="'; DELETE FROM instance_identity;--"
    assert sandbox.handler._update_kernel_hash(new) is True
    assert read_identity(sandbox)[0][1]=={**before,"kernel_hash":new,"seal_status":"intact"}
    with closing(sqlite3.connect(sandbox.db)) as conn: assert conn.execute("SELECT count(*) FROM caller_audit").fetchone()==(0,)

@pytest.mark.parametrize("mode", [sqlite3.LEGACY_TRANSACTION_CONTROL, True])
def test_deferred_commit_failure_is_no_effect_in_real_modes(sandbox, monkeypatch,mode):
    seed(sandbox)
    with closing(sqlite3.connect(sandbox.db)) as conn:
        conn.executescript("CREATE TABLE p(x PRIMARY KEY); CREATE TABLE c(x REFERENCES p(x) DEFERRABLE INITIALLY DEFERRED); CREATE TRIGGER fail AFTER UPDATE ON instance_identity BEGIN INSERT INTO c VALUES(new.kernel_hash); END;")
    before=sandbox.db.read_bytes()
    conn=sqlite3.connect(sandbox.db,autocommit=mode)
    conn.execute("PRAGMA foreign_keys=ON")
    monkeypatch.setattr(sandbox.handler,"_get_conn",lambda:conn)
    assert sandbox.handler._update_kernel_hash(NEW_HASH) is False
    assert sandbox.db.read_bytes()==before
