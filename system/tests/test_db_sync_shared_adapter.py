"""Hermetic BACH translation tests, not native/three-way or live parity.

Run with REQUIRE_SHARED_DBSYNC=1, SHARED_DBSYNC_OCEAN_ROOT and
TRANSIT_SYNC_ROOT pointing at the explicitly pinned source checkouts.
"""
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
import types
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hub.db_sync import DBSyncHandler
from hub.db_sync_adapter import SharedDBSyncAdapter, SharedDBSyncConfig


@pytest.mark.parametrize('value', [None, 0, 1, "false", [], {}])
def test_nonboolean_preview_never_authorizes(seam, value):
    adapter, root = seam
    before = tree(root)
    ok, text = handler(adapter, 'enable', dry_run=value)
    assert not ok and 'boolean-dry-run-required' in text
    assert tree(root) == before


def test_private_modules_not_left_in_global_registry(seam):
    adapter, root = seam
    before = {k for k in sys.modules if k.startswith('_bach_shared_dbsync_')}
    for _ in range(3):
        assert adapter.handle('init').ok
    after = {k for k in sys.modules if k.startswith('_bach_shared_dbsync_')}
    assert before == after


def tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def seam(tmp_path, monkeypatch):
    roots = []
    for variable in ("SHARED_DBSYNC_OCEAN_ROOT", "TRANSIT_SYNC_ROOT"):
        value = os.environ.get(variable)
        if not value or not Path(value).is_absolute() or not Path(value).is_dir():
            if os.environ.get("REQUIRE_SHARED_DBSYNC") == "1":
                pytest.fail(f"explicit pinned source required: {variable}")
            pytest.skip(f"explicit pinned source absent: {variable}")
        roots.append(Path(value))
    ocean, carrier = roots
    db = tmp_path / "data[1].sqlite"
    with closing(sqlite3.connect(db)) as connection:
        connection.executescript("""
            PRAGMA user_version=1;
            CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT, updated_at TEXT);
            CREATE TABLE secrets(id INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO tasks VALUES(1,'synthetic task','2026-09-30T00:00:00Z');
            INSERT INTO secrets VALUES(1,'synthetic-private-only');
        """)
        connection.commit()
    transit = tmp_path / "transit"
    transit.mkdir()
    state = tmp_path / "state" / "carrier.json"
    state.parent.mkdir()
    config = SharedDBSyncConfig(db, transit, state, tmp_path / "marker" / "enabled",
                              tmp_path / "heartbeat" / "status.json", "synthetic_node",
                              "bach", {"tasks": ("id", "title", "updated_at"),
                                       "secrets": ("id", "value")}, 1)
    clock = lambda: datetime(2026, 9, 30, tzinfo=timezone.utc)
    adapter = SharedDBSyncAdapter(config, ocean_root=ocean, carrier_root=carrier, clock=clock)

    def forbidden(*args, **kwargs):
        raise AssertionError("HOME/network/native manager access forbidden")

    monkeypatch.setattr(Path, "home", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("hub.db_sync.DBSyncManager", forbidden)
    yield adapter, tmp_path


def handler(adapter, operation, args=None, *, dry_run):
    # Explicit selection precedes native manager/base-path use. No runtime app
    # or startup is constructed to call the actual handler branch.
    return DBSyncHandler.handle(None, operation, [] if args is None else args,
                                dry_run=dry_run, shared_adapter=adapter)


@pytest.mark.parametrize("operation", ["backup", "enable", "disable", "cleanup", "init"])
def test_preview_changes_no_files(seam, operation):
    adapter, root = seam
    before = tree(root)
    result = adapter.handle(operation, dry_run=True,
                            scope="all-nodes" if operation == "cleanup" else None)
    assert result.outcome == "dry-run" and result.code == "ok"
    assert tree(root) == before


def test_api_default_is_preview_but_handler_false_is_apply(seam):
    adapter, root = seam
    before = tree(root)
    assert adapter.handle("enable").outcome == "dry-run"
    assert tree(root) == before
    ok, text = handler(adapter, "enable", dry_run=False)
    assert ok and "supported [ok]" in text
    assert adapter.config.marker.read_bytes() == b"enabled"


def test_backup_apply_uses_shared_carrier_and_keeps_local_secret(seam):
    adapter, _root = seam
    source_before = adapter.config.database.read_bytes()
    result = adapter.handle("backup", dry_run=False)
    assert result.outcome == "supported"
    path = Path(result.data["snapshot"]["path"])
    assert path.parent == adapter.config.transit
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM secrets").fetchone() == (0,)
        assert connection.execute("SELECT title FROM tasks").fetchone() == ("synthetic task",)
    assert adapter.config.database.read_bytes() == source_before
    heartbeat = json.loads(adapter.config.heartbeat.read_text())
    assert heartbeat[adapter.config.node_id]["last_seen"] == "2026-09-30T00:00:00+00:00"
    assert heartbeat[adapter.config.node_id]["active"] is True


def test_status_has_verified_metadata_and_no_changes(seam):
    adapter, root = seam
    assert adapter.handle("backup", dry_run=False).ok
    before = tree(root)
    result = adapter.handle("status", dry_run=False)
    assert result.outcome == "supported"
    assert len(result.data["verified_snapshots"]) == 1
    assert result.data["carrier"]["namespace"] == "bach"
    assert tree(root) == before
    ok, text = handler(adapter, "status", dry_run=True)
    assert ok and "supported [ok]" in text
    assert tree(root) == before


def test_marker_apply_is_owned_and_idempotent(seam):
    adapter, root = seam
    assert handler(adapter, "enable", dry_run=False)[0]
    before = tree(root)
    assert handler(adapter, "enable", dry_run=False)[0]
    assert tree(root) == before
    assert handler(adapter, "disable", dry_run=False)[0]
    assert not adapter.config.marker.exists()
    before = tree(root)
    assert handler(adapter, "disable", dry_run=False)[0]
    assert tree(root) == before


@pytest.mark.parametrize("operation", ["enable", "disable"])
def test_foreign_marker_refused_no_fallback(seam, operation):
    adapter, root = seam
    adapter.config.marker.parent.mkdir()
    adapter.config.marker.write_bytes(b"foreign marker")
    before = tree(root)
    ok, text = handler(adapter, operation, dry_run=False)
    assert not ok and "foreign-marker-refused" in text
    assert tree(root) == before


def test_cleanup_requires_selected_scope_and_applies_explicitly(seam):
    adapter, root = seam
    before = tree(root)
    ok, text = handler(adapter, "cleanup", dry_run=False)
    assert not ok and "explicit-cleanup-scope-required" in text
    assert tree(root) == before
    for args in (["--local-node"], ["--all-nodes"]):
        ok, text = handler(adapter, "cleanup", args, dry_run=True)
        assert ok and "dry-run [ok]" in text
        assert tree(root) == before
        ok, text = handler(adapter, "cleanup", args, dry_run=False)
        assert ok and "supported [ok]" in text


@pytest.mark.parametrize("operation", ["push", "pull", "sync", "db_sync", "backup-alias", "STATUS"])
def test_other_operations_and_aliases_refused_no_native_fallback(seam, operation):
    adapter, root = seam
    before = tree(root)
    ok, text = handler(adapter, operation, dry_run=False)
    assert not ok and "operation-outside-shared-scope" in text
    assert tree(root) == before


@pytest.mark.parametrize("args", [["--auto"], ["--all-nodes", "--local-node"], ["--scope=all"]])
def test_unsupported_arguments_refused(seam, args):
    adapter, root = seam
    before = tree(root)
    assert not handler(adapter, "cleanup", args, dry_run=False)[0]
    assert tree(root) == before


@pytest.mark.parametrize("version", [0, 2])
def test_actual_database_version_mismatch_is_not_stamped(seam, version):
    adapter, root = seam
    with closing(sqlite3.connect(adapter.config.database)) as connection:
        connection.execute(f"PRAGMA user_version={version}")
    before = tree(root)
    ok, text = handler(adapter, "init", dry_run=False)
    assert not ok and "application-schema-version-mismatch" in text
    assert tree(root) == before


def test_native_zero_contract_refused_before_init(seam):
    adapter, root = seam
    adapter.config = replace(adapter.config, user_version=0)
    before = tree(root)
    ok, text = handler(adapter, "init", dry_run=False)
    assert not ok and "explicit-schema-version-required" in text
    assert tree(root) == before


@pytest.mark.parametrize("kind", ["missing", "columns", "namespace", "node"])
def test_application_identity_and_schema_fail_closed(seam, kind):
    adapter, root = seam
    if kind == "missing":
        adapter.config.database.unlink()
    elif kind == "columns":
        adapter.config = replace(adapter.config, required_schema={"unknown_table": ("id",)})
    elif kind == "namespace":
        adapter.config = replace(adapter.config, namespace="other")
    else:
        adapter.config = replace(adapter.config, node_id="bad node id")
    before = tree(root)
    assert not handler(adapter, "init", dry_run=False)[0]
    assert tree(root) == before


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_literal_sidecars_refused_before_publication(seam, sidecar):
    adapter, root = seam
    Path(str(adapter.config.database) + sidecar).write_bytes(b"synthetic sidecar")
    before = tree(root)
    ok, text = handler(adapter, "backup", dry_run=False)
    assert not ok and "database-sidecars-refused" in text
    assert tree(root) == before


def test_generated_credential_shape_refused_before_publication(seam):
    adapter, root = seam
    with closing(sqlite3.connect(adapter.config.database)) as connection:
        connection.execute("CREATE TABLE extra(value TEXT, tail TEXT, private_note TEXT GENERATED ALWAYS AS (value||tail) STORED)")
        connection.commit()
    before = tree(root)
    ok, text = handler(adapter, "backup", dry_run=False)
    assert not ok and "unsupported-table-columns" in text
    assert tree(root) == before


@pytest.mark.parametrize("target", ["ocean", "core", "credentials"])
def test_modified_source_refused_before_execute(seam, target):
    adapter, root = seam
    if target == "ocean":
        new = root / "ocean"
        (new / "tools").mkdir(parents=True)
        path = new / "tools" / "dbsync_adapter.py"
        path.write_bytes(b"raise AssertionError('must not execute')\n")
        adapter.ocean_root = new
    else:
        new = root / "carrier"
        shutil.copytree(adapter.carrier_root / "sqlite_transit_sync", new / "sqlite_transit_sync")
        filename = "core.py" if target == "core" else "credential-triggers.json"
        (new / "sqlite_transit_sync" / filename).write_bytes(b"untrusted")
        adapter.carrier_root = new
    before = tree(root)
    ok, text = handler(adapter, "backup", dry_run=False)
    assert not ok and "pin-mismatch" in text
    assert tree(root) == before


def test_generic_tools_module_and_cached_bytecode_not_imported(seam, monkeypatch):
    adapter, root = seam
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    poison = types.ModuleType("tools.dbsync_adapter")
    poison.DBSyncAdapter = lambda *a, **k: pytest.fail("ambient tools executed")
    monkeypatch.setitem(sys.modules, "tools.dbsync_adapter", poison)
    before = tree(root)
    assert handler(adapter, "init", dry_run=True)[0]
    assert tree(root) == before
    assert not any(p.name == "__pycache__" for p in root.rglob("*"))


def test_missing_source_no_installed_fallback(seam):
    adapter, root = seam
    adapter.ocean_root = root / "missing-ocean"
    before = tree(root)
    ok, text = handler(adapter, "init", dry_run=False)
    assert not ok and "ocean-adapter-source-missing" in text
    assert tree(root) == before


def test_heartbeat_partial_failure_remains_error_with_snapshot(seam, monkeypatch):
    adapter, _root = seam
    original_replace = os.replace

    def fail_heartbeat(source, destination):
        if Path(destination) == adapter.config.heartbeat:
            raise PermissionError("synthetic heartbeat publication failure")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_heartbeat)
    source_before = adapter.config.database.read_bytes()
    result = adapter.handle("backup", dry_run=False)
    assert result.outcome == "error" and result.code == "snapshot-published-heartbeat-failed"
    assert Path(result.data["snapshot"]["path"]).is_file()
    assert adapter.config.database.read_bytes() == source_before
    assert not adapter.config.heartbeat.exists()


