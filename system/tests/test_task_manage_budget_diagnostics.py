"""Bounded diagnostics and the zero-budget final tool-round boundary."""
from __future__ import annotations

import asyncio
import copy
import sys
import uuid
from pathlib import Path

import pytest

SYSTEM = Path(__file__).resolve().parents[1]
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from hub._services.chat import bach_tools, chat_runtime
from hub._services.chat.task_cut_rule import TASK_CUT_RULE_SHORT
from hub._services.task_lease_client import (
    LeaseDeniedError, LeaseProtocolError, LeaseSelfCheckRequiredError,
)
from hub._services.llm.model_backend import OllamaBackend
from test_task_lease_client import mem_db
from test_worker_lease_binding import binding


class _Bound:
    task_id = 2217
    generation = uuid.uuid4().hex
    _review_grant = None

    def __init__(self, failure):
        self.failure = failure
        self.dispatches = 0

    def assert_active(self):
        return None

    def mark_tool_dispatch(self):
        return None

    def task_snapshot(self):
        return {"id": self.task_id, "result_max_chars": 10000}

    def execute_task_manage(self, _args, *, _dispatch_marked):
        assert _dispatch_marked is True
        self.dispatches += 1
        raise self.failure


@pytest.mark.parametrize("failure,kind,reason", [
    (LeaseDeniedError(2217, "stale_task_version",
                      {"task_id": 2217, "reason": "stale_task_version"}),
     "lease_denied", "stale_task_version"),
    (LeaseProtocolError("PRIVATE owner or ACK data"), "lease_protocol", "none"),
    (RuntimeError("PRIVATE ACK TEXT token=do-not-log"), "other", "none"),
])
def test_dispatch_denial_logs_only_finite_provenance_and_never_retries(
    caplog, monkeypatch, failure, kind, reason,
):
    from hub._services import task_result_service

    monkeypatch.setattr(task_result_service, "validate_submission", lambda *_a, **_k: None)
    bound = _Bound(failure)
    caplog.set_level("WARNING", logger="bach.chat")
    answer = bach_tools.exec_tool(
        "task_manage", {"action": "submit_result", "task_id": 2217,
                        "result": "PRIVATE RESULT do-not-log", "complete": True}, "full",
        worker_task_binding=bound, require_task_binding=True,
        allowed_tools={"task_manage"},
    )
    assert answer == "Taskoperation nicht bestätigt; Taskbindung prüfen."
    assert bound.dispatches == 1
    diagnostic = [record.getMessage() for record in caplog.records
                  if "bound_task_manage_denied" in record.getMessage()]
    assert len(diagnostic) == 1
    assert all(part in diagnostic[0] for part in (
        "stage=dispatch", "action=submit_result", f"kind={kind}",
        f"reason={reason}", "task_id=2217", f"generation={bound.generation}"))
    assert "PRIVATE" not in diagnostic[0] and "token=" not in diagnostic[0]
    assert "RESULT" not in diagnostic[0] and "ACK TEXT" not in diagnostic[0]


def test_submission_validation_exception_is_distinct_and_never_dispatches(caplog, monkeypatch):
    from hub._services import task_result_service

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("PRIVATE validation text")

    monkeypatch.setattr(task_result_service, "validate_submission", unavailable)
    bound = _Bound(AssertionError("must not dispatch"))
    caplog.set_level("WARNING", logger="bach.chat")
    answer = bach_tools.exec_tool(
        "task_manage", {"action": "submit_result", "task_id": 2217,
                        "result": "PRIVATE RESULT", "complete": True}, "full",
        worker_task_binding=bound, require_task_binding=True,
        allowed_tools={"task_manage"},
    )
    assert answer == "Taskoperation nicht bestätigt; Taskbindung prüfen."
    assert bound.dispatches == 0
    line = next(record.getMessage() for record in caplog.records
                if "bound_task_manage_denied" in record.getMessage())
    assert "stage=submission_exception" in line and "kind=other" in line
    assert "PRIVATE" not in line


def test_confirmed_self_check_denial_returns_only_fixed_guidance(caplog, monkeypatch):
    from hub._services import task_result_service

    monkeypatch.setattr(task_result_service, "validate_submission", lambda *_a, **_k: None)
    bound = _Bound(LeaseSelfCheckRequiredError("PRIVATE result and lease data"))
    caplog.set_level("WARNING", logger="bach.chat")
    answer = bach_tools.exec_tool(
        "task_manage", {"action": "submit_result", "task_id": 2217,
                        "result": "PRIVATE RESULT", "complete": True}, "full",
        worker_task_binding=bound, require_task_binding=True,
        allowed_tools={"task_manage"},
    )
    assert answer == LeaseSelfCheckRequiredError.user_message
    assert bound.dispatches == 1
    line = next(record.getMessage() for record in caplog.records
                if "bound_task_manage_denied" in record.getMessage())
    assert "kind=self_check_required" in line
    assert "PRIVATE" not in line and "lease" not in line


