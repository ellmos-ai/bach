# SPDX-License-Identifier: MIT
"""Isolated regression evidence for Task1728 review findings."""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from system.tests.test_task_lease_client import mem_db, _insert_task
from hub._services import task_lease_client as module
from hub._services.task_lease_client import TaskLeaseClient, LeaseAck, LeaseError

T0 = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)

def ack_payload(tid=1):
    return dict(granted=True, task_id=tid, lease_id=str(uuid.uuid4()), fence=1,
                worker_id="worker@HOST", host="HOST", issued_at=T0.isoformat(),
                expires_at=(T0+timedelta(minutes=30)).isoformat(),
                server_now=T0.isoformat(), ttl_profile="M", task_version="a"*64)


def test_configured_worker_never_uses_passed_projection(mem_db, monkeypatch):
    monkeypatch.setattr(module, "get_lead_config", lambda: dict(mode="worker", lead_url="http://lead.invalid:8000"))
    assert TaskLeaseClient(conn=mem_db).mode == "remote"


def test_worker_without_lead_url_fails_closed(mem_db, monkeypatch):
    monkeypatch.setattr(module, "get_lead_config", lambda: dict(mode="worker", lead_url=None))
    with pytest.raises(LeaseError):
        TaskLeaseClient(conn=mem_db)


@pytest.mark.parametrize("bad", [None, "garbage", "2026-10-05T12:00:00"])
def test_invalid_ack_clock_has_no_fallback(bad):
    data=ack_payload(); data.pop("granted"); data["server_now"]=bad
    data.pop("task_version")
    with pytest.raises(LeaseError):
        LeaseAck(**data, local_receive_time=T0)


def test_short_remaining_ttl_keeps_safety_buffer():
    data=ack_payload(); data.pop("granted"); data.pop("task_version")
    data["expires_at"]=(T0+timedelta(seconds=30)).isoformat()
    ack=LeaseAck(**data, local_receive_time=T0)
    assert ack.local_deadline == T0-timedelta(seconds=30)
    with pytest.raises(LeaseError): ack.assert_locally_valid(now=T0)


@pytest.mark.parametrize("field,value", [("task_id",2),("worker_id","other@HOST"),
    ("host","OTHER"),("fence",True),("fence",None),("ttl_profile",None),("granted","yes"),("lease_id",None),("lease_id","not-uuid")])
def test_acquire_rejects_mismatched_or_malformed_ack(monkeypatch, field, value):
    data=ack_payload(); data[field]=value
    c=TaskLeaseClient(lead_url="http://lead.invalid", device_token="test-token")
    monkeypatch.setattr(c,"_http_request",lambda *a,**k:(200,data))
    with pytest.raises(LeaseError): c.acquire(1,worker_id="worker@HOST",host="HOST",now=T0)


@pytest.mark.parametrize("operation", ["renew","release"])
def test_ref_operations_reject_foreign_ack(monkeypatch, operation):
    data=ack_payload(2)
    if operation=="release": data.update(released=True,outcome="done",status="done")
    c=TaskLeaseClient(lead_url="http://lead.invalid", device_token="test-token")
    monkeypatch.setattr(c,"_http_request",lambda *a,**k:(200,data))
    with pytest.raises(LeaseError):
        getattr(c,operation)(1,lease_id=data["lease_id"],fence=1,now=T0)


@pytest.mark.parametrize("entry",["cli","api"])
def test_operational_clients_do_not_open_worker_projection(tmp_path,monkeypatch,entry):
    monkeypatch.setattr(module,"get_lead_config",lambda:dict(mode="worker",lead_url="http://lead.invalid"))
    monkeypatch.setenv("BACH_DEVICE_TOKEN","test-token")
    monkeypatch.setattr(module.TaskLeaseClient,"_http_request",lambda *a,**k:(200,ack_payload()))
    def forbidden(): raise AssertionError("Worker projection opened")
    if entry=="cli":
        from hub.task import TaskHandler
        handler=TaskHandler(base_path=tmp_path)
        monkeypatch.setattr(handler,"_get_db",forbidden)
        ok,msg=handler.handle("lease",["1","--by","worker@HOST"])
        assert ok,msg
    else:
        from bach_api import task
        monkeypatch.setattr(task,"_connect",forbidden)
        assert task.lease_acquire(1,worker_id="worker@HOST")["granted"]


def test_local_version_survives_acquire_renew_and_stale_content_rejects(mem_db):
    tid=_insert_task(mem_db)
    from hub._services.task_lease import task_content_version
    row=dict(mem_db.execute("SELECT * FROM tasks WHERE id=?",(tid,)).fetchone())
    version=task_content_version(row)
    c=TaskLeaseClient(conn=mem_db)
    ack=c.acquire(tid,worker_id="worker@HOST",host="HOST",task_version=version,now=T0)
    assert ack.task_version==version
    renewed=c.renew(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=version,now=T0+timedelta(seconds=10))
    assert renewed.task_version==version
    mem_db.execute("UPDATE tasks SET description='changed' WHERE id=?",(tid,));mem_db.commit()
    with pytest.raises(LeaseError):
        c.release(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=version,outcome="done",now=T0+timedelta(seconds=20))


