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
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    worker = slots.get_worker_slot(worker_id, path=path)
    profile = {**profile, "task_id": worker.get("task_id")}
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
    start_request_id = "a" * 32
    pending = {
        "schema": "bach.persistent-worker-controller.v2",
        "phase": "admission_pending",
        "worker_id": worker_id,
        "service_instance": telegram_chat._WORKER_SERVICE_INSTANCE,
        "start_request_id": start_request_id,
        "intent_id": profile["intent_id"],
        "profile_version": profile["profile_version"],
        "trace_contract_sha256": "b" * 64,
        "generation": generation,
        "physical_worker_id": physical_worker_id,
        "lease_worker_id": f"{physical_worker_id}@{socket.gethostname()}",
    }
    _store_checkpoint(path, worker_id, pending)
    response, status = telegram_chat._start_worker_execution(
        worker_id,
        start_request_id=start_request_id,
        expected_service_instance=telegram_chat._WORKER_SERVICE_INSTANCE,
        expected_configuration_version=profile["configuration_version"],
        _startup_stop_event=threading.Event(),
        _startup_generation=generation,
        _startup_physical_worker_id=physical_worker_id,
        _startup_lease_worker_id=f"{physical_worker_id}@{socket.gethostname()}",
        _startup_profile_version=True,
        _startup_persistent_cloud_profile=profile,
        _startup_persistent_cloud_checkpoint=pending,
    )
    assert status == 200
    assert response["ok"] is True
    assert response["execution"]["generation"] == generation
    assert version_scopes == ["worker_profile"]


def test_persistent_cloud_startup_without_binding_fails_before_registry_or_effects(
        tmp_path, isolated_task_client, monkeypatch):
    import socket

    from hub._services.chat import telegram_chat

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    profile = _startup_profile(path)
    assert profile["state"] == "ready"
    assert profile["reason"] == "explicit_opt_in"

    class TrackingRegistry(dict):
        def __init__(self):
            super().__init__()
            self.registrations = []

        def __setitem__(self, key, value):
            self.registrations.append(key)
            super().__setitem__(key, value)

    controls = TrackingRegistry()
    executions = TrackingRegistry()
    active_threads = TrackingRegistry()
    monkeypatch.setattr(telegram_chat, "_WORKER_CONTROLS", controls)
    monkeypatch.setattr(telegram_chat, "_WORKER_EXECUTIONS", executions)
    monkeypatch.setattr(telegram_chat, "_ACTIVE_WORKER_THREADS", active_threads)

    client_reads = []
    monkeypatch.setattr(telegram_chat, "_native_task_client", lambda: (client_reads.append(True) or client))
    backend_snapshots = []
    monkeypatch.setattr(telegram_chat, "_snapshot_chat_backend",
                        lambda *args, **kwargs: backend_snapshots.append((args, kwargs)))
    starts = []
    monkeypatch.setattr(telegram_chat, "_start_reserved_worker_execution",
                        lambda *args: (starts.append(args) or ({"ok": True}, 200)))

    request_id = "8" * 32
    generation = "9" * 32
    physical_worker_id = "worker-" + "a" * 32
    response, status = telegram_chat._start_worker_execution(
        worker_id,
        start_request_id=request_id,
        expected_service_instance=telegram_chat._WORKER_SERVICE_INSTANCE,
        expected_configuration_version=profile["configuration_version"],
        _startup_stop_event=threading.Event(),
        _startup_generation=generation,
        _startup_physical_worker_id=physical_worker_id,
        _startup_lease_worker_id=f"{physical_worker_id}@{socket.gethostname()}",
        _startup_profile_version=True,
    )

    assert status == 403
    assert response["error_code"] == "persistent_admission_binding_required"
    assert response["admission"] == {
        "admitted": False, "worker_id": worker_id, "start_request_id": request_id,
        "service_instance": telegram_chat._WORKER_SERVICE_INSTANCE,
    }
    assert controls.registrations == []
    assert executions.registrations == []
    assert active_threads.registrations == []
    assert not client_reads
    assert not backend_snapshots
    assert not starts
    assert client.read(task_id).leased is False


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


