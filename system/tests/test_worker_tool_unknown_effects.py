# SPDX-License-Identifier: MIT
"""Unknown effects halt the real bound trace/lease flow; all data is temporary."""
import asyncio
import json

import pytest

from hub._services.chat import chat_runtime
from hub._services.chat.chat_runtime import ChatRuntime, ChatSession, FailedAnswer
from hub._services.chat.worker_tool_errors import ToolErrorText
from hub._services.chat.worker_tool_dispatch_trace import execute_normal_tool, acknowledge_normal_tool_result
from system.tests.test_worker_tool_dispatch_trace import (
    binding, _events, _phases, _assert_blocked_and_foreign_claim_denied,
)


def test_typed_task_operation_unknown_effect_is_held_before_consumption_ack(binding):
    code = "task_operation_unconfirmed"
    operations = []
    secret = "synthetic-private-result"
    def execute(name, args):
        operations.append(name)
        return ToolErrorText(secret, code=code)
    outcome = execute_normal_tool(binding, "task_manage", {"action": "submit_result"}, execute)
    assert outcome.status == "unknown" and outcome.result is None
    assert outcome.error_code == "task_operation_unconfirmed"
    assert _phases(binding) == ["started", "returned"]
    assert binding._client.tool_trace_events(
        binding.task_id, include_diagnostics=True)["events"][1]["diagnostic"] == {
        "outcome_class": "unconfirmed", "stage": "unknown",
        "code": "execution_unconfirmed", "sandbox_returncode": None}
    assert not acknowledge_normal_tool_result(binding, outcome)
    _assert_blocked_and_foreign_claim_denied(binding)
    retry = execute_normal_tool(binding, "task_manage", {"action": "submit_result"}, execute)
    assert retry.status == "unknown" and operations == ["task_manage"]
    assert secret not in json.dumps(_events(binding))


def test_unknown_effect_without_quarantine_ack_does_not_invent_blocked(binding, monkeypatch):
    monkeypatch.setattr(binding, "quarantine_lease", lambda **_kw: False)
    outcome = execute_normal_tool(binding, "task_manage", {"action": "submit_result"},
        lambda *_: ToolErrorText("synthetic", code="task_operation_unconfirmed"))
    assert outcome.status == "unknown" and binding._active is False
    assert binding._client.read(binding.task_id).status == "in_progress"
    assert _phases(binding) == ["started", "returned"]
    assert not acknowledge_normal_tool_result(binding, outcome)


@pytest.mark.parametrize("spoof", [False, True])
def test_display_text_and_spoofed_string_attributes_do_not_establish_unknown_effect(binding, spoof):
    class ForgedString(str):
        _code = "task_operation_unconfirmed"
        _effect_state = "unknown"
    text = "Taskoperation nicht bestaetigt; Taskbindung pruefen."
    result = ForgedString(text) if spoof else text
    outcome = execute_normal_tool(binding, "task_manage", {"action": "detail"}, lambda *_: result)
    assert outcome.status == "returned" and acknowledge_normal_tool_result(binding, outcome)
    assert _phases(binding) == ["started", "returned", "acknowledged"]
    assert binding._active is True
    assert binding._client.read(binding.task_id).status == "in_progress"


@pytest.mark.parametrize("kind", ["unknown", "policy"])
def test_runtime_stops_unknown_before_second_operation_and_keeps_policy_limit(binding, monkeypatch, kind):
    class Backend:
        backend_id = "synthetic"
        manages_own_tools = False
        def __init__(self):
            self.calls = 0
        def get_default_model(self):
            return "synthetic-model"
        def get_context_limit(self, *args):
            return 32768
        def tool_response_message(self, text, _call_id):
            return {"role": "tool", "content": text}
        async def chat(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 1:
                return {"content": "synthetic final", "tool_calls": None}
            return {"content": "", "tool_calls": [
                {"function": {"name": "task_manage", "arguments": {
                    "action": "update", "task_id": binding.task_id, "description": str(i)}}}
                for i in range(5)]}
    backend = Backend()
    runtime = ChatRuntime(backend)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_a, **_kw: None)
    from hub._services.chat import slots_config
    monkeypatch.setattr(slots_config, "update_slot", lambda *_a, **_kw: None)
    operations = []
    def execute(name, args, *a, **kw):
        operations.append(args["description"])
        if kind == "unknown":
            return ToolErrorText("synthetic", code="task_operation_unconfirmed")
        return ToolErrorText("synthetic policy", code="tool_policy_denied", reason="mode_not_authorized")
    monkeypatch.setattr(chat_runtime, "exec_tool", execute)
    session = ChatSession()
    session.chat_id = "synthetic-unknown-worker"
    session.worker_task_binding = binding
    session.allowed_tools = {"task_manage"}
    session.allow_tools = True
    session.max_tool_rounds = 8
    answer = asyncio.run(runtime._tool_loop(
        [{"role": "user", "content": "synthetic test"}], session,
        [{"type": "function", "function": {"name": "task_manage", "parameters": {"type": "object"}}}],
        backend=backend, model="synthetic-model"))
    assert isinstance(answer, FailedAnswer)
    assert answer.reason_code == ("task_operation_unconfirmed" if kind == "unknown" else "tool_denial_limit")
    assert operations == (["0"] if kind == "unknown" else ["0", "1", "2", "3"])
    assert backend.calls == 1
    if kind == "unknown":
        _assert_blocked_and_foreign_claim_denied(binding)
        assert _phases(binding) == ["started", "returned"]
    else:
        assert binding._active and binding._client.read(binding.task_id).leased



