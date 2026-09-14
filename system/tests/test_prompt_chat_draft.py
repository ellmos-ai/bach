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


def test_prompt_library_and_chat_routes_render_the_helper():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from gui import server

    client = TestClient(server.app, raise_server_exceptions=False)
    for route in ("/prompt-library", "/chat"):
        response = client.get(route)
        assert response.status_code == 200
        assert "/static/js/prompt-chat-draft.js?v=1" in response.text
