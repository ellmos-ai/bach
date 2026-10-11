import datetime
import json
import threading

import pytest

from hub._services.chat import slots_config as slots


CHECKPOINT_FIELD = slots.PERSISTENT_WORKER_CONTROLLER_CHECKPOINT_FIELD


def _cloud_worker(tmp_path, **overrides):
    path = str(tmp_path / "slots.json")
    slots.initialize_slots_config(path)
    data = {
        "id": "cloud-worker-a",
        "name": "Cloud Worker",
        "backend": "openrouter",
        "model": "provider/free-model",
        "sub_mode": "hintergrund_worker",
        "type": "continuous",
    }
    data.update(overrides)
    worker = slots.add_worker(data, path=path)
    return path, worker["id"]


def _opt_in(path, worker_id):
    current = slots.worker_configuration_snapshot(worker_id, path=path)
    return slots.change_worker_configuration(
        worker_id, current["configuration_version"], {"persistent_opt_in": True}, path=path
    )


def _checkpoint(worker, phase="admission_pending", *, trace_hash="a" * 64):
    physical_worker_id = "worker-" + "4" * 32
    return {
        "schema": "bach.persistent-worker-controller.v2",
        "phase": phase,
        "worker_id": worker["id"],
        "service_instance": "1" * 32,
        "start_request_id": "2" * 32,
        "intent_id": worker["persistent_opt_in_id"],
        "profile_version": slots._worker_profile_version(worker),
        "trace_contract_sha256": trace_hash,
        "generation": "3" * 32,
        "physical_worker_id": physical_worker_id,
        "lease_worker_id": physical_worker_id + "@HOST",
    }


def _store_checkpoint(path, worker_id, checkpoint):
    worker = slots.get_worker_slot(worker_id, path=path)
    current = slots.worker_configuration_snapshot(worker_id, path=path)
    pending = {**checkpoint, "phase": "admission_pending"}
    result = slots.set_persistent_worker_controller_checkpoint(
        worker_id, current["configuration_version"], slots._worker_profile_version(worker),
        worker["persistent_opt_in_id"], worker.get(CHECKPOINT_FIELD), pending, path=path,
    )
    if checkpoint["phase"] == "admission_pending":
        return result
    return slots.set_persistent_worker_controller_checkpoint(
        worker_id, current["configuration_version"], slots._worker_profile_version(worker),
        worker["persistent_opt_in_id"], pending, checkpoint, path=path,
    )


def _startup_profile(path):
    return slots.persistent_worker_startup_snapshot(path)["profiles"][0]


def test_new_worker_ignores_payload_opt_in_and_defaults_off(tmp_path):
    path, worker_id = _cloud_worker(
        tmp_path,
        persistent_opt_in=True,
        persistent_opt_in_id="f" * 32,
        _persistent_execution_checkpoint={"phase": "admitted"},
    )
    worker = slots.get_worker_slot(worker_id, path=path)
    assert worker["persistent_opt_in"] is False
    assert "persistent_opt_in_id" not in worker
    assert CHECKPOINT_FIELD not in worker
    assert slots.persistent_worker_startup_snapshot(path)["profiles"] == []


