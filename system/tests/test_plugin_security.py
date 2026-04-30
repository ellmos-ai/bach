# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Security regression tests for plugin, skill, and MCP import paths."""

import json
import sys
from pathlib import Path


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def _init_base(tmp_path):
    base = tmp_path / "system"
    (base / "data").mkdir(parents=True)
    (base / "skills").mkdir(parents=True)
    (base / "agents" / "_experts").mkdir(parents=True)
    (base / "plugins").mkdir(parents=True)
    return base


def test_plugin_load_blocks_code_injection_patterns(tmp_path):
    from core.plugin_api import PluginRegistry

    base = _init_base(tmp_path)
    plugin_dir = base / "plugins" / "unsafe-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "unsafe-plugin",
                "version": "0.1.0",
                "source": "trusted",
                "capabilities": ["hook_listen"],
                "hooks": [
                    {"event": "after_startup", "module": "handlers.py", "handler": "on_startup"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "handlers.py").write_text(
        "def on_startup(context):\n    eval('1 + 1')\n    return None\n",
        encoding="utf-8",
    )

    registry = PluginRegistry()
    registry._base_path = base

    success, message = registry.load_plugin(str(plugin_dir / "plugin.json"))

    assert success is False
    assert "statischer Sicherheits-Scan" in message
    assert "eval() Aufruf gefunden" in message


def test_skills_install_blocks_unsafe_package(tmp_path):
    from hub.skills import SkillsHandler

    base = _init_base(tmp_path)
    import_dir = tmp_path / "incoming-skill"
    skill_dir = import_dir / "skill"
    skill_dir.mkdir(parents=True)

    (import_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "unsafe-skill",
                "version": "1.0.0",
                "type": "skill",
                "description": "Unsafe import package",
            }
        ),
        encoding="utf-8",
    )
    (skill_dir / "tool.py").write_text(
        "def run():\n    exec('print(1)')\n",
        encoding="utf-8",
    )

    success, message = SkillsHandler(base).handle("install", [str(import_dir)])

    assert success is False
    assert "Install abgebrochen" in message
    assert "exec() Aufruf gefunden" in message
    assert not (base / "skills" / "unsafe-skill").exists()


def test_mcp_setup_rejects_untrusted_package_spec(tmp_path):
    from hub.setup import SetupHandler

    base = _init_base(tmp_path)
    handler = SetupHandler(base)

    success, errors = handler._validate_mcp_install_plan(
        ["ellmos-codecommander-mcp", "evil; rm -rf"],
        {"unsafe": {"command": "npx", "args": ["evil; rm -rf"]}},
    )

    assert success is False
    assert any("Ungueltiger MCP-Paketname" in error for error in errors)
    assert any("MCP-Paket nicht in Allowlist" in error for error in errors)


def test_mcp_config_scan_blocks_unsafe_local_server(tmp_path):
    from hub.setup import SetupHandler

    base = _init_base(tmp_path)
    handler = SetupHandler(base)
    server_file = tmp_path / "unsafe_mcp_server.js"
    server_file.write_text(
        "const child_process = require('child_process');\n"
        "child_process.exec('whoami');\n",
        encoding="utf-8",
    )

    success, blocking, warnings = handler._scan_mcp_config_paths(
        {"unsafe-local": {"command": "node", "args": [str(server_file)]}}
    )

    assert success is False
    assert warnings == []
    assert any("Node child_process exec-Aufruf gefunden" in finding for finding in blocking)


def test_mcp_setup_validation_blocks_untrusted_package(tmp_path):
    from hub.setup import SetupHandler

    base = _init_base(tmp_path)
    handler = SetupHandler(base)

    success, errors = handler._validate_mcp_install_plan(
        ["evil-mcp"],
        {"evil": {"command": "npx", "args": ["evil-mcp"]}},
    )

    assert success is False
    assert "MCP-Paket nicht in Allowlist: evil-mcp" in errors


def test_mcp_setup_validation_allows_core_packages(tmp_path):
    from hub.setup import SetupHandler

    base = _init_base(tmp_path)
    handler = SetupHandler(base)

    success, errors = handler._validate_mcp_install_plan(
        handler.CORE_MCP_PACKAGES,
        handler.CORE_MCP_SERVER_CONFIGS,
    )

    assert success is True
    assert errors == []


def test_mcp_setup_blocks_mismatched_config_package(tmp_path):
    from hub.setup import SetupHandler

    handler = SetupHandler(_init_base(tmp_path))
    ok, errors = handler._validate_mcp_install_plan(
        ["ellmos-codecommander-mcp"],
        {"bach-codecommander": {"command": "npx", "args": ["ellmos-filecommander-mcp"]}},
    )

    assert ok is False
    assert any("nicht im Installationsplan" in error for error in errors)
