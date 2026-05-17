# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ObsidianHandler (hub/obsidian.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.obsidian import ObsidianHandler


@pytest.fixture
def obs_env(tmp_path, monkeypatch):
    """ObsidianHandler with temporary DB and vault."""
    base = tmp_path / "bach" / "system"
    data = base / "data"
    data.mkdir(parents=True)
    db_path = data / "bach.db"

    vault = tmp_path / "obsidian-vault"
    vault.mkdir()
    (vault / "Daily Notes").mkdir()

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE memory_facts (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL, key TEXT NOT NULL,
            value TEXT, source TEXT, confidence REAL,
            created_at TEXT, updated_at TEXT,
            UNIQUE(category, key)
        )
    """)
    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT, status TEXT, priority TEXT,
            created_at TEXT, due_date TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE wiki_articles (
            id INTEGER PRIMARY KEY,
            title TEXT, content TEXT, category TEXT,
            created_at TEXT, updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    handler = ObsidianHandler(base)
    monkeypatch.setattr(handler, "db_path", db_path)
    return handler, base, db_path, vault


class TestObsidianBasic:
    def test_profile_name(self, obs_env):
        handler, _, _, _ = obs_env
        assert handler.profile_name == "obsidian"

    def test_operations(self, obs_env):
        handler, _, _, _ = obs_env
        ops = handler.get_operations()
        assert "status" in ops
        assert "sync" in ops
        assert "config" in ops
        assert "daily" in ops
        assert "tasks" in ops
        assert "wiki" in ops

    def test_unknown_operation(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("nope", [])
        assert ok is False
        assert "Unbekannte Operation" in msg


class TestObsidianConfig:
    def test_config_no_vault(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("config", [])
        assert ok is False
        assert "Kein Vault" in msg

    def test_config_set_path(self, obs_env):
        handler, _, db_path, vault = obs_env
        ok, msg = handler.handle("config", [str(vault)])
        assert ok is True
        assert "Vault-Pfad gesetzt" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT value FROM memory_facts WHERE key = 'obsidian_vault_path'"
        ).fetchone()
        conn.close()
        assert row[0] == str(vault)

    def test_config_nonexistent_path(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("config", ["/nonexistent/path"])
        assert ok is False
        assert "existiert nicht" in msg

    def test_config_dry_run(self, obs_env):
        handler, _, _, vault = obs_env
        ok, msg = handler.handle("config", [str(vault)], dry_run=True)
        assert ok is True
        assert "DRY" in msg

    def test_config_shows_existing(self, obs_env):
        handler, _, db_path, vault = obs_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_facts (category, key, value, source, confidence) VALUES (?, ?, ?, ?, ?)",
            ("system", "obsidian_vault_path", str(vault), "test", 1.0),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("config", [])
        assert ok is True
        assert str(vault) in msg


class TestObsidianStatus:
    def test_status_no_vault(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("status", [])
        assert ok is True
        assert "nicht konfiguriert" in msg

    def test_status_with_vault(self, obs_env):
        handler, _, db_path, vault = obs_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO memory_facts (category, key, value, source, confidence) VALUES (?, ?, ?, ?, ?)",
            ("system", "obsidian_vault_path", str(vault), "test", 1.0),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("status", [])
        assert ok is True
        assert str(vault) in msg
        assert "Daily Notes: ja" in msg


class TestObsidianSync:
    def test_sync_no_vault(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("sync", [])
        assert ok is False
        assert "nicht konfiguriert" in msg or "nicht vorhanden" in msg

    def test_daily_no_vault(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("daily", [])
        assert ok is False

    def test_tasks_no_vault(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("tasks", [])
        assert ok is False

    def test_wiki_no_vault(self, obs_env):
        handler, _, _, _ = obs_env
        ok, msg = handler.handle("wiki", [])
        assert ok is False
