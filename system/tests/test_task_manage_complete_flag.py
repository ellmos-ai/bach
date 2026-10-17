"""BACH #2210: a bound model must state complete=true/false when it submits."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub._services.chat import bach_tools


class _Binding:
    task_id = 7

    def __init__(self):
        self.calls = []

    def assert_active(self):
        return None

    def mark_tool_dispatch(self):
        return None

    def task_snapshot(self):
        return {"description": "Originalauftrag", "result_max_chars": None}

    def execute_task_manage(self, args, _dispatch_marked=False):
        self.calls.append(dict(args))
        return "ok"

    def capture_confirmed_scope(self):
        return None


def _run(args):
    binding = _Binding()
    reply = bach_tools.exec_tool("task_manage", args, "safe",
                                 worker_task_binding=binding, allowed_tools=["task_manage"])
    return reply, binding.calls


@pytest.mark.parametrize("args", [
    {"action": "submit_result", "task_id": 7, "result": "Fertig"},
    {"action": "submit_result", "task_id": 7, "result": "Fertig", "complete": "true"},
    {"action": "update", "task_id": 7, "status": "done", "result": "Fertig"},
])
def test_missing_or_non_boolean_complete_is_refused_with_a_concrete_hint(args):
    reply, calls = _run(args)
    assert reply == bach_tools._COMPLETE_FLAG_HINT and calls == []


def test_complete_true_submits_without_the_flag():
    reply, calls = _run({"action": "submit_result", "task_id": 7, "result": "Fertig", "complete": True})
    assert reply == "ok"
    assert calls == [{"action": "submit_result", "task_id": 7, "result": "Fertig"}]


def test_complete_false_keeps_the_task_text_appends_the_partial_state_and_returns_it():
    reply, calls = _run({"action": "submit_result", "task_id": 7,
                         "result": "Nur config.json gelesen; Rest offen.", "complete": False})
    assert "pending" in reply and "kein Abschluss" in reply
    assert len(calls) == 2
    assert calls[0]["action"] == "update" and calls[0]["description"].startswith("Originalauftrag\n\nTeilstand (Worker, ")
    assert calls[0]["description"].endswith("Nur config.json gelesen; Rest offen.")
    assert calls[1] == {"action": "update", "task_id": 7, "status": "pending"}
    assert not any(call["action"] == "submit_result" for call in calls)


def test_update_done_alias_with_complete_true_reaches_the_binding_unchanged():
    reply, calls = _run({"action": "update", "task_id": 7, "status": "done", "result": "Fertig", "complete": True})
    assert reply == "ok" and calls == [{"action": "update", "task_id": 7, "status": "done", "result": "Fertig"}]


def test_schema_offers_the_complete_flag():
    schema = next(tool for tool in bach_tools.TOOLS_SAFE if tool["function"]["name"] == "task_manage")
    assert schema["function"]["parameters"]["properties"]["complete"]["type"] == "boolean"
