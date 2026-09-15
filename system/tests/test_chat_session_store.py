# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Restart and failure-path tests for ChatRuntime's canonical transcript store."""

import asyncio
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.chat.chat_runtime import (  # noqa: E402
    ChatRuntime,
    FailedAnswer,
)
from hub._services.chat.session_store import (  # noqa: E402
    CHAT_SESSION_PREFIX,
    CHAT_SNAPSHOT_TYPE,
    SQLiteChatSessionStore,
)
from hub._services.llm.model_backend import CLIBackend  # noqa: E402


class _Backend:
    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, **kwargs):
        return {"content": "Persistierte Antwort"}


class _PrefixBackend:
    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, **kwargs):
        return {"content": "Backend-Fehler: legitimer CLI-Output"}


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


def test_cli_failure_persists_as_non_success_history_entry(snapshot_db, monkeypatch):
    backend = CLIBackend(cli_name="claude", cli_path="claude", cwd=".")

    async def fake_run(_prompt, model=None):
        return {"content": "Teil vor Abbruch", "error": "CLI exit 1"}

    monkeypatch.setattr(backend, "_run_cli", fake_run)
    store = SQLiteChatSessionStore(snapshot_db)
    first = ChatRuntime(backend, session_store=store)

    answer = asyncio.run(first.process("Starte CLI", "cli-failure"))

    assert isinstance(answer, FailedAnswer)
    assert answer == "Backend-Fehler: CLI exit 1\n[Teilantwort vor dem Abbruch]\nTeil vor Abbruch"
    assert first.history("cli-failure")[-1] == {
        "role": "assistant",
        "content": answer,
        "ok": False,
    }

    with sqlite3.connect(snapshot_db) as conn:
        payload = json.loads(conn.execute(
            "SELECT snapshot_data FROM session_snapshots WHERE session_id = ?",
            (store.session_id("cli-failure"),),
        ).fetchone()[0])
    assert payload["messages"][-1] == {
        "role": "assistant",
        "content": str(answer),
        "answer_status": "failed",
    }

    restarted = ChatRuntime(
        _Backend(), session_store=SQLiteChatSessionStore(snapshot_db)
    )
    assert restarted.history("cli-failure") == [
        {"role": "user", "content": "Starte CLI", "ok": True},
        {"role": "assistant", "content": str(answer), "ok": False},
    ]