@pytest.mark.parametrize("args,expected", [
    ({"action": "list", "task_id": 0}, 'Für task_manage(action="list") nur action angeben; task_id weglassen.'),
    ({"action": "update", "task_id": 0, "result": "PRIVATE RESULT"},
     'Ergebnis getrennt mit task_manage(action="submit_result", task_id=<ID>, result=<Text>, complete=true) abgeben.'),
    ({"action": "update", "task_id": 0, "status": "pending", "description": "PRIVATE CONTENT"},
     'Status allein ändern: task_manage(action="update", task_id=<ID>, status=<pending|open|blocked>); Inhaltsfelder separat aktualisieren.'),
    ({"action": "update", "task_id": 0, "status": "blocked", "description": "PRIVATE CONTENT"},
     'Status allein ändern: task_manage(action="update", task_id=<ID>, status=<pending|open|blocked>); Inhaltsfelder separat aktualisieren.'),
    ({"action": "update", "task_id": 0, "status": "done", "description": "PRIVATE CONTENT", "result": "PRIVATE RESULT", "complete": True},
     'Fertiges Ergebnis mit submit_result und complete=true abgeben; Inhaltsfelder vorher separat aktualisieren.'),
    ({"action": "update", "task_id": 0, "status": "done", "complete": True},
     'Fertiges Ergebnis mit submit_result und complete=true abgeben; Inhaltsfelder vorher separat aktualisieren.'),
    ({"action": "update", "task_id": 0, "status": "completed", "complete": True},
     'Fertiges Ergebnis mit submit_result und complete=true abgeben; Inhaltsfelder vorher separat aktualisieren.'),
    ({"action": "decompose", "task_id": 0, "subtasks": [{"title": "Kind"}], "close_parnt": False},
     'Zerlegung: task_manage(action="decompose", task_id=<ID>, subtasks=[{"title":"Kind","description":"Arbeit"}], close_parent=false); keine fremden Felder. ' + TASK_CUT_RULE_SHORT),
    ({"action": "decompose", "task_id": 0, "subtasks": [{"title": "Kind"}], "close_parent": True},
     'Bei decompose close_parent=false verwenden; danach offenen Rest mit update(status="pending") zurückgeben.'),
])
def test_bound_local_argument_errors_are_actionable_without_leaking_or_mutation(
    binding, caplog, args, expected,
):
    args["task_id"] = binding.task_id
    before = binding._client.task_snapshot(binding.task_id)
    caplog.set_level("WARNING", logger="bach.chat")
    answer = bach_tools.exec_tool("task_manage", args, "full",
        worker_task_binding=binding, require_task_binding=True,
        allowed_tools={"task_manage"})
    assert answer == expected
    assert binding._client.task_snapshot(binding.task_id) == before
    binding.assert_active()
    diagnostic = [r.getMessage() for r in caplog.records
                  if "bound_task_manage_denied" in r.getMessage()]
    assert len(diagnostic) == 1
    assert "kind=argument_shape" in diagnostic[0]
    assert "PRIVATE" not in answer + diagnostic[0]


def test_bound_worker_can_correct_rejected_mixed_update_in_two_steps(binding):
    def run(args):
        return bach_tools.exec_tool("task_manage", args, "full",
            worker_task_binding=binding, require_task_binding=True,
            allowed_tools={"task_manage"})

    before = binding._client.task_snapshot(binding.task_id)
    denied = run({"action": "update", "task_id": binding.task_id,
                  "description": "Prüfbarer Teilstand", "status": "pending"})
    assert "Inhaltsfelder separat aktualisieren" in denied
    assert binding._client.task_snapshot(binding.task_id) == before
    content = run({"action": "update", "task_id": binding.task_id,
                   "description": "Prüfbarer Teilstand"})
    assert "aktualisiert: description" in content
    binding.assert_active()
    returned = run({"action": "update", "task_id": binding.task_id,
                    "status": "pending"})
    assert "aktualisiert: status" in returned
    after = binding._client.task_snapshot(binding.task_id)
    assert after["description"] == "Prüfbarer Teilstand" and after["status"] == "pending"
    assert binding._client.read(binding.task_id).leased is False
    assert binding._client.task_result_snapshot(binding.task_id)["result"] is None


def test_last_tool_round_with_zero_requests_preserves_ack_and_skips_ninth(
    tmp_path, monkeypatch,
):
    # Reuse the existing real durable-store/Ollama fixture in this test suite.
    from test_model_request_budget_runtime import (
        MODEL, _Binding, _new_budget, _runtime_session, _run_dispatch,
        _task_manage_tool, _tool_response,
    )

    _path, _worker, budget = _new_budget(tmp_path, monkeypatch)
    backend = OllamaBackend(base_url="http://127.0.0.1:11434", default_model=MODEL)
    binding = _Binding()
    runtime, session = _runtime_session(backend, budget, monkeypatch, binding=binding)
    runtime.max_tool_rounds = session.max_tool_rounds = 2
    calls = []

    async def fake_chat(messages, tools=None, think=True, model=None):
        calls.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        if len(calls) <= 6:
            return {"content": f"prelude {len(calls)}"}
        if len(calls) <= 8:
            return _tool_response("submit_result", result="reported, not accepted")
        raise AssertionError("no ninth backend request")

    backend.chat = fake_chat
    for _ in range(6):
        assert isinstance(_run_dispatch(runtime, session, tools=None), dict)

    monkeypatch.setattr(chat_runtime, "exec_tool", lambda *_a, **_k: "unconfirmed tool result")

    async def run_loop():
        token = runtime._compute_turn_context.set((session.chat_id, "background"))
        try:
            return await runtime._tool_loop_impl(
                [{"role": "user", "content": "isolated bound task"}], session,
                [_task_manage_tool()], backend=backend, model=MODEL)
        finally:
            runtime._compute_turn_context.reset(token)

    answer = asyncio.run(run_loop())
    assert isinstance(answer, chat_runtime.FailedAnswer)
    assert "Modellanfragenbudget ausgeschöpft" in answer
    assert len(calls) == 8 and budget.remaining() == 0
    assert [phase for _identity, phase, _fields in binding.tool_phases].count("acknowledged") == 2
    assert binding.invalidated is False and binding.closed is False
