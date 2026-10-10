# SPDX-License-Identifier: MIT
"""PromptBoard imports share one handler and never corrupt existing templates."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from system.tests.test_prompt_handler import prompt_env, handler  # noqa: F401


def library(tmp_path, items):
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return path


def rows(prompt_env):
    with sqlite3.connect(prompt_env[1]) as conn:
        return conn.execute("SELECT name, text, tags, category, purpose FROM prompt_templates ORDER BY id").fetchall()


def test_import_preserves_existing_templates_and_is_repeatable(handler, prompt_env, tmp_path):
    handler.handle("add", ["Existing", "User text"])
    path = library(tmp_path, [
        {"name": "Existing", "content": "Replacement"},
        {"name": "Überblick", "content": "Prüfe die Änderung.\nDann erkläre sie.",
         "tags": ["prüfung", "review"], "category": "QA", "description": "Prüfung"},
        {"name": "Überblick", "content": "Second replacement"},
        {}, None,
    ])
    result = handler.import_promptboard(path)
    assert (result["imported"], result["skipped"], result["invalid"]) == (1, 2, 2)
    assert rows(prompt_env) == [
        ("Existing", "User text", None, None, None),
        ("Überblick", "Prüfe die Änderung.\nDann erkläre sie.", '["prüfung", "review"]', "QA", "Prüfung"),
    ]
    assert handler.import_promptboard(path)["imported"] == 0


@pytest.mark.parametrize("preview_flag", ["--dry-run", "-n"])
def test_cli_api_preview_matches_import_without_writes(handler, prompt_env, tmp_path, monkeypatch, preview_flag):
    path = library(tmp_path, [{"name": "A", "content": "Text"}, {"name": "A", "content": "Text2"}])
    monkeypatch.setenv("BACH_PROMPTBOARD_LIBRARY", str(path))
    ok, message = handler.handle("import_promptboard", [preview_flag])
    assert ok
    preview = json.loads(message)
    assert preview["dry_run"] is True
    assert (preview["imported"], preview["skipped"]) == (1, 1)
    assert rows(prompt_env) == []
    import bach_api
    monkeypatch.setattr(bach_api.get_app(), "get_handler", lambda name: handler)
    assert json.loads(bach_api.prompt.import_promptboard(str(path)))["imported"] == 1
    assert rows(prompt_env)[0][0] == "A"


@pytest.mark.parametrize("preview_flag", ["--dry-run", "-n"])
def test_preview_with_explicit_path(handler, prompt_env, tmp_path, preview_flag):
    path = library(tmp_path, [{"name": "A", "content": "Text"}])
    ok, message = handler.handle("import-promptboard", [str(path), preview_flag])
    assert ok
    assert json.loads(message)["dry_run"] is True
    assert rows(prompt_env) == []


def test_cli_entrypoint_preview_does_not_write(prompt_env, tmp_path):
    path = library(tmp_path, [{"name": "CLI", "content": "Text"}])
    system_dir = Path(__file__).resolve().parents[1]
    env = dict(os.environ, BACH_DB=str(prompt_env[1]), PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(system_dir / "bach.py"), "prompt", "import-promptboard", str(path), "-n"],
        cwd=system_dir, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"dry_run": true' in result.stdout
    assert '"imported": 1' in result.stdout
    assert rows(prompt_env) == []


def test_import_accepts_utf8_bom_and_normalizes_string_tags(handler, prompt_env, tmp_path):
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"items": [{"name": "A", "content": "Text", "tags": " QA, Prüfung "}]}), encoding="utf-8-sig")
    assert handler.import_promptboard(path)["imported"] == 1
    assert json.loads(rows(prompt_env)[0][2]) == ["QA", "Prüfung"]


@pytest.mark.parametrize("tags,expected", [
    ("a,,b", ["a", "b"]), ("", []), (" , , ", []),
    ([" QA ", "", " ", "Prüfung"], ["QA", "Prüfung"]),
])
def test_import_filters_empty_tags_and_matches_cli_storage(handler, prompt_env, tmp_path, tags, expected):
    path = library(tmp_path, [{"name": "Imported", "content": "Text", "tags": tags}])
    assert handler.import_promptboard(path)["imported"] == 1
    assert handler.handle("add", ["CLI", "Text", "--tags", ",".join(expected)])[0]
    imported, added = rows(prompt_env)
    assert json.loads(imported[2]) == expected
    assert imported[2] == added[2]


def test_missing_library_cli_diagnostic_lists_discovery_sources(handler, monkeypatch, tmp_path):
    import hub.prompt
    missing = tmp_path / "missing" / "library.json"
    monkeypatch.setattr(hub.prompt, "promptboard_library_paths", lambda: [missing])
    ok, message = handler.handle("import_promptboard", [])
    assert not ok
    assert str(missing) in message
    for source in ["BACH_PROMPTBOARD_LIBRARY", "~/.promptboard", "%APPDATA%/PromptBoard", "REL-PUB_PromptBoard"]:
        assert source in message


@pytest.mark.parametrize("payload", [[], {}, {"items": {}}])
def test_invalid_library_shape_does_not_write(handler, prompt_env, tmp_path, payload):
    path = tmp_path / "library.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="items"):
        handler.import_promptboard(path)
    assert rows(prompt_env) == []


@pytest.mark.parametrize("bad", [
    {"name": {"object": 1}, "content": "Text"},
    {"name": "Bad", "content": ["Text"]},
    {"name": "Bad", "content": "Text", "tags": {"object": 1}},
    {"name": "Bad", "content": "Text", "tags": [1]},
    {"name": "Bad", "content": "Text", "category": {}},
    {"name": "Bad", "content": "Text", "description": {}},
])
def test_invalid_types_reject_entire_import(handler, prompt_env, tmp_path, bad):
    path = library(tmp_path, [{"name": "Good", "content": "Valid"}, bad])
    ok, message = handler.handle("import_promptboard", [str(path)])
    assert not ok
    assert "items[1]" in message
    assert rows(prompt_env) == []


def test_database_failure_rolls_back_all_imports(handler, prompt_env, tmp_path):
    with sqlite3.connect(prompt_env[1]) as conn:
        conn.execute("CREATE TRIGGER reject_bad BEFORE INSERT ON prompt_templates WHEN NEW.name='Bad' BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    path = library(tmp_path, [{"name": "Good", "content": "Valid"}, {"name": "Bad", "content": "Valid"}])
    ok, _ = handler.handle("import_promptboard", [str(path)])
    assert not ok
    assert rows(prompt_env) == []


@pytest.fixture
def gui_client(prompt_env, monkeypatch):
    from gui import server
    from starlette.testclient import TestClient
    monkeypatch.setattr(server, "BACH_DB", prompt_env[1])
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "promptboard-fixture" else None)
    return TestClient(server.app, raise_server_exceptions=False,
                      headers={"Authorization": "Bearer promptboard-fixture"})


def test_gui_uses_handler_and_preserves_response(gui_client, handler, prompt_env, tmp_path, monkeypatch):
    from hub.prompt import PromptHandler
    calls = []
    original = PromptHandler.import_promptboard
    def observed(self, *args, **kwargs):
        calls.append(True)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(PromptHandler, "import_promptboard", observed)
    path = library(tmp_path, [{"name": "GUI", "content": "Text"}])
    monkeypatch.setenv("BACH_PROMPTBOARD_LIBRARY", str(path))
    response = gui_client.post("/api/prompt-library/import-promptboard")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "source": str(path), "imported": 1, "skipped": 0, "invalid": 0, "dry_run": False}
    assert calls == [True]
    assert rows(prompt_env)[0][0] == "GUI"


def test_gui_bad_encoding_is_422_and_does_not_write(gui_client, prompt_env, tmp_path, monkeypatch):
    path = tmp_path / "library.json"
    path.write_bytes(b'\xff')
    monkeypatch.setenv("BACH_PROMPTBOARD_LIBRARY", str(path))
    response = gui_client.post("/api/prompt-library/import-promptboard")
    assert response.status_code == 422
    assert rows(prompt_env) == []


def test_missing_library_gui_404_lists_attempted_paths(gui_client, prompt_env, tmp_path, monkeypatch):
    from gui import server
    missing = tmp_path / "missing" / "library.json"
    monkeypatch.setattr(server, "_promptboard_library_paths", lambda: [missing])
    response = gui_client.post("/api/prompt-library/import-promptboard")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert str(missing) in detail
    for source in ["BACH_PROMPTBOARD_LIBRARY", "~/.promptboard", "%APPDATA%/PromptBoard", "REL-PUB_PromptBoard"]:
        assert source in detail
    assert rows(prompt_env) == []


def test_imported_tags_gui_edit_roundtrip(gui_client, handler, prompt_env, tmp_path):
    path = library(tmp_path, [{"name": "Imported", "content": "Text", "tags": " QA,,Prüfung "}])
    assert handler.import_promptboard(path)["imported"] == 1
    response = gui_client.get("/api/prompt-library", params={"q": "Prüfung"})
    assert response.status_code == 200
    prompt = response.json()["prompts"][0]
    assert prompt["tags"] == "QA, Prüfung"
    assert gui_client.put(f"/api/prompt-library/{prompt['id']}",
                          json={"text": "Changed", "tags": prompt["tags"]}).status_code == 200
    assert json.loads(rows(prompt_env)[0][2]) == ["QA", "Prüfung"]


@pytest.mark.parametrize("tags", [["alpha,beta", "QA"], ['["literal"]'],
                                   ["Prüfung,Entwurf", '"quoted"']])
def test_imported_ambiguous_tags_keep_boundaries_on_gui_text_save(gui_client, handler, prompt_env, tmp_path, tags):
    path = library(tmp_path, [{"name": "Imported", "content": "Text", "tags": tags}])
    assert handler.import_promptboard(path)["imported"] == 1
    prompt = gui_client.get("/api/prompt-library").json()["prompts"][0]
    assert json.loads(prompt["tags"]) == tags
    response = gui_client.put(f"/api/prompt-library/{prompt['id']}",
                              json={"text": "Only the text changed", "tags": prompt["tags"]})
    assert response.status_code == 200
    assert json.loads(rows(prompt_env)[0][2]) == tags
