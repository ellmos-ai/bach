"""Observe actual native admission/worker lifetime without live inference."""
import importlib
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

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
