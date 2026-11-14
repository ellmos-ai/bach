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


def test_a_spoken_turn_of_the_talk_responder_is_recorded(monkeypatch):
    from gui import server
    from hub._services.chat import talk_history

    class _Resp:
        def __init__(self, payload):
            self.status_code, self._payload = 200, payload

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **k):
            return _Resp({"models": [{"name": "qwen3.8:27b-mlx"}]})

        def post(self, url, **k):
            return _Resp({"message": {"content": "Gern geschehen."}})

    seen = []
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(server.httpx, "Client", _Client)
    monkeypatch.setattr(talk_history, "record_talk_turn", lambda *a, **k: seen.append(a))
    server._TALK_HISTORY.clear()
    out = server._talk_cortex_responder("Danke", "buddha", "de")
    assert "Gern geschehen." in out
    assert seen == [("buddha", "Danke", "Gern geschehen.")]
