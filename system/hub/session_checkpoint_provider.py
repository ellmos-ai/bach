# SPDX-License-Identifier: MIT
"""Fail-soft provider seam for the neutral session-checkpoint carrier."""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_checkpoint import CheckpointStore


log = logging.getLogger(__name__)

ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_SESSION_CHECKPOINT"
_OFF_VALUES = {"0", "false", "no", "off"}
_MODULE_NAME = "session_checkpoint"


def _rollback_forced() -> bool:
    return os.environ.get(ROLLBACK_ENV_VAR, "").strip().lower() in _OFF_VALUES


def checkpoint_store_path(data_dir: Path) -> Path:
    return data_dir / "session_checkpoints.db"


def get_checkpoint_store(data_dir: Path) -> "CheckpointStore | None":
    """Return the carrier store, or fail closed without raising."""
    if _rollback_forced():
        return None

    try:
        if importlib.util.find_spec(_MODULE_NAME) is None:
            log.warning("session-checkpoint provider unavailable: module is not importable")
            return None
        from session_checkpoint import CheckpointStore

        return CheckpointStore(checkpoint_store_path(data_dir))
    except Exception as exc:
        log.warning("session-checkpoint provider unavailable (fail-closed): %s", exc)
        return None


def checkpoint_after_create(
    bach_db_path: Path,
    data_dir: Path,
    *,
    name: str | None,
    source_ref: str | None = None,
) -> dict:
    """Create one additive carrier checkpoint after a legacy snapshot commit."""
    if _rollback_forced():
        return {
            "enabled": False,
            "reason": f"rollback forced by {ROLLBACK_ENV_VAR}",
        }

    store = get_checkpoint_store(data_dir)
    if store is None:
        try:
            module_available = importlib.util.find_spec(_MODULE_NAME) is not None
        except Exception:
            module_available = False
        if not module_available:
            return {
                "enabled": False,
                "reason": f"{_MODULE_NAME} is not installed in this environment",
            }
        return {"enabled": True, "error": "checkpoint store unavailable"}

    try:
        from . import session_checkpoint_adapter

        checkpoint = session_checkpoint_adapter.create(
            store,
            bach_db_path,
            name=name,
            source_ref=source_ref,
        )
    except Exception as exc:
        log.warning("session-checkpoint carrier create failed (fail-soft): %s", exc)
        return {"enabled": True, "error": str(exc)}
    return {"enabled": True, "checkpoint": checkpoint}
