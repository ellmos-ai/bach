# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for HelpHandler (hub/help.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.help import HelpHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def fake_help_env(tmp_path, monkeypatch):
    """Minimal BACH env with help files and a tools DB."""
    help_dir = tmp_path / "docs" / "help"
    help_dir.mkdir(parents=True)

    (help_dir / "cli.txt").write_text(
        "CLI\n===\nCommand Line Interface Hilfe.\nWeitere Details...", encoding="utf-8"
    )
    (help_dir / "tasks.txt").write_text(
        "Task-Verwaltung\n===============\nTasks verwalten.", encoding="utf-8"
    )

    tools_dir = help_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "_index.txt").write_text(
        "Tools Uebersicht\n================\nAlle verfuegbaren Tools.", encoding="utf-8"
    )
    (tools_dir / "python_cli_editor.txt").write_text(
        "Python CLI Editor\n=================\nEditor fuer CLI.", encoding="utf-8"
    )

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    ati_dir = agents_dir / "ati"
    ati_dir.mkdir()
    (ati_dir / "ATI.md").write_text("# ATI Agent\nDokumentation.", encoding="utf-8")

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    workflows_dir = skills_dir / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "bugfix.md").write_text("# Bugfix Workflow\nSchritte...", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE tools (
            id INTEGER PRIMARY KEY, name TEXT, type TEXT, category TEXT,
            path TEXT, description TEXT, version TEXT, capabilities TEXT,
            use_for TEXT, command TEXT, is_available INTEGER DEFAULT 1,
            language TEXT DEFAULT 'de'
        )
    """)
    conn.execute("""
        INSERT INTO tools (name, type, category, description, version, is_available, use_for, capabilities, command, language)
        VALUES ('path_healer', 'internal', 'system', 'Heilt Pfade', '1.0', 1, 'Pfad-Reparatur,Auto-Heal', 'detect,fix', 'bach heal', 'de')
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    return tmp_path


@pytest.fixture
def handler(fake_help_env):
    return HelpHandler(fake_help_env)


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "help"

    def test_target_file(self, handler, fake_help_env):
        assert handler.target_file == fake_help_env / "docs" / "help"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "<topic>" in ops


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_shows_topics(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True
        assert "cli" in output
        assert "tasks" in output

    def test_list_shows_subdirectories(self, handler):
        ok, output = handler.handle("list", [])
        assert "tools/" in output

    def test_list_empty_operation(self, handler):
        ok, output = handler.handle("", [])
        assert ok is True

    def test_list_via_run(self, handler):
        ok, output = handler.handle("run", ["list"])
        assert ok is True
        assert "cli" in output


# ═══════════════════════════════════════════════════════════════
# SHOW TOPIC
# ═══════════════════════════════════════════════════════════════


class TestShowTopic:
    def test_show_simple_topic(self, handler):
        ok, output = handler.handle("cli", [])
        assert ok is True
        assert "Command Line Interface" in output

    def test_show_subfolder_topic(self, handler):
        ok, output = handler.handle("tools/python_cli_editor", [])
        assert ok is True
        assert "Python CLI Editor" in output

    def test_show_folder_index(self, handler):
        ok, output = handler.handle("tools", [])
        assert ok is True
        assert "Tools Uebersicht" in output

    def test_show_via_run(self, handler):
        ok, output = handler.handle("run", ["cli"])
        assert ok is True
        assert "Command Line Interface" in output

    def test_plural_fallback(self, handler):
        ok, output = handler.handle("task", [])
        assert ok is True
        assert "Task-Verwaltung" in output

    def test_topic_not_found(self, handler):
        ok, output = handler.handle("nonexistent_topic", [])
        assert ok is False
        assert "nicht gefunden" in output

    def test_topic_normalization(self, handler):
        ok, output = handler.handle("CLI", [])
        assert ok is True
        assert "Command Line Interface" in output

    def test_dash_to_underscore(self, handler):
        ok, output = handler.handle("tools/python-cli-editor", [])
        assert ok is True
        assert "Python CLI Editor" in output


# ═══════════════════════════════════════════════════════════════
# TOOL HELP (DB)
# ═══════════════════════════════════════════════════════════════


class TestToolHelp:
    def test_tool_from_db(self, handler):
        ok, output = handler.handle("path_healer", [])
        assert ok is True
        assert "path_healer" in output
        assert "Heilt Pfade" in output
        assert "Aktiv" in output

    def test_tool_wildcard(self, handler):
        ok, output = handler.handle("healer", [])
        assert ok is True
        assert "path_healer" in output

    def test_tool_capabilities(self, handler):
        ok, output = handler.handle("path_healer", [])
        assert ok is True
        assert "detect" in output
        assert "fix" in output

    def test_tool_use_for(self, handler):
        ok, output = handler.handle("path_healer", [])
        assert ok is True
        assert "Pfad-Reparatur" in output

    def test_tool_command(self, handler):
        ok, output = handler.handle("path_healer", [])
        assert "bach heal" in output


# ═══════════════════════════════════════════════════════════════
# SKILL ALIASES
# ═══════════════════════════════════════════════════════════════


class TestSkillAliases:
    def test_agent_alias(self, handler):
        ok, output = handler.handle("agent/ati", [])
        assert ok is True
        assert "ATI Agent" in output
        assert "ALIAS" in output

    def test_workflow_alias(self, handler):
        ok, output = handler.handle("workflow/bugfix", [])
        assert ok is True
        assert "Bugfix Workflow" in output

    def test_alias_not_found_shows_available(self, handler):
        ok, output = handler.handle("agent/nonexistent", [])
        assert ok is True
        assert "nicht gefunden" in output or "ati" in output


# ═══════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_help_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("hub.bach_paths.BACH_DB", tmp_path / "bach.db")
        h = HelpHandler(tmp_path)
        ok, output = h.handle("list", [])
        assert ok is False
        assert "nicht gefunden" in output

    def test_suggest_similar(self, handler):
        ok, output = handler.handle("cl", [])
        assert ok is False
        assert "cli" in output
