# -*- coding: utf-8 -*-
"""Contract tests for the read-only BACH tool_registry API."""

from __future__ import annotations

import sqlite3

import pytest

from bach_api import BachAPIError, tool_registry


def _make_registry_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE tool_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'aktiv',
            has_aufgaben INTEGER DEFAULT 0,
            has_test INTEGER DEFAULT 0,
            has_feedback INTEGER DEFAULT 0,
            task_count INTEGER DEFAULT 0,
            last_scan TIMESTAMP,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO tool_registry
        (name, path, status, has_test, task_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("Beta Tool", r"C:\\tools\\beta", "aktiv", 1, 2),
            ("Alpha Tool", r"C:\\tools\\alpha", "aktiv", 0, 5),
            ("Archived Tool", r"C:\\tools\\old", "archiviert", 1, 9),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def registry_db(tmp_path, monkeypatch):
    path = tmp_path / "bach.db"
    _make_registry_db(path)
    monkeypatch.setattr("hub.bach_paths.BACH_DB", path)
    return path


def test_list_is_active_by_default_and_sorted(registry_db):
    rows = tool_registry.list()

    assert [row["name"] for row in rows] == ["Alpha Tool", "Beta Tool"]
    assert all(row["status"] == "aktiv" for row in rows)


def test_list_supports_query_and_limit(registry_db):
    rows = tool_registry.list(query="beta", limit=1)

    assert len(rows) == 1
    assert rows[0]["name"] == "Beta Tool"


def test_list_can_read_other_status_without_write_access(registry_db):
    rows = tool_registry.list(status="archiviert")

    assert [row["name"] for row in rows] == ["Archived Tool"]
    with pytest.raises(sqlite3.OperationalError):
        with sqlite3.connect(f"{registry_db.resolve().as_uri()}?mode=ro", uri=True) as conn:
            conn.execute("UPDATE tool_registry SET status = 'aktiv'")


def test_list_rejects_invalid_arguments(registry_db):
    with pytest.raises(ValueError):
        tool_registry.list(status="unknown")
    with pytest.raises(ValueError):
        tool_registry.list(limit=0)
    with pytest.raises(TypeError):
        tool_registry.list(query=42)


def test_missing_database_is_explicit(registry_db, monkeypatch):
    missing = registry_db.parent / "missing.db"
    monkeypatch.setattr("hub.bach_paths.BACH_DB", missing)

    with pytest.raises(BachAPIError, match="nicht gefunden"):
        tool_registry.list()
