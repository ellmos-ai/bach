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
    assert "Nur config.json gelesen; Rest offen." in calls[0]["description"]
    assert calls[1] == {"action": "update", "task_id": 7, "status": "pending"}
    assert not any(call["action"] == "submit_result" for call in calls)


def test_update_done_alias_with_complete_true_reaches_the_binding_unchanged():
    reply, calls = _run({"action": "update", "task_id": 7, "status": "done", "result": "Fertig", "complete": True})
    assert reply == "ok" and calls == [{"action": "update", "task_id": 7, "status": "done", "result": "Fertig"}]


def test_review_children_submit_their_verdict_without_the_flag():
    # A review child submits a structured verdict, not work; the flag is not theirs (review path checks exact args).
    binding = _Binding()
    binding._review_grant = object()
    reply = bach_tools.exec_tool("task_manage", {"action": "submit_result", "task_id": 7, "result": '{"status":"approved"}'},
                                 "safe", worker_task_binding=binding, allowed_tools=["task_manage"])
    assert reply == "ok" and binding.calls == [{"action": "submit_result", "task_id": 7, "result": '{"status":"approved"}'}]


def test_update_done_alias_with_complete_false_still_validates_the_result():
    reply, calls = _run({"action": "update", "task_id": 7, "status": "done", "result": "  ", "complete": False})
    # #379 contract: result validation answers with the typed neutral text.
    assert "Taskergebnis ist ungültig" in reply and calls == []


def test_partial_state_replaces_the_previous_partial_block():
    previous = _saved_partial("Original", "alt")
    description = _saved_partial(previous, "neu")
    assert description.startswith("Original\n\nTeilstand (Worker, ")
    assert "neu" in description
    assert description.count("Teilstand (Worker, ") == 1 and "alt" not in description


def _saved_partial(description, result):
    binding = _Binding()
    binding.task_snapshot = lambda: {"description": description, "result_max_chars": None}
    bach_tools._return_partial_state(binding, {"task_id": 7, "result": result})
    assert binding.calls[1] == {"action": "update", "task_id": 7, "status": "pending"}
    return binding.calls[0]["description"]


@pytest.mark.parametrize("legacy", [False, True])
def test_partial_replacement_preserves_later_child_ids_and_notes(legacy):
    previous = ("Original\n\nTeilstand (Worker, 2026-10-17 20:00, complete=false):\nalt"
                if legacy else _saved_partial("Original", "alt"))
    suffix = "\n[In 2 Teilaufgaben zerlegt: [8, 9]]\nNachtrag: Ergänzung für die nächste Bearbeitung."
    description = _saved_partial(previous + suffix, "neu")
    assert suffix in description
    if legacy:
        # The end of the old free-form block is unknown: preserve it once.
        assert previous in description
    else:
        assert "alt" not in description
    latest = _saved_partial(description, "aktuell")
    assert suffix in latest and "neu" not in latest
    assert latest.count("Teilstand (Worker, ") == (2 if legacy else 1)


def test_partial_replacement_treats_marker_text_in_result_as_payload():
    nested = _saved_partial("", "Markerbeispiel")
    previous = _saved_partial("Original", "Zitat:\n" + nested + "\nDanach folgt noch echter Teilstand.")
    suffix = "\n[In 2 Teilaufgaben zerlegt: [8, 9]]"
    description = _saved_partial(previous + suffix, "aktuell: Änderungen noch offen")
    assert description.startswith("Original" + suffix)
    assert "Markerbeispiel" not in description and "Danach folgt" not in description
    assert description.count("Teilstand (Worker, ") == 1


def test_copied_sealed_block_in_later_notes_is_not_removed():
    previous = _saved_partial("Original", "alter Stand")
    note = "\nOperatornotiz: Beispiel einer früheren Antwort" + previous[len("Original"):]
    description = _saved_partial(previous + note, "Zwischenstand")
    assert description.startswith(previous + note)
    latest = _saved_partial(description, "Aktueller Stand")
    assert latest.startswith(previous + note)
    assert "Zwischenstand" not in latest


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("replacement", ["neuer Stand", "vom Nutzer ergänzter Stand"])
def test_changed_partial_block_is_preserved_when_its_boundary_cannot_be_verified(nested, replacement):
    result = "alter Stand" + (_saved_partial("", "Markerbeispiel") if nested else "")
    previous = _saved_partial("Original", result)
    changed = previous.replace("alter Stand", replacement)
    assert changed in _saved_partial(changed, "neuer Stand")


@pytest.mark.parametrize("tail, expected", [
    (["--result", "Fertig"], "--complete=true"),            # flag missing: refused with the hint
    (["--result", "Fertig", "--complete=true"], "ok"),      # submission proceeds
    (["--result", "Teil", "--complete=false"], "pending"),  # partial state, task returned open
    (["--result", "  ", "--complete=false"], "Ergebnis"),    # empty partial state is refused before storing
])
def test_bach_command_done_needs_the_same_flag(tail, expected):
    from hub._services.chat.bound_task_command import bound_task_command
    binding = _Binding()
    try:
        reply = bound_task_command("done", ["7", *tail], binding)
    except ValueError as exc:
        reply = str(exc)
    assert expected in reply
    if expected == "ok":
        assert binding.calls == [{"action": "submit_result", "task_id": 7, "result": "Fertig"}]
    if expected == "pending":
        assert [call["action"] for call in binding.calls] == ["update", "update"]


def test_schema_offers_the_complete_flag():
    schema = next(tool for tool in bach_tools.TOOLS_SAFE if tool["function"]["name"] == "task_manage")
    assert schema["function"]["parameters"]["properties"]["complete"]["type"] == "boolean"
