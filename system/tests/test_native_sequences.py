"""Real pinned engine and isolated TaskLease authority; no live providers or DBs."""
import asyncio
import json
import sqlite3
import threading
import uuid
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from llmauto.core import embedded
from hub._services.chat import native_sequences as native, slots_config as slots
from hub._services.chat.sequence_store import SequenceStore, SequenceConflict, definition
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease_client import TaskLeaseClient, LeaseConnectionError, LeaseProtocolError
from hub._services import skill_source_service

# The focused Mac run starts in system/, whereas CI starts at repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from system.tests.test_task_lease_client import _init_db, mem_db
from system.tests.test_worker_lease_binding import binding, approve_result


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("BACH_TASK_LEASE_CREATOR_WINDOW", raising=False)
    path = tmp_path / "authority.db"
    db = sqlite3.connect(path)
    _init_db(db)
    db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    db.commit(); db.close()
    return SequenceStore(path)


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    path = tmp_path / "slots.json"
    slots.initialize_slots_config(str(path))
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda _path: None)
    return path


def draft(mode="agents"):
    return {"name": "sequence-test", "title": "Testfolge", "description": "Isolierte Abnahme",
            "mode": mode, "agent_slot": "buddha_research" if mode == "skills" else "",
            "steps": [{"label": "Analyse", "agent_slot": "buddha_research", "skill_ids": ["native-a"] if mode == "skills" else [], "instructions": "Erzeuge Ergebnis A."},
                      {"label": "Prüfung", "agent_slot": "buddha_developer", "skill_ids": ["native-b"] if mode == "skills" else [], "instructions": "Verwende das Ergebnis des Vorgängers."}]}


def fast_engine():
    fields = {key: getattr(embedded, key) for key in ("SequenceStep", "SequenceState", "ExecutionHandle", "ExecutionObservation", "request_id_for")}
    return SimpleNamespace(**fields, run_sequence=lambda *args, **kw: embedded.run_sequence(*args, **kw, poll_interval=.01))


class IsolatedNative:
    """Native transport double; completion uses real fenced leases and SQLite."""
    def __init__(self, store):
        self.store=store; self.calls=[]; self.receipts={}; self.results={}; self.cancelled=[]
        self.fail_result=False; self.foreign_receipt=False; self.hold=False
        self.observed=threading.Event()
        self.gateway=native.NativeGateway(service_instance="a"*32,start=self.start,observe=self.observe,
            result=self.result,stop=self.stop,slot=slots.get_system_slot)

    def start(self, worker_id, **kwargs):
        self.calls.append((worker_id,kwargs))
        slot=slots.get_system_slot(worker_id);generation=uuid.uuid4().hex
        db=sqlite3.connect(self.store.path);db.row_factory=sqlite3.Row
        client=TaskLeaseClient(conn=db)
        physical_worker="worker-"+uuid.uuid4().hex+"@test"
        delegated=kwargs["_creator_authority"].bind(task_id=slot["task_id"],slot_id=worker_id,
            start_request_id=kwargs["start_request_id"],generation=generation,worker_id=physical_worker,host="test")
        binding=WorkerLeaseBinding.acquire(client,slot["task_id"],worker_id=physical_worker,host="test",slot=slot,
            generation=generation,is_current=lambda:True,stop_event=threading.Event(),_creator_delegation=delegated)
        output="Ergebnis "+str(len(self.calls))+" · Müller & Söhne"
        binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":output})
        assert not binding.completed_task_ids and binding.reviewed_task_ids == (binding.task_id,)
        approve_result(binding, db)
        self.results[worker_id]={**binding.completion_result,"schema":"bach.task-result.v1"}
        self.receipts[worker_id]={"schema":"bach.worker-execution.v1","service_instance":"a"*32,
            "worker_id":worker_id,"start_request_id":kwargs["start_request_id"],"generation":generation,
            "state":"terminal","terminal":True,"worker_thread_started":True,
            "results_verified":True,"reviewed_task_ids":[],"completed_task_ids":[binding.task_id]}
        db.close()
        return {"execution":self.receipts[worker_id]},202

    def observe(self, worker_id, request):
        self.observed.set();receipt=dict(self.receipts[worker_id])
        if self.foreign_receipt:receipt["generation"]="f"*32
        if self.hold and worker_id not in self.cancelled:receipt.update(terminal=False,state="finishing")
        return receipt

    def result(self,worker_id,*args):
        if self.fail_result:raise ValueError("Missing output")
        return self.results[worker_id]

    def stop(self,worker_id,_worker,**kwargs):
        expected=kwargs["expected_execution"]
        assert expected["generation"]==self.receipts[worker_id]["generation"]
        assert expected["start_request_id"]==self.receipts[worker_id]["start_request_id"]
        self.cancelled.append(worker_id)
        return True,{}, {"kind":"worker-revocation", "worker_id":worker_id,
            "generation":expected["generation"], "confirmed":True, "outcome":"revocation-confirmed",
            "execution":dict(self.receipts[worker_id])},200


