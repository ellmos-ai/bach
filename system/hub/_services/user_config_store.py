# SPDX-License-Identifier: MIT
"""Concurrent-safe storage for the shared BACH user configuration."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


ConfigUpdater = Callable[[dict], dict | None]


def load_user_config(
    path: Path,
    default: dict | None = None,
    *,
    strict: bool = False,
) -> dict:
    """Load a complete JSON object, returning a copied default on bad input."""
    fallback = dict(default or {})
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise ValueError(f"User-Config ist nicht lesbar: {exc}") from exc
        return fallback
    if isinstance(data, dict):
        return data
    if strict:
        raise ValueError("User-Config muss ein JSON-Objekt enthalten")
    return fallback


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Hold a one-byte advisory lock shared by all user-config writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    with lock_path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()

        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"User-Config ist gesperrt: {path}")
                time.sleep(0.025)

        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_user_config(
    path: Path,
    updater: ConfigUpdater,
    *,
    default: dict | None = None,
    timeout_seconds: float = 5.0,
) -> dict:
    """Atomically read, update and replace the shared JSON configuration."""
    with _exclusive_lock(path, timeout_seconds):
        current = load_user_config(path, default, strict=path.exists())
        updated = updater(dict(current))
        if updated is None:
            updated = current
        if not isinstance(updated, dict):
            raise TypeError("User-Config updater muss ein dict liefern")

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return updated