@pytest.mark.parametrize("unknown_ack", [False, True], ids=["confirmed-readback", "unknown-cas-ack"])
def test_persistent_cloud_worker_waits_for_admitted_checkpoint_readback(
        tmp_path, isolated_task_client, monkeypatch, unknown_ack):
    from hub import rheingold
    from hub._services.chat import telegram_chat

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    monkeypatch.setattr(telegram_chat, "_native_task_client", lambda: client)
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "lead"})
    monkeypatch.setattr(telegram_chat, "_persistent_worker_trace_contract", lambda: {
        "schema": "bach.worker-tool-trace.v1", "source_sha256": "a" * 64,
    })
    monkeypatch.setattr(telegram_chat, "_active_worker_ids", lambda: set())
    for name in ("_WORKER_CONTROLS", "_WORKER_EXECUTIONS", "_ACTIVE_WORKER_THREADS"):
        monkeypatch.setattr(telegram_chat, name, {})

    started = threading.Event()
    admitted_written = threading.Event()
    return_ack = threading.Event()
    readback_confirmed = threading.Event()
    effect_seen = threading.Event()
    effects = []
    thread_errors = []
    worker_threads = []

    def start_reserved(control, slot, _custom_prompt):
        control.launch_attempted = True

        def run_after_gate():
            try:
                started.set()
                if not telegram_chat._await_worker_startup_admission(control):
                    return
                assert readback_confirmed.is_set()
                binding = telegram_chat._acquire_worker_task(
                    control, slot, control.physical_worker_id,
                )
                if binding is not None:
                    effects.append(("claim", binding.task_id, binding._ack.fence))
                    effect_seen.set()
                    binding.return_lease()
            except Exception as exc:  # noqa: BLE001 -- thread failure is forwarded to test assertions
                thread_errors.append(type(exc).__name__)
            finally:
                control.done_event.set()

        worker_thread = threading.Thread(target=run_after_gate, daemon=True)
        worker_threads.append(worker_thread)
        control.thread = worker_thread
        control.worker_thread_started = True
        telegram_chat._ACTIVE_WORKER_THREADS[slot["id"]] = worker_thread
        worker_thread.start()
        return {"ok": True}, 200

    monkeypatch.setattr(telegram_chat, "_start_reserved_worker_execution", start_reserved)
    monkeypatch.setattr(telegram_chat, "_persistent_worker_trace_contract", lambda: {
        "schema": "bach.worker-tool-trace.v1", "source_sha256": "a" * 64,
    })
    real_set_checkpoint = slots.set_persistent_worker_controller_checkpoint

    def tracked_checkpoint(*args, **kwargs):
        checkpoint = args[5] if len(args) > 5 else kwargs.get("checkpoint")
        result = real_set_checkpoint(*args, **kwargs)
        if isinstance(checkpoint, dict) and checkpoint.get("phase") == "admitted":
            admitted_written.set()
            if unknown_ack:
                raise RuntimeError("synthetic unknown commit acknowledgement")
            assert return_ack.wait(3)
        return result

    monkeypatch.setattr(slots, "set_persistent_worker_controller_checkpoint", tracked_checkpoint)
    real_readback = telegram_chat._persistent_cloud_admission_readback

    def tracked_readback(*args, **kwargs):
        result = real_readback(*args, **kwargs)
        if result:
            readback_confirmed.set()
        return result

    monkeypatch.setattr(telegram_chat, "_persistent_cloud_admission_readback", tracked_readback)
    startup_stop = threading.Event()
    results = []
    caller = threading.Thread(
        target=lambda: results.append(
            telegram_chat._resume_persistent_cloud_workers_at_startup(startup_stop)
        ),
        daemon=True,
    )
    caller.start()
    try:
        assert started.wait(3)
        if unknown_ack:
            caller.join(3)
            assert not caller.is_alive()
            assert results[0]["profiles"][0]["state"] == "start_unconfirmed"
            assert admitted_written.is_set()
            assert not readback_confirmed.is_set()
            assert not effect_seen.wait(0.2)
            assert effects == []
            assert client.read(task_id).leased is False
            stored = slots.get_worker_slot(worker_id, path=path)
            assert stored[CHECKPOINT_FIELD]["phase"] == "admitted"
        else:
            assert admitted_written.wait(3)
            assert not readback_confirmed.is_set()
            assert not effect_seen.wait(0.2)
            assert effects == []
            assert client.read(task_id).leased is False
            return_ack.set()
            caller.join(3)
            assert not caller.is_alive()
            assert results[0]["profiles"][0]["state"] == "admitted"
            assert readback_confirmed.is_set()
            assert effect_seen.wait(3)
            assert effects and effects[0][0:2] == ("claim", task_id)
            for worker_thread in worker_threads:
                worker_thread.join(3)
            assert client.read(task_id).leased is False
        assert thread_errors == []
    finally:
        return_ack.set()
        startup_stop.set()
        caller.join(3)
        for worker_thread in worker_threads:
            worker_thread.join(3)


