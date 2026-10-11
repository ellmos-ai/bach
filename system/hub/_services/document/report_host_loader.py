# SPDX-License-Identifier: MIT
"""Optional trusted, installed report-host dependencies for Control startup."""
from __future__ import annotations

from importlib import metadata
import re
from typing import Any

HOST_DEPENDENCIES_GROUP = "ellmos.report_host_dependencies"
_CONFIG_KEYS = frozenset({"enabled", "provider_name", "agent_id"})
_DEPENDENCY_KEYS = frozenset({
    "word_template", "anonymizer", "document_reader",
    "operator_confirmation", "cloud_model",
})


def load_report_host_dependencies(configured_reports: Any) -> dict[str, Any] | None:
    """Load exactly the explicitly configured installed factory, with no fallback.

    Only startup configuration selects the entry point. The no-argument factory
    resolves its own private configuration; HTTP data never reaches discovery.
    Errors remain unavailable and never disclose plugin exceptions or paths.
    The existing host assembler validates each returned port.
    """
    if (type(configured_reports) is not dict
            or set(configured_reports) != _CONFIG_KEYS
            or configured_reports.get("enabled") is not True):
        return None
    provider = configured_reports.get("provider_name")
    agent = configured_reports.get("agent_id")
    if (not isinstance(provider, str)
            or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", provider) is None
            or not isinstance(agent, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", agent) is None):
        return None
    try:
        matches = [
            entry for entry in metadata.entry_points(group=HOST_DEPENDENCIES_GROUP)
            if entry.name == provider
        ]
        if len(matches) != 1:
            return None
        factory = matches[0].load()
        if not callable(factory):
            return None
        dependencies = factory()
        if (type(dependencies) is not dict
                or not set(dependencies).issubset(_DEPENDENCY_KEYS)):
            return None
        return dependencies
    except Exception:
        return None
