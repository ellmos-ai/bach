# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Restart and failure-path tests for ChatRuntime's canonical transcript store."""

import asyncio
import json
import sqlite3
import sys
import time
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
    # "ok" kam mit T-20260906-739766716 dazu -- nach dem Neustart ist der
    # FailedAnswer-Typ weg, die Bewertung kommt dann aus dem Text.
    assert restarted.history("gui-web") == [
        {"role": "user", "content": "Hallo", "ok": True},
        {"role": "assistant", "content": "Persistierte Antwort", "ok": True},
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
        {"role": "user", "content": "Sichtbar", "ok": True},
        {"role": "assistant", "content": "Auch sichtbar", "ok": True},
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


def test_clear_archive_failure_rolls_back_live_and_durable_transcript(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    asyncio.run(runtime.process("Bleibt", "gui-web"))
    original = store.load("gui-web")

    with sqlite3.connect(snapshot_db) as conn:
        conn.execute(
            "CREATE TRIGGER block_archive BEFORE INSERT ON session_snapshots "
            "WHEN instr(NEW.session_id, ':archived:') > 0 "
            "BEGIN SELECT RAISE(ABORT, 'archive blocked'); END"
        )

    with pytest.raises(RuntimeError, match="konnte nicht gelöscht werden"):
        runtime.clear_session("gui-web")

    assert runtime.sessions["gui-web"].messages == original
    assert store.load("gui-web") == original
    assert len(store.list_snapshots()) == 1
    assert runtime.persistence_status()["ok"] is False


def test_clear_delete_failure_rolls_back_archives_and_live_transcript(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    asyncio.run(runtime.process("Bleibt", "gui-web"))
    original = store.load("gui-web")
    with sqlite3.connect(snapshot_db) as conn:
        conn.execute(
            "CREATE TRIGGER block_live_delete BEFORE DELETE ON session_snapshots "
            "WHEN instr(OLD.session_id, ':archived:') = 0 "
            "BEGIN SELECT RAISE(ABORT, 'delete blocked'); END"
        )

    with pytest.raises(RuntimeError, match="konnte nicht gelöscht werden"):
        runtime.clear_session("gui-web")

    assert runtime.sessions["gui-web"].messages == original
    assert store.load("gui-web") == original
    assert len(store.list_snapshots()) == 1
    assert runtime.persistence_status()["ok"] is False


def test_clear_archives_newer_ram_after_failed_save(snapshot_db, monkeypatch):
    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    asyncio.run(runtime.process("DB-Stand", "gui-web"))
    durable = store.load("gui-web")
    session = runtime.sessions["gui-web"]
    session.messages.extend([
        {"role": "user", "content": "Nur im RAM"},
        {"role": "assistant", "content": "RAM-Antwort"},
    ])
    current = list(session.messages)

    with monkeypatch.context() as patcher:
        patcher.setattr(store, "save",
                          lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("save failed")))
        runtime._persist_session("gui-web", session)
    assert store.load("gui-web") == durable

    runtime.clear_session("gui-web")

    assert "gui-web" not in runtime.sessions
    assert store.load("gui-web") == []
    archived = [store.get_snapshot_by_id(s["id"]) for s in store.list_snapshots()]
    assert len(archived) == 2
    assert any(s["messages"] == durable for s in archived)
    assert any(s["messages"] == current for s in archived)


def test_clear_archives_ram_even_when_durable_snapshot_is_missing(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    session = runtime.get_session("gui-web")
    session.messages.append({"role": "user", "content": "Nur RAM"})
    assert store.load("gui-web") == []

    archived_id = runtime.clear_session("gui-web")

    assert archived_id is not None
    assert "gui-web" not in runtime.sessions
    assert store.load("gui-web") == []
    assert store.get_snapshot_by_id(archived_id)["messages"] == [
        {"role": "user", "content": "Nur RAM"},
    ]


def test_clear_rejects_corrupt_durable_snapshot_without_deleting_ram(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    asyncio.run(runtime.process("Bleibt", "gui-web"))
    with sqlite3.connect(snapshot_db) as conn:
        conn.execute(
            "UPDATE session_snapshots SET snapshot_data = ? WHERE session_id = ?",
            ("{kaputt", store.session_id("gui-web")),
        )

    with pytest.raises(RuntimeError, match="konnte nicht gelöscht werden"):
        runtime.clear_session("gui-web")

    assert "gui-web" in runtime.sessions
    with sqlite3.connect(snapshot_db) as conn:
        raw = conn.execute(
            "SELECT snapshot_data FROM session_snapshots WHERE session_id = ?",
            (store.session_id("gui-web"),),
        ).fetchone()[0]
    assert raw == "{kaputt"


def test_clear_rejects_duplicate_live_snapshots_without_deleting_ram(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    asyncio.run(runtime.process("Bleibt", "gui-web"))
    with sqlite3.connect(snapshot_db) as conn:
        conn.execute(
            "INSERT INTO session_snapshots (session_id, snapshot_type, snapshot_data) "
            "SELECT session_id, snapshot_type, snapshot_data FROM session_snapshots "
            "WHERE session_id = ?",
            (store.session_id("gui-web"),),
        )

    with pytest.raises(RuntimeError, match="konnte nicht gelöscht werden"):
        runtime.clear_session("gui-web")

    assert "gui-web" in runtime.sessions
    with sqlite3.connect(snapshot_db) as conn:
        live_count = conn.execute(
            "SELECT count(*) FROM session_snapshots WHERE session_id = ?",
            (store.session_id("gui-web"),),
        ).fetchone()[0]
    assert live_count == 2


def test_clear_without_store_drops_cache_and_idle_reset_keeps_blank_session(snapshot_db):
    ephemeral = ChatRuntime(_Backend())
    asyncio.run(ephemeral.process("Weg", "gui-web"))
    ephemeral.clear_session("gui-web")
    assert "gui-web" not in ephemeral.sessions

    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_Backend(), session_store=store)
    asyncio.run(runtime.process("Alt", "gui-web"))
    old = runtime.sessions["gui-web"]
    old.last_active = time.time() - 10
    runtime.SESSION_IDLE_TTL = 1

    refreshed = runtime.get_session("gui-web")

    assert refreshed is not old
    assert runtime.sessions["gui-web"] is refreshed
    assert refreshed.messages == []
