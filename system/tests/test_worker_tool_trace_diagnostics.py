"""Closed diagnostics on the real memory-only lease/trace owner; no live services."""
import ast
import copy
import json
import sqlite3
import threading
import types
import uuid
from pathlib import Path

import pytest
from system.tests.test_task_lease_client import _init_db, _insert_task
from hub._services import task_lease_client as clients
from hub._services.chat import worker_tool_trace as trace
from hub._services.chat import worker_tool_dispatch_trace as dispatch
from hub._services.chat.worker_tool_errors import ToolErrorText
from core.sandbox import SandboxResult

POLICY = {"outcome_class": "policy_rejected", "stage": "pre_dispatch_validation",
          "code": "command_not_authorized", "sandbox_returncode": None}


def extract(path, names, env):
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), env)
    return env


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(clients, "get_lead_config", lambda: {"mode": "isolated"})
    monkeypatch.setenv("BACH_TASK_LEASE_CREATOR_WINDOW", "0")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    tid = _insert_task(conn, title="Private trace fixture", status="open")
    client = clients.TaskLeaseClient(conn=conn)
    lease = client.acquire(tid, worker_id="private-worker@private-host", host="private-host",
                           task_version=client.task_snapshot(tid)["task_version"],
                           result_generation="private-trace-generation")
    identity = trace.TraceIdentity(tid, lease.fence, lease.worker_id, "private-trace-generation",
        lease.task_version, uuid.uuid4().hex, "normal-loop", "execute_command")
    class Binding:
        closed = False
        def assert_active(self):
            assert client.read(tid, lease_id=lease.lease_id).own is True
        def invalidate(self, reason):
            self.closed = True
        def quarantine_lease(self):
            pass
    source = Path(__file__).parents[1] / "hub/_services/chat/worker_lease_binding.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "WorkerLeaseBinding")
    methods = [n for n in owner.body if isinstance(n, ast.FunctionDef)
               and n.name in {"trace_tool_started", "trace_tool_phase"}]
    env = {"LeaseProtocolError": clients.LeaseProtocolError,
           "__name__": "hub._services.chat._private_binding_probe",
           "__package__": "hub._services.chat"}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), env)
    for method in methods:
        setattr(Binding, method.name, env[method.name])
    binding = Binding()
    binding.task_id, binding._client, binding._ack = tid, client, lease
    binding._lock, binding._generation = threading.RLock(), identity.generation
    binding._snapshot = {"task_version": lease.task_version}
    binding._trace_completion_tokens = {}
    yield conn, client, identity, binding
    conn.close()


def start(world):
    conn, _, identity, binding = world
    actual = binding.trace_tool_started(source=identity.source, request_id=identity.request_id,
        tool_name=identity.tool_name, arguments_sha256=trace.digest_json({"synthetic": "private"}))
    return actual, binding._trace_completion_tokens[actual]


def test_dispatch_policy_channel_roundtrip_preserves_unknown_and_privacy(world):
    conn, client, identity, binding = world
    hidden = "private-output-must-not-be-stored"
    result = dispatch.execute_normal_tool(binding, "execute_command", {"command": hidden},
        lambda *_: ToolErrorText(hidden, code="tool_policy_denied", reason="command_not_authorized"))
    assert result.status == "returned"
    assert dispatch.acknowledge_normal_tool_result(binding, result)
    old = client.tool_trace_events(identity.task_id)["events"]
    assert all("diagnostic" not in row and row["effect_status"] == "unknown" for row in old)
    rows = client.tool_trace_events(identity.task_id, include_diagnostics=True)["events"]
    assert [r["phase"] for r in rows] == ["started", "returned", "acknowledged"]
    assert rows[1]["diagnostic"] == POLICY and rows[0]["diagnostic"] is None
    assert hidden not in json.dumps(rows) and "completion_token" not in json.dumps(rows)


def test_plain_error_looking_text_is_not_diagnostic(world):
    _, client, identity, binding = world
    result = dispatch.execute_normal_tool(binding, "execute_command", {}, lambda *_: "BLOCKIERT Exitcode 0")
    assert dispatch.acknowledge_normal_tool_result(binding, result)
    assert all(x["diagnostic"] is None for x in client.tool_trace_events(identity.task_id, include_diagnostics=True)["events"])


def test_generic_exception_retains_unknown_no_exception_text(world):
    _, client, identity, binding = world
    def fail(*_):
        raise RuntimeError("synthetic-sensitive-exception")
    result = dispatch.execute_normal_tool(binding, "execute_command", {}, fail)
    assert result.status == "failed"
    rows = client.tool_trace_events(identity.task_id, include_diagnostics=True)["events"]
    assert rows[-1]["diagnostic"]["code"] == "tool_exception"
    assert rows[-1]["effect_status"] == "unknown"
    assert "synthetic-sensitive-exception" not in json.dumps(rows)


@pytest.mark.parametrize("change", [{"extra": "private"}, {"code": []}, {"stage": {}},
    {"code": "unknown-code"}, {"sandbox_returncode": False}, {"outcome_class": "success"}])