def test_persistent_cloud_optout_after_readback_stays_closed_before_assignment(
        tmp_path, isolated_task_client, monkeypatch):
    import time

    from hub import rheingold
    from hub._services.chat import telegram_chat
    from hub._services.chat.chat_runtime import ChatRuntime

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    monkeypatch.setattr(telegram_chat, "_native_task_client", lambda: client)
    monkeypatch.setattr(rheingold, "get_lead_config", lambda: {"mode": "lead"})
    monkeypatch.setattr(telegram_chat, "_persistent_worker_trace_contract", lambda: {
        "schema": "bach.worker-tool-trace.v1", "source_sha256": "a" * 64,
    })
    monkeypatch.setattr(telegram_chat, "_active_worker_ids", lambda: set())
    for name in ("_WORKER_CONTROLS", "_WORKER_EXECUTIONS", "_ACTIVE_WORKER_THREADS"):
        monkeypatch.setattr(telegram_chat, name, {})

    class SyntheticBackend:
        manages_own_tools = False

        def __init__(self):
            self.chat_calls = 0

        async def chat(self, *_args, **_kwargs):
            self.chat_calls += 1
            return "synthetic response"

    backend = SyntheticBackend()
    backend_snapshots = []
    assignments = []
    task_acquires = []
    readback_revoked = threading.Event()
    readback_calls = 0
    real_acquire = client.acquire

    def counted_acquire(*args, **kwargs):
        task_acquires.append((args, kwargs))
        return real_acquire(*args, **kwargs)

    monkeypatch.setattr(client, "acquire", counted_acquire)
    monkeypatch.setattr(telegram_chat, "runtime", ChatRuntime(backend, session_store=None))
    monkeypatch.setattr(
        telegram_chat,
        "_snapshot_chat_backend",
        lambda *_args, **_kwargs: (backend_snapshots.append(True) or backend, "provider/free-model"),
    )
    monkeypatch.setattr(
        telegram_chat,
        "begin_assignment",
        lambda **kwargs: (assignments.append(kwargs) or {"assignment_id": "synthetic"}),
    )
    monkeypatch.setattr(telegram_chat, "finish_assignment", lambda *_args, **_kwargs: None)
    real_readback = telegram_chat._persistent_cloud_admission_readback

    def readback_then_opt_out(*args, **kwargs):
        nonlocal readback_calls
        result = real_readback(*args, **kwargs)
        readback_calls += 1
        if result and not readback_revoked.is_set():
            current = slots.worker_configuration_snapshot(worker_id, path=path)
            slots.change_worker_configuration(
                worker_id, current["configuration_version"],
                {"persistent_opt_in": False}, path=path,
            )
            readback_revoked.set()
        return result

    monkeypatch.setattr(
        telegram_chat, "_persistent_cloud_admission_readback", readback_then_opt_out,
    )
    startup_stop = threading.Event()
    results = []
    caller = threading.Thread(
        target=lambda: results.append(
            telegram_chat._resume_persistent_cloud_workers_at_startup(startup_stop)
        ),
        daemon=True,
    )
    caller.start()
    try:
        caller.join(5)
        assert not caller.is_alive()
        assert results[0]["profiles"][0]["state"] == "start_unconfirmed"
        assert readback_revoked.is_set() and readback_calls >= 1
        assert assignments == []
        assert backend_snapshots == []
        assert backend.chat_calls == 0
        assert task_acquires == []
        assert client.read(task_id).leased is False
        current = slots.get_worker_slot(worker_id, path=path)
        assert current["persistent_opt_in"] is False
        assert CHECKPOINT_FIELD not in current
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            thread = telegram_chat._ACTIVE_WORKER_THREADS.get(worker_id)
            if thread is None or not getattr(thread, "is_alive", lambda: False)():
                break
            time.sleep(0.01)
        thread = telegram_chat._ACTIVE_WORKER_THREADS.get(worker_id)
        assert thread is None or not getattr(thread, "is_alive", lambda: False)()
    finally:
        startup_stop.set()
        caller.join(3)
        thread = telegram_chat._ACTIVE_WORKER_THREADS.get(worker_id)
        if thread is not None and getattr(thread, "is_alive", lambda: False)():
            thread.join(3)



