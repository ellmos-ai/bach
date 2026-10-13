"""Versioned tool-error relay tests: explicit metadata only, no result-text guessing."""
import asyncio
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from hub._services.chat import bach_tools
from hub._services.chat.bach_tools import BachToolProvider, exec_tool
from hub._services.chat.worker_tool_bridge import WorkerToolBridge
from hub._services.chat.worker_tool_client import WorkerToolClient
from hub._services.chat.worker_tool_errors import (
    SCHEMA,
    ToolErrorContractError,
    ToolErrorText,
    envelope_for,
    validate_envelope,
)

TASK_ID = 42001
GENERATION = "a" * 32
TOOL = {"type": "function", "function": {
    "name": "synthetic_tool", "description": "synthetic", "parameters": {"type": "object", "properties": {}}
}}


class _Binding:
    task_id = TASK_ID
    generation = GENERATION

    def __init__(self, *, fail_start=False, fail_phase=None):
        self.active = True
        self.fail_start = fail_start
        self.fail_phase = fail_phase
        self.events = []

    def assert_active(self):
        if not self.active:
            raise RuntimeError("inactive")

    def trace_tool_started(self, **values):
        self.events.append(("started", values))
        if self.fail_start:
            raise RuntimeError("private trace detail")
        return ("trace", values["request_id"])

    def trace_tool_phase(self, identity, phase, **values):
        self.events.append((phase, identity, values))
        if phase == self.fail_phase:
            raise RuntimeError("private trace detail")

    def invalidate(self):
        self.active = False


def _relay(monkeypatch, binding, execute):
    relay = WorkerToolBridge(binding, mode="safe")
    monkeypatch.setattr(relay._provider, "get_tools", lambda _mode: [TOOL])
    monkeypatch.setattr(relay._provider, "execute", execute)
    return relay


def _observe(client):
    original = client._http
    calls = []

    def observed(path, payload=None):
        calls.append(path)
        return original(path, payload)

    client._http = observed
    return calls


def test_tool_error_text_is_a_legacy_string_with_finite_trusted_metadata():
    value = ToolErrorText("BLOCKIERT: synthetic", code="write_path_denied")
    assert isinstance(value, str)
    assert str(value) == "BLOCKIERT: synthetic"
    correlation = {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                   "task_id": TASK_ID, "receipt_id": uuid.uuid4().hex}
    error = envelope_for(value, correlation)
    assert error == {
        "schema": SCHEMA, "code": "write_path_denied", "source": "bach_tools.write_file",
        "reason": "write_path_denied", "effect_state": "not_applied", "correlation": correlation,
    }
    assert validate_envelope(error, expected_correlation=correlation) == error


@pytest.mark.parametrize("bad", [
    {"request_id": uuid.uuid4().hex, "generation": GENERATION, "task_id": True, "receipt_id": None},
    {"request_id": uuid.uuid4().hex, "generation": "bad generation", "task_id": TASK_ID, "receipt_id": None},
    {"request_id": uuid.uuid4().hex, "generation": GENERATION, "task_id": TASK_ID, "receipt_id": "not-an-id"},
    {"request_id": uuid.uuid4().hex, "generation": GENERATION, "task_id": TASK_ID, "receipt_id": None, "extra": "field"},
])
def test_error_correlation_is_strict_and_dynamic(bad):
    with pytest.raises(ToolErrorContractError):
        envelope_for(ToolErrorText("Denied", code="tool_dispatch_denied"), bad)


def test_loopback_relay_preserves_safe_typed_denial_and_ack(monkeypatch):
    binding = _Binding()
    result = ToolErrorText("Schreiben nicht freigegeben.", code="write_tool_denied")
    with _relay(monkeypatch, binding, lambda *_: result) as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        calls = _observe(client)
        outcome = client.call_detailed("synthetic_tool", {})
        assert outcome.result == str(result)
        assert outcome.is_error is True and outcome.quarantined is False
        assert outcome.error["schema"] == SCHEMA
        assert outcome.error["code"] == "write_tool_denied"
        assert outcome.error["effect_state"] == "not_applied"
        assert outcome.error["correlation"]["receipt_id"]
        assert calls == ["/call", "/ack"]
        assert [event[0] for event in binding.events] == ["started", "returned", "acknowledged"]


