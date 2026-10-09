"""Recipient filtering and status CAS on the real User Inbox HTTP router.

All message data belongs to a temporary fixture, never the live TaskDB.
"""
from contextlib import contextmanager
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from gui.api.user_inbox import build_router


@pytest.fixture
def inbox(tmp_path):
    path = tmp_path / "messages.db"

    class Store:
        @contextmanager
        def connect(self):
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

    store = Store()
    with store.connect() as conn:
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, sender TEXT, recipient TEXT, subject TEXT, body TEXT, status TEXT, direction TEXT, created_at TEXT, read_at TEXT)")
        conn.executemany("INSERT INTO messages VALUES (?, 'fixture', ?, ?, 'Inhalt', ?, ?, '2026-10-09', NULL)", [
            (1, "user", "100%", "unread", "inbox"),
            (2, " USER ", "Gelesen", "read", "inbox"),
            (3, "user", "Archiv", "archived", "inbox"),
            (4, "agent", "Fremd", "unread", "inbox"),
            (5, "user", "Ausgehend", "unread", "outbox"),
            (6, "user", "Gelöscht", "deleted", "inbox"),
            (7, "", "Unbekannt", "unread", "inbox"),
        ])
    app = FastAPI()
    app.include_router(build_router(lambda: store))
    with TestClient(app) as client:
        yield client, store


def test_recipient_filter_precedes_count_and_pagination(inbox):
    client, _ = inbox
    response = client.get("/api/user-inbox?limit=1")
    assert response.status_code == 200
    data = response.json()
    assert data["schema"] == "bach.user-inbox.v1" and data["recipient"] == "user"
    assert data["total"] == 2 and data["unread"] == 1 and data["has_more"] is True
    assert [row["id"] for row in data["messages"]] == [2]
    assert [row["id"] for row in client.get("/api/user-inbox?limit=1&offset=1").json()["messages"]] == [1]


def test_status_search_and_literal_wildcard(inbox):
    client, _ = inbox
    assert client.get("/api/user-inbox", params={"search": "%"}).json()["total"] == 1
    assert client.get("/api/user-inbox?status=unread").json()["total"] == 1
    assert [r["id"] for r in client.get("/api/user-inbox?status=archived").json()["messages"]] == [3]


def test_read_archive_and_stale_status_cas(inbox):
    client, _ = inbox
    assert client.patch("/api/user-inbox/1", json={"status": "read", "expected_status": "unread"}).status_code == 200
    assert client.patch("/api/user-inbox/1", json={"status": "archived", "expected_status": "unread"}).status_code == 409
    assert client.patch("/api/user-inbox/1", json={"status": "archived", "expected_status": "read"}).status_code == 200
    assert client.get("/api/user-inbox").json()["total"] == 1
    assert client.get("/api/user-inbox?status=archived").json()["total"] == 2


@pytest.mark.parametrize("ident", [4, 5, 6, 7, 999])
def test_foreign_outgoing_deleted_or_missing_message_is_not_mutable(inbox, ident):
    client, store = inbox
    with store.connect() as conn:
        before = conn.execute("SELECT * FROM messages").fetchall()
    assert client.patch(f"/api/user-inbox/{ident}", json={"status": "read", "expected_status": "unread"}).status_code == 404
    with store.connect() as conn:
        assert conn.execute("SELECT * FROM messages").fetchall() == before


def test_compose_and_arbitrary_recipient_change_are_not_supported(inbox):
    client, _ = inbox
    assert client.post("/api/user-inbox", json={"recipient": "agent", "body": "hello"}).status_code == 405
    assert client.patch("/api/user-inbox/1", json={"status": "read", "expected_status": "unread", "recipient": "agent"}).status_code == 422