def test_persistent_cloud_claim_guard_rechecks_optout_after_gate(tmp_path, isolated_task_client, monkeypatch):
    import socket

    from hub._services.chat import telegram_chat

    path, worker_id = _cloud_worker(tmp_path)
    _opt_in(path, worker_id)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
    client, database, connect, insert = isolated_task_client
    task_id = _insert_task(database, connect, insert)
    monkeypatch.setattr(telegram_chat, "_native_task_client", lambda: client)

    worker = slots.get_worker_slot(worker_id, path=path)
    profile = {**_startup_profile(path), "task_id": worker.get("task_id")}
    request_id = "5" * 32
    generation = "6" * 32
    physical_worker_id = "worker-" + "7" * 32
    lease_worker_id = f"{physical_worker_id}@{socket.gethostname()}"
    pending = _checkpoint(worker, "admission_pending")
    pending.update({
        "service_instance": telegram_chat._WORKER_SERVICE_INSTANCE,
        "start_request_id": request_id,
        "generation": generation,
        "physical_worker_id": physical_worker_id,
        "lease_worker_id": lease_worker_id,
    })
    _store_checkpoint(path, worker_id, pending)
    worker = slots.get_worker_slot(worker_id, path=path)
    admitted = {**pending, "phase": "admitted"}
    config = slots.worker_configuration_snapshot(worker_id, path=path)
    slots.set_persistent_worker_controller_checkpoint(
        worker_id, config["configuration_version"], slots._worker_profile_version(worker),
        worker["persistent_opt_in_id"], pending, admitted, path=path,
    )

    cloud_binding = {"profile": profile, "checkpoint": dict(pending)}
    control = telegram_chat._WorkerControl(
        worker_id,
        generation=generation,
        physical_worker_id=physical_worker_id,
        lease_worker_id=lease_worker_id,
        start_request_id=request_id,
        admitted_worker={"id": worker_id, "type": worker.get("type")},
        slot_policy_reader=telegram_chat._execution_slot_reader(
            worker, persistent_cloud_binding=cloud_binding,
        ),
        startup_admission_required=True,
        persistent_cloud_admission_binding=cloud_binding,
    )
    monkeypatch.setattr(telegram_chat, "_WORKER_CONTROLS", {worker_id: control})
    monkeypatch.setattr(telegram_chat, "_WORKER_EXECUTIONS", {worker_id: control})
    monkeypatch.setattr(telegram_chat, "_ACTIVE_WORKER_THREADS", {})

    assert telegram_chat._persistent_cloud_admission_readback(worker_id, profile, admitted)
    assert telegram_chat._confirm_persistent_startup_gate(
        worker_id, request_id, generation, admitted_checkpoint=admitted,
    )
    assert control.startup_admission_confirmed.is_set()
    assert cloud_binding["checkpoint"] == admitted

    current = slots.worker_configuration_snapshot(worker_id, path=path)
    slots.change_worker_configuration(
        worker_id, current["configuration_version"], {"persistent_opt_in": False}, path=path,
    )

    acquired = []
    snapshots = []
    candidates = []
    real_acquire = client.acquire
    real_snapshot = client.task_snapshot
    real_candidates = client.task_candidates

    def counted_acquire(*args, **kwargs):
        acquired.append((args, kwargs))
        return real_acquire(*args, **kwargs)

    def counted_snapshot(*args, **kwargs):
        snapshots.append((args, kwargs))
        return real_snapshot(*args, **kwargs)

    def counted_candidates(*args, **kwargs):
        result = real_candidates(*args, **kwargs)
        candidates.extend(item["id"] for item in result["tasks"])
        return result

    monkeypatch.setattr(client, "acquire", counted_acquire)
    monkeypatch.setattr(client, "task_snapshot", counted_snapshot)
    monkeypatch.setattr(client, "task_candidates", counted_candidates)
    current_slot = slots.get_worker_slot(worker_id, path=path)
    with pytest.raises(RuntimeError, match="Persistente Worker-Freigabe"):
        telegram_chat._acquire_worker_task(control, current_slot, physical_worker_id)

    assert task_id in candidates
    assert acquired == []
    assert snapshots == []
    assert client.read(task_id).leased is False
    assert control.task_binding is None
    current = slots.get_worker_slot(worker_id, path=path)
    assert current["persistent_opt_in"] is False
    assert CHECKPOINT_FIELD not in current

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
    def system_worker_at_version(worker_id, version, *, version_scope, persistent_intent_id=None):
        # The native helper accepts this keyword on both persistent and legacy paths.
        # These fixtures intentionally model legacy starts with no persistent intent.
        assert persistent_intent_id is None
        return dict(profiles[worker_id])

    monkeypatch.setattr(slots, "system_worker_at_version", system_worker_at_version)
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

        failed_response, failed_status = start_profile("cloud-profile-a", "a", profile_version=False)
        active_response, active_status = start_profile("cloud-profile-b", "b", profile_version=False)
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

# The core Always-On worker uses the same explicit CAS as dynamic persistent
# profiles, while retaining its canonical system-slot identity.
def _always_on_core(tmp_path):
    path = str(tmp_path / "always-on-slots.json")
    slots.initialize_slots_config(path)
    return path, "buddha_always_on"


def _opt_in_core(path):
    current = slots.worker_configuration_snapshot("buddha_always_on", path=path)
    return slots.change_worker_configuration(
        "buddha_always_on", current["configuration_version"],
        {"persistent_opt_in": True}, path=path,
    )


def test_always_on_persistent_opt_in_is_local_and_cas_bound(tmp_path):
    path, worker_id = _always_on_core(tmp_path)
    before = slots.worker_configuration_snapshot(worker_id, path=path)
    opted = _opt_in_core(path)
    stored = slots.get_slot(worker_id, path)
    assert opted["persistent_opt_in"] is True
    assert stored["persistent_opt_in"] is True
    assert len(stored["persistent_opt_in_id"]) == 32
    assert stored["persistent_opt_in_profile_version"] == slots._persistent_core_profile_version(
        slots.get_always_on_execution_slot(path)
    )
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_worker_configuration(
            worker_id, before["configuration_version"], {"persistent_opt_in": False}, path=path,
        )