def test_legacy_prefix_is_not_promoted_to_a_typed_denial(monkeypatch):
    binding = _Binding()
    text = "BLOCKIERT: ordinary result text"
    with _relay(monkeypatch, binding, lambda *_: text) as relay:
        outcome = WorkerToolClient.from_environment(relay.private_environment()).call_detailed("synthetic_tool", {})
    assert outcome.result == text
    assert outcome.error is None and outcome.is_error is False and outcome.quarantined is False
    assert [event[0] for event in binding.events] == ["started", "returned", "acknowledged"]


def test_trace_start_failure_is_not_started_quarantined_without_receipt(monkeypatch):
    binding = _Binding(fail_start=True)
    executed = []
    with _relay(monkeypatch, binding, lambda *args: executed.append(args)) as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        calls = _observe(client)
        outcome = client.call_detailed("synthetic_tool", {})
    assert executed == [] and calls == ["/call"]
    assert outcome.quarantined is True
    assert outcome.error["code"] == "trace_unavailable"
    assert outcome.error["effect_state"] == "not_started"
    assert outcome.error["correlation"]["receipt_id"] is None
    assert binding.active is False


def test_provider_exception_is_unknown_quarantined_and_redacted(monkeypatch):
    binding = _Binding()
    secret = "RAW_VENDOR_EXCEPTION_SECRET"

    def fail(*_):
        raise RuntimeError(secret)

    with _relay(monkeypatch, binding, fail) as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        calls = _observe(client)
        outcome = client.call_detailed("synthetic_tool", {})
    assert calls == ["/call"]
    assert outcome.quarantined is True
    assert outcome.error["code"] == "tool_execution_unconfirmed"
    assert outcome.error["reason"] == "reason_unavailable"
    assert outcome.error["effect_state"] == "unknown"
    assert outcome.error["correlation"]["receipt_id"] is None
    assert secret not in outcome.result and secret not in json.dumps(outcome.error)
    assert [event[0] for event in binding.events] == ["started", "failed"]
    assert binding.active is False


def test_explicit_unknown_producer_error_is_preserved_but_not_receipted(monkeypatch):
    binding = _Binding()
    value = ToolErrorText("Taskoperation nicht bestätigt.", code="task_operation_unconfirmed")
    with _relay(monkeypatch, binding, lambda *_: value) as relay:
        outcome = WorkerToolClient.from_environment(relay.private_environment()).call_detailed("synthetic_tool", {})
    assert outcome.result == str(value)
    assert outcome.quarantined is True
    assert outcome.error["code"] == "task_operation_unconfirmed"
    assert outcome.error["effect_state"] == "unknown"
    assert outcome.error["correlation"]["receipt_id"] is None
    started = next(event[1] for event in binding.events if event[0] == "started")
    assert outcome.error["correlation"] == {"request_id": started["request_id"],
                                             "generation": GENERATION,
                                             "task_id": TASK_ID, "receipt_id": None}
    assert [event[0] for event in binding.events] == ["started", "failed"]


def test_return_trace_failure_does_not_expose_unconfirmed_receipt(monkeypatch):
    binding = _Binding(fail_phase="returned")
    executed = []
    with _relay(monkeypatch, binding, lambda *_: executed.append("ran") or "synthetic output") as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        calls = _observe(client)
        outcome = client.call_detailed("synthetic_tool", {})
    assert executed == ["ran"] and calls == ["/call"]
    assert outcome.quarantined is True
    assert outcome.error["code"] == "returned_trace_unconfirmed"
    assert outcome.error["effect_state"] == "unknown"
    assert outcome.error["correlation"]["receipt_id"] is None
    assert all(event[0] != "acknowledged" for event in binding.events)
    assert binding.active is False


def test_client_rejects_malformed_correlation_without_ack_or_retry():
    client = WorkerToolClient("http://127.0.0.1:12345", "x" * 40, GENERATION, TASK_ID)
    calls = []

    def malformed(path, _payload=None):
        calls.append(path)
        if path == "/call":
            return {"request_id": "f" * 32, "receipt_id": "b" * 32,
                    "generation": GENERATION, "task_id": TASK_ID,
                    "result": "maybe", "is_error": False}
        raise AssertionError("malformed response must not be acknowledged")

    client._http = malformed
    outcome = client.call_detailed("synthetic_tool", {})
    assert calls == ["/call"]
    assert outcome.quarantined is True
    assert outcome.error["code"] == "transport_response_invalid"
    assert outcome.error["effect_state"] == "unknown"
    assert outcome.error["correlation"]["receipt_id"] is None


