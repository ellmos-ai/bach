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
from hub._services.task_lease_client import LeaseDeniedError, LeaseSelfCheckRequiredError
from hub._services.llm.model_backend import OllamaBackend


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
                        "result": "PRIVATE RESULT do-not-log"}, "full",
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
                        "result": "PRIVATE RESULT"}, "full",
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
                        "result": "PRIVATE RESULT"}, "full",
        worker_task_binding=bound, require_task_binding=True,
        allowed_tools={"task_manage"},
    )
    assert answer == LeaseSelfCheckRequiredError.user_message
    assert bound.dispatches == 1
    line = next(record.getMessage() for record in caplog.records
                if "bound_task_manage_denied" in record.getMessage())
    assert "kind=self_check_required" in line
    assert "PRIVATE" not in line and "lease" not in line


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
