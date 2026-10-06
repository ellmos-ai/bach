# SPDX-License-Identifier: MIT
"""MCP Client for BACH Worker (Task #1453).

Enables BACH workers to connect to MCP servers (such as ControlCenter-MCP)
via stdio JSON-RPC, discover tools, enforce whitelist security, prevent credential
leaks, and guarantee child process cleanup.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Security: Path substrings that are never allowed as MCP tool arguments
_BLOCKED_PATH_PATTERNS = (
    "credentials",
    "id_ed25519",
    "id_rsa",
    ".env",
    "token",
    "keychain",
    "password",
    "secret",
)


def _check_security_args(args: Any) -> Optional[str]:
    """Check if any argument contains sensitive credential paths."""
    if isinstance(args, str):
        lower = args.lower()
        for pat in _BLOCKED_PATH_PATTERNS:
            if pat in lower:
                return f"Zugriff auf sicherheitskritische Pfade verweigert (Muster: {pat})"
    elif isinstance(args, dict):
        for k, v in args.items():
            err = _check_security_args(k) or _check_security_args(v)
            if err:
                return err
    elif isinstance(args, (list, tuple)):
        for item in args:
            err = _check_security_args(item)
            if err:
                return err
    return None


class MCPServerConnection:
    """Manages a single MCP server connection over stdio."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.command = config.get("command", "")
        self.args = config.get("args", [])
        self.allowed_tools = set(config.get("allowed_tools", []))
        self.full_mode_only_tools = set(config.get("full_mode_tools", []))
        self.process: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._lock = threading.Lock()
        self.tools_schema: list[dict] = []

    def start(self) -> bool:
        """Start the MCP server process and initialize handshake."""
        if not self.command:
            return False
        try:
            cmd = [self.command] + self.args
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            # 1. Initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "bach-worker", "version": "1.0"},
                },
            }
            self._next_id += 1
            resp = self._send_request(init_req)
            if not resp or "error" in resp:
                logger.warning("MCP server %s init failed: %s", self.name, resp)
                self.stop()
                return False

            # 2. Initialized notification
            init_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self._send_notification(init_notif)

            # 3. Read tools
            self._refresh_tools()
            return True
        except Exception as exc:
            logger.warning("Failed to start MCP server %s: %s", self.name, exc)
            self.stop()
            return False

    def _refresh_tools(self) -> None:
        """Query tools/list from server and filter against allowed_tools."""
        req = {"jsonrpc": "2.0", "id": self._next_id, "method": "tools/list", "params": {}}
        self._next_id += 1
        resp = self._send_request(req)
        if resp and "result" in resp and "tools" in resp["result"]:
            raw_tools = resp["result"]["tools"]
            filtered = []
            for t in raw_tools:
                t_name = t.get("name", "")
                if not self.allowed_tools or t_name in self.allowed_tools:
                    # Prefix with mcp_<server>_
                    prefixed_tool = dict(t)
                    prefixed_tool["original_name"] = t_name
                    prefixed_tool["server_name"] = self.name
                    prefixed_tool["name"] = f"mcp_{self.name}_{t_name}"
                    filtered.append(prefixed_tool)
            self.tools_schema = filtered

    def _send_request(self, payload: dict, timeout: float = 10.0) -> Optional[dict]:
        """Send JSON-RPC request and wait for line-delimited response."""
        with self._lock:
            if not self.process or self.process.poll() is not None:
                return None
            try:
                line = json.dumps(payload) + "\n"
                self.process.stdin.write(line)
                self.process.stdin.flush()

                # Read response
                resp_line = self.process.stdout.readline()
                if not resp_line:
                    return None
                return json.loads(resp_line.strip())
            except Exception as exc:
                logger.error("Error in MCP request to %s: %s", self.name, exc)
                return None

    def _send_notification(self, payload: dict) -> None:
        """Send JSON-RPC notification (no response expected)."""
        with self._lock:
            if not self.process or self.process.poll() is not None:
                return
            try:
                line = json.dumps(payload) + "\n"
                self.process.stdin.write(line)
                self.process.stdin.flush()
            except Exception as exc:
                logger.error("Error sending MCP notification to %s: %s", self.name, exc)

    def call_tool(self, tool_name: str, arguments: dict, mode: str = "safe") -> str:
        """Call a tool on this server with security and mode validation."""
        # 1. Allowed tools check
        if self.allowed_tools and tool_name not in self.allowed_tools:
            return f"Fehler: Werkzeug '{tool_name}' ist nicht in der Freigabeliste für Server '{self.name}'."

        # 2. Mode check (full mode required for mutating tools)
        if tool_name in self.full_mode_only_tools and mode != "full":
            return f"Fehler: Werkzeug '{tool_name}' erfordert den Modus 'full' (aktuell: {mode})."

        # 3. Path security check
        sec_err = _check_security_args(arguments)
        if sec_err:
            return f"Fehler: {sec_err}"

        # 4. Invoke
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        self._next_id += 1
        resp = self._send_request(req)
        if not resp:
            return f"Fehler: Keine Antwort von MCP-Server '{self.name}'."
        if "error" in resp:
            return f"Fehler von MCP-Server: {resp['error']}"

        result = resp.get("result", {})
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and "text" in c]
            return "\n".join(texts) if texts else json.dumps(result)
        return str(result)

    def stop(self) -> None:
        """Cleanly terminate the server process."""
        with self._lock:
            if not self.process:
                return
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=1.0)
            except Exception:
                pass
            finally:
                self.process = None


