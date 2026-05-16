# SPDX-License-Identifier: MIT
"""Tests fuer hub/plugins.py — PluginsHandler (Standalone, kein Server/DB noetig)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.plugins import PluginsHandler


@pytest.fixture
def plugins_env(tmp_path):
    """Erstellt PluginsHandler mit tmp_path als base_path."""
    h = PluginsHandler(tmp_path)
    return h


@pytest.fixture
def mock_plugin_api():
    """Mock fuer core.plugin_api.plugins — wird per patch in handle() injiziert."""
    mock = MagicMock()
    mock.list_plugins.return_value = "Geladene Plugins: test-plugin (v1.0)"
    mock.plugin_names = ["test-plugin"]
    mock.tool_names = []
    mock._plugins = {}
    mock._tools = {}
    mock.inspect_plugin.return_value = (True, "Manifest OK")
    mock.load_plugin.return_value = (True, "Plugin geladen")
    mock.unload_plugin.return_value = (True, "Plugin entladen")
    return mock


# ── Properties ──────────────────────────────────────────────

class TestProperties:
    def test_profile_name(self, plugins_env):
        assert plugins_env.profile_name == "plugins"

    def test_target_file(self, plugins_env):
        h = plugins_env
        assert h.target_file == h.base_path / "core" / "plugin_api.py"

    def test_get_operations_keys(self, plugins_env):
        ops = plugins_env.get_operations()
        expected = {"list", "inspect", "load", "unload", "tools", "info", "create", "caps", "trust", "audit"}
        assert set(ops.keys()) == expected


# ── Handle: Unknown / Fallback ──────────────────────────────

class TestHandleUnknown:
    def test_unknown_operation_returns_usage(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("nonexistent_op", [])
        assert ok is False
        assert "Usage:" in text

    def test_inspect_without_args_returns_usage(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("inspect", [])
        assert ok is False
        assert "Usage:" in text

    def test_load_without_args_returns_usage(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("load", [])
        assert ok is False
        assert "Usage:" in text


# ── Handle: list ─────────────────────────────────────────────

class TestHandleList:
    def test_list_operation(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("list", [])
        assert ok is True
        assert "test-plugin" in text

    def test_empty_operation_falls_to_list(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("", [])
        assert ok is True


# ── Handle: inspect / load / unload ─────────────────────────

class TestHandleLoadUnload:
    def test_inspect_with_path(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("inspect", ["plugins/test/plugin.json"])
        assert ok is True
        mock_plugin_api.inspect_plugin.assert_called_once()

    def test_load_with_path(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("load", ["plugins/test/plugin.json"])
        assert ok is True
        mock_plugin_api.load_plugin.assert_called_once()

    def test_unload_by_name(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("unload", ["test-plugin"])
        assert ok is True
        mock_plugin_api.unload_plugin.assert_called_once_with("test-plugin")

    def test_unload_without_args_returns_usage(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("unload", [])
        assert ok is False
        assert "Usage:" in text


# ── Handle: tools ────────────────────────────────────────────

class TestHandleTools:
    def test_tools_empty(self, plugins_env, mock_plugin_api):
        mock_plugin_api.tool_names = []
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("tools", [])
        assert ok is True
        assert "Keine Plugin-Tools" in text

    def test_tools_with_registered_tools(self, plugins_env, mock_plugin_api):
        mock_plugin_api.tool_names = ["search", "summarize"]
        mock_plugin_api._tools = {
            "search": {"description": "Suchen", "plugin": "test-plugin"},
            "summarize": {"description": "Zusammenfassen", "plugin": "test-plugin"},
        }
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("tools", [])
        assert ok is True
        assert "PLUGIN-TOOLS" in text
        assert "search" in text
        assert "2 Tools" in text


# ── Handle: info ─────────────────────────────────────────────

class TestHandleInfo:
    def test_info_plugin_not_found(self, plugins_env, mock_plugin_api):
        mock_plugin_api._plugins = {}
        mock_plugin_api.plugin_names = []
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("info", ["ghost"])
        assert ok is False
        assert "nicht gefunden" in text

    def test_info_plugin_found(self, plugins_env, mock_plugin_api):
        mock_plugin_api._plugins = {
            "test-plugin": {
                "version": "1.0.0",
                "description": "Ein Test-Plugin",
                "author": "tester",
                "loaded_at": "2026-01-01T00:00:00.000",
                "hooks": [],
                "handlers": [],
                "workflows": [],
            }
        }
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("info", ["test-plugin"])
        assert ok is True
        assert "test-plugin" in text
        assert "1.0.0" in text

    def test_info_without_args_returns_usage(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("info", [])
        assert ok is False
        assert "Usage:" in text


# ── Handle: create (Scaffolding) ─────────────────────────────

class TestHandleCreate:
    def test_create_default_name(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("create", [])
        assert ok is True
        # Default-Name ist "my-plugin"
        manifest_path = plugins_env.base_path / "plugins" / "my-plugin" / "plugin.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["name"] == "my-plugin"

    def test_create_custom_name(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("create", ["cool-plugin"])
        assert ok is True
        assert "cool-plugin" in text
        handler_path = plugins_env.base_path / "plugins" / "cool-plugin" / "handlers.py"
        assert handler_path.exists()

    def test_create_already_exists(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            plugins_env.handle("create", ["dup-plugin"])
            ok, text = plugins_env.handle("create", ["dup-plugin"])
        assert ok is False
        assert "existiert bereits" in text

    def test_create_dry_run(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("create", ["dry-plugin"], dry_run=True)
        assert ok is True
        assert "DRY-RUN" in text
        manifest_path = plugins_env.base_path / "plugins" / "dry-plugin" / "plugin.json"
        assert not manifest_path.exists()


# ── Handle: trust / audit / caps ─────────────────────────────

class TestHandleTrustAuditCaps:
    def test_trust_without_enough_args_returns_usage(self, plugins_env, mock_plugin_api):
        with patch.dict("sys.modules", {"core": MagicMock(), "core.plugin_api": MagicMock(plugins=mock_plugin_api)}):
            ok, text = plugins_env.handle("trust", ["only-one-arg"])
        assert ok is False
        assert "Usage:" in text

    def test_caps_delegates_to_capability_manager(self, plugins_env, mock_plugin_api):
        mock_cap = MagicMock()
        mock_cap.get_profiles.return_value = "Profile-Info"
        mock_cap.status.return_value = "Status-Info"
        mock_caps_mod = MagicMock(capability_manager=mock_cap)
        with patch.dict("sys.modules", {
            "core": MagicMock(),
            "core.plugin_api": MagicMock(plugins=mock_plugin_api),
            "core.capabilities": mock_caps_mod,
        }):
            ok, text = plugins_env.handle("caps", [])
        assert ok is True
        assert "Profile-Info" in text

    def test_audit_delegates_to_capability_manager(self, plugins_env, mock_plugin_api):
        mock_cap = MagicMock()
        mock_cap.get_audit_log.return_value = "Audit-Log-Data"
        mock_caps_mod = MagicMock(capability_manager=mock_cap)
        with patch.dict("sys.modules", {
            "core": MagicMock(),
            "core.plugin_api": MagicMock(plugins=mock_plugin_api),
            "core.capabilities": mock_caps_mod,
        }):
            ok, text = plugins_env.handle("audit", [])
        assert ok is True
        assert "Audit-Log-Data" in text

    def test_audit_with_limit(self, plugins_env, mock_plugin_api):
        mock_cap = MagicMock()
        mock_cap.get_audit_log.return_value = "Limited Audit"
        mock_caps_mod = MagicMock(capability_manager=mock_cap)
        with patch.dict("sys.modules", {
            "core": MagicMock(),
            "core.plugin_api": MagicMock(plugins=mock_plugin_api),
            "core.capabilities": mock_caps_mod,
        }):
            ok, text = plugins_env.handle("audit", ["5"])
        mock_cap.get_audit_log.assert_called_once_with(5)