def service(store, profiles):
    transport=IsolatedNative(store)
    return native.NativeSequences(store,transport.gateway,engine_loader=fast_engine),transport


def start_payload(chain):
    return {"request_id":uuid.uuid4().hex,"version":chain["version"],
            "configuration_version":slots.core_system_agents_snapshot()["configuration_version"],
            "expected_service_instance":"a"*32,"input":"Isolierter Arbeitsauftrag"}


def wait(controller,run_id):
    controller._threads[run_id].join(10)
    assert not controller._threads[run_id].is_alive()
    return controller.get_run(run_id)


def test_catalog_does_not_initialize_schema_or_task_rows(store):
    before=store.path.read_bytes()
    assert store.chains()==[] and store.runs()==[]
    assert store.path.read_bytes()==before


def test_definition_crud_is_versioned_and_does_not_upsert_by_name(store):
    chain=store.save_chain(draft());assert chain["version"]==1
    with pytest.raises(SequenceConflict):store.save_chain(draft())
    updated=store.save_chain({**draft(),"title":"Überarbeitete Folge"},chain_id=chain["id"],expected_version=1)
    assert updated["version"]==2
    with pytest.raises(SequenceConflict):store.save_chain(draft(),chain_id=chain["id"],expected_version=1)
    with pytest.raises(SequenceConflict):store.delete_chain(chain["id"],1)
    store.delete_chain(chain["id"],2);assert store.chains()==[]


@pytest.mark.parametrize("change", [{"steps":[]},{"mode":"fake"},{"steps":[{"label":"A","agent_slot":"../unsafe"}]},{"unknown":1},{"steps":[{"label":"A","agent_slot":"buddha_research","skill_ids":[{}]}]}])
def test_bad_definitions_are_rejected_without_schema_mutation(store,change):
    with pytest.raises(ValueError):store.save_chain({**draft(),**change})
    assert store.chains()==[]


def test_real_engine_uses_result_and_exactly_one_native_start_per_step(store,profiles):
    controller,transport=service(store,profiles);chain=store.save_chain(draft());payload=start_payload(chain)
    before=slots.sequence_profile_snapshot(["buddha_research","buddha_developer"])["profiles"]
    admitted=controller.start(chain["id"],payload);run=wait(controller,payload["request_id"])
    assert admitted["accepted"] is True and run["phase"]=="complete" and run["cursor"]==2
    assert len(transport.calls)==2 and "Ergebnis 1" in transport.calls[1][1]["custom_prompt"]
    assert run["completed"][1]["output"].startswith("Ergebnis 2")
    assert slots.sequence_profile_snapshot(list(before))["profiles"]==before
    with store.connection() as db:
        tasks=db.execute("SELECT status,assigned_slot,created_by FROM tasks ORDER BY id").fetchall()
        assert len(tasks)==2 and all(row["status"]=="done" and row["created_by"]=="user" for row in tasks)
        grants=db.execute("SELECT consumed_at,consumed_fence,worker_id FROM native_sequence_creator_delegations").fetchall()
        assert len(grants)==2 and all(row["consumed_at"] and row["consumed_fence"]==1
                                     and row["worker_id"].startswith("worker-") for row in grants)
    replay=controller.start(chain["id"],payload)
    assert replay["replayed"] is True and len(transport.calls)==2