def test_legitimate_legacy_prefix_survives_restart_as_success(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    first = ChatRuntime(_PrefixBackend(), session_store=store)

    answer = asyncio.run(first.process("Liefere CLI-Text", "cli-prefix-success"))

    assert str(answer) == "Backend-Fehler: legitimer CLI-Output"
    assert first.history("cli-prefix-success")[-1] == {
        "role": "assistant",
        "content": str(answer),
        "ok": True,
    }
    with sqlite3.connect(snapshot_db) as conn:
        payload = json.loads(conn.execute(
            "SELECT snapshot_data FROM session_snapshots WHERE session_id = ?",
            (store.session_id("cli-prefix-success"),),
        ).fetchone()[0])
    assert payload["messages"][-1] == {
        "role": "assistant",
        "content": str(answer),
        "answer_status": "success",
    }

    restarted = ChatRuntime(
        _Backend(), session_store=SQLiteChatSessionStore(snapshot_db)
    )
    assert restarted.history("cli-prefix-success") == [
        {"role": "user", "content": "Liefere CLI-Text", "ok": True},
        {"role": "assistant", "content": str(answer), "ok": True},
    ]


def test_legacy_failure_prefix_remains_fail_closed_after_restart(snapshot_db):
    store = SQLiteChatSessionStore(snapshot_db)
    with sqlite3.connect(snapshot_db) as conn:
        conn.execute(
            "INSERT INTO session_snapshots "
            "(session_id, snapshot_type, snapshot_data) VALUES (?, ?, ?)",
            (
                store.session_id("legacy-failure"),
                CHAT_SNAPSHOT_TYPE,
                json.dumps({
                    "version": 1,
                    "chat_id": "legacy-failure",
                    "messages": [
                        {"role": "user", "content": "Alte Aufgabe"},
                        {"role": "assistant", "content": "Backend-Fehler: Ollama weg"},
                    ],
                }),
            ),
        )

    restarted = ChatRuntime(
        _Backend(), session_store=SQLiteChatSessionStore(snapshot_db)
    )
    assert restarted.history("legacy-failure") == [
        {"role": "user", "content": "Alte Aufgabe", "ok": True},
        {"role": "assistant", "content": "Backend-Fehler: Ollama weg", "ok": False},
    ]


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


@pytest.mark.parametrize("save_fails", [False, True])
def test_clear_waits_for_running_turn_and_archives_its_answer(
    snapshot_db, monkeypatch, save_fails,
):
    started = threading.Event()
    release = threading.Event()
    clear_done = threading.Event()

    class _WaitingBackend(_Backend):
        async def chat(self, messages, **kwargs):
            started.set()
            await asyncio.to_thread(release.wait, 2)
            return {"content": "Antwort nach Modellwartezeit", "tool_calls": None}

    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_WaitingBackend(), session_store=store)
    if save_fails:
        monkeypatch.setattr(store, "save",
                            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("save failed")))
    answers = []
    errors = []

    def run_turn():
        try:
            answers.append(asyncio.run(runtime.process("Frage", "gui-web")))
        except Exception as exc:
            errors.append(exc)

    def run_clear():
        try:
            runtime.clear_session("gui-web")
            clear_done.set()
        except Exception as exc:
            errors.append(exc)

    turn_thread = threading.Thread(target=run_turn)
    clear_thread = threading.Thread(target=run_clear)
    turn_thread.start()
    assert started.wait(2)
    clear_thread.start()
    try:
        assert not clear_done.wait(0.1)
    finally:
        release.set()
    turn_thread.join(timeout=3)
    clear_thread.join(timeout=3)

    assert not turn_thread.is_alive() and not clear_thread.is_alive()
    assert errors == []
    assert answers == ["Antwort nach Modellwartezeit"]
    assert clear_done.is_set()
    assert "gui-web" not in runtime.sessions
    assert store.load("gui-web") == []
    archived = [store.get_snapshot_by_id(s["id"]) for s in store.list_snapshots()]
    assert len(archived) == 1
    assert archived[0]["messages"][-1]["content"] == "Antwort nach Modellwartezeit"


def test_self_clear_times_out_without_losing_history_or_leaking_gate(snapshot_db):
    errors = []
    runtime = None

    class _SelfClearBackend(_Backend):
        async def chat(self, messages, **kwargs):
            try:
                await asyncio.to_thread(runtime.clear_session, "gui-web")
            except RuntimeError as exc:
                errors.append(str(exc))
            return {"content": "Antwort bleibt erhalten", "tool_calls": None}

    store = SQLiteChatSessionStore(snapshot_db)
    runtime = ChatRuntime(_SelfClearBackend(), session_store=store)
    runtime.CLEAR_WAIT_TIMEOUT = 0.05

    assert asyncio.run(runtime.process("Frage", "gui-web")) == "Antwort bleibt erhalten"
    assert errors == ["Chat-Clear blockiert: laufender Chat-Turn"]
    assert "gui-web" in runtime.sessions
    assert store.load("gui-web")[-1]["content"] == "Antwort bleibt erhalten"
    assert len(store.list_snapshots()) == 1  # bestehender Live-Snapshot
    with sqlite3.connect(snapshot_db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM session_snapshots WHERE snapshot_type != ?",
            (CHAT_SNAPSHOT_TYPE,),
        ).fetchone()[0] == 0
    gate = runtime._chat_turn_gate("gui-web")
    assert gate.active_turns == 0 and not gate.clearing

    runtime.clear_session("gui-web")
    assert "gui-web" not in runtime.sessions
    assert store.load("gui-web") == []
    archived = [store.get_snapshot_by_id(s["id"]) for s in store.list_snapshots()]
    assert archived[0]["messages"][-1]["content"] == "Antwort bleibt erhalten"


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
