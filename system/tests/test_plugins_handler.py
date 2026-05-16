# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for PluginsHandler (hub/plugins.py)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def plugins_env(tmp_path):
    base = tmp_path / "system"
    base.mkdir()
    (base / "data").mkdir()
    (base / "core").mkdir()
    (base / "plugins").mkdir()
    return base


@pytest.fixture
def mock_plugin_api():
    mock_plugins = MagicMock()
    mock_plugins.plugin_names = []
    mock_plugins._plugins = {}
    mock_plugins._tools = {}
    mock_plugins.tool_names = []
    mock_plugins.list_plugins.return_value = "Keine Plugins geladen."
    mock_plugins.load_plugin.return_value = (True, "Plugin geladen")
    mock_plugins.unload_plugin.return_value = (True, "Plugin entladen")
    mock_plugins.inspect_plugin.return_value = (True, "Manifest OK")
    return mock_plugins


@pytest.fixture
def handler(plugins_env, mock_plugin_api):
    mock_module = MagicMock()
    mock_module.plugins = mock_plugin_api
    with patch.dict(sys.modules, {"core.plugin_api": mock_module, "core": MagicMock(), "core.capabilities": MagicMock()}):
        from hub.plugins import PluginsHandler
        h = PluginsHandler(plugins_env)
    return h


class TestPluginsHandlerInit:
    def test_profile_name(self, handler):
        assert handler.profile_name == "plugins"

    def test_target_file(self, handler, plugins_env):
        assert handler.target_file == plugins_env / "core" / "plugin_api.py"

    def test_operations(self, handler):
        ops = handler.get_operations()
        expected = {"list", "inspect", "load", "unload", "tools", "info", "create", "caps", "trust", "audit"}
        assert set(ops.keys()) == expected


class TestHandleRouting:
    def test_unknown_operation(self, handler, mock_plugin_api):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("", [])
            assert ok

    def test_list_operation(self, handler, mock_plugin_api):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("list", [])
            assert ok
            mock_plugin_api.list_plugins.assert_called_once()

    def test_load_with_path(self, handler, mock_plugin_api, plugins_env):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("load", ["plugins/test/plugin.json"])
            assert ok
            mock_plugin_api.load_plugin.assert_called_once()

    def test_unload_with_name(self, handler, mock_plugin_api):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("unload", ["test-plugin"])
            assert ok
            mock_plugin_api.unload_plugin.assert_called_once_with("test-plugin")

    def test_inspect_with_path(self, handler, mock_plugin_api, plugins_env):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("inspect", ["plugins/test/plugin.json"])
            assert ok
            mock_plugin_api.inspect_plugin.assert_called_once()

    def test_load_no_args_shows_usage(self, handler, mock_plugin_api):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("load", [])
            assert not ok
            assert "Usage" in msg


class TestCreateManifest:
    def test_create_success(self, handler, plugins_env, mock_plugin_api):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("create", ["test-plugin"])
        assert ok
        assert "erstellt" in msg
        manifest_path = plugins_env / "plugins" / "test-plugin" / "plugin.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["name"] == "test-plugin"
        assert data["manifest_version"] == "1.1"

    def test_create_duplicate_fails(self, handler, plugins_env, mock_plugin_api):
        plugin_dir = plugins_env / "plugins" / "existing"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text('{"name":"existing"}', encoding="utf-8")
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("create", ["existing"])
        assert not ok
        assert "existiert bereits" in msg

    def test_create_default_name(self, handler, plugins_env, mock_plugin_api):
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("create", [])
        assert ok
        manifest_path = plugins_env / "plugins" / "my-plugin" / "plugin.json"
        assert manifest_path.exists()


class TestListTools:
    def test_no_tools(self, handler, mock_plugin_api):
        mock_plugin_api.tool_names = []
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("tools", [])
        assert ok
        assert "Keine Plugin-Tools" in msg

    def test_with_tools(self, handler, mock_plugin_api):
        mock_plugin_api.tool_names = ["tool1", "tool2"]
        mock_plugin_api._tools = {
            "tool1": {"description": "First tool", "plugin": "p1"},
            "tool2": {"description": "Second tool", "plugin": "p2"},
        }
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("tools", [])
        assert ok
        assert "tool1" in msg
        assert "tool2" in msg
        assert "2 Tools" in msg


class TestPluginInfo:
    def test_info_not_found(self, handler, mock_plugin_api):
        mock_plugin_api._plugins = {}
        mock_plugin_api.plugin_names = []
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("info", ["nonexistent"])
        assert not ok
        assert "nicht gefunden" in msg

    def test_info_found(self, handler, mock_plugin_api):
        mock_plugin_api._plugins = {
            "test-plugin": {
                "version": "1.0.0",
                "description": "Test Plugin",
                "author": "tester",
                "loaded_at": "2026-01-01 12:00:00",
                "manifest_path": "/path/to/plugin.json",
                "activation": {"mode": "auto", "enabled": True},
                "providers": ["ollama"],
                "models": ["qwen"],
                "hooks": ["after_startup"],
                "handlers": ["test run"],
                "workflows": ["wf1"],
            }
        }
        mock_module = MagicMock()
        mock_module.plugins = mock_plugin_api
        with patch.dict(sys.modules, {"core.plugin_api": mock_module}):
            ok, msg = handler.handle("info", ["test-plugin"])
        assert ok
        assert "test-plugin" in msg
        assert "1.0.0" in msg
        assert "tester" in msg
        assert "auto" in msg
