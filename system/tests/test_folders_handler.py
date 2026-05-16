# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for FoldersHandler (hub/folders.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.folders import FoldersHandler


@pytest.fixture
def db_path(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE bach_agents (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE bach_experts (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE user_data_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path TEXT NOT NULL,
            folder_type TEXT DEFAULT 'data',
            agent_id INTEGER,
            expert_id INTEGER,
            dist_type INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed TIMESTAMP,
            FOREIGN KEY (agent_id) REFERENCES bach_agents(id),
            FOREIGN KEY (expert_id) REFERENCES bach_experts(id)
        );
        INSERT INTO bach_agents (name) VALUES ('test-agent');
        INSERT INTO bach_experts (name) VALUES ('test-expert');
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def handler(db_path):
    return FoldersHandler(db_path)


class TestListFolders:
    def test_empty(self, handler):
        result = handler.list_folders()
        assert result == []

    def test_after_add(self, handler):
        handler.add_folder("/tmp/test", "data")
        result = handler.list_folders()
        assert len(result) == 1
        assert result[0]["folder_path"] == "/tmp/test"
        assert result[0]["folder_type"] == "data"


class TestAddFolder:
    def test_basic_add(self, handler):
        fid = handler.add_folder("/tmp/mydata", "data")
        assert isinstance(fid, int)
        assert fid > 0

    def test_invalid_type(self, handler):
        with pytest.raises(ValueError, match="Ungültiger folder_type"):
            handler.add_folder("/tmp/bad", "invalid_type")

    def test_with_agent(self, handler):
        fid = handler.add_folder("/tmp/agent-data", "data", agent_name="test-agent")
        assert fid > 0
        folders = handler.list_folders()
        assert folders[0]["agent_name"] == "test-agent"

    def test_with_nonexistent_agent(self, handler):
        with pytest.raises(ValueError, match="Agent nicht gefunden"):
            handler.add_folder("/tmp/x", "data", agent_name="ghost")

    def test_all_valid_types(self, handler):
        for t in ("data", "archive", "export", "temp"):
            fid = handler.add_folder(f"/tmp/{t}", t)
            assert fid > 0
