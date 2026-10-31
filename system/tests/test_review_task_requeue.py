"""Private owner/SQLite probes; no GUI lifespan, external credentials or network."""
import ast
import asyncio
import copy
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from system.tests.test_task_lease_client import _init_db, _insert_task
from gui.device_auth import create_task_result_operator
from hub._services.task_lease import task_content_version
from hub._services.task_lease_client import TaskLeaseClient, LeaseProtocolError
from hub._services.task_result_service import ensure_result_correction_schema, ResultConflict, ResultPermissionDenied
from hub._services.worker_result_review import _ensure_schema as ensure_review_schema
from hub._services import review_task_requeue as owner


@pytest.fixture
def world():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    conn.execute("ALTER TABLE tasks ADD COLUMN result TEXT")
    ensure_result_correction_schema(conn)
    conn.execute("BEGIN") if not conn.in_transaction else None
    ensure_review_schema(conn)
    conn.commit()
    token = create_task_result_operator("private-requeue-reviewer", connection=conn, can_request_correction=True)
    task_id = _insert_task(conn, title="Private Lifecycle", status="open")
    yield conn, task_id, token
    conn.close()


def release(world, *, result=False, note="Private Übergabenotiz"):
    conn, task_id, _ = world
    client = TaskLeaseClient(conn=conn)
    task = client.task_snapshot(task_id)
    lease = client.acquire(task_id, worker_id="private-worker@privatehost", host="privatehost",
                           task_version=task["task_version"],
                           **({"result_generation": "private-generation"} if result else {}))
    if result:
        client.submit_result(task_id, lease_id=lease.lease_id, fence=lease.fence,
                             task_version=lease.task_version, generation="private-generation", result="Private alte Implementierung")
        conn.execute("UPDATE tasks SET title='Geänderter Auftrag' WHERE id=?", (task_id,))
        conn.commit()
    else:
        client.release(task_id, lease_id=lease.lease_id, fence=lease.fence,
                       task_version=lease.task_version, outcome="review", note=note,
                       result_ref="https://github.com/private-fixture/project/pull/1")
        # The current owner requires a PR reference. The positive legacy
        # note-only input is synthetic historical state, not a claim that the
        # current release owner emits it. Keep the actual owner-generated
        # status/actor/fence/release ordering and note; reconstruct this one
        # historical field solely in the private fixture.
        row=conn.execute("SELECT id,new_value FROM task_history WHERE task_id=? AND action='lease_release' ORDER BY id DESC LIMIT 1",(task_id,)).fetchone()
        detail=json.loads(row[1]);detail["result_ref"]=""
        conn.execute("UPDATE task_history SET new_value=? WHERE id=?",(json.dumps(detail),row[0]));conn.commit()


def snapshot(world):
    conn, task_id, token = world
    return TaskLeaseClient(conn=conn).review_requeue_eligibility(task_id, operator_token=token)


def payload(value):
    return {"request_id": str(uuid.uuid4()), "case": value["case"], "preconditions": copy.deepcopy(value["preconditions"])}


def apply(world, request):
    conn, task_id, token = world
    return TaskLeaseClient(conn=conn).requeue_review_task(task_id, request, operator_token=token)


