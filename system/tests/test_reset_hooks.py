# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Kombinierte Flow-Tests fuer Skill- und Plugin-Reset-Hooks.

Diese Datei ergaenzt die fachlichen Tests in
``tests/test_skill_reset_hooks.py`` und ``tests/test_plugin_reset_hooks.py``
mit minimalistischen Flow-Tests, die ausschliesslich per ``monkeypatch`` die
Emission der Lifecycle-Hooks und die Reset-Logik isoliert ueberpruefen.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from core.hooks import hooks
from core.plugin_api import PluginRegistry
from hub.skills import SkillsHandler


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def skills_env(tmp_path):
    """Minimal environment for SkillsHandler reset flow tests."""
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
def skills_handler(skills_env):
    return SkillsHandler(skills_env)


@pytest.fixture
def plugin_registry():
    return PluginRegistry()


@pytest.fixture
def mock_emit(monkeypatch):
    """Monkeypatch ``hooks.emit`` and expose a MagicMock for assertions."""
    m = MagicMock()
    m.return_value = []
    monkeypatch.setattr(hooks, "emit", m)
    return m


# ═══════════════════════════════════════════════════════════════
# SKILL RESET FLOW
# ═══════════════════════════════════════════════════════════════


class TestSkillResetFlow:
    """Flow-Tests fuer Skill-Reset mit monkeypatching von hooks.emit und _reload."""

    def test_skill_reset_flow_emits_hooks_on_success(
        self, skills_handler, mock_emit, monkeypatch
    ):
        """Ein erfolgreicher Reset muss before/after_skill_reset emitieren."""
        monkeypatch.setattr(skills_handler, "_reload", lambda: (True, "reloaded"))

        success, msg = skills_handler._reset_skill("demo-skill")

        assert success is True
        assert "demo-skill" in msg

        mock_emit.assert_any_call("before_skill_reset", {"name": "demo-skill"})
        mock_emit.assert_any_call(
            "after_skill_reset", {"name": "demo-skill", "status": "ok"}
        )
        assert mock_emit.call_count == 2

    def test_skill_reset_flow_emits_after_hook_on_failure(
        self, skills_handler, mock_emit, monkeypatch
    ):
        """Auch ein fehlgeschlagener Reset muss after_skill_reset emitieren."""
        monkeypatch.setattr(
            skills_handler, "_reload", lambda: (False, "reload failed")
        )

        success, msg = skills_handler._reset_skill("demo-skill")

        assert success is False

        mock_emit.assert_any_call("before_skill_reset", {"name": "demo-skill"})
        mock_emit.assert_any_call(
            "after_skill_reset", {"name": "demo-skill", "status": "error"}
        )
        assert mock_emit.call_count == 2


# ═══════════════════════════════════════════════════════════════
# PLUGIN RESET FLOW
# ═══════════════════════════════════════════════════════════════


class TestPluginResetFlow:
    """Flow-Tests fuer Plugin-Reset mit monkeypatching von hooks.emit,
    unload_plugin und load_plugin.
    """

    def test_plugin_reset_flow_emits_hooks_on_success(
        self, plugin_registry, mock_emit, monkeypatch
    ):
        """Ein erfolgreicher Reset muss before/after_plugin_reset emitieren."""
        plugin_registry._plugins["demo-plugin"] = {
            "name": "demo-plugin",
            "version": "1.0.0",
            "manifest_path": "/tmp/demo-plugin/plugin.json",
        }

        monkeypatch.setattr(
            plugin_registry, "unload_plugin", lambda name: (True, "unloaded")
        )
        monkeypatch.setattr(
            plugin_registry,
            "load_plugin",
            lambda manifest_path: (True, "loaded"),
        )

        success, msg = plugin_registry.reset_plugin("demo-plugin")

        assert success is True
        assert "demo-plugin" in msg

        mock_emit.assert_any_call("before_plugin_reset", {"name": "demo-plugin"})
        mock_emit.assert_any_call(
            "after_plugin_reset", {"name": "demo-plugin", "status": "ok"}
        )
        assert mock_emit.call_count == 2

    def test_plugin_reset_flow_emits_after_hook_on_failure(
        self, plugin_registry, mock_emit, monkeypatch
    ):
        """Auch ein fehlgeschlagener Reload muss after_plugin_reset emitieren."""
        plugin_registry._plugins["demo-plugin"] = {
            "name": "demo-plugin",
            "version": "1.0.0",
            "manifest_path": "/tmp/demo-plugin/plugin.json",
        }

        monkeypatch.setattr(
            plugin_registry, "unload_plugin", lambda name: (True, "unloaded")
        )
        monkeypatch.setattr(
            plugin_registry,
            "load_plugin",
            lambda manifest_path: (False, "reload failed"),
        )

        success, msg = plugin_registry.reset_plugin("demo-plugin")

        assert success is False

        mock_emit.assert_any_call("before_plugin_reset", {"name": "demo-plugin"})
        mock_emit.assert_any_call(
            "after_plugin_reset", {"name": "demo-plugin", "status": "error"}
        )
        assert mock_emit.call_count == 2

    def test_plugin_reset_flow_unknown_plugin_emits_no_hooks(
        self, plugin_registry, mock_emit
    ):
        """Fuer ein unbekanntes Plugin duerfen keine Reset-Hooks emittiert werden."""
        success, msg = plugin_registry.reset_plugin("missing-plugin")

        assert success is False
        mock_emit.assert_not_called()
