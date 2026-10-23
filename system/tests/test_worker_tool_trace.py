"""Persistent canonical task tool trace tests; isolated DB, no provider process."""
import hashlib
import json
import sqlite3
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from contextlib import closing

from hub._services.chat.worker_tool_trace import (
    SCHEMA, TraceIdentity, WorkerToolTraceError, digest_json, digest_text, append_phase,
    append_started,
)
from hub._services.chat.worker_tool_bridge import WorkerToolBridge


@pytest.fixture
def binding(tmp_path, monkeypatch):
    from system.tests.test_task_lease_service import _create_db, _connect, _insert
    from hub._services import task_lease_client
    from hub._services.chat.worker_lease_binding import WorkerLeaseBinding

    database = tmp_path / "canonical.db"
    _create_db(database)
    conn = _connect(database)
    conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    task_id = _insert(conn, title="Trace task", assigned_to="BACH")
    conn.close()
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    monkeypatch.setattr(task_lease_client, "get_lead_config", lambda: {"mode": "isolated"})
    client = task_lease_client.TaskLeaseClient(db_path=database)
    result = WorkerLeaseBinding.acquire(
        client, task_id, worker_id="trace-worker@HOST", host="HOST",
        generation="trace-generation-1", is_current=lambda: True,
        stop_event=threading.Event(),
        slot={"id": "worker-bound", "model": "isolated-model"},
    )
    yield result
    if result._active:
        result.return_lease()


def _relay(binding):
    return WorkerToolBridge(binding, mode="safe")


