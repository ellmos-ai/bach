import importlib.util
import pathlib
import socket
import sqlite3
import sys
import uuid
import pytest

from imported_capabilities.category_1_solved_wanted.leases import adapter_bach as m
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
 def deny(*args,**kwargs):raise AssertionError('No network permitted')
 monkeypatch.setattr(socket.socket,'connect',deny)
@pytest.fixture
def db(tmp_path):
 c=sqlite3.connect(tmp_path/'only-temp.db')
 c.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,status TEXT)')
 c.execute("INSERT INTO tasks VALUES(1,'pending')");c.commit()
 m.ensure_task_lease_schema(c)
 try:yield c
 finally:c.rollback();c.close()
def seed(c,token,expiry,owner='agent'):
 c.execute("UPDATE tasks SET status='in_progress',claim_id=?,claimed_by=?,claim_expires_at=?,claim_host='local'",(token,owner,expiry));c.commit()

@pytest.mark.parametrize('expiry',['1','12:00:00','2000-02-30 00:00:00'])
def test_malformed_expiry_never_reclaimed(db,expiry):
 seed(db,str(uuid.uuid4()),expiry)
 assert not m.try_claim_task_atomic(db,1,'new').success

@pytest.mark.parametrize('operation',['renew','release'])
@pytest.mark.parametrize('token',['not-a-uuid','00000000-0000-0000-0000-000000000000'])
def test_invalid_stored_fence_never_authorizes(db,operation,token):
 seed(db,token,'2999-01-01 00:00:00')
 try:r=m.renew_task_lease(db,1,token) if operation=='renew' else m.release_task_lease(db,1,token,'done')
 except ValueError:r=False
 assert not r

@pytest.mark.parametrize('operation',['claim','renew','release'])
def test_owned_transaction_rolled_back_on_sql_failure(db,operation):
 claim=m.try_claim_task_atomic(db,1,'agent') if operation!='claim' else None
 before=db.execute('SELECT * FROM tasks').fetchall()
 db.execute("CREATE TRIGGER deliberate_fail AFTER UPDATE ON tasks BEGIN SELECT RAISE(FAIL,'injected'); END");db.commit()
 with pytest.raises(sqlite3.IntegrityError):
  if operation=='claim':m.try_claim_task_atomic(db,1,'agent')
  elif operation=='renew':m.renew_task_lease(db,1,claim.claim_id,600)
  else:m.release_task_lease(db,1,claim.claim_id,'done')
 state=db.execute('SELECT * FROM tasks').fetchall()
 assert (db.in_transaction,state)==(False,before)

@pytest.mark.parametrize('operation',['claim','renew','release','schema'])
def test_external_savepoint_preserved(db,operation):
 claim=m.try_claim_task_atomic(db,1,'agent')
 db.execute('SAVEPOINT caller');db.execute("UPDATE tasks SET claim_host='caller-change'")
 with pytest.raises(ValueError):
  if operation=='claim':m.try_claim_task_atomic(db,1,'other')
  elif operation=='renew':m.renew_task_lease(db,1,claim.claim_id)
  elif operation=='release':m.release_task_lease(db,1,claim.claim_id)
  else:m.ensure_task_lease_schema(db)
 assert db.in_transaction
 db.execute('ROLLBACK TO caller');db.execute('RELEASE caller')
 assert db.execute('SELECT claim_host FROM tasks').fetchone()[0]=='local'

@pytest.mark.parametrize('expiry,expected',[('2000-01-01T00:00:00+01:00',True),('2999-01-01T00:00:00-01:00',False),('2999-01-01T00:00:00+99:99',False)])
def test_timezone_expiry_control(db,expiry,expected):
 seed(db,str(uuid.uuid4()),expiry)
 assert m.try_claim_task_atomic(db,1,'new').success is expected
