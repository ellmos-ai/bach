"""Regressionstests fuer Task #3267.

Sichert ab:
* ``bound_check_denied`` ist im Fehlervertrag als ``not_applied`` deklariert.
* Ein ``WorkerWriteGuardError`` im gebundenen ``execute_command`` wird als
  ``bound_check_denied`` gemeldet (nicht als "Wirkung unbekannt").
* Ein Timeout in ``search_text`` liefert einen Teilabbruch-Text
  (nicht "Wirkung unbekannt").
"""

import os

from hub._services.chat import bach_tools, worker_tool_errors, worker_write_guard


class _StubBinding:
    """Minimales Worker-Binding fuer ``exec_tool``."""

    _review_grant = None

    def assert_active(self):
        return True

    def mark_tool_dispatch(self):
        return None


def test_error_spec_declares_bound_check_denied_as_not_applied():
    assert worker_tool_errors._error_spec(
        "tool_policy_denied", "bound_check_denied"
    ) == ("bach_tools", "bound_check_denied", frozenset({"not_applied"}))


def test_execute_command_reports_bound_check_denied(monkeypatch):
    def _boom(*args, **kwargs):
        raise worker_write_guard.WorkerWriteGuardError("gebunden: verweigert")

    monkeypatch.setattr(worker_write_guard, "run_bound_check", _boom)

    err = bach_tools.exec_tool(
        "execute_command",
        {"command": "ls"},
        "full",
        worker_task_binding=_StubBinding(),
        allowed_tools={"execute_command"},
    )

    text = str(err)
    assert err._code == "tool_policy_denied", text
    assert err._reason == "bound_check_denied", text
    assert err._effect_state == "not_applied", text
    assert "Wirkung unbekannt" not in text
    assert "BLOCKIERT" in text


def test_search_text_reports_partial_abort_on_deadline(monkeypatch):
    # Timeout <= 0 laesst die Deadline sofort ablaufen -> Teilabbruch.
    monkeypatch.setattr(bach_tools, "SEARCH_TIMEOUT", -1)
    monkeypatch.setattr(bach_tools, "_fs_root_allowed", lambda _p: True)

    err = bach_tools.exec_tool(
        "search_text",
        {"pattern": "def ", "path": os.path.abspath(__file__)},
        "full",
        worker_task_binding=_StubBinding(),
        allowed_tools=None,
    )

    text = str(err)
    assert "Teilabbruch" in text
    assert "Wirkung unbekannt" not in text
