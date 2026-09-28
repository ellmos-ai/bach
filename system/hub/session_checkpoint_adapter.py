# SPDX-License-Identifier: MIT
"""K9 adapter: BACH SnapshotHandler -> the neutral session-checkpoint carrier.

Contract: open-ocean/architecture/session-checkpoint-capability.v1.json
(namespace "bach", six-field payload: session_id, open_tasks, recent_memory,
active_files, token_usage, created_at; parity "not-accepted" for every
operation -- this module does not change SnapshotHandler's create/load/list/
delete behaviour).

INACTIVE PREPARATION SEAM, like snapshot_payload.py: not imported by
SnapshotHandler. It proves the carrier round-trip (create/get/list/delete)
against BACH's read-only payload collector so the wiring step (a later PR,
guarded by a rollback env var) has a tested adapter to call.

The carrier (``session_checkpoint.CheckpointStore``) never opens the BACH
database itself -- this module reads BACH state via
``snapshot_payload.collect_snapshot_payload`` (read-only, mode=ro) and only
ever writes to the carrier's own dedicated SQLite file.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from session_checkpoint import Checkpoint, CheckpointStore

from .snapshot_payload import collect_snapshot_payload

NAMESPACE = "bach"


def _adapter_payload(bach_db_path: Union[str, Path], *, created_at: Optional[str] = None) -> dict:
    """Collect BACH's six-field checkpoint payload, unchanged.

    ``collect_snapshot_payload`` already returns exactly the six fields the
    K9 contract's ``application_adapter.payload_fields`` requires
    (``session_id``, ``open_tasks``, ``recent_memory``, ``active_files``,
    ``token_usage``, ``created_at``); this wrapper exists so callers go
    through the adapter module rather than the collector directly.
    """
    return collect_snapshot_payload(bach_db_path, created_at=created_at)


def _to_legacy_tuple(checkpoint: Checkpoint) -> dict:
    """Translate a carrier Checkpoint to the legacy snapshot-row shape."""
    return {
        "id": checkpoint.id,
        "session_id": checkpoint.session_id,
        "name": checkpoint.name,
        "payload": checkpoint.payload,
        "created_at": checkpoint.created_at,
    }


def create(
    store: CheckpointStore,
    bach_db_path: Union[str, Path],
    *,
    name: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> dict:
    """Collect BACH state read-only and create one checkpoint under namespace 'bach'."""
    payload = _adapter_payload(bach_db_path)
    checkpoint = store.create(
        namespace=NAMESPACE,
        session_id=payload["session_id"],
        payload=payload,
        name=name,
        kind="manual",
        source_ref=source_ref,
    )
    return _to_legacy_tuple(checkpoint)


def load(store: CheckpointStore, checkpoint_id: Optional[int] = None) -> Optional[dict]:
    """Load one checkpoint (by id, or the newest) and format its payload.

    Display-only, like SnapshotHandler's display mode: never restores state.
    Returns None when no checkpoint exists (empty namespace).
    """
    if checkpoint_id is None:
        rows = store.list(namespace=NAMESPACE, limit=1)
        if not rows:
            return None
        checkpoint = rows[0]
    else:
        checkpoint = store.get(checkpoint_id, namespace=NAMESPACE)
    return _to_legacy_tuple(checkpoint)


def list_checkpoints(store: CheckpointStore, *, limit: int = 20) -> list:
    """List checkpoint metadata (no payloads) newest-first."""
    return [
        cp.as_dict(include_payload=False)
        for cp in store.list(namespace=NAMESPACE, limit=limit)
    ]


def delete(store: CheckpointStore, checkpoint_id: int, *, dry_run: bool = True) -> dict:
    """Delete a checkpoint (dry-run by default, matching the carrier's default)."""
    checkpoint = store.delete(checkpoint_id, namespace=NAMESPACE, dry_run=dry_run)
    return _to_legacy_tuple(checkpoint)
