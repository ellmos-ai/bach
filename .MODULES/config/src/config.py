# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Standalone Module: config
============================
Concurrent-safe atomic JSON configuration storage and local LLM backend preset resolver.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

ConfigUpdater = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]


def load_config(
    path: Path | str,
    default: Optional[Dict[str, Any]] = None,
    *,
    strict: bool = False,
) -> Dict[str, Any]:
    """Load a JSON config dictionary with optional strict parsing."""
    target = Path(path)
    fallback = dict(default or {})
    if not target.exists():
        return fallback
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise ValueError(f"Config unreadable: {exc}") from exc
        return fallback
    if isinstance(data, dict):
        return data
    if strict:
        raise ValueError("Config must contain a JSON object")
    return fallback


@contextmanager
def _exclusive_file_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    """Hold a portable one-byte advisory file lock."""
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
                    raise TimeoutError(f"Config locked: {path}")
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


def update_config(
    path: Path | str,
    updater: ConfigUpdater,
    *,
    default: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 5.0,
) -> Dict[str, Any]:
    """Atomically read, update and replace a JSON configuration file."""
    target = Path(path)
    with _exclusive_file_lock(target, timeout_seconds):
        current = load_config(target, default, strict=target.exists())
        updated = updater(dict(current))
        if updated is None:
            updated = current
        if not isinstance(updated, dict):
            raise TypeError("Config updater must return a dict or None")

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, target)
        return updated


def resolve_backend_config(
    config: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Resolve effective local LLM backend config with provider-specific env overrides."""
    environ = env if env is not None else os.environ
    cfg = dict(config or {})
    backend = dict(cfg.get("backend") or {
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "default_model": "qwen3.8:27b-mlx",
    })
    kind = str(backend.get("type") or "ollama").lower()
    if kind in ("lm-studio", "lm_studio"):
        kind = "lmstudio"
    backend["type"] = kind
    prefix = "OLLAMA" if kind == "ollama" else ("LM_STUDIO" if kind == "lmstudio" else None)
    if prefix:
        if environ.get(f"{prefix}_MODEL"):
            backend["default_model"] = environ[f"{prefix}_MODEL"]
        if environ.get(f"{prefix}_URL"):
            backend["base_url"] = environ[f"{prefix}_URL"]
    return backend
