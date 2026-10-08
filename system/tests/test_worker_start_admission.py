"""Observe actual native admission/worker lifetime without live inference."""
import importlib
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
