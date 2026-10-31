"""Durable model-request budgets: profile binding, CAS history, and safe recovery."""

from __future__ import annotations

import importlib
import json
import multiprocessing
import os
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

_SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_ROOT))

from hub._services.chat import slots_config as slots
from hub._services import task_lease, task_lease_client


WORKER_ID = "budget-once"
TASK_ID = 2217
TASK_VERSION = "a" * 64


def _add_worker(path: Path, *, task_id: int = TASK_ID, limit: int | None = 8,
                worker_id: str = WORKER_ID) -> dict:
    slots.initialize_slots_config(str(path))
    data = {
        "id": worker_id,
        "name": "Temporary budget test",
        "backend": "ollama",
        "model": "qwen3.5:4b",
        "mode": "safe",
        "max_tool_rounds": 8,
        "task_id": task_id,
        "type": "once",
        "allow_tools": False,
    }
    if limit is not None:
        data["max_model_requests"] = limit
    return slots.add_worker(data, path=str(path))


def _new_record(path: Path, *, task_id: int = TASK_ID, limit: int = 8,
                worker_id: str = WORKER_ID, start_request_id: str | None = None) -> dict:
    worker = slots.get_worker_slot(worker_id, path=str(path))
    return {
        "schema": "bach.worker-model-requests.v1",
        "worker_id": worker_id,
        "service_instance": uuid.uuid4().hex,
        "pid": os.getpid(),
        "process_create_time": max(time.time(), 1.0),
        "start_request_id": start_request_id or uuid.uuid4().hex,
        "generation": uuid.uuid4().hex,
        "task_id": task_id,
        "task_version": None,
        "configuration_version": slots._worker_profile_version(worker),
        "limit": limit,
        "reserved_count": 0,
        "phase": "admitted",
        "reason": "",
        "sequence": 0,
    }


def _admit(path: Path, *, task_id: int = TASK_ID, limit: int = 8,
           worker_id: str = WORKER_ID, start_request_id: str | None = None) -> dict:
    record = _new_record(path, task_id=task_id, limit=limit, worker_id=worker_id,
                         start_request_id=start_request_id)
    with slots.worker_admission_transaction(str(path)) as advance_revision:
        advance_revision(model_request_run=record)
    return slots.model_request_run_record(worker_id, record["start_request_id"], str(path))


def _admit_same_service_run(path: Path, task_id: int, client, telegram) -> dict:
    """Create a pre-fence budget-only run owned by this service process."""
    from hub.agent_process_provider import capture_process_create_time

    # This migration fixture represents a run admitted before universal
    # controller identities existed, rather than a never-admitted new profile.
    config = slots.load_slots_config(str(path), strict=True)
    slots._model_request_worker(config, WORKER_ID).pop("_controller_run", None)
    slots.save_slots_config(config, str(path))
    record = _new_record(path, task_id=task_id, limit=5)
    record["service_instance"] = telegram._WORKER_SERVICE_INSTANCE
    record["process_create_time"] = capture_process_create_time(os.getpid())
    assert isinstance(record["process_create_time"], (int, float))
    with slots.worker_admission_transaction(str(path)) as advance_revision:
        advance_revision(model_request_run=record)
    admitted = slots.model_request_run_record(
        WORKER_ID, record["start_request_id"], str(path)
    )
    active = _reserve(
        path, admitted, task_version=client.read(task_id).task_version
    )
    assert client.read(task_id).leased is False
    return active


def _reserve(path: Path, record: dict, *, task_version: str = TASK_VERSION,
             **changes) -> dict:
    args = {
        "service_instance": record["service_instance"],
        "start_request_id": record["start_request_id"],
        "generation": record["generation"],
        "task_id": record["task_id"],
        "task_version": task_version,
        "configuration_version": record["configuration_version"],
        "path": str(path),
    }
    args.update(changes)
    return slots.reserve_model_request(record["worker_id"], **args)


def _reserve_in_child(path: str, args: dict, barrier, output) -> None:
    """Spawn target: contend through the real file lock and atomic config write."""
    try:
        barrier.wait(timeout=15)
        result = slots.reserve_model_request(args["worker_id"], **args["kwargs"])
        output.put(("reserved", result["reserved_count"], ""))
    except slots.ModelRequestBudgetError as exc:
        output.put(("exhausted", None, type(exc).__name__))
    except BaseException as exc:  # make child failures observable to the parent
        output.put(("error", None, f"{type(exc).__name__}: {exc}"))


