# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for PromptHandler (hub/prompt.py)."""

import sys
import sqlite3
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

PROMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    purpose TEXT,
    text TEXT,
    tags TEXT,
    category TEXT,
    dist_type INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    text TEXT,
    tags TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS prompt_boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS prompt_board_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL,
    prompt_id INTEGER NOT NULL,
    added_at TEXT,
    UNIQUE(board_id, prompt_id)
);
"""


@pytest.fixture
def prompt_env(tmp_path):
    base = tmp_path / "bach"
    base.mkdir()
    (base / "hub").mkdir()
    db_dir = base / "data"
    db_dir.mkdir()
    db_path = db_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(PROMPT_SCHEMA)
    conn.close()
    return base, db_path


@pytest.fixture
def handler(prompt_env):
    base, db_path = prompt_env
    from hub.prompt import PromptHandler
    h = PromptHandler(base)
    h._canonical_db = db_path
    h.db_path = db_path
    return h


@pytest.fixture
def populated(handler, prompt_env):
    _, db_path = prompt_env
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("code-review", "Code Review", "Review this code: {code}", '["dev","review"]', "development", "2026-01-01", "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO prompt_templates (name, purpose, text, tags, category, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("summarize", "Text Summary", "Summarize: {text}", '["text"]', "writing", "2026-01-02", "2026-01-02"),
    )
    conn.commit()
    conn.close()
    return handler


class TestPromptHandlerInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "prompt"

    def test_target_file(self, handler, prompt_env):
        _, db_path = prompt_env
        assert handler.target_file == db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        expected = {"list", "add", "get", "update", "delete", "search", "boards", "board"}
        assert set(ops.keys()) == expected


class TestHandleRouting:
    def test_unknown_operation(self, handler):
        ok, msg = handler.handle("foobar", [])
        assert not ok
        assert "Unbekannte Operation" in msg

    def test_get_no_args(self, handler):
        ok, msg = handler.handle("get", [])
        assert not ok
        assert "Argument benoetigt" in msg

    def test_update_no_args(self, handler):
        ok, msg = handler.handle("update", [])
        assert not ok
        assert "Argumente benoetigt" in msg

    def test_delete_no_args(self, handler):
        ok, msg = handler.handle("delete", [])
        assert not ok
        assert "Argument benoetigt" in msg

    def test_search_no_args(self, handler):
        ok, msg = handler.handle("search", [])
        assert not ok
        assert "Argument benoetigt" in msg

    def test_board_no_args(self, handler):
        ok, msg = handler.handle("board", [])
        assert not ok
        assert "Argument benoetigt" in msg


class TestList:
    def test_list_empty(self, handler):
        ok, msg = handler.handle("list", [])
        assert ok
        assert "Keine Prompt-Templates" in msg

    def test_list_with_data(self, populated):
        ok, msg = populated.handle("list", [])
        assert ok
        assert "code-review" in msg
        assert "summarize" in msg
        assert "2 Template(s)" in msg

    def test_list_with_category_filter(self, populated):
        ok, msg = populated.handle("list", ["--category", "development"])
        assert ok
        assert "code-review" in msg
        assert "summarize" not in msg

    def test_list_category_no_match(self, populated):
        ok, msg = populated.handle("list", ["--category", "nonexistent"])
        assert ok
        assert "Keine Prompt-Templates" in msg


class TestAdd:
    def test_add_success(self, handler):
        ok, msg = handler.handle("add", ["test-prompt", "Hello {name}"])
        assert ok
        assert "erstellt" in msg
        assert "test-prompt" in msg

    def test_add_with_options(self, handler):
        ok, msg = handler.handle("add", [
            "my-prompt", "Text here",
            "--category", "dev",
            "--tags", "a,b,c",
            "--purpose", "Testing"
        ])
        assert ok
        assert "erstellt" in msg

    def test_add_duplicate(self, populated):
        ok, msg = populated.handle("add", ["code-review", "new text"])
        assert not ok
        assert "existiert bereits" in msg

    def test_add_missing_args(self, handler):
        ok, msg = handler.handle("add", ["only-name"])
        assert not ok
        assert "Usage" in msg


class TestGet:
    def test_get_by_name(self, populated):
        ok, msg = populated.handle("get", ["code-review"])
        assert ok
        assert "PROMPT TEMPLATE" in msg
        assert "code-review" in msg
        assert "Review this code" in msg

    def test_get_by_id(self, populated):
        ok, msg = populated.handle("get", ["1"])
        assert ok
        assert "code-review" in msg

    def test_get_not_found(self, handler):
        ok, msg = handler.handle("get", ["nonexistent"])
        assert not ok
        assert "nicht gefunden" in msg


class TestUpdate:
    def test_update_success(self, populated):
        ok, msg = populated.handle("update", ["code-review", "New review text"])
        assert ok
        assert "aktualisiert" in msg
        assert "v1" in msg

    def test_update_not_found(self, handler):
        ok, msg = handler.handle("update", ["nonexistent", "text"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_update_creates_version(self, populated, prompt_env):
        _, db_path = prompt_env
        populated.handle("update", ["code-review", "Version 2 text"])
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM prompt_versions WHERE prompt_id=1").fetchone()[0]
        conn.close()
        assert count == 1


class TestDelete:
    def test_delete_success(self, populated):
        ok, msg = populated.handle("delete", ["code-review"])
        assert ok
        assert "geloescht" in msg

    def test_delete_not_found(self, handler):
        ok, msg = handler.handle("delete", ["nonexistent"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_delete_removes_from_db(self, populated, prompt_env):
        _, db_path = prompt_env
        populated.handle("delete", ["code-review"])
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT * FROM prompt_templates WHERE name='code-review'").fetchone()
        conn.close()
        assert row is None


class TestSearch:
    def test_search_found(self, populated):
        ok, msg = populated.handle("search", ["review"])
        assert ok
        assert "code-review" in msg
        assert "1 Treffer" in msg

    def test_search_not_found(self, populated):
        ok, msg = populated.handle("search", ["zzzzz"])
        assert ok
        assert "Keine Treffer" in msg

    def test_search_by_tag(self, populated):
        ok, msg = populated.handle("search", ["dev"])
        assert ok
        assert "code-review" in msg


class TestBoards:
    def test_boards_empty(self, handler):
        ok, msg = handler.handle("boards", [])
        assert ok
        assert "Keine Boards" in msg

    def test_boards_with_data(self, populated, prompt_env):
        _, db_path = prompt_env
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO prompt_boards (title, description, created_at) VALUES (?, ?, ?)",
                     ("Dev Board", "Development prompts", "2026-01-01"))
        conn.commit()
        conn.close()
        ok, msg = populated.handle("boards", [])
        assert ok
        assert "Dev Board" in msg


class TestBoard:
    def test_board_create(self, handler):
        ok, msg = handler.handle("board", ["New Board"])
        assert ok
        assert "erstellt" in msg

    def test_board_add_prompt(self, populated):
        populated.handle("board", ["My Board"])
        ok, msg = populated.handle("board", ["My Board", "--add-prompt", "code-review"])
        assert ok
        assert "hinzugefuegt" in msg

    def test_board_remove_prompt(self, populated):
        populated.handle("board", ["My Board", "--add-prompt", "code-review"])
        ok, msg = populated.handle("board", ["My Board", "--remove-prompt", "code-review"])
        assert ok
        assert "entfernt" in msg

    def test_board_add_nonexistent_prompt(self, populated):
        populated.handle("board", ["My Board"])
        ok, msg = populated.handle("board", ["My Board", "--add-prompt", "nope"])
        assert not ok
        assert "nicht gefunden" in msg
