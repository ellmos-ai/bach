# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB-2 (#3986): ELLMOS Talk turns persist in session_snapshots (synthetic data only)."""
import sqlite3

import pytest

from hub._services.chat.session_store import SQLiteChatSessionStore, chat_source
from hub._services.chat.talk_history import record_talk_turn


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "bach.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE session_snapshots (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, "
                     "snapshot_type TEXT NOT NULL, snapshot_data TEXT, name TEXT, created_at TEXT)")
    return SQLiteChatSessionStore(db)


def test_turns_accumulate_in_one_named_snapshot(store):
    record_talk_turn("buddha", "Hallo", "Hallo zurück", store=store)
    record_talk_turn("buddha", "Wie geht es?", "Gut", store=store)
    page = store.list_snapshot_page()
    assert page["total"] == 1
    row = page["sessions"][0]
    assert row["chat_id"] == "talk-buddha" and row["name"] == "Talk (buddha)"
    assert row["stored_message_count"] == 4 and chat_source(row["chat_id"]) == "user"
    assert [m["content"] for m in store.load("talk-buddha")] == ["Hallo", "Hallo zurück", "Wie geht es?", "Gut"]


def test_personas_do_not_share_a_transcript(store):
    record_talk_turn("buddha", "a", "b", store=store)
    record_talk_turn("claude", "c", "d", store=store)
    assert store.list_snapshot_page()["total"] == 2


def test_persona_is_normalised_to_a_safe_chat_id(store):
    record_talk_turn(" Buddha ", "a", "b", store=store)
    record_talk_turn("../x y", "a", "b", store=store)
    assert {r["chat_id"] for r in store.list_snapshot_page()["sessions"]} == {"talk-buddha", "talk-x-y"}


def test_a_broken_store_never_breaks_the_talk_turn(tmp_path):
    missing = SQLiteChatSessionStore(tmp_path / "absent.db")
    record_talk_turn("buddha", "a", "b", store=missing)  # must not raise


def test_a_spoken_turn_uses_runtime_persistence_once_and_survives_restart(monkeypatch, store):
    import asyncio
    from gui import server
    from hub._services.chat.chat_runtime import ChatRuntime
    from hub._services.chat import talk_history

    seen_messages = []
    class Backend:
        def get_default_model(self):
            return "synthetic-slot-model"

        async def chat(self, messages, **kwargs):
            seen_messages.append(messages)
            return {"content": "Gern geschehen."}

    runtime = ChatRuntime(Backend(), session_store=store)
    class Response:
        status_code = 200
        def __init__(self, payload):
            self.payload = payload
        def json(self):
            return self.payload

    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url, **kwargs):
            assert url == "http://control.invalid/api/status"
            return Response({"ready": True})
        def post(self, url, **kwargs):
            assert url == "http://control.invalid/api/chat"
            body = kwargs["json"]
            answer = asyncio.run(runtime.process(body["prompt"], body["chat_id"]))
            return Response({"ok": True, "answer": str(answer)})

    monkeypatch.setattr(server.httpx, "Client", Client)
    monkeypatch.setattr(server, "_chat_control_base_url", lambda: "http://control.invalid/api")
    monkeypatch.setattr(server, "get_control_api_auth_header", lambda: "Bearer synthetic-control")
    monkeypatch.setattr(server, "_chat_control_payload_ready", lambda payload: payload == {"ready": True})
    def no_second_writer(*args, **kwargs):
        pytest.fail("Talk must not append a second copy after ChatRuntime persisted")
    monkeypatch.setattr(talk_history, "record_talk_turn", no_second_writer)
    chat_id = server._talk_chat_scope({"id": 7}, "buddha_chat")
    token = server._TALK_CALLER_SCOPE.set(chat_id)
    try:
        assert "Gern geschehen." in server._talk_cortex_responder("Danke", "buddha", "de")
        runtime = ChatRuntime(Backend(), session_store=SQLiteChatSessionStore(store.db_path))
        assert "Gern geschehen." in server._talk_cortex_responder("Weiter", "buddha", "de")
    finally:
        server._TALK_CALLER_SCOPE.reset(token)
    assert [m["content"] for m in store.load(chat_id)] == [
        "Danke", "Gern geschehen.", "Weiter", "Gern geschehen."]
    assert store.list_snapshot_page()["total"] == 1
    assert any(m.get("content") == "Danke" for m in seen_messages[-1])
