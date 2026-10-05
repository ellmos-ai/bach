# -*- coding: utf-8 -*-
"""Registry-/API-Tests fuer Skill-/Plugin-Reset-Hooks (P3-Vision 1404).

Diese Datei enthaelt zentrale Meta-Tests: Sie prueft, dass die vier
Reset-Events im HookRegistry bekannt und broadcast-faehig sind, und dass
SkillsHandler sowie PluginsHandler die Operation ``reset`` anbieten.

Die eigentliche Emission der Lifecycle-Hooks wird in
``tests/test_skill_reset_hooks.py`` und ``tests/test_plugin_reset_hooks.py``
abgedeckt.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.hooks import HookRegistry, hooks
from core.plugin_api import PluginRegistry
from hub.plugins import PluginsHandler
from hub.skills import SkillsHandler


RESET_EVENTS = [
    "before_skill_reset",
    "after_skill_reset",
    "before_plugin_reset",
    "after_plugin_reset",
]


@pytest.fixture(autouse=True)
def reset_hooks_singleton():
    """Globales HookRegistry-Singleton zwischen Tests zuruecksetzen."""
    hooks._listeners.clear()
    hooks._interceptors.clear()
    hooks._log.clear()
    hooks.last_interceptor_results.clear()


@pytest.mark.parametrize("event", RESET_EVENTS)
def test_reset_events_are_known(event: str):
    """Alle vier Reset-Events muessen in KNOWN_EVENTS registriert sein."""
    assert event in HookRegistry.KNOWN_EVENTS, f"{event} fehlt in KNOWN_EVENTS"


@pytest.mark.parametrize("event", RESET_EVENTS)
def test_reset_events_are_distributed(event: str):
    """after_* Reset-Events sollen broadcast-faehig sein."""
    assert event in HookRegistry.DISTRIBUTED_EVENTS, f"{event} fehlt in DISTRIBUTED_EVENTS"


def test_skills_handler_get_operations_includes_reset():
    """SkillsHandler muss 'reset' als Operation anbieten."""
    handler = SkillsHandler(Path("/tmp"))
    ops = handler.get_operations()
    assert "reset" in ops
    assert "before" in ops["reset"].lower() and "after" in ops["reset"].lower()


def test_plugins_handler_get_operations_includes_reset():
    """PluginsHandler muss 'reset' als Operation anbieten."""
    handler = PluginsHandler(Path("/tmp"))
    ops = handler.get_operations()
    assert "reset" in ops
    assert "before" in ops["reset"].lower() and "after" in ops["reset"].lower()


def test_plugins_handler_handle_routes_reset():
    """PluginsHandler.handle leitet 'reset <name>' an plugins.reset_plugin weiter."""
    handler = PluginsHandler(Path("/tmp"))
    with patch("core.plugin_api.plugins") as mock_plugins:
        mock_plugins.reset_plugin.return_value = (True, "reset ok")
        success, msg = handler.handle("reset", ["mein-plugin"])
    assert success is True
    assert msg == "reset ok"
    mock_plugins.reset_plugin.assert_called_once_with("mein-plugin")


def test_reset_plugin_emits_before_and_after_hooks():
    """reset_plugin emittiert before_plugin_reset und after_plugin_reset."""
    registry = PluginRegistry()
    registry._plugins["demo"] = {
        "name": "demo",
        "manifest_path": "/tmp/demo/plugin.json",
    }

    with patch("core.hooks.hooks.emit") as mock_emit:
        with patch.object(registry, "unload_plugin", return_value=(True, "unloaded")):
            with patch.object(registry, "load_plugin", return_value=(True, "loaded")):
                success, msg = registry.reset_plugin("demo")

    assert success is True
    mock_emit.assert_any_call("before_plugin_reset", {"name": "demo"})
    mock_emit.assert_any_call(
        "after_plugin_reset", {"name": "demo", "status": "ok"}
    )


def test_reset_plugin_emits_after_hook_on_unload_failure():
    """Auch beim Scheitern des Unloads muss after_plugin_reset emittiert werden."""
    registry = PluginRegistry()
    registry._plugins["demo"] = {
        "name": "demo",
        "manifest_path": "/tmp/demo/plugin.json",
    }

    with patch("core.hooks.hooks.emit") as mock_emit:
        with patch.object(
            registry, "unload_plugin", return_value=(False, "unload failed")
        ):
            success, msg = registry.reset_plugin("demo")

    assert success is False
    mock_emit.assert_any_call("before_plugin_reset", {"name": "demo"})
    mock_emit.assert_any_call(
        "after_plugin_reset", {"name": "demo", "status": "error"}
    )
