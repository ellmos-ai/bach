# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for ContextHandler (hub/context.py)."""

import json
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.context import ContextHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def ctx_env(tmp_path):
    """Minimal environment for ContextHandler."""
    (tmp_path / "memory").mkdir()
    (tmp_path / "data" / "logs").mkdir(parents=True)
    (tmp_path / "help").mkdir()
    return tmp_path


@pytest.fixture
def handler(ctx_env):
    return ContextHandler(ctx_env)


@pytest.fixture
def populated_env(ctx_env):
    """Environment with sample memories, tasks, and lessons."""
    mem_dir = ctx_env / "memory"
    (mem_dir / "20260501_session.md").write_text(
        "# Session 2026-05-01\nMigrated backup handler to new API.\nFixed 3 tests.",
        encoding="utf-8",
    )
    (mem_dir / "20260502_notes.md").write_text(
        "# Notes\nClipboard cascade now supports Wayland.",
        encoding="utf-8",
    )
    (mem_dir / "tasks.json").write_text(
        json.dumps({
            "tasks": [
                {"task": "Fix xclip fallback", "status": "open", "priority": "high"},
                {"task": "Write tests for scheduler", "status": "open", "priority": "critical"},
                {"task": "Done task", "status": "done", "priority": "low"},
            ]
        }),
        encoding="utf-8",
    )

    help_dir = ctx_env / "help"
    (help_dir / "lessons.txt").write_text(
        "1. Always set PYTHONIOENCODING=utf-8\n"
        "2. Never use bare except\n"
        "3. Test on all platforms\n",
        encoding="utf-8",
    )
    return ctx_env


# ═══════════════════════════════════════════════════════════════
# PROPERTIES
# ═══════════════════════════════════════════════════════════════


class TestProperties:
    def test_profile_name(self, handler):
        assert handler.profile_name == "context"

    def test_operations(self, handler):
        ops = handler.get_operations()
        assert "auto" in ops
        assert "search" in ops
        assert "longterm" in ops
        assert "recent" in ops


# ═══════════════════════════════════════════════════════════════
# AUTO CONTEXT
# ═══════════════════════════════════════════════════════════════


class TestAutoContext:
    def test_auto_empty(self, handler):
        ok, output = handler.handle("auto", [])
        assert ok is True
        assert "AUTO-KONTEXT" in output

    def test_auto_with_memories(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("auto", [])
        assert ok is True
        assert "MEMORY-EINTRAEGE" in output

    def test_auto_shows_priority_tasks(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("auto", [])
        assert ok is True
        assert "PRIORITAETS-TASKS" in output

    def test_auto_shows_lessons(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("auto", [])
        assert ok is True
        assert "LESSONS LEARNED" in output

    def test_default_operation_is_auto(self, handler):
        ok, output = handler.handle("unknown_op", [])
        assert ok is True
        assert "AUTO-KONTEXT" in output


# ═══════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════


class TestSearch:
    def test_search_no_args(self, handler):
        ok, output = handler.handle("search", [])
        assert ok is False
        assert "Usage" in output

    def test_search_finds_term(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("search", ["clipboard"])
        assert ok is True
        assert "clipboard" in output.lower() or "Gefunden" in output

    def test_search_no_results(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("search", ["nonexistent_xyz_term"])
        assert ok is True
        assert "Keine" in output or "0" in output


# ═══════════════════════════════════════════════════════════════
# RECENT
# ═══════════════════════════════════════════════════════════════


class TestRecent:
    def test_recent_empty(self, handler):
        ok, output = handler.handle("recent", [])
        assert ok is True
        assert "Keine" in output

    def test_recent_with_memories(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("recent", ["2"])
        assert ok is True
        assert "MEMORY-EINTRAEGE" in output

    def test_recent_default_count(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("recent", [])
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# LONGTERM
# ═══════════════════════════════════════════════════════════════


class TestLongterm:
    def test_longterm_empty(self, handler):
        ok, output = handler.handle("longterm", [])
        assert ok is True

    def test_longterm_with_query(self, populated_env):
        h = ContextHandler(populated_env)
        ok, output = h.handle("longterm", ["backup"])
        assert ok is True


# ═══════════════════════════════════════════════════════════════
# INTERNAL METHODS
# ═══════════════════════════════════════════════════════════════


class TestInternalMethods:
    def test_get_recent_memories_empty(self, handler):
        result = handler._get_recent_memories(5)
        assert result == []

    def test_get_recent_memories_with_data(self, populated_env):
        h = ContextHandler(populated_env)
        result = h._get_recent_memories(5)
        assert len(result) >= 1
        assert "date" in result[0]
        assert "summary" in result[0]

    def test_get_priority_tasks_empty(self, handler):
        result = handler._get_priority_tasks()
        assert result == []

    def test_get_priority_tasks_filters_correctly(self, populated_env):
        h = ContextHandler(populated_env)
        result = h._get_priority_tasks()
        assert len(result) == 2
        priorities = {t["priority"] for t in result}
        assert priorities <= {"high", "critical"}

    def test_get_lessons_summary_empty(self, handler):
        result = handler._get_lessons_summary()
        assert result == []

    def test_get_lessons_summary_with_data(self, populated_env):
        h = ContextHandler(populated_env)
        result = h._get_lessons_summary()
        assert len(result) >= 1
        assert "PYTHONIOENCODING" in result[0]

    def test_get_warnings_empty(self, handler):
        result = handler._get_warnings()
        assert result == []

    def test_search_in_memory_finds_term(self, populated_env):
        h = ContextHandler(populated_env)
        result = h._search_in_memory("backup", None, None)
        assert len(result) >= 1
        assert result[0]["file"].endswith(".md")

    def test_search_in_system_finds_help(self, populated_env):
        h = ContextHandler(populated_env)
        result = h._search_in_system("pythonioencoding")
        assert len(result) >= 1


# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════


class TestCodeQuality:
    def test_no_bare_except(self):
        import ast
        source_file = SYSTEM_ROOT / "hub" / "context.py"
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                pytest.fail(f"Bare except at line {node.lineno} in context.py")
