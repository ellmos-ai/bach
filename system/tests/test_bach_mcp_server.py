# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the built-in BACH MCP server and first-class CLI handler."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


def test_mcp_handler_is_discovered():
    from core.app import App

    handler = App(SYSTEM_ROOT).get_handler("mcp")

    assert handler is not None
    assert "serve" in handler.get_operations()


def test_mcp_handler_serves_stdio(monkeypatch):
    from hub.mcp import McpHandler

    calls = []
    fake_server = SimpleNamespace(serve=lambda transport: calls.append(transport))
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_server)

    success, message = McpHandler(SYSTEM_ROOT).handle("serve", [])

    assert success is True
    assert message == ""
    assert calls == ["stdio"]


def test_mcp_handler_dry_run_does_not_import_server(monkeypatch):
    from hub.mcp import McpHandler

    def fail_import(_name):
        raise AssertionError("dry-run must not import or start the MCP server")

    monkeypatch.setattr(importlib, "import_module", fail_import)

    success, message = McpHandler(SYSTEM_ROOT).handle("serve", ["--dry-run"], dry_run=True)

    assert success is True
    assert "DRY-RUN" in message


def test_mcp_handler_reports_missing_sdk(monkeypatch):
    from hub.mcp import McpHandler

    def missing_sdk(_name):
        raise ImportError("No module named 'mcp'", name="mcp")

    monkeypatch.setattr(importlib, "import_module", missing_sdk)

    success, message = McpHandler(SYSTEM_ROOT).handle("serve", [])

    assert success is False
    assert "requirements-optional.txt" in message


def test_server_serve_forwards_transport(monkeypatch):
    from tools import mcp_server

    calls = []
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kwargs: calls.append(kwargs))

    mcp_server.serve(transport="stdio")

    assert calls == [{"transport": "stdio"}]


def test_server_import_ignores_bach_hub_mcp_shadow():
    code = """
import sys
from pathlib import Path

system_root = Path.cwd()
import tools
sys.path.insert(0, str(system_root / "hub"))
from tools import mcp_server

assert mcp_server.FastMCP.__module__.startswith("mcp.server")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SYSTEM_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_server_exposes_resources_tools_and_prompts():
    from tools import mcp_server

    resources = await mcp_server.mcp.list_resources()
    tools = await mcp_server.mcp.list_tools()
    prompts = await mcp_server.mcp.list_prompts()

    assert len(resources) == 8
    assert len(tools) == 23
    assert len(prompts) == 3


def test_core_profile_registers_first_class_cli():
    from hub.setup import SetupHandler

    assert SetupHandler.CORE_MCP_SERVER_CONFIGS["bach"] == {
        "command": "bach",
        "args": ["mcp", "serve"],
    }


def test_setup_writes_first_class_profile(tmp_path, monkeypatch):
    from hub.setup import SetupHandler

    home = tmp_path / "home"
    home.mkdir()
    config_path = home / ".claude.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: home)

    success, _message = SetupHandler(SYSTEM_ROOT)._configure_claude_mcp(
        SetupHandler.CORE_MCP_PACKAGES,
        dry_run=False,
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert success is True
    assert config["mcpServers"]["bach"] == {
        "command": "bach",
        "args": ["mcp", "serve"],
    }


def test_cli_does_not_print_empty_server_status(monkeypatch, capsys):
    import bach as bach_cli

    class Handler:
        def handle(self, operation, args, dry_run=False):
            assert operation == "serve"
            return True, ""

    class App:
        def get_handler(self, name):
            return Handler() if name == "mcp" else None

    monkeypatch.setattr(bach_cli, "_get_app", lambda: App())
    monkeypatch.setattr(bach_cli, "cmd", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bach_cli, "_run_injectors", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("BACH_USE_LAUNCHER", "0")
    monkeypatch.setattr(sys, "argv", ["bach.py", "mcp", "serve"])

    assert bach_cli.main() == 0
    assert capsys.readouterr().out == ""


def test_mcp_server_imports_real_mcp_despite_hub_shadow(monkeypatch):
    """Regressionsschutz gegen sys.path-Shadowing (Task #1284).

    In der Vollsuite kann ein frueherer Test (z. B. tests/test_portable_agents.py)
    system/hub auf sys.path legen. Dann loest ein Top-Level "import mcp" auf
    system/hub/mcp.py statt auf das echte mcp-Paket auf -- der Sub-Import
    "mcp.server.fastmcp" in tools/mcp_server.py scheitert mit
    "attempted relative import with no known parent package".

    Der Test stellt beide Verschattungsarten her (hub-Verzeichnis auf sys.path
    UND sys.modules['mcp'] = hub/mcp.py ohne __path__) und prueft, dass der
    shadow-proof Import-Pfad von tools/mcp_server.py (``mmod._import_fastmcp``)
    trotzdem das echte mcp-Paket laedt. Wir rufen gezielt die Import-Hilfsfunktion
    auf, statt das komplette Modul im vergifteten Zustand neu auszufuehren --
    letzteres ziehe unbeabsichtigt andere hub/tools.py-Relative-Imports (eine
    eigene Verschattungsklasse, ausserhalb des mcp-Scopes) in den Test und
    mache ihn nicht deterministisch.
    """
    hub_dir = SYSTEM_ROOT / "hub"
    assert (hub_dir / "mcp.py").exists(), "Voraussetzung: system/hub/mcp.py"

    # Sauberer Import im ungegiffteten Zustand (im Volllauf laeuft der Modul-
    # Import genau einmal und ist dann gecached). _import_fastmcp ist die
    # eigentliche shadow-proof Logik und laesst sich isoliert ueberpruefen.
    import tools.mcp_server as mmod

    original_path = list(sys.path)
    saved_mcp = sys.modules.get("mcp")
    hub_mcp = importlib.import_module("hub.mcp")
    saved_hub_name = hub_mcp.__name__

    def _poison():
        # (1) hub-Verzeichnis an den Anfang von sys.path
        if str(hub_dir) not in sys.path:
            sys.path.insert(0, str(hub_dir))
        # (2) sys.modules['mcp'] mit hub/mcp.py (kein Package) verseuchen
        hub_mcp.__name__ = "mcp"
        sys.modules["mcp"] = hub_mcp

    def _restore():
        sys.path[:] = original_path
        for key in list(sys.modules):
            if key == "mcp" or key.startswith("mcp."):
                del sys.modules[key]
        if saved_mcp is not None:
            sys.modules["mcp"] = saved_mcp
        # Leckage vermeiden: geteiltes hub.mcp-Objekt ruecksetzen
        hub_mcp.__name__ = saved_hub_name

    try:
        _poison()
        # Sanity: Verschattung ist tatsaechlich aktiv (kein echtes Package)
        assert not hasattr(sys.modules["mcp"], "__path__"), (
            "Poison nicht aktiv: mcp hat ein __path__"
        )

        FastMCP = mmod._import_fastmcp()

        real_mcp = sys.modules["mcp"]
        assert hasattr(real_mcp, "__path__"), (
            "mcp wurde als echtes Package geladen (mit __path__), "
            "nicht als schattierendes hub/mcp.py"
        )
        assert "site-packages" in real_mcp.__file__, (
            f"mcp sollte aus dem venv/site-packages kommen, ist aber: "
            f"{real_mcp.__file__}"
        )

        from mcp.server.fastmcp import FastMCP as RealFastMCP

        assert FastMCP is RealFastMCP
    finally:
        _restore()
