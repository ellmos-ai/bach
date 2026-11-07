# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB-2 (#3986): history list filters by source (Ich/Buddha/Worker/System) and marks problems.

Synthetic data only: no private chat content, no provider calls.
"""
import asyncio
import sqlite3

import pytest

from hub._services.chat.chat_runtime import ChatRuntime
from hub._services.chat.session_store import chat_source

from tests.test_agent_history_delivery import history  # noqa: F401  (fixture)

HEX = "a" * 32


@pytest.mark.parametrize("chat_id,expected", [
    ("gui-web", "user"),
    ("web-abc", "user"),
    ("slot:buddha_chat:" + HEX, "user"),
    ("agent:1:slot:buddha_chat:" + HEX, "user"),
    ("123456789", "user"),
    ("talk-buddha", "user"),
    ("buddha_always_on", "buddha"),
    ("worker-7", "worker"),
    ("idle-worker", "worker"),
    ("control-api-x", "system"),
    ("", "system"),
])
def test_chat_source_is_derived_from_the_chat_id(chat_id, expected):
    assert chat_source(chat_id) == expected


class _Backend:
    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, **kwargs):
        return {"content": "Antwort"}


def _seed(store):
    store.save("gui-web", [{"role": "user", "content": "Frage"}], name="Web: Frage")
    store.save("buddha_always_on", [{"role": "user", "content": "Lauf"}], name="Chat (buddha_always_on)")
    store.save("worker-7", [{"role": "user", "content": "Task"},
                            {"role": "assistant", "content": "Fehler", "answer_status": "failed"}],
               name="Chat (worker-7)")
    store.archive_current("worker-7", "Archiv [Worker Taskwechsel] Chat (worker-7)")
    store.save("control-api-x", [{"role": "user", "content": "x"}], name="Chat (control-api-x)")


def _names(data):
    return [row["name"] for row in data["sessions"]]


def test_source_user_never_lists_worker_archives(history):  # noqa: F811
    store, client, _, _ = history
    _seed(store)
    data = client.get("/api/agent-history/sessions?source=user").json()
    assert data["source_filter"] == "user"
    assert _names(data) == ["Web: Frage"]
    assert not any(n.startswith("Archiv [Worker Taskwechsel]") for n in _names(data))
    assert all(row["source"] == "user" for row in data["sessions"])


def test_default_is_all_sources_and_counts_are_separate(history):  # noqa: F811
    store, client, _, _ = history
    _seed(store)
    data = client.get("/api/agent-history/sessions").json()
    assert data["source_filter"] == "all"
    assert data["total"] == 5
    assert data["source_counts"] == {"user": 1, "buddha": 1, "worker": 2, "system": 1}


def test_counts_ignore_the_source_filter_but_follow_the_archive_filter(history):  # noqa: F811
    store, client, _, _ = history
    _seed(store)
    data = client.get("/api/agent-history/sessions?source=user&archive=archived").json()
    assert data["total"] == 0
    assert data["source_counts"] == {"user": 0, "buddha": 0, "worker": 1, "system": 0}


def test_unknown_source_is_rejected(history):  # noqa: F811
    _, client, _, _ = history
    assert client.get("/api/agent-history/sessions?source=nope").status_code == 422


def test_failed_answers_are_counted_and_filterable(history):  # noqa: F811
    store, client, _, _ = history
    _seed(store)
    everything = client.get("/api/agent-history/sessions").json()
    failed = {(row["name"]): row["failed_count"] for row in everything["sessions"]}
    assert failed["Chat (worker-7)"] == 1 and failed["Web: Frage"] == 0
    only = client.get("/api/agent-history/sessions?problems=true").json()
    assert {row["failed_count"] > 0 for row in only["sessions"]} == {True}
    assert only["total"] == 2  # the worker transcript and its archive copy
    assert only["problems"] is True


def test_a_sent_chat_message_creates_exactly_one_listed_snapshot(history):  # noqa: F811
    store, client, _, database = history
    chat_id = "slot:buddha_chat:" + HEX
    runtime = ChatRuntime(_Backend(), session_store=store)
    assert asyncio.run(runtime.process("Hallo", chat_id)) == "Antwort"
    assert asyncio.run(runtime.process("Nochmal", chat_id)) == "Antwort"
    with sqlite3.connect(database) as conn:
        count = conn.execute("SELECT COUNT(*) FROM session_snapshots").fetchone()[0]
    assert count == 1
    data = client.get("/api/agent-history/sessions?source=user").json()
    assert data["total"] == 1
    assert data["sessions"][0]["chat_id"] == chat_id
    assert data["sessions"][0]["stored_message_count"] == 4


def test_session_detail_names_chat_id_and_source_for_continuing(history):  # noqa: F811
    store, client, _, database = history
    _seed(store)
    with sqlite3.connect(database) as conn:
        worker_id = conn.execute("SELECT id FROM session_snapshots WHERE name = 'Chat (worker-7)'").fetchone()[0]
        web_id = conn.execute("SELECT id FROM session_snapshots WHERE name = 'Web: Frage'").fetchone()[0]
    worker = client.get(f"/api/agent-history/sessions/{worker_id}").json()
    assert (worker["chat_id"], worker["chat_source"]) == ("worker-7", "worker")
    assert worker["source"] == "session_snapshots"  # the data-source field of the detail contract stays untouched
    web = client.get(f"/api/agent-history/sessions/{web_id}").json()
    assert (web["chat_id"], web["chat_source"]) == ("gui-web", "user")
