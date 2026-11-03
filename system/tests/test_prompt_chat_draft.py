# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression checks for the Prompt Library -> Buddha Chat draft handoff."""

from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
TEMPLATES = SYSTEM_ROOT / "gui" / "templates"
STATIC_JS = SYSTEM_ROOT / "gui" / "static" / "js"


def test_prompt_library_handoff_uses_session_storage_not_url_payload():
    source = (TEMPLATES / "prompt-library.html").read_text(encoding="utf-8")

    assert "BachChatDraft.store(text.value)" in source
    assert "window.location.assign('/chat')" in source
    assert "/chat?" not in source
    assert "encodeURIComponent(text.value)" not in source


def test_chat_consumes_draft_into_editor_without_sending_it():
    source = (TEMPLATES / "chat.html").read_text(encoding="utf-8")
    start = source.index("function loadLibraryDraft()")
    end = source.index("async function send()", start)
    handoff = source[start:end]

    assert "BachChatDraft.consume()" in handoff
    assert "inputEl.value = draft" in handoff
    assert "send()" not in handoff
    assert "fetch(" not in handoff


def test_draft_helper_is_one_time_and_rejects_oversized_payloads():
    source = (STATIC_JS / "prompt-chat-draft.js").read_text(encoding="utf-8")

    assert "const MAX_DRAFT_LENGTH = 200000" in source
    assert source.index("target.removeItem(STORAGE_KEY)") < source.index("JSON.parse(raw)")
    assert "payload.text.length > MAX_DRAFT_LENGTH" in source


def test_chat_rechecks_readiness_before_consuming_editor_text():
    source = (TEMPLATES / "chat.html").read_text(encoding="utf-8")
    start = source.index("async function send()")
    end = source.index("sendBtn.addEventListener", start)
    send = source[start:end]

    assert send.index("/readiness?chat_id=") < send.index("inputEl.value = ''")
    assert "readiness.available !== true" in send
    assert "inputEl.value = text" in send


def test_both_pages_load_the_shared_draft_helper():
    include = '<script src="/static/js/prompt-chat-draft.js?v=1"></script>'

    assert include in (TEMPLATES / "prompt-library.html").read_text(encoding="utf-8")
    assert include in (TEMPLATES / "chat.html").read_text(encoding="utf-8")
    assert include in (TEMPLATES / "index.html").read_text(encoding="utf-8")


def test_index_dashboard_has_quick_prompt_card_and_chat_handoff():
    source = (TEMPLATES / "index.html").read_text(encoding="utf-8")

    assert "quick-prompt-input" in source
    assert "quick-prompt-select" in source
    assert "openQuickPromptInChat()" in source
    assert "window.BachChatDraft.store(text)" in source
    assert "loadQuickPromptTemplates()" in source
    assert "/api/prompt-library" in source


def test_prompt_library_and_chat_routes_render_the_helper():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from gui import server

    client = TestClient(server.app, raise_server_exceptions=False)
    for route in ("/prompt-library", "/chat"):
        response = client.get(route)
        assert response.status_code == 200
        assert "/static/js/prompt-chat-draft.js?v=1" in response.text


def test_prompt_library_import_preview_endpoint(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    import json
    from fastapi.testclient import TestClient
    from gui import server

    lib_path = tmp_path / "library.json"
    lib_path.write_text(json.dumps({"items": [{"name": "P1", "content": "Text"}]}), encoding="utf-8")
    monkeypatch.setattr(server, "_promptboard_library_paths", lambda: [lib_path])
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "test-token" else None)

    client = TestClient(server.app, raise_server_exceptions=False, headers={"Authorization": "Bearer test-token"})
    response = client.get("/api/prompt-library/import-promptboard/preview")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert data["imported"] == 1
    assert data["source"] == str(lib_path)


def test_prompt_library_template_has_preview_and_tag_filtering():
    source = (TEMPLATES / "prompt-library.html").read_text(encoding="utf-8")
    assert "previewPromptBoard()" in source
    assert "/api/prompt-library/import-promptboard/preview" in source
    assert "filterTag(tag)" in source


def test_prompt_library_template_has_drag_and_drop_and_file_upload():
    source = (TEMPLATES / "prompt-library.html").read_text(encoding="utf-8")
    assert "pl-drop-area" in source
    assert "handleDragOver(event)" in source
    assert "handleDrop(event)" in source
    assert "handleFileSelect(event)" in source
    assert "pl-file-input" in source
    assert "/api/prompt-library/import-json/preview" in source
    assert "/api/prompt-library/import-json" in source


def test_prompt_library_import_json_endpoints(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from gui import server

    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "test-token" else None)
    client = TestClient(server.app, raise_server_exceptions=False, headers={"Authorization": "Bearer test-token"})

    payload = {
        "filename": "external_library.json",
        "payload": {
            "items": [
                {"name": "UploadPrompt1", "content": "Text 1", "category": "Uploaded"},
                {"name": "UploadPrompt1", "content": "Duplikat"},
            ]
        }
    }

    # 1. Preview
    res_preview = client.post("/api/prompt-library/import-json/preview", json=payload)
    assert res_preview.status_code == 200
    data_preview = res_preview.json()
    assert data_preview["ok"] is True
    assert data_preview["dry_run"] is True
    assert data_preview["imported"] == 1
    assert data_preview["skipped"] == 1
    assert data_preview["source"] == "external_library.json"

    # 2. Actual Import
    res_import = client.post("/api/prompt-library/import-json", json=payload)
    assert res_import.status_code == 200
    data_import = res_import.json()
    assert data_import["ok"] is True
    assert data_import["dry_run"] is False
    assert data_import["imported"] == 1
    assert data_import["source"] == "external_library.json"