@pytest.mark.parametrize(("backend", "model", "fallbacks"), [
    ("ollama-cloud", "qwen3.8:27b-mlx", []),
    ("lmstudio", "qwen3.8:27b-mlx", []),
    ("ollama", "qwen3.8:27b-mlx:cloud", []),
    ("ollama", "qwen3.8:27b-mlx", [{"backend": "ollama", "model": "qwen3.5:4b"}]),
])
def test_always_on_persistent_opt_in_rejects_unsupported_or_fallback_routes(
        tmp_path, backend, model, fallbacks):
    path, worker_id = _always_on_core(tmp_path)
    slots.update_slot(worker_id, {
        "backend": backend, "model": model, "model_fallbacks": fallbacks,
    }, path)
    current = slots.worker_configuration_snapshot(worker_id, path=path)
    with pytest.raises(ValueError, match="lokales Modellziel"):
        slots.change_worker_configuration(
            worker_id, current["configuration_version"], {"persistent_opt_in": True}, path=path,
        )
    stored = slots.get_slot(worker_id, path)
    assert stored.get("persistent_opt_in") is not True
    assert "persistent_opt_in_id" not in stored


def test_always_on_profile_edit_revokes_consent_and_restoring_does_not_resurrect(
        tmp_path, monkeypatch):
    from hub._services import skill_source_service

    path, worker_id = _always_on_core(tmp_path)
    monkeypatch.setattr(skill_source_service, "check_write_locks", lambda _path: None)
    _opt_in_core(path)
    original = slots.get_slot(worker_id, path)["model"]
    intent_id = slots.get_slot(worker_id, path)["persistent_opt_in_id"]

    slots.update_slot(worker_id, {"model": original + "-changed"}, path)
    changed = slots.get_slot(worker_id, path)
    assert changed["persistent_opt_in"] is False
    assert "persistent_opt_in_id" not in changed
    assert "persistent_opt_in_profile_version" not in changed
    assert CHECKPOINT_FIELD not in changed

    slots.update_slot(worker_id, {"model": original}, path)
    restored = slots.get_slot(worker_id, path)
    assert restored["model"] == original
    assert restored["persistent_opt_in"] is False
    assert "persistent_opt_in_id" not in restored

    # The second Core-profile CAS writer must revoke the same consent binding.
    _opt_in_core(path)
    before = slots.core_system_agents_snapshot(path)
    slots.change_core_system_agent(
        worker_id, before["configuration_version"], {"model": original + "-cas-change"}, path=path,
    )
    changed_by_cas = slots.get_slot(worker_id, path)
    assert changed_by_cas["persistent_opt_in"] is False
    assert "persistent_opt_in_id" not in changed_by_cas
    assert intent_id != slots.get_slot(worker_id, path).get("persistent_opt_in_id")


def test_always_on_status_and_controller_task_changes_preserve_profile_consent(tmp_path):
    path, worker_id = _always_on_core(tmp_path)
    _opt_in_core(path)
    intent_id = slots.get_slot(worker_id, path)["persistent_opt_in_id"]
    slots.update_slot(worker_id, {
        "status": "running", "task_id": 481, "current_activity": "Task gebunden",
    }, path)
    running = slots.get_slot(worker_id, path)
    assert running["persistent_opt_in"] is True
    assert running["persistent_opt_in_id"] == intent_id
    slots.update_slot(worker_id, {"status": "idle", "task_id": None}, path)
    idle = slots.get_slot(worker_id, path)
    assert idle["persistent_opt_in"] is True
    assert idle["persistent_opt_in_id"] == intent_id


def _capacity_policy(model):
    from hub._services.chat.local_resource_reserve import GIB, SCHEMA

    return {
        "schema": SCHEMA,
        "enabled": True,
        "memory_reserve_bytes": GIB,
        "disk_reserve_bytes": GIB,
        "wait_seconds": 60,
        "poll_seconds": 1,
        "models": {
            model: {
                "digest": "d" * 64,
                "weight_budget_bytes": GIB,
                "kv_headroom_bytes": GIB,
                "overhead_bytes": GIB,
                "num_ctx": 16384,
            }
        },
    }


def _capacity_receipt(model, *, state="ready", checked_at=None, policy_version="a" * 64,
                      memory_available=None, disk_free=None):
    from hub._services.chat.local_resource_reserve import GIB, SCHEMA

    return {
        "schema": SCHEMA,
        "state": state,
        "admitted": state == "ready",
        "enforced": True,
        "retryable": state != "ready",
        "checked_at": checked_at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "policy_version": policy_version,
        "model": model,
        "wait_seconds": 60,
        "poll_seconds": 1,
        "memory_total_bytes": 8 * GIB,
        "memory_available_bytes": memory_available if memory_available is not None else 5 * GIB,
        "memory_required_bytes": 4 * GIB,
        "disk_free_bytes": disk_free or {"taskdb": 8 * GIB, "runtime": 8 * GIB, "slots": 8 * GIB},
        "disk_reserve_bytes": GIB,
        "weight_request_bytes": GIB,
        "resident_weight_credit": False,
    }


