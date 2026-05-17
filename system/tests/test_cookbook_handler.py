# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for CookbookHandler (hub/cookbook.py)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.cookbook import CookbookHandler


@pytest.fixture
def cook_env(tmp_path, monkeypatch):
    """CookbookHandler with temporary DB."""
    base = tmp_path / "bach" / "system"
    data = base / "data"
    data.mkdir(parents=True)
    (data / "generated").mkdir()
    db_path = data / "bach.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE cookbook_recipes (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            title TEXT,
            description TEXT,
            recipe_json TEXT,
            dist_type INTEGER DEFAULT 2,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tools (
            id INTEGER PRIMARY KEY,
            name TEXT, category TEXT, description TEXT, usage TEXT
        )
    """)
    conn.commit()
    conn.close()

    handler = CookbookHandler(base)
    monkeypatch.setattr(handler, "db_path", db_path)
    handler.output_dir = data / "generated"
    return handler, base, db_path


class TestCookbookBasic:
    def test_profile_name(self, cook_env):
        handler, _, _ = cook_env
        assert handler.profile_name == "cookbook"

    def test_operations(self, cook_env):
        handler, _, _ = cook_env
        ops = handler.get_operations()
        assert "list" in ops
        assert "generate" in ops
        assert "add" in ops
        assert "delete" in ops
        assert "help" in ops

    def test_unknown_operation(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("nope", [])
        assert ok is False
        assert "Unbekannte Operation" in msg

    def test_help(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("help", [])
        assert ok is True


class TestCookbookList:
    def test_list_empty(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "Keine Rezepte" in msg

    def test_list_with_recipes(self, cook_env):
        handler, _, db_path = cook_env
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO cookbook_recipes (name, title, description, dist_type) VALUES (?, ?, ?, ?)",
            ("tool-doku", "Tool-Dokumentation", "Generiert Tool-Doku", 2),
        )
        conn.execute(
            "INSERT INTO cookbook_recipes (name, title, description, dist_type) VALUES (?, ?, ?, ?)",
            ("user-report", "User-Report", "Custom Report", 1),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("list", [])
        assert ok is True
        assert "tool-doku" in msg
        assert "CORE" in msg
        assert "USER" in msg


class TestCookbookGenerate:
    def test_generate_no_args(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("generate", [])
        assert ok is False
        assert "Rezeptname fehlt" in msg

    def test_generate_not_found(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("generate", ["nonexistent"])
        assert ok is False
        assert "nicht gefunden" in msg

    def test_generate_dry_run(self, cook_env):
        handler, _, db_path = cook_env
        recipe = {
            "tables": ["tools"],
            "columns": ["name", "category"],
            "where": "",
            "order_by": "name",
            "template": "markdown_table",
            "title": "Tool-Liste",
            "output_file": "TOOLS.md",
        }
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO cookbook_recipes (name, title, recipe_json) VALUES (?, ?, ?)",
            ("tools", "Tools", json.dumps(recipe)),
        )
        conn.execute(
            "INSERT INTO tools (name, category, description) VALUES (?, ?, ?)",
            ("hammer", "build", "Ein Hammer"),
        )
        conn.commit()
        conn.close()

        ok, msg = handler.handle("generate", ["tools"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in msg
        assert "TOOLS.md" in msg

    def test_generate_writes_file(self, cook_env):
        handler, base, db_path = cook_env
        recipe = {
            "tables": ["tools"],
            "columns": ["name", "category"],
            "where": "",
            "order_by": "name",
            "template": "markdown_table",
            "title": "Tool-Liste",
            "output_file": "TOOLS.md",
        }
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO cookbook_recipes (name, title, recipe_json) VALUES (?, ?, ?)",
            ("tools", "Tools", json.dumps(recipe)),
        )
        conn.execute("INSERT INTO tools (name, category) VALUES ('saw', 'cut')")
        conn.commit()
        conn.close()

        ok, msg = handler.handle("generate", ["tools"])
        assert ok is True
        assert "Rohfassung generiert" in msg

        output = handler.output_dir / "TOOLS.md"
        assert output.exists()


class TestCookbookAddDelete:
    def test_add_no_args(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("add", [])
        assert ok is False

    def test_delete_no_args(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("delete", [])
        assert ok is False

    def test_delete_nonexistent(self, cook_env):
        handler, _, _ = cook_env
        ok, msg = handler.handle("delete", ["ghost"])
        assert ok is False
        assert "nicht gefunden" in msg