def test_explicit_path_overlap_and_relative_paths_refused(seam):
    adapter, root = seam
    for config in (replace(adapter.config, marker=adapter.config.database),
                   replace(adapter.config, database=Path("relative.sqlite"))):
        adapter.config = config
        before = tree(root)
        assert not handler(adapter, "init", dry_run=False)[0]
        assert tree(root) == before


def test_invalid_selector_is_not_native_fallback(seam):
    _, root = seam
    before = tree(root)
    ok, text = handler(object(), "backup", dry_run=False)
    assert not ok and "invalid-adapter" in text
    assert tree(root) == before


def test_native_selection_rollback_preserves_shared_artifacts(seam, monkeypatch):
    adapter, root = seam
    assert handler(adapter, "enable", dry_run=False)[0]
    before = tree(root)
    calls = []

    class NativeProbe:
        def __init__(self):
            calls.append("constructed")

        def get_status(self):
            return "native dispatch probe (no live data)"

    monkeypatch.setattr("hub.db_sync.DBSyncManager", NativeProbe)
    ok, text = DBSyncHandler.handle(None, "status", [], dry_run=True)
    assert ok and text == "native dispatch probe (no live data)"
    assert calls == ["constructed"]
    assert tree(root) == before
    # This is selection rollback only, not migrated native-state equivalence.