def test_client_decompose_requires_version_and_preserves_receipt(mem_db):
    mem_db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    mem_db.commit()
    tid=_insert_task(mem_db);c=TaskLeaseClient(conn=mem_db)
    ack=c.acquire(tid,worker_id="worker@HOST",host="HOST",now=T0)
    receipt=c.decompose(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=ack.task_version,
                        subtasks=[{"title":"child äöü"}],now=T0+timedelta(seconds=5))
    assert receipt.parent_closed and receipt.created_count==1
    assert receipt.task_version!=ack.task_version
    with pytest.raises(LeaseError):
        c.decompose(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=ack.task_version,
                    subtasks=[{"title":"duplicate"}],now=T0+timedelta(seconds=6))
    assert mem_db.execute("SELECT count(*) FROM tasks").fetchone()[0]==2


@pytest.fixture
def http_adapter(tmp_path, monkeypatch):
    TestClient = pytest.importorskip("fastapi.testclient").TestClient
    import gui.server as srv
    from system.tests.test_task_client_integration import _create_db
    db=tmp_path/"lead.db"; tid=_create_db(db)
    with sqlite3.connect(db) as conn:conn.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    monkeypatch.setattr(srv,"BACH_DB",db)
    monkeypatch.setattr(srv,"USER_DB",db)
    monkeypatch.setattr(srv,"DATA_DIR",tmp_path/"data")
    monkeypatch.setattr(srv,"BACH_DIR",tmp_path)
    monkeypatch.setattr(srv,"GUI_DIR",tmp_path/"gui")
    monkeypatch.setattr(srv,"validate_token",lambda token:dict(id=1,name="fixture") if token=="fixture-secret" else None)
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW","0")
    requests=[]
    server=TestClient(srv.app,raise_server_exceptions=False)
    def urlopen(req,timeout):
        from urllib.parse import urlsplit
        parts=urlsplit(req.full_url)
        requests.append((req.method,parts.path,dict(req.header_items())))
        response=server.request(req.method,parts.path+("?"+parts.query if parts.query else ""),
                                headers=dict(req.header_items()),content=req.data)
        return SimpleNamespace(status=response.status_code,
            read=lambda:response.content,__enter__=lambda self:self,__exit__=lambda *args:None)
    # Special methods are resolved on the class, not the instance.
    class Reply:
        def __init__(self,response):self.response=response;self.status=response.status
        def read(self):return self.response.read()
        def __enter__(self):return self
        def __exit__(self,*_):pass
    monkeypatch.setattr(module.urllib.request,"urlopen",lambda req,timeout:Reply(urlopen(req,timeout)))
    return TaskLeaseClient(lead_url="http://lead.invalid:8000",device_token="fixture-secret"),tid,requests,db


def test_actual_http_adapter_bearer_version_and_decompose(http_adapter):
    c,tid,requests,db=http_adapter
    view=c.read(tid);version=view.task_version
    ack=c.acquire(tid,worker_id="worker@HOST",host="HOST",task_version=version)
    assert ack.task_version==version
    assert c.read(tid,lease_id=ack.lease_id).own
    renewed=c.renew(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=version)
    assert renewed.task_version==version
    receipt=c.decompose(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=version,
                        subtasks=[{"title":"kind"}],close_parent=False)
    assert not receipt.parent_closed and receipt.task_version!=version
    released=c.release(tid,lease_id=ack.lease_id,fence=ack.fence,
                       task_version=receipt.task_version,outcome="done")
    assert released.status=="done"
    assert all(headers.get("Authorization")=="Bearer fixture-secret" for _,_,headers in requests)
    assert all("X-device-token" not in headers for _,_,headers in requests)


@pytest.mark.parametrize("token",[None,"revoked"])
def test_remote_invalid_device_fails_before_work(http_adapter,token):
    c,tid,requests,db=http_adapter;c._device_token=token
    with pytest.raises(LeaseError) as exc:
        c.acquire(tid,worker_id="worker@HOST",host="HOST")
    assert "fixture-secret" not in str(exc.value) and "revoked" not in str(exc.value)
    if token is None:assert not requests
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM tasks WHERE id=?",(tid,)).fetchone()[0]=="open"


