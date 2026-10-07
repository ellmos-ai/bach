"""Stop only the captured physical generation; never infer end from timeout."""
import importlib
import threading

import pytest


@pytest.fixture
def stopped_worker(monkeypatch):
    control = importlib.import_module("hub._services.chat.telegram_chat")
    slot = {"id": "buddha_always_on", "type": "continuous", "status": "running", "enabled": True}
    writes = []
    def update(_ident, changes):
        writes.append(dict(changes))
        slot.update(changes)
        return dict(slot)
    monkeypatch.setattr(control, "_WORKER_CONTROLS", {})
    monkeypatch.setattr(control, "_ACTIVE_WORKER_THREADS", {})
    monkeypatch.setattr(control, "_WORKER_EXECUTIONS", {})
    monkeypatch.setattr(control, "_execution_worker_slot", lambda _ident: dict(slot))
    monkeypatch.setattr(control, "update_slot", update)
    monkeypatch.setattr(control, "record_activity", lambda *_a, **_kw: None)
    monkeypatch.setattr(control, "_WORKER_STOP_WAIT_SECONDS", .01)
    worker = control._WorkerControl(slot["id"])
    worker.admitted_worker = {"id": slot["id"], "type": slot["type"]}
    worker.launch_attempted = True
    worker.worker_thread_started = True
    entered, release = threading.Event(), threading.Event()
    def body():
        entered.set()
        assert release.wait(5)
        with control._WORKER_CONTROL_LOCK:
            worker.done_event.set()
            control._WORKER_CONTROLS.pop(slot["id"], None)
            control._ACTIVE_WORKER_THREADS.pop(slot["id"], None)
    worker.thread = threading.Thread(target=body)
    control._WORKER_CONTROLS[slot["id"]] = worker
    control._WORKER_EXECUTIONS[slot["id"]] = worker
    control._ACTIVE_WORKER_THREADS[slot["id"]] = worker.thread
    worker.thread.start()
    assert entered.wait(2)
    expected = {"service_instance": control._WORKER_SERVICE_INSTANCE,
                "start_request_id": worker.start_request_id, "generation": worker.generation}
    try:
        yield control, worker, slot, writes, release, expected
    finally:
        release.set()
        worker.thread.join(3)
        assert not worker.thread.is_alive()


@pytest.mark.parametrize("field", ["service_instance", "start_request_id", "generation"])
def test_wrong_execution_fence_cannot_stop_or_write(stopped_worker, field):
    control, worker, slot, writes, _release, expected = stopped_worker
    expected = {**expected, field: "0" * 32}
    confirmed, _, receipt, code = control._request_worker_revocation(
        slot["id"], slot, expected_execution=expected)
    assert code == 409 and not confirmed
    assert not worker.stop_event.is_set() and writes == []
    assert receipt["confirmed"] is False and receipt["status_persisted"] is False


def test_matching_stop_remains_pending_until_actual_native_thread_end(stopped_worker):
    control, worker, slot, _writes, release, expected = stopped_worker
    confirmed, _, receipt, code = control._request_worker_revocation(
        slot["id"], slot, expected_execution=expected)
    assert code == 409 and not confirmed and worker.stop_event.is_set()
    assert receipt["execution"]["start_request_id"] == expected["start_request_id"]
    assert receipt["execution"]["terminal"] is False
    release.set()
    worker.thread.join(3)
    assert not worker.thread.is_alive()
    confirmed, _, receipt, code = control._request_worker_revocation(
        slot["id"], slot, expected_execution=expected)
    assert code == 200 and confirmed and receipt["execution"]["terminal"] is True


def test_control_selection_and_stop_request_share_the_lock(stopped_worker, monkeypatch):
    control, _worker, slot, _writes, _release, _expected = stopped_worker
    original = control._active_worker_control
    competitors = []
    def selection(ident):
        result = original(ident)
        entered, acquired = threading.Event(), threading.Event()
        def compete():
            entered.set()
            with control._WORKER_CONTROL_LOCK:
                acquired.set()
        competitor = threading.Thread(target=compete)
        competitors.append(competitor)
        competitor.start()
        assert entered.wait(2)
        assert not acquired.wait(.05), "Generation changed between selection and stop"
        return result
    monkeypatch.setattr(control, "_active_worker_control", selection)
    try:
        control._request_worker_revocation(slot["id"], slot)
    finally:
        for competitor in competitors:
            competitor.join(3)
            assert not competitor.is_alive()


def test_late_old_receipt_cannot_overwrite_new_retained_generation(stopped_worker):
    control, worker, slot, writes, release, _expected = stopped_worker
    release.set()
    worker.thread.join(3)
    newer = control._WorkerControl(slot["id"])
    newer.done_event.set()
    control._WORKER_EXECUTIONS[slot["id"]] = newer
    receipt = control._write_revocation_receipt(worker, slot, outcome="old-ended")
    assert receipt["confirmed"] is True and receipt["status_persisted"] is False
    assert writes == []


@pytest.mark.parametrize("expected", [{}, {"generation": "a" * 32}, True,
    {"service_instance": "a" * 32, "start_request_id": "b" * 32, "generation": True}])
def test_malformed_stop_fence_has_no_mutation(stopped_worker, expected):
    control, worker, slot, writes, _release, _expected = stopped_worker
    with pytest.raises(ValueError):
        control._request_worker_revocation(slot["id"], slot, expected_execution=expected)
    assert not worker.stop_event.is_set() and writes == []