def test_lost_ack_is_unknown_and_call_is_never_retried(monkeypatch):
    binding = _Binding()
    executions = []
    with _relay(monkeypatch, binding, lambda *_: executions.append("once") or "done") as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        original = client._http
        calls = []

        def lose_ack(path, payload=None):
            calls.append(path)
            response = original(path, payload)
            if path == "/ack":
                raise OSError("synthetic lost ACK")
            return response

        client._http = lose_ack
        first = client.call_detailed("synthetic_tool", {})
        second = client.call_detailed("synthetic_tool", {})
    assert executions == ["once"]
    assert calls == ["/call", "/ack"]
    assert first.quarantined is True
    assert first.error["code"] == "transport_ack_unconfirmed"
    assert first.error["effect_state"] == "unknown"
    assert first.error["correlation"]["receipt_id"]
    assert second.quarantined is True
    assert second.error["code"] == "transport_response_unconfirmed"
    assert second.error["correlation"]["receipt_id"] is None


def test_legacy_call_tuple_survives_for_confirmed_success_and_denial(monkeypatch):
    binding = _Binding()
    values = iter([ToolErrorText("Denied", code="tool_dispatch_denied"), "ordinary success"])
    with _relay(monkeypatch, binding, lambda *_: next(values)) as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        denied = client.call("synthetic_tool", {})
        success = client.call("synthetic_tool", {})
    assert denied == ("Denied", True)
    assert success == ("ordinary success", False)


def test_stdio_mcp_exposes_structured_error_metadata(monkeypatch):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    binding = _Binding()
    denial = ToolErrorText("Denied", code="tool_dispatch_denied")
    with _relay(monkeypatch, binding, lambda *_: denial) as relay:
        script = Path(__file__).resolve().parents[1] / "hub/_services/chat/worker_tool_mcp.py"

        async def run():
            async with (
                stdio_client(StdioServerParameters(
                    command=sys.executable, args=["-X", "utf8", str(script)],
                    env=relay.private_environment())) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
                assert any(tool.name == "synthetic_tool" for tool in listed.tools)
                answer = await session.call_tool("synthetic_tool", {})
                assert answer.isError is True
                assert answer.content[0].text == "Denied"
                assert answer.structuredContent["schema"] == SCHEMA
                assert answer.structuredContent["code"] == "tool_dispatch_denied"
                assert answer.structuredContent["effect_state"] == "not_applied"

        asyncio.run(run())


@pytest.mark.parametrize(("name", "args", "mode", "bach_app", "reason"), [
    ("list_directory", {"path": "/etc"}, "safe", None, "path_not_authorized"),
    ("read_file", {"path": "/etc/passwd"}, "safe", None, "path_not_authorized"),
    ("search_text", {"pattern": None}, "safe", None, "search_pattern_invalid"),
    ("execute_command", {"command": "true"}, "safe", None, "mode_not_authorized"),
    ("bach_command", {"handler": "not-allowed"}, "safe", object(), "handler_not_allowed"),
])
def test_exec_tool_static_guards_emit_bounded_policy_denials(name, args, mode, bach_app, reason):
    result = exec_tool(name, args, mode, bach_app=bach_app)
    assert type(result) is ToolErrorText
    correlation = {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                   "task_id": TASK_ID, "receipt_id": uuid.uuid4().hex}
    envelope = envelope_for(result, correlation)
    assert envelope["code"] == "tool_policy_denied"
    assert envelope["source"] == "bach_tools"
    assert envelope["reason"] == reason
    assert envelope["effect_state"] == "not_applied"
    assert not any(secret in str(result) for secret in ("/etc", "not-allowed"))


def test_provider_allowlist_denial_uses_same_typed_bach_reason():
    provider = BachToolProvider(allowed_tools=set())
    result = provider.execute("read_file", {"path": "harmless.txt"}, "safe")
    correlation = {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                   "task_id": TASK_ID, "receipt_id": uuid.uuid4().hex}
    envelope = envelope_for(result, correlation)
    assert envelope["code"] == "tool_policy_denied"
    assert envelope["source"] == "bach_tools"
    assert envelope["reason"] == "tool_not_authorized"
    assert envelope["effect_state"] == "not_applied"


def test_read_file_content_with_denial_prefix_is_an_ordinary_success(tmp_path, monkeypatch):
    file_path = tmp_path / "ordinary.txt"
    file_path.write_text("BLOCKIERT: das ist Dateiinhalt\n", encoding="utf-8")
    monkeypatch.setattr(bach_tools, "_fs_root_allowed", lambda _path: True)
    result = exec_tool("read_file", {"path": str(file_path)}, "safe")
    assert type(result) is str
    assert result == "BLOCKIERT: das ist Dateiinhalt\n"
    assert envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                 "task_id": TASK_ID, "receipt_id": None}) is None


