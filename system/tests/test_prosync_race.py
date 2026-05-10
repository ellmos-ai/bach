#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Regression test: sync-state tracking prevents mtime race condition.

The old find_newer_backups() compared backup mtime vs local DB mtime.
If the local DB was modified after a remote backup arrived, the backup
was never detected. The fix uses sync_state.json per-host tracking.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_DIR))

from hub.db_sync import DBSyncManager


def _create_minimal_db(path: Path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR IGNORE INTO system_config VALUES ('version', '2.5')")
    conn.commit()
    conn.close()


def test_race_condition():
    """Modifying local DB after backup arrives must NOT hide the backup."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        transit = tmp / "transit"
        transit.mkdir()
        local_bach = tmp / "local_bach"
        local_bach.mkdir()
        db_path = local_bach / "bach.db"

        _create_minimal_db(db_path)

        backup = transit / "bach_remote-host_2026-05-10T12-00-00.bachdb"
        _create_minimal_db(backup)
        time.sleep(0.05)

        # Simulate local DB modification AFTER backup arrived (the race)
        db_path.write_bytes(db_path.read_bytes())
        assert db_path.stat().st_mtime >= backup.stat().st_mtime

        mgr = DBSyncManager(db_path=db_path, transit_dir=transit)
        mgr.local_bach_dir = local_bach
        mgr.hostname = "local-host"

        newer = mgr.find_newer_backups()
        assert len(newer) == 1, f"Expected 1 backup, got {len(newer)} — race condition regression!"
        assert "remote-host" in newer[0].name

        # After "pulling", mark it — should not appear again
        state = mgr._load_sync_state()
        state.setdefault("last_pulled", {})["remote-host"] = backup.stat().st_mtime
        mgr._save_sync_state(state)

        newer_after = mgr.find_newer_backups()
        assert len(newer_after) == 0, f"Expected 0 after pull, got {len(newer_after)} — idempotency broken!"

    print("[PASS] test_race_condition: mtime race correctly handled by sync-state tracking")


def test_own_backups_excluded():
    """Backups from own hostname must never appear in find_newer_backups()."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        transit = tmp / "transit"
        transit.mkdir()
        local_bach = tmp / "local_bach"
        local_bach.mkdir()
        db_path = local_bach / "bach.db"

        _create_minimal_db(db_path)

        own = transit / "bach_local-host_2026-05-10T12-00-00.bachdb"
        _create_minimal_db(own)

        mgr = DBSyncManager(db_path=db_path, transit_dir=transit)
        mgr.local_bach_dir = local_bach
        mgr.hostname = "local-host"

        assert len(mgr.find_newer_backups()) == 0, "Own backups must be excluded!"

    print("[PASS] test_own_backups_excluded")


def test_extract_host():
    """Hostname extraction from backup filename."""
    assert DBSyncManager._extract_host(Path("bach_Mac-Studio_2026-05-10T04-47-52.bachdb")) == "Mac-Studio"
    assert DBSyncManager._extract_host(Path("bach_ASUS-GEI_2026-05-10T04-45-22.bachdb")) == "ASUS-GEI"
    assert DBSyncManager._extract_host(Path("random_file.bachdb")) is None
    print("[PASS] test_extract_host")


if __name__ == "__main__":
    test_extract_host()
    test_own_backups_excluded()
    test_race_condition()
    print("\nAlle ProSync Race-Condition Tests bestanden.")