@pytest.mark.parametrize("operation",["acquire","renew","release","decompose","update"])
def test_remote_timeout_never_retries_mutation(monkeypatch,operation):
    requests=[]
    def timeout(req,timeout):requests.append(req);raise TimeoutError("fixture-secret")
    monkeypatch.setattr(module.urllib.request,"urlopen",timeout)
    c=TaskLeaseClient(lead_url="http://lead.invalid",device_token="fixture-secret")
    ref=dict(lease_id=str(uuid.uuid4()),fence=1,task_version="a"*64)
    with pytest.raises(LeaseError) as exc:
        if operation=="acquire":c.acquire(1,worker_id="worker@HOST",host="HOST")
        elif operation=="decompose":c.decompose(1,subtasks=[{"title":"child"}],**ref)
        elif operation=="update":c.update(1,changes={"description":"changed"},**ref)
        else:getattr(c,operation)(1,**ref)
    assert len(requests)==1 and "fixture-secret" not in str(exc.value)


def test_committed_decomposition_lost_ack_stops_without_duplicate(http_adapter,monkeypatch):
    c,tid,requests,db=http_adapter
    ack=c.acquire(tid,worker_id="worker@HOST",host="HOST")
    original=module.urllib.request.urlopen
    def lose(req,timeout):
        reply=original(req,timeout)
        if req.full_url.endswith("/decompose"):raise TimeoutError("lost ACK after commit")
        return reply
    monkeypatch.setattr(module.urllib.request,"urlopen",lose)
    with pytest.raises(LeaseError):
        c.decompose(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=ack.task_version,subtasks=[{"title":"child"}])
    assert sum(path.endswith("/decompose") for _,path,_ in requests)==1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0]==2
        assert conn.execute("SELECT status FROM tasks WHERE id=?",(tid,)).fetchone()[0]=="done"


def test_remote_snapshot_candidates_and_update_use_authenticated_lead(http_adapter):
    c,tid,requests,db=http_adapter
    snapshot=c.task_snapshot(tid)
    assert any(item["id"]==tid for item in c.task_candidates()["tasks"])
    ack=c.acquire(tid,worker_id="worker@HOST",host="HOST",task_version=snapshot["task_version"])
    updated=c.update(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=ack.task_version,
                     changes={"description":"Auftrag überarbeitet"})
    assert c.task_snapshot(tid)["task_version"]==updated.task_version
    c.release(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=updated.task_version,outcome="return")
    assert all(headers.get("Authorization")=="Bearer fixture-secret" for _,_,headers in requests)


def test_committed_update_lost_ack_never_retries(http_adapter,monkeypatch):
    c,tid,requests,db=http_adapter
    ack=c.acquire(tid,worker_id="worker@HOST",host="HOST")
    original=module.urllib.request.urlopen
    def lose(req,timeout):
        reply=original(req,timeout)
        if req.full_url.endswith("/update"):raise TimeoutError("lost ACK after commit")
        return reply
    monkeypatch.setattr(module.urllib.request,"urlopen",lose)
    with pytest.raises(LeaseError):
        c.update(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=ack.task_version,
                 changes={"description":"committed once"})
    assert sum(path.endswith("/update") for _,path,_ in requests)==1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT description FROM tasks WHERE id=?",(tid,)).fetchone()[0]=="committed once"
        assert conn.execute("SELECT count(*) FROM task_history WHERE action='lease_update'").fetchone()[0]==1


def test_operator_content_change_rejects_http_holder(http_adapter):
    c,tid,_,db=http_adapter
    ack=c.acquire(tid,worker_id="worker@HOST",host="HOST")
    with sqlite3.connect(db) as conn:conn.execute("UPDATE tasks SET description='operator change' WHERE id=?",(tid,))
    for operation in ("renew","release"):
        with pytest.raises(module.LeaseDeniedError) as exc:
            getattr(c,operation)(tid,lease_id=ack.lease_id,fence=ack.fence,task_version=ack.task_version)
        assert exc.value.reason=="stale_task_version"


@pytest.mark.parametrize("action",["lease","lease-show","lease-renew","lease-release"])
def test_cli_version_and_all_worker_operations_use_lead(tmp_path,monkeypatch,action):
    from hub.task import TaskHandler
    monkeypatch.setattr(module,"get_lead_config",lambda:dict(mode="worker",lead_url="http://lead.invalid"))
    data=ack_payload(); lease_id=data["lease_id"]; seen=[]
    def http(self,method,path,payload=None,headers=None):
        seen.append((path,payload))
        if path.endswith("/release"):return 200,dict(task_id=1,released=True,fence=1,outcome="done",status="done",server_now=T0.isoformat())
        if method=="GET":return 200,dict(task_id=1,leased=True,fence=1,legacy=False,own=False,status="in_progress",server_now=T0.isoformat(),task_version="a"*64)
        return 200,data
    monkeypatch.setattr(module.TaskLeaseClient,"_http_request",http)
    handler=TaskHandler(base_path=tmp_path)
    def forbidden():raise AssertionError("Projection opened")
    monkeypatch.setattr(handler,"_get_db",forbidden)
    args=["1","--by","worker@HOST","--lease-id",lease_id,"--fence","1","--task-version","a"*64]
    ok,msg=handler.handle(action,args);assert ok,msg
    assert len(seen)==1
    if action!="lease-show":assert seen[0][1]["task_version"]=="a"*64


