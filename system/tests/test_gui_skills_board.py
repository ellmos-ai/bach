# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for the web GUI skills board fallback behavior."""

import asyncio
import sqlite3
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui import server


def _seed_skills_board_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE bach_agents (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT,
            description TEXT,
            skill_path TEXT,
            is_active INTEGER DEFAULT 1,
            priority INTEGER DEFAULT 50
        );

        CREATE TABLE bach_experts (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            display_name TEXT,
            description TEXT,
            skill_path TEXT,
            agent_id INTEGER,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE hierarchy_items (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            dashboard_url TEXT,
            status TEXT DEFAULT 'active'
        );

        CREATE TABLE hierarchy_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id TEXT NOT NULL,
            parent_type TEXT NOT NULL,
            child_id TEXT NOT NULL,
            child_type TEXT NOT NULL,
            assignment_order INTEGER DEFAULT 0
        );
        """
    )

    conn.execute(
        """
        INSERT INTO bach_agents (id, name, display_name, description, skill_path, is_active, priority)
        VALUES (1, 'bueroassistent', 'Clara', 'Office orchestration', 'agents/bueroassistent.txt', 1, 80)
        """
    )
    conn.execute(
        """
        INSERT INTO bach_experts (id, name, display_name, description, skill_path, agent_id, is_active)
        VALUES (1, 'steuer-agent', 'Theodor', 'Tax expert', 'agents/_experts/steuer/', 1, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO hierarchy_items (id, type, name, description, status)
        VALUES ('skill-bugfix', 'skill', 'Bugfix Skill', 'Skill description', 'active')
        """
    )
    conn.execute(
        """
        INSERT INTO hierarchy_items (id, type, name, description, status)
        VALUES ('service-registry', 'service', 'Registry Service', 'Service description', 'active')
        """
    )
    conn.execute(
        """
        INSERT INTO hierarchy_items (id, type, name, description, status)
        VALUES ('workflow-bugfix-protokoll', 'workflow', 'Bugfix Protokoll', 'Dateibasierter Workflow: bugfix-protokoll.md', 'active')
        """
    )
    conn.execute(
        """
        INSERT INTO hierarchy_assignments (parent_id, parent_type, child_id, child_type, assignment_order)
        VALUES ('bueroassistent', 'agent', 'steuer-agent', 'expert', 0)
        """
    )
    conn.commit()
    conn.close()


def test_get_skills_hierarchy_falls_back_to_db_when_json_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "bach.db"
    json_path = tmp_path / "skills_hierarchy.json"
    _seed_skills_board_db(db_path)

    def _get_bach_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(server, "SKILLS_HIERARCHY_FILE", json_path)
    monkeypatch.setattr(server, "get_bach_db", _get_bach_db)

    data = asyncio.run(server.get_skills_hierarchy())

    assert data["_meta"]["source"] == "bach.db"
    assert [item["id"] for item in data["items"]["agents"]] == ["bueroassistent"]
    assert [item["id"] for item in data["items"]["experts"]] == ["steuer-agent"]
    assert [item["id"] for item in data["items"]["skills"]] == ["skill-bugfix"]
    assert [item["id"] for item in data["items"]["services"]] == ["service-registry"]
    assert [item["id"] for item in data["items"]["workflows"]] == ["workflow-bugfix-protokoll"]
    assert data["assignments"]["bueroassistent"]["experts"] == ["steuer-agent"]
    assert json_path.exists()


def test_resolve_skill_file_uses_live_agent_and_workflow_paths(tmp_path, monkeypatch):
    system_root = tmp_path / "system"
    (system_root / "agents" / "bueroassistent").mkdir(parents=True)
    (system_root / "agents" / "_experts" / "steuer").mkdir(parents=True)
    (system_root / "skills" / "workflows").mkdir(parents=True)

    agent_file = system_root / "agents" / "bueroassistent" / "SKILL.md"
    expert_file = system_root / "agents" / "_experts" / "steuer" / "SKILL.md"
    workflow_file = system_root / "skills" / "workflows" / "bugfix-protokoll.md"

    agent_file.write_text("# Bueroassistent\n", encoding="utf-8")
    expert_file.write_text("# Steuer\n", encoding="utf-8")
    workflow_file.write_text("# Workflow\n", encoding="utf-8")

    monkeypatch.setattr(server, "BACH_DIR", system_root)
    monkeypatch.setattr(server, "SKILLS_DIR", system_root / "skills")
    monkeypatch.setattr(server, "AGENTS_DIR", system_root / "agents")
    monkeypatch.setattr(server, "EXPERTS_DIR", system_root / "agents" / "_experts")

    resolved_agent = server.resolve_skill_file(
        "agent",
        "bueroassistent",
        path_hint="agents/bueroassistent.txt",
    )
    resolved_expert = server.resolve_skill_file(
        "expert",
        "steuer-agent",
        path_hint="agents/_experts/steuer/",
    )
    resolved_workflow = server.resolve_skill_file(
        "workflow",
        "bugfix-protokoll",
        description="Dateibasierter Workflow: bugfix-protokoll.md",
    )

    assert resolved_agent == agent_file
    assert resolved_expert == expert_file
    assert resolved_workflow == workflow_file
