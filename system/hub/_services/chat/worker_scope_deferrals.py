"""Temporary preparation skips; never permission to replay model or tool work."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable

from .worker_queue_status import project_queue_status


@dataclass
class ScopePreparationDeferrals:
    """Retry preparation only after all fresh candidates were considered.

    Expiry alone never makes a task selectable: short cooldowns otherwise let
    early failing tasks starve later candidates. Ordinary version deferrals
    remain owned by the controller and always take precedence.
    """
    clock: Callable[[], float] = time.monotonic
    retry_seconds: float = 30.0
    _entries: dict[int, tuple[str, float]] = field(default_factory=dict, init=False)

    def defer(self, task_id: int, version: str, *, tool_dispatch_count) -> bool:
        if type(tool_dispatch_count) is not int or tool_dispatch_count != 0:
            return False
        if type(task_id) is not int or task_id <= 0 or not isinstance(version, str) or not version:
            return False
        now = self.clock()
        if not math.isfinite(now) or not math.isfinite(self.retry_seconds) or self.retry_seconds <= 0:
            return False
        self._entries[task_id] = (version, now + self.retry_seconds)
        return True

    def combined(self, ordinary: dict[int, str]) -> dict[int, str]:
        if not self._entries:
            return ordinary
        return {**{tid: value[0] for tid, value in self._entries.items()}, **ordinary}

    def resolved(self, task_id: int) -> None:
        self._entries.pop(task_id, None)

    def after_exhausted_scan(self, record) -> tuple[int, ...]:
        checked = project_queue_status(record)
        if checked is None or checked['state'] != 'waiting' or checked['scan_complete'] is not True:
            return ()
        now = self.clock()
        if not math.isfinite(now):
            return ()
        expired = tuple(tid for tid, (_, deadline) in self._entries.items() if deadline <= now)
        for tid in expired:
            self._entries.pop(tid)
        return expired