@pytest.mark.parametrize("with_result", [False, True])
def test_two_real_owner_cases_preserve_evidence_and_recover_ack(world, with_result):
    conn, task_id, token = world
    release(world, result=with_result)
    before_changes = conn.total_changes
    before = snapshot(world)
    assert before["eligible"] is True
    assert before["case"] == ("stale_result" if with_result else "release_note_without_result")
    assert conn.total_changes == before_changes and not conn.in_transaction
    assert "Übergabenotiz" not in json.dumps(before, ensure_ascii=False)
    request = payload(before)
    old_history = [tuple(r) for r in conn.execute("SELECT * FROM task_history ORDER BY id")]
    old_results = [tuple(r) for r in conn.execute("SELECT * FROM worker_task_results ORDER BY id")]
    ack = apply(world, request)
    assert ack["applied"] is True and ack["replayed"] is False
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "pending"
    assert old_results == [tuple(r) for r in conn.execute("SELECT * FROM worker_task_results ORDER BY id")]
    assert old_history == [tuple(r) for r in conn.execute("SELECT * FROM task_history ORDER BY id LIMIT ?", (len(old_history),))]
    # The first response is deliberately discarded, like a lost ACK. Same
    # request reconstructs the durable event and never writes a second one.
    changes = conn.total_changes
    replay = apply(world, request)
    assert replay["event_id"] == ack["event_id"] and replay["replayed"] is True
    assert conn.total_changes == changes
    assert conn.execute("SELECT COUNT(*) FROM task_history WHERE action='review_task_requeue'").fetchone()[0] == 1
    altered = copy.deepcopy(request); altered["preconditions"]["history_revision"] += 1
    with pytest.raises(ResultConflict): apply(world, altered)


@pytest.mark.parametrize("kind", ["task", "history", "lease", "result", "intent"])
def test_actual_preimage_races_fail_without_requeue(world, kind):
    conn, task_id, _ = world
    release(world, result=True)
    request = payload(snapshot(world))
    if kind == "task": conn.execute("UPDATE tasks SET description='race' WHERE id=?", (task_id,))
    elif kind == "history": conn.execute("INSERT INTO task_history(task_id,action,changed_at) VALUES (?,'other_audit','fixture')", (task_id,))
    elif kind == "lease": conn.execute("UPDATE tasks SET claim_fence=claim_fence+1 WHERE id=?", (task_id,))
    elif kind == "result": conn.execute("UPDATE worker_task_results SET generation='changed' WHERE task_id=?", (task_id,))
    else: conn.execute("INSERT INTO worker_result_review_intents VALUES (999,?,1,?,'private',?,1)", (task_id, "a"*64, "b"*64))
    conn.commit()
    with pytest.raises(ResultConflict): apply(world, request)
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "review"
    assert conn.execute("SELECT COUNT(*) FROM task_history WHERE action='review_task_requeue'").fetchone()[0] == 0


@pytest.mark.parametrize("kind,blocker", [
    ("accepted", "accepted_result"), ("current", "current_result_requires_existing_review"),
    ("lease", "lease_or_claim_present"), ("intent", "review_intent_or_model_review_present"),
    ("inline", "other_result_or_review_contract"), ("pointer", "correction_pointer_present"),
])
def test_accepted_active_or_foreign_contract_denied(world, kind, blocker):
    conn, task_id, _ = world
    release(world, result=True)
    if kind == "accepted": conn.execute("UPDATE worker_task_results SET accepted_by='operator-device:1'")
    elif kind == "current": conn.execute("UPDATE worker_task_results SET task_version=?", (task_content_version(dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())),))
    elif kind == "lease": conn.execute("UPDATE tasks SET claimed_by='other@privatehost' WHERE id=?", (task_id,))
    elif kind == "intent": conn.execute("INSERT INTO worker_result_review_intents VALUES (999,?,1,?,'private',?,1)", (task_id,"a"*64,"b"*64))
    elif kind == "inline": conn.execute("UPDATE tasks SET result='prior inline result' WHERE id=?", (task_id,))
    else: conn.execute("UPDATE tasks SET result_correction_request_id=1 WHERE id=?", (task_id,))
    conn.commit()
    view = snapshot(world)
    assert not view["eligible"] and blocker in view["blockers"]
    request=payload(view)
    request["case"]="stale_result"  # well-formed even when current result has case=None
    before="\n".join(conn.iterdump())
    with pytest.raises(ResultConflict): apply(world, request)
    assert "\n".join(conn.iterdump())==before