def test_partial_edit_write_is_unknown_and_redacted(tmp_path, monkeypatch):
    file_path = tmp_path / "partial.txt"
    file_path.write_text("old! contents", encoding="utf-8")
    original_write_text = Path.write_text
    secret = "PRIVATE_PARTIAL_WRITE_EXCEPTION"

    def partial_write(path, data, encoding=None, errors=None, newline=None):
        original_write_text(path, data[:3], encoding=encoding, errors=errors, newline=newline)
        raise OSError(secret)

    monkeypatch.setattr(Path, "write_text", partial_write)
    result = exec_tool("edit_file", {"path": str(file_path), "old_text": "old!",
                                      "new_text": "new-value"}, "full")
    assert type(result) is ToolErrorText
    assert str(result) == "Werkzeugausführung nicht bestätigt; Wirkung unbekannt."
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": uuid.uuid4().hex})
    assert envelope["code"] == "bach_tool_effect_unconfirmed"
    assert envelope["source"] == "bach_tools"
    assert envelope["effect_state"] == "unknown"
    assert secret not in str(result) and secret not in json.dumps(envelope)
    assert file_path.read_text(encoding="utf-8") == "new"


def test_web_fetch_network_failure_is_unknown_without_vendor_detail(monkeypatch):
    from hub.web_scrape import WebScrapeHandler

    secret = "PRIVATE_NETWORK_FAILURE_DETAIL"
    monkeypatch.setattr(WebScrapeHandler, "_request", lambda _self, _url: (None, secret))
    result = exec_tool("web_fetch", {"url": "https://example.invalid/resource"}, "safe")
    assert type(result) is ToolErrorText
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": None})
    assert envelope["code"] == "bach_tool_effect_unconfirmed"
    assert envelope["reason"] == "reason_unavailable"
    assert envelope["effect_state"] == "unknown"
    assert secret not in str(result) and secret not in json.dumps(envelope)

@pytest.mark.parametrize("bad_state", [[], {}, True, 1, None])
def test_envelope_rejects_non_string_effect_state_as_contract_error(bad_state):
    correlation = {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                   "task_id": TASK_ID, "receipt_id": uuid.uuid4().hex}
    envelope = envelope_for(ToolErrorText("Denied", code="write_path_denied"), correlation)
    envelope["effect_state"] = bad_state
    with pytest.raises(ToolErrorContractError):
        validate_envelope(envelope)


@pytest.mark.parametrize("helper_name", ["run_shell", "run_shell_restricted", "run_argv"])
@pytest.mark.parametrize("failure_kind", ["timeout", "exception"])
def test_post_dispatch_shell_helper_failures_are_unknown_and_redacted(
        monkeypatch, helper_name, failure_kind):
    secret = "PRIVATE_POST_DISPATCH_EXCEPTION_DETAIL"

    def fail(*args, **kwargs):
        if failure_kind == "timeout":
            raise bach_tools.subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 1))
        raise RuntimeError(secret)

    monkeypatch.setattr(bach_tools.subprocess, "run", fail)
    if helper_name == "run_shell":
        result = bach_tools.run_shell("synthetic fixed command")
    elif helper_name == "run_shell_restricted":
        monkeypatch.setattr(bach_tools.safe_exec, "resolve_executable", lambda *_args: ["synthetic"])
        result = bach_tools.run_shell_restricted("synthetic command")
    else:
        result = bach_tools.run_argv(["synthetic", "argument"])

    assert type(result) is ToolErrorText
    assert str(result) == "Werkzeugausführung nicht bestätigt; Wirkung unbekannt."
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": None})
    assert envelope["source"] == "bach_tools"
    assert envelope["reason"] == "reason_unavailable"
    assert envelope["effect_state"] == "unknown"
    assert secret not in str(result) and secret not in json.dumps(envelope)


