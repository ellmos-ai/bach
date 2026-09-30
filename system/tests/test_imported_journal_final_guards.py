import os
from contextlib import contextmanager
import pytest
from tests.test_imported_journal_countercases import a, smart, core, no_network

@pytest.mark.parametrize('mode',['none','exception'])
@pytest.mark.parametrize('operation',['forward-move','undo-move','undo-copy'])
def test_final_hash_nontrue_guard_preserves_resources(tmp_path,monkeypatch,mode,operation):
    active=[True]
    @contextmanager
    def lease(paths):
        def check():
            if active[0]:return True
            if mode=='exception':raise RuntimeError('checker unavailable')
            return None
        yield check
    src,out=tmp_path/'src',tmp_path/'out';src.write_bytes(b'payload')
    j=a.BachActionJournal(tmp_path/'journal','run',allowed_roots=(tmp_path,),mutation_guard=lease)
    if operation.startswith('undo'):j.execute_actions([a.FileActionStep(operation.split('-')[1],str(src),str(out))])
    before={p:p.read_bytes() if p.exists() else None for p in (src,out)}
    mod=core if operation=='undo-copy' else smart
    orig=mod.file_sha256
    def expire(p):
        result=orig(p);active[0]=False;return result
    monkeypatch.setattr(mod,'file_sha256',expire)
    with pytest.raises((RuntimeError,PermissionError)):
        if operation.startswith('undo'):j.rollback()
        else:j.execute_actions([a.FileActionStep('move',str(src),str(out))])
    assert {p:p.read_bytes() if p.exists() else None for p in before}==before
    assert not j._fds and not j._streams and not j._entry_lock.locked()

def test_revocation_after_mkstemp_closes_real_fd(tmp_path,monkeypatch):
    active=[True];fds=[]
    @contextmanager
    def lease(paths):yield lambda:active[0]
    original=a.tempfile.mkstemp
    def create(**kw):
        fd,name=original(**kw);fds.append(fd);active[0]=False;return fd,name
    monkeypatch.setattr(a.tempfile,'mkstemp',create)
    src,out=tmp_path/'src',tmp_path/'out';src.write_bytes(b'payload')
    j=a.BachActionJournal(tmp_path/'journal','run',allowed_roots=(tmp_path,),mutation_guard=lease)
    with pytest.raises(PermissionError):j.execute_actions([a.FileActionStep('copy',str(src),str(out))])
    assert len(fds)==1 and len(j.retained_temporary_paths)==1 and not out.exists()
    with pytest.raises(OSError):os.fstat(fds[0])
    assert not j._fds and not j._streams
