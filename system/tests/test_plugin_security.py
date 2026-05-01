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
    quarantine_dirs = list((base / "data" / "quarantine" / "plugin").glob("*"))
    assert len(quarantine_dirs) == 1
    report = json.loads((quarantine_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["kind"] == "plugin"
    assert "unsafe-plugin" in report["reason"]
    assert report["copied"] is True


def test_plugin_inspect_reads_manifest_without_importing_runtime_code(tmp_path):
    from core.plugin_api import PluginRegistry

    base = _init_base(tmp_path)
    plugin_dir = base / "plugins" / "catalog-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "catalog-plugin",
                "manifest_version": "1.1",
                "version": "0.2.0",
                "source": "trusted",
                "capabilities": ["hook_listen"],
                "activation": {"mode": "manual", "enabled": True},
                "providers": [{"id": "nvidia", "type": "model-provider"}],
                "models": [{"id": "nvidia/llama", "provider": "nvidia"}],
                "setup": {"env": ["NVIDIA_API_KEY"]},
                "hooks": [
                    {"event": "after_startup", "module": "handlers.py", "handler": "on_startup"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "handlers.py").write_text(
        "raise RuntimeError('runtime import should not happen during inspect')\n",
        encoding="utf-8",
    )

    success, message = PluginRegistry().inspect_plugin(str(plugin_dir / "plugin.json"))

    assert success is True
    assert "manifest-first Vorschau" in message
    assert "Provider:     1 Eintrag" in message
    assert "nvidia" in message
    assert "Security-Scan: OK" in message


def test_plugin_load_stores_manifest_first_metadata(tmp_path):
    from core.capabilities import capability_manager
    from core.plugin_api import PluginRegistry

    base = _init_base(tmp_path)
    plugin_dir = base / "plugins" / "metadata-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "metadata-plugin",
                "manifest_version": "1.1",
                "version": "0.3.0",
                "source": "trusted",
                "capabilities": ["db_read"],
                "activation": {"mode": "startup", "enabled": False},
                "providers": [{"id": "local"}],
                "models": [{"id": "local/test-model", "provider": "local"}],
                "setup": {"requires": ["local-model"]},
            }
        ),
        encoding="utf-8",
    )

    registry = PluginRegistry()
    registry._base_path = base
    success, message = registry.load_plugin(str(plugin_dir / "plugin.json"))

    assert success is True
    assert "metadata-plugin" in registry._plugins
    info = registry._plugins["metadata-plugin"]
    assert info["activation"]["mode"] == "startup"
    assert info["providers"][0]["id"] == "local"
    assert info["models"][0]["id"] == "local/test-model"
    assert info["metadata"]["manifest_version"] == "1.1"

    registry.unload_plugin("metadata-plugin")
    capability_manager.unregister_plugin("metadata-plugin")


def test_plugin_load_blocks_missing_manifest_file_reference(tmp_path):
    from core.plugin_api import PluginRegistry

    base = _init_base(tmp_path)
    plugin_dir = base / "plugins" / "broken-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "broken-plugin",
                "version": "0.1.0",
                "source": "trusted",
                "capabilities": ["handler_register"],
                "handlers": [{"name": "broken", "file": "missing_handler.py"}],
            }
        ),
        encoding="utf-8",
    )

    registry = PluginRegistry()
    registry._base_path = base

    success, message = registry.inspect_plugin(str(plugin_dir / "plugin.json"))

    assert success is False
    assert "Manifest-Warnungen" in message
    assert "handlers[0].file nicht gefunden" in message

    success, message = registry.load_plugin(str(plugin_dir / "plugin.json"))

    assert success is False
    assert "Manifest-Validierung fehlgeschlagen" in message
    assert "missing_handler.py" in message
    assert registry.plugin_names == []


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
    quarantine_dirs = list((base / "data" / "quarantine" / "skill").glob("*"))
    assert len(quarantine_dirs) == 1
    report = json.loads((quarantine_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["kind"] == "skill"
    assert "unsafe-skill" in report["reason"]
    assert report["copied"] is True


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
    quarantine_dirs = list((base / "data" / "quarantine" / "mcp").glob("*"))
    assert len(quarantine_dirs) == 1
    report = json.loads((quarantine_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["kind"] == "mcp"
    assert report["metadata"]["server"] == "unsafe-local"


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
