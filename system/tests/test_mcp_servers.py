# -*- coding: utf-8 -*-
"""
MCP Server Cross-Platform Tests
================================
Tests that ellmos FileCommander and CodeCommander MCP servers
can be found and initialized on the current platform.
Skipped automatically if the MCP binaries are not installed.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import pytest


INIT_MESSAGE = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"}
    }
})

MCP_SERVERS = [
    ("ellmos-filecommander-mcp", "ellmos-filecommander"),
    ("ellmos-codecommander-mcp", "ellmos-codecommander"),
]


def _find_mcp_binary(name: str) -> str | None:
    """Find MCP server binary via shutil.which or common npm global paths.

    npm packages may expose binaries with or without the '-mcp' suffix,
    so we check both variants.
    """
    for candidate_name in [name, name.removesuffix("-mcp")]:
        found = shutil.which(candidate_name)
        if found:
            return found
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        for candidate_name in [name, name.removesuffix("-mcp")]:
            candidate = os.path.join(appdata, "npm", f"{candidate_name}.cmd")
            if os.path.isfile(candidate):
                return candidate
    return None


def _send_init(binary: str, timeout: int = 15) -> dict:
    """Send JSON-RPC initialize to an MCP server and return parsed response."""
    result = subprocess.run(
        [binary],
        input=INIT_MESSAGE + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    lines = result.stdout.strip().splitlines()
    assert lines, f"MCP server {binary} produced no output"
    return json.loads(lines[0])


class TestMCPServerDiscovery:
    """Test that MCP server binaries can be found."""

    @pytest.mark.parametrize("binary_name,display_name", MCP_SERVERS)
    def test_binary_discoverable(self, binary_name, display_name):
        found = _find_mcp_binary(binary_name)
        if found is None:
            pytest.skip(f"{binary_name} not installed on this system")
        assert os.path.exists(found), f"Binary path {found} does not exist"


class TestMCPServerInitialize:
    """Test that MCP servers respond to JSON-RPC initialize."""

    @pytest.mark.parametrize("binary_name,display_name", MCP_SERVERS)
    def test_initialize_response(self, binary_name, display_name):
        found = _find_mcp_binary(binary_name)
        if found is None:
            pytest.skip(f"{binary_name} not installed on this system")

        response = _send_init(found)

        assert "result" in response, f"No 'result' in response: {response}"
        result = response["result"]
        assert "serverInfo" in result
        info = result["serverInfo"]
        assert "name" in info
        assert "version" in info

    @pytest.mark.parametrize("binary_name,display_name", MCP_SERVERS)
    def test_server_capabilities(self, binary_name, display_name):
        found = _find_mcp_binary(binary_name)
        if found is None:
            pytest.skip(f"{binary_name} not installed on this system")

        response = _send_init(found)
        result = response.get("result", {})
        capabilities = result.get("capabilities", {})
        assert "tools" in capabilities, f"{display_name} should expose tools capability"

    @pytest.mark.parametrize("binary_name,display_name", MCP_SERVERS)
    def test_protocol_version(self, binary_name, display_name):
        found = _find_mcp_binary(binary_name)
        if found is None:
            pytest.skip(f"{binary_name} not installed on this system")

        response = _send_init(found)
        result = response.get("result", {})
        version = result.get("protocolVersion", "")
        assert version, f"{display_name} should return protocolVersion"


class TestMCPServerPlatformCompat:
    """Platform-specific compatibility checks."""

    def test_home_dir_resolution(self):
        home = os.path.expanduser("~")
        assert home != "~", "HOME directory could not be resolved"
        assert os.path.isdir(home), f"HOME {home} is not a directory"

    def test_node_available(self):
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js not installed")
        result = subprocess.run(
            [node, "--version"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=10,
        )
        assert result.stdout.strip().startswith("v"), "node --version should start with 'v'"

    def test_npm_available(self):
        npm = shutil.which("npm")
        if npm is None:
            pytest.skip("npm not installed")
        result = subprocess.run(
            [npm, "--version"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=15,
        )
        assert result.returncode == 0, "npm --version failed"

    @pytest.mark.parametrize("binary_name,display_name", MCP_SERVERS)
    def test_no_hardcoded_windows_paths(self, binary_name, display_name):
        """Verify MCP servers don't crash on non-Windows due to hardcoded paths."""
        if platform.system() == "Windows":
            pytest.skip("This test checks non-Windows compatibility")
        found = _find_mcp_binary(binary_name)
        if found is None:
            pytest.skip(f"{binary_name} not installed")
        response = _send_init(found)
        assert "error" not in response, f"Server error on {platform.system()}: {response.get('error')}"
