#!/usr/bin/env python3
"""Run one K9 dbsync use case in an isolated process and print the observed state.

The probe is the "old/new" half of a parity test.  It is started once per
implementation so that module caches, environment switches and BACH path
constants cannot leak between runs:

* ``bach-legacy``  -- BACH ``DBSyncManager`` with ``BACH_USE_EXTERNAL_TRANSITSYNC=0``
  (the native ProSync path, i.e. the old implementation),
* ``bach-module``  -- the same BACH handler routed through the canonical
  ``sqlite-transit-sync`` module via BACH's own provider seam,
* ``ocean-module`` -- the canonical module used directly, as OCEAN composes it.

Only anonymized fixture databases below ``--workdir`` are touched.  BACH is
imported from ``--bach-root`` (never installed, never booted); its local
directory and default database are redirected into the work directory.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path

MODES = ("bach-legacy", "bach-module", "ocean-module")
USE_CASES = ("push-pull", "sync-roundtrip")
SOURCE_NODE = "node-a"
TARGET_NODE = "node-b"


def _create(path: Path, sql: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(sql.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()


def _rows(path: Path, sql: str) -> list[list]:
    connection = sqlite3.connect(path)
    try:
        return [list(row) for row in connection.execute(sql).fetchall()]
    finally:
        connection.close()


def _import_under(root: Path, name: str):
    module = importlib.import_module(name)
    module_path = Path(module.__file__).resolve()
    if not module_path.is_relative_to(root.resolve()):
        raise SystemExit(f"{name} import escaped requested root: {module_path}")
    return module


def _bach_managers(bach_root: Path, work: Path, transit: Path, dbs: dict[str, Path]):
    sys.path.insert(0, str(bach_root))
    db_sync = _import_under(bach_root, "system.hub.db_sync")
    managers = {}
    for node, db_path in dbs.items():
        manager = db_sync.DBSyncManager(db_path=db_path, transit_dir=transit)
        # Per-node identity and state, set before the lazy engine probe.
        manager.hostname = node
        manager.heartbeat_file = transit / "heartbeat.json"
        manager.local_bach_dir = work / "local" / node
        manager.local_bach_dir.mkdir(parents=True, exist_ok=True)
        managers[node] = manager
    return managers


def _ocean_syncs(work: Path, transit: Path, dbs: dict[str, Path]):
    module = importlib.import_module("sqlite_transit_sync")
    return {
        node: module.TransitSync(module.SyncConfig(
            database=db_path,
            transit=transit,
            state=work / "local" / node / "transit_sync_state" / "state.json",
            node_id=node,
            namespace="bach",
        ))
        for node, db_path in dbs.items()
    }


def run(mode: str, bach_root: Path, transit_root: Path, fixture: Path, work: Path,
        use_case: str = "push-pull") -> dict:
    if mode not in MODES or use_case not in USE_CASES:
        raise SystemExit(f"unknown mode {mode} or use case {use_case}")
    work.mkdir(parents=True, exist_ok=True)
    os.environ["BACH_LOCAL_DIR"] = str(work / "local" / "unused")
    os.environ["BACH_DB"] = str(work / "local" / "unused" / "bach.db")
    # Since BACH e619345 the native ProSync merge itself uses the module's row
    # policy, so every mode imports it from the pinned root.
    sys.path.insert(0, str(transit_root))
    _import_under(transit_root, "sqlite_transit_sync")
    if mode == "bach-legacy":
        os.environ["BACH_USE_EXTERNAL_TRANSITSYNC"] = "0"
    else:
        os.environ.pop("BACH_USE_EXTERNAL_TRANSITSYNC", None)

    transit = work / "transit"
    transit.mkdir()
    dbs = {SOURCE_NODE: work / SOURCE_NODE / "bach.db", TARGET_NODE: work / TARGET_NODE / "bach.db"}
    _create(dbs[SOURCE_NODE], fixture / "source.sql")
    _create(dbs[TARGET_NODE], fixture / "target.sql")

    item_sql = "SELECT id, value, updated_at FROM items ORDER BY id"

    def changed_rows(before: list[list]) -> int:
        # Same metric for every implementation: target rows inserted or updated.
        return len({tuple(row) for row in _rows(dbs[TARGET_NODE], item_sql)} - {tuple(row) for row in before})

    before_push = set(transit.iterdir())
    if mode == "ocean-module":
        syncs = _ocean_syncs(work, transit, dbs)
        provider = "sqlite-transit-sync"
        syncs[SOURCE_NODE].push()
        push_ok = True
        pull = syncs[TARGET_NODE].pull
        target_sync = syncs[TARGET_NODE].sync
        source_pull = syncs[SOURCE_NODE].pull
    else:
        managers = _bach_managers(bach_root, work, transit, dbs)
        engine = managers[SOURCE_NODE]._get_external_engine()
        if managers[SOURCE_NODE]._external_error:
            raise SystemExit(f"external engine error: {managers[SOURCE_NODE]._external_error}")
        provider = "sqlite-transit-sync" if engine is not None else "bach-legacy"
        push_ok, _ = managers[SOURCE_NODE].sync_on_exit()

        def pull():
            ok, message = managers[TARGET_NODE].sync_on_start()
            if not ok:
                raise SystemExit(f"pull failed: {message}")

        def target_sync():
            # BACH `dbsync sync -y`: the source heartbeat is fresh, so confirm.
            ok, message = managers[TARGET_NODE].sync(auto_confirm=True)
            if not ok:
                raise SystemExit(f"sync failed: {message}")

        def source_pull():
            ok, message = managers[SOURCE_NODE].sync_on_start()
            if not ok:
                raise SystemExit(f"pull failed: {message}")

    published = [
        path for path in set(transit.iterdir()) - before_push
        if path.name.endswith((".bachdb", ".sqlite-snapshot"))
    ]
    if len(published) != 1:
        raise SystemExit(f"expected exactly one published snapshot, got {sorted(p.name for p in published)}")
    published = published[0]
    if use_case == "sync-roundtrip":
        return _sync_roundtrip(mode, provider, push_ok, published, transit, dbs, target_sync, source_pull)
    before_first = _rows(dbs[TARGET_NODE], item_sql)
    pull()
    first_changed = changed_rows(before_first)
    before_second = _rows(dbs[TARGET_NODE], item_sql)
    pull()
    second_changed = changed_rows(before_second)
    first_ok = second_ok = True

    return {
        "mode": mode,
        "provider": provider,
        "push_ok": push_ok,
        "pull_ok": first_ok and second_ok,
        "published_secret_rows": _rows(published, "SELECT COUNT(*) FROM secrets")[0][0],
        "published_items": _rows(published, "SELECT id, value FROM items ORDER BY id"),
        "target_items": _rows(dbs[TARGET_NODE], "SELECT id, value FROM items ORDER BY id"),
        "target_secrets": _rows(dbs[TARGET_NODE], "SELECT id, value FROM secrets ORDER BY id"),
        "source_items": _rows(dbs[SOURCE_NODE], "SELECT id, value FROM items ORDER BY id"),
        "first_pull_changed": first_changed,
        "repeat_pull_changed": second_changed,
    }


def _sync_roundtrip(mode, provider, push_ok, source_snapshot, transit, dbs, target_sync, source_pull) -> dict:
    """Target runs a full sync (pull, then publish), then the source pulls it back."""
    before_sync = set(transit.iterdir())
    target_sync()
    target_published = [
        path for path in set(transit.iterdir()) - before_sync
        if path.name.endswith((".bachdb", ".sqlite-snapshot"))
    ]
    if len(target_published) != 1:
        raise SystemExit(f"sync must publish exactly one snapshot, got {sorted(p.name for p in target_published)}")
    source_pull()
    return {
        "mode": mode,
        "provider": provider,
        "push_ok": push_ok,
        "source_snapshot_secret_rows": _rows(source_snapshot, "SELECT COUNT(*) FROM secrets")[0][0],
        "target_snapshot_secret_rows": _rows(target_published[0], "SELECT COUNT(*) FROM secrets")[0][0],
        "target_snapshot_items": _rows(target_published[0], "SELECT id, value FROM items ORDER BY id"),
        "target_items": _rows(dbs[TARGET_NODE], "SELECT id, value FROM items ORDER BY id"),
        "target_secrets": _rows(dbs[TARGET_NODE], "SELECT id, value FROM secrets ORDER BY id"),
        "source_items": _rows(dbs[SOURCE_NODE], "SELECT id, value FROM items ORDER BY id"),
        "source_secrets": _rows(dbs[SOURCE_NODE], "SELECT id, value FROM secrets ORDER BY id"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--bach-root", type=Path, required=True)
    parser.add_argument("--transit-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--use-case", default="push-pull", choices=USE_CASES)
    args = parser.parse_args()
    result = run(args.mode, args.bach_root, args.transit_root, args.fixture, args.workdir, args.use_case)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
