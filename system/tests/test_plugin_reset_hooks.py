# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer Plugin-Reset-Hooks (before_plugin_reset / after_plugin_reset)."""

from unittest.mock import MagicMock, patch

import pytest

from core.plugin_api import PluginRegistry


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def registry():
    """Fresh PluginRegistry instance without any loaded plugins."""
    return PluginRegistry()


@pytest.fixture
def mock_hooks():
    """Fresh mock for core.hooks.hooks singleton."""
    m = MagicMock()
    m.emit.return_value = []
    return m


# ═══════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════


class TestPluginResetHooks:
    def test_reset_plugin_emits_before_and_after_hooks_success(
        self, registry, mock_hooks
    ):
        """reset_plugin muss before/after_plugin_reset emitieren, wenn Reload
        erfolgreich ist."""
        registry._plugins["demo-plugin"] = {
            "name": "demo-plugin",
            "version": "1.0.0",
            "manifest_path": "/tmp/demo-plugin/plugin.json",
        }

        with patch("core.hooks.hooks", mock_hooks):
            with patch.object(
                registry, "load_plugin", return_value=(True, "reloaded")
            ):
                success, msg = registry.reset_plugin("demo-plugin")

        assert success is True
        assert "demo-plugin" in msg

        mock_hooks.emit.assert_any_call(
            "before_plugin_reset", {"name": "demo-plugin"}
        )
        mock_hooks.emit.assert_any_call(
            "after_plugin_reset", {"name": "demo-plugin", "status": "ok"}
        )
        assert mock_hooks.emit.call_count == 2

    def test_reset_plugin_emits_after_hook_on_reload_failure(
        self, registry, mock_hooks
    ):
        """Auch beim Scheitern des Reloads muss after_plugin_reset mit
        status=error emittiert werden."""
        registry._plugins["demo-plugin"] = {
            "name": "demo-plugin",
            "version": "1.0.0",
            "manifest_path": "/tmp/demo-plugin/plugin.json",
        }

        with patch("core.hooks.hooks", mock_hooks):
            with patch.object(
                registry, "load_plugin", return_value=(False, "reload failed")
            ):
                success, msg = registry.reset_plugin("demo-plugin")

        assert success is False

        mock_hooks.emit.assert_any_call(
            "before_plugin_reset", {"name": "demo-plugin"}
        )
        mock_hooks.emit.assert_any_call(
            "after_plugin_reset", {"name": "demo-plugin", "status": "error"}
        )
        assert mock_hooks.emit.call_count == 2

    def test_reset_plugin_without_manifest_emits_ok_after_hook(
        self, registry, mock_hooks
    ):
        """Ohne bekannten Manifest-Pfad wird das Plugin entladen; after_plugin_reset
        muss trotzdem mit status=ok emittiert werden."""
        registry._plugins["demo-plugin"] = {
            "name": "demo-plugin",
            "version": "1.0.0",
            "manifest_path": None,
        }

        with patch("core.hooks.hooks", mock_hooks):
            success, msg = registry.reset_plugin("demo-plugin")

        assert success is True
        assert "entladen" in msg.lower()

        mock_hooks.emit.assert_any_call(
            "before_plugin_reset", {"name": "demo-plugin"}
        )
        mock_hooks.emit.assert_any_call(
            "after_plugin_reset", {"name": "demo-plugin", "status": "ok"}
        )
        assert mock_hooks.emit.call_count == 2

    def test_reset_plugin_unknown_plugin_emits_no_hooks(self, registry, mock_hooks):
        """Fuer ein nicht geladenes Plugin duerfen keine Hooks emittiert werden."""
        with patch("core.hooks.hooks", mock_hooks):
            success, msg = registry.reset_plugin("missing-plugin")

        assert success is False
        assert "nicht gefunden" in msg.lower()
        mock_hooks.emit.assert_not_called()