@pytest.mark.parametrize("kind", ["absent_note", "external_ref", "malformed", "wrong_actor"])
def test_note_provenance_not_rewritten_as_empty(world, kind):
    conn, task_id, _ = world
    release(world, note="" if kind=="absent_note" else "private note")
    row = conn.execute("SELECT id,new_value FROM task_history WHERE action='lease_release'").fetchone()
    if kind == "malformed": conn.execute("UPDATE task_history SET new_value='[]' WHERE id=?", (row[0],))
    elif kind == "external_ref":
        detail=json.loads(row[1]);detail["result_ref"]="https://github.com/private-fixture/project/pull/1"
        conn.execute("UPDATE task_history SET new_value=? WHERE id=?", (json.dumps(detail),row[0]))
    elif kind == "wrong_actor": conn.execute("UPDATE task_history SET changed_by='foreign' WHERE id=?", (row[0],))
    conn.commit()
    if kind == "malformed":
        with pytest.raises(ResultConflict): snapshot(world)
    else: assert snapshot(world)["eligible"] is False


@pytest.mark.parametrize("kind", ["wrong", "revoked", "capability"])
def test_operator_permission_before_effect(world, kind):
    conn, task_id, token = world
    release(world)
    request=payload(snapshot(world))
    if kind=="wrong": token="private-invalid"
    elif kind=="revoked": conn.execute("UPDATE devices SET status='revoked'");conn.commit()
    else: conn.execute("UPDATE task_result_operators SET can_request_correction=0");conn.commit()
    changes=conn.total_changes
    with pytest.raises(ResultPermissionDenied): owner.review_requeue_eligibility(conn,task_id,operator_token=token)
    with pytest.raises(ResultPermissionDenied): owner.requeue_review_task(conn,task_id,request,operator_token=token)
    assert conn.total_changes==changes


@pytest.mark.parametrize("change", ["UPDATE worker_task_results SET generation='trigger' WHERE task_id=NEW.id;",
                                      "UPDATE tasks SET claim_fence=claim_fence+1 WHERE id=NEW.id;",
                                      "DELETE FROM task_history WHERE task_id=NEW.id;"])
def test_postwrite_preservation_failure_rolls_back_atomically(world, change):
    conn, task_id, _=world
    release(world,result=True);request=payload(snapshot(world))
    before="\n".join(conn.iterdump())
    conn.execute("CREATE TRIGGER private_preservation AFTER UPDATE OF status ON tasks WHEN NEW.status='pending' BEGIN "+change+" END")
    conn.commit()
    with pytest.raises(ResultConflict): apply(world,request)
    conn.execute("DROP TRIGGER private_preservation");conn.commit()
    assert "\n".join(conn.iterdump())==before


@pytest.mark.parametrize("field,value", [("history_revision",True),("lease_fence",False),("result_id",0),("history_sha256",{}),("intent_sha256",[])])
def test_malformed_preconditions_fail_before_effect(world, field, value):
    release(world);request=payload(snapshot(world));request["preconditions"][field]=value
    changes=world[0].total_changes
    with pytest.raises((ValueError,LeaseProtocolError)): apply(world,request)
    assert world[0].total_changes==changes