@pytest.mark.parametrize("helper_name", ["run_shell", "run_shell_restricted", "run_argv"])
def test_nonzero_subprocess_exit_is_unknown_and_redacted_at_each_helper(
        monkeypatch, helper_name):
    stdout_secret = "PRIVATE_SUBPROCESS_STDOUT"
    stderr_secret = "PRIVATE_SUBPROCESS_STDERR"

    def failed_process(args, **_kwargs):
        return bach_tools.subprocess.CompletedProcess(
            args, 23, stdout=stdout_secret, stderr=stderr_secret)

    monkeypatch.setattr(bach_tools.subprocess, "run", failed_process)
    if helper_name == "run_shell":
        result = bach_tools.run_shell("synthetic fixed command")
    elif helper_name == "run_shell_restricted":
        monkeypatch.setattr(
            bach_tools.safe_exec, "resolve_executable",
            lambda *_args, **_kwargs: ["synthetic"],
        )
        result = bach_tools.run_shell_restricted("synthetic command")
    else:
        result = bach_tools.run_argv(["synthetic", "argument"])

    assert type(result) is ToolErrorText
    assert str(result) == "Werkzeugausf\u00fchrung nicht best\u00e4tigt; Wirkung unbekannt."
    envelope = envelope_for(result, {
        "request_id": uuid.uuid4().hex,
        "generation": GENERATION,
        "task_id": TASK_ID,
        "receipt_id": None,
    })
    assert envelope["code"] == "bach_tool_effect_unconfirmed"
    assert envelope["source"] == "bach_tools"
    assert envelope["reason"] == "reason_unavailable"
    assert envelope["effect_state"] == "unknown"
    assert stdout_secret not in str(result) and stderr_secret not in str(result)
    assert stdout_secret not in json.dumps(envelope) and stderr_secret not in json.dumps(envelope)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "restricted"),
    [
        ("ollama_info", {"action": "list"}, False),
        ("safe_shell", {"command": "synthetic"}, True),
        ("ollama_info", {"action": "show", "model": "synthetic-model"}, False),
    ],
)
def test_nonzero_subprocess_error_is_unknown_through_cli_and_worker_bridge(
        monkeypatch, tool_name, arguments, restricted):
    stderr_secret = "PRIVATE_BRIDGE_SUBPROCESS_STDERR"

    def failed_process(args, **_kwargs):
        return bach_tools.subprocess.CompletedProcess(
            args, 23, stdout="PRIVATE_STDOUT", stderr=stderr_secret)

    monkeypatch.setattr(bach_tools.subprocess, "run", failed_process)
    if restricted:
        monkeypatch.setattr(bach_tools, "is_safe_command", lambda _cmd: True)
        monkeypatch.setattr(bach_tools, "is_blocked", lambda _cmd: False)
        monkeypatch.setattr(bach_tools.safe_exec, "tokenize", lambda _cmd: ["synthetic"])
        monkeypatch.setattr(bach_tools.safe_exec, "dequote", lambda token: token)
        monkeypatch.setattr(bach_tools, "check_safe_shell_args", lambda _tokens: None)
        monkeypatch.setattr(
            bach_tools.safe_exec, "resolve_executable",
            lambda *_args, **_kwargs: ["synthetic"],
        )

    binding = _Binding()

    def execute(_name, _args, _mode):
        return exec_tool(tool_name, arguments, "safe")

    with _relay(monkeypatch, binding, execute) as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        calls = _observe(client)
        outcome = client.call_detailed("synthetic_tool", {})

    started = next(event[1] for event in binding.events if event[0] == "started")
    assert calls == ["/call"]
    assert outcome.quarantined is True
    assert outcome.error["code"] == "bach_tool_effect_unconfirmed"
    assert outcome.error["source"] == "bach_tools"
    assert outcome.error["effect_state"] == "unknown"
    assert outcome.error["correlation"] == {
        "request_id": started["request_id"],
        "generation": GENERATION,
        "task_id": TASK_ID,
        "receipt_id": None,
    }
    assert [event[0] for event in binding.events] == ["started", "failed"]
    assert stderr_secret not in outcome.result and stderr_secret not in json.dumps(outcome.error)
    assert "PRIVATE_STDOUT" not in outcome.result and "PRIVATE_STDOUT" not in json.dumps(outcome.error)


