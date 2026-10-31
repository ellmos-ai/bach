"""A bound worker spends its remaining tool rounds on a real task handoff."""
from __future__ import annotations

import asyncio

import pytest

from hub._services.chat.chat_runtime import ChatRuntime, ChatSession, FailedAnswer
from hub._services.chat.worker_tool_trace import TraceIdentity


TASK_TOOL = {"type": "function", "function": {"name": "task_manage", "parameters": {
    "type": "object", "properties": {"action": {"type": "string", "enum": [
        "list", "detail", "update", "decompose", "submit_result", "done"]}}}}}
READ_TOOL = {"type": "function", "function": {"name": "read_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}}}}


class _Binding:
    task_id = 2217
    completed_task_ids = ()
    closed = False

    def __init__(self, *, review=False):
        self._review_grant = object() if review else None
        self.phases = []

    def trace_tool_started(self, *, source, request_id, tool_name, arguments_sha256):
        self.phases.append(("started", tool_name))
        return TraceIdentity(self.task_id, 4, "worker-test@host", "generation-test",
                             "a" * 64, request_id, source, tool_name)

    def trace_tool_phase(self, identity, phase, *, receipt_id=None, result_sha256=None):
        self.phases.append((phase, identity.tool_name))
        return {"accepted": True}

    def invalidate(self, _reason=None):
        raise AssertionError("A deliberately blocked tool must not invalidate the binding")


class _Backend:
    def get_default_model(self):
        return "test-model"

    def tool_response_message(self, content, tool_call_id=""):
        return {"role": "tool", "content": content}


def _run(monkeypatch, requested, *, max_rounds=2, grants=None, review=False,
         offered=None, bound=True, context_full=False):
    backend = _Backend()
    runtime = ChatRuntime(backend)
    runtime.hook_every = 999
    runtime.auto_continue = 3  # The final reserve must not add free-form turns.
    session = ChatSession()
    session.chat_id = "bound-task-test"
    session.model = "test-model"
    session.allow_tools = True
    session.allowed_tools = grants if grants is not None else {"task_manage", "read_file"}
    binding = _Binding(review=review) if bound else None
    session.worker_task_binding = binding
    session.max_tool_rounds = max_rounds
    if context_full:
        runtime.handoff_percent = 1

        async def unexpected_handoff(*_args, **_kwargs):
            raise AssertionError("Die Abschlussreserve darf keine zusätzliche Übergabe starten")

        monkeypatch.setattr(runtime, "_handoff", unexpected_handoff)
    calls = []
    effects = []

    async def model(_session, selected_backend, selected_model, messages, *, tools=None, **kwargs):
        calls.append((tools, [dict(message) for message in messages], kwargs))
        if len(calls) == 1:
            return {"content": "", "tool_calls": [{"function": {
                "name": requested[0], "arguments": requested[1]}}],
                "prompt_tokens": 50000 if context_full else 0}, selected_backend, selected_model
        if tools is None:
            return {"content": "Nur Text, keine bestätigte Abgabe", "tool_calls": None}, selected_backend, selected_model
        return {"content": "Zwischenstand bleibt offen", "tool_calls": None}, selected_backend, selected_model

    def execute(name, arguments, mode, **kwargs):
        effects.append((name, arguments))
        return "Taskwirkung bestätigt"

    monkeypatch.setattr(runtime, "_chat_with_configured_fallbacks", model)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_args: None)
    monkeypatch.setattr("hub._services.chat.chat_runtime.exec_tool", execute)
    token = runtime._compute_turn_context.set((session.chat_id, "background"))
    try:
        answer = asyncio.run(runtime._tool_loop(
            [{"role": "user", "content": "Task #2217 prüfen"}], session,
            tools=[READ_TOOL, TASK_TOOL] if offered is None else offered,
        ))
    finally:
        runtime._compute_turn_context.reset(token)
    return answer, calls, effects, binding


@pytest.mark.parametrize("name,arguments", [
    ("read_file", {"path": "noch-eine-datei.txt"}),
    ("task_manage", {"action": "detail", "task_id": 2217}),
    ("task_manage", {"action": "submit_result", "task_id": 999, "result": "fremd"}),
    ("task_manage", {"action": "done", "task_id": 2217, "result": "unbelegt"}),
])
def test_stubborn_backend_cannot_use_last_round_for_research_or_unapproved_action(
        monkeypatch, name, arguments):
    answer, calls, effects, binding = _run(monkeypatch, (name, arguments), max_rounds=1)
    assert effects == []
    assert len(calls) == 2  # Existing final text call; no extra tool round.
    assert [item["function"]["name"] for item in calls[0][0]] == ["task_manage"]
    assert "Abschlussreserve" in str(calls[0][1]) or "ABSCHLUSSRESERVE" in str(calls[0][1])
    assert "BLOCKIERT" in str(calls[1][1])
    assert binding.phases == [("started", name), ("returned", name), ("acknowledged", name)]
    assert "keine bestätigte Abgabe" in answer


@pytest.mark.parametrize("action,arguments", [
    ("submit_result", {"action": "submit_result", "task_id": 2217,
                       "result": "Belegter Zwischenstand, gesondert prüfen"}),
    ("update", {"action": "update", "task_id": 2217,
                "description": "Prüfung begonnen; eine Quelle ist offen"}),
    ("decompose", {"action": "decompose", "task_id": 2217,
                   "subtasks": [{"title": "Quellenprüfung", "description": "Konkreter Beleg fehlt"}],
                   "close_parent": False}),
])
def test_final_round_retains_only_existing_task_progress_authority(monkeypatch, action, arguments):
    _answer, calls, effects, binding = _run(monkeypatch, ("task_manage", arguments))
    assert len(calls) == 2
    assert effects == [("task_manage", arguments)]
    assert binding.phases == [("started", "task_manage"), ("returned", "task_manage"),
                              ("acknowledged", "task_manage")]
    assert calls[0][0][0]["function"]["parameters"]["properties"]["action"]["enum"] == [
        "submit_result", "update", "decompose"]
    assert action in calls[0][0][0]["function"]["parameters"]["properties"]["action"]["enum"]
    assert READ_TOOL["function"]["name"] == "read_file"  # No mutation of source schemas.


def test_review_grant_keeps_only_own_submit_and_no_unoffered_tool(monkeypatch):
    _answer, calls, effects, binding = _run(
        monkeypatch, ("task_manage", {"action": "update", "task_id": 2217,
                                      "description": "unzulässig"}), review=True)
    assert effects == []
    assert calls[0][0][0]["function"]["parameters"]["properties"]["action"]["enum"] == ["submit_result"]
    assert binding.phases[-1] == ("acknowledged", "task_manage")


def test_model_cannot_invent_task_manage_when_only_read_tool_was_offered(monkeypatch):
    _answer, calls, effects, binding = _run(
        monkeypatch, ("task_manage", {"action": "submit_result", "task_id": 2217,
                                      "result": "unbelegte Behauptung"}), offered=[READ_TOOL])
    assert calls[0][0] == []
    assert effects == []
    assert binding.phases == [("started", "task_manage"), ("returned", "task_manage"),
                              ("acknowledged", "task_manage")]


def test_missing_task_grant_is_not_added_at_actual_backend_boundary():
    runtime = ChatRuntime(_Backend())
    session = ChatSession()
    session.allow_tools = True
    session.allowed_tools = {"read_file"}
    session.worker_task_binding = _Binding()
    tools = runtime._bound_worker_tools_for_request(
        session, _Backend(), enabled=True, completion_reserve=True)
    assert tools == []


def test_missing_task_grant_does_not_promise_or_execute_an_unavailable_submit(monkeypatch):
    _answer, calls, effects, _binding = _run(
        monkeypatch, ("read_file", {"path": "further-source.py"}), grants={"read_file"})
    assert calls[0][0] == []
    assert "Task-Abgabewerkzeug ist nicht freigegeben" in str(calls[0][1])
    assert effects == []


def test_ungranted_invented_write_is_blocked_and_traced_in_reserve(monkeypatch):
    answer, calls, effects, binding = _run(
        monkeypatch, ("write_file", {"path": "unexpected.txt", "content": "unzulässig"}),
        grants={"task_manage"}, max_rounds=1)
    assert effects == []
    assert "BLOCKIERT" in str(calls[1][1])
    assert binding.phases == [("started", "write_file"), ("returned", "write_file"),
                              ("acknowledged", "write_file")]
    assert "keine bestätigte Abgabe" in answer


def test_unbound_normal_chat_keeps_original_round_warning(monkeypatch):
    _answer, calls, effects, binding = _run(
        monkeypatch, ("read_file", {"path": "source.txt"}), max_rounds=3,
        bound=False)
    assert binding is None
    assert effects == [("read_file", {"path": "source.txt"})]
    assert "Gehe JETZT direkt zur Code-Änderung (edit_file / write_file) über" in str(calls[1][1])
    assert "Wenn du die Aufgabe in dieser Session nicht mehr fertigstellen kannst" in str(calls[1][1])


def test_full_context_in_reserve_fails_without_handoff_or_tool_effect(monkeypatch):
    answer, calls, effects, binding = _run(
        monkeypatch, ("task_manage", {"action": "submit_result", "task_id": 2217,
                                      "result": "unbelegt"}),
        max_rounds=1, context_full=True)
    assert isinstance(answer, FailedAnswer)
    assert "Kontextfenster in der Abschlussreserve erschöpft" in str(answer)
    # The worker returns the task with this code and keeps working.
    assert answer.reason_code == "completion_reserve_context_exhausted"
    assert len(calls) == 1
    assert effects == []
    assert binding.phases == []


class _Budget:
    def __init__(self, remaining):
        self._remaining = remaining

    def remaining(self):
        return self._remaining


@pytest.mark.parametrize("read_chars, budget, handoff_expected", [
    (900, None, True),   # large last read: hand off once before entering the reserve
    (30, None, False),   # estimate stays below the threshold: no extra model request
    (900, 2, False),     # budget reserve: no handoff, unchanged fail-closed reserve
])
def test_large_last_normal_round_hands_off_before_entering_reserve(
        monkeypatch, read_chars, budget, handoff_expected):
    # BACH #2226: the last normal round's read results first appear in the reserve
    # prompt; without a handoff before entry the reserve fails with a full context.
    runtime = ChatRuntime(_Backend())
    runtime.hook_every = 999
    runtime.auto_continue = 0
    runtime.handoff_percent = 50
    monkeypatch.setattr(runtime, "get_model_context_limit", lambda *_args, **_kwargs: 1000)
    session = ChatSession()
    session.chat_id = "bound-task-test"
    session.model = "test-model"
    session.allow_tools = True
    session.allowed_tools = {"task_manage", "read_file"}
    binding = _Binding()
    session.worker_task_binding = binding
    session.max_tool_rounds = 3
    session.model_request_budget = _Budget(budget) if budget is not None else None
    order, effects = [], []
    update = {"action": "update", "task_id": 2217, "description": "Teilstand: Quelle gelesen"}

    async def handoff(*_args, **_kwargs):
        order.append("handoff")
        return [{"role": "user", "content": "Übergabe: eine Quelle gelesen, Befund offen"}]

    async def model(_session, selected_backend, selected_model, messages, *, tools=None, **kwargs):
        order.append("model")
        calls = order.count("model")
        if calls == 1:
            return {"content": "", "prompt_tokens": 400, "tool_calls": [{"function": {
                "name": "read_file", "arguments": {"path": "quelle.md"}}}]}, selected_backend, selected_model
        if calls == 2:
            # The reserve prompt still carries a large read unless a handoff came first.
            full = read_chars > 300 and "handoff" not in order
            return {"content": "", "prompt_tokens": 700 if full else 100, "tool_calls": [{"function": {
                "name": "task_manage", "arguments": update}}]}, selected_backend, selected_model
        return {"content": "Zwischenstand gesichert", "tool_calls": None}, selected_backend, selected_model

    def execute(name, arguments, mode, **kwargs):
        effects.append((name, arguments))
        return "x" * read_chars if name == "read_file" else "Taskwirkung bestätigt"

    monkeypatch.setattr(runtime, "_handoff", handoff)
    monkeypatch.setattr(runtime, "_chat_with_configured_fallbacks", model)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_args: None)
    monkeypatch.setattr("hub._services.chat.chat_runtime.exec_tool", execute)
    token = runtime._compute_turn_context.set((session.chat_id, "background"))
    try:
        answer = asyncio.run(runtime._tool_loop(
            [{"role": "user", "content": "Task #2217 prüfen"}], session, tools=[READ_TOOL, TASK_TOOL]))
    finally:
        runtime._compute_turn_context.reset(token)
    assert order.count("handoff") == (1 if handoff_expected else 0)
    if budget is not None:
        # Unchanged contract: the budget reserve is active from the first request,
        # blocks the read, and a full prompt there fails without any effect.
        assert isinstance(answer, FailedAnswer)
        assert "Kontextfenster in der Abschlussreserve erschöpft" in str(answer)
        assert effects == []
        return
    assert not isinstance(answer, FailedAnswer), answer
    assert order[:3] == (["model", "handoff", "model"] if handoff_expected else ["model", "model", "model"])
    assert effects == [("read_file", {"path": "quelle.md"}), ("task_manage", update)]
