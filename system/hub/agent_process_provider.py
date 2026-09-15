"""Optional named-agent process registry supplied by agent-launcher.

The BACH agent handler retains its own CLI, persona resolution and launch
policy. Only the process liveness boundary may be delegated here; disabling
the seam immediately restores the legacy reader without moving PID state.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path


ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_AGENT_REGISTRY"
_ON_VALUES = {"1", "true", "yes", "on"}


def external_registry_available() -> bool:
    """Probe only; do not import the module or touch a process registry."""
    if os.environ.get(ROLLBACK_ENV_VAR, "").strip().lower() not in _ON_VALUES:
        return False
    return importlib.util.find_spec("agent_launcher") is not None


def create_agent_registry(pid_dir: str | Path):
    """Construct the external reader, failing loudly on a broken contract."""
    if not external_registry_available():
        return None
    module = importlib.import_module("agent_launcher")
    registry = getattr(module, "AgentProcessRegistry", None)
    if registry is None:
        raise AttributeError("agent-launcher must export AgentProcessRegistry")
    return registry(Path(pid_dir))