def handler(control, monkeypatch, body):
    monkeypatch.setenv("BACH_CONTROL_API_TOKEN", "test-control-token")
    from unittest.mock import Mock
    instance = control.ControlHandler.__new__(control.ControlHandler)
    instance.path = "/api/workers/stop"
    instance.headers = {"Origin": "http://127.0.0.1:8000", "Content-Type": "application/json",
                        "Authorization": "Bearer test-control-token"}
    instance._read_body = lambda: body
    instance._json = Mock()
    return instance


def test_http_stop_fence_is_enforced_and_returns_exact_execution(stopped_worker, monkeypatch):
    control, worker, slot, _writes, _release, expected = stopped_worker
    body = {"id": slot["id"], **{"expected_" + key: value for key, value in expected.items()}}
    instance = handler(control, monkeypatch, {**body, "expected_generation": "0" * 32})
    instance.do_POST()
    result, code = instance._json.call_args.args
    assert code == 409 and result["ok"] is False and not worker.stop_event.is_set()
    instance._read_body = lambda: body
    instance.do_POST()
    result, code = instance._json.call_args.args
    assert code == 409 and worker.stop_event.is_set()
    assert result["execution"]["generation"] == expected["generation"]
    assert result["execution"]["terminal"] is False


@pytest.mark.parametrize("changes", [{"expected_generation": "a" * 32},
    {"expected_service_instance": None, "expected_start_request_id": "a" * 32, "expected_generation": "b" * 32}])
def test_http_partial_or_malformed_stop_fence_is_rejected(stopped_worker, monkeypatch, changes):
    control, worker, slot, writes, _release, _expected = stopped_worker
    instance = handler(control, monkeypatch, {"id": slot["id"], **changes})
    instance.do_POST()
    result, code = instance._json.call_args.args
    assert code == 400 and "error" in result
    assert not worker.stop_event.is_set() and writes == []


def test_join_keeps_old_terminal_proof_after_a_new_run_wins(stopped_worker):
    control, worker, slot, writes, release, expected = stopped_worker
    original = worker.thread
    newer = control._WorkerControl(slot["id"])
    entered, release_new = threading.Event(), threading.Event()
    def newer_body():
        entered.set()
        assert release_new.wait(5)
        newer.done_event.set()
    newer.thread = threading.Thread(target=newer_body)
    newer.launch_attempted = newer.worker_thread_started = True
    class JoinThenNewRun:
        def is_alive(self): return original.is_alive()
        def join(self, timeout=None):
            release.set()
            original.join(2)
            assert not original.is_alive()
            with control._WORKER_CONTROL_LOCK:
                control._WORKER_CONTROLS[slot["id"]] = newer
                control._WORKER_EXECUTIONS[slot["id"]] = newer
                control._ACTIVE_WORKER_THREADS[slot["id"]] = newer.thread
                slot["status"] = "running"
                newer.thread.start()
            assert entered.wait(2)
    worker.thread = JoinThenNewRun()
    try:
        confirmed, _, receipt, code = control._request_worker_revocation(
            slot["id"], slot, requested_status="paused", expected_execution=expected)
        assert code == 200 and receipt["execution"]["terminal"] is True
        assert receipt["execution"]["generation"] == worker.generation
        assert receipt["status_persisted"] is False and writes == []
        assert not newer.stop_event.is_set() and slot["status"] == "running"
        assert control.worker_execution_receipt(slot["id"])["generation"] == newer.generation
    finally:
        release_new.set()
        newer.thread.join(3)
        worker.thread = original
        assert not newer.thread.is_alive()


def test_known_execution_is_readable_and_stoppable_after_configuration_loss(stopped_worker, monkeypatch):
    control, worker, slot, writes, release, expected = stopped_worker
    def missing(_ident): raise ValueError("Missing actual core profile")
    monkeypatch.setattr(control, "_execution_worker_slot", missing)
    body = {"id": slot["id"], **{"expected_" + key: value for key, value in expected.items()}}
    instance = handler(control, monkeypatch, body)
    instance.path = "/api/workers/execution?id=" + slot["id"] + "&start_request_id=" + worker.start_request_id
    instance.do_GET()
    result = instance._json.call_args.args[0]
    assert result["ok"] is True and result["execution"]["generation"] == worker.generation
    instance.path = "/api/workers/stop"
    instance.do_POST()
    result, code = instance._json.call_args.args
    assert code == 409 and worker.stop_event.is_set() and writes == []
    release.set()
    worker.thread.join(3)
    instance.do_POST()
    result, code = instance._json.call_args.args
    assert code == 200 and result["execution"]["terminal"] is True
    assert writes == []


@pytest.mark.parametrize("operation", ["update", "activity", "cooldown", "terminal"])
def test_missing_core_configuration_never_creates_default_metadata(stopped_worker, monkeypatch, operation):
    control, worker, slot, writes, release, _expected = stopped_worker
    def missing(_ident): raise ValueError("Missing actual core profile")
    monkeypatch.setattr(control, "_execution_worker_slot", missing)
    calls = []
    monkeypatch.setattr(control, "record_activity", lambda *_a, **_kw: calls.append("activity"))
    monkeypatch.setattr(control, "bump_pause_counter", lambda *_a, **_kw: calls.append("cooldown") or False)
    if operation == "update": assert control._update_worker_slot(worker, {"status": "error"}) is None
    if operation == "activity": assert control._record_worker_activity(worker, "error") is False
    if operation == "cooldown": assert control._wait_worker_cooldown(worker) is False
    if operation == "terminal":
        release.set()
        worker.thread.join(3)
        assert control._write_revocation_receipt(worker, slot, outcome="ended")["status_persisted"] is False
    assert writes == [] and calls == []