def test_prompt_library_template_has_variable_replacement_and_preview():
    source = (TEMPLATES / "prompt-library.html").read_text(encoding="utf-8")
    assert "pl-variables-panel" in source
    assert "extractTemplateVariables" in source
    assert "getSubstitutedPromptText" in source
    assert "updateVariablePreview" in source
    assert "openResolvedInChat" in source
    assert "pl-preview-box" in source
    assert "pl-variables-grid" in source
    assert "BachChatDraft.store(text.value)" in source


def test_chat_has_voice_input_and_stt_streaming_support():
    source = (TEMPLATES / "chat.html").read_text(encoding="utf-8")
    assert 'id="mic-btn"' in source
    mic_idx = source.index('id="mic-btn"')
    assert 'hidden' not in source[mic_idx-30:mic_idx+30]
    assert "navigator.mediaDevices.getUserMedia" in source
    assert "MediaRecorder" in source
    assert "/api/voice/stt" in source
    assert "params.get('voice') === '1'" in source


def test_api_voice_stt_endpoint(monkeypatch):
    import base64
    from fastapi.testclient import TestClient
    from gui import server

    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "test-token" else None)
    client = TestClient(server.app, raise_server_exceptions=False, headers={"Authorization": "Bearer test-token"})

    # Missing audio_b64 -> 400
    res_bad = client.post("/api/voice/stt", json={})
    assert res_bad.status_code == 400

    # Valid audio_b64
    fake_audio = base64.b64encode(b"RIFF-fake-wav").decode("ascii")
    res_ok = client.post("/api/voice/stt", json={"audio_b64": fake_audio, "suffix": ".wav", "language": "de"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["schema"] == "ellmos.voice-io.stt.v1"


def test_prompt_library_favorite_api_and_gui_features(monkeypatch, tmp_path):
    import sqlite3
    from fastapi.testclient import TestClient
    from gui import server

    db_path = tmp_path / "test_bach.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE prompt_templates (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, purpose TEXT, text TEXT, tags TEXT, category TEXT, created_at TEXT, updated_at TEXT, dist_type INTEGER DEFAULT 1)"
    )
    conn.execute(
        "CREATE TABLE prompt_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, prompt_id INTEGER, version_number INTEGER, text TEXT, tags TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO prompt_templates (name, purpose, text, tags, category) VALUES ('Fav1', 'Test Purpose', 'Content 1', 'tagA', 'CatA')"
    )
    conn.execute(
        "INSERT INTO prompt_templates (name, purpose, text, tags, category) VALUES ('Fav2', 'Test Purpose 2', 'Content 2', 'favorite,tagB', 'CatB')"
    )
    conn.commit()
    conn.close()

    def get_test_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(server, "get_bach_db", get_test_db)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "test-token" else None)
    client = TestClient(server.app, raise_server_exceptions=False, headers={"Authorization": "Bearer test-token"})

    # 1. List all prompts - checks is_favorite attribute
    res = client.get("/api/prompt-library")
    assert res.status_code == 200
    data = res.json()
    prompts = {p["name"]: p for p in data["prompts"]}
    assert prompts["Fav1"]["is_favorite"] is False
    assert prompts["Fav2"]["is_favorite"] is True

    # 2. Filter by favorites=1
    res_fav = client.get("/api/prompt-library?favorites=1")
    assert res_fav.status_code == 200
    fav_prompts = res_fav.json()["prompts"]
    assert len(fav_prompts) == 1
    assert fav_prompts[0]["name"] == "Fav2"

    # 3. Toggle favorite on Fav1 -> becomes True
    fav1_id = prompts["Fav1"]["id"]
    res_toggle = client.post(f"/api/prompt-library/{fav1_id}/favorite")
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_favorite"] is True

    # Check updated list
    res_fav_after = client.get("/api/prompt-library?favorites=1")
    assert len(res_fav_after.json()["prompts"]) == 2

    # Toggle again -> becomes False
    res_toggle_off = client.post(f"/api/prompt-library/{fav1_id}/favorite")
    assert res_toggle_off.status_code == 200
    assert res_toggle_off.json()["is_favorite"] is False

    # Check GUI template contains favorite controls
    source = (TEMPLATES / "prompt-library.html").read_text(encoding="utf-8")
    assert "pl-fav-filter" in source
    assert "toggleFavoritesOnly" in source
    assert "toggleFavById" in source
    assert "⭐ Nur Favoriten" in source


def test_chat_tray_favorite_prompts_and_auto_preview():
    from unittest.mock import MagicMock, patch

    with patch.dict("sys.modules", {
        "pystray": MagicMock(),
        "PIL": MagicMock(),
        "PIL.Image": MagicMock(),
        "PIL.ImageDraw": MagicMock(),
        "PIL.ImageFont": MagicMock(),
    }):
        from hub._services.chat.chat_tray import BACHTray
        tray = BACHTray(host="testhost", port=9999)

        # Test preview generator
        long_text = "Dies ist ein sehr langer Prompt mit vielen Zeilen\n\nund Absätzen\tund Leerzeichen, der auf maximal siebzig Zeichen gekürzt werden muss."
        preview = tray._make_prompt_preview(long_text, max_len=60)
        assert len(preview) <= 60
        assert preview.endswith("...")
        assert "\n" not in preview

        # Ensure initial favorites is populated
        assert len(tray.favorite_prompts) > 0

        # Snapshot contains favorite count
        snapshot = tray.promptboard_smoke_snapshot()
        assert "favorite_count" in snapshot
        assert snapshot["favorite_count"] >= 1



