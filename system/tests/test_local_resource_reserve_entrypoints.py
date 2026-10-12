# SPDX-License-Identifier: MIT
"""Real API-entrypoint regressions for metadata-only local reserve probes."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_PROBE = r"""
import json, os, sqlite3, sys
from pathlib import Path
repo = Path(sys.argv[1])
layout = sys.argv[2]
sys.path[:0] = ([str(repo), str(repo / "system")] if layout == "editable-root"
               else [str(repo / "system"), str(repo)])
def forbidden_connect(*args, **kwargs):
    raise AssertionError("reserve path inspection must never open SQLite")
sqlite3.connect = forbidden_connect
import bach_api
origin = Path(bach_api.__file__).resolve()
expected = repo / ("bach_api.py" if layout == "editable-root" else "system/bach_api.py")
assert origin == expected.resolve(), (origin, expected)
if layout == "editable-root":
    assert not hasattr(bach_api, "_resolve_db_path"), "do not widen private shim exports"
from hub.bach_paths import BACH_DB
from hub._services.chat.local_resource_reserve import _data_roots
roots = _data_roots()
assert roots["taskdb"] == Path(os.environ["BACH_DB"]).parent
assert BACH_DB == Path(os.environ["BACH_DB"])
print(json.dumps({"api_origin": str(origin), "taskdb_root": str(roots["taskdb"])}))
"""


@pytest.mark.parametrize("layout", ["editable-root", "system"])
@pytest.mark.parametrize("existing_database", [False, True])
def test_reserve_paths_use_canonical_registry_without_opening_database(
    tmp_path, layout, existing_database
):
    home = tmp_path / "home"
    home.mkdir()
    database_dir = home / "selected-ledger"
    database_dir.mkdir()
    database = database_dir / "bach.db"
    if existing_database:
        database.write_bytes(b"reserve-probe-sentinel-not-a-sqlite-database")
    before = {
        str(path.relative_to(home)): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in home.rglob("*") if path.is_file()
    }
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        BACH_DB=str(database),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
    )
    env.pop("BACH_ALLOW_ONEDRIVE_DB_FALLBACK", None)
    result = subprocess.run(
        [sys.executable, "-B", "-c", _PROBE, str(REPO), layout],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed["taskdb_root"] == str(database_dir)
    after = {
        str(path.relative_to(home)): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in home.rglob("*") if path.is_file()
    }
    assert after == before
    assert database.exists() is existing_database
    assert not Path(str(database) + "-wal").exists()
    assert not Path(str(database) + "-shm").exists()
