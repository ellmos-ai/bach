# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ConnectionsHandler (hub/connections.py)."""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.connections import ConnectionsHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def fake_bach_env(tmp_path, monkeypatch):
    """Minimal BACH environment with a connections table."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE connections (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT DEFAULT '',
            endpoint TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            help_text TEXT DEFAULT '',
            trigger_patterns TEXT DEFAULT NULL
        )
    """)
    conn.execute("""
        INSERT INTO connections (name, type, category, is_active, help_text, endpoint, trigger_patterns)
        VALUES ('claude-code', 'ai', 'partner', 1, 'Claude Code CLI', '', '["code", "develop"]')
    """)
    conn.execute("""
        INSERT INTO connections (name, type, category, is_active, help_text, endpoint, trigger_patterns)
        VALUES ('fc-mcp', 'mcp', 'filecommander', 1, 'FileCommander MCP', 'stdio', '["file", "dir"]')
    """)
    conn.execute("""
        INSERT INTO connections (name, type, category, is_active, help_text, endpoint, trigger_patterns)
        VALUES ('inactive-svc', 'service', 'legacy', 0, 'Old service', '', NULL)
    """)
    conn.commit()
    conn.close()

    (tmp_path / "help").mkdir()
    (tmp_path / "help" / "actors.txt").write_text("ACTORS MODEL\n============\nTest actors content.", encoding="utf-8")
    (tmp_path / "help" / "partners.txt").write_text("PARTNER PROFILES\n================\nTest partners.", encoding="utf-8")

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path, db_path


@pytest.fixture
def handler(fake_bach_env):
    base_path, _ = fake_bach_env
    return ConnectionsHandler(base_path)


# ═══════════════════════════════════════════════════════════════
# BASIC PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "connections"

    def test_target_file_is_db(self, handler, fake_bach_env):
        _, db_path = fake_bach_env
        assert handler.target_file == db_path

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "db" in ops
        assert "show" in ops
        assert "actors" in ops
        assert "partners" in ops


# ═══════════════════════════════════════════════════════════════
# LIST / DB
# ═══════════════════════════════════════════════════════════════


class TestListDb:
    def test_list_all(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True
        assert "claude-code" in output
        assert "fc-mcp" in output
        assert "inactive-svc" in output

    def test_db_alias(self, handler):
        ok1, out1 = handler.handle("list", [])
        ok2, out2 = handler.handle("db", [])
        assert ok1 == ok2
        assert out1 == out2

    def test_filter_by_type(self, handler):
        ok, output = handler.handle("list", ["--type", "ai"])
        assert ok is True
        assert "claude-code" in output
        assert "fc-mcp" not in output

    def test_filter_by_type_mcp(self, handler):
        ok, output = handler.handle("list", ["--type", "mcp"])
        assert ok is True
        assert "fc-mcp" in output
        assert "claude-code" not in output

    def test_filter_no_results(self, handler):
        ok, output = handler.handle("list", ["--type", "nonexistent"])
        assert ok is True
        assert "Keine Connections" in output

    def test_status_icons(self, handler):
        ok, output = handler.handle("list", [])
        lines = output.split("\n")
        active_line = [l for l in lines if "claude-code" in l][0]
        inactive_line = [l for l in lines if "inactive-svc" in l][0]
        assert "[OK]" in active_line
        assert "[--]" in inactive_line

    def test_statistics_section(self, handler):
        ok, output = handler.handle("list", [])
        assert "Statistik:" in output
        assert "Gesamt: 3" in output

    def test_db_missing(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(handler, "db_path", tmp_path / "nonexistent.db")
        ok, output = handler.handle("list", [])
        assert ok is False
        assert "nicht gefunden" in output

    def test_default_operation(self, handler):
        ok, output = handler.handle("unknown_op", [])
        assert ok is True
        assert "claude-code" in output


# ═══════════════════════════════════════════════════════════════
# SHOW
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_by_name(self, handler):
        ok, output = handler.handle("show", ["claude-code"])
        assert ok is True
        assert "claude-code" in output
        assert "ai" in output
        assert "Aktiv" in output

    def test_show_partial_match(self, handler):
        ok, output = handler.handle("show", ["claude"])
        assert ok is True
        assert "claude-code" in output

    def test_show_not_found(self, handler):
        ok, output = handler.handle("show", ["nonexistent_connector"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_show_trigger_patterns(self, handler):
        ok, output = handler.handle("show", ["claude-code"])
        assert ok is True
        assert "TRIGGER" in output
        assert "code" in output
        assert "develop" in output

    def test_show_invalid_json_trigger_patterns(self, fake_bach_env):
        base_path, db_path = fake_bach_env
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE connections SET trigger_patterns = 'not-valid-json' WHERE name = 'claude-code'"
        )
        conn.commit()
        conn.close()

        handler = ConnectionsHandler(base_path)
        ok, output = handler.handle("show", ["claude-code"])
        assert ok is True
        assert "TRIGGER" not in output

    def test_show_null_trigger_patterns(self, handler):
        ok, output = handler.handle("show", ["inactive-svc"])
        assert ok is True
        assert "TRIGGER" not in output

    def test_show_db_missing(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(handler, "db_path", tmp_path / "nonexistent.db")
        ok, output = handler.handle("show", ["test"])
        assert ok is False
        assert "nicht gefunden" in output

    def test_show_no_args(self, handler):
        ok, output = handler.handle("show", [])
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# HELP FILES
# ═══════════════════════════════════════════════════════════════


class TestHelp:
    def test_actors(self, handler):
        ok, output = handler.handle("actors", [])
        assert ok is True
        assert "ACTORS MODEL" in output

    def test_partners(self, handler):
        ok, output = handler.handle("partners", [])
        assert ok is True
        assert "PARTNER PROFILES" in output

    def test_help_file_missing(self, handler, tmp_path):
        handler.help_dir = tmp_path / "nonexistent"
        ok, output = handler.handle("actors", [])
        assert ok is False
        assert "nicht gefunden" in output


# ═══════════════════════════════════════════════════════════════
# BARE EXCEPT FIX VERIFICATION
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        """Verify connections.py has no bare except clauses."""
        import inspect
        source = inspect.getsource(ConnectionsHandler)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "except:" or stripped == "except: pass":
                pytest.fail(f"Bare except at line {i+1}: {stripped}")
