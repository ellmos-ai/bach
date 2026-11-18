# BACH Adapter: worker_queue_preflight
# SPDX-License-Identifier: MIT
"""Read-only queue observations: change hints never authorize model or task work."""
from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .worker_lease_binding import WorkerLeaseBinding
from .worker_queue_status import REJECTIONS


class QueueChangeObserver:
    """Coalesce cross-process commits, with an independent periodic fallback.

    PRAGMA data_version is compared only on the same persistent read-only
    connection. A new connection/authority gets a new epoch. No transaction is
    held across a preflight or a wait; hints are not semantic TaskCreated events.
    """

    def __init__(self, client_factory, *, clock=time.monotonic,
                 probe_seconds=.5, minimum_recheck_seconds=2.):
        if (not callable(client_factory) or not callable(clock)
                or not all(isinstance(v, (float, int)) and math.isfinite(v) and v > 0
                           for v in (probe_seconds, minimum_recheck_seconds))):
            raise ValueError("Invalid queue observer")
        self._factory = client_factory
        self._clock = clock
        self._probe = float(probe_seconds)
        self._minimum = float(minimum_recheck_seconds)
        self._connection = None
        self._last_available = False
        self._authority = None
        self._epoch = 0
        self._last_wake = float("-inf")
        self.last_reason = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        connection, self._connection = self._connection, None
        self._last_available = False
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass

    def _registry_revision(self):
        from .worker_repo_registry import registry_path
        try:
            info = registry_path().lstat()
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        except OSError:
            return None

    def revision(self):
        registry = self._registry_revision()
        resolved = False
        try:
            client = self._factory()  # Re-resolve authority; no projection fallback.
            path = client._local_observation_path()
            if path is None:
                authority = (client.mode, client.lead_url, None)
            else:
                path = Path(path)
                info = path.stat()
                authority = (client.mode, str(path), info.st_dev, info.st_ino)
            resolved = True
            if authority != self._authority:
                self.close()
                self._authority = authority
                self._epoch += 1
            if path is None:
                return (self._epoch, None, registry)
            if self._connection is None:
                self._connection = sqlite3.connect(
                    path.absolute().as_uri() + "?mode=ro", uri=True,
                    timeout=.2, isolation_level=None)
                self._connection.execute("PRAGMA query_only=ON")
            version = self._connection.execute("PRAGMA data_version").fetchone()[0]
            if not self._last_available:
                self._epoch += 1
            self._last_available = True
            return (self._epoch, version, registry)
        except Exception:
            # Connection loss produces one change hint, then the periodic path.
            # A future successful resolver/read may reconnect with a new epoch.
            was_available = self._last_available
            self.close()
            if not resolved and self._authority is not None:
                self._authority = None
                self._epoch += 1
            elif was_available:
                self._epoch += 1
            return (self._epoch, None, registry)

    def wait(self, stop_event, observed_revision, *, timeout=10.):
        """Return the stop flag, matching Event.wait; a hint only ends this wait."""
        deadline = self._clock() + timeout
        while not stop_event.is_set():
            now = self._clock()
            if now >= deadline:
                self.last_reason = "periodic"
                self._last_wake = now
                return False
            if (self.revision() != observed_revision
                    and now - self._last_wake >= self._minimum):
                self.last_reason = "change_hint"
                self._last_wake = now
                return False
            if stop_event.wait(min(self._probe, max(0., deadline - now))):
                return True
        return True


@dataclass(frozen=True)
class QueuePreflight:
    eligible: bool = False
    scan_complete: bool = False
    candidate_count: int = 0
    task_id: int | None = None
    rejected_counts: dict[str, int] = field(default_factory=dict)
    state: str = "unavailable"

    @property
    def activity(self):
        if self.state == "unavailable":
            return "Queue-Vorprüfung nicht bestätigt; kein Modellstart, erneute Prüfung folgt"
        reasons = ", ".join(f"{reason}: {count}" for reason, count in self.rejected_counts.items())
        return (f"Queue-Vorprüfung: keine passende freie Aufgabe ({self.candidate_count} Kandidaten)"
                + ("; " + reasons if reasons else ""))


def preflight_worker_queue(client, slot, *, worker_id, host, generation, is_current,
                           stop_event, deferred_versions=None, review_route=None,
                           review_requested_model=None):
    """Use the native selector and read checks without acquiring or minting grants.

    This is prospective eligibility. Final Acquire, source preparation, current
    profile, model-resource admission and every dispatch guard remain mandatory.
    An incomplete/unavailable scan never authorizes a pre-queue model warmup.
    """
    counts = {}
    candidates = 0
    deferred = dict(deferred_versions or {})
    profile = WorkerLeaseBinding._selection_profile_snapshot(slot)
    seen = set()

    def current():
        if not is_current() or stop_event.is_set():
            raise RuntimeError("Worker no longer current")

    def reject(reason):
        if reason not in REJECTIONS:
            raise ValueError("Unknown preflight reason")
        counts[reason] = counts.get(reason, 0) + 1

    def eligible(task, *, review=False):
        nonlocal candidates
        current()
        if (not isinstance(task, dict) or type(task.get("id")) is not int
                or task["id"] <= 0 or not isinstance(task.get("task_version"), str)
                or task["id"] in seen):
            raise ValueError("Invalid native candidate")
        seen.add(task["id"])
        candidates += 1
        pin = WorkerLeaseBinding._effective_selection_policy_snapshot(client, task, profile)
        reason = ("selection_policy_unavailable" if pin is None else
                  WorkerLeaseBinding._selection_rejection_reason(
                      task, {**slot, "pickup_filter": {"enabled": False}} if review else slot,
                      selection_policy=pin["policy"]))
        if reason is None and deferred.get(task["id"]) == task["task_version"]:
            reason = "deferred_version"
        if reason is None:
            reason = client._preflight_task_readiness(task["id"],
                task_version=task["task_version"], worker_id=worker_id, review=review)
        if reason is None and review:
            try:
                review_match = client._review_eligible(task["id"], worker_id=worker_id, host=host,
                    generation=generation, slot_id=slot["id"], route=review_route,
                    requested_model=review_requested_model, is_current=is_current,
                    stop_event=stop_event)
            except Exception:
                review_match = False  # Same per-review denial behavior as native grant pickup.
            if review_match is not True:
                reason = "ownership"
        current()
        if reason is not None:
            reject(reason)
            return False
        return True

    try:
        if getattr(client, "mode", None) not in {"local", "remote"}:
            raise ValueError("Canonical authority unavailable")
        for reviews in (False, True):
            if reviews and (client.mode != "local" or not isinstance(review_route, dict)
                    or not isinstance(review_requested_model, str) or not review_requested_model):
                continue
            offset = 0
            while True:
                current()
                page = (client._review_candidates(limit=100, offset=offset) if reviews else
                        client.task_candidates(limit=100, offset=offset, _read_only=True))
                if (not isinstance(page, dict) or not isinstance(page.get("tasks"), list)
                        or len(page["tasks"]) > 100 or type(page.get("has_more")) is not bool
                        or page.get("offset") != offset):
                    raise ValueError("Invalid native candidate page")
                for task in page["tasks"]:
                    if eligible(task, review=reviews):
                        return QueuePreflight(True, False, candidates, task["id"],
                                              dict(counts), "eligible")
                if not page["has_more"]:
                    break
                if offset >= 100_000:
                    raise ValueError("Native candidate page made no progress")
                offset += 100
        current()
        return QueuePreflight(False, True, candidates, None, dict(counts), "waiting")
    except Exception:
        return QueuePreflight(False, False, candidates, None, dict(counts), "unavailable")
