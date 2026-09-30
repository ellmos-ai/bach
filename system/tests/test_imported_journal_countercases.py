import importlib
import pathlib
import socket
import sys
from contextlib import contextmanager
import pytest
base='imported_capabilities.category_2_superior_solutions.action_journal'
a=importlib.import_module(base+'.adapter_bach')
core=importlib.import_module(base+'.action_journal')
smart=importlib.import_module(base+'.smart_inbox')

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
 def deny(*args,**kwargs):raise AssertionError('network forbidden')
 monkeypatch.setattr(socket.socket,'connect',deny)

@pytest.mark.parametrize('operation',['forward-move','undo-move','undo-copy'])
def test_lost_guard_during_final_hash_prevents_resource_mutation(tmp_path,monkeypatch,operation):
 owned=[True]
 @contextmanager
 def guard(paths):
  assert all(p.is_relative_to(tmp_path) for p in paths)
  yield lambda:owned[0]
 src=tmp_path/'src';target=tmp_path/'target';src.write_bytes(b'private fixture')
 j=a.BachActionJournal(tmp_path/'journal','run',allowed_roots=(tmp_path,),mutation_guard=guard)
 if operation.startswith('undo'):
  j.execute_actions([a.FileActionStep(operation.split('-')[1],str(src),str(target))])
 before={p:p.read_bytes() if p.exists() else None for p in (src,target)}
 # Ownership expires while the final content check is reading an existing file.
 # The real unchanged hash function and actual rename/unlink remain in use.
 module=core if operation=='undo-copy' else smart
 original=module.file_sha256
 def expiring_hash(path):
  result=original(path)
  owned[0]=False
  return result
 monkeypatch.setattr(module,'file_sha256',expiring_hash)
 with pytest.raises(PermissionError):
  if operation=='forward-move':j.execute_actions([a.FileActionStep('move',str(src),str(target))])
  else:j.rollback()
 after={p:p.read_bytes() if p.exists() else None for p in (src,target)}
 assert after==before,'resource changed after host lease became invalid'
