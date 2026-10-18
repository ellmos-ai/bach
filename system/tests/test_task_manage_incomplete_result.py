"""Reject explicit incomplete-result claims on a bound task completion."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub._services.chat import bach_tools
from hub._services.chat.bound_task_command import bound_task_command


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


def _run(args, binding=None):
    binding = binding or _Binding()
    reply = bach_tools.exec_tool("task_manage", args, "safe", worker_task_binding=binding,
                                 allowed_tools=["task_manage"])
    return reply, binding


INCOMPLETE_2230 = (
    "Forensik-Doku-Prüfung help_forensic (Paket 9caac91f422980d7bb3249918ddaed69904b334f):\n"
    "1. Quelle: system/hub/_services/recurring/config.json ist die einzige Quelldatei im Delta. "
    "0 weitere Dateien vorhanden.\n"
    "2. Workflow-Dokumente (help-forensic.md, help-expert-review.md, root-docs-review.md, "
    "docs-analyse.md) wurden konsultiert. Keine neuen Änderungen erbracht - nur Analyse gemäß Routinetext.\n"
    "3. Konfiguration: Routine fällig seit 2026-10-17 (last_run 2026-10-03T01:33:54). "
    "Wartungsdienst launchd org.ellmos.bach.docs-maintenance scheitert an SchedulerFacadeUnavailable "
    "(fehlendes last_success in ellmos-scheduler 0.3.3). Fix via PR #10 / Lead #2165 auf Mac erforderlich.\n"
    "4. Doku-Prüfung: docs/help/*.txt-Dateien konnten nicht erfolgreich geprüft werden "
    "(formatter_capability_unverified; read_file fehlt). Keine Abweichungen zu dokumentieren, "
    "da kein Vollzug der Prüfung möglich ist.\n"
    "Fazit: Die Pflichtarbeit ist unvollständig erfüllt - die forensische Analyse kann durch den "
    "fehlenden Wartungsdienst-Vollzug nicht durchgeführt werden. Der lokale Modelllauf "
    "(qwen3.5:4b) wurde nicht realisiert, weil der native Dienst nicht funktioniert."
)


@pytest.mark.parametrize("result", [
    "Die Aufgabe ist unvollständig.",
    "Pflichtarbeit ist offen.",
    INCOMPLETE_2230,
    "Keine Pflichtarbeit ist offen. Die Aufgabe ist unvollständig.",
    "No required work is outstanding. The required work remains incomplete.",
    '{"status":"incomplete"}',
    '{"complete": false}',
])
def test_explicit_incomplete_result_is_detected_even_after_positive_context(result):
    assert bach_tools._result_explicitly_incomplete(result)


@pytest.mark.parametrize("result", [
    "Die Aufgabe ist vollständig erledigt.",
    "Keine Pflichtarbeit ist offen.",
    "No required work is outstanding.",
    '{"status":"complete","complete":true}',
])
def test_complete_or_negated_result_is_not_classified_as_incomplete(result):
    assert not bach_tools._result_explicitly_incomplete(result)


@pytest.mark.parametrize("action", ["submit_result", "update"])
def test_complete_true_is_refused_when_result_says_required_work_is_incomplete(action):
    args = {"action": action, "task_id": 7, "result": INCOMPLETE_2230, "complete": True}
    if action == "update":
        args["status"] = "done"
    reply, binding = _run(args)
    assert reply == bach_tools._INCOMPLETE_RESULT_HINT
    assert binding.calls == []


def test_complete_false_preserves_the_existing_partial_state_path():
    reply, binding = _run({"action": "submit_result", "task_id": 7,
                           "result": "Aufgabe ist unvollständig; Teilstand gespeichert.", "complete": False})
    assert "pending" in reply and "kein Abschluss" in reply
    assert len(binding.calls) == 2
    assert binding.calls[0]["action"] == "update"
    assert "Aufgabe ist unvollständig" in binding.calls[0]["description"]
    assert binding.calls[1] == {"action": "update", "task_id": 7, "status": "pending"}


def test_review_child_verdict_keeps_its_existing_bypass():
    binding = _Binding()
    binding._review_grant = object()
    reply, binding = _run({"action": "submit_result", "task_id": 7,
                           "result": '{"status":"incomplete"}'}, binding)
    assert reply == "ok"
    assert binding.calls == [{"action": "submit_result", "task_id": 7,
                              "result": '{"status":"incomplete"}'}]


@pytest.mark.parametrize("tail", [
    ["--result", "fertig"],
    ["--result", "fertig", "--complete=true", "--complete=false"],
    ["--result", "fertig", "--complete=maybe"],
    ["--result", "fertig", "--complete"],
    ["--result", "fertig", "--complete=true", "--unexpected"],
])
def test_cli_rejects_missing_duplicate_or_malformed_completion_arguments_before_dispatch(tail):
    binding = _Binding()
    with pytest.raises(ValueError):
        bound_task_command("done", ["7", *tail], binding)
    assert binding.calls == []


def test_cli_rejects_contradictory_complete_result_before_dispatch():
    binding = _Binding()
    with pytest.raises(ValueError, match="Ergebnis nennt offene Pflichtarbeit"):
        bound_task_command("done", ["7", "--result", INCOMPLETE_2230, "--complete=true"], binding)
    assert binding.calls == []


def test_cli_partial_result_uses_existing_open_task_path():
    binding = _Binding()
    reply = bound_task_command("done", ["7", "--result", "Die Aufgabe ist unvollständig.",
                                         "--complete=false"], binding)
    assert "pending" in reply
    assert [call["action"] for call in binding.calls] == ["update", "update"]
