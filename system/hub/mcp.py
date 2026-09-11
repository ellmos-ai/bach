# SPDX-License-Identifier: MIT
"""First-class CLI handler for the built-in BACH MCP server."""

import importlib
from pathlib import Path

from .base import BaseHandler


class McpHandler(BaseHandler):
    """Expose the built-in MCP server through ``bach mcp serve``."""

    @property
    def profile_name(self) -> str:
        return "mcp"

    @property
    def target_file(self) -> Path:
        return self.base_path / "tools" / "mcp_server.py"

    def get_operations(self) -> dict:
        return {
            "serve": "BACH MCP Server über stdio starten",
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        if operation in ("", "help"):
            return True, self._help()
        if operation != "serve":
            return False, (
                f"Unbekannte Operation: {operation}\n\n"
                "Verfügbar: serve"
            )
        if any(arg not in ("--dry-run", "-n") for arg in args):
            return False, "Usage: bach mcp serve [--dry-run]"
        if dry_run:
            return True, "[DRY-RUN] BACH MCP Server würde über stdio starten"

        try:
            server = importlib.import_module("tools.mcp_server")
        except ImportError as exc:
            if exc.name == "mcp" or (exc.name and exc.name.startswith("mcp.")):
                return False, (
                    "MCP SDK nicht installiert. "
                    "Bitte optionale Abhängigkeiten installieren: "
                    "pip install -r requirements-optional.txt"
                )
            raise

        server.serve(transport="stdio")
        # No trailing status text: stdout belongs exclusively to MCP stdio.
        return True, ""

    @staticmethod
    def _help() -> str:
        return (
            "BACH MCP Server\n\n"
            "Usage:\n"
            "  bach mcp serve              Server über stdio starten\n"
            "  bach mcp serve --dry-run    Start nur pruefen\n\n"
            "Der Server stellt BACH-Ressourcen, -Tools und -Prompts bereit."
        )
