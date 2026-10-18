"""Bound worker completion flag keeps unfinished work out of done/review."""
import pytest

pytest_plugins = (
    "system.tests.test_task_lease_client",
    "system.tests.test_worker_lease_binding",
)

from hub._services.chat import bach_tools
from hub._services.chat.bound_task_command import bound_task_command


@pytest.mark.parametrize("result", [
    "Die Pflichtarbeit ist unvollständig erfüllt; der Pflichtteil ist noch offen.",
    "Die Aufgabe ist unvollständig.",
    "The required work is not yet complete.",
    '{"status":"incomplete","complete":false}',
    (
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
    ),
    "No required work is incomplete. The required work remains incomplete.",
])
def test_complete_true_rejects_explicit_incomplete_result_without_dispatch(binding, result):
    response = bach_tools.exec_tool(
        "task_manage",
        {"action": "submit_result", "task_id": binding.task_id, "result": result, "complete": True},
        "safe",
        worker_task_binding=binding,
    )
    assert isinstance(response, bach_tools.ToolErrorText)
    assert response._code == "invalid_task_result"
    assert "unvollständig" not in str(response)
    assert not binding.closed
    assert not binding.completed_task_ids
    assert not binding.reviewed_task_ids


def test_complete_false_persists_sealed_partial_state_and_returns_task_pending(binding):
    response = bach_tools.exec_tool(
        "task_manage",
        {"action": "submit_result", "task_id": binding.task_id,
         "result": "Eine von drei Prüfungen abgeschlossen.", "complete": False},
        "safe",
        worker_task_binding=binding,
    )
    assert "Teilstand gespeichert" in response
    assert binding.closed
    assert binding._client.task_snapshot(binding.task_id)["status"] == "pending"
    description = binding.task_snapshot()["description"]
    assert "Eine von drei Prüfungen abgeschlossen." in description
    assert "bach-worker-partial:v1" in description
    assert not binding.completed_task_ids
    assert not binding.reviewed_task_ids


@pytest.mark.parametrize("result", [
    "All required work is complete.",
    "No required work remains incomplete.",
    "Die Pflichtarbeit ist nicht unvollständig.",
])
def test_complete_true_accepts_non_incomplete_and_explicit_negation(binding, result):
    response = bach_tools.exec_tool(
        "task_manage",
        {"action": "submit_result", "task_id": binding.task_id, "result": result, "complete": True},
        "safe",
        worker_task_binding=binding,
    )
    assert "wartet in Review" in response
    assert binding.closed
    assert binding.reviewed_task_ids == (binding.task_id,)


@pytest.mark.parametrize("complete", [None, "true", 1])
def test_completion_requires_boolean_complete_flag(binding, complete):
    response = bach_tools.exec_tool(
        "task_manage",
        {"action": "done", "task_id": binding.task_id, "result": "Ergebnis", "complete": complete},
        "safe",
        worker_task_binding=binding,
    )
    assert isinstance(response, bach_tools.ToolErrorText)
    assert response._code == "invalid_task_arguments"
    assert not binding.closed
    assert not binding.completed_task_ids
    assert not binding.reviewed_task_ids


def test_completion_requires_complete_flag(binding):
    response = bach_tools.exec_tool(
        "task_manage",
        {"action": "done", "task_id": binding.task_id, "result": "Ergebnis"},
        "safe",
        worker_task_binding=binding,
    )
    assert isinstance(response, bach_tools.ToolErrorText)
    assert response._code == "invalid_task_arguments"
    assert not binding.closed


def test_complete_flag_is_rejected_outside_result_submission(binding):
    response = bach_tools.exec_tool(
        "task_manage",
        {"action": "detail", "task_id": binding.task_id, "complete": True},
        "safe",
        worker_task_binding=binding,
    )
    assert isinstance(response, bach_tools.ToolErrorText)
    assert response._code == "invalid_task_arguments"
    assert not binding.closed


@pytest.mark.parametrize("arguments", [
    [None, "--complete=true", "--result=Ergebnis"],
    ["--complete", "true", "--result=Ergebnis"],
    ["--complete=maybe", "--result=Ergebnis"],
    ["--complete=true", "--complete=false", "--result=Ergebnis"],
])
def test_bound_task_command_rejects_malformed_completion_arguments(binding, arguments):
    with pytest.raises(ValueError):
        bound_task_command("done", [str(binding.task_id), *arguments], binding)
    assert not binding.closed
    assert not binding.completed_task_ids
    assert not binding.reviewed_task_ids


def test_bound_task_command_false_records_partial_state(binding):
    result = bound_task_command(
        "done",
        [str(binding.task_id), "--complete=false", "--result=Noch offene Pflichtarbeit"],
        binding,
    )
    assert "Teilstand gespeichert" in result
    assert binding._client.task_snapshot(binding.task_id)["status"] == "pending"
    assert "Noch offene Pflichtarbeit" in binding.task_snapshot()["description"]
    assert not binding.completed_task_ids


def test_bach_task_command_hides_argument_exception_details(binding):
    before = binding.task_snapshot()
    result = bach_tools.exec_tool(
        "bach_command",
        {"handler": "task", "operation": "done",
         "args": [str(binding.task_id), "--complete=true", "--result=Die Pflichtarbeit ist unvollständig erfüllt."]},
        "safe",
        worker_task_binding=binding,
    )
    assert "BLOCKIERT" in result
    assert "unvollständig erfüllt" not in result
    assert binding.task_snapshot() == before
    assert not binding.closed
