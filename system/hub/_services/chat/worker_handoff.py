# SPDX-License-Identifier: MIT
"""One explicit context handoff, bound to a worker run and safe model boundary."""
from datetime import datetime, timezone
import threading
import uuid


class WorkerHandoff:
    def __init__(self, worker_id: str, generation: str):
        self.worker_id = worker_id
        self.generation = generation
        self._lock = threading.RLock()
        self._receipt = None
        self._closed = False

    def snapshot(self):
        with self._lock:
            return dict(self._receipt) if self._receipt else None

    @property
    def closed(self):
        with self._lock:
            return self._closed

    def request(self, generation: str):
        with self._lock:
            if self._closed or generation != self.generation:
                raise ValueError("Workerlauf ist nicht mehr aktuell")
            if self._receipt and self._receipt["state"] in {"pending", "running"}:
                raise ValueError("Kontextübergabe ist bereits angefordert")
            self._receipt = {
                "kind": "worker-handoff", "worker_id": self.worker_id,
                "generation": self.generation, "request_id": uuid.uuid4().hex,
                "state": "pending", "requested_at": datetime.now(timezone.utc).isoformat(),
                "confirmed_at": None,
            }
            return dict(self._receipt)

    def consume(self):
        with self._lock:
            if self._closed or not self._receipt or self._receipt["state"] != "pending":
                return None
            self._receipt["state"] = "running"
            return self._receipt["request_id"]

    def finish(self, request_id: str, *, succeeded: bool):
        with self._lock:
            if (self._closed or not self._receipt or self._receipt["request_id"] != request_id
                    or self._receipt["state"] != "running"):
                return False
            self._receipt["state"] = "confirmed" if succeeded else "error"
            if succeeded:
                self._receipt["confirmed_at"] = datetime.now(timezone.utc).isoformat()
            return True

    def cancel(self):
        with self._lock:
            self._closed = True
            if self._receipt and self._receipt["state"] in {"pending", "running"}:
                self._receipt["state"] = "cancelled"