@pytest.fixture
def local_task_client(tmp_path, monkeypatch):
    """A real TaskLeaseClient over a private temporary SQLite task database."""
    database = tmp_path / "lease-test.sqlite3"
    conn = sqlite3.connect(str(database), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'M',
            category TEXT,
            assigned_to TEXT,
            created_by TEXT,
            depends_on TEXT,
            estimated_minutes INTEGER,
            actual_minutes INTEGER,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT,
            due_date TEXT,
            source TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            changed_by TEXT,
            changed_at TEXT NOT NULL
        )"""
    )
    task_lease.ensure_task_lease_schema(conn)
    cursor = conn.execute(
        "INSERT INTO tasks (title, status) VALUES (?, 'open')",
        ("isolated budget recovery",),
    )
    task_id = cursor.lastrowid
    conn.commit()

    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    client = task_lease_client.TaskLeaseClient(conn=conn)
    try:
        yield task_id, client, conn
    finally:
        conn.close()


def _configure_old_process_recovery(monkeypatch, path: Path, client, process_state: str):
    """Bind recovery to this temp config, a canonical temp lease reader, and an old PID."""
    telegram = importlib.import_module("hub._services.chat.telegram_chat")
    process_provider = importlib.import_module("hub.agent_process_provider")
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    monkeypatch.setattr(telegram, "_WORKER_SERVICE_INSTANCE", "f" * 32)
    monkeypatch.setattr(telegram, "_WORKER_EXECUTIONS", {})
    inspected = []
    monkeypatch.setattr(
        process_provider,
        "inspect_process_identity",
        lambda identity: (inspected.append(identity) or (process_state, None)),
    )
    lease_reads = []
    monkeypatch.setattr(
        telegram,
        "_native_task_client",
        lambda: (lease_reads.append(True) or client),
    )
    return telegram, inspected, lease_reads


@pytest.mark.parametrize("bad", [True, 0, 2, 257, 3.0, "8"])
def test_budget_limit_rejects_non_integer_and_out_of_range_values_without_writing(
    tmp_path, bad
):
    path = tmp_path / "slots.json"
    slots.initialize_slots_config(str(path))
    before = path.read_bytes()

    with pytest.raises(ValueError, match="max_model_requests"):
        slots.add_worker(
            {
                "id": "bad-budget",
                "name": "Bad budget",
                "task_id": TASK_ID,
                "type": "once",
                "max_model_requests": bad,
            },
            path=str(path),
        )

    assert path.read_bytes() == before
    assert slots.get_worker_slot("bad-budget", path=str(path)) == {}


def test_budget_limit_accepts_only_documented_boundaries(tmp_path):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=3, worker_id="budget-min")
    _add_worker(path, limit=256, worker_id="budget-max")

    assert slots.get_worker_slot("budget-min", path=str(path))["max_model_requests"] == 3
    assert slots.get_worker_slot("budget-max", path=str(path))["max_model_requests"] == 256


def test_unbudgeted_admission_preserves_legacy_save_callback_signature(
    tmp_path, monkeypatch
):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=None)
    before = slots.load_slots_config(str(path), strict=True).get("admission_revision")
    real_save = slots.save_slots_config
    calls = []

    def legacy_save(config, save_path=None):
        calls.append(save_path)
        return real_save(config, save_path)

    monkeypatch.setattr(slots, "save_slots_config", legacy_save)
    with slots.worker_admission_transaction(str(path)) as advance_revision:
        advance_revision()

    after = slots.load_slots_config(str(path), strict=True)
    assert calls == [str(path)]
    assert isinstance(after["admission_revision"], str) and after["admission_revision"]
    assert after["admission_revision"] != before
    assert "_model_request_runs" not in slots.get_worker_slot(WORKER_ID, path=str(path))


def test_request_limit_is_profile_data_and_generic_writes_cannot_change_it(tmp_path):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=None)
    before_worker = slots.get_worker_slot(WORKER_ID, path=str(path))
    before_profile = slots._worker_profile_version(before_worker)
    public = slots.worker_configuration_snapshot(WORKER_ID, path=str(path))

    changed = slots.change_worker_configuration(
        WORKER_ID,
        public["configuration_version"],
        {"max_model_requests": 9},
        path=str(path),
    )
    after_worker = slots.get_worker_slot(WORKER_ID, path=str(path))
    after_profile = slots._worker_profile_version(after_worker)

    assert changed["configuration"]["max_model_requests"] == 9
    assert after_worker["max_model_requests"] == 9
    assert before_profile != after_profile
    assert changed["configuration_version"] != public["configuration_version"]
    with pytest.raises(RuntimeError, match="configuration_version_conflict"):
        slots.change_worker_configuration(
            WORKER_ID,
            public["configuration_version"],
            {"max_model_requests": 10},
            path=str(path),
        )
    with pytest.raises(ValueError, match="Modellanfragenbudget"):
        slots.update_slot(WORKER_ID, {"max_model_requests": 10}, path=str(path))


def test_private_request_progress_survives_reload_without_changing_authority_versions(
    tmp_path, local_task_client
):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=4)
    record = _admit(path, task_id=task_id, limit=4)

    task_before = client.read(task_id)
    config_before = slots.load_slots_config(str(path), strict=True)
    core_before = slots._core_configuration_version(config_before)
    worker_before = slots.get_worker_slot(WORKER_ID, path=str(path))
    profile_before = slots._worker_profile_version(worker_before)
    public_before = slots.worker_configuration_snapshot(WORKER_ID, path=str(path))

    first = _reserve(path, record, task_version=task_before.task_version)
    reloaded = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    config_after = slots.load_slots_config(str(path), strict=True)
    task_after = client.read(task_id)

    assert first["reserved_count"] == 1
    assert reloaded == first
    assert slots._core_configuration_version(config_after) == core_before
    assert slots._worker_profile_version(
        slots.get_worker_slot(WORKER_ID, path=str(path))
    ) == profile_before
    assert slots.worker_configuration_snapshot(
        WORKER_ID, path=str(path)
    )["configuration_version"] == public_before["configuration_version"]
    assert (task_after.task_version, task_after.fence, task_after.leased) == (
        task_before.task_version, task_before.fence, task_before.leased
    )


def test_failed_reservation_write_before_replace_does_not_consume_a_request(
    tmp_path, monkeypatch
):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=4)
    record = _admit(path, limit=4)
    before = path.read_bytes()
    real_save = slots.save_slots_config
    calls = []

    def fail_before_write(config, write_path=None, *, durable=False):
        calls.append((write_path, durable))
        raise OSError("simulated failure before atomic replace")

    monkeypatch.setattr(slots, "save_slots_config", fail_before_write)
    with pytest.raises(OSError, match="before atomic replace"):
        _reserve(path, record)
    monkeypatch.setattr(slots, "save_slots_config", real_save)

    current = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert calls == [(str(path), True)]
    assert path.read_bytes() == before
    assert current["phase"] == "admitted"
    assert current["reserved_count"] == 0
    assert current["sequence"] == 0


def test_lost_confirmation_after_durable_replace_never_refunds_the_reservation(
    tmp_path, monkeypatch
):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=4)
    record = _admit(path, limit=4)
    real_save = slots.save_slots_config

    def replace_then_lose_confirmation(config, write_path=None, *, durable=False):
        real_save(config, write_path, durable=durable)
        raise OSError("simulated lost durability confirmation")

    monkeypatch.setattr(slots, "save_slots_config", replace_then_lose_confirmation)
    with pytest.raises(OSError, match="lost durability confirmation"):
        _reserve(path, record)
    monkeypatch.setattr(slots, "save_slots_config", real_save)

    current = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert current["phase"] == "active"
    assert current["reserved_count"] == 1
    assert current["sequence"] == 1
    second = _reserve(path, current)
    assert second["reserved_count"] == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_instance", "0" * 32),
        ("start_request_id", "1" * 32),
        ("generation", "2" * 32),
        ("task_id", TASK_ID + 1),
        ("configuration_version", "b" * 64),
        ("task_version", "c" * 64),
    ],
)
def test_reservation_cas_rejects_foreign_or_changed_run_bindings(
    tmp_path, field, value
):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=5)
    record = _admit(path, limit=5)
    first = _reserve(path, record)
    before = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))

    args = {
        "service_instance": record["service_instance"],
        "start_request_id": record["start_request_id"],
        "generation": record["generation"],
        "task_id": record["task_id"],
        "task_version": TASK_VERSION,
        "configuration_version": record["configuration_version"],
        "path": str(path),
    }
    args[field] = value
    with pytest.raises(slots.ModelRequestBudgetError):
        slots.reserve_model_request(WORKER_ID, **args)

    after = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert first["reserved_count"] == 1
    assert after == before


def test_confirmed_task_updates_keep_one_run_and_request_counter(
    tmp_path, monkeypatch, local_task_client,
):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    task_id, client, _conn = local_task_client
    path = tmp_path / "slots.json"
    _add_worker(path, task_id=task_id, limit=5)
    record = _admit(path, task_id=task_id, limit=5)
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    binding = WorkerLeaseBinding.acquire(
        client, task_id, worker_id=f"{WORKER_ID}@HOST", host="HOST",
        generation=record["generation"], is_current=lambda: True,
        stop_event=threading.Event(),
    )
    telegram = importlib.import_module("hub._services.chat.telegram_chat")
    budget = telegram._ModelRequestBudget(
        worker_id=WORKER_ID, service_instance=record["service_instance"],
        start_request_id=record["start_request_id"], generation=record["generation"],
        task_id=task_id, configuration_version=record["configuration_version"],
    )

    first = budget.reserve(binding)
    original_version = first["task_version"]
    binding.execute_task_manage({"action": "update", "task_id": task_id,
                                 "description": "Erster bestätigter Stand"})
    binding.execute_task_manage({"action": "update", "task_id": task_id,
                                 "description": "Zweiter bestätigter Stand"})
    current_version = binding.task_snapshot()["task_version"]
    assert current_version != original_version
    second = budget.reserve(binding)
    assert second["start_request_id"] == first["start_request_id"]
    assert second["task_version"] == current_version
    assert second["reserved_count"] == first["reserved_count"] + 1 == 2
    assert second["limit"] == first["limit"] == 5
    binding.invalidate()
    with pytest.raises(slots.ModelRequestBudgetError):
        budget.reserve(binding)
    assert slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path)) == second


@pytest.mark.parametrize("transitions", [
    (),
    ((TASK_VERSION, "b" * 64),),
    ((TASK_VERSION, "b" * 64), ("d" * 64, "c" * 64)),
    (("d" * 64, "c" * 64),),
])
def test_unconfirmed_or_broken_version_path_cannot_spend_request(tmp_path, transitions):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=5)
    record = _admit(path, limit=5)
    first = _reserve(path, record)
    with pytest.raises(slots.ModelRequestBudgetError):
        _reserve(path, first, task_version="c" * 64,
                 confirmed_version_transitions=transitions)
    assert slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path)) == first


def test_separate_processes_can_reserve_only_the_last_slot_once(tmp_path):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=3)
    record = _admit(path, limit=3)
    _reserve(path, record)
    record = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    _reserve(path, record)
    args = {
        "worker_id": WORKER_ID,
        "kwargs": {
            "service_instance": record["service_instance"],
            "start_request_id": record["start_request_id"],
            "generation": record["generation"],
            "task_id": record["task_id"],
            "task_version": TASK_VERSION,
            "configuration_version": record["configuration_version"],
            "path": str(path),
        },
    }

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    output = context.Queue()
    children = [
        context.Process(target=_reserve_in_child, args=(str(path), args, barrier, output))
        for _ in range(2)
    ]
    for child in children:
        child.start()
    barrier.wait(timeout=15)
    messages = [output.get(timeout=25) for _ in children]
    for child in children:
        child.join(timeout=25)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        assert child.exitcode == 0

    current = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert sorted(message[0] for message in messages) == ["exhausted", "reserved"]
    assert not [message for message in messages if message[0] == "error"]
    assert current["reserved_count"] == 3
    assert current["sequence"] == 3


def test_controller_reconciliation_does_not_clear_an_unconfirmed_budget_run(tmp_path):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=4)
    record = _admit(path, limit=4)
    current = _reserve(path, record)
    slots.update_slot(WORKER_ID, {"status": "running"}, path=str(path))

    reconciled = slots.reconcile_workers(active_worker_ids=set(), path=str(path))
    worker = slots.get_worker_slot(WORKER_ID, path=str(path))
    stored = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))

    assert reconciled[0]["id"] == WORKER_ID
    assert worker["status"] == "error"
    assert "unbestätigt" in worker["current_activity"].lower()
    assert stored["phase"] == "active"
    assert stored["reserved_count"] == current["reserved_count"] == 1
    next_record = _new_record(path, limit=4)
    before = path.read_bytes()
    with slots.worker_admission_transaction(str(path)) as advance_revision:
        with pytest.raises(RuntimeError, match="budget_previous_run_unconfirmed"):
            advance_revision(model_request_run=next_record)
    assert path.read_bytes() == before


def test_terminal_cas_enforces_reason_count_sequence_and_keeps_old_run_readable(tmp_path):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=5)
    record = _admit(path, limit=5)

    with pytest.raises(RuntimeError, match="budget_terminal_conflict"):
        slots.terminalize_model_request_run(
            WORKER_ID,
            service_instance=record["service_instance"],
            start_request_id=record["start_request_id"],
            generation=record["generation"],
            expected_sequence=0,
            reason="interrupted_unknown",
            path=str(path),
        )
    active = _reserve(path, record)
    with pytest.raises(RuntimeError, match="budget_terminal_conflict"):
        slots.terminalize_model_request_run(
            WORKER_ID,
            service_instance=record["service_instance"],
            start_request_id=record["start_request_id"],
            generation=record["generation"],
            expected_sequence=0,
            reason="controller_cleanup_confirmed",
            path=str(path),
        )
    terminal = slots.terminalize_model_request_run(
        WORKER_ID,
        service_instance=record["service_instance"],
        start_request_id=record["start_request_id"],
        generation=record["generation"],
        expected_sequence=active["sequence"],
        reason="interrupted_unknown",
        path=str(path),
    )
    assert terminal["phase"] == "terminal"
    assert terminal["reserved_count"] == 1
    assert terminal["reason"] == "interrupted_unknown"
    assert slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path)) == terminal
    with pytest.raises(RuntimeError, match="budget_terminal_conflict"):
        slots.terminalize_model_request_run(
            WORKER_ID,
            service_instance=record["service_instance"],
            start_request_id=record["start_request_id"],
            generation=record["generation"],
            expected_sequence=terminal["sequence"],
            reason="interrupted_unknown",
            path=str(path),
        )


def test_new_run_archives_prior_terminal_and_cannot_replay_its_start_id(tmp_path):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=5)
    old = _admit(path, limit=5)
    active = _reserve(path, old)
    old_terminal = slots.terminalize_model_request_run(
        WORKER_ID,
        service_instance=old["service_instance"],
        start_request_id=old["start_request_id"],
        generation=old["generation"],
        expected_sequence=active["sequence"],
        reason="interrupted_unknown",
        path=str(path),
    )

    new = _new_record(path, limit=5)
    with slots.worker_admission_transaction(str(path)) as advance_revision:
        advance_revision(model_request_run=new)
    current = slots.model_request_run_record(WORKER_ID, path=str(path))
    archived = slots.model_request_run_record(WORKER_ID, old["start_request_id"], str(path))

    assert current["start_request_id"] == new["start_request_id"]
    assert current["reserved_count"] == 0
    assert current["phase"] == "admitted"
    assert archived == old_terminal

    empty_terminal = slots.terminalize_model_request_run(
        WORKER_ID,
        service_instance=new["service_instance"],
        start_request_id=new["start_request_id"],
        generation=new["generation"],
        expected_sequence=0,
        reason="interrupted_no_dispatch",
        path=str(path),
    )
    duplicate = _new_record(path, limit=5, start_request_id=old["start_request_id"])
    before = path.read_bytes()
    with slots.worker_admission_transaction(str(path)) as advance_revision:
        with pytest.raises(RuntimeError, match="budget_start_request_reused"):
            advance_revision(model_request_run=duplicate)
    assert path.read_bytes() == before
    assert slots.model_request_run_record(WORKER_ID, old["start_request_id"], str(path)) == old_terminal
    assert slots.model_request_run_record(
        WORKER_ID, empty_terminal["start_request_id"], str(path)
    ) == empty_terminal


def test_budgeted_worker_and_private_run_state_cannot_be_deleted_or_generic_written(tmp_path):
    path = tmp_path / "slots.json"
    _add_worker(path, limit=4)
    record = _admit(path, limit=4)

    with pytest.raises(ValueError, match="Modellanfragenbudget"):
        slots.update_slot(
            WORKER_ID,
            {"_model_request_runs": {"schema": "forged", "current": None, "terminal": []}},
            path=str(path),
        )
    public = slots.worker_configuration_snapshot(WORKER_ID, path=str(path))
    with pytest.raises(ValueError, match="Unbekannte Worker-Konfigurationsfelder"):
        slots.change_worker_configuration(
            WORKER_ID,
            public["configuration_version"],
            {"_model_request_runs": {"schema": "forged", "current": None, "terminal": []}},
            path=str(path),
        )
    with pytest.raises(RuntimeError, match="Budgetierte Run-Belege"):
        slots.remove_worker(WORKER_ID, path=str(path))

    persisted = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert persisted == record


@pytest.mark.parametrize("process_state", ["gone", "mismatch"])
def test_recovery_terminalizes_only_dead_process_with_canonical_unleased_task(
    tmp_path, monkeypatch, local_task_client, process_state
):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=5)
    initial_view = client.read(task_id)
    record = _admit(path, task_id=task_id, limit=5)
    active = _reserve(path, record, task_version=initial_view.task_version)
    assert client.read(task_id).leased is False
    telegram, inspected, lease_reads = _configure_old_process_recovery(
        monkeypatch, path, client, process_state
    )

    assert telegram._recover_model_request_run(WORKER_ID) is True
    terminal = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    final_view = client.read(task_id)

    assert inspected == [{
        "pid": active["pid"],
        "process_create_time": active["process_create_time"],
    }]
    assert lease_reads == [True]
    assert terminal["phase"] == "terminal"
    assert terminal["reason"] == "interrupted_unknown"
    assert terminal["reserved_count"] == active["reserved_count"] == 1
    assert (final_view.leased, final_view.fence, final_view.task_version) == (
        False, initial_view.fence, initial_view.task_version
    )


@pytest.mark.parametrize("process_state", ["alive", "unknown"])
def test_recovery_keeps_live_or_unknown_old_process_unresolved(
    tmp_path, monkeypatch, local_task_client, process_state
):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=5)
    record = _admit(path, task_id=task_id, limit=5)
    _reserve(path, record, task_version=client.read(task_id).task_version)
    telegram, inspected, lease_reads = _configure_old_process_recovery(
        monkeypatch, path, client, process_state
    )

    assert telegram._recover_model_request_run(WORKER_ID) is False
    current = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert inspected == [{
        "pid": record["pid"],
        "process_create_time": record["process_create_time"],
    }]
    assert lease_reads == []
    assert current["phase"] == "active"
    assert current["reserved_count"] == 1


def test_recovery_does_not_close_an_old_run_while_task_is_actively_leased(
    tmp_path, monkeypatch, local_task_client
):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=5)
    lease = client.acquire(task_id, worker_id="tester@ASUS-GEI", host="ASUS-GEI")
    record = _admit(path, task_id=task_id, limit=5)
    _reserve(path, record, task_version=client.read(task_id).task_version)
    telegram, inspected, lease_reads = _configure_old_process_recovery(
        monkeypatch, path, client, "gone"
    )

    assert lease.lease_id
    assert telegram._recover_model_request_run(WORKER_ID) is False
    current = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    view = client.read(task_id)

    assert inspected[0]["pid"] == record["pid"]
    assert lease_reads == [True]
    assert view.leased is True
    assert current["phase"] == "active"
    assert current["reserved_count"] == 1


def test_same_service_recovery_requires_finished_retained_control(tmp_path, monkeypatch, local_task_client):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=5)
    record = _admit(path, task_id=task_id, limit=5)
    _reserve(path, record, task_version=client.read(task_id).task_version)
    telegram = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    monkeypatch.setattr(telegram, "_WORKER_SERVICE_INSTANCE", record["service_instance"])
    monkeypatch.setattr(telegram, "_WORKER_EXECUTIONS", {})
    lease_reads = []
    monkeypatch.setattr(telegram, "_native_task_client", lambda: (lease_reads.append(True) or client))

    assert telegram._recover_model_request_run(WORKER_ID) is False
    current = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert current["phase"] == "active"
    assert current["reserved_count"] == 1
    assert lease_reads == []


def test_public_receipt_recovers_finished_same_service_run_before_new_start(
    tmp_path, monkeypatch, local_task_client
):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=5)
    telegram = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    active = _admit_same_service_run(path, task_id, client, telegram)

    old_thread = threading.Thread(target=lambda: None)
    old_thread.start()
    old_thread.join(timeout=1)
    assert not old_thread.is_alive()
    old_control = telegram._WorkerControl(
        worker_id=WORKER_ID,
        generation=active["generation"],
        start_request_id=active["start_request_id"],
        thread=old_thread,
        worker_thread_started=True,
        model_request_budget=telegram._ModelRequestBudget(
            WORKER_ID, active["service_instance"], active["start_request_id"],
            active["generation"], task_id, active["configuration_version"],
        ),
    )
    old_control.done_event.set()
    assert active["phase"] == "active" and active["reserved_count"] == 1
    assert old_control.done_event.is_set() and not old_thread.is_alive()
    monkeypatch.setattr(telegram, "_WORKER_EXECUTIONS", {WORKER_ID: old_control})
    monkeypatch.setattr(telegram, "_WORKER_CONTROLS", {})
    monkeypatch.setattr(telegram, "_ACTIVE_WORKER_THREADS", {})
    lease_reads = []
    monkeypatch.setattr(
        telegram, "_native_task_client", lambda: (lease_reads.append(True) or client)
    )

    # A prior terminal write was lost: durable state is still active even
    # though this exact service control and its worker thread have finished.
    observed = telegram.worker_execution_receipt(
        WORKER_ID, active["start_request_id"], verify_results=False
    )
    old_terminal = slots.model_request_run_record(
        WORKER_ID, active["start_request_id"], str(path)
    )
    assert observed["terminal"] is True
    assert observed["state"] == "terminal"
    assert observed["start_request_id"] == active["start_request_id"]
    assert observed["model_requests"] == {
        "run_id": active["start_request_id"],
        "used": 1,
        "limit": 5,
        "remaining": 4,
        "phase": "terminal",
    }
    assert old_terminal["phase"] == "terminal"
    assert old_terminal["reason"] == "interrupted_unknown"
    assert old_terminal["reserved_count"] == active["reserved_count"] == 1
    assert lease_reads == [True]
    assert client.read(task_id).leased is False

    # Exercise the public admission path, but replace only the final launch
    # seam with a sleeping local thread; no provider or model is invoked.
    new_request_id = "b" * 32
    launch_release = threading.Event()
    launch_started = threading.Event()
    launch_threads = []
    launch_calls = []

    def isolated_launch(control, slot, custom_prompt):
        assert slot["id"] == WORKER_ID
        launch_calls.append((control.start_request_id, custom_prompt))

        def wait_without_backend():
            launch_started.set()
            launch_release.wait()

        thread = threading.Thread(target=wait_without_backend, daemon=True)
        thread.start()
        control.thread = thread
        control.launch_attempted = True
        control.worker_thread_started = True
        telegram._WORKER_CONTROLS[WORKER_ID] = control
        telegram._ACTIVE_WORKER_THREADS[WORKER_ID] = thread
        launch_threads.append((thread, control))
        return {"ok": True, "status": "isolated-launch-seam"}, 200

    monkeypatch.setattr(telegram, "_start_reserved_worker_execution", isolated_launch)
    config_version = slots.core_system_agents_snapshot(str(path))["configuration_version"]
    try:
        response, status = telegram.start_worker_execution(
            WORKER_ID,
            start_request_id=new_request_id,
            expected_service_instance=telegram._WORKER_SERVICE_INSTANCE,
            expected_configuration_version=config_version,
        )
        assert status == 200 and response["ok"] is True
        assert launch_started.wait(timeout=1)
        assert launch_calls == [(new_request_id, None)]

        new_receipt = response["execution"]
        assert new_receipt["start_request_id"] == new_request_id
        assert new_receipt["state"] == "running"
        assert new_receipt["terminal"] is False
        assert new_receipt["model_requests"] == {
            "run_id": new_request_id,
            "used": 0,
            "limit": 5,
            "remaining": 5,
            "phase": "admitted",
        }
        assert slots.model_request_run_record(
            WORKER_ID, active["start_request_id"], str(path)
        ) == old_terminal
        current = slots.model_request_run_record(WORKER_ID, new_request_id, str(path))
        assert current["phase"] == "admitted" and current["reserved_count"] == 0

        old_readback = telegram.worker_execution_receipt(
            WORKER_ID, active["start_request_id"], verify_results=False
        )
        assert old_readback["terminal"] is True
        assert old_readback["start_request_id"] == active["start_request_id"]
        assert old_readback["model_requests"]["used"] == 1
    finally:
        launch_release.set()
        for thread, control in launch_threads:
            thread.join(timeout=1)
            control.done_event.set()


@pytest.mark.parametrize(
    ("thread_is_live", "expected_state"),
    [(True, "running"), (False, "unconfirmed")],
)
def test_public_start_keeps_live_or_unknown_same_service_run_blocked(
    tmp_path, monkeypatch, local_task_client, thread_is_live, expected_state
):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=5)
    telegram = importlib.import_module("hub._services.chat.telegram_chat")
    monkeypatch.setattr(slots, "DEFAULT_SLOTS_FILE", str(path))
    active = _admit_same_service_run(path, task_id, client, telegram)

    release = threading.Event()
    if thread_is_live:
        thread = threading.Thread(target=release.wait, daemon=True)
        thread.start()
    else:
        thread = threading.Thread(target=lambda: None)
        thread.start()
        thread.join(timeout=1)
        assert not thread.is_alive()
    control = telegram._WorkerControl(
        worker_id=WORKER_ID,
        generation=active["generation"],
        start_request_id=active["start_request_id"],
        thread=thread,
        worker_thread_started=True,
        model_request_budget=telegram._ModelRequestBudget(
            WORKER_ID, active["service_instance"], active["start_request_id"],
            active["generation"], task_id, active["configuration_version"],
        ),
    )
    monkeypatch.setattr(telegram, "_WORKER_EXECUTIONS", {WORKER_ID: control})
    monkeypatch.setattr(telegram, "_WORKER_CONTROLS", {WORKER_ID: control})
    monkeypatch.setattr(telegram, "_ACTIVE_WORKER_THREADS", {WORKER_ID: thread})
    lease_reads = []
    monkeypatch.setattr(
        telegram, "_native_task_client", lambda: (lease_reads.append(True) or client)
    )
    monkeypatch.setattr(
        telegram, "_start_reserved_worker_execution",
        lambda *args, **kwargs: pytest.fail("Unbestätigte Altgeneration darf nicht starten"),
    )

    try:
        observed = telegram.worker_execution_receipt(
            WORKER_ID, active["start_request_id"], verify_results=False
        )
        assert observed["terminal"] is False
        assert observed["state"] == expected_state
        assert observed["model_requests"]["phase"] == "active"
        assert observed["model_requests"]["used"] == 1

        response, status = telegram.start_worker_execution(
            WORKER_ID,
            start_request_id="c" * 32,
            expected_service_instance=telegram._WORKER_SERVICE_INSTANCE,
            expected_configuration_version=(
                slots.core_system_agents_snapshot(str(path))["configuration_version"]
            ),
        )
        assert status == 409
        assert response["admission"]["admitted"] is False
        assert response["execution"]["terminal"] is False
        current = slots.model_request_run_record(
            WORKER_ID, active["start_request_id"], str(path)
        )
        assert current["phase"] == "active" and current["reserved_count"] == 1
        assert lease_reads == []
    finally:
        release.set()
        thread.join(timeout=1)


def test_zero_dispatch_recovery_uses_only_no_dispatch_terminal_reason(
    tmp_path, monkeypatch, local_task_client
):
    path = tmp_path / "slots.json"
    task_id, client, _ = local_task_client
    _add_worker(path, task_id=task_id, limit=5)
    initial_view = client.read(task_id)
    record = _admit(path, task_id=task_id, limit=5)
    telegram, inspected, lease_reads = _configure_old_process_recovery(
        monkeypatch, path, client, "gone"
    )

    assert telegram._recover_model_request_run(WORKER_ID) is True
    terminal = slots.model_request_run_record(WORKER_ID, record["start_request_id"], str(path))
    assert terminal["phase"] == "terminal"
    assert terminal["reason"] == "interrupted_no_dispatch"
    assert terminal["reserved_count"] == 0
    assert client.read(task_id).task_version == initial_view.task_version
    assert inspected[0]["pid"] == record["pid"]
    assert lease_reads == [True]


@pytest.mark.parametrize("phase", [
    "admitted", "active", "unknown", "terminal", "invalid", [], {}, None, 1, True,
])
def test_model_request_phase_projection_keeps_worker_status_for_malformed_payloads(phase):
    from gui.api import worker_status_adapter

    budget = {"run_id": "a" * 32, "used": 1, "limit": 8, "remaining": 7, "phase": phase}
    projected = worker_status_adapter._project_worker({
        "id": "budget-status-fixture", "status": "running", "model_requests": budget,
    })

    assert projected["id"] == "budget-status-fixture"
    assert projected["status"] == "running"
    if type(phase) is str and phase in {"admitted", "active", "unknown", "terminal"}:
        assert projected["model_requests"] == budget
    else:
        assert "model_requests" not in projected