def test_gate_reopen_denial_rolls_back_and_is_typed_not_applied(tmp_path, monkeypatch):
    db_path = tmp_path / "gate-reopen.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
            "category TEXT, priority TEXT, status TEXT, assigned_to TEXT, depends_on TEXT, "
            "created_at TEXT, updated_at TEXT, completed_at TEXT)"
        )
        conn.execute(
            "INSERT INTO tasks (id, title, status) VALUES (1, 'Parked task', 'blocked')"
        )

    def reject_after_partial_write(conn, task_id, _existing, _updates, **_kwargs):
        conn.execute("UPDATE tasks SET title='must roll back' WHERE id=?", (task_id,))
        raise bach_tools.GateReopenBlocked("synthetic terminal-gate reason")

    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: str(db_path))
    monkeypatch.setattr(
        bach_tools, "_current_apply_task_field_changes", lambda: reject_after_partial_write)

    result = exec_tool(
        "task_manage", {"action": "update", "task_id": 1, "status": "open"}, "full")

    assert type(result) is ToolErrorText
    expected = (
        "[WARN] Task #1 ist terminal geparkt (Gate-Haltefrist) -- Reopen blockiert: "
        "synthetic terminal-gate reason. Fuer einen bewussten Reopen "
        + chr(96) + "bach task reopen 1" + chr(96) + " (oder unblock) nutzen."
    )
    assert str(result) == expected
    envelope = envelope_for(result, {
        "request_id": uuid.uuid4().hex,
        "generation": GENERATION,
        "task_id": TASK_ID,
        "receipt_id": None,
    })
    assert envelope["reason"] == "state_conflict"
    assert envelope["effect_state"] == "not_applied"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT title, status FROM tasks WHERE id=1").fetchone()
    assert row == ("Parked task", "blocked")


@pytest.mark.parametrize(("tool_name", "arguments", "mode", "requires_path_exists"), [
    ("system_status", {}, "safe", False),
    ("maintain", {"action": "run", "operation": "clean"}, "full", False),
    ("maintain", {"action": "health"}, "full", False),
    ("maintain", {"action": "services"}, "full", False),
    ("maintain", {"action": "sync"}, "full", True),
])
def test_shell_failure_metadata_survives_composing_tool_callers(
        monkeypatch, tool_name, arguments, mode, requires_path_exists):
    failure = ToolErrorText("Werkzeugausführung nicht bestätigt; Wirkung unbekannt.",
                            code="bach_tool_effect_unconfirmed")
    monkeypatch.setattr(bach_tools, "run_shell", lambda *_args, **_kwargs: failure)
    if requires_path_exists:
        monkeypatch.setattr(Path, "exists", lambda _path: True)
    result = exec_tool(tool_name, arguments, mode)
    assert result is failure
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": None})
    assert envelope["effect_state"] == "unknown"


def test_claude_http_errors_are_unknown_and_do_not_expose_vendor_text(monkeypatch):
    httpx = pytest.importorskip("httpx")
    secret = "PRIVATE_VENDOR_HTTP_ERROR"

    class Response:
        status_code = 503

        @staticmethod
        def json():
            return {"error": {"message": secret}}

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: Response())
    result = bach_tools._delegate_claude_api("synthetic prompt", "synthetic key")
    assert type(result) is ToolErrorText
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": None})
    assert envelope["effect_state"] == "unknown"
    assert secret not in str(result) and secret not in json.dumps(envelope)


@pytest.mark.parametrize("failure_kind", ["timeout", "exception"])
def test_delegate_post_dispatch_failures_are_unknown_and_redacted(monkeypatch, failure_kind):
    secret = "PRIVATE_DELEGATE_FAILURE_DETAIL"
    monkeypatch.setenv("BACH_DELEGATION_DEPTH", "0")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def failed_process(args, **kwargs):
        if failure_kind == "timeout":
            raise bach_tools.subprocess.TimeoutExpired(args, kwargs.get("timeout", 1))
        raise OSError(secret)

    monkeypatch.setattr(bach_tools.subprocess, "run", failed_process)
    result = exec_tool("delegate", {"target": "codex", "prompt": "synthetic"}, "full")
    assert type(result) is ToolErrorText
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": None})
    assert envelope["effect_state"] == "unknown"
    assert secret not in str(result) and secret not in json.dumps(envelope)


def test_claude_timeout_and_exception_are_unknown_without_vendor_text(monkeypatch):
    httpx = pytest.importorskip("httpx")
    secret = "PRIVATE_VENDOR_TIMEOUT_DETAIL"

    def fail(*_args, **_kwargs):
        raise httpx.TimeoutException(secret)

    monkeypatch.setattr(httpx, "post", fail)
    result = bach_tools._delegate_claude_api("synthetic prompt", "synthetic key")
    assert type(result) is ToolErrorText
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": None})
    assert envelope["effect_state"] == "unknown"
    assert secret not in str(result) and secret not in json.dumps(envelope)


