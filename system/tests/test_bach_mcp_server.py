# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the built-in BACH MCP server and first-class CLI handler."""

import importlib
import json
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
