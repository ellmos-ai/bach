# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for SyncHandler.

Tests filesystem-to-DB synchronization for skills and tools.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.sync import SyncHandler


@pytest.fixture
def sync_env(tmp_path, monkeypatch):
    """SyncHandler with temporary filesystem and DB."""
    db_path = tmp_path / "data" / "bach.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, type TEXT, category TEXT, path TEXT,
            content TEXT, content_hash TEXT, description TEXT,
            dist_type INTEGER DEFAULT 2,
            created_at TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, type TEXT, category TEXT, path TEXT,
            content TEXT, content_hash TEXT, template_content TEXT,
            description TEXT, is_available INTEGER DEFAULT 1,
            dist_type INTEGER DEFAULT 2,
            created_at TEXT, updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    handler = SyncHandler(tmp_path)
    monkeypatch.setattr(handler, "db_path", db_path)
    return handler, tmp_path, db_path


class TestSyncBasic:
    def test_get_operations(self, sync_env):
        handler, _, _ = sync_env
        ops = handler.get_operations()
        assert "skills" in ops
        assert "tools" in ops
        assert "all" in ops
        assert "status" in ops

    def test_profile_name(self, sync_env):
        handler, _, _ = sync_env
        assert handler.profile_name == "sync"

    def test_unknown_operation_shows_status(self, sync_env):
        handler, _, _ = sync_env
        ok, msg = handler.handle("nonexistent", [])
        assert ok is True


class TestSyncSkills:
    def test_empty_dir_syncs_nothing(self, sync_env):
        handler, _, _ = sync_env
        ok, msg = handler.handle("skills", [])
        assert ok is True
        assert "0 aktualisiert" in msg
        assert "0 neu" in msg

    def test_new_skill_discovered(self, sync_env):
        handler, base, db_path = sync_env
        skill_file = base / "skills" / "test_skill.md"
        skill_file.write_text("# Test Skill\nEine Beschreibung.", encoding="utf-8")

        ok, msg = handler.handle("skills", [])
        assert ok is True
        assert "1 neu" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT name, path, content FROM skills WHERE name = 'test_skill'").fetchone()
        conn.close()
        assert row is not None
        assert "test_skill" in row[1]
        assert "# Test Skill" in row[2]

    def test_unchanged_skill_not_resynced(self, sync_env):
        handler, base, _ = sync_env
        skill_file = base / "skills" / "stable.md"
        skill_file.write_text("Stable content", encoding="utf-8")

        handler.handle("skills", [])
        ok, msg = handler.handle("skills", [])
        assert "0 aktualisiert" in msg
        assert "1 OK" in msg or "unchanged" in msg.lower()

    def test_modified_skill_resynced(self, sync_env):
        handler, base, db_path = sync_env
        skill_file = base / "skills" / "evolving.md"
        skill_file.write_text("Version 1", encoding="utf-8")
        handler.handle("skills", [])

        skill_file.write_text("Version 2 with changes", encoding="utf-8")
        ok, msg = handler.handle("skills", [])
        assert "1 aktualisiert" in msg

        conn = sqlite3.connect(str(db_path))
        content = conn.execute("SELECT content FROM skills WHERE name = 'evolving'").fetchone()[0]
        conn.close()
        assert "Version 2" in content

    def test_dry_run_no_db_change(self, sync_env):
        handler, base, db_path = sync_env
        skill_file = base / "skills" / "drytest.md"
        skill_file.write_text("Should not appear in DB", encoding="utf-8")

        ok, msg = handler.handle("skills", ["--dry-run"])
        assert ok is True

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        conn.close()
        assert count == 0

    def test_force_resyncs_unchanged(self, sync_env):
        handler, base, _ = sync_env
        skill_file = base / "skills" / "forced.md"
        skill_file.write_text("Same content", encoding="utf-8")
        handler.handle("skills", [])

        ok, msg = handler.handle("skills", ["--force"])
        assert "1 aktualisiert" in msg

    def test_subdirectory_skills_found(self, sync_env):
        handler, base, db_path = sync_env
        sub = base / "skills" / "workflows"
        sub.mkdir()
        (sub / "workflow1.md").write_text("Workflow text", encoding="utf-8")

        ok, msg = handler.handle("skills", [])
        assert "1 neu" in msg

    def test_hidden_files_skipped(self, sync_env):
        handler, base, db_path = sync_env
        (base / "skills" / "_internal.md").write_text("Hidden", encoding="utf-8")
        (base / "skills" / ".hidden.md").write_text("Hidden too", encoding="utf-8")
        (base / "skills" / "visible.md").write_text("Visible", encoding="utf-8")

        handler.handle("skills", [])
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        conn.close()
        assert count == 1


class TestSyncTools:
    def test_empty_dir(self, sync_env):
        handler, _, _ = sync_env
        ok, msg = handler.handle("tools", [])
        assert ok is True

    def test_new_tool_discovered(self, sync_env):
        handler, base, db_path = sync_env
        tool_file = base / "tools" / "my_tool.py"
        tool_file.write_text('"""My tool description."""\ndef run(): pass', encoding="utf-8")

        ok, msg = handler.handle("tools", [])
        assert ok is True
        assert "1 neu" in msg

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT name FROM tools WHERE name = 'my_tool'").fetchone()
        conn.close()
        assert row is not None

    def test_underscore_tools_skipped(self, sync_env):
        handler, base, db_path = sync_env
        (base / "tools" / "__init__.py").write_text("", encoding="utf-8")
        (base / "tools" / "_helper.py").write_text("helper", encoding="utf-8")
        (base / "tools" / "real_tool.py").write_text("real", encoding="utf-8")

        handler.handle("tools", [])
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
        conn.close()
        assert count == 1


class TestSyncAll:
    def test_syncs_both(self, sync_env):
        handler, base, db_path = sync_env
        (base / "skills" / "s1.md").write_text("Skill 1", encoding="utf-8")
        (base / "tools" / "t1.py").write_text("Tool 1", encoding="utf-8")

        ok, msg = handler.handle("all", [])
        assert ok is True
        assert "SYNC SKILLS" in msg
        assert "SYNC TOOLS" in msg


class TestHashConsistency:
    def test_same_content_same_hash(self, sync_env):
        handler, _, _ = sync_env
        h1 = handler._compute_hash("Hello World")
        h2 = handler._compute_hash("Hello World")
        assert h1 == h2

    def test_different_content_different_hash(self, sync_env):
        handler, _, _ = sync_env
        h1 = handler._compute_hash("Version A")
        h2 = handler._compute_hash("Version B")
        assert h1 != h2

    def test_path_separators_normalized(self, sync_env):
        handler, base, db_path = sync_env
        sub = base / "skills" / "sub"
        sub.mkdir()
        (sub / "test.md").write_text("Test", encoding="utf-8")

        handler.handle("skills", [])
        conn = sqlite3.connect(str(db_path))
        path = conn.execute("SELECT path FROM skills WHERE name = 'test'").fetchone()[0]
        conn.close()
        assert "\\" not in path