def test_credential_scan_failure_removes_partial_and_leaves_source(seam):
    adapter, _root = seam
    token = "sk-" + "syntheticOnlyNotACredential" * 2
    with closing(sqlite3.connect(adapter.config.database)) as connection:
        connection.execute("UPDATE tasks SET title=?", (token,))
        connection.commit()
    source = adapter.config.database.read_bytes()
    result = adapter.handle("backup", dry_run=False)
    assert result.outcome == "error" and result.code == "carrier-call-failed-state-unknown"
    assert result.data["error_class"] == "SyncError"
    assert not list(adapter.config.transit.iterdir())
    assert adapter.config.database.read_bytes() == source
    assert token not in str(result)
    assert not adapter.config.heartbeat.exists()


def test_heartbeat_partial_failure_handler_is_false_not_rollback(seam, monkeypatch):
    adapter, _root = seam
    original_replace = os.replace

    def fail_heartbeat(source, destination):
        if Path(destination) == adapter.config.heartbeat:
            raise PermissionError("synthetic heartbeat publication failure")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_heartbeat)
    ok, text = handler(adapter, "backup", dry_run=False)
    assert not ok and "error [snapshot-published-heartbeat-failed]" in text
    assert list(adapter.config.transit.glob("*.sqlite-snapshot"))


