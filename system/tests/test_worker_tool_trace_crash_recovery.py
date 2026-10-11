"""Lease recovery checks for abandoned canonical worker-tool traces."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hub._services.chat.worker_tool_trace import (
    digest_json,
    digest_text,
)
from hub._services.task_lease_client import LeaseProtocolError


@pytest.fixture
def task_database(tmp_path, monkeypatch):
    from hub._services import task_lease_client
    from hub._services.task_lease_client import TaskLeaseClient

    from system.tests.test_task_lease_service import _connect, _create_db, _insert

    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    database = tmp_path / "canonical-task-trace.db"
    _create_db(database)
    with _connect(database) as conn:
        task_id = _insert(conn, title="Synthetic trace recovery task", assigned_to="BACH")
    return database, task_id, TaskLeaseClient(db_path=database)


@pytest.fixture
def bound_task(task_database):
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    database, task_id, client = task_database
    binding = WorkerLeaseBinding.acquire(
        client,
        task_id,
        worker_id="trace-worker@HOST",
        host="HOST",
        generation="trace-generation-1",
        is_current=lambda: True,
        stop_event=threading.Event(),
    )
    yield database, task_id, client, binding
    if binding._active:
        binding.return_lease()


def _start(binding, request_id=None):
    return binding.trace_tool_started(
        source="cli-relay",
        request_id=request_id or uuid.uuid4().hex,
        tool_name="task_manage",
        arguments_sha256=digest_json({"action": "detail", "task_id": binding.task_id}),
    )


def _hard_crash_child(database: Path, task_id: int, phase: str) -> subprocess.CompletedProcess:
    system_root = Path(__file__).resolve().parents[1]
    script = r'''
import os, sys, threading, uuid
from pathlib import Path
sys.path.insert(0, sys.argv[4])
from hub._services import task_lease_client
from hub._services.chat.worker_lease_binding import WorkerLeaseBinding
from hub._services.chat.worker_tool_trace import digest_json, digest_text
from hub._services.task_lease_client import TaskLeaseClient
task_lease_client.get_lead_config = lambda: {"mode": "isolated"}
database, task_id, phase = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
client = TaskLeaseClient(db_path=database)
binding = WorkerLeaseBinding.acquire(
    client, task_id, worker_id="crash-worker@HOST", host="HOST",
    generation="crash-generation-1", is_current=lambda: True,
    stop_event=threading.Event())
identity = binding.trace_tool_started(
    source="cli-relay", request_id=uuid.uuid4().hex, tool_name="task_manage",
    arguments_sha256=digest_json({"synthetic": "child crash"}))
if phase == "returned":
    binding.trace_tool_phase(identity, "returned", receipt_id=uuid.uuid4().hex,
        result_sha256=digest_text("synthetic returned result"))
elif phase == "failed":
    binding.trace_tool_phase(identity, "failed")
os._exit(73)
'''
    env = os.environ.copy()
    env["BACH_TASK_LEASE_CREATOR_WINDOW"] = "0"
    old_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(system_root) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    return subprocess.run(
        [sys.executable, "-B", "-c", script, str(database), str(task_id), phase, str(system_root)],
        cwd=system_root.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _attempt_expired_takeover(database, task_id, client):
    from hub._services import task_lease

    from system.tests.test_task_lease_service import _connect

    snapshot = client.task_snapshot(task_id)
    future = datetime.now(timezone.utc) + timedelta(days=2)
    with _connect(database) as conn:
        return task_lease._acquire_lease(
            conn,
            task_id,
            worker_id="takeover-worker@HOST",
            host="HOST",
            request_id=uuid.uuid4().hex,
            task_version=snapshot["task_version"],
            result_generation=uuid.uuid4().hex,
            now=future,
        )


@pytest.mark.parametrize(
    ("phase", "expected_phases"),
    [
        ("started", ["started"]),
        ("returned", ["started", "returned"]),
        ("failed", ["started", "failed"]),
    ],
)
def test_hard_child_exit_leaves_trace_unresolved_and_denies_expired_takeover(
    task_database, phase, expected_phases
):
    database, task_id, client = task_database
    process = _hard_crash_child(database, task_id, phase)
    assert process.returncode == 73, process.stderr
    events = client.tool_trace_events(task_id)["events"]
    assert [event["phase"] for event in events] == expected_phases

    result = _attempt_expired_takeover(database, task_id, client)
    assert result.payload["granted"] is False
    assert result.payload["reason"] == "unresolved_tool_trace"
    assert [event["phase"] for event in client.tool_trace_events(task_id)["events"]] == expected_phases


def test_live_holder_cannot_start_a_second_request_before_trace_ack(bound_task):
    _database, _task_id, client, binding = bound_task
    _start(binding)

    with pytest.raises(LeaseProtocolError):
        _start(binding)

    assert [event["phase"] for event in client.tool_trace_events(binding.task_id)["events"]] == ["started"]


def test_fully_acknowledged_history_allows_a_new_generation(bound_task):
    _database, task_id, client, binding = bound_task
    identity = _start(binding)
    receipt_id = uuid.uuid4().hex
    assert binding.trace_tool_phase(
        identity,
        "returned",
        receipt_id=receipt_id,
        result_sha256=digest_text("synthetic result"),
    )["accepted"] is True
    assert binding.trace_tool_phase(identity, "acknowledged", receipt_id=receipt_id)["accepted"] is True
    old_fence = binding._ack.fence
    assert binding.return_lease() is True

    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    next_binding = WorkerLeaseBinding.acquire(
        client,
        task_id,
        worker_id="trace-worker@HOST",
        host="HOST",
        generation="trace-generation-2",
        is_current=lambda: True,
        stop_event=threading.Event(),
    )
    try:
        assert next_binding._ack.fence == old_fence + 1
    finally:
        if next_binding._active:
            next_binding.return_lease()


def test_ack_with_wrong_receipt_is_unreadable_and_does_not_unlock_takeover(bound_task):
    database, task_id, client, binding = bound_task
    identity = _start(binding)
    returned_receipt = uuid.uuid4().hex
    assert binding.trace_tool_phase(
        identity,
        "returned",
        receipt_id=returned_receipt,
        result_sha256=digest_text("synthetic result"),
    )["accepted"] is True

    from system.tests.test_task_lease_service import _connect

    forged_receipt = uuid.uuid4().hex
    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with _connect(database) as conn:
        conn.execute(
            """INSERT INTO worker_tool_trace_events (
                schema, task_id, fence, worker_id, generation, task_version, request_id,
                receipt_id, source, tool_name, phase, occurred_at, arguments_sha256,
                result_sha256, completion_sha256, effect_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "bach.worker-tool-trace.v1",
                identity.task_id,
                identity.fence,
                identity.worker_id,
                identity.generation,
                identity.task_version,
                identity.request_id,
                forged_receipt,
                identity.source,
                identity.tool_name,
                "acknowledged",
                occurred_at,
                None,
                None,
                None,
                "unknown",
            ),
        )

    result = _attempt_expired_takeover(database, task_id, client)
    assert result.payload["granted"] is False
    assert result.payload["reason"] == "tool_trace_unavailable"


def test_missing_trace_table_keeps_legacy_acquire_available(task_database):
    _database, task_id, client = task_database
    snapshot = client.task_snapshot(task_id)
    ack = client.acquire(
        task_id,
        worker_id="legacy-worker@HOST",
        host="HOST",
        task_version=snapshot["task_version"],
        result_generation=uuid.uuid4().hex,
    )
    assert ack.task_id == task_id
    assert ack.worker_id == "legacy-worker@HOST"
    assert type(ack.fence) is int and ack.fence > 0


def test_malformed_trace_schema_fails_closed_after_expiry(bound_task):
    database, task_id, client, binding = bound_task
    _start(binding)

    from system.tests.test_task_lease_service import _connect

    with _connect(database) as conn:
        conn.execute("DROP INDEX ux_worker_tool_trace_phase")

    result = _attempt_expired_takeover(database, task_id, client)
    assert result.payload["granted"] is False
    assert result.payload["reason"] == "tool_trace_unavailable"
