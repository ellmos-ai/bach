# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Unit tests for standalone plugins module."""
from pathlib import Path
import pytest
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from plugins import PluginRegistry, PluginMetadata


def test_plugin_registry_basics():
    registry = PluginRegistry()
    assert registry.status()["total_plugins"] == 0

    ok_load, msg_load = registry.load_plugin({
        "name": "test_plugin",
        "version": "1.2.0",
        "description": "A test plugin",
        "tools": ["test_tool_1", "test_tool_2"],
        "capabilities": ["fs.read", "net.http"],
        "trust_level": "standard",
    })
    assert ok_load is True
    assert "[OK]" in msg_load

    plugin = registry.get_plugin("test_plugin")
    assert plugin is not None
    assert plugin.version == "1.2.0"
    assert plugin.enabled is True

    # Tools and capabilities
    tools = registry.list_tools()
    assert len(tools) == 2
    assert tools[0]["tool"] == "test_tool_1"

    caps = registry.list_capabilities()
    assert "test_plugin" in caps
    assert "fs.read" in caps["test_plugin"]


def test_plugin_enable_disable_trust_and_unload():
    registry = PluginRegistry()
    registry.load_plugin({
        "name": "alpha",
        "version": "1.0.0",
        "tools": ["alpha_calc"],
    })

    # Disable
    ok_dis, _ = registry.disable_plugin("alpha")
    assert ok_dis is True
    assert len(registry.list_tools()) == 0

    # Enable
    ok_en, _ = registry.enable_plugin("alpha")
    assert ok_en is True
    assert len(registry.list_tools()) == 1

    # Trust
    ok_tr, _ = registry.set_trust_level("alpha", "trusted")
    assert ok_tr is True
    assert registry.get_plugin("alpha").trust_level == "trusted"

    # Unload
    ok_un, _ = registry.unload_plugin("alpha")
    assert ok_un is True
    assert registry.get_plugin("alpha") is None
    assert registry.status()["total_plugins"] == 0


def test_plugin_inspect_and_audit():
    registry = PluginRegistry()
    ok_ins, data_ins = registry.inspect_plugin({
        "name": "inspector_gadget",
        "version": "2.0.0",
        "capabilities": ["shell.exec"],
    })
    assert ok_ins is True
    assert data_ins["name"] == "inspector_gadget"

    # Bad inspect
    ok_bad, _ = registry.inspect_plugin({})
    assert ok_bad is False

    # Audit history
    registry.load_plugin({"name": "audited_mod"})
    log = registry.audit_log()
    assert len(log) >= 1
    assert log[-1]["target"] == "audited_mod"
