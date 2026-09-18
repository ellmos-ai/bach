# -*- coding: utf-8 -*-
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Single-Flight Network Lock
==========================
Atomares Single-Flight Locking mit Maschinen- und Prozess-Token
(z. B. transfer-attempt.json) zur Vermeidung von parallelen Schreib- und
Transfer-Konflikten bei Cloud- und Transit-Synchronisationen.

Ruecktransfer aus NemoFold / Ratified Architectural Pattern (T-20260917-318279373).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("bach.network_lock")

DEFAULT_LOCK_NAME = "transfer-attempt.json"
DEFAULT_TTL_SECONDS = 120.0


class SingleFlightLockError(RuntimeError):
    """Ausgeloest wenn der Single-Flight Lock nicht erworben werden kann."""

    def __init__(self, message: str, lock_info: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.lock_info = lock_info


def _is_pid_alive(pid: int) -> bool:
    """Prueft, ob der angegebene Prozess noch laeuft (cross-platform, Windows-sicher)."""
    if pid <= 0:
        return False
    # 1. psutil wenn vorhanden
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass

    # 2. Windows: OpenProcess prueft Existenz ohne TerminateProcess-Gefahr
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == 259  # STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)

    # 3. Unix/POSIX: Signal 0 prueft Existenz ohne Signalwirkung
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class SingleFlightLock:
    """Atomarer Single-Flight Lock mit Maschinen- und Prozess-Token.

    Nutzt OS-Level atomare Dateierstellung (O_CREAT | O_EXCL) mit
    integrierter Stale-Erkennung (abgelaufene TTL oder toter lokaler PID).
    """

    def __init__(
        self,
        lock_dir: Path | str,
        lock_name: str = DEFAULT_LOCK_NAME,
        timeout: float = 0.0,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        operation: str = "transfer",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.lock_dir = Path(lock_dir)
        self.lock_name = lock_name
        self.lock_file = self.lock_dir / self.lock_name
        self.timeout = float(timeout)
        self.ttl_seconds = float(ttl_seconds)
        self.operation = operation
        self.metadata = metadata or {}

        self.machine = socket.gethostname()
        self.pid = os.getpid()
        self.lock_id = str(uuid.uuid4())
        self.process_token = f"{self.machine}:{self.pid}:{self.lock_id}"
        self.is_acquired = False

    def read_lock_file(self) -> Optional[Dict[str, Any]]:
        """Liest die aktuellen Lock-Metadaten."""
        if not self.lock_file.exists():
            return None
        try:
            content = self.lock_file.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception:
            return None

    def _check_and_break_stale(self) -> bool:
        """Prueft ob die vorhandene Lock-Datei stale ist und raeumt sie auf."""
        info = self.read_lock_file()
        if info is None:
            # Datei existiert, ist aber korrupt/leer
            try:
                self.lock_file.unlink(missing_ok=True)
                logger.warning(
                    "[SingleFlightLock] Korrupte/leere Lockdatei entfernt: %s",
                    self.lock_file,
                )
                return True
            except OSError:
                return False

        # 1. TTL-Pruefung
        expires_at_str = info.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now() > expires_at:
                    try:
                        self.lock_file.unlink(missing_ok=True)
                        logger.warning(
                            "[SingleFlightLock] Abgelaufenen Lock (TTL) entfernt: %s (Erstellt: %s, Ablauf: %s)",
                            self.lock_file,
                            info.get("created_at"),
                            expires_at_str,
                        )
                        return True
                    except OSError:
                        return False
            except ValueError:
                pass

        # 2. Gleiche Maschine, toter PID
        lock_machine = info.get("machine")
        lock_pid = info.get("pid")
        if lock_machine == self.machine and isinstance(lock_pid, int):
            if not _is_pid_alive(lock_pid):
                try:
                    self.lock_file.unlink(missing_ok=True)
                    logger.warning(
                        "[SingleFlightLock] Lock von beendetem PID %d auf Host %s entfernt: %s",
                        lock_pid,
                        lock_machine,
                        self.lock_file,
                    )
                    return True
                except OSError:
                    return False

        return False

    def _try_acquire(self) -> bool:
        """Versucht einmalig die atomare Erstellung der Lock-Datei."""
        self.lock_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "lock_id": self.lock_id,
            "machine": self.machine,
            "pid": self.pid,
            "process_token": self.process_token,
            "operation": self.operation,
            "created_at": datetime.now().isoformat(),
            "expires_at": (
                datetime.now() + timedelta(seconds=self.ttl_seconds)
            ).isoformat(),
            "metadata": self.metadata,
        }
        raw_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY

        try:
            fd = os.open(str(self.lock_file), flags)
        except FileExistsError:
            if self._check_and_break_stale():
                try:
                    fd = os.open(str(self.lock_file), flags)
                except FileExistsError:
                    return False
            else:
                return False
        except OSError as e:
            raise SingleFlightLockError(
                f"Fehler beim Erstellen der Lockdatei {self.lock_file}: {e}"
            ) from e

        try:
            os.write(fd, raw_bytes)
        finally:
            os.close(fd)

        self.is_acquired = True
        return True

    def acquire(
        self, timeout: Optional[float] = None, retry_interval: float = 0.1
    ) -> bool:
        """Erwirbt den Single-Flight Lock, optional mit Timeout."""
        t_wait = self.timeout if timeout is None else float(timeout)

        if t_wait <= 0:
            if not self._try_acquire():
                info = self.read_lock_file()
                raise SingleFlightLockError(
                    f"Single-Flight Lock aktiv auf {self.lock_file}: "
                    f"Maschine={info.get('machine') if info else '?'}, "
                    f"PID={info.get('pid') if info else '?'}, "
                    f"Op={info.get('operation') if info else '?'}",
                    lock_info=info,
                )
            return True

        deadline = time.monotonic() + t_wait
        while True:
            if self._try_acquire():
                return True
            if time.monotonic() >= deadline:
                info = self.read_lock_file()
                raise SingleFlightLockError(
                    f"Timeout ({t_wait}s) beim Warten auf Single-Flight Lock {self.lock_file}: "
                    f"gehalten von {info}",
                    lock_info=info,
                )
            time.sleep(retry_interval)

    def release(self) -> bool:
        """Gibt den Lock frei (loescht Lock-Datei nur wenn Prozess-Token uebereinstimmt)."""
        if not self.is_acquired:
            return False

        try:
            info = self.read_lock_file()
            if info and info.get("process_token") == self.process_token:
                self.lock_file.unlink(missing_ok=True)
            elif not self.lock_file.exists():
                pass
            else:
                logger.warning(
                    "[SingleFlightLock] Lockdatei %s gehoert nicht mehr zu Token %s",
                    self.lock_file,
                    self.process_token,
                )
        except OSError as e:
            logger.warning(
                "[SingleFlightLock] Fehler beim Freigeben von %s: %e",
                self.lock_file,
                e,
            )
        finally:
            self.is_acquired = False

        return True

    def __enter__(self) -> "SingleFlightLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


def get_lock_info(
    lock_dir: Path | str, lock_name: str = DEFAULT_LOCK_NAME
) -> Optional[Dict[str, Any]]:
    """Gibt Metadaten des aktuellen Single-Flight Locks zurueck oder None."""
    lock_path = Path(lock_dir) / lock_name
    if not lock_path.exists():
        return None
    try:
        content = lock_path.read_text(encoding="utf-8")
        info = json.loads(content)
        # Pruefe Stale
        expires_at_str = info.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now() > expires_at:
                    return None
            except ValueError:
                pass
        return info
    except Exception:
        return None


def is_locked(lock_dir: Path | str, lock_name: str = DEFAULT_LOCK_NAME) -> bool:
    """Prueft, ob ein aktiver Single-Flight Lock vorliegt."""
    return get_lock_info(lock_dir, lock_name=lock_name) is not None


def force_break_lock(lock_dir: Path | str, lock_name: str = DEFAULT_LOCK_NAME) -> bool:
    """Entfernt gewaltsam eine bestehende Lock-Datei."""
    lock_path = Path(lock_dir) / lock_name
    if not lock_path.exists():
        return False
    try:
        lock_path.unlink()
        return True
    except OSError:
        return False


@contextmanager
def single_flight_lock(
    lock_dir: Path | str,
    lock_name: str = DEFAULT_LOCK_NAME,
    timeout: float = 0.0,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    operation: str = "transfer",
    metadata: Optional[Dict[str, Any]] = None,
):
    """Context Manager fuer Single-Flight Lock."""
    lock = SingleFlightLock(
        lock_dir=lock_dir,
        lock_name=lock_name,
        timeout=timeout,
        ttl_seconds=ttl_seconds,
        operation=operation,
        metadata=metadata,
    )
    with lock:
        yield lock