def test_carrier_state_corruption_refused_without_reset(seam):
    adapter, root = seam
    adapter.config.state.write_text('{"protocol":999,"last_pulled":{}}')
    before = tree(root)
    ok, text = handler(adapter, "backup", dry_run=False)
    assert not ok and "invalid-carrier-state" in text
    assert tree(root) == before


def test_source_symlink_refused_or_native_privilege_explicit(seam):
    adapter, root = seam
    new = root / "linked-ocean"
    (new / "tools").mkdir(parents=True)
    target = new / "tools" / "dbsync_adapter.py"
    try:
        target.symlink_to(adapter.ocean_root / "tools" / "dbsync_adapter.py")
    except OSError as error:
        # The Windows host denies creating links without the privilege. This
        # is not a synthetic POSIX link-proof; the POSIX run executes the guard.
        assert os.name == "nt" and error.winerror == 1314
        return
    adapter.ocean_root = new
    before = tree(root)
    ok, text = handler(adapter, "init", dry_run=False)
    assert not ok and "linked-ocean-source-refused" in text
    assert tree(root) == before


def test_cleanup_apply_selected_local_then_all_nodes(seam):
    adapter, root = seam
    local = adapter.handle("backup", dry_run=False).data["snapshot"]["path"]
    other = SharedDBSyncAdapter(replace(adapter.config, node_id="synthetic_foreign"),
                                ocean_root=adapter.ocean_root,
                                carrier_root=adapter.carrier_root, clock=adapter.clock)
    foreign = other.handle("backup", dry_run=False).data["snapshot"]["path"]
    before = tree(root)
    preview = adapter.handle("cleanup", dry_run=True, scope="all-nodes",
                             keep_days=0, keep_per_node=0)
    assert preview.outcome == "dry-run" and len(preview.data["eligible"]) == 2
    assert preview.data["deleted"] == []
    assert tree(root) == before
    selected = adapter.handle("cleanup", dry_run=False, scope="local-node",
                              keep_days=0, keep_per_node=0)
    assert selected.outcome == "supported" and len(selected.data["deleted"]) == 1
    assert not Path(local).exists() and Path(foreign).exists()
    selected = adapter.handle("cleanup", dry_run=False, scope="all-nodes",
                              keep_days=0, keep_per_node=0)
    assert selected.outcome == "supported" and len(selected.data["deleted"]) == 1
    assert not Path(foreign).exists()


def test_atomic_marker_replace_failure_leaves_no_partial_marker(seam, monkeypatch):
    adapter, root = seam
    adapter.config.marker.parent.mkdir()
    before = tree(root)

    def fail_replace(*args):
        raise PermissionError("synthetic marker write failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    ok, text = handler(adapter, "enable", dry_run=False)
    assert not ok and "error [operation-failed]" in text
    assert tree(root) == before and not adapter.config.marker.exists()


def test_cleanup_invalid_retention_refused_no_deletion(seam):
    adapter, root = seam
    assert adapter.handle("backup", dry_run=False).ok
    before = tree(root)
    result = adapter.handle("cleanup", dry_run=False, scope="all-nodes", keep_days=-1)
    assert result.outcome == "refused" and result.code == "invalid-retention"
    assert tree(root) == before
