# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Round-trip tests for the K9 session-checkpoint adapter (hub/session_checkpoint_adapter.py).

Contract: open-ocean/architecture/session-checkpoint-capability.v1.json.
Uses only temporary SQLite files -- a temp BACH-like DB for the source payload
and a temp carrier store for the checkpoint. Never touches the canonical live
BACH database or a shared carrier file.
"""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
TESTS_ROOT = Path(__file__).parent
for _p in (SYSTEM_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from session_checkpoint import CheckpointStore

from hub import session_checkpoint_adapter as adapter
from test_snapshot_payload import _make_db  # reuse the shared fixture DB builder


@pytest.fixture
def bach_db(tmp_path):
    db = tmp_path / "bach.db"
    _make_db(db, session="sess-s5")
    return db


@pytest.fixture
def store(tmp_path):
    return CheckpointStore(tmp_path / "checkpoints.db")


def test_create_load_roundtrip(store, bach_db):
    created = adapter.create(store, bach_db, name="s5-roundtrip")

    assert created["session_id"] == "sess-s5"
    assert created["payload"]["session_id"] == "sess-s5"
    assert len(created["payload"]["open_tasks"]) == 10  # capped, mirrors SnapshotHandler
    assert len(created["payload"]["recent_memory"]) == 5
    assert set(created["payload"]) == {
        "session_id", "open_tasks", "recent_memory",
        "active_files", "token_usage", "created_at",
    }
    assert len(created["payload"]["active_files"]) == 10  # capped, mirrors SnapshotHandler
    assert created["payload"]["token_usage"] == 500

    loaded = adapter.load(store, created["id"])
    assert loaded == created

    newest = adapter.load(store)  # no id -> newest
    assert newest == created


def test_list_omits_payload(store, bach_db):
    adapter.create(store, bach_db)
    rows = adapter.list_checkpoints(store)
    assert len(rows) == 1
    assert "payload" not in rows[0]
    assert rows[0]["namespace"] == "bach"


def test_delete_dry_run_then_real(store, bach_db):
    created = adapter.create(store, bach_db)

    dry = adapter.delete(store, created["id"], dry_run=True)
    assert dry["id"] == created["id"]
    assert adapter.list_checkpoints(store)  # still there

    adapter.delete(store, created["id"], dry_run=False)
    assert adapter.list_checkpoints(store) == []


def test_load_empty_namespace_returns_none(store):
    assert adapter.load(store) is None


def test_adapter_import_safe_without_carrier(monkeypatch):
    """Adapter must be importable without session_checkpoint installed (e.g. by HandlerRegistry)."""
    import importlib
    # simulate uninstalled session_checkpoint
    monkeypatch.setitem(sys.modules, "session_checkpoint", None)
    import hub.session_checkpoint_adapter as fresh_adapter
    importlib.reload(fresh_adapter)
    assert hasattr(fresh_adapter, "create")
    assert hasattr(fresh_adapter, "load")
    assert hasattr(fresh_adapter, "list_checkpoints")
    assert hasattr(fresh_adapter, "delete")


def test_checkpoint_after_delete_provider(bach_db):
    from hub import session_checkpoint_provider as prov

    data_dir = bach_db.parent
    res_create = prov.checkpoint_after_create(
        bach_db, data_dir, name="test-prov", source_ref="bach-session_snapshots:42"
    )
    assert res_create.get("enabled") is True

    store = prov.get_checkpoint_store(data_dir)
    assert store is not None
    cps = [cp for cp in store.list(namespace="bach") if cp.source_ref == "bach-session_snapshots:42"]
    assert len(cps) == 1

    # Dry-run delete does not remove the checkpoint
    dry_res = prov.checkpoint_after_delete(data_dir, source_ref="bach-session_snapshots:42", dry_run=True)
    assert dry_res.get("enabled") is True
    assert len([cp for cp in store.list(namespace="bach") if cp.source_ref == "bach-session_snapshots:42"]) == 1

    # Live delete removes the checkpoint
    del_res = prov.checkpoint_after_delete(data_dir, source_ref="bach-session_snapshots:42", dry_run=False)
    assert del_res.get("enabled") is True
    assert len([cp for cp in store.list(namespace="bach") if cp.source_ref == "bach-session_snapshots:42"]) == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
