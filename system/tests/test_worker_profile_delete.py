"""Task2332: profile deletion proves run end and retains terminal receipts."""
import json
import os
import threading
from types import SimpleNamespace

import pytest

from system.tests.test_worker_start_admission import admission
from system.tests.test_task_lease_client import mem_db
from hub._services.chat import slots_config as slots
from hub._services.task_lease_client import TaskLeaseClient
from hub.agent_process_provider import capture_process_create_time


@pytest.fixture
def deletion(admission, mem_db, monkeypatch):
    control, worker = admission
    monkeypatch.setattr(control.socket, "gethostname", lambda: "HOST")
    # The profile was created by the same native fixture before host isolation.
    marker = slots.get_worker_slot(worker["id"])["_controller_run"]
    edit_raw(worker["id"], _controller_run={**marker, "host": "HOST"})
    monkeypatch.setattr("hub._services.task_lease_client.get_lead_config", lambda: {"mode": "isolated"})
    client = TaskLeaseClient(conn=mem_db)
    monkeypatch.setattr(control, "_native_task_client", lambda: client)
    return control, worker, client


def edit_raw(worker_id, **changes):
    cfg = slots.load_slots_config(strict=True)
    worker = next(w for w in cfg["dynamic_workers"] if w["id"] == worker_id)
    for key, value in changes.items():
        if value is ...:
            worker.pop(key, None)
        else:
            worker[key] = value
    slots.save_slots_config(cfg)
    return worker


def ended(control, worker):
    run = control._WorkerControl(worker["id"], physical_worker_id="worker-" + "a" * 32,
                                 lease_worker_id="worker-" + "a" * 32 + "@HOST")
    run.done_event.set()
    run.launch_attempted = True
    run.worker_thread_started = True
    control._WORKER_EXECUTIONS[worker["id"]] = run
    record = {"schema": slots._CONTROLLER_RUN_SCHEMA, "phase": "admitted",
              "worker_id": worker["id"], "service_instance": control._WORKER_SERVICE_INSTANCE,
              "pid": os.getpid(), "process_create_time": capture_process_create_time(os.getpid()), "host": "HOST",
              "start_request_id": run.start_request_id, "generation": run.generation,
              "physical_worker_id": run.physical_worker_id, "lease_worker_id": run.lease_worker_id,
              "durable": os.name == "posix", "prior_runs_unconfirmed": False}
    edit_raw(worker["id"], _controller_run=record)
    return run, record


def test_new_never_admitted_profile_can_be_deleted_without_task_authority(deletion, monkeypatch):
    control, worker, _ = deletion
    monkeypatch.setattr(control, "_native_task_client", lambda: pytest.fail("No run ever admitted"))
    assert control.delete_worker_profile(worker["id"])[1] == 200
    assert not slots.get_worker_slot(worker["id"])


def test_low_level_delete_requires_controller_guard(deletion):
    _, worker, _ = deletion
    with pytest.raises(RuntimeError, match="worker_delete_execution_unconfirmed"):
        slots.remove_worker(worker["id"])
    assert slots.get_worker_slot(worker["id"])


@pytest.mark.parametrize("state", ["running", "stopping", "admission_pending", "cleanup_missing"])
def test_inactive_display_never_overrides_live_or_unconfirmed_generation(deletion, state):
    control, worker, _ = deletion
    run, _ = ended(control, worker)
    edit_raw(worker["id"], status="expired", current_activity="Beendet")
    if state == "admission_pending":
        run.admission_pending = True
    elif state == "cleanup_missing":
        run.done_event.clear()
    else:
        run.thread = SimpleNamespace(is_alive=lambda: True)
        if state == "stopping":
            run.stop_event.set()
    response, code = control.delete_worker_profile(worker["id"])
    assert code == 409 and response["error_code"] == "worker_delete_active"
    assert slots.get_worker_slot(worker["id"])


def test_exact_physical_worker_lease_blocks_delete_even_with_different_displayed_task(deletion, mem_db):
    control, worker, client = deletion
    run, _ = ended(control, worker)
    mem_db.execute("INSERT INTO tasks(id,title,status) VALUES(19,'Real task','pending')")
    mem_db.commit()
    ack = client.acquire(19, worker_id=run.lease_worker_id, host="HOST")
    edit_raw(worker["id"], task_id=999)
    assert control.delete_worker_profile(worker["id"])[1] == 409
    client.release(19, lease_id=ack.lease_id, fence=ack.fence)
    assert control.delete_worker_profile(worker["id"])[1] == 200


def test_unknown_legacy_offline_profile_stays_visible(deletion):
    control, worker, _ = deletion
    edit_raw(worker["id"], _controller_run=..., status="completed")
    response, code = control.delete_worker_profile(worker["id"])
    assert code == 409 and response["error_code"] == "worker_delete_execution_unconfirmed"
    assert slots.get_worker_slot(worker["id"])


