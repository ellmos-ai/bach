"""Observe actual native admission/worker lifetime without live inference."""
import importlib
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from system.tests.test_task_lease_client import mem_db

from hub._services.chat.chat_runtime import ChatSession
from hub._services.chat.slots_config import initialize_slots_config, add_worker, get_worker_slot, update_slot


@pytest.mark.parametrize("reason", ["disabled", "missing", "unreadable"])
def test_pre_reservation_denial_has_correlated_no_admission_proof(admission, monkeypatch, reason):
    control, worker = admission
    def slot(_ident):
        if reason == "unreadable": raise ValueError("No config")
        return None if reason == "missing" else {**worker, "enabled": False}
    monkeypatch.setattr(control, "_execution_worker_slot", slot)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: pytest.fail("No denied admission"))
    result, code = control.start_worker_execution(worker["id"], start_request_id="6" * 32,
        expected_service_instance=control._WORKER_SERVICE_INSTANCE)
    assert code in {403, 404, 503}
    assert result["admission"] == {"admitted": False, "worker_id": worker["id"],
        "start_request_id": "6" * 32, "service_instance": control._WORKER_SERVICE_INSTANCE}
    assert not control._WORKER_EXECUTIONS


@pytest.fixture
def admission(tmp_path, monkeypatch):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    path = str(tmp_path / "slots.json")
    initialize_slots_config(path)
    from hub._services.chat import slots_config
    monkeypatch.setattr(slots_config, "DEFAULT_SLOTS_FILE", path)
    worker = add_worker({"name": "Admission", "type": "once"}, path)
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    monkeypatch.setattr(control, "_ACTIVE_WORKER_THREADS", {})
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {}, raising=False)
    monkeypatch.setattr(control, "get_worker_slot", lambda ident: get_worker_slot(ident, path))
    monkeypatch.setattr(control, "update_slot", lambda ident, changes: update_slot(ident, changes, path))
    monkeypatch.setattr(control, "record_activity", lambda *args, **kw: None)
    monkeypatch.setattr(control, "_snapshot_chat_backend", lambda *args, **kw: (object(), "test-model"))
    monkeypatch.setattr(control, "_acquire_worker_task", lambda *args: None)
    monkeypatch.setattr(control.runtime, "get_session", lambda ident: ChatSession())
    async def forbidden(*args, **kw): pytest.fail("No inference without actual Task Acquire")
    monkeypatch.setattr(control.runtime, "process", forbidden)
    return control, worker


def test_agent_manager_starts_dynamic_worker_through_actual_controller(admission, tmp_path, monkeypatch):
    import sqlite3
    from hub._services.agent_manage_service import AgentManager
    from hub._services.chat import slots_config
    control, worker = admission
    update_slot(worker["id"], {"mode": "safe", "allowed_tools": ["read_file"]})
    database = tmp_path / "canonical.db"
    with sqlite3.connect(database) as conn: conn.execute("CREATE TABLE fixture (id INTEGER)")
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *args, **kw: None)
    manager = AgentManager(db_path=database, execution_receipt=control.worker_execution_receipt,
        start_worker=control.start_worker_execution, local_provider=lambda slot: True, guard=lambda path: None)
    result = manager({"action": "start_local", "slot_id": worker["id"],
        "configuration_version": slots_config.core_system_agents_snapshot()["configuration_version"]},
        mode="safe", allowed_tools={"read_file"})
    assert result["execution"]["worker_thread_started"] is True
    execution = control._WORKER_EXECUTIONS[worker["id"]]
    execution.thread.join(3)
    receipt = control.worker_execution_receipt(worker["id"], result["execution"]["start_request_id"])
    assert receipt["terminal"] is True and receipt["completed_task_ids"] == []


def test_pending_role_admission_is_visible_and_serialized(admission, monkeypatch):
    control, worker = admission
    entered, release = threading.Event(), threading.Event()
    assignments, endings, results = [], [], []
    def begin(**kw):
        assignments.append(kw)
        entered.set()
        assert release.wait(10)
        return kw
    monkeypatch.setattr(control, "begin_assignment", begin)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kw: endings.append(kw))
    def start():
        try: results.append(control.start_worker_execution(worker["id"], start_request_id="a" * 32))
        except Exception as exc: results.append(exc)
    caller = threading.Thread(target=start)
    caller.start()
    try:
        assert entered.wait(2), results
        pending = control.worker_execution_receipt(worker["id"], "a" * 32)
        assert pending["state"] == "starting" and pending["terminal"] is False
        assert pending["worker_thread_started"] is False
        duplicate, code = control.start_worker_execution(worker["id"], start_request_id="b" * 32)
        assert code == 409 and duplicate["status"] == "starting"
        assert len(assignments) == 1
        same, code = control.start_worker_execution(worker["id"], start_request_id="a" * 32)
        assert code == 202 and same["execution"]["start_request_id"] == "a" * 32
        assert len(assignments) == 1
    finally:
        release.set()
        caller.join(3)
    assert not caller.is_alive() and results[0][1] == 200
    ctrl = control._WORKER_EXECUTIONS[worker["id"]]
    ctrl.thread.join(3)
    assert not ctrl.thread.is_alive()
    terminal = control.worker_execution_receipt(worker["id"], "a" * 32)
    assert terminal["state"] == "terminal" and terminal["terminal"] is True
    assert terminal["worker_thread_started"] is True
    assert terminal["completed_task_ids"] == []
    replay, code = control.start_worker_execution(worker["id"], start_request_id="a" * 32)
    assert code == 200 and replay["execution"]["terminal"] is True and len(assignments) == 1
    assert len(endings) == 1


