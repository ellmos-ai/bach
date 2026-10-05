# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for gui/cluster_tasks.py.

Covers the ClusterTaskClient with mocked httpx and an in-memory-style SQLite
fallback.  The fallback DB is created on a temporary path and monkey-patched
into gui.task_db.BACH_DB (and the re-export in gui.cluster_tasks).
"""

from __future__ import annotations

import httpx
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui import cluster_tasks as cluster_tasks_mod
from gui import task_db as task_db_mod


# ═══════════════════════════════════════════════════════════════
# Full tasks schema used by the local fallback
# ═══════════════════════════════════════════════════════════════

_TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'P3',
    status TEXT DEFAULT 'open',
    category TEXT DEFAULT 'general',
    project TEXT,
    assigned_to TEXT DEFAULT 'user',
    created_by TEXT DEFAULT 'user',
    depends_on TEXT,
    required_model TEXT,
    assigned_slot TEXT,
    image_data BLOB,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    due_date TEXT,
    source TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    claimed_by TEXT,
    claimed_at TEXT
);
CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    field_changed TEXT,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT DEFAULT 'user',
    changed_at TEXT NOT NULL
);
"""


def _make_cluster_settings(
    *,
    mode: str = "offline",
    url: str = "",
    token: str = "",
    timeout: float = 1.0,
    retries: int = 1,
):
    """Build a minimal cluster settings object matching gui.config.ClusterSettings."""

    class _ClusterSettings:
        def __init__(self):
            self.mode_str = mode
            self.url = url.rstrip("/")
            self.token = token
            self.timeout = timeout
            self.retries = retries

        @property
        def is_online(self) -> bool:
            return self.mode_str == "online"

        @property
        def has_credentials(self) -> bool:
            return bool(self.token)

    return _ClusterSettings()


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    """Create a temp SQLite DB with the full tasks schema and patch BACH_DB."""
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_TASKS_SCHEMA)
    conn.commit()
    conn.close()

    monkeypatch.setattr(task_db_mod, "BACH_DB", db_path)
    return db_path


@pytest.fixture
def client(monkeypatch, local_db):
    """Return a ClusterTaskClient whose settings can be re-bound per test."""
    c = cluster_tasks_mod.ClusterTaskClient()
    yield c
    # Ensure no lingering httpx session is left open.
    if c.session is not None:
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(c.close())
        else:
            pass  # Session cleanup is the caller's responsibility inside loops.


# ═══════════════════════════════════════════════════════════════
# MODE / CONFIGURATION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_offline_mode_uses_local_fallback(client, local_db):
    """When cluster is configured OFFLINE, requests never hit HTTP."""
    client.settings = _make_cluster_settings(mode="offline")
    result = await client.list_tasks()
    assert result["success"] is True
    assert result["tasks"] == []


@pytest.mark.asyncio
async def test_auto_mode_without_credentials_uses_local_fallback(client, local_db):
    """AUTO without token/url must fallback locally and not raise."""
    client.settings = _make_cluster_settings(mode="auto")
    result = await client.list_tasks()
    assert result["success"] is True
    assert result["tasks"] == []


# ═══════════════════════════════════════════════════════════════
# ONLINE / HTTP
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_online_list_forwards_to_cluster(client, local_db):
    """ONLINE mode with credentials performs a real HTTP GET."""
    client.settings = _make_cluster_settings(
        mode="online", url="http://cluster.local", token="secret"
    )

    mock_response = Mock()
    mock_response.json = Mock(
        return_value={"success": True, "tasks": [{"id": 1, "title": "Remote"}]}
    )
    mock_response.raise_for_status = Mock(return_value=None)

    with patch("gui.cluster_tasks.httpx.AsyncClient") as mock_client_cls:
        mock_instance = mock_client_cls.return_value = AsyncMock()
        mock_instance.request = AsyncMock(return_value=mock_response)

        result = await client.list_tasks()

    assert result["success"] is True
    assert result["tasks"] == [{"id": 1, "title": "Remote"}]


@pytest.mark.asyncio
async def test_online_create_forwards_to_cluster(client, local_db):
    client.settings = _make_cluster_settings(
        mode="online", url="http://cluster.local", token="secret"
    )
    payload = {"title": "New", "description": "D", "priority": "P2"}

    mock_response = Mock()
    mock_response.json = Mock(
        return_value={"success": True, "task": {"id": 42, **payload}}
    )
    mock_response.raise_for_status = Mock(return_value=None)

    with patch("gui.cluster_tasks.httpx.AsyncClient") as mock_client_cls:
        mock_instance = mock_client_cls.return_value = AsyncMock()
        mock_instance.request = AsyncMock(return_value=mock_response)

        result = await client.create_task(payload)

    assert result["success"] is True
    assert result["task"]["id"] == 42


@pytest.mark.asyncio
async def test_online_unreachable_falls_back_locally(client, local_db):
    """If the cluster returns a transport error, we fall back to SQLite."""
    client.settings = _make_cluster_settings(
        mode="online", url="http://cluster.local", token="secret", retries=1
    )

    with patch("gui.cluster_tasks.httpx.AsyncClient") as mock_client_cls:
        mock_instance = mock_client_cls.return_value = AsyncMock()
        mock_instance.request = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await client.create_task({"title": "Fallback"})

    assert result["success"] is True
    assert result["task"]["title"] == "Fallback"


# ═══════════════════════════════════════════════════════════════
# LOCAL CRUD
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_create_and_list(client, local_db):
    client.settings = _make_cluster_settings(mode="offline")
    create_result = await client.create_task({"title": "A", "description": "Desc"})
    assert create_result["success"] is True
    task_id = create_result["task"]["id"]

    list_result = await client.list_tasks()
    assert list_result["success"] is True
    assert any(t["id"] == task_id for t in list_result["tasks"])


@pytest.mark.asyncio
async def test_local_get(client, local_db):
    client.settings = _make_cluster_settings(mode="offline")
    created = await client.create_task({"title": "Get me"})
    task_id = created["task"]["id"]

    fetched = await client.get_task(task_id)
    assert fetched["success"] is True
    assert fetched["task"]["title"] == "Get me"


@pytest.mark.asyncio
async def test_local_update(client, local_db):
    client.settings = _make_cluster_settings(mode="offline")
    created = await client.create_task({"title": "Old"})
    task_id = created["task"]["id"]

    updated = await client.update_task(task_id, {"title": "New"})
    assert updated["success"] is True
    assert updated["task"]["title"] == "New"


@pytest.mark.asyncio
async def test_local_delete(client, local_db):
    client.settings = _make_cluster_settings(mode="offline")
    created = await client.create_task({"title": "Delete me"})
    task_id = created["task"]["id"]

    deleted = await client.delete_task(task_id)
    assert deleted["success"] is True

    fetched = await client.get_task(task_id)
    assert fetched["success"] is False
    assert fetched["status_code"] == 404