@pytest.mark.parametrize("process_state, expected", [("gone", 200), ("mismatch", 200),
                                                     ("owned", 409), ("unavailable", 409)])
def test_prior_service_needs_dead_exact_process_and_free_leases(deletion, monkeypatch, process_state, expected):
    control, worker, _ = deletion
    _, record = ended(control, worker)
    control._WORKER_EXECUTIONS.clear()
    edit_raw(worker["id"], _controller_run={**record, "service_instance": "b" * 32, "durable": True})
    monkeypatch.setattr("hub.agent_process_provider.inspect_process_identity", lambda record: (process_state, None))
    assert control.delete_worker_profile(worker["id"])[1] == expected


def test_same_service_lost_control_is_not_recovered_from_dead_pid(deletion, monkeypatch):
    control, worker, _ = deletion
    ended(control, worker)
    control._WORKER_EXECUTIONS.clear()
    monkeypatch.setattr("hub.agent_process_provider.inspect_process_identity", lambda record: ("gone", None))
    assert control.delete_worker_profile(worker["id"])[1] == 409


def budget_record(worker_id):
    return {"schema": "bach.worker-model-requests.v1", "worker_id": worker_id,
            "service_instance": "c" * 32, "pid": 999999,
            "process_create_time": 1.0, "start_request_id": "d" * 32,
            "generation": "e" * 32, "task_id": 1, "task_version": None,
            "configuration_version": "f" * 64, "limit": 3, "reserved_count": 0,
            "phase": "terminal", "reason": "interrupted_no_dispatch", "sequence": 1}


@pytest.mark.parametrize("archive_fails", [False, True])
def test_terminal_budget_is_archived_before_profile_and_opt_in_disappear(deletion, mem_db, monkeypatch, archive_fails):
    from hub._services.chat import worker_run_archive
    control, worker, _ = deletion
    mem_db.execute("INSERT INTO tasks(id,title,status) VALUES(1,'Budget task','pending')")
    mem_db.commit()
    record = budget_record(worker["id"])
    edit_raw(worker["id"], _controller_run=..., task_id=1, max_model_requests=3,
             persistent_opt_in=True, _model_request_runs={"schema": record["schema"], "current": record, "terminal": []})
    observed = []
    def archive(worker_id, records, directory):
        assert slots.get_worker_slot(worker_id)["persistent_opt_in"] is True
        assert records == [record]
        observed.append((worker_id, records, directory))
        if archive_fails:
            raise OSError("private archive path")
        return 1
    monkeypatch.setattr(worker_run_archive, "archive_terminal_records", archive)
    response, code = control.delete_worker_profile(worker["id"])
    assert len(observed) == 1
    assert code == (503 if archive_fails else 200)
    assert bool(slots.get_worker_slot(worker["id"])) is archive_fails
    assert "private archive path" not in json.dumps(response)


def test_unknown_lease_readback_keeps_profile(deletion, monkeypatch):
    control, worker, _ = deletion
    ended(control, worker)
    def unavailable(_worker):
        raise OSError("private database path")
    monkeypatch.setattr(control, "_native_task_client", lambda: SimpleNamespace(worker_leases=unavailable))
    response, code = control.delete_worker_profile(worker["id"])
    assert code == 503 and slots.get_worker_slot(worker["id"])
    assert "private database path" not in json.dumps(response)


def test_admission_persists_exact_identity_before_launch(deletion, monkeypatch):
    control, worker, _ = deletion
    def launch(run, slot, prompt):
        record = slots.get_worker_slot(worker["id"])["_controller_run"]
        assert record["phase"] == "admitted"
        assert record["generation"] == run.generation
        assert record["physical_worker_id"] == run.physical_worker_id
        assert record["lease_worker_id"] == run.lease_worker_id
        assert control._WORKER_EXECUTIONS[worker["id"]] is run
        assert run.admission_pending is True
        return {"error": "Fixture denies launch"}, 403
    monkeypatch.setattr(control, "_start_reserved_worker_execution", launch)
    assert control.start_worker_execution(worker["id"], start_request_id="1" * 32)[1] == 403
    assert control.delete_worker_profile(worker["id"])[1] == 200


@pytest.mark.parametrize("method, path", [("POST", "/api/workers/delete"),
    ("POST", "/api/worker/delete"), ("DELETE", "/api/workers?id=worker-fixture")])
