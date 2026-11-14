# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Standalone Plugins Module
Autarker Plugin-Manager für BACH und Ocean.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class PluginMetadata:
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    entrypoint: str = ""
    tools: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    trust_level: str = "standard"  # untrusted, standard, trusted, core
    enabled: bool = True
    manifest_path: str = ""
    loaded_at: str = field(default_factory=lambda: datetime.now().isoformat())


class PluginRegistry:
    """Autarke Plugin-Verwaltung für BACH und Ocean."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginMetadata] = {}
        self._audit_history: list[dict[str, Any]] = []

    def inspect_plugin(self, manifest_source: str | Path | dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Prüft ein Plugin-Manifest ohne es dauerhaft zu laden."""
        try:
            data = self._read_manifest_data(manifest_source)
            if not isinstance(data, dict):
                return False, {"error": "Manifest muss ein JSON-Objekt sein"}
            if not data.get("name"):
                return False, {"error": "Feld 'name' fehlt im Manifest"}
            return True, {
                "name": data["name"],
                "version": data.get("version", "1.0.0"),
                "description": data.get("description", ""),
                "tools": data.get("tools", []),
                "capabilities": data.get("capabilities", []),
                "valid": True,
            }
        except Exception as exc:
            return False, {"error": str(exc), "valid": False}

    def load_plugin(self, manifest_source: str | Path | dict[str, Any]) -> tuple[bool, str]:
        """Lädt ein Plugin anhand eines Pfads oder Dicts."""
        try:
            data = self._read_manifest_data(manifest_source)
            name = str(data.get("name") or "").strip()
            if not name:
                return False, "Fehler: 'name' ist erforderlich."

            meta = PluginMetadata(
                name=name,
                version=str(data.get("version", "1.0.0")),
                description=str(data.get("description", "")),
                author=str(data.get("author", "")),
                entrypoint=str(data.get("entrypoint", "")),
                tools=list(data.get("tools", [])),
                hooks=list(data.get("hooks", [])),
                capabilities=list(data.get("capabilities", [])),
                trust_level=str(data.get("trust_level", "standard")),
                enabled=bool(data.get("enabled", True)),
                manifest_path=str(manifest_source) if isinstance(manifest_source, (str, Path)) else "in-memory",
            )
            self._plugins[name] = meta
            self._record_audit("load", name, f"Plugin {name} v{meta.version} geladen")
            return True, f"[OK] Plugin '{name}' v{meta.version} erfolgreich geladen."
        except Exception as exc:
            return False, f"Fehler beim Laden des Plugins: {exc}"

    def unload_plugin(self, name: str) -> tuple[bool, str]:
        """Entlädt ein Plugin."""
        if name not in self._plugins:
            return False, f"Plugin '{name}' ist nicht geladen."
        del self._plugins[name]
        self._record_audit("unload", name, f"Plugin {name} entladen")
        return True, f"[OK] Plugin '{name}' wurde entladen."

    def enable_plugin(self, name: str) -> tuple[bool, str]:
        if name not in self._plugins:
            return False, f"Plugin '{name}' nicht gefunden."
        self._plugins[name].enabled = True
        self._record_audit("enable", name, "Plugin aktiviert")
        return True, f"[OK] Plugin '{name}' aktiviert."

    def disable_plugin(self, name: str) -> tuple[bool, str]:
        if name not in self._plugins:
            return False, f"Plugin '{name}' nicht gefunden."
        self._plugins[name].enabled = False
        self._record_audit("disable", name, "Plugin deaktiviert")
        return True, f"[OK] Plugin '{name}' deaktiviert."

    def set_trust_level(self, name: str, level: str) -> tuple[bool, str]:
        valid_levels = {"untrusted", "standard", "trusted", "core"}
        if level not in valid_levels:
            return False, f"Ungültiges Trust-Level. Erlaubt: {', '.join(sorted(valid_levels))}"
        if name not in self._plugins:
            return False, f"Plugin '{name}' nicht gefunden."
        self._plugins[name].trust_level = level
        self._record_audit("trust_change", name, f"Trust-Level auf '{level}' gesetzt")
        return True, f"[OK] Plugin '{name}' Trust-Level ist nun '{level}'."

    def get_plugin(self, name: str) -> Optional[PluginMetadata]:
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        return [asdict(p) for p in self._plugins.values()]

    def list_tools(self) -> list[dict[str, Any]]:
        tools = []
        for p in self._plugins.values():
            if p.enabled:
                for t in p.tools:
                    tools.append({"tool": t, "plugin": p.name, "trust": p.trust_level})
        return tools

    def list_capabilities(self) -> dict[str, list[str]]:
        caps: dict[str, list[str]] = {}
        for p in self._plugins.values():
            if p.enabled:
                caps[p.name] = p.capabilities
        return caps

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._audit_history[-limit:]

    def status(self) -> dict[str, Any]:
        return {
            "schema": "bach.plugins-status.v1",
            "total_plugins": len(self._plugins),
            "active_plugins": sum(1 for p in self._plugins.values() if p.enabled),
            "total_tools": len(self.list_tools()),
            "audit_entries": len(self._audit_history),
        }

    def _read_manifest_data(self, source: str | Path | dict[str, Any]) -> dict[str, Any]:
        if isinstance(source, dict):
            return source
        p = Path(source)
        if p.is_dir():
            p = p / "plugin.json"
        if not p.is_file():
            raise FileNotFoundError(f"Manifest nicht gefunden: {p}")
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _record_audit(self, action: str, target: str, details: str) -> None:
        self._audit_history.append({
            "action": action,
            "target": target,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        })


_global_registry = PluginRegistry()


def get_plugin_registry() -> PluginRegistry:
    return _global_registry


plugins = _global_registry