def test_actual_route_bodies_auth_and_no_gui_lifespan(world):
    from fastapi import Request, HTTPException
    conn,task_id,token=world;release(world)
    tree=ast.parse((Path(__file__).resolve().parents[1]/'gui/server.py').read_text(encoding='utf-8'))
    funcs={n.name:n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)}
    dump="\n".join(conn.iterdump());opened=[]
    def private_connection():
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript(dump);opened.append(c);return c
    ns={'Request':Request,'HTTPException':HTTPException,'get_bach_db':private_connection}
    for name,route in [('review_task_requeue_eligibility_read','/api/tasks/{task_id}/review-requeue/eligibility'),('review_task_requeue_write','/api/tasks/{task_id}/review-requeue')]:
        node=copy.deepcopy(funcs[name]);assert ast.literal_eval(node.decorator_list[0].args[0])==route
        node.decorator_list=[];exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-route','exec'),ns)
    def request(auth):return Request({'type':'http','headers':[(b'x-bach-result-operator',token.encode())] if auth else []})
    view=asyncio.run(ns['review_task_requeue_eligibility_read'](task_id,request(True)))
    assert view['eligible'] is True
    with pytest.raises(HTTPException) as caught:asyncio.run(ns['review_task_requeue_eligibility_read'](task_id,request(False)))
    assert caught.value.status_code==403
    with pytest.raises(HTTPException) as caught:asyncio.run(ns['review_task_requeue_write'](task_id,payload(view),request(False)))
    assert caught.value.status_code==403
    ack=asyncio.run(ns['review_task_requeue_write'](task_id,payload(view),request(True)))
    assert ack['applied'] is True and ack['current_readback_required'] is True


@pytest.mark.parametrize('tamper',[None,'bool_eligible','bool_revision','dict_case','dict_blockers','missing_status','false_positive'])
def test_remote_eligibility_protocol_and_exact_personal_header(world,tamper):
    release(world);response=snapshot(world);_,task_id,token=world
    if tamper=='bool_eligible':response['eligible']=1
    elif tamper=='bool_revision':response['preconditions']['history_revision']=True
    elif tamper=='dict_case':response['case']={}
    elif tamper=='dict_blockers':response['blockers']={}
    elif tamper=='missing_status':response.pop('status')
    elif tamper=='false_positive':response['blockers']=['lease_or_claim_present']
    client=TaskLeaseClient.__new__(TaskLeaseClient);client._mode='remote';calls=[]
    def transport(method,path,**kwargs):calls.append((method,path,kwargs));return 200,copy.deepcopy(response)
    client._http_request=transport
    if tamper is None:assert client.review_requeue_eligibility(task_id,operator_token=token)['eligible'] is True
    else:
        with pytest.raises(LeaseProtocolError):client.review_requeue_eligibility(task_id,operator_token=token)
    assert calls==[('GET',f'/api/tasks/{task_id}/review-requeue/eligibility',{'headers':{'X-BACH-Result-Operator':token}})]


@pytest.mark.parametrize('tamper',[None,'wrong_request','bool_event','changed_digest'])
def test_remote_ack_protocol_no_transport_replay(world,tamper):
    release(world);request=payload(snapshot(world));response=apply(world,request);_,task_id,token=world
    if tamper=='wrong_request':response['request_id']=str(uuid.uuid4())
    elif tamper=='bool_event':response['event_id']=True
    elif tamper=='changed_digest':response['preserved_results_sha256']='a'*64
    client=TaskLeaseClient.__new__(TaskLeaseClient);client._mode='remote';calls=[]
    def transport(method,path,body=None,**kwargs):calls.append((method,path,body,kwargs));return 200,copy.deepcopy(response)
    client._http_request=transport
    if tamper is None:assert client.requeue_review_task(task_id,request,operator_token=token)['applied'] is True
    else:
        with pytest.raises(LeaseProtocolError):client.requeue_review_task(task_id,request,operator_token=token)
    assert calls==[('POST',f'/api/tasks/{task_id}/review-requeue',request,{'headers':{'X-BACH-Result-Operator':token}})]


def test_result_service_adapter_cannot_use_personal_requeue(world):
    from hub._services.task_lease_client import TaskResultServiceClient
    conn,task_id,token=world;release(world);request=payload(snapshot(world))
    client=TaskResultServiceClient(conn=conn,service_id='private-service',service_token='x'*43)
    changes=conn.total_changes
    with pytest.raises(LeaseProtocolError):client.review_requeue_eligibility(task_id,operator_token=token)
    with pytest.raises(LeaseProtocolError):client.requeue_review_task(task_id,request,operator_token=token)
    assert conn.total_changes==changes

