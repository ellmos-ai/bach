"""Sichere Fehlerbelege für den lokalen Doku-Wartungsdienst."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FAILURE_SCHEMA = "bach.maintenance-failure.v1"
FAILURE_PHASES = {
    "config_load",
    "runtime_init",
    "owner_acquire",
    "config_reload",
    "scheduler_tick",
    "status_write",
    "poll_wait",
    "shutdown_status_write",
    "serve",
    "tick",
    "documentation_dispatch",
    "handler_import",
    "handler_init",
    "handler_dispatch",
    "unknown",
}
_KEYS = {
    "schema",
    "observed_at",
    "phase",
    "exception_class",
    "host",
    "revision",
    "owner_generation",
}
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_REV = re.compile(r"[a-f0-9]{40}")
_GEN = re.compile(r"[a-f0-9]{32}")


def maintenance_exception_class(error):
    name = type(error).__name__
    return name if _CLASS.fullmatch(name) else "Exception"


def _host():
    try:
        value = socket.gethostname()
        return value if isinstance(value, str) and _HOST.fullmatch(value) else None
    except Exception:  # noqa: BLE001 - hostname data is optional and must stay redacted
        return None


def _revision(root):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=Path(root).resolve(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=1,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        value = result.stdout.strip()
        if result.returncode == 0 and _REV.fullmatch(value):
            return value
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def _symlink(path):
    path = Path(path)
    while True:
        if path.is_symlink():
            return True
        if path.parent == path:
            return False
        path = path.parent


def _local_runtime(runtime, task_db):
    try:
        runtime = Path(runtime).expanduser()
        task_db = Path(task_db).expanduser()
        if not runtime.is_absolute() or not task_db.is_absolute():
            return None
        if _symlink(runtime) or _symlink(task_db):
            return None
        if runtime.resolve() != (task_db.parent / "maintenance").resolve():
            return None
        if any("onedrive" in part.casefold() for part in runtime.parts):
            return None
        if not runtime.is_dir():
            return None
        return runtime
    except Exception:  # noqa: BLE001 - invalid paths fail closed
        return None


def write_failure_receipt(
    runtime,
    root,
    phase,
    error,
    guard=None,
    *,
    task_db=None,
    owner_generation=None,
    now=None,
):
    """Schreibt nur mit verfügbarem Lock-Guard einen redigierten lokalen Beleg."""
    if task_db is None or not callable(guard):
        return False
    if not hasattr(os, "fchmod"):
        return False
    runtime = _local_runtime(runtime, task_db)
    if runtime is None:
        return False

    temporary = None
    fd = None
    try:
        if not isinstance(phase, str) or phase not in FAILURE_PHASES:
            phase = "unknown"
        generation = None
        if isinstance(owner_generation, str) and _GEN.fullmatch(owner_generation):
            generation = owner_generation
        observed = now or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            return False
        value = {
            "schema": FAILURE_SCHEMA,
            "observed_at": (
                observed.astimezone(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            ),
            "phase": phase,
            "exception_class": maintenance_exception_class(error),
            "host": _host(),
            "revision": _revision(root),
            "owner_generation": generation,
        }
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(data) > 4096:
            return False

        target = runtime / "failure.json"
        if target.is_symlink():
            return False
        guard(target)
        fd, name = tempfile.mkstemp(prefix=".failure-", suffix=".tmp", dir=runtime)
        temporary = Path(name)
        os.fchmod(fd, 0o600)
        guard(temporary)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if target.is_symlink():
            return False
        guard(target)
        os.replace(temporary, target)
        temporary = None
        return True
    except Exception:  # noqa: BLE001 - preserve the primary runtime error
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def read_failure_receipt(runtime, *, now=None):
    """Liefert ausschließlich aktuelle, validierte Fehlerfelder."""
    try:
        runtime = Path(runtime)
        path = runtime / "failure.json"
        if _symlink(runtime) or path.is_symlink():
            return None, "maintenance_failure_unverified"
        if any("onedrive" in part.casefold() for part in runtime.parts):
            return None, "maintenance_failure_unverified"
        if not path.exists():
            return None, None
        if not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("invalid receipt")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != _KEYS:
            raise ValueError("invalid fields")
        if value["schema"] != FAILURE_SCHEMA or value["phase"] not in FAILURE_PHASES:
            raise ValueError("invalid identity")
        if not isinstance(value["exception_class"], str):
            raise TypeError("invalid exception class")
        if not _CLASS.fullmatch(value["exception_class"]):
            raise ValueError("invalid exception class")
        observed = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("invalid time")
        host = value["host"]
        revision = value["revision"]
        generation = value["owner_generation"]
        if host is not None and (
            not isinstance(host, str) or not _HOST.fullmatch(host)
        ):
            raise ValueError("invalid host")
        if revision is not None and (
            not isinstance(revision, str) or not _REV.fullmatch(revision)
        ):
            raise ValueError("invalid revision")
        if generation is not None and (
            not isinstance(generation, str) or not _GEN.fullmatch(generation)
        ):
            raise ValueError("invalid owner generation")
        age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
        if age < -300:
            raise ValueError("future receipt")
        if age > 86400:
            return None, "maintenance_failure_stale"
        return {key: value[key] for key in _KEYS}, "maintenance_failure"
    except Exception:  # noqa: BLE001 - malformed receipts remain unavailable
        return None, "maintenance_failure_unverified"