@pytest.mark.parametrize("mode", ["agents", "skills"])
def test_skill_mode_keeps_one_approved_agent_and_pins_each_skill(store,profiles,monkeypatch,tmp_path,mode):
    root=tmp_path/"skills"
    monkeypatch.setenv("BACH_USER_SKILLS_ROOT",str(root))
    monkeypatch.setenv("BACH_SKILLS_ROOTS","[]")
    versions={"native-a":"1.0.0","native-b":"2.1.0"}
    expected=[]
    for skill_id,version in versions.items():
        source=root/skill_id/"SKILL.md"
        source.parent.mkdir(parents=True)
        source.write_text(f"---\nname: {skill_id}\nversion: {version}\n---\n\nPrüfanleitung für {skill_id}.\n",encoding="utf-8")
        skill=skill_source_service.read_skill(skill_id)
        expected.append([{"id":skill_id,"source_version":skill["source_version"],"version":version}])
    read=native.read_skill
    reads=[]
    def read_once(skill_id):
        reads.append(skill_id)
        return read(skill_id)
    monkeypatch.setattr(native,"read_skill",read_once)
    controller,transport=service(store,profiles)
    document=draft(mode)
    for step,skill_id in zip(document["steps"],versions):
        step["skill_ids"]=[skill_id]
    chain=store.save_chain(document);payload=start_payload(chain)
    controller.start(chain["id"],payload);run=wait(controller,payload["request_id"])
    assert run["phase"]=="complete" and len(transport.calls)==2
    assert reads==list(versions)
    saved=store.run(run["run_id"])
    expected_agents=["buddha_research"]*2 if mode=="skills" else ["buddha_research","buddha_developer"]
    assert [step["agent_slot"] for step in saved["plan"]["steps"]]==expected_agents
    assert [step["skill_refs"] for step in saved["plan"]["steps"]]==expected
    for index,step in enumerate(saved["plan"]["steps"]):
        assert skill_source_service.validate_skill_refs(step["skill_refs"])==expected[index]
        assert "Prüfanleitung für "+step["skill_refs"][0]["id"] in skill_source_service.load_skill_instructions(step["skill_refs"])
        assert slots.get_system_slot(transport.calls[index][0])["skill_refs"]==expected[index]


@pytest.mark.parametrize("fault",["result","receipt"])
def test_missing_result_or_foreign_generation_never_admits_next_step(store,profiles,fault):
    controller,transport=service(store,profiles);transport.fail_result=fault=="result";transport.foreign_receipt=fault=="receipt"
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
    if fault == "result":
        assert transport.observed.wait(5)
        run=controller.get_run(payload["request_id"])
        assert controller._threads[payload["request_id"]].is_alive()
        assert run["cursor"] == 0 and len(transport.calls) == 1
        assert run["result_wait"] == "task_result_unconfirmed"
        transport.fail_result=False
        run=wait(controller,payload["request_id"])
        assert run["phase"] == "complete" and len(transport.calls) == 2
        return
    run=wait(controller,payload["request_id"])
    assert len(transport.calls)==1 and run["cursor"]==0 and run["phase"] in {"failed","unconfirmed"}


def test_stop_is_durable_and_waits_for_the_exact_native_terminal(store,profiles):
    controller,transport=service(store,profiles);transport.hold=True
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
    assert transport.observed.wait(5)
    controller.stop(payload["request_id"]);run=wait(controller,payload["request_id"])
    assert run["phase"]=="stopped" and run["stop_requested"] is True
    assert len(transport.calls)==1 and transport.cancelled==[transport.calls[0][0]]


def test_no_mutation_of_a_chain_with_a_live_run(store,profiles):
    controller,transport=service(store,profiles);transport.hold=True
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload);assert transport.observed.wait(5)
    try:
        with pytest.raises(SequenceConflict):store.delete_chain(chain["id"],chain["version"])
        with pytest.raises(SequenceConflict):store.save_chain(draft(),chain_id=chain["id"],expected_version=chain["version"])
        with pytest.raises(SequenceConflict):controller.start(chain["id"],start_payload(chain))
    finally:controller.stop(payload["request_id"]);wait(controller,payload["request_id"])


def test_stale_living_cas_fails_before_task_or_run_creation(store,profiles):
    controller,transport=service(store,profiles);chain=store.save_chain(draft());payload=start_payload(chain)
    slots.change_core_system_agent("buddha_research",payload["configuration_version"],{"name":"Andere Besetzung"})
    with pytest.raises(RuntimeError):controller.start(chain["id"],payload)
    assert store.runs()==[] and transport.calls==[]


