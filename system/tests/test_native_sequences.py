"""Real pinned engine and isolated TaskLease authority; no live providers or DBs."""
import asyncio
import json
import sqlite3
import threading
import uuid
from types import SimpleNamespace

import pytest
from llmauto.core import embedded
from hub._services.chat import native_sequences as native, slots_config as slots
from hub._services.chat.sequence_store import SequenceStore, SequenceConflict, definition
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.task_lease_client import TaskLeaseClient, LeaseConnectionError, LeaseProtocolError
from hub._services import skill_source_service
from system.tests.test_task_lease_client import _init_db, mem_db
from system.tests.test_worker_lease_binding import binding


@pytest.fixture
def store(tmp_path):
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
    fields = {key: getattr(embedded, key) for key in ("SequenceStep", "SequenceState", "ExecutionHandle", "ExecutionObservation")}
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
        binding=WorkerLeaseBinding.acquire(client,slot["task_id"],worker_id="isolated-native@test",host="test",
            generation=generation,is_current=lambda:True,stop_event=threading.Event())
        output="Ergebnis "+str(len(self.calls))+" · Müller & Söhne"
        binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":output})
        self.results[worker_id]=binding.completion_result
        self.receipts[worker_id]={"schema":"bach.worker-execution.v1","service_instance":"a"*32,
            "worker_id":worker_id,"start_request_id":kwargs["start_request_id"],"generation":generation,
            "state":"terminal","terminal":True,"worker_thread_started":True,"completed_task_ids":[binding.task_id]}
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
        return True,{}, {},200


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
        tasks=db.execute("SELECT status,assigned_slot FROM tasks ORDER BY id").fetchall()
        assert len(tasks)==2 and all(row["status"]=="done" for row in tasks)
    replay=controller.start(chain["id"],payload)
    assert replay["replayed"] is True and len(transport.calls)==2


def test_skill_mode_keeps_one_approved_agent_and_pins_each_skill(store,profiles,monkeypatch):
    monkeypatch.setattr(native,"read_skill",lambda skill_id:{"id":skill_id,"source_version":"b"*64})
    monkeypatch.setattr(native,"load_skill_instructions",lambda pins:"skills")
    monkeypatch.setattr(skill_source_service,"load_skill_instructions",lambda pins:"skills")
    controller,transport=service(store,profiles);chain=store.save_chain(draft("skills"));payload=start_payload(chain)
    controller.start(chain["id"],payload);run=wait(controller,payload["request_id"])
    assert run["phase"]=="complete"
    saved=store.run(run["run_id"])
    assert [step["agent_slot"] for step in saved["plan"]["steps"]]==["buddha_research"]*2
    assert [step["skill_refs"][0]["id"] for step in saved["plan"]["steps"]]==["native-a","native-b"]


@pytest.mark.parametrize("fault",["result","receipt"])
def test_missing_result_or_foreign_generation_never_admits_next_step(store,profiles,fault):
    controller,transport=service(store,profiles);transport.fail_result=fault=="result";transport.foreign_receipt=fault=="receipt"
    chain=store.save_chain(draft());payload=start_payload(chain);controller.start(chain["id"],payload)
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


def test_restart_reports_unconfirmed_and_does_not_replay_dispatch(store,profiles):
    store.initialize();chain=store.save_chain(draft());controller,transport=service(store,profiles)
    store.create_run("b"*32,chain["id"],chain["version"],"c"*64,"old-service",native.MARBLERUN_COMMIT,{"steps":[]})
    run=controller.get_run("b"*32)
    assert run["phase"]=="unconfirmed" and run["runtime_verified"] is False
    with pytest.raises(SequenceConflict):controller.stop("b"*32)
    assert transport.calls==[]


def test_task_and_step_binding_roll_back_together(store):
    store.initialize()
    with store.connection(write=True) as db:db.execute("CREATE TRIGGER refuse_step BEFORE INSERT ON native_sequence_steps BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):store.prepare_step("a"*32,0,"b"*32,"worker","Analyse","Isoliert","model")
    with store.connection() as db:assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]==0


def test_semantic_output_is_atomic_with_the_done_release(binding,mem_db):
    binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":"Tatsächliches Ergebnis · üöäß"})
    record=binding.completion_result
    history=mem_db.execute("SELECT new_value FROM task_history WHERE task_id=? AND action='lease_release'",(binding.task_id,)).fetchone()
    note=json.loads(json.loads(history[0])["note"])
    assert note==record and record["result"]=="Tatsächliches Ergebnis · üöäß"
    assert binding._client.task_snapshot(binding.task_id)["status"]=="done"


@pytest.mark.parametrize("value",["",True,{},"x"*3001,"\nx"*1499])
def test_invalid_output_never_completes_a_task(binding,value):
    with pytest.raises(LeaseProtocolError):binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":value})
    assert not binding.completed_task_ids and binding.completion_result is None
    assert binding._client.task_snapshot(binding.task_id)["status"]=="in_progress"


def test_lost_done_ack_retains_neither_output_nor_completion_claim(binding,monkeypatch):
    original=binding._client.release
    def lost(*args,**kw):original(*args,**kw);raise LeaseConnectionError("lost ack")
    monkeypatch.setattr(binding._client,"release",lost)
    with pytest.raises(LeaseConnectionError):binding.execute_task_manage({"action":"done","task_id":binding.task_id,"result":"Ergebnis"})
    assert binding.completion_result is None and not binding.completed_task_ids


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
    run=control._WorkerControl("owned-worker",generation=binding.generation,start_request_id="a"*32)
    run.task_binding=binding
    control._retain_worker_task_receipts(run)
    run.done_event.set();run.thread=SimpleNamespace(is_alive=lambda:True)
    monkeypatch.setattr(control,"_WORKER_EXECUTIONS",{"owned-worker":run})
    with pytest.raises(ValueError):control.worker_execution_result("owned-worker","a"*32,binding.generation,binding.task_id)
    run.thread=SimpleNamespace(is_alive=lambda:False)
    with pytest.raises(ValueError):control.worker_execution_result("owned-worker","b"*32,binding.generation,binding.task_id)
    assert control.worker_execution_result("owned-worker","a"*32,binding.generation,binding.task_id)["result"]=="Fachliches Ergebnis"
