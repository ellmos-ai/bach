# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit test for standalone conversation_store module."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import conversation_store


def test_manifest_validity():
    manifest_p = Path(__file__).resolve().parent.parent / "manifest.json"
    assert manifest_p.exists()
    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert data["name"] == "conversation_store"
    assert data["selfcontained"] is True


def test_transcript_hashing_and_lifecycle(tmp_path):
    db_file = tmp_path / "test_sessions.db"
    store = conversation_store.ConversationTranscriptStore(db_file, max_messages=3)

    chat_id = "user-12345-telegram"
    sid = store.session_id(chat_id)
    assert sid.startswith(conversation_store.CHAT_SESSION_PREFIX)
    assert len(sid) == len(conversation_store.CHAT_SESSION_PREFIX) + 64

    # Empty initially
    assert store.get_transcript(chat_id) == []

    # Append messages
    store.append_message(chat_id, "user", "Hallo!")
    store.append_message(chat_id, "assistant", "Guten Tag!")
    transcript = store.get_transcript(chat_id)
    assert len(transcript) == 2
    assert transcript[0]["role"] == "user"
    assert transcript[1]["role"] == "assistant"

    # Enforce max_messages=3 limit
    store.append_message(chat_id, "user", "Nachricht 3")
    store.append_message(chat_id, "assistant", "Nachricht 4")
    bounded = store.get_transcript(chat_id)
    assert len(bounded) == 3
    assert bounded[0]["content"] == "Guten Tag!"
    assert bounded[2]["content"] == "Nachricht 4"

    # Clear transcript
    assert store.clear_transcript(chat_id) is True
    assert store.get_transcript(chat_id) == []