@pytest.mark.parametrize("change", [{"enabled":False},{"allowed_tools":["skill_manage"]},{"custom_role_prompt":"Neue Freigabe"}])
def test_source_change_between_precheck_and_materialization_never_starts_worker(store,profiles,monkeypatch,change):
    controller,transport=service(store,profiles);chain=store.save_chain(draft());payload=start_payload(chain)
    original=native.materialize_sequence_slot
    def changed(*args,**kwargs):
        snapshot=slots.core_system_agents_snapshot()
        slots.change_core_system_agent("buddha_research",snapshot["configuration_version"],change)
        return original(*args,**kwargs)
    monkeypatch.setattr(native,"materialize_sequence_slot",changed)
    controller.start(chain["id"],payload);run=wait(controller,payload["request_id"])
    assert run["phase"]=="unconfirmed" and transport.calls==[]
    assert not any(item.get("sequence_run_id") for item in slots.core_system_agents_snapshot()["agents"])


@pytest.mark.parametrize("fault",["before-checkpoint","after-checkpoint","before-bind","after-bind","after-admission"])
def test_stop_recovers_exact_admission_after_lost_checkpoint_or_binding_ack(store,profiles,monkeypatch,fault):
    controller,transport=service(store,profiles);transport.hold=True
    original_checkpoint=store.checkpoint;original_bind=store.bind_execution
    fired=False
    def checkpoint(state,service_id):
        nonlocal fired
        if "checkpoint" in fault and state.phase=="running" and not fired:
            fired=True
            if fault=="after-checkpoint":original_checkpoint(state,service_id)
            raise RuntimeError("Lost checkpoint ACK")
        return original_checkpoint(state,service_id)
    def bind(*args):
        nonlocal fired
        if "bind" in fault and not fired:
            fired=True
            if fault=="after-bind":original_bind(*args)
            raise RuntimeError("Lost binding ACK")
        return original_bind(*args)
    if fault=="after-admission":
        original_start=transport.gateway.start_worker
        def start(*args,**kwargs):
            original_start(*args,**kwargs)
            raise RuntimeError("Lost native start ACK")
        monkeypatch.setattr(transport.gateway,"start_worker",start)
    monkeypatch.setattr(store,"checkpoint",checkpoint);monkeypatch.setattr(store,"bind_execution",bind)
    chain=store.save_chain(draft());payload=start_payload(chain)
    controller.start(chain["id"],payload);run=wait(controller,payload["request_id"])
    assert run["phase"]=="unconfirmed" and len(transport.calls)==1
    controller.stop(payload["request_id"]);run=wait(controller,payload["request_id"])
    assert run["phase"]=="stopped" and run["stop_requested"] is True
    assert len(transport.calls)==1 and transport.cancelled==[transport.calls[0][0]]


def test_stop_racing_with_failed_running_checkpoint_needs_no_second_click(store,profiles,monkeypatch):
    controller,transport=service(store,profiles);transport.hold=True;original=store.checkpoint;fired=False
    def checkpoint(state,service_id):
        nonlocal fired
        if state.phase=="running" and not fired:
            fired=True;store.stop(state.run_id,service_id)
            raise RuntimeError("Running checkpoint lost during stop")
        return original(state,service_id)
    monkeypatch.setattr(store,"checkpoint",checkpoint)
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
    run=wait(controller,payload["request_id"])
    assert run["phase"]=="stopped" and len(transport.calls)==1 and len(transport.cancelled)==1


def test_pending_409_stop_keeps_observing_until_physical_terminal(store,profiles,monkeypatch):
    controller,transport=service(store,profiles);transport.hold=True;original_stop=transport.stop;original_observe=transport.observe
    observations_after_stop=0
    def stop(*args,**kwargs):
        _,worker,receipt,_=original_stop(*args,**kwargs)
        receipt.update(confirmed=False,outcome="revocation-pending")
        receipt["execution"].update(terminal=False,state="stopping")
        return False,worker,receipt,409
    def observe(worker_id,request):
        nonlocal observations_after_stop
        receipt=original_observe(worker_id,request)
        if worker_id in transport.cancelled:
            observations_after_stop+=1
            if observations_after_stop<=3:receipt.update(terminal=False,state="finishing")
        return receipt
    monkeypatch.setattr(transport.gateway,"stop_worker",stop);monkeypatch.setattr(transport.gateway,"observe_worker",observe)
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
    assert transport.observed.wait(5);controller.stop(payload["request_id"])
    run=wait(controller,payload["request_id"])
    assert run["phase"]=="stopped" and observations_after_stop==4 and len(transport.calls)==1


