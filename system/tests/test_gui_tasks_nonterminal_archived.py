"""B-01 (PB-3, #3987): `status=nonterminal` darf archivierte Tasks nicht liefern."""

import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from gui import server

    db = tmp_path / "tasks.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, title TEXT, status TEXT, priority TEXT,
                category TEXT, assigned_to TEXT, delegated_to TEXT,
                created_at TEXT, depends_on TEXT, image_data TEXT, description TEXT
            );
        """)
        conn.executemany(
            "INSERT INTO tasks (id,title,status,priority,category,created_at) "
            "VALUES (?,?,?,'P2','gui','2026-11-01')",
            [(1, "open", "open"), (2, "prog", "in_progress"), (3, "rev", "review"),
             (4, "arch", "archived"), (5, "arch2", "ARCHIVED "), (6, "done", "done")],
        )

    def connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(server, "get_bach_db", connect)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "t" else None)
    c = TestClient(server.app, headers={"Authorization": "Bearer t"})
    try:
        yield c
    finally:
        c.close()


def _ids(client, status):
    return sorted(t["id"] for t in client.get(f"/api/tasks?status={status}&limit=50").json()["tasks"])


def test_nonterminal_enthaelt_keine_archivierten(client):
    assert _ids(client, "nonterminal") == [1, 2, 3]


def test_archived_liefert_weiter_alle_archivierten(client):
    assert 4 in _ids(client, "archived")


def test_all_enthaelt_archivierte(client):
    assert {4, 5} <= set(_ids(client, "all"))
