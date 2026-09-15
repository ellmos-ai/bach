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

try:
    import psutil
except ImportError:  # pragma: no cover - optional at source level; stop fails closed
    psutil = None


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
    instance = registry(Path(pid_dir))
    if not callable(getattr(instance, "probe_running", None)):
        raise AttributeError("agent-launcher AgentProcessRegistry must export probe_running")
    return instance


class AgentProcessIdentityError(RuntimeError):
    """A PID file cannot prove ownership of the current OS process."""


def capture_process_create_time(pid: int) -> float | None:
    """Capture the OS process birth time immediately after spawning."""
    if psutil is None:
        return None
    try:
        return psutil.Process(int(pid)).create_time()
    except (psutil.Error, TypeError, ValueError, OSError):
        return None


def inspect_process_identity(record: dict):
    """Return (owned|unverified|mismatch|gone|unavailable, bound process)."""
    pid = record.get("pid")
    created = record.get("process_create_time")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return "unverified", None
    if not isinstance(created, (int, float)) or isinstance(created, bool):
        return "unverified", None
    if psutil is None:
        return "unavailable", None
    try:
        process = psutil.Process(pid)
        if process.create_time() != float(created):
            return "mismatch", None
        if not process.is_running():
            return "gone", None
        return "owned", process
    except psutil.NoSuchProcess:
        return "gone", None
    except (psutil.Error, OSError, ValueError):
        return "unavailable", None


def verified_process(record: dict):
    """Return an identity-bound Process, never a bare reusable PID."""
    state, process = inspect_process_identity(record)
    if state != "owned":
        reasons = {
            "unverified": "Agent-Prozessidentität fehlt (Alt-PID-Datei)",
            "mismatch": "Agent-Prozessidentität stimmt nicht überein",
            "gone": "Agent-Prozess existiert nicht mehr",
            "unavailable": "Agent-Prozessidentität nicht lesbar",
        }
        raise AgentProcessIdentityError(reasons[state])
    return process


def terminate_verified_process(process, *, windows: bool) -> None:
    """Use psutil's PID-reuse-checked process methods, never taskkill /PID."""
    # children() also checks the parent's identity before enumerating. Stop
    # known descendants on every platform before removing the parent record.
    for child in reversed(process.children(recursive=True)):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            continue
    if windows:
        process.kill()
    else:
        process.terminate()
