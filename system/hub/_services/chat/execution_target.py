# SPDX-License-Identifier: MIT
"""Ephemeral, allowlisted evidence for the backend target of a live run.

The target is set only at the backend dispatch boundary and is removed when
that call returns. Configuration alone therefore cannot turn a slot into a
local or external run in the GUI.
"""
from __future__ import annotations

from datetime import datetime, timezone
import platform
import re
from typing import Any


SCHEMA = "bach.execution-target.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,191}$")
_SOURCE = frozenset({
    "backend_dispatch",
    "host_inference_gate",
    "local_backend_dispatch",
    "local_target_probe",
})


def _observed_at(value: str | None = None) -> str:
    return value if isinstance(value, str) and value else datetime.now(timezone.utc).isoformat()


def _optional_identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def project_execution_target(raw: Any) -> dict[str, Any] | None:
    """Return only the public fields of a valid current dispatch receipt."""
    if not isinstance(raw, dict):
        return None
    required = {"schema", "provider", "model", "host", "locality", "source", "observed_at"}
    if raw.get("schema") != SCHEMA or not required.issubset(raw):
        return None
    provider = raw.get("provider")
    model = raw.get("model")
    host = raw.get("host")
    locality = raw.get("locality")
    source = raw.get("source")
    observed_at = raw.get("observed_at")
    if (not isinstance(provider, str) or not _IDENTIFIER.fullmatch(provider)
            or not isinstance(model, str) or not _MODEL.fullmatch(model)
            or not isinstance(host, str) or not _IDENTIFIER.fullmatch(host)
            or locality not in {"local", "external"}
            or source not in _SOURCE
            or not isinstance(observed_at, str) or len(observed_at) > 64):
        return None
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "provider": provider,
        "model": model,
        "host": host,
        "locality": locality,
        "source": source,
        "observed_at": observed_at,
    }
    for key in ("socket_id", "binding_id", "agent_id", "slot_id"):
        value = raw.get(key)
        if value is not None:
            value = _optional_identifier(value)
            if value is None:
                return None
            result[key] = value
    return result


def local_execution_target(
    provider: str,
    model: str,
    *,
    binding: dict[str, Any] | None = None,
    slot_id: str | None = None,
    host: str | None = None,
    source: str = "local_backend_dispatch",
) -> dict[str, Any] | None:
    """Build a local target from the selected backend and optional socket proof."""
    raw: dict[str, Any] = {
        "schema": SCHEMA,
        "provider": provider,
        "model": model,
        "host": host or platform.node() or "local",
        "locality": "local",
        "source": source,
        "observed_at": _observed_at(),
    }
    if isinstance(binding, dict):
        for key in ("socket_id", "binding_id", "agent_id"):
            if key in binding:
                raw[key] = binding[key]
    if slot_id is not None:
        raw["slot_id"] = slot_id
    return project_execution_target(raw)


def external_execution_target(
    provider: str,
    model: str,
    *,
    slot_id: str | None = None,
    source: str = "backend_dispatch",
) -> dict[str, Any] | None:
    """Build an external target from a call boundary or a verified probe."""
    raw: dict[str, Any] = {
        "schema": SCHEMA,
        "provider": provider,
        "model": model,
        "host": "external",
        "locality": "external",
        "source": source,
        "observed_at": _observed_at(),
    }
    if slot_id is not None:
        raw["slot_id"] = slot_id
    return project_execution_target(raw)
