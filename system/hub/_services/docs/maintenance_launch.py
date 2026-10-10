"""Portable activation plan; generation never installs or starts a service."""

from __future__ import annotations

import plistlib
from pathlib import Path


def launch_plan(root: Path, python: Path, task_db: Path, runtime: Path, config: Path):
    script = root / "system/tools/maintenance/scheduler_maintenance.py"
    if (
        not python.is_file()
        or not script.is_file()
        or not all(p.is_absolute() for p in (root, python, task_db, runtime, config))
    ):
        raise ValueError("Explicit installed paths required")
    arguments = [
        str(python),
        str(script),
        "serve",
        "--config",
        str(config),
        "--runtime-dir",
        str(runtime),
    ]
    value = {
        "Label": "org.ellmos.bach.docs-maintenance",
        "ProgramArguments": arguments,
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 60,
        "EnvironmentVariables": {
            "BACH_DB": str(task_db),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    }
    return {
        "schema": "bach.maintenance-launch-plan.v1",
        "platform": "macos",
        "installed": False,
        "started": False,
        "requires_integrated_revision": True,
        "label": value["Label"],
        "program_arguments": arguments,
        "launch_agent": plistlib.dumps(value).decode("utf-8"),
        "rollback": "Unload this exact LaunchAgent; set enabled=false; retain native receipts. "
        "Legacy session daemon stays disabled.",
    }
