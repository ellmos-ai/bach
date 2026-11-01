# SPDX-License-Identifier: MIT
"""Native host observations, separate from inference admission decisions.

Compression and swap are observations, never additional available memory.
Darwin-only commands are bounded and never run on Windows.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone

import psutil

OBSERVATION_SCHEMA = "bach.host-resource-observation.v1"
_ERRORS = frozenset({
    "swap_observation_unavailable", "darwin_pressure_observation_unsupported",
    "pressure_observation_unavailable", "compression_observation_unavailable",
    "compression_page_size_unverified",
})
_OBSERVED = frozenset({
    "schema", "checked_at", "platform", "memory_total_bytes", "memory_available_bytes",
    "compression_added_to_capacity", "swap_added_to_capacity", "pressure_level",
    "compressor_physical_bytes", "compressor_logical_bytes", "swap_total_bytes",
    "swap_used_bytes", "errors",
})
_MAX_BYTES = 4096 * 1024**3
_PAGE = re.compile(r"page size of (\d+) bytes")
_COUNTER = re.compile(r'^([^:]+):\s*(\d+)\.?\s*$', re.MULTILINE)


def _darwin_counter_command(command):
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=2, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def valid_host_resources(value):
    """True only for what observe_host_resources (or probe's failure stub) produces:
    exact fields, typed and bounded counters, and never compression or swap as capacity."""
    if not isinstance(value, dict) or value.get("schema") != OBSERVATION_SCHEMA:
        return False
    if set(value) == {"schema", "errors"}:
        return value["errors"] == ["host_observation_failed"]
    if not _OBSERVED <= set(value) <= _OBSERVED | {"page_size_bytes"}:
        return False
    errors = value["errors"]
    if (not isinstance(errors, list) or len(errors) > len(_ERRORS)
            or any(not isinstance(error, str) or error not in _ERRORS for error in errors)):
        return False

    def counter(raw, low=0):
        return type(raw) is int and low <= raw <= _MAX_BYTES

    checked_at = value["checked_at"]
    try:
        parsed = datetime.fromisoformat(checked_at) if isinstance(checked_at, str) and len(checked_at) <= 40 else None
    except ValueError:
        parsed = None
    page_size = value.get("page_size_bytes", 4096)
    return (parsed is not None and parsed.tzinfo is not None
            and isinstance(value["platform"], str) and re.fullmatch(r"[a-z0-9]{1,32}", value["platform"]) is not None
            and counter(value["memory_total_bytes"], 1) and counter(value["memory_available_bytes"])
            and value["memory_available_bytes"] <= value["memory_total_bytes"]
            and value["compression_added_to_capacity"] is False and value["swap_added_to_capacity"] is False
            and (value["pressure_level"] is None
                 or (type(value["pressure_level"]) is int and value["pressure_level"] in {1, 2, 4}))
            and all(value[name] is None or counter(value[name]) for name in (
                "compressor_physical_bytes", "compressor_logical_bytes", "swap_total_bytes", "swap_used_bytes"))
            and type(page_size) is int and page_size in {4096, 16384, 65536})


def observe_host_resources(memory):
    """Return measured counters without changing the admission arithmetic."""
    result = {
        "schema": "bach.host-resource-observation.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "platform": sys.platform,
        "memory_total_bytes": int(memory.total),
        "memory_available_bytes": int(memory.available),
        "compression_added_to_capacity": False,
        "swap_added_to_capacity": False,
        "pressure_level": None,
        "compressor_physical_bytes": None,
        "compressor_logical_bytes": None,
        "swap_total_bytes": None,
        "swap_used_bytes": None,
        "errors": [],
    }
    try:
        swap = psutil.swap_memory()
        result.update(swap_total_bytes=int(swap.total), swap_used_bytes=int(swap.used))
    except (OSError, RuntimeError, AttributeError, ValueError, psutil.Error):
        result["errors"].append("swap_observation_unavailable")
    if sys.platform != "darwin":
        result["errors"].append("darwin_pressure_observation_unsupported")
        return result
    pressure = _darwin_counter_command(
        ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"]
    )
    if pressure is not None and pressure.strip() in {"1", "2", "4"}:
        result["pressure_level"] = int(pressure.strip())
    else:
        result["errors"].append("pressure_observation_unavailable")
    raw = _darwin_counter_command(["/usr/bin/vm_stat"])
    page = _PAGE.search(raw) if raw is not None else None
    counts = dict(_COUNTER.findall(raw)) if raw is not None else {}
    if page is None or not all(name in counts for name in (
        "Pages occupied by compressor", "Pages stored in compressor"
    )):
        result["errors"].append("compression_observation_unavailable")
        return result
    page_bytes = int(page.group(1))
    if page_bytes not in {4096, 16384, 65536}:
        result["errors"].append("compression_page_size_unverified")
        return result
    result.update(
        page_size_bytes=page_bytes,
        compressor_physical_bytes=int(counts["Pages occupied by compressor"]) * page_bytes,
        compressor_logical_bytes=int(counts["Pages stored in compressor"]) * page_bytes,
    )
    return result
