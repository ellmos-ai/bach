# SPDX-License-Identifier: MIT
"""Explicit BACH translation of the accepted shared Ocean dbsync adapter.

This source seam does not enable startup/exit sync or migrate legacy state.
All paths, application schema/version and clock belong to the caller. The
shared module owns backup, validation, markers and retention; this file only
verifies its source and translates its result to BACH's bool/text contract.
"""

from __future__ import annotations

import hashlib
import stat
import sys
import types
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

OCEAN_COMMIT = "7127a0f5beea7d3784121c89ca69a118af5ca32b"
OCEAN_ADAPTER_SHA256 = "e0b46347849035d58d0464c3c0554a4d9594033a8617eeb7aaa34b290b0266a7"
OPERATIONS = frozenset({"backup", "status", "enable", "disable", "cleanup", "init"})


class SharedAdapterRefusal(ValueError):
    """A non-sensitive stable refusal code; no native fallback is attempted."""


@dataclass(frozen=True)
class SharedDBSyncConfig:
    database: Path
    transit: Path
    state: Path
    marker: Path
    heartbeat: Path
    node_id: str
    namespace: str
    required_schema: Mapping[str, tuple[str, ...]]
    user_version: int


def _source_path(root: Path) -> Path:
    root = Path(root)
    if not root.is_absolute() or ".." in root.parts:
        raise SharedAdapterRefusal("absolute-ocean-root-required")
    path = root / "tools" / "dbsync_adapter.py"
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            raise SharedAdapterRefusal("ocean-adapter-source-missing") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SharedAdapterRefusal("linked-ocean-source-refused")
    if not path.is_file():
        raise SharedAdapterRefusal("ocean-adapter-source-missing")
    return path


class SharedDBSyncAdapter:
    """An explicitly selected source adapter, with dry-run as the API default.

    The caller must hold an exclusive writer claim and provide a quiescent DB.
    No HOME, environment, installed-module or application-schema defaults are
    consulted. A broken shared contract never invokes native ProSync.
    """

    def __init__(self, config: SharedDBSyncConfig, *, ocean_root: Path,
                 carrier_root: Path, clock: Callable[[], datetime]):
        self.config = config
        self.ocean_root = ocean_root
        self.carrier_root = carrier_root
        self.clock = clock

    def _adapter(self):
        if self.config.namespace != "bach":
            raise SharedAdapterRefusal("bach-namespace-required")
        path = _source_path(self.ocean_root)
        content = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(content).hexdigest() != OCEAN_ADAPTER_SHA256:
            raise SharedAdapterRefusal("ocean-adapter-pin-mismatch")
        name = f"_bach_shared_dbsync_{uuid.uuid4().hex}"
        module = types.ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        try:
            exec(compile(content, str(path), "exec"), module.__dict__)  # noqa: S102 - exact verified bytes only
        finally:
            del sys.modules[name]
        c = self.config
        config = module.AdapterConfig(
            database=c.database, transit=c.transit, state=c.state,
            marker=c.marker, heartbeat=c.heartbeat, node_id=c.node_id,
            namespace=c.namespace, required_schema=c.required_schema,
            user_version=c.user_version,
        )
        return module.DBSyncAdapter(config, carrier_root=self.carrier_root,
                                    clock=self.clock)

    def handle(self, operation: str, *, dry_run: bool = True,
               scope: str | None = None, keep_days: int = 7,
               keep_per_node: int = 10):
        """Return the shared OperationResult without hiding partial failures."""
        # Failure during source/config validation is a refusal, rather than a
        # successful fallback. The handler converts the stable exception code.
        return self._adapter().handle(operation, dry_run=dry_run, scope=scope,
                                      keep_days=keep_days,
                                      keep_per_node=keep_per_node)

    def handler_result(self, operation: str, *, dry_run: bool = True,
                       scope: str | None = None) -> tuple[bool, str]:
        """Translate exactly once; outcome/reason stay visible in BACH text."""
        try:
            result = self.handle(operation, dry_run=dry_run, scope=scope)
        except (SharedAdapterRefusal, ValueError) as error:
            # The shared AdapterRefusal is ValueError and contains stable codes.
            return False, f"Shared dbsync refused: {error}"
        except Exception as error:  # noqa: BLE001 - stable error class; never native fallback
            return False, f"Shared dbsync error: {type(error).__name__}"
        return result.ok, f"Shared dbsync {result.outcome} [{result.code}]: {result.message}"