def test_core_capacity_reauthorization_requires_fresh_current_semantic_ready_probe(
        tmp_path, monkeypatch):
    from hub._services.chat import local_resource_reserve

    path, _ = _always_on_core(tmp_path)
    _opt_in_core(path)
    worker = slots.get_always_on_execution_slot(path)
    model = worker["model"]
    policy = _capacity_policy(model)
    policy_version = "a" * 64
    monkeypatch.setattr(local_resource_reserve, "read_policy",
                        lambda: (policy, policy_version))

    blocked = _capacity_receipt(
        model, state="waiting_memory_reserve", policy_version=policy_version,
        memory_available=3 * local_resource_reserve.GIB,
    )
    baseline = slots._persistent_core_capacity_observation(
        blocked, worker=worker, expected_state="waiting_memory_reserve")
    ready = _capacity_receipt(model, policy_version=policy_version)
    observed = slots._persistent_core_capacity_observation(
        ready, worker=worker, expected_state="ready")
    assert baseline is not None and baseline["state"] == "waiting_memory_reserve"
    assert observed is not None and observed["state"] == "ready"
    assert observed["fingerprint"] != baseline["fingerprint"]

    recovery_state = {
        "phase": "capacity_wait",
        "capacity_state": baseline["state"],
        "capacity_policy_version": baseline["policy_version"],
        "capacity_fingerprint": baseline["fingerprint"],
    }
    proof = {
        "schema": "bach.persistent-core-capacity-reauthorization.v1",
        "receipt": ready,
        "previous_state": baseline["state"],
        "previous_policy_version": baseline["policy_version"],
        "previous_fingerprint": baseline["fingerprint"],
    }
    assert slots._valid_persistent_core_capacity_reauthorization(
        proof, worker=worker, recovery_state=recovery_state)

    stale = dict(ready, checked_at=(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=121)
    ).isoformat())
    assert slots._persistent_core_capacity_observation(
        stale, worker=worker, expected_state="ready") is None
    future = dict(ready, checked_at=(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1)
    ).isoformat())
    assert slots._persistent_core_capacity_observation(
        future, worker=worker, expected_state="ready") is None

    # A plausible ready receipt from a different policy cannot reset this wait.
    altered_policy = dict(policy, memory_reserve_bytes=2 * local_resource_reserve.GIB)
    altered_version = "b" * 64
    monkeypatch.setattr(local_resource_reserve, "read_policy",
                        lambda: (altered_policy, altered_version))
    altered_ready = _capacity_receipt(
        model, policy_version=altered_version, memory_available=6 * local_resource_reserve.GIB,
    )
    altered_ready["memory_required_bytes"] = 5 * local_resource_reserve.GIB
    assert slots._persistent_core_capacity_observation(
        altered_ready, worker=worker, expected_state="ready") is not None
    altered_proof = {**proof, "receipt": altered_ready}
    assert not slots._valid_persistent_core_capacity_reauthorization(
        altered_proof, worker=worker, recovery_state=recovery_state)

    # An arbitrary state/fingerprint change or RAM reading that remains below
    # the configured threshold is not a fresh capacity-ready transition.
    still_waiting = _capacity_receipt(
        model, state="waiting_memory_reserve", policy_version=altered_version,
        memory_available=4 * local_resource_reserve.GIB,
    )
    assert slots._persistent_core_capacity_observation(
        still_waiting, worker=worker, expected_state="ready") is None

@pytest.fixture
def core_reconciliation_fixture(tmp_path, isolated_task_client, monkeypatch):
    """Bind real Core snapshots and scans to private configuration/TaskDB files."""
    from pathlib import Path
    from types import SimpleNamespace

    from hub._services.chat import telegram_chat

    client, database, connect, insert = isolated_task_client

    def prepare(status="running"):
        path, worker_id = _always_on_core(tmp_path)
        _opt_in_core(path)
        initial = slots.persistent_core_startup_snapshot(path)
        contract = telegram_chat._persistent_worker_trace_contract()
        assert contract is not None, "The real normal-loop trace contract is required"
        checkpoint = _checkpoint(
            initial["slot"], "admitted", trace_hash=contract["source_sha256"],
        )
        checkpoint["profile_version"] = initial["profile_version"]
        recovery = telegram_chat._core_recovery_record(
            initial, "active", checkpoint=checkpoint,
        )
        config = slots.load_slots_config(path, strict=True)
        config["slots"][worker_id].update({
            "status": status,
            CHECKPOINT_FIELD: checkpoint,
            slots.PERSISTENT_CORE_RECOVERY_FIELD: recovery,
        })
        slots.save_slots_config(config, path)
        monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", path)
        monkeypatch.setattr(telegram_chat, "_active_worker_ids", lambda: set())
        monkeypatch.setattr(telegram_chat, "_native_task_client", lambda: client)
        monkeypatch.setattr(
            telegram_chat, "_start_worker_execution",
            lambda *args, **kwargs: pytest.fail("Reconciliation must not start a worker"),
        )

        task_id = _insert_task(database, connect, insert, title="Core reconciliation")
        # Initialize fixture service schemas before taking the read-only observation.
        client.task_snapshot(task_id)
        client.read(task_id)
        client.tool_trace_events(task_id)
        snapshot = slots.persistent_core_startup_snapshot()
        assert snapshot["state"] == "prior_generation_unsettled"
        assert snapshot["slot"]["status"] == status
        assert slots._valid_persistent_core_recovery_state(
            recovery, worker=snapshot["slot"], checkpoint=checkpoint,
        )
        scans = []
        original_scan = telegram_chat._persistent_worker_reconciliation_scan

        def observe_scan(*args):
            result = original_scan(*args)
            scans.append(result)
            return result

        monkeypatch.setattr(
            telegram_chat, "_persistent_worker_reconciliation_scan", observe_scan,
        )
        return SimpleNamespace(
            chat=telegram_chat, path=Path(path), snapshot=snapshot,
            contract=contract, client=client, task_id=task_id, scans=scans,
            checkpoint=checkpoint, recovery=recovery, database=database,
        )

    return prepare


