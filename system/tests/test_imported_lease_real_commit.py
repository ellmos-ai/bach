import sqlite3
import pytest
from tests.test_imported_lease_transaction_modes import fixture_db, seed, invoke, m, no_net

@pytest.mark.parametrize('mode',['legacy','isolation_none','autocommit_true'])
@pytest.mark.parametrize('op',['claim','renew','release'])
def test_real_deferred_commit_failure(fixture_db,mode,op):
    opts={} if mode=='legacy' else ({'isolation_level':None} if mode=='isolation_none' else {'autocommit':True})
    c=sqlite3.connect(fixture_db,**opts)
    try:
        c.execute('PRAGMA foreign_keys=ON')
        token=seed(c,op)
        c.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE child(id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)')
        c.execute('CREATE TRIGGER invalid_child AFTER UPDATE ON tasks BEGIN INSERT INTO child VALUES(999); END')
        c.commit()
        before=c.execute('SELECT * FROM tasks').fetchall()
        with pytest.raises(sqlite3.IntegrityError,match='FOREIGN KEY constraint failed'):
            invoke(c,op,token)
        assert not c.in_transaction
        assert c.execute('SELECT * FROM tasks').fetchall()==before
        assert c.execute('SELECT * FROM child').fetchall()==[]
        with sqlite3.connect(fixture_db) as reopened:
            assert reopened.execute('SELECT * FROM tasks').fetchall()==before
    finally:
        if c.in_transaction:c.execute('ROLLBACK')
        c.close()

@pytest.mark.parametrize('mode',['legacy','isolation_none','autocommit_true'])
def test_partial_schema_rollback(tmp_path,mode):
    opts={} if mode=='legacy' else ({'isolation_level':None} if mode=='isolation_none' else {'autocommit':True})
    c=sqlite3.connect(tmp_path/'schema.db',**opts)
    try:
        c.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,status TEXT)')
        calls=[]
        def auth(action,*args):
            if action==sqlite3.SQLITE_ALTER_TABLE:
                calls.append(action)
                if len(calls)==2:return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        c.set_authorizer(auth)
        with pytest.raises(sqlite3.DatabaseError):m.ensure_task_lease_schema(c)
        c.set_authorizer(None)
        assert len(calls)==2 and not c.in_transaction
        assert [r[1] for r in c.execute('PRAGMA table_info(tasks)')]==['id','status']
    finally:
        c.set_authorizer(None)
        if c.in_transaction:c.execute('ROLLBACK')
        c.close()