def test_stop_during_role_admission_prevents_worker_launch(admission, monkeypatch):
    control, worker = admission
    entered, release = threading.Event(), threading.Event()
    results, endings, acquisitions = [], [], []
    def begin(**kw):
        entered.set()
        assert release.wait(10)
        return kw
    monkeypatch.setattr(control, "begin_assignment", begin)
    monkeypatch.setattr(control, "finish_assignment", lambda assignment, **kw: endings.append(kw))
    monkeypatch.setattr(control, "_WORKER_STOP_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(control, "_acquire_worker_task", lambda *args: acquisitions.append(args))
    caller = threading.Thread(target=lambda: results.append(
        control.start_worker_execution(worker["id"], start_request_id="c" * 32)))
    caller.start()
    try:
        assert entered.wait(2)
        confirmed, updated, receipt, code = control._request_worker_revocation(
            worker["id"], worker, requested_status="paused")
        assert not confirmed and code == 409 and receipt["confirmed"] is False
    finally:
        release.set()
        caller.join(3)
    assert not caller.is_alive() and results[0][1] == 409
    terminal = control.worker_execution_receipt(worker["id"], "c" * 32)
    assert terminal["terminal"] is True and terminal["worker_thread_started"] is False
    assert terminal["worker_status"] == "paused"
    assert acquisitions == [] and endings[0]["status"] == "interrupted"


def test_unknown_thread_launch_cannot_be_retried(admission, monkeypatch):
    control, worker = admission
    starts = []
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: starts.append(kw) or kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *args, **kw: pytest.fail("Unknown physical launch"))
    class UnconfirmedThread:
        def __init__(self, **kw): pass
        def start(self): raise OSError("unconfirmed test launch")
        def is_alive(self): return False
    monkeypatch.setattr(control.threading, "Thread", UnconfirmedThread)
    result, code = control.start_worker_execution(worker["id"], start_request_id="d" * 32)
    assert code == 503 and "error" in result
    observed = control.worker_execution_receipt(worker["id"], "d" * 32)
    assert observed["state"] == "unconfirmed" and observed["terminal"] is False
    assert observed["worker_thread_started"] is None
    result, code = control.start_worker_execution(worker["id"], start_request_id="e" * 32)
    assert code == 409 and len(starts) == 1


def test_known_admission_denial_is_terminal_and_correlated(admission, monkeypatch):
    control, worker = admission
    calls = []
    def denied(**kw):
        calls.append(kw)
        raise ValueError("synthetic incomplete role")
    monkeypatch.setattr(control, "begin_assignment", denied)
    result, code = control.start_worker_execution(worker["id"], start_request_id="f" * 32)
    assert code == 400
    observed = control.worker_execution_receipt(worker["id"], "f" * 32)
    assert observed["terminal"] is True and observed["worker_thread_started"] is False
    with pytest.raises(ValueError):
        control.worker_execution_receipt(worker["id"], "0" * 32)
    result, code = control.start_worker_execution(worker["id"], start_request_id="f" * 32)
    assert code == 200 and len(calls) == 1


def test_worker_body_receipt_does_not_replace_actual_thread_termination(admission, monkeypatch):
    control, worker = admission
    real_thread = threading.Thread
    tail_entered, tail_release = threading.Event(), threading.Event()
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *args, **kw: None)
    def factory(target, **kw):
        def body():
            target()
            tail_entered.set()
            assert tail_release.wait(10)
        return real_thread(target=body, **kw)
    monkeypatch.setattr(control.threading, "Thread", factory)
    result, code = control.start_worker_execution(worker["id"], start_request_id="1" * 32)
    ctrl = control._WORKER_EXECUTIONS[worker["id"]]
    try:
        assert code == 200 and tail_entered.wait(2)
        assert ctrl.done_event.is_set() and ctrl.thread.is_alive()
        observed = control.worker_execution_receipt(worker["id"], "1" * 32)
        assert observed["state"] == "finishing" and observed["terminal"] is False
        owner, physical = control._active_worker_control(worker["id"])
        assert owner is ctrl and physical is ctrl.thread
        result, code = control.start_worker_execution(worker["id"], start_request_id="2" * 32)
        assert code == 409
    finally:
        tail_release.set()
        ctrl.thread.join(3)
    assert not ctrl.thread.is_alive()
    assert control.worker_execution_receipt(worker["id"], "1" * 32)["terminal"] is True


