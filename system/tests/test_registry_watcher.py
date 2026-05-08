# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for the layout-aware registry watcher."""

import importlib.util
import sqlite3
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
MAINTENANCE_DIR = SYSTEM_ROOT / "tools" / "maintenance"

_original_platform = sys.platform
sys.platform = "linux_fake_for_test"
try:
    spec = importlib.util.spec_from_file_location(
        "registry_watcher_test_module",
        MAINTENANCE_DIR / "registry_watcher.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    RegistryWatcher = module.RegistryWatcher
finally:
    sys.platform = _original_platform


def _init_base(tmp_path):
    base = tmp_path / "system"
    (base / "data").mkdir(parents=True)
    (base / "tools").mkdir()
    (base / "skills" / "workflows").mkdir(parents=True)
    (base / "agents").mkdir()

    db_path = base / "data" / "bach.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE tools (
                name TEXT,
                path TEXT,
                type TEXT,
                category TEXT,
                command TEXT,
                dist_type INTEGER DEFAULT 2,
                is_available INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE skills (
                name TEXT,
                path TEXT,
                type TEXT,
                category TEXT,
                dist_type INTEGER DEFAULT 2
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE bach_agents (
                name TEXT,
                skill_path TEXT,
                is_active INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE partner_recognition (
                partner_name TEXT,
                status TEXT,
                partner_type TEXT
            )
            """
        )

    return base, db_path


def test_registry_watcher_separates_current_tools_from_external_and_stale_rows(tmp_path):
    base, db_path = _init_base(tmp_path)
    (base / "tools" / "current_tool.py").write_text("print('ok')\n", encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO tools (name, path, type, category, command, is_available)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            [
                ("current_tool", "tools/current_tool.py", "python", "general", None),
                ("legacy_tool", "tools/legacy_tool.py", "python", "general", None),
                ("git", None, "command", "external", "git"),
            ],
        )

    result = RegistryWatcher(base_path=base).check_tools()

    assert result["db_count"] == 3
    assert result["managed_db_count"] == 2
    assert result["fs_count"] == 1
    assert result["valid"] == ["current_tool"]
    assert result["orphan_files"] == []
    assert [item["name"] for item in result["stale_db_entries"]] == ["legacy_tool"]
    assert [item["name"] for item in result["external_entries"]] == ["git"]


def test_registry_watcher_aligns_skills_with_sync_scope_and_flags_orphans(tmp_path):
    base, db_path = _init_base(tmp_path)
    (base / "skills" / "workflows" / "current.md").write_text("# Current\n", encoding="utf-8")
    (base / "skills" / "workflows" / "orphan.md").write_text("# Orphan\n", encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO skills (name, path, type, category, dist_type)
            VALUES (?, ?, ?, ?, 2)
            """,
            [
                ("current", "skills/workflows/current.md", "protocol", "workflows"),
                ("old_help", "skills/help/old.txt", "file", "legacy"),
                ("agent_note", "agents/bueroassistent.txt", "file", "legacy"),
                ("legacy_abs", "C:/legacy/skill.md", "file", "legacy"),
            ],
        )

    watcher = RegistryWatcher(base_path=base)
    result = watcher.check_skills()

    assert result["valid"] == ["current"]
    assert result["orphan_files"] == ["skills/workflows/orphan.md"]
    assert [item["name"] for item in result["stale_db_entries"]] == ["old_help"]
    assert [item["name"] for item in result["historical_entries"]] == ["agent_note"]
    assert [item["name"] for item in result["external_entries"]] == ["legacy_abs"]
    assert watcher._actionable_count(result) == 1


def test_registry_summary_counts_only_actionable_issues(tmp_path):
    base, db_path = _init_base(tmp_path)
    (base / "tools" / "current_tool.py").write_text("print('ok')\n", encoding="utf-8")
    (base / "skills" / "workflows" / "orphan.md").write_text("# Orphan\n", encoding="utf-8")
    (base / "agents" / "bueroassistent.txt").write_text("Agent\n", encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tools (name, path, type, category, command, is_available)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            ("current_tool", "tools/current_tool.py", "python", "general", None),
        )
        conn.execute(
            """
            INSERT INTO bach_agents (name, skill_path, is_active)
            VALUES (?, ?, 1)
            """,
            ("bueroassistent", "agents/bueroassistent.txt"),
        )
        conn.execute(
            """
            INSERT INTO partner_recognition (partner_name, status, partner_type)
            VALUES (?, ?, ?)
            """,
            ("Claude", "active", "llm"),
        )

    summary = RegistryWatcher(base_path=base).check_all()["summary"]

    assert summary["actionable_issues"] == 1
    assert summary["stale_entries"] == 0
    assert summary["ignored_entries"] == 0
    assert summary["healthy"] is False
