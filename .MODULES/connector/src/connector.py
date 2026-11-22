# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: connector
===============================
Self-contained connector endpoint registry, exponential retry backoff,
and outbound message envelope builder/router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ConnectorSpec:
    name: str
    connector_type: str
    endpoint: str
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundEnvelope:
    connector_name: str
    recipient: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attempt: int = 0


def compute_backoff_seconds(attempt: int, *, base_seconds: float = 5.0, cap_seconds: float = 300.0) -> float:
    """Compute bounded exponential backoff delay for connector delivery retries."""
    exp = max(0, int(attempt))
    delay = base_seconds * (2 ** exp)
    return float(min(delay, cap_seconds))


class ConnectorRegistry:
    """In-memory, zero-DB connector specification registry & dispatcher."""

    def __init__(self) -> None:
        self._connectors: Dict[str, ConnectorSpec] = {}
        self._handlers: Dict[str, Callable[[ConnectorSpec, OutboundEnvelope], Dict[str, Any]]] = {}

    def register(
        self,
        name: str,
        connector_type: str,
        endpoint: str,
        *,
        enabled: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConnectorSpec:
        spec = ConnectorSpec(
            name=name.strip(),
            connector_type=connector_type.strip().lower(),
            endpoint=endpoint.strip(),
            enabled=enabled,
            metadata=dict(metadata or {}),
        )
        self._connectors[spec.name] = spec
        return spec

    def register_transport(
        self,
        connector_type: str,
        fn: Callable[[ConnectorSpec, OutboundEnvelope], Dict[str, Any]],
    ) -> None:
        self._handlers[connector_type.strip().lower()] = fn

    def list_enabled(self) -> List[ConnectorSpec]:
        return [c for c in self._connectors.values() if c.enabled]

    def dispatch(self, connector_name: str, recipient: str, content: str) -> Dict[str, Any]:
        spec = self._connectors.get(connector_name)
        if spec is None:
            return {"ok": False, "error": f"Unknown connector: {connector_name}"}
        if not spec.enabled:
            return {"ok": False, "error": f"Connector disabled: {connector_name}"}
        if not content.strip():
            return {"ok": False, "error": "Empty message content"}

        envelope = OutboundEnvelope(connector_name=spec.name, recipient=recipient, content=content)
        handler = self._handlers.get(spec.connector_type)
        if handler is None:
            return {
                "ok": False,
                "error": f"No transport handler registered for type '{spec.connector_type}'",
            }
        return handler(spec, envelope)