def test_every_delete_alias_uses_same_fenced_operation(deletion, monkeypatch, method, path):
    control, _, _ = deletion
    handler = object.__new__(control.ControlHandler)
    handler.path = path
    monkeypatch.setattr(handler, "_allow_control_request", lambda: True)
    monkeypatch.setattr(handler, "_allow_json_post", lambda: True)
    monkeypatch.setattr(handler, "_read_body", lambda: {"id": "worker-fixture"})
    received = []
    monkeypatch.setattr(handler, "_json", lambda body, code=200: received.append((body, code)))
    monkeypatch.setattr(control, "delete_worker_profile", lambda worker_id: ({"error_code": "fenced", "id": worker_id}, 409))
    getattr(handler, "do_" + method)()
    assert received == [({"error_code": "fenced", "id": "worker-fixture"}, 409)]


def test_private_controller_identity_is_not_in_worker_projection(deletion):
    control, worker, _ = deletion
    ended(control, worker)
    stored = slots.get_worker_slot(worker["id"])
    assert "_controller_run" not in control._without_private_model_request_runs(stored)
    assert "_controller_run" not in control._worker_handoff_snapshot(stored)


def test_conflicting_retained_generation_cannot_use_older_dead_process_proof(deletion, monkeypatch):
    control, worker, _ = deletion
    _, record = ended(control, worker)
    edit_raw(worker["id"], _controller_run={**record, "service_instance": "b" * 32, "durable": True})
    monkeypatch.setattr("hub.agent_process_provider.inspect_process_identity", lambda record: ("gone", None))
    assert control.delete_worker_profile(worker["id"])[1] == 409


def test_start_cannot_slip_between_delete_proof_archive_and_profile_removal(deletion, monkeypatch):
    from hub._services.chat import worker_run_archive
    control, worker, _ = deletion
    entered, release = threading.Event(), threading.Event()
    results = {}
    def archive(*args):
        entered.set()
        assert release.wait(3)
        return 0
    monkeypatch.setattr(worker_run_archive, "archive_terminal_records", archive)
    monkeypatch.setattr(control, "_start_reserved_worker_execution", lambda *args: pytest.fail("Deleted profile cannot launch"))
    deleting = threading.Thread(target=lambda: results.update(delete=control.delete_worker_profile(worker["id"])))
    starting = threading.Thread(target=lambda: results.update(start=control.start_worker_execution(worker["id"], start_request_id="2" * 32)))
    deleting.start()
    try:
        assert entered.wait(3)
        starting.start()
        assert "start" not in results
    finally:
        release.set()
        deleting.join(5)
        if starting.ident:
            starting.join(5)
    assert not deleting.is_alive() and not starting.is_alive()
    assert results["delete"][1] == 200 and results["start"][1] == 404


def test_actual_pending_admission_blocks_delete_without_implicit_stop(deletion, monkeypatch):
    control, worker, _ = deletion
    entered, release = threading.Event(), threading.Event()
    def launch(run, slot, prompt):
        entered.set()
        assert release.wait(3)
        return {"error": "Fixture rejected"}, 403
    monkeypatch.setattr(control, "_start_reserved_worker_execution", launch)
    starting = threading.Thread(target=lambda: control.start_worker_execution(worker["id"], start_request_id="3" * 32))
    starting.start()
    try:
        assert entered.wait(3)
        assert control.delete_worker_profile(worker["id"])[1] == 409
        assert not control._WORKER_EXECUTIONS[worker["id"]].stop_event.is_set()
    finally:
        release.set()
        starting.join(5)
    assert not starting.is_alive()
    assert control.delete_worker_profile(worker["id"])[1] == 200


def test_legacy_uncertainty_survives_new_terminal_admissions(deletion, monkeypatch):
    control, worker, _ = deletion
    edit_raw(worker["id"], _controller_run=...)
    monkeypatch.setattr(control, "_start_reserved_worker_execution", lambda *args: ({"error": "Fixture"}, 403))
    for request in ("4" * 32, "5" * 32):
        assert control.start_worker_execution(worker["id"], start_request_id=request)[1] == 403
        record = slots.get_worker_slot(worker["id"])["_controller_run"]
        assert record["prior_runs_unconfirmed"] is True
        assert control.delete_worker_profile(worker["id"])[1] == 409


@pytest.mark.parametrize("field", ["system", "execution_kind", "_controller_run"])
def test_generic_profile_updates_cannot_forge_controller_identity(deletion, field):
    _, worker, _ = deletion
    before = slots.get_worker_slot(worker["id"])
    with pytest.raises(ValueError):
        slots.update_slot(worker["id"], {field: True})
    assert slots.get_worker_slot(worker["id"]) == before


