# SPDX-License-Identifier: MIT
"""Adapter-Blueprint: Failure-Trails in BACH-Komponenten einhängen.

Dieser Adapter ist bewusst dünn gehalten (Ocean shadow,
runtime_authority=false). Er erzeugt einen ``FailureTrailStore`` aus dem
BACH-Datenverzeichnis und bietet zwei Anknüpfungspunkte:

1. ``get_store()`` – direkter Zugriff für Scheduler/Subagenten.
2. ``annotate_hook_decision()`` – Hinweis an den Memory-Hook, ob ein
   Werkzeugpfad gerade als blockiert gilt, ohne die Hook-Logik selbst zu
   verändern.

Falls ``session_checkpoint`` / ``memoryhooker`` später eine native
Failure-Trail-Tabelle mitbringen, kann dieser Adapter als Rückweg dienen
(BACH_USE_EXTERNAL_FAILURE_TRAILS).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .working_memory import FailureTrailStore

log = logging.getLogger(__name__)

ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_FAILURE_TRAILS"
_OFF_VALUES = {"0", "false", "no", "off"}


def _rollback_forced() -> bool:
    return os.environ.get(ROLLBACK_ENV_VAR, "").strip().lower() in _OFF_VALUES


def _data_dir() -> Path:
    """BACH-Datenverzeichnis (heimverzeichnis-basiert, wie bach_paths.py)."""
    try:
        from .bach_paths import BACH_DIR

        return Path(BACH_DIR)
    except Exception:
        return Path.home() / ".bach"


def get_store(
    db_path: Path | str | None = None,
    *,
    max_retries: int = 5,
    base_backoff_seconds: int = 60,
    max_backoff_seconds: int = 3600,
) -> "FailureTrailStore | None":
    """Gibt den internen Failure-Trail-Store zurück.

    Bei ``BACH_USE_EXTERNAL_FAILURE_TRAILS=1/true/yes/on`` oder bei
    einem externen Carrier-Modul würde hier später ein externer Store
    geladen werden. Aktuell ist nur der interne Pfad implementiert.
    """
    if _rollback_forced():
        log.debug("failure_trails: internal store forced by %s", ROLLBACK_ENV_VAR)

    if db_path is None:
        from .bach_paths import BACH_DB

        db_path = Path(BACH_DB)

    from .working_memory import FailureTrailStore

    return FailureTrailStore(
        db_path=db_path,
        max_retries=max_retries,
        base_backoff_seconds=base_backoff_seconds,
        max_backoff_seconds=max_backoff_seconds,
    )


def annotate_hook_decision(
    tool_path: str,
    context: dict | None = None,
) -> dict:
    """Liefert einen dekorativen Hinweis für Memory-Hook/Scheduler.

    Rückgabe-Shape ist bewusst minimal, damit Caller entscheiden können,
    ob sie ihn beachten:

    .. code-block:: python

        {
            "tool_path": "bach/filesystem/read",
            "blocked": True,
            "retry_count": 3,
            "backoff_seconds_remaining": 117,
        }
    """
    store = get_store()
    if store is None:
        return {"tool_path": tool_path, "blocked": False, "reason": "store unavailable"}

    trails = store.list_trails(tool_path)
    if not trails:
        return {"tool_path": tool_path, "blocked": False}

    newest = trails[0]
    now = __import__("datetime").datetime.now()
    remaining = int((newest.backoff_until - now).total_seconds())
    blocked = store.is_blocked(tool_path, context)
    return {
        "tool_path": tool_path,
        "blocked": blocked,
        "retry_count": newest.retry_count,
        "backoff_seconds_remaining": max(0, remaining),
    }