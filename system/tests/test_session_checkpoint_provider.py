# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the fail-soft SnapshotHandler session-checkpoint provider seam."""

import sqlite3
import sys
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
TESTS_ROOT = Path(__file__).parent
for _path in (SYSTEM_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from session_checkpoint import CheckpointStore

from hub import session_checkpoint_adapter
from hub import session_checkpoint_provider
from hub.snapshot import SnapshotHandler
from test_snapshot_handler import snap_env


def test_get_checkpoint_store_respects_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv(session_checkpoint_provider.ROLLBACK_ENV_VAR, "0")

    assert session_checkpoint_provider.get_checkpoint_store(tmp_path) is None
    assert not session_checkpoint_provider.checkpoint_store_path(tmp_path).exists()


def test_get_checkpoint_store_returns_real_store(tmp_path, monkeypatch):
    monkeypatch.delenv(session_checkpoint_provider.ROLLBACK_ENV_VAR, raising=False)

    store = session_checkpoint_provider.get_checkpoint_store(tmp_path)

    assert isinstance(store, CheckpointStore)


def test_snapshot_create_load_roundtrip_through_carrier(snap_env, monkeypatch):
    monkeypatch.delenv(session_checkpoint_provider.ROLLBACK_ENV_VAR, raising=False)
    handler, base_path, db_path = snap_env
    handler = SnapshotHandler(base_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO tasks (title, status) VALUES (?, ?)",
        ("roundtrip task", "pending"),
    )
    conn.execute(
        "INSERT INTO memory_working (type, content, is_active) VALUES (?, ?, 1)",
        ("note", "roundtrip memory"),
    )
    conn.commit()
    conn.close()

    ok, output = handler.handle("create", ["roundtrip-test"])

    assert ok is True
    assert "checkpoint:" in output
    store = session_checkpoint_provider.get_checkpoint_store(db_path.parent)
    assert isinstance(store, CheckpointStore)
    loaded = session_checkpoint_adapter.load(store)
    assert loaded is not None

    payload = loaded["payload"]
    assert payload["session_id"] == "sess-001"
    assert payload["created_at"]
    assert payload["open_tasks"]
    assert payload["open_tasks"][0]["title"] == "roundtrip task"
    assert payload["recent_memory"]
    assert payload["recent_memory"][0] == "roundtrip memory"


def test_repeated_snapshot_name_still_gets_its_own_checkpoint(snap_env, monkeypatch):
    # Regression: source_ref used to be derived from the user-chosen
    # snapshot_name, which is free-text and can repeat. A second create with
    # the same name raised CheckpointConflict inside checkpoint_after_create,
    # which is fail-soft and swallowed it silently -- the carrier silently
    # stopped tracking new snapshots under a reused name. source_ref is now
    # derived from session_snapshots.id (unique per row), so two snapshots
    # sharing a name each get their own checkpoint.
    monkeypatch.delenv(session_checkpoint_provider.ROLLBACK_ENV_VAR, raising=False)
    handler, base_path, db_path = snap_env
    handler = SnapshotHandler(base_path)

    ok1, output1 = handler.handle("create", ["dup-name"])
    ok2, output2 = handler.handle("create", ["dup-name"])

    assert ok1 is True and ok2 is True
    assert "checkpoint:" in output1
    assert "checkpoint:" in output2

    store = session_checkpoint_provider.get_checkpoint_store(db_path.parent)
    rows = session_checkpoint_adapter.list_checkpoints(store, limit=20)
    assert len(rows) == 2
    assert len({row["id"] for row in rows}) == 2


def test_snapshot_create_rollback_keeps_legacy_output_and_no_carrier(
    snap_env, monkeypatch
):
    monkeypatch.setenv(session_checkpoint_provider.ROLLBACK_ENV_VAR, "0")
    handler, _, db_path = snap_env

    ok, output = handler.handle("create", ["rollback-test"])

    assert ok is True
    assert output.startswith("[OK] Snapshot 'rollback-test' erstellt\n")
    assert "checkpoint:" not in output
    assert output.count("\n") == 3
    assert not session_checkpoint_provider.checkpoint_store_path(db_path.parent).exists()