def test_normal_bound_worker_schema_keeps_completion_contract(binding):
    from hub._services.chat.bach_tools import BachToolProvider
    provider = BachToolProvider(worker_task_binding=binding, allowed_tools={"task_manage"})
    schema = next(t["function"]["parameters"] for t in provider.get_tools("safe")
                  if t["function"]["name"] == "task_manage")
    assert "complete" in schema["properties"]
    assert "update" in schema["properties"]["action"]["enum"]



def test_unknown_effect_with_lost_native_quarantine_ack_keeps_hold_without_fake_receipt(binding, monkeypatch):
    from hub._services.task_lease_client import LeaseProtocolError
    original = binding._client.release
    releases = []
    def release(*args, **kwargs):
        releases.append(True)
        original(*args, **kwargs)
        raise LeaseProtocolError("synthetic lost quarantine ACK")
    monkeypatch.setattr(binding._client, "release", release)
    outcome = execute_normal_tool(binding, "task_manage", {"action": "submit_result"},
        lambda *_: ToolErrorText("synthetic", code="task_operation_unconfirmed"))
    assert outcome.status == "unknown" and outcome.result is None
    assert binding._quarantine_ack is None and releases == [True]
    assert binding._client.read(binding.task_id).status == "blocked"
    assert not acknowledge_normal_tool_result(binding, outcome)
    assert _phases(binding) == ["started", "returned"]


def test_unknown_after_closed_submission_does_not_requeue_or_requarantine(binding, monkeypatch):
    quarantine = []
    original = binding.quarantine_lease
    def checked():
        quarantine.append(True)
        return original()
    monkeypatch.setattr(binding, "quarantine_lease", checked)
    def submitted(*_):
        assert binding.record_worktree_result(binding.task_id, "synthetic result",
            review=True, result_ref="https://github.com/example/repo/pull/1")
        return ToolErrorText("synthetic lost operation ACK", code="task_operation_unconfirmed")
    outcome = execute_normal_tool(binding, "task_manage", {"action": "submit_result"}, submitted)
    assert outcome.status == "unknown" and binding.closed is True
    assert binding._client.read(binding.task_id).status == "review"
    assert quarantine == [] and not acknowledge_normal_tool_result(binding, outcome)
    assert _phases(binding) == ["started", "returned"]



def test_diagnostic_observation_does_not_establish_task_operation_authority(binding):
    from hub._services.chat.worker_tool_trace import DiagnosticToolText
    value = DiagnosticToolText("synthetic observation", {
        "outcome_class": "unconfirmed", "stage": "unknown",
        "code": "execution_unconfirmed", "sandbox_returncode": None})
    outcome = execute_normal_tool(binding, "execute_command", {}, lambda *_: value)
    assert outcome.status == "returned" and acknowledge_normal_tool_result(binding, outcome)
    assert binding._active and binding._client.read(binding.task_id).leased
    assert _phases(binding) == ["started", "returned", "acknowledged"]



def test_confirmed_task_unknown_quarantine_records_bounded_native_note(binding):
    outcome = execute_normal_tool(binding, "task_manage", {"action": "submit_result"},
        lambda *_: ToolErrorText("synthetic-private-result", code="task_operation_unconfirmed"))
    assert outcome.status == "unknown" and binding._quarantine_ack is not None
    conn = binding._client._get_local_connection()
    try:
        notes = [json.loads(row["new_value"])["note"] for row in conn.execute(
            "SELECT new_value FROM task_history WHERE task_id=? AND action='lease_release'",
            (binding.task_id,))]
    finally:
        conn.close()
    assert len(notes) == 1 and "task_operation_unconfirmed" in notes[0]
    assert notes[0].startswith("backend_error_after_tool_dispatch:")
    assert "synthetic-private" not in notes[0]
    assert _phases(binding) == ["started", "returned"]
