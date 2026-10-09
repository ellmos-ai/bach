# SPDX-License-Identifier: MIT
"""Synthetic pin stores: no production configuration, database or module writes."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from hub._services import domain_pin_store as store
from hub._services import skill_source_service
from gui.api import domain_catalog as catalog
from gui import server

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    path = tmp_path / "data/domain_pins.json"
    monkeypatch.setattr(catalog, "PIN_STORAGE_FILE", path)
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda p: None)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "pin-fixture" else None)
    import sqlite3, hashlib
    from gui.api import unified_api
    database = tmp_path / "devices.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE devices(id INTEGER, token_hash TEXT, status TEXT)")
        connection.execute("INSERT INTO devices VALUES(1, ?, 'active')", (hashlib.sha256(b"pin-fixture").hexdigest(),))
    monkeypatch.setattr(unified_api, "BACH_DB", database)
    return path, TestClient(server.app, headers={"Authorization": "Bearer pin-fixture"})

def test_get_defaults_is_read_only(isolated):
    path, client = isolated
    data = client.get("/api/domains/pins").json()
    assert data["schema"] == store.SCHEMA and data["version"] == store.ABSENT_VERSION
    assert data["persisted"] is False
    assert not path.exists() and not path.parent.exists()

@pytest.mark.parametrize("document", [["ati","gone-module"], {"pins":["ati","gone-module"],"private_metadata":{"note":"Grüße"}}])
def test_legacy_ids_and_other_metadata_preserved(tmp_path, document):
    path=tmp_path/"pins.json";path.write_text(json.dumps(document,ensure_ascii=False),encoding="utf-8")
    before=store.read(path,[])
    saved=store.mutate(path,[],before["version"],domain_id="steuer-suite",pinned=True,guard=lambda p: None)
    assert saved["ids"]==["ati","gone-module","steuer-suite"]
    decoded=json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document,dict):assert decoded["private_metadata"]==document["private_metadata"]
    assert store.read(path,[])["version"]==saved["version"]

def test_same_version_two_writers_only_one_commits(tmp_path):
    path=tmp_path/"pins.json"
    def write(identifier):
        try:return store.mutate(path,[],store.ABSENT_VERSION,domain_id=identifier,pinned=True,guard=lambda p: None)
        except store.PinConflict:return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,["domain-a","domain-b"]))
    assert results.count("conflict")==1
    assert len(store.read(path,[])["ids"])==1

@pytest.mark.parametrize("document", [None,{},{"pins":None},{"pins":[3]},{"pins":["../escape"]},{"pins":["ati","ati"]},"malformed"])
def test_invalid_stored_pins_never_fall_back_or_overwrite(tmp_path,document):
    path=tmp_path/"pins.json"
    raw=b"{" if document=="malformed" else json.dumps(document).encode()
    path.write_bytes(raw)
    with pytest.raises(store.PinUnavailable):store.read(path,["ati"])
    with pytest.raises(store.PinUnavailable):store.mutate(path,["ati"],store.ABSENT_VERSION,domain_id="new",pinned=True,guard=lambda p: None)
    assert path.read_bytes()==raw

@pytest.mark.parametrize("ids", [None,{},False,[3],["../escape"],["ati","ati"],["ati"]*257])
def test_invalid_batch_no_storage_mutation(tmp_path,ids):
    path=tmp_path/"pins.json"
    with pytest.raises(ValueError):store.mutate(path,[],store.ABSENT_VERSION,ids=ids,guard=lambda p: None)
    assert not path.exists()

@pytest.mark.parametrize("pinned", [None,"false",0,1,[],{}])
def test_pin_status_requires_bool(tmp_path,pinned):
    path=tmp_path/"pins.json"
    with pytest.raises(ValueError):store.mutate(path,[],store.ABSENT_VERSION,domain_id="ati",pinned=pinned,guard=lambda p: None)
    assert not path.exists()

def test_project_lock_refuses_before_any_file_write(tmp_path):
    path=tmp_path/"data/pins.json";calls=[]
    def deny(p):calls.append(p);raise PermissionError("fixture lock")
    with pytest.raises(PermissionError):store.mutate(path,[],store.ABSENT_VERSION,domain_id="ati",pinned=True,guard=deny)
    assert calls==[path] and not path.parent.exists()

def test_guard_rechecked_before_atomic_replace(tmp_path):
    path=tmp_path/"pins.json";calls=[]
    def deny_third(p):
        calls.append(p)
        if len(calls)==3:raise PermissionError("new lock")
    with pytest.raises(PermissionError):store.mutate(path,[],store.ABSENT_VERSION,domain_id="ati",pinned=True,guard=deny_third)
    assert not path.exists()
    assert not list(tmp_path.glob(".*.tmp"))

def test_symlink_target_never_mutated(tmp_path):
    original=tmp_path/"original.json";original.write_text('{"pins":[]}',encoding="utf-8")
    path=tmp_path/"link.json"
    try:path.symlink_to(original)
    except OSError:pytest.skip("Host cannot create symlinks")
    with pytest.raises(PermissionError):store.mutate(path,[],store.ABSENT_VERSION,domain_id="ati",pinned=True,guard=lambda p: None)
    assert original.read_text()=='{"pins":[]}'

def test_api_version_conflict_and_persistent_readback(isolated):
    path,client=isolated
    initial=client.get("/api/domains/pins").json()
    first=client.post("/api/domains/domain-fixture/pin",json={"pinned":True,"version":initial["version"]})
    assert first.status_code==200
    saved=first.json()
    assert saved["success"] and saved["persisted"] and saved["id"]=="domain-fixture"
    assert any(p["id"]=="domain-fixture" for p in saved["pins"])
    assert client.get("/api/domains/pins").json()["version"]==saved["version"]
    stale=client.post("/api/domains/other-fixture/pin",json={"pinned":True,"version":initial["version"]})
    assert stale.status_code==409
    removal=client.post("/api/domains/domain-fixture/pin",json={"pinned":False,"version":saved["version"]})
    assert removal.status_code==200
    assert json.loads(path.read_text())["pins"]==[p["id"] for p in initial["pins"]]
    fresh_client=TestClient(server.app,headers={"Authorization":"Bearer pin-fixture"})
    assert fresh_client.get("/api/domains/pins").json()["version"]==removal.json()["version"]

def test_api_missing_version_cannot_use_legacy_whole_list_writer(isolated):
    path,client=isolated
    assert client.post("/api/domains/pins",json={"pinned_ids":["ati"]}).status_code==428
    assert client.post("/api/domains/ati/pin",json={"pinned":True}).status_code==428
    assert not path.exists()

def test_api_batch_preserves_ack_binding_and_metadata(isolated):
    path,client=isolated
    path.parent.mkdir();path.write_text('{"pins":["ati"],"foreign":"keep"}',encoding="utf-8")
    version=client.get("/api/domains/pins").json()["version"]
    result=client.post("/api/domains/pins",json={"pinned_ids":["ati","law-checker"],"version":version})
    assert result.status_code==200 and result.json()["status"]=="saved"
    assert [p["id"] for p in result.json()["pins"]]==["ati","law-checker"]
    assert json.loads(path.read_text())["foreign"]=="keep"

def test_api_device_auth_and_invalid_bool(isolated):
    path,client=isolated
    anonymous=TestClient(server.app)
    assert anonymous.post("/api/domains/ati/pin",json={"pinned":True,"version":store.ABSENT_VERSION}).status_code==401
    assert client.post("/api/domains/ati/pin",json={"pinned":"false","version":store.ABSENT_VERSION}).status_code==422
    assert not path.exists()

def test_api_unavailable_and_project_lock_are_visible(isolated,monkeypatch):
    path,client=isolated
    path.parent.mkdir();path.write_text("{",encoding="utf-8")
    assert client.get("/api/domains/pins").status_code==503
    path.unlink()
    def deny(p):raise PermissionError("fixture")
    monkeypatch.setattr(skill_source_service,"check_write_locks",deny)
    assert client.post("/api/domains/ati/pin",json={"pinned":True,"version":store.ABSENT_VERSION}).status_code==423
    assert not path.exists()
