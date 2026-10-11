# SPDX-License-Identifier: MIT
"""One tag storage format, with compatible legacy search and GUI editing."""
import json
import sqlite3

import pytest

from system.tests.test_prompt_handler import prompt_env, handler  # noqa: F401


@pytest.fixture
def gui_client(prompt_env, monkeypatch):
    from gui import server
    from starlette.testclient import TestClient
    monkeypatch.setattr(server, "BACH_DB", prompt_env[1])
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "tag-fixture" else None)
    return TestClient(server.app, raise_server_exceptions=False,
                      headers={"Authorization": "Bearer tag-fixture"})


def stored_tags(prompt_env, name):
    with sqlite3.connect(prompt_env[1]) as conn:
        return conn.execute("SELECT tags FROM prompt_templates WHERE name = ?", (name,)).fetchone()[0]


@pytest.mark.parametrize("tags,expected", [
    ("a,,b", ["a", "b"]), ("", []), (" , , ", []),
    (" QA, Prüfung, ", ["QA", "Prüfung"]),
    ('["QA", "Prüfung"]', ["QA", "Prüfung"]),
])
def test_cli_and_gui_add_use_the_same_tag_storage(handler, gui_client, prompt_env, tags, expected):
    assert handler.handle("add", ["CLI", "Text", "--tags", tags])[0]
    response = gui_client.post("/api/prompt-library", json={"name": "GUI", "text": "Text", "tags": tags})
    assert response.status_code == 200
    assert json.loads(stored_tags(prompt_env, "CLI")) == expected
    assert stored_tags(prompt_env, "GUI") == stored_tags(prompt_env, "CLI")


@pytest.mark.parametrize("raw_tags", ["QA,Prüfung", json.dumps(["QA", "Prüfung"]),
                                     json.dumps(["QA", "Prüfung"], ensure_ascii=False)])
def test_legacy_and_json_tags_are_searchable_and_editable(handler, gui_client, prompt_env, raw_tags):
    assert handler.handle("add", ["Tagged", "Text"])[0]
    with sqlite3.connect(prompt_env[1]) as conn:
        conn.execute("UPDATE prompt_templates SET tags = ? WHERE name = 'Tagged'", (raw_tags,))
        pid = conn.execute("SELECT id FROM prompt_templates WHERE name = 'Tagged'").fetchone()[0]
    ok, message = handler.handle("search", ["Prüfung"])
    assert ok and "Tagged" in message
    response = gui_client.get("/api/prompt-library", params={"q": "Prüfung"})
    assert response.status_code == 200
    assert [p["id"] for p in response.json()["prompts"]] == [pid]
    before = gui_client.get(f"/api/prompt-library/{pid}").json()["prompt"]
    assert before["tags"].replace(" ", "") == "QA,Prüfung"
    # A text-only CLI update preserves the original tag bytes, including history.
    assert handler.handle("update", [str(pid), "CLI update"])[0]
    assert stored_tags(prompt_env, "Tagged") == raw_tags
    response = gui_client.put(f"/api/prompt-library/{pid}", json={"text": "GUI update", "tags": before["tags"]})
    assert response.status_code == 200
    assert json.loads(stored_tags(prompt_env, "Tagged")) == ["QA", "Prüfung"]
    after = gui_client.get(f"/api/prompt-library/{pid}").json()
    assert after["prompt"]["tags"] == "QA, Prüfung"
    assert all(v["tags"].replace(" ", "") == "QA,Prüfung" for v in after["versions"])
    with sqlite3.connect(prompt_env[1]) as conn:
        assert [r[0] for r in conn.execute("SELECT tags FROM prompt_versions ORDER BY id")] == [raw_tags, raw_tags]


def test_gui_omitted_tags_preserve_existing_but_explicit_empty_clears(gui_client, prompt_env):
    created = gui_client.post("/api/prompt-library", json={"name": "GUI", "text": "Text", "tags": "a,b"})
    assert created.status_code == 200
    pid = created.json()["id"]
    assert gui_client.put(f"/api/prompt-library/{pid}", json={"text": "Changed"}).status_code == 200
    assert json.loads(stored_tags(prompt_env, "GUI")) == ["a", "b"]
    assert gui_client.put(f"/api/prompt-library/{pid}", json={"text": "Changed again", "tags": ""}).status_code == 200
    assert stored_tags(prompt_env, "GUI") == "[]"


def test_tag_helpers_reject_invalid_list_values():
    from hub.prompt import serialize_prompt_tags
    with pytest.raises(ValueError, match="tags"):
        serialize_prompt_tags(["QA", 1])