@pytest.mark.parametrize("status", ["idle", "running", "error"])
def test_persistent_core_reconciliation_consumes_real_snapshot_status(
        core_reconciliation_fixture, status):
    case = core_reconciliation_fixture(status)
    config_before = case.path.read_bytes()
    task_before = case.client.task_snapshot(case.task_id)
    lease_before = case.client.read(case.task_id)
    assert case.snapshot["status"] == case.snapshot["slot"]["status"] == status

    proof = case.chat._persistent_core_reconciliation_proof(
        case.snapshot, case.contract,
    )

    assert proof is not None
    assert proof["status_before"] == status
    assert proof["stable_scans"] == 2 and proof["complete"] is True
    assert len(case.scans) == 2
    assert all(scan["complete"] is True for scan in case.scans)
    assert case.scans[0]["sha256"] == case.scans[1]["sha256"]
    assert slots._valid_persistent_core_reconciliation_proof(
        proof, worker=case.snapshot["slot"], checkpoint=case.checkpoint,
        recovery_state=case.recovery,
    )
    assert case.path.read_bytes() == config_before
    assert case.client.task_snapshot(case.task_id) == task_before
    after = case.client.read(case.task_id)
    assert (after.leased, after.fence) == (lease_before.leased, lease_before.fence)


def test_persistent_core_reconciliation_rejects_real_snapshot_status_drift(
        core_reconciliation_fixture):
    case = core_reconciliation_fixture("running")
    slots.update_slot("buddha_always_on", {"status": "error"}, path=str(case.path))
    assert slots.persistent_core_startup_snapshot()["status"] == "error"
    before = case.path.read_bytes()

    assert case.chat._persistent_core_reconciliation_proof(
        case.snapshot, case.contract,
    ) is None
    assert case.scans == []
    assert case.path.read_bytes() == before


@pytest.mark.parametrize("gate", [
    "active_old_lease", "old_generation_trace", "identity_conflict",
])
def test_persistent_core_reconciliation_preserves_native_lease_trace_identity_gates(
        core_reconciliation_fixture, gate):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
    from hub._services.chat.worker_tool_trace import digest_json

    case = core_reconciliation_fixture()
    generation = "6" * 32 if gate == "identity_conflict" else case.checkpoint["generation"]
    binding = WorkerLeaseBinding.acquire(
        case.client, case.task_id, worker_id=case.checkpoint["lease_worker_id"],
        host="HOST", generation=generation, is_current=lambda: True,
        stop_event=threading.Event(),
    )
    try:
        if gate != "active_old_lease":
            binding.trace_tool_started(
                source="normal-loop", request_id="5" * 32, tool_name="search_text",
                arguments_sha256=digest_json({"query": "synthetic trace only"}),
            )
            assert binding.return_lease() is True
        before = case.path.read_bytes()
        task_before = case.client.task_snapshot(case.task_id)
        lease_before = case.client.read(case.task_id)

        assert case.chat._persistent_core_reconciliation_proof(
            case.snapshot, case.contract,
        ) is None
        assert len(case.scans) == 1 and case.scans[0][gate] is True
        assert case.path.read_bytes() == before
        assert case.client.task_snapshot(case.task_id) == task_before
        after = case.client.read(case.task_id)
        assert (after.leased, after.fence) == (lease_before.leased, lease_before.fence)
    finally:
        if not binding.closed:
            assert binding.return_lease() is True


def test_persistent_core_reconciliation_rejects_incomplete_native_inventory(
        core_reconciliation_fixture, monkeypatch):
    case = core_reconciliation_fixture()
    monkeypatch.setattr(case.client, "task_candidates", lambda **kwargs: {
        "tasks": [], "total": 1, "has_more": False, "offset": 0,
    })
    before = case.path.read_bytes()

    assert case.chat._persistent_core_reconciliation_proof(
        case.snapshot, case.contract,
    ) is None
    assert case.scans == []
    assert case.path.read_bytes() == before


