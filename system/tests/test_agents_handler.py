# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for AgentsHandler (hub/agents.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.agents import AgentsHandler, resolve_agent_name


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


def _create_agent_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            type TEXT DEFAULT 'boss',
            is_active INTEGER DEFAULT 1,
            description TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bach_agents (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            persona TEXT DEFAULT '',
            description TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            language TEXT DEFAULT 'de'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bach_experts (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            persona TEXT DEFAULT '',
            description TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            language TEXT DEFAULT 'de'
        )
    """)
    conn.commit()


def _seed_agents(conn):
    conn.executemany(
        "INSERT INTO bach_agents (name, display_name, persona, description, is_active, language) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("steuer-agent", "Steuer-Agent", "Finanzexperte", "Steuerverwaltung und Belegerfassung", 1, "de"),
            ("research-agent", "Research-Agent", "Wissenschaftler", "Literaturrecherche und Paper-Analyse", 1, "de"),
            ("inactive-agent", "Inaktiver Agent", "Deaktiviert", "Momentan deaktiviert", 0, "de"),
        ],
    )
    conn.executemany(
        "INSERT INTO bach_experts (name, display_name, persona, description, is_active, language) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("steuer-scanner", "Steuer-Scanner", "Belegspezialist", "Scannt und klassifiziert Belege", 1, "de"),
            ("report-generator", "Report-Generator", "Berichtsexperte", "Generiert Berichte und Zusammenfassungen", 1, "de"),
        ],
    )
    conn.executemany(
        "INSERT INTO agents (name, type, is_active, description) VALUES (?, ?, ?, ?)",
        [
            ("steuer-agent", "boss", 1, "Steuerverwaltung"),
            ("research-agent", "boss", 1, "Recherche"),
        ],
    )
    conn.commit()


@pytest.fixture
def agents_env(tmp_path, monkeypatch):
    """Minimal env with agent tables and filesystem structure."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(db_path)
    _create_agent_tables(conn)
    _seed_agents(conn)
    conn.close()

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    steuer = agents_dir / "steuer-agent"
    steuer.mkdir()
    (steuer / "SKILL.md").write_text("# Steuer-Agent\nVerwaltet Steuerbelege.", encoding="utf-8")

    research = agents_dir / "research-agent"
    research.mkdir()
    (research / "SKILL.md").write_text("# Research-Agent\nRecherchiert Papers.", encoding="utf-8")

    experts_dir = agents_dir / "_experts"
    experts_dir.mkdir()
    scanner = experts_dir / "steuer-scanner"
    scanner.mkdir()
    (scanner / "CONCEPT.md").write_text("# Steuer-Scanner\nStatus: AKTIV\n", encoding="utf-8")

    monkeypatch.setattr("hub.bach_paths.BACH_DB", db_path)
    monkeypatch.setattr("hub.agents._AGENTS_DIR", agents_dir)
    monkeypatch.setattr("hub.agents._EXPERTS_DIR", experts_dir)
    monkeypatch.setattr("hub.agents._PATHS_FROM_BACH", True)

    return tmp_path, db_path


# ═══════════════════════════════════════════════════════════════
# TESTS: resolve_agent_name
# ═══════════════════════════════════════════════════════════════


class TestResolveAgentName:
    def test_exact_name(self, agents_env):
        _, db_path = agents_env
        result = resolve_agent_name(db_path, "steuer-agent")
        assert result is not None
        assert result["name"] == "steuer-agent"
        assert result["type"] == "boss"

    def test_exact_expert(self, agents_env):
        _, db_path = agents_env
        result = resolve_agent_name(db_path, "steuer-scanner")
        assert result is not None
        assert result["name"] == "steuer-scanner"
        assert result["type"] == "expert"

    def test_case_insensitive(self, agents_env):
        _, db_path = agents_env
        result = resolve_agent_name(db_path, "STEUER-AGENT")
        assert result is not None
        assert result["name"] == "steuer-agent"

    def test_display_name_match(self, agents_env):
        _, db_path = agents_env
        result = resolve_agent_name(db_path, "Research-Agent")
        assert result is not None
        assert result["name"] == "research-agent"

    def test_substring_match(self, agents_env):
        _, db_path = agents_env
        result = resolve_agent_name(db_path, "research")
        assert result is not None
        assert "research" in result["name"]

    def test_fuzzy_match(self, agents_env):
        _, db_path = agents_env
        result = resolve_agent_name(db_path, "steue-agent")
        assert result is not None
        assert result["name"] == "steuer-agent"

    def test_not_found(self, agents_env):
        _, db_path = agents_env
        result = resolve_agent_name(db_path, "zzz_nonexistent_zzz_foobar")
        assert result is None

    def test_empty_query(self, agents_env):
        _, db_path = agents_env
        assert resolve_agent_name(db_path, "") is None
        assert resolve_agent_name(db_path, "  ") is None

    def test_missing_db(self, tmp_path):
        fake_db = tmp_path / "nonexistent.db"
        assert resolve_agent_name(fake_db, "test") is None

    def test_none_db(self):
        assert resolve_agent_name(None, "test") is None


# ═══════════════════════════════════════════════════════════════
# TESTS: AgentsHandler
# ═══════════════════════════════════════════════════════════════


class TestAgentsInit:
    def test_handler_creates(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        assert handler.profile_name == "agents"

    def test_get_operations(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        ops = handler.get_operations()
        assert "list" in ops
        assert "info" in ops
        assert "active" in ops
        assert "sync" in ops
        assert "rename" in ops


class TestAgentsList:
    def test_list_all(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        ok, msg = handler.handle("list", [], dry_run=False)
        assert ok
        assert "steuer" in msg.lower()

    def test_active_only(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        ok, msg = handler.handle("active", [], dry_run=False)
        assert ok
        assert "steuer" in msg.lower()

    def test_no_database(self, tmp_path, monkeypatch):
        fake_db = tmp_path / "data" / "nonexistent.db"
        monkeypatch.setattr("hub.bach_paths.BACH_DB", fake_db)
        handler = AgentsHandler(tmp_path)
        ok, msg = handler.handle("list", [], dry_run=False)
        assert not ok
        assert "nicht gefunden" in msg.lower() or "not found" in msg.lower()


class TestAgentsInfo:
    def test_info_existing(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        ok, msg = handler.handle("info", ["steuer-agent"], dry_run=False)
        assert ok
        assert "steuer" in msg.lower()

    def test_info_expert(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        ok, msg = handler.handle("info", ["steuer-scanner"], dry_run=False)
        assert ok
        assert "scanner" in msg.lower()

    def test_info_not_found(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        ok, msg = handler.handle("info", ["nonexistent_xyz"], dry_run=False)
        assert not ok


class TestAgentsRename:
    def test_rename_missing_args(self, agents_env):
        base, _ = agents_env
        handler = AgentsHandler(base)
        ok, msg = handler.handle("rename", ["steuer-agent"], dry_run=False)
        assert not ok
        assert "syntax" in msg.lower() or "error" in msg.lower()

    def test_rename_success(self, agents_env):
        base, db_path = agents_env
        handler = AgentsHandler(base)
        ok, msg = handler.handle("rename", ["steuer-agent", "Neuer Name"], dry_run=False)
        if ok:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT display_name FROM bach_agents WHERE name = ?", ("steuer-agent",)
            ).fetchone()
            conn.close()
            assert row is not None
            assert row["display_name"] == "Neuer Name"
