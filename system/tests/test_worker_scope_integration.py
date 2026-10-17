"""Scope capture must preserve real submissions and avoid SQLite/controller locks."""
import asyncio
import sqlite3
import threading

import pytest

from hub._services.task_lease_client import LeaseProtocolError, TaskLeaseClient
from system.tests.test_task_lease_client import mem_db
from system.tests.test_worker_execution_evidence import worker_context, _submit
from system.tests.test_task_result_correction_api import api_review, _request


def test_dispatcher_captures_only_after_real_submit_outside_locks(worker_context, monkeypatch):
    from hub._services.chat.bach_tools import exec_tool
    from hub._services import worker_scope_evidence as evidence

    ctx = worker_context
    binding, conn = ctx["binding"], ctx["conn"]
    observed = []

    def capture(db, actual):
        assert actual is binding and db is conn
        assert not conn.in_transaction and not binding._lock._is_owned()
        assert binding._completion_result["result_id"] > 0
        assert binding._review_ack.released is True
        observed.append(binding._completion_result["result_id"])
        raise RuntimeError("optional Git/lock service unavailable")

    monkeypatch.setattr(evidence, "capture_scope_evidence", capture)
    response = exec_tool("task_manage", {
        "action": "submit_result", "task_id": ctx["task_id"], "complete": True,
        "result": "Fachliches Ergebnis bleibt trotz fehlendem Scope in Review.",
    }, "full", worker_task_binding=binding, require_task_binding=True)
    assert "Ergebnis gespeichert" in response
    assert len(observed) == 1
    state = binding.result_state()
    assert state["reviewed_task_ids"] == (ctx["task_id"],)
    assert not state["result"]["accepted"]


def test_lost_ack_capture_waits_for_canonical_reconciliation(worker_context, monkeypatch):
    from hub._services import worker_scope_evidence as evidence

    ctx = worker_context
    binding, client = ctx["binding"], ctx["client"]
    original = client.submit_result
    captured = []

    def commit_then_lose_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("lost transport ACK after committed submission")

    def capture(conn, actual):
        assert actual._completion_result is not None
        assert not actual._lock._is_owned() and not conn.in_transaction
        captured.append(actual._completion_result["result_id"])
        return True

    monkeypatch.setattr(client, "submit_result", commit_then_lose_ack)
    monkeypatch.setattr(evidence, "capture_scope_evidence", capture)
    with pytest.raises(LeaseProtocolError):
        _submit(binding, ctx["task_id"])
    assert captured == [] and binding._completion_result is None
    state = binding.result_state()
    assert captured == [state["result"]["result_id"]]
    assert state["reviewed_task_ids"] == (ctx["task_id"],)


@pytest.mark.parametrize("caller_transaction", [False, True])
def test_local_projection_runs_only_after_sqlite_snapshot(worker_context, monkeypatch,
                                                         caller_transaction):
    from hub._services import worker_scope_evidence as evidence

    ctx = worker_context
    _submit(ctx["binding"], ctx["task_id"])
    conn = ctx["conn"]
    projected = []

    def project(data):
        assert not conn.in_transaction
        projected.append(data["task_id"])
        return data

    monkeypatch.setattr(evidence, "project_scope_evidence", project)
    if caller_transaction:
        conn.execute("BEGIN")
    try:
        result = ctx["client"].task_result_snapshot(ctx["task_id"])
        assert result["result"]["result_revision"] is None
        assert projected == ([] if caller_transaction else [ctx["task_id"]])
        assert conn.in_transaction is caller_transaction
    finally:
        if caller_transaction:
            conn.rollback()


def test_remote_capture_has_no_http_or_local_fallback(worker_context, monkeypatch):
    ctx = worker_context
    remote = TaskLeaseClient(conn=ctx["conn"], lead_url="https://lead.invalid",
                             device_token="fixture-token")

    def forbidden(*args, **kwargs):
        pytest.fail("remote capture cannot call HTTP or open a local database")

    monkeypatch.setattr(remote, "_http_request", forbidden)
    monkeypatch.setattr(remote, "_get_local_connection", forbidden)
    assert remote._capture_task_scope(ctx["binding"]) is False
    assert ctx["client"]._capture_task_scope(object()) is False


def test_successful_capture_is_once_but_current_readback_remains_fresh(worker_context, monkeypatch):
    from hub._services import worker_scope_evidence as evidence

    ctx = worker_context
    _submit(ctx["binding"], ctx["task_id"])
    captures, projections = [], []

    def capture(conn, binding):
        captures.append(binding._completion_result["result_id"])
        return True

    def project(data):
        projections.append(data["task_id"])
        return data

    monkeypatch.setattr(evidence, "capture_scope_evidence", capture)
    monkeypatch.setattr(evidence, "project_scope_evidence", project)
    first = ctx["binding"].result_state()
    second = ctx["binding"].result_state()
    assert first["reviewed_task_ids"] == second["reviewed_task_ids"] == (ctx["task_id"],)
    assert len(captures) == 1
    assert projections == [ctx["task_id"], ctx["task_id"]]


def test_api_projects_after_close_off_event_loop(api_review, monkeypatch):
    from hub._services import worker_scope_evidence as evidence

    server, keeper, task_id, _, _, token, _ = api_review
    db_path = keeper.execute("PRAGMA database_list").fetchone()[2]
    connections = []
    main_thread = threading.get_ident()

    class TrackedConnection(sqlite3.Connection):
        closed_for_projection = False

        def close(self):
            super().close()
            self.closed_for_projection = True

    def connect():
        conn = sqlite3.connect(db_path, factory=TrackedConnection)
        conn.row_factory = sqlite3.Row
        connections.append(conn)
        return conn

    def project(data):
        assert connections and all(c.closed_for_projection for c in connections)
        assert threading.get_ident() != main_thread
        return data

    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(evidence, "project_scope_evidence", project)
    result = asyncio.run(server.read_task_result(task_id, _request(token)))
    assert result["result"]["accepted"] is False
    assert result["operator_capabilities"]["accept_result"] is True
