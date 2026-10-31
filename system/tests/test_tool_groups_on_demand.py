"""A bound worker with request_tools starts on the core set and opens groups within allowed_tools.

Local worker harness (25.10.2026): tool descriptions cost Buddha 1 391 tokens for three
tools, 2 225 for its eleven and 4 256 for all 28 in a 16 384-token window.
"""
from __future__ import annotations

import asyncio

from hub._services.chat.chat_runtime import ChatRuntime, ChatSession
from hub._services.chat.worker_tool_trace import TraceIdentity

BUDDHA = {"task_manage", "start_task_worktree", "read_file", "search_text", "list_directory",
          "file_info", "edit_file", "write_file", "create_directory", "execute_command", "finish_task"}
CORE = {"task_manage", "read_file", "search_text", "list_directory"}


class _Binding:
    task_id = 2551
    completed_task_ids = ()
    closed = False
    _review_grant = None

    def assert_active(self):
        return None

    def trace_tool_started(self, *, source, request_id, tool_name, arguments_sha256):
        return TraceIdentity(self.task_id, 4, "worker-test@host", "generation-test",
                             "a" * 64, request_id, source, tool_name)

    def trace_tool_phase(self, identity, phase, *, receipt_id=None, result_sha256=None):
        return {"accepted": True}

    def invalidate(self):
        raise AssertionError("a denied group request must not invalidate the binding")


class _Backend:
    def get_default_model(self):
        return "qwen3.8:27b-mlx"

    def tool_response_message(self, content, tool_call_id=""):
        return {"role": "tool", "content": content}


def _session(grants):
    session = ChatSession()
    session.chat_id = "buddha-test"
    session.mode = "full"
    session.allow_tools = True
    session.allowed_tools = grants
    session.worker_task_binding = _Binding()
    session.requested_tool_groups = set()
    return session


def _names(tools):
    return {tool["function"]["name"] for tool in tools}


def _request_tool(tools):
    return next(tool for tool in tools if tool["function"]["name"] == "request_tools")


def test_core_set_offers_only_groups_within_allowed_tools():
    runtime = ChatRuntime(_Backend())
    tools = runtime._bound_worker_tools_for_request(
        _session(BUDDHA | {"request_tools"}), _Backend(), enabled=True)
    assert _names(tools) == CORE | {"request_tools"}
    meta = _request_tool(tools)["function"]
    assert meta["parameters"]["properties"]["group"]["enum"] == ["dateien", "lieferung", "ausfuehren"]
    assert "dateien: Dateien schreiben (write_file, edit_file, create_directory, file_info)" in meta["description"]
    assert "web" not in meta["description"]
    # Reserve narrowing is unchanged and drops the meta tool with everything else.
    reserve = runtime._bound_worker_tools_for_request(
        _session(BUDDHA | {"request_tools"}), _Backend(), enabled=True, completion_reserve=True)
    assert _names(reserve) == {"task_manage"}


def test_without_request_tools_grant_the_schema_is_unchanged():
    runtime = ChatRuntime(_Backend())
    tools = runtime._bound_worker_tools_for_request(_session(BUDDHA), _Backend(), enabled=True)
    assert _names(tools) == BUDDHA


def test_meta_tool_disappears_once_every_granted_group_is_open():
    runtime = ChatRuntime(_Backend())
    session = _session(BUDDHA | {"request_tools"})
    session.requested_tool_groups = {"dateien", "lieferung", "ausfuehren"}
    tools = runtime._bound_worker_tools_for_request(session, _Backend(), enabled=True)
    assert _names(tools) == BUDDHA


def test_requested_group_opens_from_next_round_and_never_beyond_allowed_tools(monkeypatch):
    backend = _Backend()
    runtime = ChatRuntime(backend)
    runtime.hook_every = 999
    session = _session(BUDDHA | {"request_tools"})
    session.max_tool_rounds = 10
    offered, results, effects = [], [], []
    script = [
        [("request_tools", {"group": "dateien"}), ("request_tools", {"group": "web"})],
        [("request_tools", {"group": "lieferung"})],
    ]

    async def model(_session, selected_backend, selected_model, messages, *, tools=None, **kwargs):
        # The real request path rebuilds the schema at the backend boundary.
        offered.append(_names(runtime._bound_worker_tools_for_request(
            session, selected_backend, enabled=True)))
        results.extend(m["content"] for m in messages if m.get("role") == "tool")
        if script:
            calls = [{"function": {"name": name, "arguments": args}} for name, args in script.pop(0)]
            return {"content": "", "tool_calls": calls, "prompt_tokens": 10}, selected_backend, selected_model
        return {"content": "fertig", "tool_calls": None, "prompt_tokens": 10}, selected_backend, selected_model

    def execute(name, arguments, mode, **kwargs):
        effects.append(name)
        return "ok"

    monkeypatch.setattr(runtime, "_chat_with_configured_fallbacks", model)
    monkeypatch.setattr(runtime, "_worker_backend_gate", lambda *_args: None)
    monkeypatch.setattr("hub._services.chat.chat_runtime.exec_tool", execute)
    token = runtime._compute_turn_context.set((session.chat_id, "background"))
    try:
        answer = asyncio.run(runtime._tool_loop(
            [{"role": "user", "content": "Task #2551"}], session, tools=[{"function": {"name": "read_file"}}]))
    finally:
        runtime._compute_turn_context.reset(token)

    assert answer == "fertig"
    assert offered[0] == CORE | {"request_tools"}
    assert offered[1] == CORE | {"request_tools", "write_file", "edit_file", "create_directory", "file_info"}
    assert offered[2] == BUDDHA - {"execute_command"} | {"request_tools"}
    assert all(not name & {"move_file", "web_fetch", "web_search", "safe_shell"} for name in offered)
    assert "Ab der nächsten Runde verfügbar: write_file, edit_file, create_directory, file_info" in results
    assert any(r.startswith("BLOCKIERT: Werkzeuggruppe ist nicht verfügbar.") for r in results)
    assert effects == []  # request_tools never reaches the file/tool dispatcher


def test_slot_validation_accepts_the_meta_tool_but_still_rejects_unknown_tools():
    from hub._services.chat.slots_config import _validated_core_edits

    assert "request_tools" in _validated_core_edits(
        {"allowed_tools": sorted(BUDDHA | {"request_tools"})})["allowed_tools"]
    try:
        _validated_core_edits({"allowed_tools": ["task_manage", "request_everything"]})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown tool names must stay rejected")