def test_start_service_instance_and_request_types_are_checked_before_role(admission, monkeypatch):
    control, worker = admission
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: pytest.fail("Uncorrelated admission"))
    result, code = control.start_worker_execution(worker["id"], start_request_id="3" * 32,
        expected_service_instance="0" * 32)
    assert code == 409 and result["error_code"] == "service_instance_conflict"
    for malformed in (True, "", "z" * 32, "a" * 33):
        assert control.start_worker_execution(worker["id"], start_request_id=malformed)[1] == 400
    assert control._WORKER_EXECUTIONS == {}


def test_execution_readback_requires_auth_and_exact_request(admission, monkeypatch):
    control, worker = admission
    handler = control.ControlHandler.__new__(control.ControlHandler)
    handler.path = "/api/workers/execution?id=" + worker["id"]
    responses = []
    monkeypatch.setattr(handler, "_json", lambda body, code=200: responses.append((body, code)))
    monkeypatch.setattr(handler, "_allow_control_request", lambda: False)
    handler.do_GET()
    assert responses == []
    monkeypatch.setattr(handler, "_allow_control_request", lambda: True)
    handler.do_GET()
    assert responses[-1][1] == 200 and responses[-1][0]["execution"]["state"] == "idle"
    assert responses[-1][0]["execution"]["service_instance"] == control._WORKER_SERVICE_INSTANCE
    handler.path += "&start_request_id=" + "4" * 32
    handler.do_GET()
    assert responses[-1][1] == 409


def test_missing_cleanup_after_thread_exit_is_unconfirmed(admission, monkeypatch):
    control, worker = admission
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *args, **kw: None)
    result, code = control.start_worker_execution(worker["id"], start_request_id="5" * 32)
    ctrl = control._WORKER_EXECUTIONS[worker["id"]]
    ctrl.thread.join(3)
    assert not ctrl.thread.is_alive()
    ctrl.done_event.clear()  # Simulate missing proof of the complete cleanup.
    observed = control.worker_execution_receipt(worker["id"], "5" * 32)
    assert observed["state"] == "unconfirmed" and observed["terminal"] is False


def _system_fixture_worker():
    from hub._services.chat import slots_config as slots
    result = slots.materialize_system_blueprint(811, 1,
        {"worker_type": "once", "model": "owned-local", "mode": "safe"},
        slots.core_system_agents_snapshot()["configuration_version"])
    return slots.get_system_slot(result["slot_id"])


@pytest.mark.parametrize("mutation", ["delete", "materialize"])
@pytest.mark.parametrize("versioned_start", [False, True])
def test_admission_invalidates_idle_mutation_before_worker_status_write(
        admission, monkeypatch, mutation, versioned_start):
    from hub._services.chat import slots_config as slots
    control, _ = admission
    worker = _system_fixture_worker()
    before = slots.core_system_agents_snapshot()["configuration_version"]
    entered, release = threading.Event(), threading.Event()
    results = []

    def begin(**kw):
        entered.set()
        assert release.wait(10)
        return kw

    monkeypatch.setattr(control, "begin_assignment", begin)
    monkeypatch.setattr(control, "finish_assignment", lambda *a, **kw: None)
    caller = threading.Thread(target=lambda: results.append(control.start_worker_execution(
        worker["id"], start_request_id="7" * 32,
        expected_configuration_version=before if versioned_start else None)))
    caller.start()
    try:
        assert entered.wait(3), results
        assert slots.get_system_slot(worker["id"])["status"] == "idle"
        assert slots.core_system_agents_snapshot()["configuration_version"] != before
        observed = control._system_slots_snapshot()
        current = next(a for a in observed["agents"] if a["id"] == worker["id"])
        assert current["execution"]["state"] == "starting"
        assert current["execution"]["terminal"] is False
        with pytest.raises(RuntimeError, match="configuration_version_conflict"):
            if mutation == "delete":
                slots.delete_system_slot(worker["id"], before)
            else:
                slots.materialize_system_blueprint(811, 2, {"worker_type": "once"}, before)
        assert slots.get_system_slot(worker["id"])["blueprint_version"] == 1
    finally:
        release.set()
        caller.join(3)
        execution = control._WORKER_EXECUTIONS.get(worker["id"])
        if execution and hasattr(execution.thread, "join"):
            execution.thread.join(3)
    assert not caller.is_alive() and results[0][1] == 200


