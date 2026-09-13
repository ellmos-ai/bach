"""Consumer for order messages ("Auftragsnachrichten") in the BACH `messages` table.

The domain logic originally lived in the neutral module ``assistant-core``
(Welle 1, decision D-20260830-002). This file is the compatibility seam that
keeps BACH's import paths and signatures unchanged:

    from hub._services.chat.message_worker import start_worker

If ``assistant-core`` is installed, BACH re-exports its implementation.
Otherwise it falls back to the local ``_messages_compat`` module so that
BACH remains bootable even when the editable ``assistant-core`` checkout is
missing (e.g. on a fresh host or after the upstream repo was moved).

BACH still injects its own database path and its own ``process`` callback --
the module owns no data and no runtime. Reply semantics are unchanged: an
*inbox* row whose ``parent_id`` points at the order is the "answered" marker.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable

try:  # Wave 2/3: use upstream assistant-core when available
    from assistant_core.messages import (  # noqa: F401 - re-exported for callers
        DEFAULT_RECIPIENTS,
        POLL_SECONDS,
        ProcessFn,
        file_reply,
        pending_orders,
        run_once,
    )
    from assistant_core.messages import start_worker as _start_worker

    def start_worker(
        db_path: str,
        process: ProcessFn,
        recipients: Iterable[str] = DEFAULT_RECIPIENTS,
        interval: float = POLL_SECONDS,
        stop: threading.Event | None = None,
    ) -> threading.Thread:
        """Poll ``db_path`` every ``interval`` seconds in a daemon thread."""
        return _start_worker(
            db_path, process, recipients, interval, stop, name="bach-message-worker"
        )

except ImportError:  # pragma: no cover - fallback for missing editable checkout
    from hub._services.chat._messages_compat import (  # noqa: F401
        DEFAULT_RECIPIENTS,
        POLL_SECONDS,
        ProcessFn,
        file_reply,
        pending_orders,
        run_once,
        start_worker,
    )

__all__ = [
    "DEFAULT_RECIPIENTS",
    "POLL_SECONDS",
    "ProcessFn",
    "file_reply",
    "pending_orders",
    "run_once",
    "start_worker",
]