class MCPClientManager:
    """Manages all configured MCP servers for the BACH runtime."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path(__file__).resolve().parent.parent / "data" / "mcp_servers.json"
        self.servers: dict[str, MCPServerConnection] = {}
        atexit.register(self.stop_all)

    def load_config(self) -> dict:
        """Load configuration from JSON file."""
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Could not read MCP servers config from %s: %s", self.config_path, exc)
            return {}

    def start_all(self) -> None:
        """Start all configured MCP servers."""
        cfg = self.load_config()
        for name, srv_cfg in cfg.items():
            if not srv_cfg.get("enabled", True):
                continue
            conn = MCPServerConnection(name, srv_cfg)
            if conn.start():
                self.servers[name] = conn

    def get_all_tools(self) -> list[dict]:
        """Aggregate available tools across all active servers."""
        tools = []
        for srv in self.servers.values():
            tools.extend(srv.tools_schema)
        return tools

    def execute_tool(self, prefixed_name: str, arguments: dict, mode: str = "safe") -> str:
        """Execute a tool matching 'mcp_<server>_<tool>'."""
        if not prefixed_name.startswith("mcp_"):
            return f"Fehler: '{prefixed_name}' ist kein MCP-Werkzeug."

        parts = prefixed_name[4:].split("_", 1)
        if len(parts) < 2:
            return f"Fehler: Ungültiges MCP-Werkzeugformat: {prefixed_name}"

        server_name, tool_name = parts[0], parts[1]
        if server_name not in self.servers:
            return f"Fehler: MCP-Server '{server_name}' ist nicht aktiv oder nicht verbunden."

        return self.servers[server_name].call_tool(tool_name, arguments, mode=mode)

    def stop_all(self) -> None:
        """Stop all running MCP servers."""
        for srv in list(self.servers.values()):
            srv.stop()
        self.servers.clear()

    def get_activity_summary(self) -> list[dict]:
        """Return status summary of connected servers and tools for /activity."""
        summary = []
        for name, srv in self.servers.items():
            summary.append({
                "server": name,
                "status": "connected" if srv.process and srv.process.poll() is None else "stopped",
                "tool_count": len(srv.tools_schema),
                "tools": [t["original_name"] for t in srv.tools_schema],
            })
        return summary


_manager_instance: Optional[MCPClientManager] = None


def get_mcp_manager() -> MCPClientManager:
    """Singleton getter for MCPClientManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MCPClientManager()
    return _manager_instance