def test_python_api_preserves_version_and_decompose(http_adapter,monkeypatch):
    from bach_api import task
    c,tid,requests,db=http_adapter
    monkeypatch.setattr(module,"get_lead_config",lambda:dict(mode="worker",lead_url=c.lead_url))
    monkeypatch.setenv("BACH_DEVICE_TOKEN","fixture-secret")
    def forbidden():raise AssertionError("Projection opened")
    monkeypatch.setattr(task,"_connect",forbidden)
    version=task.lease_read(tid)["task_version"]
    ack=task.lease_acquire(tid,worker_id="worker@HOST",task_version=version)
    assert ack["task_version"]==version
    renewed=task.lease_renew(tid,lease_id=ack["lease_id"],fence=ack["fence"],task_version=version)
    assert renewed["task_version"]==version
    receipt=task.lease_decompose(tid,lease_id=ack["lease_id"],fence=ack["fence"],task_version=version,subtasks=[{"title":"child"}])
    assert receipt["parent_closed"] and receipt["created_count"]==1


def test_trithon_worker_never_opens_projection_on_lead_failure(tmp_path,monkeypatch):
    from hub._services import trithon_dispatch as trithon
    from hub._services.chat.slots_config import initialize_slots_config
    from hub._services.trithon.routing_contract import create_pending_contract
    from system.tests.test_trithon_lease_dispatch import TEST_ASSIGNMENT
    slots=tmp_path/"slots.json"; ledger=tmp_path/"ledger.jsonl"
    initialize_slots_config(str(slots));create_pending_contract(ledger,"ticket")
    ticket=trithon.SyntheticTicket("ticket",1,ledger,tmp_path/"projection.db",slots)
    monkeypatch.setattr(module,"get_lead_config",lambda:dict(mode="worker",lead_url="http://lead.invalid"))
    def no_lead(*a,**k):raise module.LeaseConnectionError("offline")
    monkeypatch.setattr(module.TaskLeaseClient,"acquire",no_lead)
    def forbidden(*a,**k):raise AssertionError("Projection opened")
    monkeypatch.setattr(trithon.sqlite3,"connect",forbidden)
    monkeypatch.setattr(trithon,"route_intent_v1",forbidden)
    result=trithon.execute_intent_v1(ticket,**TEST_ASSIGNMENT)
    assert not result["success"] and result["error"]=="offline"
    assert not ticket.db_path.exists()
    assert not any(json.loads(line).get("status")=="done" for line in ledger.read_text().splitlines())


@pytest.mark.parametrize("payload",[dict(mode="worker",lead_url=None),dict(mode="worker",lead_url=""),dict(mode="worker"),dict(mode="lead"),dict(mode="isolated"),dict(mode="unknown"),"malformed",None])
def test_real_worker_config_without_fixed_lead_never_opens_projection(tmp_path,monkeypatch,payload):
    from hub import rheingold
    config=tmp_path/"lead.json"
    if payload is not None:config.write_text(json.dumps(payload) if isinstance(payload,dict) else payload,encoding="utf-8")
    monkeypatch.setattr(rheingold,"LEAD_CONFIG_FILE",config)
    monkeypatch.setattr(rheingold,"is_rheingold_lead",lambda:False)
    monkeypatch.setenv("BACH_TEST_RHEINGOLD","1")
    monkeypatch.setenv("BACH_MODE","worker")
    for name in ("BACH_LEAD_URL","BACH_RHEINGOLD_URL","BACH_RHEINGOLD_DISABLED"):
        monkeypatch.delenv(name,raising=False)
    opened=[]
    def projection():opened.append(True);return sqlite3.connect(":memory:")
    with pytest.raises(LeaseError):TaskLeaseClient.for_task_db(projection)
    assert not opened


def test_explicit_isolated_config_still_allows_local_adapter(tmp_path,monkeypatch):
    from hub import rheingold
    config=tmp_path/"lead.json";config.write_text('{"mode":"isolated"}',encoding="utf-8")
    monkeypatch.setattr(rheingold,"LEAD_CONFIG_FILE",config)
    monkeypatch.setattr(rheingold,"is_rheingold_lead",lambda:False)
    monkeypatch.setenv("BACH_TEST_RHEINGOLD","1")
    monkeypatch.delenv("BACH_MODE",raising=False)
    for name in ("BACH_LEAD_URL","BACH_RHEINGOLD_URL","BACH_RHEINGOLD_DISABLED"):
        monkeypatch.delenv(name,raising=False)
    assert TaskLeaseClient().mode=="local"
