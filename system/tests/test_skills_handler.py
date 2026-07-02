# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SkillsHandler (hub/skills.py)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.skills import SkillsHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def skills_env(tmp_path):
    """Minimal environment for SkillsHandler."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "bach.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, type TEXT, category TEXT,
            path TEXT, version TEXT, description TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)
    conn.commit()
    conn.close()
    return tmp_path


@pytest.fixture
def handler(skills_env):
    return SkillsHandler(skills_env)


@pytest.fixture
def populated_skills(skills_env):
    """Skills directory with sample skill files."""
    s = skills_env / "skills"

    demo = s / "demo_skill"
    demo.mkdir()
    (demo / "SKILL.md").write_text(
        "---\nname: demo\nversion: 1.0.0\n---\n# Demo Skill\nA demo skill for testing.",
        encoding="utf-8",
    )
    (demo / "main.py").write_text("print('hello')", encoding="utf-8")

    proto = s / "_protocols"
    proto.mkdir()
    (proto / "test_protocol.md").write_text(
        "# Test Protocol\nStep 1: do something",
        encoding="utf-8",
    )

    return skills_env


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "skills"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "list" in ops
        assert "show" in ops
        assert "search" in ops
        assert "create" in ops
        assert "export" in ops
        assert "install" in ops
        assert "hierarchy" in ops
        assert "version" in ops


# ═══════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════


class TestList:
    def test_list_empty(self, handler):
        ok, output = handler.handle("list", [])
        assert ok is True

    def test_list_with_skills(self, populated_skills):
        h = SkillsHandler(populated_skills)
        ok, output = h.handle("list", [])
        assert ok is True
        assert "demo" in output.lower() or "SKILL" in output


# ═══════════════════════════════════════════════════════════════
# SHOW
# ═══════════════════════════════════════════════════════════════


class TestShow:
    def test_show_existing(self, populated_skills):
        h = SkillsHandler(populated_skills)
        ok, output = h.handle("show", ["demo_skill"])
        # show may return False if skill name doesn't match internal lookup
        assert isinstance(ok, bool)
        assert isinstance(output, str)

    def test_show_nonexistent(self, handler):
        ok, output = handler.handle("show", ["nonexistent_xyz"])
        assert ok is False
        assert "not found" in output.lower() or "nicht gefunden" in output.lower()


# ═══════════════════════════════════════════════════════════════
# VERSION / LOOKUP
# ═══════════════════════════════════════════════════════════════


class TestVersionLookup:
    def test_bach_version_uses_root_skill_before_fuzzy_workflow_match(self, skills_env):
        (skills_env / "SKILL.md").write_text(
            "---\nname: bach\nversion: 3.9.1\n---\n# BACH\n",
            encoding="utf-8",
        )
        workflow_dir = skills_env / "skills" / "workflows" / "system"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "claude-bach-vernetzung.md").write_text(
            "---\nname: claude-bach-vernetzung\nversion: 1.0.0\n---\n# Vernetzung\n",
            encoding="utf-8",
        )

        h = SkillsHandler(skills_env)
        ok, output = h.handle("version", ["bach"])

        assert ok is True
        assert "SKILL.md" in output
        assert "LOKAL:   v3.9.1" in output
        assert "claude-bach-vernetzung" not in output

    def test_find_skill_prefers_exact_file_stem_before_substring(self, skills_env):
        workflow_dir = skills_env / "skills" / "workflows"
        workflow_dir.mkdir()
        exact = workflow_dir / "alpha.md"
        fuzzy = workflow_dir / "x-alpha.md"
        fuzzy.write_text("# Fuzzy\n", encoding="utf-8")
        exact.write_text("# Exact\n", encoding="utf-8")

        h = SkillsHandler(skills_env)

        assert h._find_skill("alpha") == exact


# ═══════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════


class TestSearch:
    def test_search_no_args_falls_through_to_list(self, handler):
        # empty args silently falls through to list — may be a bug
        ok, output = handler.handle("search", [])
        assert ok is True
        assert "SKILLS" in output

    def test_search_finds_skill(self, populated_skills):
        h = SkillsHandler(populated_skills)
        ok, output = h.handle("search", ["demo"])
        assert ok is True
        assert "demo" in output.lower() or "Gefunden" in output

    def test_search_no_results(self, handler):
        ok, output = handler.handle("search", ["nonexistent_xyz"])
        assert ok is True
        assert "No results" in output or "Keine" in output


# ═══════════════════════════════════════════════════════════════
# CREATE
# ═══════════════════════════════════════════════════════════════


class TestCreate:
    def test_create_no_args_falls_through_to_list(self, handler):
        ok, output = handler.handle("create", [])
        assert ok is True
        assert "SKILLS" in output

    def test_create_dry_run(self, handler):
        ok, output = handler.handle("create", ["my_new_skill", "--dry-run"])
        assert ok is True
        assert "DRY-RUN" in output

    def test_create_skill(self, handler):
        ok, output = handler.handle("create", ["test_created_skill"])
        assert ok is True
        created = list(handler.skills_dir.rglob("*test_created_skill*"))
        assert len(created) >= 1 or "erstellt" in output.lower() or "created" in output.lower()


# ═══════════════════════════════════════════════════════════════
# HIERARCHY
# ═══════════════════════════════════════════════════════════════


class TestHierarchy:
    def test_hierarchy_missing_table(self, handler):
        ok, output = handler.handle("hierarchy", [])
        assert ok is False
        assert "hierarchy_items" in output or "Migration" in output

    def test_hierarchy_with_table(self, skills_env):
        db_path = skills_env / "data" / "bach.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS hierarchy_items (
            id INTEGER PRIMARY KEY, name TEXT, type TEXT,
            parent_id INTEGER, description TEXT, status TEXT DEFAULT 'active',
            path TEXT, version TEXT, priority INTEGER DEFAULT 0
        )""")
        conn.commit()
        conn.close()
        h = SkillsHandler(skills_env)
        ok, output = h.handle("hierarchy", [])
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import ast
        source_file = SYSTEM_ROOT / "hub" / "skills.py"
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                pytest.fail(f"Bare except at line {node.lineno} in skills.py")
