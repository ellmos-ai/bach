"""Own a heartbeat thread for a real worker block, including blocking calls.

A lost lease stops future mutations. The provider call still has to reach
its actual terminal state before the worker can report that it has stopped.
"""
from __future__ import annotations

import math
import threading
import time
from threading import Thread as HeartbeatThread

from hub._services.task_lease_client import LeaseProtocolError


class WorkerLeaseSupervisor:
    def __init__(self, binding, *, poll_interval=15.0, renew_interval=300.0):
        if any(not math.isfinite(value) or value <= 0 for value in (poll_interval, renew_interval)):
            raise ValueError("Heartbeat intervals must be positive and finite")
        self.binding = binding
        self.poll_interval = poll_interval
        self.renew_interval = renew_interval
        self._finished = threading.Event()
        self._failed = threading.Event()
        self._failure = None
        self._thread = None

    @property
    def failure(self):
        return self._failure

    @property
    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    def wait_for_failure(self, timeout):
        return self._failed.wait(timeout)

    def _monitor(self):
        last_renew = time.monotonic()
        while not self._finished.is_set():
            if self.binding.stop_requested or self.binding.closed:
                return
            try:
                renewed = self.binding.heartbeat(
                    renew_due=time.monotonic() - last_renew >= self.renew_interval)
                if renewed:
                    last_renew = time.monotonic()
            except BaseException:
                # Stop/close may race this check. Neither is a lost ACK.
                if self.binding.stop_requested or self.binding.closed:
                    return
                self.binding.invalidate()
                self._failure = LeaseProtocolError("Lease-Bestätigung oder Sicherheitsfrist fehlt")
                self._failed.set()
                return
            if self._finished.wait(self.poll_interval):
                return

    def __enter__(self):
        self.binding.assert_active()
        if self._thread is not None:
            raise RuntimeError("Heartbeat supervisor cannot be reused")
        self._thread = HeartbeatThread(target=self._monitor, daemon=True,
                                       name=f"worker-task-heartbeat-{self.binding.task_id}")
        self._thread.start()
        return self

    def close(self):
        self._finished.set()
        if self._thread is not None:
            # An already sent Renew must reach its real terminal state. Do not
            # report a clean stop while this owned mutation is still in flight.
            self._thread.join()

    def __exit__(self, *_):
        self.close()

    async def run(self, provider_factory):
        with self:
            result = await provider_factory()
        if self.failure is not None:
            raise self.failure
        if not self.binding.closed and not self.binding.stop_requested:
            self.binding.assert_active()
        return result