def test_stored_system_flag_does_not_skip_dynamic_admission_fence(deletion, monkeypatch):
    control, worker, _ = deletion
    edit_raw(worker["id"], system=True)
    version = slots.core_system_agents_snapshot()["configuration_version"]
    observed = []
    def launch(run, slot, prompt):
        observed.append(slot)
        assert slot["system"] is False
        record = slots.get_worker_slot(worker["id"])["_controller_run"]
        assert record["phase"] == "admitted" and record["generation"] == run.generation
        return {"error": "Fixture"}, 403
    monkeypatch.setattr(control, "_start_reserved_worker_execution", launch)
    assert control.start_worker_execution(worker["id"], start_request_id="6" * 32,
        expected_configuration_version=version)[1] == 403
    assert len(observed) == 1
    assert control.delete_worker_profile(worker["id"])[1] == 200


def test_live_prior_controller_blocks_reconciliation_before_checkpoint_mutation(deletion, monkeypatch):
    control, worker, _ = deletion
    _, record = ended(control, worker)
    control._WORKER_EXECUTIONS.clear()
    edit_raw(worker["id"], _controller_run={**record, "service_instance": "b" * 32, "durable": True})
    before = slots._resolve_path(None).read_bytes()
    monkeypatch.setattr("hub.agent_process_provider.inspect_process_identity", lambda record: ("owned", None))
    monkeypatch.setattr(control, "_persistent_worker_reconciliation_scan", lambda *args: pytest.fail("No scan before prior process proof"))
    result = control._reconcile_persistent_cloud_worker(
        {"worker_id": worker["id"], "reason": "prior_generation_unsettled"},
        trace_contract={"schema": "bach.worker-tool-trace.v1", "source_sha256": "a" * 64})
    assert result["state"] == "blocked" and result["reason"] == "prior_controller_unconfirmed"
    assert slots._resolve_path(None).read_bytes() == before


def test_valid_legacy_v2_checkpoint_without_process_identity_blocks_before_scan(deletion, monkeypatch):
    control, worker, _ = deletion
    checkpoint = {
        "schema": "bach.persistent-worker-controller.v2", "phase": "admitted",
        "worker_id": worker["id"], "service_instance": "a" * 32,
        "start_request_id": "b" * 32, "intent_id": "c" * 32,
        "profile_version": "d" * 64, "trace_contract_sha256": "e" * 64,
        "generation": "f" * 32, "physical_worker_id": "worker-" + "1" * 32,
        "lease_worker_id": "worker-" + "1" * 32 + "@HOST",
    }
    assert slots._valid_persistent_worker_controller_checkpoint(checkpoint)
    edit_raw(worker["id"], _controller_run=...,
             **{slots.PERSISTENT_WORKER_CONTROLLER_CHECKPOINT_FIELD: checkpoint})
    before = slots._resolve_path(None).read_bytes()
    monkeypatch.setattr(control, "_persistent_worker_reconciliation_scan", lambda *args: pytest.fail("Unknown old process cannot be reconciled"))
    result = control._reconcile_persistent_cloud_worker(
        {"worker_id": worker["id"], "reason": "prior_generation_unsettled"},
        trace_contract={"schema": "bach.worker-tool-trace.v1", "source_sha256": "e" * 64})
    assert result == {"state": "blocked", "reason": "prior_controller_unconfirmed"}
    assert slots._resolve_path(None).read_bytes() == before


def test_foreign_host_pid_cannot_prove_prior_controller_death(deletion, monkeypatch):
    control, worker, _ = deletion
    _, record = ended(control, worker)
    control._WORKER_EXECUTIONS.clear()
    edit_raw(worker["id"], _controller_run={**record, "host": "OTHER-HOST",
        "lease_worker_id": record["physical_worker_id"] + "@OTHER-HOST",
        "service_instance": "a" * 32, "durable": True})
    monkeypatch.setattr("hub.agent_process_provider.inspect_process_identity",
                        lambda *_args: pytest.fail("No local PID check for a foreign host"))
    assert control.delete_worker_profile(worker["id"])[1] == 409


def test_non_durable_never_admitted_profile_can_start_after_service_restart(deletion, monkeypatch):
    control, worker, _ = deletion
    marker = slots.get_worker_slot(worker["id"])["_controller_run"]
    edit_raw(worker["id"], _controller_run={**marker, "durable": False, "pid": 999999})
    assert control.delete_worker_profile(worker["id"])[1] == 409
    observed = []
    def launch(*args):
        observed.append(True)
        return {"error": "Fixture denies launch"}, 403
    monkeypatch.setattr(control, "_start_reserved_worker_execution", launch)
    assert control.start_worker_execution(worker["id"], start_request_id="7" * 32)[1] == 403
    assert observed == [True]
    assert slots.get_worker_slot(worker["id"])["_controller_run"]["prior_runs_unconfirmed"] is True
    assert control.delete_worker_profile(worker["id"])[1] == 409

