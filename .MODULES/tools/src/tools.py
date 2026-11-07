# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Standalone Tools Module
Autarker Tool-Manager und Dispatcher für BACH und Ocean.
"""
from __future__ import annotations

import inspect
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass
class ToolMetadata:
    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    permissions_required: list[str] = field(default_factory=list)
    handler: Optional[Callable[..., Any]] = None
    enabled: bool = True
    author: str = ""
    version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ToolRegistry:
    """Autarke Tool-Verwaltung für BACH und Ocean."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        self._audit_log: list[dict[str, Any]] = []

    def register_tool(
        self,
        name: str,
        description: str = "",
        parameters: Optional[dict[str, Any]] = None,
        category: str = "general",
        permissions_required: Optional[list[str]] = None,
        handler: Optional[Callable[..., Any]] = None,
        enabled: bool = True,
        version: str = "1.0.0",
    ) -> bool:
        """Registriert ein Tool."""
        if not name or not name.strip():
            return False

        meta = ToolMetadata(
            name=name.strip(),
            description=description,
            parameters=parameters or {},
            category=category,
            permissions_required=permissions_required or [],
            handler=handler,
            enabled=enabled,
            version=version,
        )
        self._tools[meta.name] = meta
        return True

    def get_tool(self, name: str) -> Optional[ToolMetadata]:
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None, enabled_only: bool = False) -> list[ToolMetadata]:
        res = list(self._tools.values())
        if category:
            res = [t for t in res if t.category.lower() == category.lower()]
        if enabled_only:
            res = [t for t in res if t.enabled]
        return res

    def invoke_tool(
        self,
        name: str,
        parameters: Optional[dict[str, Any]] = None,
        caller_permissions: Optional[list[str] | set[str]] = None,
    ) -> tuple[bool, Any]:
        """Führt ein registriertes Tool mit Sicherheits- und Berechtigungsprüfung aus."""
        params = parameters or {}
        tool = self.get_tool(name)
        if not tool:
            return False, f"Tool '{name}' nicht registriert"
        if not tool.enabled:
            return False, f"Tool '{name}' ist deaktiviert"

        # Berechtigungs-Prüfung
        if tool.permissions_required:
            caller_perms = set(caller_permissions or [])
            missing = [p for p in tool.permissions_required if p not in caller_perms]
            if missing:
                self._record_audit(name, params, success=False, error=f"Fehlende Rechte: {missing}")
                return False, f"Ausführung verweigert: Fehlende Berechtigung(en) {missing}"

        # Handler-Aufruf
        if not tool.handler:
            self._record_audit(name, params, success=False, error="Kein Handler implementiert")
            return False, f"Tool '{name}' besitzt keinen ausführbaren Handler"

        try:
            sig = inspect.signature(tool.handler)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                res = tool.handler(**params)
            else:
                accepted = {k: v for k, v in params.items() if k in sig.parameters}
                res = tool.handler(**accepted)

            self._record_audit(name, params, success=True, result=str(res)[:100])
            return True, res
        except Exception as exc:
            self._record_audit(name, params, success=False, error=str(exc))
            return False, f"Ausführungsfehler in Tool '{name}': {exc}"

    def _record_audit(self, name: str, params: dict[str, Any], success: bool, result: Any = None, error: Any = None):
        self._audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "tool": name,
            "params_keys": list(params.keys()),
            "success": success,
            "result": result,
            "error": error,
        })

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(self._audit_log[-limit:]))
