#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Coordinate watchdog Ollama unload with BACH's existing host inference lock.

No model starts, new admission queue, owner records, or background jobs.
Exit 0: all requested unloads confirmed; 1: skipped/failed/partly applied.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import signal
import stat
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "http://127.0.0.1:11434"
MAX_RESPONSE = 262144
SUPPORTED_OLLAMA_VERSION = "0.33.3"


class Denied(Exception):
    pass


class Unconfirmed(Denied):
    pass


def read_object(path: Path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(data) > MAX_RESPONSE:
        raise Denied("session_record_too_large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise Denied("invalid_session_record")
    return value


def session_blocks(path: Path):
    value = read_object(path)
    if value is None:
        return False
    timestamp = value.get("timestamp_last_request")
    keep_alive = value.get("effective_keep_alive_seconds", 300)
    active = value.get("model_active_inferenz", False)
    if (
        type(timestamp) not in (int, float)
        or not math.isfinite(timestamp)
        or timestamp <= 0
        or type(keep_alive) not in (int, float)
        or not math.isfinite(keep_alive)
        or keep_alive < 0
        or type(active) is not bool
    ):
        raise Denied("invalid_session_record")
    age = time.time() - timestamp
    if age < 0:
        raise Denied("future_session_record")
    # Preserve the original one-hour crash/staleness boundary.
    if age > 3600:
        return False
    return active or age < keep_alive + 120


def read_pressure():
    result = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
        capture_output=True, text=True, timeout=3, check=False,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or value not in {"1", "2", "4"}:
        raise Denied("pressure_unknown")
    return int(value)


def read_free_pages():
    result = subprocess.run(
        ["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=3,
        check=False,
    )
    match = re.search(r"^Pages free:\s+(\d+)\.", result.stdout, re.MULTILINE)
    if result.returncode != 0 or match is None:
        raise Denied("free_pages_unknown")
    return int(match.group(1))


def check_conditions(args):
    if session_blocks(args.session_flag):
        raise Denied("session_active")
    pressure = read_pressure()
    # Confirmed normal pressure is never a reason to unload a model.
    if pressure == 1:
        raise Denied("pressure_normal")
    free = read_free_pages()
    if args.metric_mode == "pressure":
        eligible = pressure >= args.warn_level or free < args.emergency_pages
    else:
        eligible = free < args.free_threshold
    if not eligible:
        raise Denied("pressure_recovered")


def api_request(opener, path, deadline, payload=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Denied("unload_deadline")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API + path, data=body, headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    # Bypass ambient proxies: only the fixed local Ollama server is addressed.
    with opener.open(request, timeout=min(5, remaining)) as response:
        data = response.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise Denied("ollama_response_too_large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise Denied("invalid_ollama_response")
    return value


def model_records(snapshot):
    models = snapshot.get("models")
    if not isinstance(models, list) or len(models) > 16:
        raise Denied("invalid_model_list")
    records = []
    for model in models:
        if not isinstance(model, dict):
            raise Denied("invalid_model_list")
        name = model.get("name")
        if not isinstance(name, str) or not name or len(name) > 512:
            raise Denied("invalid_model_list")
        digest = model.get("digest")
        if not isinstance(digest, str) or not digest or len(digest) > 128:
            raise Denied("invalid_model_digest")
        if any(previous[0] == name and previous[1] != digest for previous in records):
            raise Denied("ambiguous_model_identity")
        record = (name, digest)
        if record not in records:
            records.append(record)
    return records


def deadline_expired(signum, frame):
    raise TimeoutError("unload guard deadline")


def sync_directory(root):
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def record_intent(root, name, digest):
    path = root / "unload-pending.json"
    # Durable intent must precede the external effect. A partial write or any
    # crash is deliberately a hold; neither gate nor watchdog auto-removes it.
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        import hashlib

        json.dump({
            "schema": "bach.inference-unload-intent.v1",
            "request_id": uuid.uuid4().hex,
            "pid": os.getpid(),
            "started_at": time.time(),
            "target_sha256": hashlib.sha256(
                json.dumps([name, digest], separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }, handle)
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(root)
    return path


def unload(args):
    root = args.inference_root.expanduser()
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise Denied("inference_root_unavailable")
    if any(part.lower().startswith("onedrive") for part in root.resolve().parts):
        raise Denied("inference_root_not_local")
    # Same inode and same flock family as user_config_store._exclusive_lock.
    # Never unlink, replace, or create an alternative inference lock.
    path = root / "inference.lock"
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "r+b") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise Denied("invalid_inference_lock")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Denied("inference_active") from None
        try:
            if path.stat().st_ino != info.st_ino:
                raise Denied("inference_lock_changed")
            if os.path.lexists(root / "unload-pending.json"):
                raise Denied("previous_unload_unresolved")
            check_conditions(args)
            deadline = time.monotonic() + 20
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            version = api_request(opener, "/api/version", deadline)
            if version.get("version") != SUPPORTED_OLLAMA_VERSION:
                raise Denied("ollama_version_not_reviewed")
            records = model_records(api_request(opener, "/api/ps", deadline))
            if not records:
                raise Denied("no_loaded_models")
            for name, digest in records:
                check_conditions(args)
                pending = record_intent(root, name, digest)
                try:
                    response = api_request(
                        opener, "/api/generate", deadline,
                        {"model": name, "keep_alive": 0, "stream": False},
                    )
                    if response.get("done") is not True or response.get("done_reason") != "unload":
                        raise Denied("unload_not_confirmed")
                    # v0.33.3 acknowledges scheduling expiry before the runner
                    # actually unloads. A busy direct caller keeps its runner alive.
                    # Keep both lock and durable intent until observed completion.
                    while any(
                        observed_name == name or observed_digest == digest
                        for observed_name, observed_digest in model_records(
                            api_request(opener, "/api/ps", deadline)
                        )
                    ):
                        if time.monotonic() >= deadline:
                            raise Denied("unload_completion_unknown")
                        time.sleep(.1)
                    pending.unlink()
                    sync_directory(root)
                except Denied as error:
                    # An accepted or attempted POST is never a skipped action.
                    raise Unconfirmed(str(error)) from None
                # Do not emit model names or free-form server responses.
                print("ollama_unload_confirmed", flush=True)
            return 0
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inference-root", type=Path, required=True)
    parser.add_argument("--session-flag", type=Path, required=True)
    parser.add_argument("--metric-mode", choices=("pressure", "free"), required=True)
    parser.add_argument("--warn-level", type=int, choices=(2, 4), required=True)
    parser.add_argument("--emergency-pages", type=int, required=True)
    parser.add_argument("--free-threshold", type=int, required=True)
    args = parser.parse_args()
    if args.emergency_pages < 0 or args.free_threshold < 0:
        parser.error("page thresholds must be nonnegative")
    previous_handler = signal.signal(signal.SIGALRM, deadline_expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, 20)
        return unload(args)
    except Unconfirmed as error:
        print("ollama_unload_unconfirmed:" + str(error), flush=True)
    except Denied as error:
        print("ollama_unload_skipped:" + str(error), flush=True)
    except (OSError, ValueError, OverflowError, TimeoutError, subprocess.SubprocessError,
            urllib.error.URLError):
        # A timeout can follow an applied POST. Never claim a confirmed effect
        # and never automatically retry the ambiguous POST here.
        print("ollama_unload_unconfirmed:guard_or_api_error", flush=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
