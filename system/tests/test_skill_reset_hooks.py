# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer Skill-Reset-Hooks (before_skill_reset / after_skill_reset)."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    """Minimal environment for SkillsHandler reset hook tests."""
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
def mock_hooks():
    """Fresh mock for core.hooks.hooks singleton."""
    m = MagicMock()
    m.emit.return_value = []
    return m


# ═══════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════


class TestSkillResetHooks:
    def test_reset_skill_emits_before_and_after_hooks(self, handler, mock_hooks):
        """_reset_skill muss before_skill_reset und after_skill_reset emitieren."""
        with patch("core.hooks.hooks", mock_hooks):
            with patch.object(handler, "_reload", return_value=(True, "reloaded")):
                success, msg = handler._reset_skill("demo-skill")

        assert success is True
        assert "demo-skill" in msg

        mock_hooks.emit.assert_any_call("before_skill_reset", {"name": "demo-skill"})
        mock_hooks.emit.assert_any_call(
            "after_skill_reset", {"name": "demo-skill", "status": "ok"}
        )
        assert mock_hooks.emit.call_count == 2

    def test_reset_skill_emits_after_hook_on_reload_failure(self, handler, mock_hooks):
        """Auch beim Scheitern des Reloads muss after_skill_reset mit status=error emittiert werden."""
        with patch("core.hooks.hooks", mock_hooks):
            with patch.object(handler, "_reload", return_value=(False, "reload failed")):
                success, msg = handler._reset_skill("demo-skill")

        assert success is False
        mock_hooks.emit.assert_any_call("before_skill_reset", {"name": "demo-skill"})
        mock_hooks.emit.assert_any_call(
            "after_skill_reset", {"name": "demo-skill", "status": "error"}
        )
        assert mock_hooks.emit.call_count == 2
