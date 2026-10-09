"""Native history uses only synthetic SQLite/profile fixtures, without provider calls."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gui import server
from gui.api import agent_history as api
from gui.api import unified_api
from hub._services.chat import agent_profile_context as profiles
from hub._services.chat.session_store import SQLiteChatSessionStore, CHAT_SNAPSHOT_TYPE, ChatSessionStoreError


@pytest.fixture
def history(tmp_path, monkeypatch):
    database=tmp_path/"bach.db"
    conn=sqlite3.connect(database)
    try:
        conn.executescript("""
        CREATE TABLE devices(id INTEGER,token_hash TEXT,status TEXT);
        CREATE TABLE session_snapshots(id INTEGER PRIMARY KEY,session_id TEXT,snapshot_type TEXT,snapshot_data TEXT,name TEXT,created_at TEXT);
        CREATE TABLE bach_agents(id INTEGER PRIMARY KEY,name TEXT,version TEXT,is_active INTEGER);
        CREATE TABLE tasks(id INTEGER PRIMARY KEY,title TEXT,status TEXT);
        CREATE TABLE task_history(task_id INTEGER,action TEXT,field_changed TEXT,old_value TEXT,new_value TEXT,changed_at TEXT,changed_by TEXT);
        """)
        conn.execute("INSERT INTO devices VALUES(1,?,'active')",(hashlib.sha256(b'history-fixture').hexdigest(),))
        conn.execute("INSERT INTO devices VALUES(2,?,'revoked')",(hashlib.sha256(b'revoked-fixture').hexdigest(),))
        conn.execute("INSERT INTO bach_agents VALUES(1,'fixture','1.0.0',1)")
        conn.execute("INSERT INTO tasks VALUES(1,'Grüße Aufgabe','done')")
        conn.execute("INSERT INTO tasks VALUES(2,'Offene Aufgabe','pending')")
        conn.execute("INSERT INTO task_history VALUES(1,'status_change','status','in_progress','done','2026-01-01T10:00:00Z','private-actor')")
        conn.execute("INSERT INTO task_history VALUES(1,'field_change','description','private old','private secret','2026-01-01T11:00:00Z','private-actor')")
        conn.execute("INSERT INTO task_history VALUES(2,'status_change','status','done','pending','2026-01-01T12:00:00Z','other-actor')")
        conn.commit()
    finally:conn.close()
    root=tmp_path/'agents';profile=root/'fixture/SKILL.md';profile.parent.mkdir(parents=True)
    content=b'---\nname: fixture\nversion: 1.0.0\n---\nRole fixture.'
    profile.write_bytes(content)
    monkeypatch.setattr(api,"BACH_DB",database)
    monkeypatch.setattr(unified_api,"BACH_DB",database)
    monkeypatch.setattr(profiles,"BACH_DB",database)
    monkeypatch.setattr(profiles,"AGENTS_DIR",root)
    monkeypatch.setattr(profiles,"_PROFILES",{"fixture":("fixture","1.0.0",hashlib.sha256(content).hexdigest())})
    monkeypatch.setattr(server,"validate_token",lambda token:{"id":1} if token in {'history-fixture','revoked-fixture'} else None)
    store=SQLiteChatSessionStore(database)
    client=TestClient(server.app,headers={"Authorization":"Bearer history-fixture"})
    return store,client,profile,database


def seed_global(store, chat="gui-web"):
    store.save(chat,[{"role":"user","content":"Hallo äöü"},{"role":"assistant","content":"Antwort"}])


def seed_profile(store):
    binding,_=profiles.resolve_profile(1)
    chat="agent:1:"+32*"a"
    store.save(chat,[{"role":"user","content":"Profil privat"}],binding=binding)


def test_filter_before_paging_keeps_global_rows(history):
    store,client,_,_=history
    seed_global(store)
    seed_profile(store)
    response=client.get("/api/agent-history/sessions?limit=1")
    assert response.status_code==200
    data=response.json()
    assert data["schema"]=="bach.chat-sessions.v1" and data["total"]==1
    assert len(data["sessions"])==1 and data["sessions"][0]["chat_id"]=="gui-web"
    assert data["has_more"] is False
    selected=client.get("/api/agent-history/sessions?agent_id=1&limit=1").json()
    assert selected["total"]==1 and selected["sessions"][0]["agent_id"]==1


def test_archives_and_pagination_are_actual_store_rows(history):
    store,client,_,_=history
    seed_global(store);store.archive_current("gui-web")
    page=client.get("/api/agent-history/sessions?limit=1").json()
    assert page["total"]==2 and page["has_more"] is True
    next_page=client.get("/api/agent-history/sessions?limit=1&offset=1").json()
    assert next_page["sessions"][0]["id"]!=page["sessions"][0]["id"]
    assert next_page["has_more"] is False
    archived=client.get("/api/agent-history/sessions?archive=archived").json()
    current=client.get("/api/agent-history/sessions?archive=current").json()
    assert archived["total"]==current["total"]==1
    assert archived["sessions"][0]["archived"] is True and current["sessions"][0]["archived"] is False


@pytest.mark.parametrize("query",["limit=0","limit=101","offset=-1","offset=100001","agent_id=0","archive=maybe"])
def test_invalid_filters_do_not_query_or_create(history,query,monkeypatch):
    _,client,_,_=history
    monkeypatch.setattr(api,"_store",lambda: (_ for _ in ()).throw(AssertionError("invalid input queried storage")))
    assert client.get("/api/agent-history/sessions?"+query).status_code==422


def test_readers_do_not_modify_database(history):
    store,client,_,database=history
    seed_global(store)
    before=database.read_bytes()
    page=client.get("/api/agent-history/sessions").json()
    snapshot_id=page["sessions"][0]["id"]
    assert client.get("/api/agent-history/sessions/"+str(snapshot_id)).status_code==200
    assert client.get("/api/agent-history/tasks").status_code==200
    assert database.read_bytes()==before


def test_detail_requires_matching_current_profile_binding(history):
    store,client,profile,_=history
    seed_profile(store)
    snapshot_id=client.get("/api/agent-history/sessions?agent_id=1").json()["sessions"][0]["id"]
    path="/api/agent-history/sessions/"+str(snapshot_id)
    assert client.get(path).status_code==409
    assert client.get(path+"?agent_id=2").status_code==409
    assert client.get(path+"?agent_id=1").json()["messages"][0]["content"]=="Profil privat"
    profile.write_bytes(b"changed source")
    assert client.get(path+"?agent_id=1").status_code==409
    assert client.get("/api/agent-history/sessions?agent_id=1").status_code==409


def test_detail_exposes_visible_messages_and_real_task_ids_only(history):
    store,client,_,_=history
    store.save("gui-web",[
        {"role":"system","content":"private system"},
        {"role":"user","content":"<script>document.body.remove()</script>"},
        {"role":"assistant","content":"<think>hidden reason</think>Öffentliche Antwort","answer_status":"success","completed_task_ids":[1]},
        {"role":"tool","content":"Werkzeugergebnis"}])
    snapshot_id=client.get("/api/agent-history/sessions").json()["sessions"][0]["id"]
    data=client.get("/api/agent-history/sessions/"+str(snapshot_id)).json()
    assert data["stored_message_count"]==4 and len(data["messages"])==3
    assert data["reasoning_included"] is False and data["system_messages_included"] is False
    assert data["messages"][1]["content"]=="Öffentliche Antwort"
    assert data["messages"][1]["completed_task_ids"]==[1]
    assert "private system" not in json.dumps(data) and "hidden reason" not in json.dumps(data)


def test_unterminated_reasoning_is_not_a_visible_answer(history):
    store,client,_,_=history
    store.save("gui-web",[{"role":"assistant","content":"<analysis>hidden"}])
    snapshot_id=client.get("/api/agent-history/sessions").json()["sessions"][0]["id"]
    assert client.get("/api/agent-history/sessions/"+str(snapshot_id)).json()["messages"][0]["content"]==""


def test_normal_store_limits_are_declared_and_not_called_full_history(history):
    store,client,_,_=history
    store.save("gui-web",[{"role":"user","content":str(i)} for i in range(50)])
    page=client.get("/api/agent-history/sessions").json()
    assert page["save_limits"]=={"max_messages":40,"max_content_chars":24000}
    assert page["sessions"][0]["stored_message_count"]==40
    data=client.get("/api/agent-history/sessions/"+str(page["sessions"][0]["id"])).json()
    assert data["available_excerpt"] is True and len(data["messages"])==40


def test_task_events_count_filters_and_content_privacy(history):
    _,client,_,_=history
    page=client.get("/api/agent-history/tasks?limit=1").json()
    assert page["total"]==3 and page["has_more"] is True and len(page["events"])==1
    assert page["events"][0]["task_id"]==2
    task=client.get("/api/agent-history/tasks?task_id=1&status=done").json()
    assert task["total"]==2 and all(e["task_id"]==1 for e in task["events"])
    raw=json.dumps(task)
    assert "private secret" not in raw and "private-actor" not in raw and "private old" not in raw
    assert task["events"][0]["old_status"] is None
    assert task["events"][1]["old_status"]=="in_progress" and task["events"][1]["new_status"]=="done"
    assert client.get("/api/agent-history/tasks?status=made-up").status_code==422


@pytest.mark.parametrize("path",["sessions","tasks","sessions/1"])
def test_device_authentication_is_required_even_if_middleware_accepts_revoked_token(history,path):
    _,client,_,_=history
    assert client.get("/api/agent-history/"+path,headers={"Authorization":"Bearer revoked-fixture"}).status_code==403
    assert client.get("/api/agent-history/"+path,headers={"Authorization":"Bearer invalid"}).status_code==401


def test_missing_sources_are_unavailable_not_empty_success(history):
    _,client,_,database=history
    database.unlink()
    assert client.get("/api/agent-history/sessions").status_code==503
    assert client.get("/api/agent-history/tasks").status_code==503


def test_corrupt_store_is_not_an_empty_page(history):
    store,client,_,database=history
    conn=sqlite3.connect(database)
    try:
        conn.execute("INSERT INTO session_snapshots VALUES(1,'malformed',?,'{','Broken','2026')",(CHAT_SNAPSHOT_TYPE,));conn.commit()
    finally:conn.close()
    assert client.get("/api/agent-history/sessions").status_code==503


def test_store_page_does_not_create_missing_db(tmp_path):
    path=tmp_path/"missing.db"
    with pytest.raises(ChatSessionStoreError):SQLiteChatSessionStore(path).list_snapshot_page()
    assert not path.exists()

@pytest.mark.parametrize("path",["sessions/0","sessions/999999999999999999999","sessions?agent_id=999999999999999999999","tasks?task_id=999999999999999999999"])
def test_identifiers_are_bounded_before_sql(history,path):
    _,client,_,_=history
    assert client.get("/api/agent-history/"+path).status_code==422

def test_detail_does_not_accept_an_unknown_transcript_version(history):
    store,client,_,database=history
    seed_global(store)
    snapshot_id=client.get("/api/agent-history/sessions").json()["sessions"][0]["id"]
    conn=sqlite3.connect(database)
    try:
        conn.execute("UPDATE session_snapshots SET snapshot_data=?",(json.dumps({"version":2,"messages":[],"chat_id":"gui-web"}),));conn.commit()
    finally:conn.close()
    assert client.get("/api/agent-history/sessions/"+str(snapshot_id)).status_code==503
    assert client.get("/api/agent-history/sessions").status_code==503


def test_legacy_profile_prefix_is_excluded_before_global_count_and_paging(history):
    store,client,_,database=history
    seed_global(store)
    conn=sqlite3.connect(database)
    try:
        payload={"version":1,"chat_id":"agent:1:"+32*"b","messages":[]}
        conn.execute("INSERT INTO session_snapshots(session_id,snapshot_type,snapshot_data,name,created_at) VALUES(?,?,?,?,?)",
                     ("legacy-profile",CHAT_SNAPSHOT_TYPE,json.dumps(payload),"Legacy","2099"))
        conn.commit()
    finally:conn.close()
    page=client.get("/api/agent-history/sessions?limit=1").json()
    assert page["total"]==1 and page["sessions"][0]["chat_id"]=="gui-web"


def test_profile_prefix_binding_is_consistent_before_count_and_paging(history):
    store,client,_,database=history
    seed_profile(store)
    conn=sqlite3.connect(database)
    try:
        for chat in ("gui-web","agent:2:"+32*"b","agent:1:invalid"):
            payload={"version":1,"chat_id":chat,"context_class":"agent-profile","agent_id":1,"messages":[]}
            conn.execute("INSERT INTO session_snapshots(session_id,snapshot_type,snapshot_data,name,created_at) VALUES(?,?,?,?,?)",
                         (chat,CHAT_SNAPSHOT_TYPE,json.dumps(payload),"Invalid binding","2099"))
        conn.commit()
    finally:conn.close()
    page=client.get("/api/agent-history/sessions?agent_id=1&limit=1").json()
    assert page["total"]==1 and page["sessions"][0]["chat_id"]=="agent:1:"+32*"a"


@pytest.mark.parametrize("field",["session_id","chat_id","name"])
def test_null_transcript_metadata_is_unavailable_not_uncaught_500(history,field):
    store,client,_,database=history
    seed_global(store)
    conn=sqlite3.connect(database)
    try:
        if field=="chat_id":
            conn.execute("UPDATE session_snapshots SET snapshot_data=json_set(snapshot_data,'$.chat_id',NULL)")
        else:
            conn.execute("UPDATE session_snapshots SET "+field+"=NULL")
        conn.commit()
    finally:conn.close()
    assert client.get("/api/agent-history/sessions").status_code==503


def test_legacy_archive_without_chat_key_remains_readable_without_database_repair(history):
    store,client,_,database=history
    seed_global(store);store.archive_current("gui-web")
    conn=sqlite3.connect(database)
    try:
        conn.execute("UPDATE session_snapshots SET snapshot_data=json_remove(snapshot_data,'$.chat_id') WHERE instr(session_id,':archived:')>0")
        conn.commit()
    finally:conn.close()
    before=database.read_bytes()
    page=client.get("/api/agent-history/sessions?archive=archived").json()
    assert page["total"]==1 and page["sessions"][0]["chat_id"]==""
    assert page["sessions"][0]["archived"] is True
    snapshot_id=page["sessions"][0]["id"]
    detail=client.get("/api/agent-history/sessions/"+str(snapshot_id))
    assert detail.status_code==200 and detail.json()["messages"][0]["content"]=="Hallo äöü"
    assert database.read_bytes()==before


def test_missing_chat_key_cannot_override_existing_profile_binding(history):
    store,client,_,database=history
    seed_profile(store);store.archive_current("agent:1:"+32*"a")
    conn=sqlite3.connect(database)
    try:
        conn.execute("UPDATE session_snapshots SET snapshot_data=json_remove(snapshot_data,'$.chat_id') WHERE instr(session_id,':archived:')>0")
        snapshot_id=conn.execute("SELECT id FROM session_snapshots WHERE instr(session_id,':archived:')>0").fetchone()[0]
        conn.commit()
    finally:conn.close()
    assert client.get("/api/agent-history/sessions?archive=archived").json()["total"]==0
    assert client.get("/api/agent-history/sessions?archive=archived&agent_id=1").json()["total"]==0
    assert client.get("/api/agent-history/sessions/"+str(snapshot_id)).status_code==409
    assert client.get("/api/agent-history/sessions/"+str(snapshot_id)+"?agent_id=1").status_code==409
