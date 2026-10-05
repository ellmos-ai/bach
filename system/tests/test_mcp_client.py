# SPDX-License-Identifier: MIT
"""Tests for MCP Client Manager and Security Guards (Task #1453)."""

import json
from unittest.mock import MagicMock
from hub.mcp_client import MCPServerConnection, MCPClientManager, _check_security_args


def test_security_arg_checker():
    # Clean args
    assert _check_security_args("hello world") is None
    assert _check_security_args({"param": "normal_value", "count": 5}) is None

    # Sensitive strings
    assert _check_security_args("/path/to/credentials.json") is not None
    assert _check_security_args("C:/keys/id_ed25519") is not None
    assert _check_security_args({"key": ".env.local"}) is not None
    assert _check_security_args(["normal", "my_secret_token"]) is not None


def test_mcp_connection_allowed_tools_and_mode_guards():
    config = {
        "command": "fake_cmd",
        "allowed_tools": ["find_skill", "write_file"],
        "full_mode_tools": ["write_file"],
    }
    conn = MCPServerConnection("test_server", config)

    # 1. Non-allowed tool is rejected immediately
    res = conn.call_tool("delete_everything", {})
    assert "nicht in der Freigabeliste" in res

    # 2. Mutating tool in safe mode is rejected
    res_safe = conn.call_tool("write_file", {"path": "test.txt"}, mode="safe")
    assert "erfordert den Modus 'full'" in res_safe

    # 3. Path security violation is rejected
    res_sec = conn.call_tool("find_skill", {"path": "C:/keys/id_rsa"}, mode="safe")
    assert "sicherheitskritische Pfade verweigert" in res_sec


def test_mcp_connection_mock_roundtrip():
    config = {
        "command": "fake_cmd",
        "allowed_tools": ["list_skills"],
    }
    conn = MCPServerConnection("test_server", config)

    # Mock process
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = MagicMock()

    # Sequence of responses: 1. tools/list, 2. tools/call
    responses = [
        json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "list_skills", "description": "List all skills"},
                    {"name": "unauthorized_tool", "description": "Forbidden"}
                ]
            }
        }) + "\n",
        json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "Skill A, Skill B"}]}
        }) + "\n",
    ]

    mock_proc.stdout.readline.side_effect = responses

    conn.process = mock_proc
    conn._refresh_tools()

    # Tool list was filtered and prefixed
    assert len(conn.tools_schema) == 1
    assert conn.tools_schema[0]["name"] == "mcp_test_server_list_skills"
    assert conn.tools_schema[0]["original_name"] == "list_skills"

    # Call tool
    output = conn.call_tool("list_skills", {})
    assert output == "Skill A, Skill B"

    # Process cleanup
    conn.stop()
    assert conn.process is None
    mock_proc.terminate.assert_called_once()


def test_mcp_client_manager_dispatch(tmp_path):
    cfg_file = tmp_path / "mcp_servers.json"
    cfg_file.write_text(json.dumps({
        "mock_cc": {
            "command": "mock",
            "allowed_tools": ["find_skill"],
            "enabled": True
        }
    }), encoding="utf-8")

    mgr = MCPClientManager(config_path=cfg_file)
    cfg = mgr.load_config()
    assert "mock_cc" in cfg

    # Test error routing for unknown tool or inactive server
    err = mgr.execute_tool("invalid_format", {})
    assert "kein MCP-Werkzeug" in err

    err2 = mgr.execute_tool("mcp_mock_cc_find_skill", {})
    assert "nicht aktiv oder nicht verbunden" in err2
