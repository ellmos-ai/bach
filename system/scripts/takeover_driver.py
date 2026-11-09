#!/usr/bin/env python3
"""Takeover Driver – manages owned leases and heartbeats for ellmos-scheduler.

Provides a minimal implementation of owner/lease-expiry fencing and heartbeat
for a single-owner Mac Studio supervision scenario.

Used by the com.bach.ocean-takeover-local launch agent (KeepAlive=false) to
supervise individual ellmos-scheduler runs started by ellmos-scheduler.

Features:
- Acquire an owner lease on the first run, based on task ownership.
- Periodic heartbeat renewal via TaskLeaseClient to keep the lease alive.
- Fail‑closed semantics – expired or mismatched fences block any further
  lease operations.
- Enforces local fencing rules: a lease is tied to a concrete owner
  (slot/fence) and must be renewed before expiration.

The driver is deliberately simple – it does not implement a full scheduler,
but can be extended by higher‑level orchestration code (e.g. Ocean pipeline
or BACH task plans) as needed.

Usage (example):
    from system.scripts.takeover_driver import TakeoverDriver
    driver = TakeoverDriver(task_id, owner="mac-studio-owner")
    driver.start()  # acquires lease, starts heartbeat loop
    # ... later ...
    driver.stop()
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from hub._services.task_lease_client import TaskLeaseClient
from hub._services.task_lease import LeaseResult

log = logging.getLogger(__name__)

@dataclass
class TakeoverDriverConfig:
    """Configuration for a single‑owner Takeover driver."""
    task_id: int
    owner: str
    # Allow overriding the lead mode for tests – default is local
    lead_mode: str = "isolated"
    heartbeat_interval: float = 30.0  # seconds
    lease_timeout: float = 60.0  # maximum time to wait for a lease


class TakeoverDriver:
    """Single‑owner lease driver with fencing and heartbeat.

    The driver assumes a single, non‑renewable lease per task id (owner).
    It will block any other lease acquisition unless the fence matches.
    """

    def __init__(self, config: TakeoverDriverConfig) -> None:
        self._config = config
        self._client: Optional[TaskLeaseClient] = None
        self._lease: Optional[LeaseResult] = None
        self._running = False
        self._task = None  # asyncio Task for heartbeat loop
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def start(self) -> LeaseResult:
        """Acquire an owner lease and start the heartbeat loop.

        Returns the active lease result. Raises ``RuntimeError`` if the lease
        cannot be acquired within ``lease_timeout``.
        """
        if self._running:
            raise RuntimeError("TakeoverDriver is already running")

        # Build a TaskLeaseClient for the current lead (Mac Studio).
        # In a real deployment this would read the lead configuration from
        # ``hub.rheingold.get_lead_config``.
        from hub.rheingold import get_lead_config

        lead_cfg = get_lead_config()
        self._client = TaskLeaseClient(lead_url=lead_cfg.get("lead_url"), timeout=30)

        try:
            # Acquire a lease for the given task – owner is encoded via
            # the ``by`` parameter (user) and ``fence`` (slot).
            # The ``by`` field is used as the owner identifier; fence is derived
            # from the current slot (here we use a deterministic slot based on
            # task_id to guarantee idempotence).
            slot = self._config.task_id % 1000  # deterministic slot for owner
            lease = self._client.acquire_lease(
                task_id=self._config.task_id,
                by=self._config.owner,
                slot=slot,
                ttl=self._config.heartbeat_interval,
            )
        except Exception as exc:
            raise RuntimeError(
                f"TakeoverDriver could not acquire lease for task {self._config.task_id}: {exc}"
            ) from exc

        self._lease = lease
        log.info(
            "Acquired lease %s for task %s (owner=%s, fence=%s)",
            lease.lease_id,
            self._config.task_id,
            self._config.owner,
            lease.claim_fence,
        )

        self._running = True
        # Start heartbeat task
        self._task = asyncio.create_task(self._heartbeat_loop())
        return lease

    def stop(self) -> None:
        """Release the lease and stop the heartbeat loop.

        Safe to call multiple times.
        """
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                self._task.result(timeout=5)
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._client and self._lease:
            try:
                self._client.release_lease(
                    task_id=self._config.task_id,
                    lease_id=self._lease.lease_id,
                    fence=self._lease.claim_fence,
                )
                log.info(
                    "Released lease %s for task %s",
                    self._lease.lease_id,
                    self._config.task_id,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("Failed to release lease: %s", exc)

        self._lease = None
        self._client = None

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Renew the lease at ``heartbeat_interval`` intervals.

        If renewal fails the process exits with a non‑zero code (fail‑closed).
        """
        while self._running:
            await asyncio.sleep(self._config.heartbeat_interval)
            if not self._running:
                break
            # Renew the lease using the current fence.
            assert self._client is not None
            assert self._lease is not None
            try:
                renewed = self._client.renew_lease(
                    task_id=self._config.task_id,
                    lease_id=self._lease.lease_id,
                    fence=self._lease.claim_fence,
                )
                self._lease = renewed
                log.debug("Heartbeat renewed lease %s", renewed.lease_id)
            except Exception as exc:
                log.critical(
                    "Heartbeat renewal failed – exiting because fail‑closed semantics require abort. "
                    "lease=%s error=%s",
                    self._lease.lease_id,
                    exc,
                )
                # Exit with a non‑zero status to trigger OS supervision restart.
                sys.exit(1)

    def _handle_signal(self, signum, _frame) -> None:
        """Translate OS signals into a graceful driver shutdown."""
        log.info("Received signal %s – stopping takeover driver", signum)
        self.stop()
        sys.exit(0)


def _demo_run() -> None:
    """Simple CLI entry point for testing – not used in production."""
    import argparse

    parser = argparse.ArgumentParser(description="Takeover driver demo for task ownership")
    parser.add_argument("--task-id", type=int, required=True, help="Task ID to own")
    parser.add_argument("--owner", required=True, help="Owner identifier (e.g. mac-studio-owner)")
    parser.add_argument(
        "--no-heartbeat",
        action="store_true",
        help="Disable heartbeat loop (for unit tests)",
    )
    args = parser.parse_args()

    config = TakeoverDriverConfig(task_id=args.task_id, owner=args.owner)
    driver = TakeoverDriver(config)
    lease = driver.start()
    print(f"Started TakeoverDriver for task {args.task_id}, lease_id {lease.lease_id}")

    if args.no_heartbeat:
        # In test scenarios we may skip the loop – just keep the process alive
        while True:
            time.sleep(1)
    else:
        # Run asyncio event loop
        try:
            asyncio.get_event_loop().run_forever()
        except KeyboardInterrupt:
            driver.stop()
            sys.exit(0)


if __name__ == "__main__":
    _demo_run()