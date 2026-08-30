# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Restart and failure-path tests for ChatRuntime's canonical transcript store."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.chat_runtime import ChatRuntime  # noqa: E402
from hub._services.chat.session_store import (  # noqa: E402
    CHAT_SESSION_PREFIX,
    CHAT_SNAPSHOT_TYPE,
    SQLiteChatSessionStore,
)


class _Backend:
    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, **kwargs):
        return {"content": "Persistierte Antwort"}


@pytest.fixture
def snapshot_db(tmp_path):
    db_path = tmp_path / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE session_snapshots (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                snapshot_data TEXT,
                name TEXT,
                created_at TEXT
            )
        """)
    return db_path


def test_transcript_survives_runtime_restart_without_creating_history_session(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    first = ChatRuntime(_Backend(), session_store=store)
    assert asyncio.run(first.process("Hallo", "gui-web")) == "Persistierte Antwort"

    restarted = ChatRuntime(_Backend(), session_store=SQLiteChatSessionStore(snapshot_db))
    assert restarted.history("gui-web") == [
        {"role": "user", "content": "Hallo"},
        {"role": "assistant", "content": "Persistierte Antwort"},
    ]
    assert "gui-web" not in restarted.sessions

    restored = restarted.get_session("gui-web")
    assert restored.messages[-1]["content"] == "Persistierte Antwort"


def test_chat_identifier_is_hashed_and_one_snapshot_is_updated(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    chat_id = "telegram-user-123456"
    store.save(chat_id, [{"role": "user", "content": "eins"}])
    store.save(chat_id, [{"role": "user", "content": "zwei"}])

    with sqlite3.connect(snapshot_db) as conn:
        rows = conn.execute(
            "SELECT session_id, snapshot_type, snapshot_data "
            "FROM session_snapshots"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0].startswith(CHAT_SESSION_PREFIX)
    assert chat_id not in rows[0][0]
    assert rows[0][1] == CHAT_SNAPSHOT_TYPE
    assert json.loads(rows[0][2])["messages"][0]["content"] == "zwei"


def test_history_hides_internal_entries_after_restart(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    store.save("gui-web", [
        {"role": "system", "content": "Bisheriger Kontext"},
        {"role": "user", "content": "Sichtbar"},
        {"role": "tool", "content": "intern"},
        {"role": "assistant", "content": "Auch sichtbar"},
    ])

    restarted = ChatRuntime(_Backend(), session_store=store)
    assert restarted.history("gui-web") == [
        {"role": "user", "content": "Sichtbar"},
        {"role": "assistant", "content": "Auch sichtbar"},
    ]


def test_clear_removes_memory_and_persisted_transcript(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    asyncio.run(runtime.process("Löschen", "gui-web"))
    assert "gui-web" in runtime.sessions

    runtime.clear_session("gui-web")

    assert "gui-web" not in runtime.sessions
    assert store.load("gui-web") == []


def test_corrupt_snapshot_is_hidden_and_health_reports_error(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    with sqlite3.connect(snapshot_db) as conn:
        conn.execute(
            "INSERT INTO session_snapshots "
            "(session_id, snapshot_type, snapshot_data) VALUES (?, ?, ?)",
            (store.session_id("gui-web"), CHAT_SNAPSHOT_TYPE, "not-json"),
        )

    runtime = ChatRuntime(_Backend(), session_store=store)
    assert runtime.history("gui-web") == []
    assert runtime.persistence_status()["ok"] is False
    assert "invalid JSON" in runtime.persistence_status()["error"]


def test_missing_snapshot_table_does_not_break_live_chat(tmp_path):
    db_path = tmp_path / "bach.db"
    sqlite3.connect(db_path).close()
    runtime = ChatRuntime(_Backend(), session_store=SQLiteChatSessionStore(db_path))

    assert asyncio.run(runtime.process("Hallo", "gui-web")) == "Persistierte Antwort"
    assert runtime.persistence_status()["ok"] is False
    assert "session_snapshots" in runtime.persistence_status()["error"]


def test_failed_persistent_clear_does_not_claim_success(tmp_path):
    db_path = tmp_path / "bach.db"
    sqlite3.connect(db_path).close()
    runtime = ChatRuntime(_Backend(), session_store=SQLiteChatSessionStore(db_path))
    runtime.get_session("gui-web").messages.append({"role": "user", "content": "bleibt"})

    with pytest.raises(RuntimeError, match="konnte nicht gelöscht werden"):
        runtime.clear_session("gui-web")
    assert "gui-web" in runtime.sessions
