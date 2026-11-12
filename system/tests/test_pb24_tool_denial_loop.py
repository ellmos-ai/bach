"""PB-24 (T-20261107-607312930): a denied tool action ends the tool round, it is not re-dispatched.

Measured 07.11.2026 on the Mac Studio: the BACH Telegram chat (a worker bound to a task) logged
runs of ``Tool [n] dispatch`` with ``bound_task_manage_denied`` and kept Ollama busy for hours.
A bound worker whose model re-sends the same denied call must stop with a visible reason, and
the number of denials and of tool calls per model answer is capped.
"""
from __future__ import annotations

import asyncio

from hub._services.chat.chat_runtime import ChatRuntime, ChatSession, FailedAnswer
from hub._services.chat.worker_tool_errors import ToolErrorText
from system.tests.test_chat_runtime_completion_reserve import (
    READ_TOOL, TASK_TOOL, _Backend, _Binding)


def _denied():
    return ToolErrorText("Ungültige Task-Werkzeugargumente.", code="invalid_task_arguments")


def _run(monkeypatch, answers, execute, *, max_rounds=12):
    """``answers``: one list of (name, args) tool calls per model answer; the last one repeats."""
    runtime = ChatRuntime(_Backend())
    runtime.hook_every = 999
    runtime.auto_continue = 0
    session = ChatSession()
    session.chat_id = "pb24-test"
    session.model = "test-model"
    session.allow_tools = True
    session.allowed_tools = {"task_manage", "read_file", "write_file"}
    session.worker_task_binding = _Binding()
    session.max_tool_rounds = max_rounds
    calls = []
    effects = []

    async def model(_session, selected_backend, selected_model, messages, *, tools=None, **kwargs):
        index = min(len(calls), len(answers) - 1)
        calls.append(index)
        batch = answers[index]
        if batch is None:
            return {"content": "fertig", "tool_calls": None}, selected_backend, selected_model
        return {"content": "", "tool_calls": [{"function": {"name": n, "arguments": a}}
                                              for n, a in batch],
                "prompt_tokens": 0}, selected_backend, selected_model

    def run_tool(name, arguments, mode, **kwargs):
        effects.append((name, dict(arguments)))
        return execute(name, arguments, len(effects))

    monkeypatch.setattr(runtime, "_chat_with_configured_fallbacks", model)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_args: None)
    monkeypatch.setattr("hub._services.chat.chat_runtime.exec_tool", run_tool)
    token = runtime._compute_turn_context.set((session.chat_id, "background"))
    try:
        answer = asyncio.run(runtime._tool_loop(
            [{"role": "user", "content": "Task #3781"}], session, tools=[READ_TOOL, TASK_TOOL]))
    finally:
        runtime._compute_turn_context.reset(token)
    return answer, calls, effects


def test_identical_denied_call_is_dispatched_once_then_the_round_ends_with_a_reason(monkeypatch):
    call = ("task_manage", {"action": "detail", "task_id": 999})
    answer, model_calls, effects = _run(monkeypatch, [[call]], lambda *_a: _denied())
    assert len(effects) == 1, "the denied call must not be dispatched a second time"
    assert isinstance(answer, FailedAnswer)
    assert answer.reason_code == "tool_denial_repeated"
    assert len(model_calls) == 2, "no further model request after the repeated denied call"


def test_many_different_denials_hit_a_cap(monkeypatch):
    answers = [[("task_manage", {"action": "detail", "task_id": 1000 + i})] for i in range(30)]
    answer, model_calls, effects = _run(monkeypatch, answers, lambda *_a: _denied())
    assert isinstance(answer, FailedAnswer)
    assert answer.reason_code == "tool_denial_limit"
    assert len(effects) <= 5


def test_a_corrected_call_after_one_denial_still_works(monkeypatch):
    answers = [[("task_manage", {"action": "detail", "task_id": 999})],
               [("task_manage", {"action": "detail", "task_id": 3781})], None]
    results = iter([_denied(), "Task #3781: offen"])
    answer, _calls, effects = _run(monkeypatch, answers, lambda *_a: next(results))
    assert len(effects) == 2
    assert not isinstance(answer, FailedAnswer)
    assert answer == "fertig"


def test_tool_calls_per_answer_are_capped_before_any_dispatch(monkeypatch):
    batch = [("read_file", {"path": f"datei{i}.txt"}) for i in range(40)]
    answer, _calls, effects = _run(monkeypatch, [batch], lambda *_a: "inhalt")
    assert effects == []
    assert isinstance(answer, FailedAnswer)
    assert answer.reason_code == "tool_call_limit"


def test_read_not_found_then_write_then_read_again_succeeds(monkeypatch):
    not_found = ToolErrorText(
        "Datei nicht gefunden.", code="tool_policy_denied", reason="resource_not_found"
    )
    answers = [
        [("read_file", {"path": "neu.txt"})],
        [("write_file", {"path": "neu.txt", "content": "hallo"})],
        [("read_file", {"path": "neu.txt"})],
        None,
    ]
    results = iter([not_found, "geschrieben", "hallo"])
    answer, _calls, effects = _run(monkeypatch, answers, lambda *_a: next(results))
    assert len(effects) == 3
    assert not isinstance(answer, FailedAnswer)
    assert answer == "fertig"


def test_six_resource_not_found_calls_in_a_row_do_not_hit_denial_cap(monkeypatch):
    not_found = ToolErrorText(
        "Datei nicht gefunden.", code="tool_policy_denied", reason="resource_not_found"
    )
    answers = [[("read_file", {"path": f"fehlt{i}.txt"})] for i in range(6)] + [None]
    answer, _calls, effects = _run(monkeypatch, answers, lambda *_a: not_found)
    assert len(effects) == 6
    assert not isinstance(answer, FailedAnswer)
    assert answer == "fertig"


def test_successful_call_clears_consecutive_denial_counter(monkeypatch):
    answers = [
        [("task_manage", {"action": "detail", "task_id": 1001})],
        [("task_manage", {"action": "detail", "task_id": 1002})],
        [("task_manage", {"action": "detail", "task_id": 1003})],
        [("task_manage", {"action": "detail", "task_id": 3781})],
        [("task_manage", {"action": "detail", "task_id": 2001})],
        [("task_manage", {"action": "detail", "task_id": 2002})],
        [("task_manage", {"action": "detail", "task_id": 2003})],
        None,
    ]
    results = iter([
        _denied(), _denied(), _denied(),
        "Task #3781: offen",
        _denied(), _denied(), _denied(),
    ])
    answer, _calls, effects = _run(monkeypatch, answers, lambda *_a: next(results))
    assert len(effects) == 7
    assert not isinstance(answer, FailedAnswer)
    assert answer == "fertig"


def test_four_real_denials_in_a_row_still_end_with_tool_denial_limit(monkeypatch):
    answers = [[("task_manage", {"action": "detail", "task_id": 1000 + i})] for i in range(4)] + [None]
    answer, _calls, effects = _run(monkeypatch, answers, lambda *_a: _denied())
    assert len(effects) == 4
    assert isinstance(answer, FailedAnswer)
    assert answer.reason_code == "tool_denial_limit"