def test_explicit_opt_in_is_cas_bound_to_eligible_cloud_profile(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    result = _opt_in(path, worker_id)
    worker = slots.get_worker_slot(worker_id, path=path)
    assert result["persistent_opt_in"] is True
    assert len(worker["persistent_opt_in_id"]) == 32
    assert worker["persistent_opt_in_profile_version"] == slots._worker_profile_version(worker)
    assert _startup_profile(path)["state"] == "ready"


def test_missing_cloud_model_cannot_receive_persistent_opt_in(tmp_path):
    path, worker_id = _cloud_worker(tmp_path, model="")
    current = slots.worker_configuration_snapshot(worker_id, path=path)
    with pytest.raises(ValueError, match="Cloudprofile"):
        slots.change_worker_configuration(
            worker_id, current["configuration_version"], {"persistent_opt_in": True}, path=path
        )


def test_execution_digest_does_not_change_when_only_consent_changes(tmp_path):
    from hub._services.chat import telegram_chat

    path, worker_id = _cloud_worker(tmp_path)
    worker = slots.get_worker_slot(worker_id, path=path)
    before = telegram_chat._execution_worker_configuration(worker)
    _opt_in(path, worker_id)
    opted_in = telegram_chat._execution_worker_configuration(slots.get_worker_slot(worker_id, path=path))
    current = slots.worker_configuration_snapshot(worker_id, path=path)
    slots.change_worker_configuration(
        worker_id, current["configuration_version"], {"persistent_opt_in": False}, path=path
    )
    opted_out = telegram_chat._execution_worker_configuration(slots.get_worker_slot(worker_id, path=path))
    assert before["configuration_version"] == opted_in["configuration_version"]
    assert before["configuration_version"] == opted_out["configuration_version"]
    assert "persistent_opt_in" not in opted_in
    assert "persistent_opt_in" not in opted_out


def test_running_or_paused_profile_never_enters_startup_recovery(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    slots.update_slot(worker_id, {"status": "running"}, path=path)
    profile = _startup_profile(path)
    assert profile["state"] == "unavailable"
    assert profile["reason"] == "profile_not_idle"
    slots.update_slot(worker_id, {"status": "paused"}, path=path)
    profile = _startup_profile(path)
    assert profile["state"] == "unavailable"
    assert profile["reason"] == "profile_not_idle"


def test_acquire_before_post_checkpoint_gap_blocks_even_when_profile_says_idle(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    worker = slots.get_worker_slot(worker_id, path=path)
    _store_checkpoint(path, worker_id, _checkpoint(worker, "admission_pending"))
    profile = _startup_profile(path)
    assert profile["state"] == "unavailable"
    assert profile["reason"] == "prior_generation_unsettled"


def test_admitted_generation_is_not_replayed_without_native_trace_readback(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    worker = slots.get_worker_slot(worker_id, path=path)
    _store_checkpoint(path, worker_id, _checkpoint(worker, "admitted"))
    profile = _startup_profile(path)
    assert profile["state"] == "unavailable"
    assert profile["reason"] == "prior_generation_unsettled"


def test_malformed_checkpoint_blocks_and_cas_protects_private_field(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    config = slots.load_slots_config(path, strict=True)
    config["dynamic_workers"][0][CHECKPOINT_FIELD] = {"phase": "clean"}
    slots.save_slots_config(config, path)
    profile = _startup_profile(path)
    assert profile["state"] == "unavailable"
    assert profile["reason"] == "invalid_controller_checkpoint"
    with pytest.raises(ValueError, match="Versions-CAS"):
        slots.update_slot(worker_id, {CHECKPOINT_FIELD: None}, path=path)


def test_controller_checkpoint_is_private_and_does_not_change_profile_or_consent_versions(tmp_path):
    from hub._services.chat import telegram_chat

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    worker = slots.get_worker_slot(worker_id, path=path)
    before_config = slots.worker_configuration_snapshot(worker_id, path=path)
    before_profile = slots._worker_profile_version(worker)
    checkpoint = _checkpoint(worker)
    _store_checkpoint(path, worker_id, checkpoint)
    after_config = slots.worker_configuration_snapshot(worker_id, path=path)
    after_worker = slots.get_worker_slot(worker_id, path=path)
    assert after_config["configuration_version"] == before_config["configuration_version"]
    assert slots._worker_profile_version(after_worker) == before_profile
    assert CHECKPOINT_FIELD not in after_config
    projected = telegram_chat._worker_handoff_snapshot(after_worker)
    assert CHECKPOINT_FIELD not in projected
    assert projected["persistent_opt_in"] is True


def test_manual_consent_revocation_clears_checkpoint_atomically(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    worker = slots.get_worker_slot(worker_id, path=path)
    _store_checkpoint(path, worker_id, _checkpoint(worker))
    current = slots.worker_configuration_snapshot(worker_id, path=path)
    result = slots.change_worker_configuration(
        worker_id, current["configuration_version"], {"persistent_opt_in": False}, path=path
    )
    final = slots.get_worker_slot(worker_id, path=path)
    assert result["persistent_opt_in"] is False
    assert final["persistent_opt_in"] is False
    assert CHECKPOINT_FIELD not in final
    assert "persistent_opt_in_id" not in final


def test_automatic_start_fails_closed_when_normal_trace_contract_is_missing(monkeypatch):
    from hub import rheingold
    from hub._services.chat import telegram_chat

    worker_id = "cloud-worker-a"
    profile = {"worker_id": worker_id, "state": "ready", "reason": "explicit_opt_in",
               "configuration_version": "c" * 64, "profile_version": "d" * 64,
               "intent_id": "e" * 32}
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "lead"})
    monkeypatch.setattr(telegram_chat, "persistent_worker_startup_snapshot",
                        lambda: {"profiles": [profile]})
    monkeypatch.setattr(telegram_chat, "_active_worker_ids", lambda: set())
    monkeypatch.setattr(telegram_chat, "_persistent_worker_trace_contract", lambda: None)
    starts = []
    monkeypatch.setattr(telegram_chat, "_start_worker_execution", lambda *a, **k: starts.append((a, k)))
    result = telegram_chat._resume_persistent_cloud_workers_at_startup(threading.Event())
    assert starts == []
    assert result["profiles"] == [{"worker_id": worker_id, "state": "not_started",
                                    "reason": "trace_contract_unavailable"}]


def test_dynamic_worker_version_scopes_keep_global_and_profile_cas_distinct(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    profile = _startup_profile(path)
    assert profile["state"] == "ready"
    profile_version = profile["configuration_version"]
    core_version = slots.core_system_agents_snapshot(path)["configuration_version"]
    assert profile_version != core_version

    assert slots.system_worker_at_version(worker_id, core_version, path=path)["id"] == worker_id
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.system_worker_at_version(worker_id, profile_version, path=path)
    assert slots.system_worker_at_version(
        worker_id, profile_version, version_scope="worker_profile", path=path
    )["id"] == worker_id
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.system_worker_at_version(
            worker_id, core_version, version_scope="worker_profile", path=path
        )
    with pytest.raises(ValueError, match="Versionsbereich"):
        slots.system_worker_at_version(worker_id, core_version, version_scope="unknown", path=path)


def test_private_startup_admission_uses_profile_version_scope(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import socket

    from hub._services.chat import telegram_chat

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    profile = _startup_profile(path)
    assert profile["state"] == "ready"
    version_scopes = []
    read_worker = slots.system_worker_at_version

    def read_isolated_worker(slot_id, expected_version, **kwargs):
        version_scopes.append(kwargs.get("version_scope"))
        return read_worker(slot_id, expected_version, path=path, **kwargs)

    @contextmanager
    def isolated_admission(path=None):
        yield lambda: None

    monkeypatch.setattr(slots, "system_worker_at_version", read_isolated_worker)
    monkeypatch.setattr(slots, "worker_admission_transaction", isolated_admission)
    monkeypatch.setattr(telegram_chat, "_active_worker_control", lambda _: (None, None))
    monkeypatch.setattr(telegram_chat, "_start_reserved_worker_execution",
                        lambda *args: ({"ok": True}, 200))
    for name in ("_WORKER_CONTROLS", "_ACTIVE_WORKER_THREADS", "_WORKER_EXECUTIONS"):
        monkeypatch.setattr(telegram_chat, name, {})

    generation = "1" * 32
    physical_worker_id = "worker-" + "2" * 32
    response, status = telegram_chat._start_worker_execution(
        worker_id,
        start_request_id="a" * 32,
        expected_service_instance=telegram_chat._WORKER_SERVICE_INSTANCE,
        expected_configuration_version=profile["configuration_version"],
        _startup_stop_event=threading.Event(),
        _startup_generation=generation,
        _startup_physical_worker_id=physical_worker_id,
        _startup_lease_worker_id=f"{physical_worker_id}@{socket.gethostname()}",
        _startup_profile_version=True,
    )
    assert status == 200
    assert response["ok"] is True
    assert response["execution"]["generation"] == generation
    assert version_scopes == ["worker_profile"]


def test_present_trace_contract_fingerprint_is_strictly_shaped():
    from hub._services.chat import telegram_chat

    contract = telegram_chat._persistent_worker_trace_contract()
    if contract is not None:
        assert contract["schema"] == "bach.worker-tool-trace.v1"
        assert len(contract["source_sha256"]) == 64
        assert all(c in "0123456789abcdef" for c in contract["source_sha256"])


def test_trace_contract_requires_the_actual_bound_normal_tool_loop(monkeypatch):
    from hub._services.chat import telegram_chat
    from hub._services.chat.chat_runtime import ChatRuntime

    contract = _contract_or_skip()
    assert contract["schema"] == "bach.worker-tool-trace.v1"

    def uninstrumented(*args, **kwargs):
        return None

    with monkeypatch.context() as patch:
        patch.setattr(ChatRuntime, "_tool_loop_impl", uninstrumented)
        assert telegram_chat._persistent_worker_trace_contract() is None

    with monkeypatch.context() as patch:
        patch.setattr(ChatRuntime, "_worker_backend_gate", classmethod(uninstrumented))
        assert telegram_chat._persistent_worker_trace_contract() is None


@pytest.fixture
def isolated_task_client(tmp_path, monkeypatch):
    from hub._services import task_lease_client
    from system.tests.test_task_lease_service import _connect, _create_db, _insert

    database = tmp_path / "canonical.db"
    _create_db(database)
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    client = task_lease_client.TaskLeaseClient(db_path=database)
    return client, database, _connect, _insert


def _contract_or_skip():
    from hub._services.chat import telegram_chat

    contract = telegram_chat._persistent_worker_trace_contract()
    if contract is None:
        pytest.skip("Der echte #2079-Normal-Loop-Tracevertrag ist in dieser Basis nicht komponiert")
    return contract


def _seed_previous_generation(path, worker_id, contract, *, status="running", phase="admission_pending"):
    if status != "idle":
        slots.update_slot(worker_id, {"status": status}, path=path)
    worker = slots.get_worker_slot(worker_id, path=path)
    checkpoint = _checkpoint(worker, phase, trace_hash=contract["source_sha256"])
    _store_checkpoint(path, worker_id, checkpoint)
    return checkpoint


def _insert_task(database, connect, insert, *, title="Recovery task", status="pending"):
    conn = connect(database)
    try:
        created_at = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)
        ).strftime("%Y-%m-%d %H:%M:%S")
        return insert(
            conn, title=title, status=status, assigned_to="BACH", created_at=created_at
        )
    finally:
        conn.close()


def _reconcile(path, worker_id, contract, client, monkeypatch):
    from hub._services.chat import telegram_chat

    monkeypatch.setattr(telegram_chat, "_active_worker_ids", lambda: set())
    return telegram_chat._reconcile_persistent_cloud_worker(
        _startup_profile(path), contract, client=client, path=path,
    )


def test_legacy_controller_checkpoint_is_not_recovered(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    worker = slots.get_worker_slot(worker_id, path=path)
    legacy = _checkpoint(worker)
    legacy["schema"] = "bach.persistent-worker-controller.v1"
    config = slots.load_slots_config(path, strict=True)
    config["dynamic_workers"][0][CHECKPOINT_FIELD] = legacy
    slots.save_slots_config(config, path)
    profile = _startup_profile(path)
    assert profile["state"] == "unavailable"
    assert profile["reason"] == "invalid_controller_checkpoint"


def test_admission_checkpoint_cannot_change_prebound_generation(tmp_path):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    worker = slots.get_worker_slot(worker_id, path=path)
    pending = _checkpoint(worker)
    _store_checkpoint(path, worker_id, pending)
    current = slots.get_worker_slot(worker_id, path=path)
    version = slots.worker_configuration_snapshot(worker_id, path=path)["configuration_version"]
    changed = {**pending, "phase": "admitted", "generation": "f" * 32}
    with pytest.raises(RuntimeError, match="transition_conflict"):
        slots.set_persistent_worker_controller_checkpoint(
            worker_id, version, slots._worker_profile_version(current),
            current["persistent_opt_in_id"], pending, changed, path=path,
        )


def test_composed_trace_reader_covers_every_reclaimable_status(isolated_task_client):
    from hub._services.chat import telegram_chat

    contract = _contract_or_skip()
    client, database, connect, insert = isolated_task_client
    retryable = ("pending", "open", "in_progress", "progress")
    terminal = ("review", "completed", "done", "blocked")
    ids = {}
    for status in retryable + terminal:
        ids[status] = _insert_task(database, connect, insert, title="Status " + status, status=status)
    page = client.task_candidates(limit=100, offset=0)
    assert {item["id"] for item in page["tasks"]} == {ids[status] for status in retryable}
    assert page["total"] == len(retryable)
    assert contract["schema"] == "bach.worker-tool-trace.v1"
    assert len(contract["source_sha256"]) == 64
    # The normal acquisition reader consumes all four statuses from this same API.
    import inspect
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    acquire_wrapper = inspect.getsource(WorkerLeaseBinding.acquire_next)
    candidate_reader = inspect.getsource(WorkerLeaseBinding._acquire_next_observed)
    assert "_acquire_next_observed(" in acquire_wrapper
    assert "client.task_candidates(" in candidate_reader


def test_clean_stale_running_generation_settles_only_after_two_stable_native_scans(
        tmp_path, isolated_task_client, monkeypatch):
    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    client, database, connect, insert = isolated_task_client
    _insert_task(database, connect, insert)
    contract = _contract_or_skip()
    checkpoint = _seed_previous_generation(path, worker_id, contract, status="running")
    profile = _startup_profile(path)
    assert profile["reason"] == "prior_generation_unsettled"
    from hub._services.chat import telegram_chat
    first = telegram_chat._persistent_worker_reconciliation_scan(client, checkpoint, "running")
    second = telegram_chat._persistent_worker_reconciliation_scan(client, checkpoint, "running")
    assert first["complete"] is second["complete"] is True
    assert first["sha256"] == second["sha256"]
    result = _reconcile(path, worker_id, contract, client, monkeypatch)
    assert result["state"] == "settled"
    assert result["generation"] == checkpoint["generation"]
    worker = slots.get_worker_slot(worker_id, path=path)
    assert worker["status"] == "idle"
    assert CHECKPOINT_FIELD not in worker
    assert worker["persistent_opt_in"] is True
    assert _startup_profile(path)["state"] == "ready"


def test_acquire_before_checkpoint_crash_blocks_on_matching_active_lease(
        tmp_path, isolated_task_client, monkeypatch):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    contract = _contract_or_skip()
    checkpoint = _seed_previous_generation(path, worker_id, contract, status="running")
    binding = WorkerLeaseBinding.acquire(
        client, task_id, worker_id=checkpoint["lease_worker_id"], host="HOST",
        generation=checkpoint["generation"], is_current=lambda: True,
        stop_event=threading.Event(),
    )
    try:
        result = _reconcile(path, worker_id, contract, client, monkeypatch)
        assert result == {"state": "blocked", "reason": "active_old_generation_lease"}
        worker = slots.get_worker_slot(worker_id, path=path)
        assert worker["status"] == "running"
        assert worker[CHECKPOINT_FIELD] == checkpoint
    finally:
        binding.return_lease()


def test_acknowledged_old_generation_tool_trace_still_blocks_retryable_task(
        tmp_path, isolated_task_client, monkeypatch):
    contract = _contract_or_skip()
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.chat.worker_tool_dispatch_trace import (
        acknowledge_normal_tool_result, execute_normal_tool,
    )

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    checkpoint = _seed_previous_generation(path, worker_id, contract, status="running")
    binding = WorkerLeaseBinding.acquire(
        client, task_id, worker_id=checkpoint["lease_worker_id"], host="HOST",
        generation=checkpoint["generation"], is_current=lambda: True,
        stop_event=threading.Event(),
    )
    outcome = execute_normal_tool(binding, "search_text", {"query": "safe fixture"},
                                  lambda *_: "safe fixture result")
    assert outcome.status == "returned"
    assert acknowledge_normal_tool_result(binding, outcome)
    assert binding.return_lease() is True
    assert client.task_snapshot(task_id)["status"] == "pending"
    result = _reconcile(path, worker_id, contract, client, monkeypatch)
    assert result == {"state": "blocked", "reason": "old_generation_tool_trace"}
    worker = slots.get_worker_slot(worker_id, path=path)
    assert worker["status"] == "running"
    assert worker[CHECKPOINT_FIELD] == checkpoint


def test_started_unknown_old_generation_trace_blocks_after_safe_return(
        tmp_path, isolated_task_client, monkeypatch):
    contract = _contract_or_skip()
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.chat.worker_tool_trace import digest_json

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    checkpoint = _seed_previous_generation(path, worker_id, contract, status="running")
    binding = WorkerLeaseBinding.acquire(
        client, task_id, worker_id=checkpoint["lease_worker_id"], host="HOST",
        generation=checkpoint["generation"], is_current=lambda: True,
        stop_event=threading.Event(),
    )
    binding.trace_tool_started(
        source="normal-loop", request_id="5" * 32, tool_name="search_text",
        arguments_sha256=digest_json({"query": "safe fixture"}),
    )
    assert binding.return_lease() is True
    assert client.task_snapshot(task_id)["status"] == "pending"
    result = _reconcile(path, worker_id, contract, client, monkeypatch)
    assert result == {"state": "blocked", "reason": "old_generation_tool_trace"}


def test_two_scan_difference_blocks_status_version_and_fence_changes(
        tmp_path, isolated_task_client, monkeypatch):
    from hub._services.chat import telegram_chat
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    contract = _contract_or_skip()
    checkpoint = _seed_previous_generation(path, worker_id, contract, status="running")
    before = telegram_chat._persistent_worker_reconciliation_scan(client, checkpoint, "running")
    conn = connect(database)
    conn.execute("UPDATE tasks SET description = ? WHERE id = ?", ("changed isolated version", task_id))
    conn.commit()
    conn.close()
    changed_version = telegram_chat._persistent_worker_reconciliation_scan(client, checkpoint, "running")
    assert before["sha256"] != changed_version["sha256"]
    binding = WorkerLeaseBinding.acquire(
        client, task_id, worker_id="other-worker@OTHER", host="OTHER",
        generation="6" * 32, is_current=lambda: True, stop_event=threading.Event(),
    )
    try:
        with_lease = telegram_chat._persistent_worker_reconciliation_scan(client, checkpoint, "running")
        assert with_lease["sha256"] != changed_version["sha256"]
        assert with_lease["active_old_lease"] is False
    finally:
        binding.return_lease()


def test_unstable_second_native_scan_keeps_running_checkpoint(
        tmp_path, isolated_task_client, monkeypatch):
    from hub._services.chat import telegram_chat

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    contract = _contract_or_skip()
    checkpoint = _seed_previous_generation(path, worker_id, contract, status="running")
    original = telegram_chat._persistent_worker_reconciliation_scan
    calls = 0

    def mutate_after_first_scan(*args):
        nonlocal calls
        result = original(*args)
        calls += 1
        if calls == 1:
            conn = connect(database)
            conn.execute("UPDATE tasks SET description = ? WHERE id = ?", ("raced", task_id))
            conn.commit()
            conn.close()
        return result

    monkeypatch.setattr(telegram_chat, "_persistent_worker_reconciliation_scan", mutate_after_first_scan)
    result = _reconcile(path, worker_id, contract, client, monkeypatch)
    assert result == {"state": "blocked", "reason": "task_inventory_unstable"}
    worker = slots.get_worker_slot(worker_id, path=path)
    assert worker["status"] == "running"
    assert worker[CHECKPOINT_FIELD] == checkpoint


def test_missing_native_candidate_page_fails_closed(
        tmp_path, isolated_task_client, monkeypatch):
    from hub._services.chat import telegram_chat
    from hub._services.task_lease_client import LeaseProtocolError

    client, database, connect, insert = isolated_task_client
    ids = [_insert_task(database, connect, insert, title=f"Page {n}") for n in range(101)]
    checkpoint = {
        "generation": "3" * 32,
        "lease_worker_id": "worker-" + "4" * 32 + "@HOST",
        "trace_contract_sha256": "a" * 64,
    }
    real_reader = client.task_candidates
    changed = False

    def change_between_pages(*, limit=100, offset=0):
        nonlocal changed
        if offset == 100 and not changed:
            conn = connect(database)
            conn.execute("UPDATE tasks SET status = 'review' WHERE id = ?", (ids[-1],))
            conn.commit()
            conn.close()
            changed = True
        return real_reader(limit=limit, offset=offset)

    monkeypatch.setattr(client, "task_candidates", change_between_pages)
    with pytest.raises(LeaseProtocolError):
        telegram_chat._persistent_worker_reconciliation_scan(client, checkpoint, "running")


@pytest.mark.parametrize(("field", "value"), [
    ("memory_hook_opt_in", "false"),
    ("think", "false"),
    ("allow_tools", 1),
    ("multi_role", None),
])
def test_invalid_worker_boolean_edit_preserves_config_bytes(tmp_path, field, value):
    from pathlib import Path

    path, worker_id = _cloud_worker(tmp_path)
    snapshot = slots.worker_configuration_snapshot(worker_id, path=path)
    before = Path(path).read_bytes()

    with pytest.raises(ValueError, match=field):
        slots.change_worker_configuration(
            worker_id, snapshot["configuration_version"], {field: value}, path=path,
        )

    assert Path(path).read_bytes() == before


def test_manual_buddha_stop_isolated_from_cloud_profiles_and_monitor(monkeypatch):
    from contextlib import contextmanager
    from http.server import BaseHTTPRequestHandler
    import socket

    from hub._services.chat import telegram_chat as chat

    profiles = {
        "cloud-profile-a": {"id": "cloud-profile-a", "enabled": True, "type": "continuous",
                            "status": "idle"},
        "cloud-profile-b": {"id": "cloud-profile-b", "enabled": True, "type": "continuous",
                            "status": "idle"},
        "buddha_always_on": {"id": "buddha_always_on", "enabled": True, "type": "continuous",
                              "status": "idle"},
    }

    @contextmanager
    def no_revision_write():
        yield lambda: None

    monkeypatch.setattr(slots, "worker_admission_transaction", no_revision_write)
    monkeypatch.setattr(
        slots, "system_worker_at_version",
        lambda worker_id, version, *, version_scope: dict(profiles[worker_id]),
    )
    monkeypatch.setattr(chat, "_execution_worker_slot", lambda worker_id: profiles.get(worker_id))
    monkeypatch.setattr(chat, "_WORKER_CONTROLS", {})
    monkeypatch.setattr(chat, "_ACTIVE_WORKER_THREADS", {})
    monkeypatch.setattr(chat, "_WORKER_EXECUTIONS", {})

    monitor_entered = threading.Event()
    monkeypatch.setattr(
        chat, "_resume_persistent_cloud_workers_at_startup",
        lambda _stop: {"state": "ready", "profiles": []},
    )

    def retry_always_on(_stop_event):
        monitor_entered.set()
        return {"state": "waiting_for_local_provider", "retry": True}

    monkeypatch.setattr(chat, "_resume_always_on_at_startup", retry_always_on)

    controls = {}

    def start_reserved(control, slot, _custom_prompt):
        controls[slot["id"]] = control
        if slot["id"] == "cloud-profile-a":
            raise RuntimeError("fixture start failure")
        control.launch_attempted = True
        control.worker_thread_started = True

        def wait_for_shutdown():
            if control.stop_event.wait(5):
                control.done_event.set()

        worker_thread = threading.Thread(target=wait_for_shutdown, daemon=True)
        control.thread = worker_thread
        chat._ACTIVE_WORKER_THREADS[slot["id"]] = worker_thread
        worker_thread.start()
        return {"ok": True}, 200

    monkeypatch.setattr(chat, "_start_reserved_worker_execution", start_reserved)
    monkeypatch.setattr(
        chat, "_write_revocation_receipt",
        lambda control, worker, *, outcome: {
            "confirmed": True, "status_persisted": True, "outcome": outcome,
        },
    )

    server = chat.QuietHTTPServer(
        ("127.0.0.1", 0), BaseHTTPRequestHandler, bind_and_activate=False,
    )
    server_closed = False
    monitor_thread = None
    try:
        monitor_thread = chat._start_always_on_startup_monitor(server)
        assert monitor_entered.wait(1)
        shutdown_event = server.always_on_startup_stop

        def start_profile(worker_id, generation_digit, *, profile_version):
            physical_worker_id = "worker-" + generation_digit * 32
            return chat._start_worker_execution(
                worker_id,
                expected_service_instance=chat._WORKER_SERVICE_INSTANCE,
                expected_configuration_version=f"configuration-{worker_id}",
                _startup_stop_event=shutdown_event,
                _startup_generation=generation_digit * 32,
                _startup_physical_worker_id=physical_worker_id,
                _startup_lease_worker_id=f"{physical_worker_id}@{socket.gethostname()}",
                _startup_profile_version=profile_version,
            )

        failed_response, failed_status = start_profile("cloud-profile-a", "a", profile_version=True)
        active_response, active_status = start_profile("cloud-profile-b", "b", profile_version=True)
        buddha_response, buddha_status = start_profile("buddha_always_on", "c", profile_version=False)
        failed = controls["cloud-profile-a"]
        active = controls["cloud-profile-b"]
        buddha = controls["buddha_always_on"]

        assert failed_status == 503
        assert failed_response["execution"]["terminal"] is True
        assert active_status == 200 and active_response["execution"]["state"] == "running"
        assert buddha_status == 200 and buddha_response["execution"]["state"] == "running"
        assert failed.stop_event.is_set()
        assert not shutdown_event.is_set()
        assert not active.stop_event.is_set() and active.thread.is_alive()
        assert not buddha.stop_event.is_set() and buddha.thread.is_alive()
        assert monitor_thread.is_alive()

        # A normal Buddha Stop is routed through the same per-worker revocation
        # path as the user action. It must not set the server-wide signal.
        confirmed, _updated, receipt, status = chat._request_worker_revocation(
            "buddha_always_on", profiles["buddha_always_on"], activity="Manuell gestoppt",
        )
        assert confirmed and status == 200 and receipt["confirmed"]
        assert buddha.stop_event.is_set()
        assert not shutdown_event.is_set()
        assert not active.stop_event.is_set() and active.thread.is_alive()
        assert monitor_thread.is_alive()
        assert not buddha.thread.is_alive()

        # The per-worker signal stays linked to the server-wide shutdown.
        assert buddha.stop_event._shutdown_event is shutdown_event
        server.server_close()
        server_closed = True
        assert shutdown_event.is_set()
        assert active.stop_event.is_set() and active.stop_event.wait(0) is True
        assert buddha.stop_event._shutdown_event.is_set()
        active.thread.join(timeout=1)
        assert not active.thread.is_alive() and active.done_event.is_set()
        assert not monitor_thread.is_alive()
    finally:
        if not server_closed:
            server.server_close()
        if monitor_thread is not None:
            monitor_thread.join(timeout=1)
        for control in controls.values():
            worker_thread = control.thread
            if worker_thread is not None and worker_thread.is_alive():
                control.stop_event.set()
                worker_thread.join(timeout=1)
