"""Consumer for order messages ("Auftragsnachrichten") in the BACH `messages` table.

Since wave 1 of the BACH-GUI module cut (decision D-20260830-002) the domain
logic lives in the neutral module ``assistant-core``; this file is the
compatibility seam that keeps BACH's import paths and signatures unchanged:

    from hub._services.chat.message_worker import start_worker

BACH still injects its own database path (``chat_runtime.RUNTIME_BACH_DB``)
and its own ``ChatRuntime.process`` callback -- the module owns no data and
no runtime. Reply semantics are unchanged: an *inbox* row whose ``parent_id``
points at the order is the "answered" marker (plan items 1.1.4/1.2.4/1.2.5).
"""
from __future__ import annotations

import threading
from typing import Iterable

from assistant_core.messages import (  # noqa: F401 - re-exported for BACH callers and tests
    DEFAULT_RECIPIENTS,
    POLL_SECONDS,
    ProcessFn,
    file_reply,
    pending_orders,
    run_once,
)
from assistant_core.messages import start_worker as _start_worker

__all__ = ["DEFAULT_RECIPIENTS", "POLL_SECONDS", "ProcessFn", "file_reply", "pending_orders", "run_once", "start_worker"]


def start_worker(
    db_path: str,
    process: ProcessFn,
    recipients: Iterable[str] = DEFAULT_RECIPIENTS,
    interval: float = POLL_SECONDS,
    stop: threading.Event | None = None,
) -> threading.Thread:
    """Poll ``db_path`` every ``interval`` seconds in a daemon thread (BACH thread name kept)."""
    return _start_worker(db_path, process, recipients, interval, stop, name="bach-message-worker")
