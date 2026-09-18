# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Single-Flight Network Lock
==========================
Ruecktransfer robuster Kernel-Schutzmechanismen aus NemoFold in BACH Core und OPEN OCEAN.
Absicherung von Netzwerkuebertragungen und SQLite-Transit-Synchronisationen
durch ein atomares 'transfer-attempt.json'-Lockfile mit Maschinen- und Prozess-Token.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


class SingleFlightLockError(RuntimeError):
    """Wird ausgeloest, wenn ein konkurrierender Transfer bereits aktiv ist."""


@dataclass(frozen=True)
class LockPayload:
    machine_token: str
    pid: int
    session_token: str
    started_at: float
    expires_at: float
    purpose: str


class SingleFlightLock:
    """Atomares Single-Flight Lockfile ueber transfer-attempt.json."""

    def __init__(
        self,
        lock_path: Path | str,
        ttl_seconds: int = 300,
        purpose: str = "sqlite-transit-sync",
        machine_token: Optional[str] = None,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.ttl_seconds = ttl_seconds
        self.purpose = purpose
        self.machine_token = machine_token or socket.gethostname()
        self.session_token = str(uuid.uuid4())
        self._acquired = False

    def __enter__(self) -> SingleFlightLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = LockPayload(
            machine_token=self.machine_token,
            pid=os.getpid(),
            session_token=self.session_token,
            started_at=now,
            expires_at=now + self.ttl_seconds,
            purpose=self.purpose,
        )
        data = json.dumps(asdict(payload), indent=2).encode("utf-8")

        try:
            # Atomare Dateierstellung mit O_CREAT | O_EXCL
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            self._acquired = True
        except FileExistsError:
            # Pruefe ob existierendes Lock abgelaufen ist (Stale Lock Recovery)
            if self._is_stale():
                try:
                    self.lock_path.unlink()
                    fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                    self._acquired = True
                    return
                except Exception:
                    pass
            raise SingleFlightLockError(
                f"Konkurrierender Transfer aktiv: {self.lock_path} ist durch einen anderen Prozess gesperrt."
            )

    def _is_stale(self) -> bool:
        try:
            content = self.lock_path.read_text(encoding="utf-8")
            info = json.loads(content)
            expires = info.get("expires_at", 0)
            return time.time() > expires
        except Exception:
            return False

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            if self.lock_path.exists():
                content = self.lock_path.read_text(encoding="utf-8")
                info = json.loads(content)
                if info.get("session_token") == self.session_token:
                    self.lock_path.unlink()
        except Exception:
            pass
        finally:
            self._acquired = False