def test_malformed_diagnostic_denied_before_database_change(world, change):
    conn, _, identity, _ = world
    _, token = start(world)
    before = conn.total_changes
    invalid = {**POLICY, **change}
    with pytest.raises(trace.WorkerToolTraceError):
        trace.append_phase(conn, identity, "returned", receipt_id=uuid.uuid4().hex,
            result_sha256="a" * 64, completion_token=token, diagnostic=invalid)
    assert conn.total_changes == before


def test_partial_diagnostic_denied(world):
    conn, _, identity, _ = world
    _, token = start(world)
    with pytest.raises(trace.WorkerToolTraceError):
        trace.append_phase(conn, identity, "failed", completion_token=token,
                           diagnostic={"outcome_class": "unconfirmed"})


def test_same_event_replay_requires_same_diagnostic(world):
    conn, _, identity, _ = world
    _, token = start(world)
    args = dict(receipt_id=uuid.uuid4().hex, result_sha256="b" * 64,
                completion_token=token, diagnostic=POLICY)
    first = trace.append_phase(conn, identity, "returned", **args)
    count = conn.total_changes
    second = trace.append_phase(conn, identity, "returned", **args)
    assert first["event_id"] == second["event_id"] and conn.total_changes == count
    args["diagnostic"] = {**POLICY, "code": "invalid_arguments"}
    with pytest.raises(trace.TraceReplayError):
        trace.append_phase(conn, identity, "returned", **args)
    assert conn.total_changes == count


def test_wrong_generation_cannot_attach_diagnostic(world):
    conn, _, identity, _ = world
    _, token = start(world)
    from dataclasses import replace
    wrong = replace(identity, generation="foreign-generation")
    with pytest.raises(trace.TraceCorrelationError):
        trace.append_phase(conn, wrong, "failed", completion_token=token, diagnostic=POLICY)


@pytest.mark.parametrize("change", [{}, {"cleanup_confirmed": None}, {"cleanup_confirmed": False},
    {"watchdog_joined": False}, {"cleanup_scope": None}, {"cleanup_errors": ("private",)},
    {"timed_out": True}, {"memory_exceeded": True}, {"returncode": False}])
def test_sandbox_exit_only_from_confirmed_clean_terminal(change):
    source = Path(__file__).parents[1] / "hub/_services/chat/bach_tools.py"
    env = extract(source, {"_bound_check_text", "_tool_effect_unconfirmed"}, {"ToolErrorText": ToolErrorText})
    values = dict(returncode=7, stdout="synthetic-stdout", stderr="synthetic-stderr",
        cleanup_confirmed=True, watchdog_joined=True, cleanup_scope="owned_posix_process_group")
    values.update(change)
    rendered = env["_bound_check_text"](SandboxResult(**values), 60)
    diag = dispatch._result_diagnostic("execute_command", rendered)
    if not change:
        assert diag["sandbox_returncode"] == 7 and diag["outcome_class"] == "sandbox_terminal"
    else:
        assert diag is None


def test_unconfirmed_typed_error_does_not_become_policy_or_exit():
    value = ToolErrorText("synthetic", code="bach_tool_effect_unconfirmed")
    diag = dispatch._result_diagnostic("execute_command", value)
    assert diag["outcome_class"] == "unconfirmed" and diag["sandbox_returncode"] is None


def test_remote_transport_and_reader_use_closed_optional_payload(monkeypatch):
    monkeypatch.setattr(clients, "get_lead_config", lambda: {"mode": "isolated"})
    client = clients.TaskLeaseClient(lead_url="http://private.invalid", device_token="synthetic-not-a-real-token")
    identity = trace.TraceIdentity(1, 1, "worker@private", "generation", "a" * 64,
        uuid.uuid4().hex, "normal-loop", "execute_command")
    calls = []
    def http(method, path, payload=None, headers=None):
        calls.append((method, path, payload))
        return 200, {"schema": trace.SCHEMA, "accepted": True, "event_id": 1,
            "task_id": 1, "request_id": identity.request_id, "phase": "returned"}
    monkeypatch.setattr(client, "_http_request", http)
    client.tool_trace_phase(identity, "returned", receipt_id=uuid.uuid4().hex,
        result_sha256="b" * 64, completion_token="a" * 43, diagnostic=POLICY)
    assert calls[0][2]["diagnostic"] == POLICY
    before = len(calls)
    with pytest.raises(clients.LeaseProtocolError):
        client.tool_trace_phase(identity, "failed", completion_token="a" * 43, diagnostic={})
    assert len(calls) == before


def test_append_only_trigger_and_read_only_projection(world):
    conn, _, identity, _ = world
    start(world)
    before = conn.total_changes
    trace.list_events(conn, identity.task_id, include_diagnostics=True)
    assert conn.total_changes == before
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE worker_tool_trace_events SET diagnostic_json='null'")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM worker_tool_trace_events")
    conn.rollback()
