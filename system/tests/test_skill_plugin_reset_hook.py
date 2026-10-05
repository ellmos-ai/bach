# -*- coding: utf-8 -*-
"""Lifecycle-Hook-Emission fuer Skill-/Plugin-Reset (Task #1542).

Diese Datei deckt die tatsaechliche Emission der Reset-Hooks ab:
- before_skill_reset / after_skill_reset
- before_plugin_reset / after_plugin_reset

Es werden sowohl die internen Reset-Methoden als auch das Handler-Routing
ueber ``SkillsHandler`` und ``PluginsHandler`` mit Stub-Registries getestet.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.hooks import hooks
from core.plugin_api import PluginRegistry
from hub.plugins import PluginsHandler
from hub.skills import SkillsHandler


@pytest.fixture(autouse=True)
def reset_hooks_singleton():
    """HookRegistry-Singleton zwischen Tests zuruecksetzen."""
    hooks._listeners.clear()
    hooks._interceptors.clear()
    hooks._log.clear()
    hooks.last_interceptor_results.clear()


class StubPluginRegistry(PluginRegistry):
    """PluginRegistry mit stub-basiertem unload/load fuer Reset-Tests."""

    def __init__(self, name: str = "demo"):
        super().__init__()
        self._plugins[name] = {
            "name": name,
            "manifest_path": f"/tmp/{name}/plugin.json",
        }

    def unload_plugin(self, name: str) -> tuple:
        return True, f"{name} unloaded"

    def load_plugin(self, manifest_path: str) -> tuple:
        return True, f"{manifest_path} loaded"


class TestSkillResetHooks:
    """Skill-Reset Hook-Emission."""

    def test_reset_skill_emits_before_and_after_hooks(self):
        handler = SkillsHandler(Path("/tmp"))
        with patch("core.hooks.hooks.emit") as mock_emit:
            with patch.object(handler, "_reload", return_value=(True, "reloaded")):
                success, msg = handler._reset_skill("demo")

        assert success is True
        mock_emit.assert_any_call("before_skill_reset", {"name": "demo"})
        mock_emit.assert_any_call(
            "after_skill_reset", {"name": "demo", "status": "ok"}
        )

    def test_reset_skill_emits_after_hook_on_reload_failure(self):
        handler = SkillsHandler(Path("/tmp"))
        with patch("core.hooks.hooks.emit") as mock_emit:
            with patch.object(handler, "_reload", return_value=(False, "reload failed")):
                success, msg = handler._reset_skill("demo")

        assert success is False
        mock_emit.assert_any_call("before_skill_reset", {"name": "demo"})
        mock_emit.assert_any_call(
            "after_skill_reset", {"name": "demo", "status": "error"}
        )

    def test_skills_handler_reset_routes_to_reset_skill(self):
        handler = SkillsHandler(Path("/tmp"))
        with patch("core.hooks.hooks.emit") as mock_emit:
            with patch.object(handler, "_reload", return_value=(True, "reloaded")):
                success, msg = handler.handle("reset", ["demo"])

        assert success is True
        assert "SKILL RESET: demo" in msg
        mock_emit.assert_any_call("before_skill_reset", {"name": "demo"})
        mock_emit.assert_any_call(
            "after_skill_reset", {"name": "demo", "status": "ok"}
        )


class TestPluginResetHooks:
    """Plugin-Reset Hook-Emission."""

    def test_plugins_handler_reset_emits_hooks(self):
        handler = PluginsHandler(Path("/tmp"))
        registry = StubPluginRegistry("demo")

        with patch("core.hooks.hooks.emit") as mock_emit:
            with patch("core.plugin_api.plugins", registry):
                success, msg = handler.handle("reset", ["demo"])

        assert success is True
        mock_emit.assert_any_call("before_plugin_reset", {"name": "demo"})
        mock_emit.assert_any_call(
            "after_plugin_reset", {"name": "demo", "status": "ok"}
        )

    def test_plugins_handler_reset_emits_error_hook_on_load_failure(self):
        handler = PluginsHandler(Path("/tmp"))
        registry = StubPluginRegistry("demo")
        registry.load_plugin = lambda manifest_path: (False, "load failed")

        with patch("core.hooks.hooks.emit") as mock_emit:
            with patch("core.plugin_api.plugins", registry):
                success, msg = handler.handle("reset", ["demo"])

        assert success is False
        mock_emit.assert_any_call("before_plugin_reset", {"name": "demo"})
        mock_emit.assert_any_call(
            "after_plugin_reset", {"name": "demo", "status": "error"}
        )
