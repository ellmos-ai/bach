# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ToolsHandler (hub/tools.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.tools import ToolsHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_tools_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'cli',
            category TEXT DEFAULT '',
            description TEXT DEFAULT '',
            command TEXT DEFAULT '',
            endpoint TEXT DEFAULT '',
            capabilities TEXT DEFAULT '[]',
            use_for TEXT DEFAULT '',
            is_available INTEGER DEFAULT 1,
            language TEXT DEFAULT 'de'
        )
    """)
    conn.commit()


def _seed_tools(conn):
    tools = [
        ("encoding_fixer", "cli", "coding", "Encoding-Probleme beheben", "python encoding_fixer.py", "", '["fix_encoding"]', "Dateien mit kaputtem Encoding reparieren", 1, "de"),
        ("backup_manager", "cli", "backup", "Backups erstellen und verwalten", "python backup_manager.py", "", '["backup","restore"]', "Backup-Operationen", 1, "de"),
        ("ollama_chat", "external", "ai", "Ollama Chat-Interface", "", "http://localhost:11434", '["chat","generate"]', "LLM-Anfragen", 1, "de"),
        ("disabled_tool", "cli", "test", "Inaktives Tool", "", "", "[]", "", 0, "de"),
    ]
    conn.executemany(
        "INSERT INTO tools (name, type, category, description, command, endpoint, capabilities, use_for, is_available, language) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tools,
    )
    conn.commit()


@pytest.fixture
def tools_env(tmp_path, monkeypatch):
    """Minimal env with tools table and sample scripts."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_tools_table(conn)
    _seed_tools(conn)
    conn.close()

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "c_encoding_fixer.py").write_text(
        '"""Encoding Fixer - repariert kaputte Encodings."""\nimport sys\nprint("OK")\n',
        encoding="utf-8",
    )
    (tools_dir / "backup_manager.py").write_text(
        '"""Backup Manager."""\nimport argparse\nprint("backup")\n',
        encoding="utf-8",
    )
    sub = tools_dir / "coding"
    sub.mkdir()
    (sub / "indent_checker.py").write_text('"""Indent Checker."""\n', encoding="utf-8")

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


# ═══════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════


class TestToolsInit:
    def test_handler_creates(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        assert handler.tools_dir == base / "tools"

    def test_profile_name(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        assert handler.profile_name == "tools"

    def test_get_operations(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ops = handler.get_operations()
        assert "list" in ops
        assert "db" in ops
        assert "show" in ops
        assert "run" in ops
        assert "search" in ops


class TestToolsList:
    def test_list_finds_scripts(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("list", [], dry_run=False)
        assert ok
        assert "c_encoding_fixer" in msg
        assert "backup_manager" in msg

    def test_list_shows_subdirs(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("list", [], dry_run=False)
        assert ok
        assert "coding" in msg.lower()

    def test_list_missing_dir(self, tmp_path, monkeypatch):
        db_path = tmp_path / "data" / "bach.db"
        monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
        handler = ToolsHandler(tmp_path)
        ok, msg = handler.handle("list", [], dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg


class TestToolsDb:
    def test_db_list_all(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("db", [], dry_run=False)
        assert ok
        assert "encoding_fixer" in msg
        assert "ollama_chat" in msg

    def test_db_filter_type(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("db", ["--type", "external"], dry_run=False)
        assert ok
        assert "ollama_chat" in msg

    def test_db_no_database(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "data" / "nonexistent.db"
        monkeypatch.setattr("hub.bach_paths.BACH_DB", fake_db)
        handler = ToolsHandler(tmp_path)
        ok, msg = handler.handle("db", [], dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg.lower() or "not found" in msg.lower()


class TestToolsShow:
    def test_show_from_db(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("show", ["encoding_fixer"], dry_run=False)
        assert ok
        assert "encoding_fixer" in msg
        assert "Encoding" in msg

    def test_show_from_filesystem(self, tools_env):
        base, db_path = tools_env
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM tools")
        conn.commit()
        conn.close()
        handler = ToolsHandler(base)
        ok, msg = handler.handle("show", ["c_encoding_fixer"], dry_run=False)
        assert ok
        assert "encoding_fixer" in msg.lower()

    def test_show_not_found(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("show", ["nonexistent_xyz"], dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg.lower()


class TestToolsSearch:
    def test_search_by_name(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("search", ["encoding"], dry_run=False)
        assert ok
        assert "encoding" in msg.lower()

    def test_search_by_description(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("search", ["Backup"], dry_run=False)
        assert ok
        assert "backup" in msg.lower()

    def test_search_no_results(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("search", ["zzz_impossible_term_zzz"], dry_run=False)
        assert ok
        assert "keine" in msg.lower() or "0" in msg


class TestToolsRun:
    def test_run_dry_run(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("run", ["c_encoding_fixer"], dry_run=True)
        assert ok
        assert "DRY-RUN" in msg

    def test_run_not_found(self, tools_env):
        base, _ = tools_env
        handler = ToolsHandler(base)
        ok, msg = handler.handle("run", ["nonexistent_xyz"], dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg.lower()
