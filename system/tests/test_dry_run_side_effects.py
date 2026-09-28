# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Negative side-effect tests for BACH CLI --dry-run."""

import hashlib
import os
import sqlite3
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


def test_dry_run_task_no_side_effects(isolated_runtime, tmp_path):
    """Ensure `bach task add --dry-run` creates no task, and `bach task done --dry-run` preserves status and runtime."""
    db_path = tmp_path / "test_tasks.db"
    conn = sqlite3.connect(db_path)
    schema_sql = (SYSTEM_ROOT / "data" / "schema" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.close()

    env = os.environ.copy()
    env["BACH_RUNTIME_DIR"] = str(isolated_runtime)
    env["BACH_RUNTIME"] = str(isolated_runtime)
    env["BACH_DB"] = str(db_path)
    env["BACH_RHEINGOLD_DISABLED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    before_add = runtime_snapshot(isolated_runtime)

    # 1. Prüfen, dass `bach task add --dry-run` keinen Task anlegt
    res_dry = _run_bach("task", "add", "DryRunTestTask", "--dry-run", env=env)
    assert res_dry.returncode == 0
    after_dry_add = runtime_snapshot(isolated_runtime)
    assert before_add == after_dry_add, f"Dry-run task add modified runtime directory: {set(after_dry_add) ^ set(before_add)}"

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    assert count == 0, f"Expected 0 tasks in DB after dry-run, found {count}"

    # 2. Echten Task anlegen, ID merken
    res_real = _run_bach("task", "add", "RealTaskForDryRunDone", env=env)
    assert res_real.returncode == 0

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT id, status FROM tasks WHERE title = 'RealTaskForDryRunDone'").fetchone()
    conn.close()
    assert row is not None, "Real task was not created in DB"
    task_id, initial_status = row[0], row[1]
    assert initial_status != "done"

    # 3. Snapshot vor done --dry-run
    before_done = runtime_snapshot(isolated_runtime)

    # 4. Pruefen, dass `bach task done <id> --dry-run` den Status nicht aendert
    res_done_dry = _run_bach("task", "done", str(task_id), "--dry-run", env=env)
    assert res_done_dry.returncode == 0

    after_done = runtime_snapshot(isolated_runtime)
    assert before_done == after_done, f"Dry-run task done modified runtime directory: {set(after_done) ^ set(before_done)}"

    conn = sqlite3.connect(db_path)
    status_after = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
    conn.close()
    assert status_after == initial_status, f"Expected task status {initial_status}, but was {status_after}"
