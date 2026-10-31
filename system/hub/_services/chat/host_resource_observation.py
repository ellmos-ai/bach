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
