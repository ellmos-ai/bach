#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Provider seam for the sqlite-transit-sync extraction (MODULRUECKTRANSFER Stufe 7).

BACH's native ProSync (``hub/db_sync.py``: whole-DB ``.bachdb`` snapshots
merged by column timestamps) keeps working WITHOUT this module. The external
``sqlite-transit-sync`` package contributes verified, state-gated snapshots
with deterministic per-node delta merges over the same transit directory:

  * ``DBSyncManager.sync_on_start``  - pull pending verified snapshots
  * ``DBSyncManager.sync_on_exit``   - push one verified snapshot
  * ``DBSyncManager.sync``           - pull + push

The engine never shares the legacy ``.bachdb`` namespace: snapshots live in
the ``bach`` namespace of the transit directory and the merge state file is
kept OUTSIDE the transit directory (a hard ``SyncConfig`` invariant).

Rollback rule (MODULRUECKTRANSFER-PLAN section 4, rule 1): setting the
environment variable ``BACH_USE_EXTERNAL_TRANSITSYNC=0`` (also false/no/off)
forces BACH back to the legacy ProSync path immediately, even when the
external module is importable.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

EXTERNAL_MODULE = "sqlite_transit_sync"
EXTERNAL_DIST = "sqlite-transit-sync"
ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_TRANSITSYNC"

# Ein Namespace fuer den bach.db-Lebenszyklus; Legacy-.bachdb-Dateien und
# TransitSync-Snapshots stoeren sich nicht (getrennte Dateinamen/Manifeste).
DEFAULT_NAMESPACE = "bach"
STATE_DIR_NAME = "transit_sync_state"
STATE_FILE_NAME = "state.json"

CONTRACT_SYMBOLS = ("SyncConfig", "TransitSync", "MergeReport", "Snapshot")

_ROLLBACK_OFF_VALUES = {"0", "false", "no", "off"}


class TransitSyncContractError(RuntimeError):
    """Raised when the installed module violates the Stufe-7 contract."""


@dataclass(frozen=True)
class TransitSyncProvider:
    name: str
    external: bool
    module: Optional[str]
    reason: str


def _rollback_forced() -> bool:
    return os.environ.get(ROLLBACK_ENV_VAR, "").strip().lower() in _ROLLBACK_OFF_VALUES


def probe_transit_sync_provider() -> TransitSyncProvider:
    """Describe the available provider without importing it (find_spec only)."""
    if _rollback_forced():
        return TransitSyncProvider(
            name="bach-legacy",
            external=False,
            module=None,
            reason=f"rollback switch {ROLLBACK_ENV_VAR}=0 forces the internal ProSync path",
        )
    if importlib.util.find_spec(EXTERNAL_MODULE) is not None:
        return TransitSyncProvider(
            name="ellmos sqlite-transit-sync",
            external=True,
            module=EXTERNAL_MODULE,
            reason="independent module is importable",
        )
    return TransitSyncProvider(
        name="bach-legacy",
        external=False,
        module=None,
        reason=f"{EXTERNAL_DIST} is not installed in this environment",
    )


def load_external_transit_sync() -> Any:
    """Import the independent module explicitly (no silent fallback)."""
    return importlib.import_module(EXTERNAL_MODULE)


def _validate_contract(module: Any) -> None:
    missing = [symbol for symbol in CONTRACT_SYMBOLS if not hasattr(module, symbol)]
    if missing:
        raise TransitSyncContractError(
            f"{EXTERNAL_DIST} contract violation: missing {', '.join(missing)} "
            f"(required by MODULRUECKTRANSFER Stufe 7)"
        )


