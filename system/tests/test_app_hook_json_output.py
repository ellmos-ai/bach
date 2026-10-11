# SPDX-License-Identifier: MIT
"""Hook diagnostics preserve JSON payloads and remain visible."""
import json
from types import SimpleNamespace
import pytest
from core.app import App
from core.hooks import HookRegistry


def app_for(monkeypatch, payload, success=True):
    app = App.__new__(App)
    app.hooks = HookRegistry()
    app.hooks.register_interceptor(
        lambda event, context: "Workflow-Hinweis: prüfe Änderungen" if event == "after_command" else None,
        name="synthetic-json-gate",
    )
    handler = SimpleNamespace(handle=lambda operation, args: (success, payload))
    monkeypatch.setattr(app, "get_handler", lambda name: handler)
    return app


@pytest.mark.parametrize("payload", ['{"ok": true, "imported": 1}', '[]', 'true', '0', '"Text"'])
def test_json_payload_is_byte_preserved_and_diagnostic_uses_stderr(monkeypatch, capsys, payload):
    app = app_for(monkeypatch, payload)
    ok, message = app.execute("prompt", "import_promptboard", [])
    assert ok and message == payload
    assert json.loads(message) == json.loads(payload)
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "Workflow-Hinweis: prüfe Änderungen\n"


def test_text_diagnostic_keeps_existing_message_suffix(monkeypatch, capsys):
    app = app_for(monkeypatch, "[OK] erledigt")
    assert app.execute("task", "status", []) == (True, "[OK] erledigt\nWorkflow-Hinweis: prüfe Änderungen")
    assert capsys.readouterr().err == ""


def test_error_json_keeps_failure_status(monkeypatch, capsys):
    payload = '{"ok": false, "reason": "blocked"}'
    app = app_for(monkeypatch, payload, False)
    assert app.execute("prompt", "import", []) == (False, payload)
    assert "Workflow-Hinweis" in capsys.readouterr().err


def test_bach_api_prompt_return_is_valid_json_with_hook_notice(monkeypatch, capsys):
    import bach_api
    payload = '{"ok": true, "imported": 1, "dry_run": false}'
    app = app_for(monkeypatch, payload)
    monkeypatch.setattr(bach_api, "get_app", lambda: app)
    assert json.loads(bach_api.prompt.import_promptboard("synthetic/library.json"))["imported"] == 1
    streams = capsys.readouterr()
    assert streams.out == "" and "Workflow-Hinweis" in streams.err