def test_snapshot_waits_for_revision_and_ram_admission_publication(admission, monkeypatch):
    from hub._services.chat import slots_config as slots
    control, _ = admission
    worker = _system_fixture_worker()
    original = slots.worker_admission_transaction
    written, release, attempted, observed = (threading.Event() for _ in range(4))
    results, snapshots = [], []

    @contextmanager
    def transaction(*a, **kw):
        with original(*a, **kw) as advance:
            def held_advance():
                advance()
                written.set()
                assert release.wait(10)
            yield held_advance

    monkeypatch.setattr(slots, "worker_admission_transaction", transaction)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: (_ for _ in ()).throw(ValueError("fixture denial")))

    def snapshot():
        attempted.set()
        snapshots.append(control._system_slots_snapshot())
        observed.set()

    caller = threading.Thread(target=lambda: results.append(control.start_worker_execution(
        worker["id"], start_request_id="8" * 32)))
    reader = threading.Thread(target=snapshot)
    caller.start()
    try:
        assert written.wait(3)
        reader.start()
        assert attempted.wait(3)
        assert not observed.wait(.05)
    finally:
        release.set()
        caller.join(3)
        if reader.ident is not None:
            reader.join(3)
    assert not caller.is_alive() and not reader.is_alive()
    assert results[0][1] == 400
    instance = next(a for a in snapshots[0]["agents"] if a["id"] == worker["id"])
    assert instance["execution"]["start_request_id"] == "8" * 32
    assert instance["execution"]["state"] in {"starting", "terminal"}


def test_revision_write_failure_prevents_any_ram_admission(admission, monkeypatch):
    from hub._services.chat import slots_config as slots
    control, worker = admission
    monkeypatch.setattr(slots, "save_slots_config", lambda *a, **kw: (_ for _ in ()).throw(OSError("fixture write denied")))
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: pytest.fail("No admission without durable revision"))
    result, code = control.start_worker_execution(worker["id"], start_request_id="9" * 32)
    assert code == 503 and result["admission"]["admitted"] is False
    assert not control._WORKER_CONTROLS and not control._WORKER_EXECUTIONS
    assert not control._ACTIVE_WORKER_THREADS


def test_denied_admission_does_not_restore_old_token_and_replay_does_not_revise(admission, monkeypatch):
    from hub._services.chat import slots_config as slots
    control, worker = admission
    before = slots.core_system_agents_snapshot()["configuration_version"]
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: (_ for _ in ()).throw(ValueError("fixture denial")))
    assert control.start_worker_execution(worker["id"], start_request_id="a" * 32)[1] == 400
    after = slots.core_system_agents_snapshot()["configuration_version"]
    assert before != after
    assert control.start_worker_execution(worker["id"], start_request_id="a" * 32)[1] == 200
    assert slots.core_system_agents_snapshot()["configuration_version"] == after
    assert control.start_worker_execution(worker["id"], start_request_id="b" * 32)[1] == 400
    assert slots.core_system_agents_snapshot()["configuration_version"] != after


def test_system_snapshot_keeps_receipt_until_physical_cleanup_tail_ends(admission, monkeypatch):
    control, _ = admission
    worker = _system_fixture_worker()
    retained = control._WorkerControl(worker["id"], start_request_id="c" * 32)
    class Tail:
        alive = True
        def is_alive(self):
            return self.alive
    retained.thread = Tail()
    retained.worker_thread_started = True
    retained.done_event.set()
    control._WORKER_EXECUTIONS[worker["id"]] = retained
    assert worker["id"] not in control._WORKER_CONTROLS
    current = next(a for a in control._system_slots_snapshot()["agents"] if a["id"] == worker["id"])
    assert current["execution"]["state"] == "finishing" and current["execution"]["terminal"] is False
    retained.thread.alive = False
    current = next(a for a in control._system_slots_snapshot()["agents"] if a["id"] == worker["id"])
    assert current["execution"]["terminal"] is True
    never_started = next(a for a in control._system_slots_snapshot()["agents"] if a["id"] == "buddha_chat")
    assert never_started["execution"] is None