def create_external_engine(
    db_path: Path,
    transit_dir: Path,
    local_bach_dir: Path,
    node_id: Optional[str] = None,
    namespace: str = DEFAULT_NAMESPACE,
) -> "ExternalTransitSyncEngine":
    """Build the BACH-facing sync engine from the external module.

    Fails closed with :class:`TransitSyncContractError` if the installed
    module does not expose the contract symbols (SyncConfig, TransitSync,
    MergeReport, Snapshot) required by MODULRUECKTRANSFER Stufe 7.
    """
    module = load_external_transit_sync()
    _validate_contract(module)
    kwargs = {
        "database": Path(db_path),
        "transit": Path(transit_dir),
        "state": Path(local_bach_dir) / STATE_DIR_NAME / STATE_FILE_NAME,
        "namespace": namespace,
    }
    if node_id:  # sonst Modul-Default: socket.gethostname()
        kwargs["node_id"] = node_id
    config = module.SyncConfig(**kwargs)
    return ExternalTransitSyncEngine(module, config)


def create_external_engine_if_active(
    db_path: Path,
    transit_dir: Path,
    local_bach_dir: Path,
    node_id: Optional[str] = None,
) -> Optional["ExternalTransitSyncEngine"]:
    """Factory used by DBSyncManager: None = legacy ProSync path stays active.

    Returns None (not an error) when the rollback switch is set or the module
    is not installed. Raises :class:`TransitSyncContractError` when the module
    IS importable but violates the contract, so misconfiguration surfaces
    instead of silently degrading.
    """
    provider = probe_transit_sync_provider()
    if not provider.external:
        return None
    return create_external_engine(
        db_path=db_path,
        transit_dir=transit_dir,
        local_bach_dir=local_bach_dir,
        node_id=node_id,
    )


class ExternalTransitSyncEngine:
    """Thin adapter mapping BACH ProSync lifecycle calls onto TransitSync.

    Only verified snapshots are merged (``pull`` verifies before merging);
    repeated pulls of an already-merged snapshot are state-gated no-ops.
    Merge semantics: timestamp LWW over (updated_at, modified_at, created_at),
    ``secrets`` excluded by default - parity with the legacy ProSync merge.
    Deletions do not propagate (same limitation as the legacy merge).
    """

    def __init__(self, module: Any, config: Any):
        self._module = module
        self._config = config
        self._sync = module.TransitSync(config)

    @property
    def node_id(self) -> str:
        return self._config.node_id

    def pending(self) -> list:
        """Names of pending foreign snapshots (verified on pull)."""
        return [snapshot.path.name for snapshot in self._sync.pending()]

    def push(self) -> str:
        """Publish one verified snapshot of the local DB. Returns its name."""
        snapshot = self._sync.push()
        return snapshot.path.name

    def pull(self) -> Tuple[int, list]:
        """Merge every pending verified snapshot in deterministic order.

        Returns (changed_rows, snapshot_names) where changed_rows counts
        inserted + updated rows across all merge reports.
        """
        reports = self._sync.pull()
        changed = sum(report.inserted + report.updated for report in reports)
        names = [report.snapshot for report in reports]
        return changed, names

    def sync(self) -> Tuple[bool, str]:
        """Full cycle: pull pending snapshots, then push the local state."""
        changed, names = self.pull()
        snapshot_name = self.push()
        if names:
            message = (
                f"TransitSync: {changed} Zeilen aus {len(names)} Snapshot(s) "
                f"gemergt, Push: {snapshot_name}"
            )
        else:
            message = f"TransitSync: nichts ausstehend, Push: {snapshot_name}"
        return True, message

    def cleanup(self, keep_days: int = 7, keep_per_node: int = 10,
                dry_run: bool = True) -> dict:
        """Retention passthrough. Dry-run by default (module invariant)."""
        return self._sync.cleanup(
            keep_days=keep_days, keep_per_node=keep_per_node, dry_run=dry_run
        )

    def status(self) -> dict:
        return {
            "provider": "ellmos sqlite-transit-sync",
            "node_id": self._config.node_id,
            "namespace": self._config.namespace,
            "pending": self.pending(),
        }
