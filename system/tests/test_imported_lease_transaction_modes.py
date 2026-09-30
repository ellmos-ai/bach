import importlib.util
import pathlib
import socket
import sqlite3
import sys
import uuid
import pytest
from imported_capabilities.category_1_solved_wanted.leases import adapter_bach as m

@pytest.fixture(autouse=True)
def no_net(monkeypatch):
    def deny(*a, **k): raise AssertionError('No network')
    monkeypatch.setattr(socket.socket, 'connect', deny)

@pytest.fixture
def fixture_db(tmp_path):
    path = tmp_path / 'private.db'
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,status TEXT)')
    c.execute("INSERT INTO tasks VALUES(1,'pending')")
    c.commit()
    m.ensure_task_lease_schema(c)
    c.close()
    return path

def invoke(c, op, token):
    if op == 'schema': return m.ensure_task_lease_schema(c)
    if op == 'claim': return m.try_claim_task_atomic(c, 1, 'agent')
    if op == 'renew': return m.renew_task_lease(c, 1, token, 600)
    return m.release_task_lease(c, 1, token, 'done')

def seed(c, op):
    token = str(uuid.uuid4())
    if op in ('renew', 'release'):
        c.execute("UPDATE tasks SET status='in_progress',claim_id=?,claimed_by='old',claim_expires_at='2999-01-01 00:00:00'", (token,))
        c.commit()
    return token

@pytest.mark.parametrize('op', ['schema', 'claim', 'renew', 'release'])
def test_python312_autocommit_true_success_is_closed(fixture_db, op):
    c = sqlite3.connect(fixture_db, autocommit=True)
    try:
        token = seed(c, op)
        invoke(c, op, token)
        assert not c.in_transaction
        with sqlite3.connect(fixture_db) as reopened:
            assert reopened.execute('SELECT * FROM tasks').fetchall() == c.execute('SELECT * FROM tasks').fetchall()
    finally:
        if c.in_transaction: c.execute('ROLLBACK')
        c.close()

@pytest.mark.parametrize('op', ['claim', 'renew', 'release'])
def test_python312_autocommit_true_error_is_rolled_back(fixture_db, op):
    c = sqlite3.connect(fixture_db, autocommit=True)
    try:
        token = seed(c, op)
        c.execute("CREATE TRIGGER fail AFTER UPDATE ON tasks BEGIN SELECT RAISE(FAIL,'injected'); END")
        before = c.execute('SELECT * FROM tasks').fetchall()
        with pytest.raises(sqlite3.IntegrityError): invoke(c, op, token)
        assert (c.in_transaction, c.execute('SELECT * FROM tasks').fetchall()) == (False, before)
    finally:
        if c.in_transaction: c.execute('ROLLBACK')
        c.close()

class CommitFailure(sqlite3.Connection):
    remaining = None
    def commit(self):
        if self.remaining is not None:
            self.remaining -= 1
            if self.remaining == 0: raise sqlite3.OperationalError('commit injected')
        return super().commit()

@pytest.mark.parametrize('op', ['claim', 'renew', 'release'])
def test_commit_failure_restores_owned_transaction(fixture_db, op):
    c = sqlite3.connect(fixture_db, factory=CommitFailure)
    try:
        token = seed(c, op)
        before = c.execute('SELECT * FROM tasks').fetchall()
        c.remaining = 2 if op == 'claim' else 1
        with pytest.raises(sqlite3.OperationalError, match='commit injected'): invoke(c, op, token)
        assert (c.in_transaction, c.execute('SELECT * FROM tasks').fetchall()) == (False, before)
    finally: c.rollback(); c.close()