@pytest.mark.parametrize("fault",["observation","checkpoint"])
def test_stop_at_supervisor_exit_is_handed_over_without_second_click(store,profiles,monkeypatch,fault):
    controller,transport=service(store,profiles);transport.hold=True
    exited=threading.Event();release_exit=threading.Event();fired=False
    original_once=controller._execute_once;original_observe=transport.gateway.observe_worker;original_checkpoint=store.checkpoint
    def observe(*args):
        nonlocal fired
        if fault=="observation" and not fired:
            fired=True;raise ValueError("Transient observation failure")
        return original_observe(*args)
    def checkpoint(state,service_id):
        nonlocal fired
        if fault=="checkpoint" and state.phase=="running" and not fired:
            fired=True;raise RuntimeError("Lost running checkpoint")
        return original_checkpoint(state,service_id)
    once_count=0
    def execute_once(*args):
        nonlocal once_count
        once_count+=1;original_once(*args)
        if once_count==1:
            exited.set();assert release_exit.wait(5)
    monkeypatch.setattr(controller,"_execute_once",execute_once)
    monkeypatch.setattr(transport.gateway,"observe_worker",observe);monkeypatch.setattr(store,"checkpoint",checkpoint)
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
    try:
        assert exited.wait(5)
        assert controller.get_run(payload["request_id"])["phase"]=="unconfirmed"
        controller.stop(payload["request_id"])
    finally:release_exit.set()
    run=wait(controller,payload["request_id"])
    assert run["phase"]=="stopped" and once_count==2
    assert len(transport.calls)==1 and transport.cancelled==[transport.calls[0][0]]


@pytest.mark.parametrize("fault",["outcome","generation","controller"])
def test_unrelated_409_stop_never_counts_as_pending_acceptance(store,profiles,monkeypatch,fault):
    controller,transport=service(store,profiles);transport.hold=True;original=transport.stop
    def stop(*args,**kwargs):
        _,worker,receipt,_=original(*args,**kwargs)
        receipt.update(confirmed=False,outcome="revocation-pending")
        receipt["execution"].update(terminal=False,state="stopping")
        if fault=="outcome":receipt["outcome"]="execution-conflict"
        elif fault=="generation":receipt["execution"]["generation"]="f"*32
        else:receipt["execution"]["service_instance"]="f"*32
        return False,worker,receipt,409
    monkeypatch.setattr(transport.gateway,"stop_worker",stop)
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
    assert transport.observed.wait(5);controller.stop(payload["request_id"])
    run=wait(controller,payload["request_id"])
    assert run["phase"]=="unconfirmed" and "cancellation_unconfirmed" in run["reason"] and len(transport.calls)==1


@pytest.mark.parametrize("field,value",[("generation","f"*32),("service_instance","f"*32),("start_request_id","f"*32)])
def test_stop_reconciliation_rejects_a_foreign_admission(store,profiles,monkeypatch,field,value):
    controller,transport=service(store,profiles);transport.hold=True;original=store.checkpoint;fired=False
    def checkpoint(state,service_id):
        nonlocal fired
        if state.phase=="running" and not fired:
            fired=True;raise RuntimeError("Checkpoint lost")
        return original(state,service_id)
    monkeypatch.setattr(store,"checkpoint",checkpoint)
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
    wait(controller,payload["request_id"]);worker_id=transport.calls[0][0];transport.receipts[worker_id][field]=value
    controller.stop(payload["request_id"]);run=wait(controller,payload["request_id"])
    assert run["phase"]=="unconfirmed" and transport.cancelled==[] and len(transport.calls)==1


def test_exact_binding_retry_is_idempotent_but_another_generation_is_rejected(store):
    chain=store.save_chain(draft());request="b"*32
    store.create_run("a"*32,chain["id"],chain["version"],"f"*64,"d"*32,native.MARBLERUN_COMMIT,{"steps":[{}]})
    step=store.prepare_step("a"*32,0,request,"system-sequence-"+"a"*32+"-0","Analyse","Isoliert","model",
        backend="openrouter",service="d"*32)
    handle=embedded.ExecutionHandle(request,"c"*32,"d"*32)
    store.bind_execution("a"*32,0,handle);store.bind_execution("a"*32,0,handle)
    with pytest.raises(SequenceConflict):store.bind_execution("a"*32,0,embedded.ExecutionHandle(request,"e"*32,"d"*32))
    with store.connection() as db:
        assert db.execute("SELECT assigned_to FROM tasks WHERE id=?",(step["task_id"],)).fetchone()[0]=="OPENROUTER"


