# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Negative side-effect tests for BACH CLI --dry-run."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
BACH_ROOT = SYSTEM_ROOT.parent


def runtime_snapshot(runtime_dir: Path) -> dict[str, str]:
    """Return a hash mapping of all files in runtime_dir."""
    snapshot: dict[str, str] = {}
    if not runtime_dir.exists():
        return snapshot
    for p in sorted(runtime_dir.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(runtime_dir))
            snapshot[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snapshot


def _run_bach(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(BACH_ROOT / "bach.py"), *args]
    return subprocess.run(
        cmd,
        cwd=str(BACH_ROOT),
        env=env,
        text=True,
        capture_output=True,
    )


def test_dry_run_fs_no_side_effects(isolated_runtime):
    """Ensure `bach fs heal --dry-run` and `bach fs backup --dry-run` do not write to BACH_RUNTIME."""
    env = os.environ.copy()
    env["BACH_RUNTIME_DIR"] = str(isolated_runtime)
    env["BACH_RUNTIME"] = str(isolated_runtime)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    before = runtime_snapshot(isolated_runtime)

    _run_bach("fs", "heal", "--dry-run", env=env)
    _run_bach("fs", "backup", "--dry-run", env=env)

    after = runtime_snapshot(isolated_runtime)
    assert before == after, f"Dry-run modified runtime directory: {set(after) ^ set(before)}"