def test_delegate_nonzero_exit_is_unknown_without_raw_stderr(monkeypatch):
    secret = "PRIVATE_DELEGATE_STDERR"
    monkeypatch.setenv("BACH_DELEGATION_DEPTH", "0")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def failed_process(args, **_kwargs):
        return bach_tools.subprocess.CompletedProcess(args, 1, stdout="", stderr=secret)

    monkeypatch.setattr(bach_tools.subprocess, "run", failed_process)
    result = exec_tool("delegate", {"target": "codex", "prompt": "synthetic"}, "full")
    assert type(result) is ToolErrorText
    envelope = envelope_for(result, {"request_id": uuid.uuid4().hex, "generation": GENERATION,
                                     "task_id": TASK_ID, "receipt_id": None})
    assert envelope["effect_state"] == "unknown"
    assert secret not in str(result) and secret not in json.dumps(envelope)


def test_post_dispatch_timeout_is_quarantined_and_matches_started_trace(monkeypatch):
    binding = _Binding()

    def timeout(*args, **kwargs):
        raise bach_tools.subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 1))

    monkeypatch.setattr(bach_tools.subprocess, "run", timeout)
    with _relay(monkeypatch, binding, lambda *_: bach_tools.run_shell("synthetic fixed command")) as relay:
        client = WorkerToolClient.from_environment(relay.private_environment())
        calls = _observe(client)
        outcome = client.call_detailed("synthetic_tool", {})
    started = next(event[1] for event in binding.events if event[0] == "started")
    correlation = outcome.error["correlation"]
    assert calls == ["/call"]
    assert outcome.quarantined is True
    assert outcome.error["effect_state"] == "unknown"
    assert correlation == {"request_id": started["request_id"], "generation": GENERATION,
                           "task_id": TASK_ID, "receipt_id": None}
    assert [event[0] for event in binding.events] == ["started", "failed"]



@pytest.mark.parametrize(
    ("action_args", "row", "expected_text", "expected_reason"),
    [
        ({"action": "done"}, None, "Keine Task-ID angegeben", "invalid_arguments"),
        ({"action": "done", "task_id": TASK_ID}, None,
         f"Task #{TASK_ID} nicht gefunden", "resource_not_found"),
        ({"action": "done", "task_id": 1},
         (1, "Already complete", "", "done"),
         "Task #1 war bereits erledigt.", "state_conflict"),
        ({"action": "decompose", "task_id": 1,
          "subtasks": [{"title": "Child", "description": "Work"}]},
         (1, "Parent review", "[In 1 Teilaufgaben zerlegt]", "open"),
         ("Task #1 ('Parent review') ist bereits eine Teilaufgabe oder wurde bereits zerlegt "
         "und kann nicht weiter rekursiv aufgeteilt werden. "
         "Bitte führe die Aufgabe direkt im Code aus oder aktualisiere sie mit action='update'."),
         "state_conflict"),
    ],
)
def test_legacy_task_manage_denials_keep_display_text_and_typed_reason(
        tmp_path, monkeypatch, action_args, row, expected_text, expected_reason):
    db_path = tmp_path / "task-manage.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT, description TEXT, "
            "category TEXT, priority TEXT, status TEXT, assigned_to TEXT, depends_on TEXT, "
            "created_at TEXT, updated_at TEXT, completed_at TEXT)"
        )
        if row is not None:
            conn.execute(
                "INSERT INTO tasks (id, title, description, status) VALUES (?, ?, ?, ?)",
                row,
            )
    monkeypatch.setattr(bach_tools, "_current_runtime_db", lambda: str(db_path))
    monkeypatch.setattr(bach_tools, "_current_apply_task_field_changes", lambda: None)

    result = exec_tool("task_manage", action_args, "safe")

    assert type(result) is ToolErrorText
    assert str(result) == expected_text
    envelope = envelope_for(result, {
        "request_id": uuid.uuid4().hex,
        "generation": GENERATION,
        "task_id": TASK_ID,
        "receipt_id": None,
    })
    assert envelope["schema"] == SCHEMA
    assert envelope["source"] == "bach_tools"
    assert envelope["reason"] == expected_reason
    assert envelope["effect_state"] == "not_applied"