def test_admission_lock_blocks_a_separate_process_until_ram_publication_boundary(admission):
    from hub._services.chat import slots_config as slots
    _system_fixture_worker()
    before = slots.core_system_agents_snapshot()["configuration_version"]
    script = """import sys
from hub._services.chat import slots_config as slots
print('ready', flush=True)
try:
    slots.delete_system_slot('system-blueprint-811', sys.argv[2], path=sys.argv[1])
except RuntimeError as exc:
    assert str(exc) == 'configuration_version_conflict'
    print('conflict', flush=True)
else:
    raise AssertionError('Obsolete admission token accepted')
"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(Path(slots.__file__).resolve().parents[3])}
    child = None
    ready = threading.Event()
    reader = None
    try:
        with slots.worker_admission_transaction() as advance:
            advance()
            child = subprocess.Popen([sys.executable, "-c", script, slots.DEFAULT_SLOTS_FILE, before],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            def read_ready():
                if child.stdout.readline().strip() == "ready":
                    ready.set()
            reader = threading.Thread(target=read_ready, daemon=True)
            reader.start()
            assert ready.wait(5)
            reader.join(1)
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=.05)
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 0, stderr
        assert stdout.strip() == "conflict"
        assert slots.get_system_slot("system-blueprint-811")
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        if reader is not None:
            reader.join(1)


@pytest.fixture
def startup(admission, monkeypatch):
    from hub._services.chat import slots_config as slots
    from hub import rheingold
    from hub._services import agent_manage_service
    control, _worker = admission
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "lead"})
    monkeypatch.setattr(agent_manage_service, "verified_local_agent_model", lambda *_: True)
    monkeypatch.setattr(control, "begin_assignment", lambda **kw: kw)
    monkeypatch.setattr(control, "finish_assignment", lambda *_a, **_kw: None)
    slots.update_slot("buddha_always_on", {"backend": "ollama", "status": "idle"})
    yield control, slots
    for execution in tuple(control._WORKER_EXECUTIONS.values()):
        execution.stop_event.set()
        if execution.thread:
            execution.thread.join(3)
            assert not execution.thread.is_alive()


def test_startup_resumes_one_physical_always_on_and_preserves_empty_queue(startup):
    control, slots = startup
    stop = threading.Event()
    first = control._resume_always_on_at_startup(stop)
    assert first["state"] == "admitted" and first["retry"] is False
    execution = control._WORKER_EXECUTIONS["buddha_always_on"]
    assert execution.worker_thread_started is True and execution.thread.is_alive()
    generation = execution.generation
    again = control._resume_always_on_at_startup(stop)
    assert again["state"] == "existing_admission" and again["retry"] is False
    assert control._WORKER_EXECUTIONS["buddha_always_on"].generation == generation
    assert execution.thread.is_alive() and execution.task_binding is None
    assert slots.get_always_on_execution_slot()["status"] == "running"


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"status": "paused", "auto_paused": False},
    {"status": "stopping"}, {"status": "completed"}, {"status": "expired"},
    {"backend": "openrouter"}, {"backend": "ollama-cloud"},
    {"backend": "ollama", "model": "glm-5.3:cloud"},
])
def test_startup_preserves_manual_stop_and_never_starts_cloud(startup, changes):
    control, slots = startup
    slots.update_slot("buddha_always_on", changes)
    result = control._resume_always_on_at_startup(threading.Event())
    assert result["retry"] is False
    assert not control._WORKER_EXECUTIONS
    assert not control._ACTIVE_WORKER_THREADS


def test_startup_leaves_followers_and_isolated_hosts_idle(startup, monkeypatch):
    control, _slots = startup
    from hub import rheingold
    for mode in ("worker", "isolated", "invalid"):
        monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": mode})
        assert control._resume_always_on_at_startup(threading.Event())["state"] == "not_lead"
    assert not control._WORKER_EXECUTIONS


def test_startup_waits_for_verified_local_model_without_inference(startup, monkeypatch):
    control, _slots = startup
    from hub._services import agent_manage_service
    monkeypatch.setattr(agent_manage_service, "verified_local_agent_model", lambda *_: False)
    result = control._resume_always_on_at_startup(threading.Event())
    assert result == {"state": "waiting_local_model", "retry": True}
    assert not control._WORKER_EXECUTIONS


def test_startup_provider_check_cannot_authorize_changed_cloud_policy(startup, monkeypatch):
    control, slots = startup
    from hub._services import agent_manage_service
    def change_provider(*_):
        slots.update_slot("buddha_always_on", {"backend": "openrouter", "model": "openrouter/free"})
        return True
    monkeypatch.setattr(agent_manage_service, "verified_local_agent_model", change_provider)
    result = control._resume_always_on_at_startup(threading.Event())
    assert result["state"] == "configuration_changed" and result["retry"] is True
    assert not control._WORKER_EXECUTIONS


def test_startup_shutdown_during_provider_probe_prevents_admission(startup, monkeypatch):
    control, _slots = startup
    from hub._services import agent_manage_service
    stop = threading.Event()
    def shutdown(*_):
        stop.set()
        return True
    monkeypatch.setattr(agent_manage_service, "verified_local_agent_model", shutdown)
    result = control._resume_always_on_at_startup(stop)
    assert result == {"state": "shutdown", "retry": False}
    assert not control._WORKER_EXECUTIONS


def test_manual_always_on_stop_persists_pause_across_new_controller(startup):
    control, slots = startup
    slot = slots.get_always_on_execution_slot()
    confirmed, _, receipt, code = control._request_worker_revocation("buddha_always_on", slot)
    assert confirmed and code == 200 and receipt["final_status"] == "paused"
    assert slots.get_always_on_execution_slot()["status"] == "paused"
    assert control._resume_always_on_at_startup(threading.Event())["retry"] is False
    assert not control._WORKER_EXECUTIONS


def test_startup_hook_runs_after_http_bind_and_closes_its_monitor(startup, monkeypatch):
    control, _slots = startup
    monkeypatch.setattr(control, "CONTROL_PORT", 0)
    monkeypatch.setattr(control, "_control_bind_host", lambda: "127.0.0.1")
    server = control.start_control_api()
    assert server is not None and server.server_port > 0
    try:
        server.always_on_startup_thread.join(3)
        assert not server.always_on_startup_thread.is_alive()
        execution = control._WORKER_EXECUTIONS["buddha_always_on"]
        assert execution.thread.is_alive() and execution.worker_thread_started
        assert control.worker_execution_receipt("buddha_always_on")["service_instance"] == control._WORKER_SERVICE_INSTANCE
    finally:
        server.shutdown()
        server.server_close()
    assert server.always_on_startup_stop.is_set()


def test_startup_bind_failure_never_starts_any_worker(startup, monkeypatch):
    control, _slots = startup
    def occupied(*_):
        raise OSError("Port occupied")
    monkeypatch.setattr(control, "QuietHTTPServer", occupied)
    assert control.start_control_api() is None
    assert not control._WORKER_EXECUTIONS


def test_shutdown_closes_startup_monitor_waiting_for_local_model(startup, monkeypatch):
    control, _slots = startup
    from hub._services import agent_manage_service
    entered = threading.Event()
    def unavailable(*_):
        entered.set()
        return False
    monkeypatch.setattr(agent_manage_service, "verified_local_agent_model", unavailable)
    server = control.QuietHTTPServer(("127.0.0.1", 0), control.ControlHandler)
    control._start_always_on_startup_monitor(server)
    try:
        assert entered.wait(3)
        assert server.always_on_startup_thread.is_alive()
        assert not control._WORKER_EXECUTIONS
    finally:
        server.server_close()
    assert server.always_on_startup_stop.is_set()
    assert not server.always_on_startup_thread.is_alive()


def test_concurrent_startup_attempts_publish_only_one_physical_generation(startup, monkeypatch):
    control, _slots = startup
    entered, release = threading.Event(), threading.Event()
    def begin(**kw):
        entered.set()
        assert release.wait(5)
        return kw
    monkeypatch.setattr(control, "begin_assignment", begin)
    first = []
    caller = threading.Thread(target=lambda: first.append(control._resume_always_on_at_startup(threading.Event())))
    caller.start()
    try:
        assert entered.wait(3)
        generation = control._WORKER_EXECUTIONS["buddha_always_on"].generation
        second = control._resume_always_on_at_startup(threading.Event())
        assert second["state"] == "existing_admission" and not second["retry"]
        assert control._WORKER_EXECUTIONS["buddha_always_on"].generation == generation
    finally:
        release.set()
        caller.join(3)
    assert not caller.is_alive()
    assert first[0]["state"] == "admitted"
    assert control._WORKER_EXECUTIONS["buddha_always_on"].thread.is_alive()


def test_startup_uncertain_physical_launch_is_never_retried_as_cas(startup, monkeypatch):
    control, _slots = startup
    monkeypatch.setattr(control, "_start_worker_execution", lambda *_a, **_kw: (
        {"error": "Worker-Start nicht bestätigt", "execution": {"terminal": False}}, 503))
    result = control._resume_always_on_at_startup(threading.Event())
    assert result["state"] == "admission_unconfirmed" and not result["retry"]


def test_startup_read_only_policy_snapshot_preserves_original_bytes(startup):
    _control, slots = startup
    path = Path(slots.DEFAULT_SLOTS_FILE)
    before = path.read_bytes()
    expected_version = slots.core_system_agents_snapshot()["configuration_version"]
    policy = slots.always_on_startup_snapshot()
    assert policy["configuration_version"] == expected_version
    assert policy["slot"]["id"] == "buddha_always_on"
    assert path.read_bytes() == before


def test_startup_policy_and_version_use_only_one_file_image(startup, monkeypatch):
    _control, slots = startup
    import json
    path = Path(slots.DEFAULT_SLOTS_FILE)
    raw = path.read_bytes()
    changed = json.loads(raw.decode("utf-8"))
    changed["slots"]["buddha_always_on"]["backend"] = "openrouter"
    changed["slots"]["buddha_always_on"]["model"] = "openrouter/free"
    calls = []
    original = Path.read_bytes
    def racing_read(target):
        if target == path:
            calls.append(target)
            return raw if len(calls) == 1 else json.dumps(changed).encode("utf-8")
        return original(target)
    expected_version = slots.core_system_agents_snapshot()["configuration_version"]
    monkeypatch.setattr(Path, "read_bytes", racing_read)
    policy = slots.always_on_startup_snapshot()
    assert calls == [path]
    assert policy["configuration_version"] == expected_version
    assert policy["slot"]["backend"] == "ollama"


@pytest.mark.parametrize("elapsed", [False, True])
def test_startup_respects_automatic_pause_deadline(startup, elapsed):
    from datetime import datetime, timedelta, timezone
    control, slots = startup
    started = datetime.now(timezone.utc) - timedelta(minutes=31 if elapsed else 1)
    slots.update_slot("buddha_always_on", {"status": "paused", "auto_paused": True,
        "pause_started_at": started.isoformat(), "pause_minutes": 30})
    result = control._resume_always_on_at_startup(threading.Event())
    if elapsed:
        assert result["state"] == "admitted"
        assert control._WORKER_EXECUTIONS["buddha_always_on"].thread.is_alive()
    else:
        assert result == {"state": "waiting_cooldown", "retry": True}
        assert not control._WORKER_EXECUTIONS


def test_shutdown_event_is_checked_inside_native_reservation(startup):
    control, _slots = startup
    stop = threading.Event()
    stop.set()
    response, code = control._start_worker_execution("buddha_always_on", _startup_stop_event=stop)
    assert code == 409 and response["admission"]["admitted"] is False
    assert response["error_code"] == "startup_shutdown"
    assert not control._WORKER_EXECUTIONS


def test_shutdown_during_assignment_prevents_own_physical_generation(startup, monkeypatch):
    control, _slots = startup
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()
    def begin(**kw):
        entered.set()
        assert release.wait(5)
        return kw
    monkeypatch.setattr(control, "begin_assignment", begin)
    results = []
    caller = threading.Thread(target=lambda: results.append(control._resume_always_on_at_startup(stop)))
    caller.start()
    try:
        assert entered.wait(3)
        execution = control._WORKER_EXECUTIONS["buddha_always_on"]
        assert execution.stop_event is stop
        stop.set()
        release.set()
        caller.join(3)
        assert not caller.is_alive()
        assert execution.worker_thread_started is False
        assert execution.done_event.is_set()
        assert results[0]["state"] == "denied"
        assert results[0]["execution"]["terminal"] is True
    finally:
        stop.set()
        release.set()
        caller.join(3)


def test_policy_conflict_after_assignment_never_reports_activity(startup, monkeypatch):
    control, slots = startup
    def begin(**kw):
        slots.update_slot("buddha_always_on", {"model": "different-model"})
        return kw
    monkeypatch.setattr(control, "begin_assignment", begin)
    result = control._resume_always_on_at_startup(threading.Event())
    assert result["state"] == "denied" and result["retry"] is False
    assert result["execution"]["worker_thread_started"] is False
    assert result["execution"]["terminal"] is True


def test_server_close_signals_only_its_own_boot_generation(startup, monkeypatch):
    control, _slots = startup
    server = control.QuietHTTPServer(("127.0.0.1", 0), control.ControlHandler)
    control._start_always_on_startup_monitor(server)
    server.always_on_startup_thread.join(3)
    own = control._WORKER_EXECUTIONS["buddha_always_on"]
    foreign = control._WorkerControl("different-explicit-worker")
    control._WORKER_EXECUTIONS[foreign.worker_id] = foreign
    try:
        assert own.worker_thread_started and own.thread.is_alive()
        server.server_close()
        own.thread.join(3)
        assert own.stop_event.is_set() and not own.thread.is_alive()
        assert not foreign.stop_event.is_set()
    finally:
        control._WORKER_EXECUTIONS.pop(foreign.worker_id)


@pytest.fixture
def real_acquire_before_fixture():
    return importlib.import_module("hub._services.chat.telegram_chat")._acquire_worker_task


@pytest.fixture
def recovery(real_acquire_before_fixture, startup, monkeypatch, mem_db):
    from hub._services.task_lease_client import TaskLeaseClient
    from hub._services import task_lease_client as client_module
    control, slots = startup
    monkeypatch.setattr(client_module, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "600")
    client = TaskLeaseClient(conn=mem_db)
    mem_db.execute("ALTER TABLE tasks ADD COLUMN created_at TEXT")
    from hub._services import skill_source_service
    def fixture_lock_guard(target):
        assert Path(target) == Path(slots.DEFAULT_SLOTS_FILE)
        if list(Path(target).parent.glob("LOCK*.txt")):
            raise PermissionError("Fixture write lock")
    monkeypatch.setattr(skill_source_service, "check_write_locks", fixture_lock_guard)
    monkeypatch.setattr(control, "_native_task_client", lambda: client)
    slots.update_slot("buddha_always_on", {"task_id": 42, "status": "running"})
    execution = control._WorkerControl("buddha_always_on", startup_recovery=True)
    execution.slot_policy_reader = control._execution_slot_reader(slots.get_always_on_execution_slot())
    control._WORKER_CONTROLS[execution.worker_id] = execution
    control._WORKER_EXECUTIONS[execution.worker_id] = execution
    return control, slots, client, execution, real_acquire_before_fixture, mem_db


def test_crash_recovery_waits_for_real_held_lease_then_acquires_fresh_fence(recovery):
    control, slots, client, execution, acquire, db = recovery
    db.execute("INSERT INTO tasks(id,title,status,category,priority) VALUES(42,'Crash recovery','pending','INBOX','P1')")
    db.commit()
    old = client.acquire(42, worker_id="old-process@fixture", host="fixture")
    assert acquire(execution, slots.get_always_on_execution_slot(), "new-process") is None
    assert db.execute("SELECT claim_fence FROM tasks WHERE id=42").fetchone()[0] == old.fence
    client.release(42, lease_id=old.lease_id, fence=old.fence, outcome="return", task_version=old.task_version)
    fresh = acquire(execution, slots.get_always_on_execution_slot(), "new-process")
    try:
        assert fresh.task_id == 42
        assert fresh._ack.fence > old.fence
        fresh.assert_active()
        assert control._control_execution_receipt(execution)["completed_task_ids"] == []
    finally:
        fresh.return_lease()


def test_crash_recovery_preserves_real_creator_priority_window(recovery):
    from datetime import datetime, timezone
    control, slots, _client, execution, acquire, db = recovery
    db.execute("INSERT INTO tasks(id,title,status,created_by,created_at,category,priority) VALUES(42,'Creator priority','pending','external-user',?,'INBOX','P1')",
               (datetime.now(timezone.utc).isoformat(),))
    db.commit()
    assert acquire(execution, slots.get_always_on_execution_slot(), "new-process") is None
    row = db.execute("SELECT status,claim_fence FROM tasks WHERE id=42").fetchone()
    assert row["status"] == "pending" and row["claim_fence"] == 0
    assert control._control_execution_receipt(execution)["completed_task_ids"] == []


@pytest.mark.parametrize("status", ["done", "blocked", "cancelled", "completed"])
def test_crash_recovery_clears_only_canonically_terminal_old_task_pointer(recovery, status):
    control, slots, _client, execution, acquire, db = recovery
    db.execute("INSERT INTO tasks(id,title,status) VALUES(42,'Previous task',?)", (status,))
    db.commit()
    assert acquire(execution, slots.get_always_on_execution_slot(), "new-process") is None
    assert slots.get_always_on_execution_slot()["task_id"] is None
    assert db.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == status
    assert control._control_execution_receipt(execution)["completed_task_ids"] == []


def test_terminal_recovery_does_not_clear_intervening_new_task_pointer(recovery, monkeypatch):
    control, slots, client, execution, acquire, db = recovery
    db.execute("INSERT INTO tasks(id,title,status) VALUES(42,'Previous task','done')")
    db.commit()
    original = client.task_snapshot
    def intervening(task_id):
        snapshot = original(task_id)
        slots.update_slot("buddha_always_on", {"task_id": 43})
        return snapshot
    monkeypatch.setattr(client, "task_snapshot", intervening)
    assert acquire(execution, slots.get_always_on_execution_slot(), "new-process") is None
    assert slots.get_always_on_execution_slot()["task_id"] == 43
    assert control._control_execution_receipt(execution)["completed_task_ids"] == []


def test_terminal_recovery_write_lock_preserves_task_pointer_and_task_state(recovery):
    control, slots, _client, execution, acquire, db = recovery
    db.execute("INSERT INTO tasks(id,title,status) VALUES(42,'Previous task','done')")
    db.commit()
    path = Path(slots.DEFAULT_SLOTS_FILE)
    before = path.read_bytes()
    lock = path.parent / "LOCK.txt"
    lock.write_text("Fixture lock\n", encoding="utf-8")
    try:
        with pytest.raises(PermissionError):
            acquire(execution, slots.get_always_on_execution_slot(), "new-process")
        assert path.read_bytes() == before
        assert db.execute("SELECT status FROM tasks WHERE id=42").fetchone()[0] == "done"
        assert control._control_execution_receipt(execution)["completed_task_ids"] == []
    finally:
        lock.unlink()


@pytest.mark.parametrize("stamp", ["", "invalid", None])
def test_startup_unverifiable_automatic_pause_does_not_start(startup, stamp):
    control, slots = startup
    slots.update_slot("buddha_always_on", {"status": "paused", "auto_paused": True,
        "pause_started_at": stamp, "pause_minutes": 30})
    result = control._resume_always_on_at_startup(threading.Event())
    assert result == {"state": "invalid_cooldown", "retry": False}
    assert not control._WORKER_EXECUTIONS