def test_restart_reports_unconfirmed_and_does_not_replay_dispatch(store,profiles):
    store.initialize();chain=store.save_chain(draft());controller,transport=service(store,profiles)
    store.create_run("b"*32,chain["id"],chain["version"],"c"*64,"old-service",native.MARBLERUN_COMMIT,{"steps":[]})
    run=controller.get_run("b"*32)
    assert run["phase"]=="unconfirmed" and run["runtime_verified"] is False
    with pytest.raises(SequenceConflict):controller.stop("b"*32)
    assert transport.calls==[]


def test_task_and_step_binding_roll_back_together(store):
    chain=store.save_chain(draft())
    store.create_run("a"*32,chain["id"],chain["version"],"f"*64,"d"*32,native.MARBLERUN_COMMIT,{"steps":[{}]})
    with store.connection(write=True) as db:db.execute("CREATE TRIGGER refuse_step BEFORE INSERT ON native_sequence_steps BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.prepare_step("a"*32,0,"b"*32,"system-sequence-"+"a"*32+"-0","Analyse","Isoliert","model",service="d"*32)
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM native_sequence_creator_delegations").fetchone()[0]==0


def test_semantic_output_is_atomic_with_review_and_requires_separate_acceptance(binding,mem_db):
    binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":"Tatsächliches Ergebnis · üöäß"})
    record=binding.submitted_result
    history=mem_db.execute("SELECT new_value FROM task_history WHERE task_id=? AND action='lease_release'",(binding.task_id,)).fetchone()
    release=json.loads(history[0])
    assert release["result_ref"] == f"bach-task-result:{record['result_id']}:{record['result_sha256']}"
    assert record["result"]=="Tatsächliches Ergebnis · üöäß"
    assert binding.completion_result is None and binding._client.task_snapshot(binding.task_id)["status"]=="review"
    approve_result(binding)
    assert binding.completion_result["accepted"] is True
    assert binding._client.task_snapshot(binding.task_id)["status"]=="done"


@pytest.mark.parametrize("value",["",True,{},"x"*3001,"\nx"*1501])
def test_invalid_output_never_completes_a_task(binding,value):
    with pytest.raises(LeaseProtocolError):binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":value})
    assert not binding.completed_task_ids and binding.completion_result is None
    assert binding._client.task_snapshot(binding.task_id)["status"]=="in_progress"


def test_lost_submission_ack_reconstructs_exact_review_without_mutation_retry(binding,monkeypatch):
    original=binding._client.submit_result
    calls=[]
    def lost(*args,**kw):
        calls.append((args,kw));original(*args,**kw);raise LeaseConnectionError("lost ack")
    monkeypatch.setattr(binding._client,"submit_result",lost)
    with pytest.raises(LeaseConnectionError):binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":"Ergebnis"})
    assert binding.completion_result is None and not binding.completed_task_ids
    assert binding.reviewed_task_ids == (binding.task_id,) and len(calls) == 1
    assert binding.closed and binding.submitted_result["result"] == "Ergebnis"
    approve_result(binding)
    assert binding.completed_task_ids == (binding.task_id,) and len(calls) == 1


def test_unregistered_module_revision_is_rejected(monkeypatch):
    monkeypatch.setattr(native.importlib.metadata,"distribution",lambda _name:SimpleNamespace(read_text=lambda _file:'{}'))
    with pytest.raises(RuntimeError):native.embedded_module()


def test_gui_without_device_request_never_dispatches_or_writes():
    from gui.api import unified_api
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:asyncio.run(unified_api.execute_marblerun_chain(1,{"input":"fixture"}))
    assert failure.value.status_code==401


def test_result_handoff_requires_physical_thread_end_and_exact_request(binding,monkeypatch):
    from hub._services.chat import telegram_chat as control
    binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":"Fachliches Ergebnis"})
    approve_result(binding)
    run=control._WorkerControl("owned-worker",generation=binding.generation,start_request_id="a"*32)
    run.task_binding=binding
    control._retain_worker_task_receipts(run)
    run.done_event.set();run.thread=SimpleNamespace(is_alive=lambda:True)
    monkeypatch.setattr(control,"_WORKER_EXECUTIONS",{"owned-worker":run})
    with pytest.raises(ValueError):control.worker_execution_result("owned-worker","a"*32,binding.generation,binding.task_id)
    run.thread=SimpleNamespace(is_alive=lambda:False)
    with pytest.raises(ValueError):control.worker_execution_result("owned-worker","b"*32,binding.generation,binding.task_id)
    assert control.worker_execution_result("owned-worker","a"*32,binding.generation,binding.task_id)["result"]=="Fachliches Ergebnis"