def test_persistent_core_reconciliation_requires_two_stable_native_scans(
        core_reconciliation_fixture, monkeypatch):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    case = core_reconciliation_fixture()
    original = case.chat._persistent_worker_reconciliation_scan

    def change_after_first_scan(*args):
        result = original(*args)
        if len(case.scans) == 1:
            binding = WorkerLeaseBinding.acquire(
                case.client, case.task_id, worker_id="fixture-other@OTHER",
                host="OTHER", generation="6" * 32, is_current=lambda: True,
                stop_event=threading.Event(),
            )
            assert binding.return_lease() is True
        return result

    monkeypatch.setattr(
        case.chat, "_persistent_worker_reconciliation_scan", change_after_first_scan,
    )
    before = case.path.read_bytes()

    assert case.chat._persistent_core_reconciliation_proof(
        case.snapshot, case.contract,
    ) is None
    assert len(case.scans) == 2
    assert all(scan["complete"] is True for scan in case.scans)
    assert case.scans[0]["sha256"] != case.scans[1]["sha256"]
    assert case.path.read_bytes() == before


def _core_settlement_observation(case):
    """Observe configuration and fixture TaskDB bytes plus public task/lease data."""
    task = case.client.task_snapshot(case.task_id)
    lease = case.client.read(case.task_id)
    lease_fields = {
        key: getattr(lease, key)
        for key in ("task_id", "status", "leased", "fence", "holder", "task_version")
    }
    return {
        "configuration": case.path.read_bytes(),
        "task_database": case.database.read_bytes(),
        "task": json.dumps(task, sort_keys=True).encode(),
        "lease": json.dumps(lease_fields, sort_keys=True).encode(),
    }


@pytest.mark.parametrize("status", ["idle", "running", "error"])
def test_persistent_core_reconciliation_settles_only_matching_current_status(
        core_reconciliation_fixture, status):
    case = core_reconciliation_fixture(status)
    before = _core_settlement_observation(case)

    result = case.chat._persistent_core_settle_old_generation(
        case.snapshot, (None, None), case.contract,
    )

    assert result is not None
    assert result["status"] == "idle" and result["checkpoint"] is None
    assert result["recovery_state"]["phase"] == "ready"
    current = slots.persistent_core_startup_snapshot()
    assert current["state"] == "ready" and current["checkpoint"] is None
    assert current["intent_id"] == case.snapshot["intent_id"]
    assert current["profile_version"] == case.snapshot["profile_version"]
    assert current["slot"]["persistent_opt_in"] is True
    assert len(case.scans) == 2
    assert all(scan["complete"] is True for scan in case.scans)
    assert case.scans[0]["sha256"] == case.scans[1]["sha256"]
    after = _core_settlement_observation(case)
    assert after["configuration"] != before["configuration"]
    for key in ("task_database", "task", "lease"):
        assert after[key] == before[key]


@pytest.mark.parametrize("changed_status", ["error", "paused"])
@pytest.mark.parametrize("race_point", [
    "during_second_scan", "after_second_scan", "after_proof_before_cas",
])
def test_persistent_core_reconciliation_settlement_rejects_late_status_drift(
        core_reconciliation_fixture, monkeypatch, race_point, changed_status):
    case = core_reconciliation_fixture("running")
    changed = []

    def change_status():
        assert not changed
        slots.update_slot(
            "buddha_always_on", {"status": changed_status}, path=str(case.path),
        )
        assert slots.get_always_on_execution_slot(str(case.path))["status"] == changed_status
        changed.append(_core_settlement_observation(case))

    if race_point == "during_second_scan":
        original = case.client.task_candidates
        calls = 0

        def candidates(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                change_status()
            return original(**kwargs)

        monkeypatch.setattr(case.client, "task_candidates", candidates)
    elif race_point == "after_second_scan":
        original = case.chat._persistent_worker_reconciliation_scan

        def scan(*args):
            result = original(*args)
            if len(case.scans) == 2:
                change_status()
            return result

        monkeypatch.setattr(case.chat, "_persistent_worker_reconciliation_scan", scan)
    else:
        original = slots.update_persistent_core_controller_state

        def before_cas(*args, **kwargs):
            proof = kwargs["reconciliation_proof"]
            assert proof["status_before"] == "running"
            assert slots._valid_persistent_core_reconciliation_proof(
                proof, worker=slots.persistent_core_startup_snapshot()["slot"],
                checkpoint=case.checkpoint, recovery_state=case.recovery,
            )
            change_status()
            return original(*args, **kwargs)

        monkeypatch.setattr(slots, "update_persistent_core_controller_state", before_cas)

    result = case.chat._persistent_core_settle_old_generation(
        case.snapshot, (None, None), case.contract,
    )

    assert len(changed) == 1
    assert result is None
    assert len(case.scans) == 2
    assert all(scan["complete"] is True for scan in case.scans)
    assert case.scans[0]["sha256"] == case.scans[1]["sha256"]
    assert _core_settlement_observation(case) == changed[0]
    current = slots.persistent_core_startup_snapshot()
    assert current["status"] == changed_status
    assert current["checkpoint"] == case.checkpoint
    assert current["recovery_state"] == case.recovery
