"""Portable activation plan; generation never installs or starts a service."""

from __future__ import annotations

import os
import plistlib
import shutil
from pathlib import Path

LAUNCHD_DEFAULT_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")


def service_path() -> str:
    """PATH for the LaunchAgent.

    launchd starts agents with /usr/bin:/bin:/usr/sbin:/sbin. On macOS /usr/bin/git is the
    Xcode shim, which exits non-zero until the Xcode license is accepted; the documentation
    dispatcher then fails with CalledProcessError (measured on the Mac Studio 14.11.2026).
    The directory of the git found when the plan is generated goes first.
    """
    git = shutil.which("git")
    first = [os.path.dirname(git)] if git else []
    return ":".join(dict.fromkeys([*first, *LAUNCHD_DEFAULT_PATH]))


def launch_plan(root: Path, python: Path, task_db: Path, runtime: Path, config: Path):
    script = root / "system/tools/maintenance/scheduler_maintenance.py"
    if (
        not python.is_file()
        or not script.is_file()
        or not all(p.is_absolute() for p in (root, python, task_db, runtime, config))
    ):
        raise ValueError("Explicit installed paths required")
    local_runtime = task_db.resolve().parent / "maintenance"
    runtime = runtime.resolve()
    if runtime != local_runtime or any(
        "onedrive" in part.casefold() for part in runtime.parts
    ):
        raise ValueError("Canonical local maintenance runtime required")
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
        "StandardOutPath": str(runtime / "scheduler.stdout.log"),
        "StandardErrorPath": str(runtime / "scheduler.stderr.log"),
        "Umask": "077",
        "KeepAlive": True,
        "ThrottleInterval": 60,
        "EnvironmentVariables": {
            "BACH_DB": str(task_db),
            "PATH": service_path(),
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