def _http(bridge, path, payload):
    settings = bridge.private_environment()
    request = urllib.request.Request(
        settings["BACH_WORKER_TOOL_URL"] + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + settings["BACH_WORKER_TOOL_TOKEN"],
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def _call(bridge, args, *, request_id=None):
    return _http(bridge, "/call", {
        "request_id": request_id or uuid.uuid4().hex,
        "previous_receipt": None,
        "name": "task_manage",
        "arguments": args,
    })


def _ack(bridge, result):
    return _http(bridge, "/ack", {
        "request_id": result["request_id"], "receipt_id": result["receipt_id"],
    })


def _events(binding):
    client = binding._client
    return client.tool_trace_events(binding.task_id)["events"]


def test_cli_relay_persists_hash_only_phases_and_blocks_restart_replay(binding):
    arguments = {"action": "detail", "task_id": binding.task_id}
    request_id = uuid.uuid4().hex
    with _relay(binding) as relay:
        result = _call(relay, arguments, request_id=request_id)
        assert _ack(relay, result)["acknowledged"] is True
    events = _events(binding)
    assert [event["phase"] for event in events] == ["started", "returned", "acknowledged"]
    assert all(event["schema"] == SCHEMA and event["effect_status"] == "unknown" for event in events)
    assert events[0]["arguments_sha256"] == digest_json(arguments)
    assert events[1]["result_sha256"] == digest_text(result["result"])
    assert events[1]["receipt_id"] == events[2]["receipt_id"] == result["receipt_id"]
    assert all("lease_id" not in event and "arguments" not in event and "result" not in event
               for event in events)
    assert binding._ack.lease_id not in json.dumps(events)
    assert "Trace task" not in json.dumps(events)

    # A fresh relay instance has no in-memory seen-set; the canonical event must stop replay.
    with _relay(binding) as restarted:
        with pytest.raises(urllib.error.HTTPError) as error:
            _call(restarted, arguments, request_id=request_id)
        assert error.value.code in {403, 503}
    assert [event["phase"] for event in _events(binding)] == ["started", "returned", "acknowledged"]
    assert binding.tool_dispatch_count == 1


def test_start_sink_failure_prevents_provider_call(binding, monkeypatch):
    with _relay(binding) as relay:
        calls = []
        monkeypatch.setattr(relay._provider, "execute", lambda *args: calls.append(args))
        monkeypatch.setattr(binding, "trace_tool_started",
                            lambda **kwargs: (_ for _ in ()).throw(WorkerToolTraceError("sink")))
        with pytest.raises(urllib.error.HTTPError) as error:
            _call(relay, {"action": "detail", "task_id": binding.task_id})
        assert error.value.code == 503
        assert calls == []


def test_provider_failure_records_only_a_failed_phase(binding, monkeypatch):
    secret = "synthetic-credential-must-not-be-stored"
    with _relay(binding) as relay:
        def fail(*args):
            raise RuntimeError(secret)
        monkeypatch.setattr(relay._provider, "execute", fail)
        with pytest.raises(urllib.error.HTTPError) as error:
            _call(relay, {"action": "detail", "task_id": binding.task_id})
        assert error.value.code == 503
    events = _events(binding)
    assert [event["phase"] for event in events] == ["started", "failed"]
    assert secret not in json.dumps(events)
    assert all(event["effect_status"] == "unknown" for event in events)


def test_return_sink_failure_does_not_replay_tool(binding, monkeypatch):
    with _relay(binding) as relay:
        executed = []
        original = relay._provider.execute
        def counted(*args):
            executed.append(args)
            return original(*args)
        monkeypatch.setattr(relay._provider, "execute", counted)
        original_phase = binding.trace_tool_phase
        def fail_return(identity, phase, **kwargs):
            if phase == "returned":
                raise WorkerToolTraceError("synthetic sink outage")
            return original_phase(identity, phase, **kwargs)
        monkeypatch.setattr(binding, "trace_tool_phase", fail_return)
        request_id = uuid.uuid4().hex
        with pytest.raises(urllib.error.HTTPError) as error:
            _call(relay, {"action": "detail", "task_id": binding.task_id}, request_id=request_id)
        assert error.value.code == 503
        with pytest.raises(urllib.error.HTTPError):
            _call(relay, {"action": "detail", "task_id": binding.task_id}, request_id=request_id)
        assert len(executed) == 1
    assert [event["phase"] for event in _events(binding)] == ["started"]


def test_started_call_can_be_completed_after_lease_return(binding):
    request_id = uuid.uuid4().hex
    identity = binding.trace_tool_started(
        source="cli-relay", request_id=request_id, tool_name="task_manage",
        arguments_sha256=digest_json({"action": "detail", "task_id": binding.task_id}),
    )
    assert binding.return_lease() is True
    ack = binding.trace_tool_phase(
        identity, "returned", receipt_id=uuid.uuid4().hex,
        result_sha256=hashlib.sha256(b"returned after return").hexdigest(),
    )
    assert ack["accepted"] is True
    assert [event["phase"] for event in _events(binding)] == ["started", "returned"]


def test_trace_event_table_is_append_only(binding):
    request_id = uuid.uuid4().hex
    identity = binding.trace_tool_started(
        source="cli-relay", request_id=request_id, tool_name="task_manage",
        arguments_sha256=digest_json({"task_id": binding.task_id}),
    )
    conn = binding._client._get_local_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE worker_tool_trace_events SET tool_name='other'")
        conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM worker_tool_trace_events")
        conn.rollback()
    finally:
        conn.close()


def test_trace_identity_rejects_wrong_fence_and_uncorrelated_terminal(binding):
    request_id = uuid.uuid4().hex
    identity = binding.trace_tool_started(
        source="cli-relay", request_id=request_id, tool_name="task_manage",
        arguments_sha256=digest_json({"task_id": binding.task_id}),
    )
    wrong = TraceIdentity(
        task_id=identity.task_id, fence=identity.fence + 1, worker_id=identity.worker_id,
        generation=identity.generation, task_version=identity.task_version,
        request_id=identity.request_id, source=identity.source, tool_name=identity.tool_name,
    )
    with pytest.raises(Exception):
        binding._client.tool_trace_phase(wrong, "failed")
    with closing(binding._client._get_local_connection()) as conn:
        with pytest.raises(Exception):
            append_phase(conn, identity, "acknowledged", receipt_id=uuid.uuid4().hex,
                         completion_token=binding._trace_completion_tokens[identity])
    assert [event["phase"] for event in _events(binding)] == ["started"]


def test_remote_trace_uses_lead_transport_without_local_fallback(binding, monkeypatch):
    from hub._services.task_lease_client import TaskLeaseClient
    client = TaskLeaseClient(lead_url="https://lead.example", device_token="synthetic-device-token")
    calls = []
    completion_token = "A" * 43
    def transport(method, path, payload=None, headers=None):
        calls.append((method, path, payload, headers))
        phase = payload.get("phase", "started") if payload else "started"
        data = {"schema": SCHEMA, "accepted": True, "event_id": len(calls),
                "task_id": binding.task_id, "request_id": "a" * 32, "phase": phase}
        if phase == "started":
            data["completion_token"] = completion_token
        return 200, data
    monkeypatch.setattr(client, "_http_request", transport)
    identity = TraceIdentity(
        task_id=binding.task_id, fence=1, worker_id="trace-worker@HOST",
        generation="trace-generation-1", task_version="a" * 64, request_id="a" * 32,
        source="cli-relay", tool_name="task_manage",
    )
    lease_id = "11111111-1111-4111-8111-111111111111"
    ack = client.tool_trace_start(identity, lease_id=lease_id,
                                  arguments_sha256="b" * 64)
    assert ack.accepted is True and ack.completion_token == completion_token
    assert completion_token not in repr(ack)
    method, path, payload, headers = calls[0]
    assert method == "POST" and path.endswith("/tool-trace/start")
    assert payload["schema"] == SCHEMA and "lease_id" not in payload
    assert headers == {"X-Lease-Id": lease_id}
    client.tool_trace_phase(identity, "failed", completion_token=completion_token)
    _, phase_path, phase_payload, phase_headers = calls[1]
    assert phase_path.endswith("/tool-trace/events")
    assert completion_token not in json.dumps(phase_payload)
    assert phase_headers == {"X-Trace-Completion": completion_token}
    assert client.mode == "remote"


def test_submit_result_return_still_allows_only_terminal_trace_and_ack(binding):
    arguments = {
        "action": "done",
        "task_id": binding.task_id,
        "result": "Synthetic trace lifecycle result for review",
        "complete": True,
    }
    with _relay(binding) as relay:
        result = _call(relay, arguments)
        assert binding._active is False
        assert binding.submitted_result is not None
        assert [event["phase"] for event in _events(binding)] == ["started", "returned"]
        acknowledged = _ack(relay, result)
        assert acknowledged["acknowledged"] is True
        events = _events(binding)
        assert [event["phase"] for event in events] == ["started", "returned", "acknowledged"]
        assert all(event["effect_status"] == "unknown" for event in events)
        with pytest.raises(urllib.error.HTTPError) as error:
            _http(relay, "/call", {
                "request_id": uuid.uuid4().hex,
                "previous_receipt": result["receipt_id"],
                "name": "task_manage",
                "arguments": {"action": "detail", "task_id": binding.task_id},
            })
        assert error.value.code in {403, 503}
        assert binding.tool_dispatch_count == 1


def _trace_api(binding, monkeypatch):
    from system.gui.api import worker_tool_trace as api
    app = FastAPI()
    app.include_router(api.router)
    monkeypatch.setattr(api, "BACH_DB", binding._client._db_path)
    allowed = {"Bearer starter-device", "Bearer observer-device"}
    def authorize(request):
        if request.headers.get("authorization") not in allowed:
            raise HTTPException(401, "device auth required")
    monkeypatch.setattr(api, "_authorize", authorize)
    return TestClient(app), api


def _trace_api_identity(binding, request_id):
    return TraceIdentity(
        task_id=binding.task_id, fence=binding._ack.fence,
        worker_id=binding._ack.worker_id, generation=binding._generation,
        task_version=binding._ack.task_version, request_id=request_id,
        source="cli-relay", tool_name="task_manage",
    )


def _trace_api_payload(identity, *, phase=None, receipt_id=None, result_sha256=None):
    payload = {
        "schema": SCHEMA, "fence": identity.fence, "worker_id": identity.worker_id,
        "generation": identity.generation, "task_version": identity.task_version,
        "request_id": identity.request_id, "source": identity.source,
        "tool_name": identity.tool_name,
    }
    if phase is None:
        payload["arguments_sha256"] = "b" * 64
    else:
        payload.update(phase=phase, receipt_id=receipt_id, result_sha256=result_sha256)
    return payload


def test_http_completion_is_bound_to_starter_and_exact_request(binding, monkeypatch):
    client, _ = _trace_api(binding, monkeypatch)
    identity = _trace_api_identity(binding, uuid.uuid4().hex)
    started = client.post(
        f"/api/tasks/{binding.task_id}/tool-trace/start",
        json=_trace_api_payload(identity),
        headers={"Authorization": "Bearer starter-device",
                 "X-Lease-Id": binding._ack.lease_id},
    )
    assert started.status_code == 200
    completion_token = started.json()["completion_token"]
    assert len(completion_token) == 43
    path = f"/api/tasks/{binding.task_id}/tool-trace/events"
    listed = client.get(
        path, headers={"Authorization": "Bearer observer-device"})
    assert listed.status_code == 200
    assert completion_token not in listed.text
    assert "completion_sha256" not in listed.text

    receipt_id = uuid.uuid4().hex
    returned = _trace_api_payload(
        identity, phase="returned", receipt_id=receipt_id, result_sha256="c" * 64)
    no_capability = client.post(
        path, json=returned, headers={"Authorization": "Bearer observer-device"})
    assert no_capability.status_code == 422
    forged_capability = client.post(
        path, json=returned,
        headers={"Authorization": "Bearer observer-device",
                 "X-Trace-Completion": "Z" * 43},
    )
    assert forged_capability.status_code == 409

    foreign_identity = TraceIdentity(
        task_id=identity.task_id, fence=identity.fence, worker_id=identity.worker_id,
        generation=identity.generation, task_version=identity.task_version,
        request_id=uuid.uuid4().hex, source=identity.source, tool_name=identity.tool_name,
    )
    foreign_request = client.post(
        path, json=_trace_api_payload(
            foreign_identity, phase="returned", receipt_id=receipt_id,
            result_sha256="c" * 64),
        headers={"Authorization": "Bearer observer-device",
                 "X-Trace-Completion": completion_token},
    )
    assert foreign_request.status_code == 422

    starter_return = client.post(
        path, json=returned,
        headers={"Authorization": "Bearer starter-device",
                 "X-Trace-Completion": completion_token},
    )
    assert starter_return.status_code == 200
    acknowledged = client.post(
        path, json=_trace_api_payload(
            identity, phase="acknowledged", receipt_id=receipt_id),
        headers={"Authorization": "Bearer starter-device",
                 "X-Trace-Completion": completion_token},
    )
    assert acknowledged.status_code == 200
    reread = client.get(path, headers={"Authorization": "Bearer observer-device"})
    assert [event["phase"] for event in reread.json()["events"]] == [
        "started", "returned", "acknowledged"]
    assert completion_token not in reread.text
    assert "completion_sha256" not in reread.text


def test_trace_http_never_creates_missing_database_and_reads_query_only(
        binding, tmp_path, monkeypatch):
    client, api = _trace_api(binding, monkeypatch)
    database = tmp_path / "missing" / "canonical.db"
    monkeypatch.setattr(api, "BACH_DB", database)
    identity = _trace_api_identity(binding, uuid.uuid4().hex)
    path = f"/api/tasks/{binding.task_id}/tool-trace/events"
    read = client.get(path, headers={"Authorization": "Bearer observer-device"})
    assert read.status_code == 503
    write = client.post(
        f"/api/tasks/{binding.task_id}/tool-trace/start",
        json=_trace_api_payload(identity),
        headers={"Authorization": "Bearer starter-device",
                 "X-Lease-Id": binding._ack.lease_id},
    )
    assert write.status_code == 503
    assert not database.exists()

    monkeypatch.setattr(api, "BACH_DB", binding._client._db_path)
    conn = api._connection(read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE read_only_probe(value TEXT)")
    finally:
        conn.close()


def test_trace_rejects_open_caller_transaction_without_ending_it(binding):
    from system.tests.test_task_lease_service import _connect
    database = binding._client._db_path
    with closing(_connect(database)) as setup:
        setup.execute("CREATE TABLE trace_transaction_probe(value TEXT)")
        setup.commit()

    identity = binding.trace_tool_started(
        source="cli-relay", request_id=uuid.uuid4().hex, tool_name="task_manage",
        arguments_sha256=digest_json({"action": "detail"}),
    )
    token = binding._trace_completion_tokens[identity]
    conn = _connect(database)
    observer = _connect(database)
    try:
        conn.execute("INSERT INTO trace_transaction_probe(value) VALUES ('pending-phase')")
        assert conn.in_transaction
        with pytest.raises(WorkerToolTraceError):
            append_phase(conn, identity, "failed", completion_token=token)
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM trace_transaction_probe").fetchone()[0] == "pending-phase"
        assert observer.execute("SELECT COUNT(*) FROM trace_transaction_probe").fetchone()[0] == 0
        conn.rollback()
        assert observer.execute("SELECT COUNT(*) FROM trace_transaction_probe").fetchone()[0] == 0

        second = TraceIdentity(
            task_id=identity.task_id, fence=identity.fence, worker_id=identity.worker_id,
            generation=identity.generation, task_version=identity.task_version,
            request_id=uuid.uuid4().hex, source=identity.source, tool_name=identity.tool_name,
        )
        conn.execute("INSERT INTO trace_transaction_probe(value) VALUES ('pending-start')")
        assert conn.in_transaction
        with pytest.raises(WorkerToolTraceError):
            append_started(conn, second, lease_id=binding._ack.lease_id,
                           arguments_sha256="d" * 64)
        assert conn.in_transaction
        assert conn.execute("SELECT value FROM trace_transaction_probe").fetchone()[0] == "pending-start"
        assert observer.execute("SELECT COUNT(*) FROM trace_transaction_probe").fetchone()[0] == 0
        conn.rollback()
        assert observer.execute("SELECT COUNT(*) FROM trace_transaction_probe").fetchone()[0] == 0
    finally:
        conn.close()
        observer.close()
