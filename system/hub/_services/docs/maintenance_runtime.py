"""One process owner consuming ellmos-scheduler's native due/claim/run engine."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hub.scheduler_provider import create_documentation_scheduler

from .maintenance_dispatch import PACKAGES, DocumentationDispatcher, read_state, stamp
from .maintenance_failure import (
    maintenance_exception_class,
    read_failure_receipt,
    write_failure_receipt,
)
from .maintenance_recurring import ROUTINES, dispatch_routine, routine_definitions

CONFIG_SCHEMA = "bach.maintenance-config.v1"
BINDING_REQUEST_SCHEMA = "bach.maintenance-worker-binding-request.v1"
BINDING_ACK_SCHEMA = "bach.maintenance-worker-binding-ack.v1"
STATUS_SCHEMA = "bach.maintenance-status.v1"
JOB_ID = "bach.docs.delta"
JOB_IDS = {JOB_ID, *["bach.docs.routine." + name for name in ROUTINES]}
STATES = {"running", "busy", "backoff", "storage_budget", "storage_reserve", "stopped"}
TASK_STATES = {
    "pending",
    "open",
    "in_progress",
    "review",
    "done",
    "completed",
    "cancelled",
    "blocked",
}
TRUSTED_LOCK_TOOLS = {
    # Verified native lock-master a807cad; Windows canonical scripts 2026-10-10.
    (
        "154c504cb6c37a01740e889b9435b95ef510a7a6ea598417e5bff1bbae4e8770",
        "604cdf2686f716309c701b021e09e8050ae5d36d6ffd21c73d376c8caa69f4fe",
    ),
    (
        "5f3f961bfc3975a30bc4e9403115570a64bb08147a0188cab1a24435b6fa7ce4",
        "b46f8110311d134f9c229e05d3f6a897033cf32ff94b5773a09ba966373f7363",
    ),
}


def _safe_scalar(key, value):
    if value is None:
        return value
    if key in {"task_id", "result_id", "exit_code"}:
        if type(value) is not int or (key != "exit_code" and value <= 0):
            raise ValueError("Invalid public maintenance number")
    elif key in {"enabled", "result_accepted"}:
        if type(value) is not bool:
            raise ValueError("Invalid public maintenance boolean")
    elif key in {"revision", "run_id"}:
        pattern = "[a-f0-9]{40}" if key == "revision" else "[a-f0-9]{64}"
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError("Invalid public maintenance identifier")
    elif key in {"id", "job_id"}:
        if value not in JOB_IDS:
            raise ValueError("Invalid public maintenance job")
    elif key == "task_status":
        if value not in TASK_STATES:
            raise ValueError("Invalid public task status")
    elif key == "status":
        if value not in {
            "succeeded",
            "failed",
            "timed_out",
            "running",
            "claimed",
            "skipped",
        }:
            raise ValueError("Invalid public run status")
    elif (
        not isinstance(value, str)
        or len(value) > 40
        or datetime.fromisoformat(value).tzinfo is None
    ):
        raise ValueError("Invalid public maintenance timestamp")
    return value


def load_config(path: Path) -> dict:
    if path.stat().st_size > 16384:
        raise ValueError("Maintenance configuration exceeds budget")
    return validate_config(json.loads(path.read_text(encoding="utf-8")))


def validate_config(config: dict) -> dict:
    expected = {
        "schema",
        "enabled",
        "interval_seconds",
        "poll_seconds",
        "min_available_mib",
        "max_state_db_bytes",
        "lock_tools_root",
        "protected_roots",
        "worker_binding",
    }
    if (
        not isinstance(config, dict)
        or set(config) != expected
        or config["schema"] != CONFIG_SCHEMA
    ):
        raise ValueError("Invalid maintenance configuration")
    if type(config["enabled"]) is not bool:
        raise ValueError("Explicit maintenance activation required")
    for field, minimum, maximum in (
        ("interval_seconds", 60, 86400),
        ("poll_seconds", 5, 300),
        ("min_available_mib", 128, 8192),
        ("max_state_db_bytes", 1048576, 1073741824),
    ):
        value = config[field]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("Invalid maintenance budget")
    roots = config["protected_roots"]
    if (
        not isinstance(roots, list)
        or not 1 <= len(roots) <= 8
        or any(not isinstance(p, str) or not Path(p).is_absolute() for p in roots)
    ):
        raise ValueError("Explicit protected roots required")
    tools = config["lock_tools_root"]
    if not isinstance(tools, str) or not Path(tools).is_absolute():
        raise ValueError("Explicit canonical lock tools required")
    binding = config["worker_binding"]
    if (
        not isinstance(binding, dict)
        or set(binding) - {"assigned_slot", "required_model"}
        or any(
            not isinstance(v, str) or not v.strip() or len(v) > 128
            for v in binding.values()
        )
    ):
        raise ValueError("Invalid worker binding")
    return config


class CanonicalLockGuard:
    def __init__(self, config: dict):
        self.scanner = Path(config["lock_tools_root"]) / "lock_scan.py"
        self.roots = [Path(p) for p in config["protected_roots"]]

    def __call__(self, target: Path):
        if not self.scanner.is_file():
            raise PermissionError("maintenance_lock_unverified")
        utility = self.scanner.parent / "lock_utils.py"
        try:
            if any(
                path.is_symlink() or path.stat().st_size > 262144
                for path in (self.scanner, utility)
            ):
                raise PermissionError("maintenance_lock_source_unverified")
            pair = tuple(
                hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (self.scanner, utility)
            )
            if pair not in TRUSTED_LOCK_TOOLS:
                raise PermissionError("maintenance_lock_source_unverified")
        except OSError:
            raise PermissionError("maintenance_lock_source_unverified") from None
        deadline = time.monotonic() + 6
        for path in dict.fromkeys([*self.roots, target]):
            existing = path
            while not existing.exists() and existing != existing.parent:
                existing = existing.parent
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-S",
                        str(self.scanner),
                        "--check-dir",
                        str(existing),
                        "--json",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=max(0.01, deadline - time.monotonic()),
                    check=False,
                    env={
                        **os.environ,
                        "PYTHONIOENCODING": "utf-8",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                value = json.loads(result.stdout)
            except (OSError, ValueError, subprocess.SubprocessError):
                raise PermissionError("maintenance_lock_unverified") from None
            if (
                result.returncode != 0
                or len(result.stdout.encode("utf-8")) > 65536
                or value.get("locks") != []
                or value.get("twin_status") not in {"ok", "not-applicable"}
            ):
                raise PermissionError("maintenance_locked_or_unknown")
            if Path(value.get("checked", "")).resolve() != existing.resolve():
                raise PermissionError("maintenance_lock_target_unverified")
            if path == self.roots[0]:
                twins = value.get("twins_checked")
                if (
                    value.get("twin_status") != "ok"
                    or not isinstance(twins, list)
                    or not twins
                    or not any(
                        Path(twin).resolve() in [p.resolve() for p in self.roots[1:]]
                        for twin in twins
                    )
                ):
                    raise PermissionError("maintenance_project_twin_unverified")


@contextmanager
def process_owner(path: Path, guard):
    """OS releases this exclusion on exit/crash; a PID number is no authority."""
    guard(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise PermissionError("Invalid maintenance owner path")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _write_status(path: Path, value: dict, guard):
    guard(path)
    if (
        path.is_symlink()
        or path.with_suffix(".tmp").is_symlink()
        or any(p.is_symlink() for p in path.parents)
    ):
        raise PermissionError("Invalid maintenance status path")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("Maintenance status exceeds budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    guard(temporary)
    temporary.write_text(encoded, encoding="utf-8")
    guard(path)
    temporary.replace(path)


def readonly_status(
    runtime: Path, *, root: Path, config_path=None, now=None, process_factory=None
) -> dict:
    """No imports of the store, migrations, database creation or process starts."""
    failure, failure_reason = read_failure_receipt(runtime, now=now)

    def empty_status(reason="no_maintenance_receipt"):
        value = {
            "schema": STATUS_SCHEMA,
            "running": False,
            "identity": "unknown",
            "reason": reason,
            "semantic_review_completed": False,
        }
        if failure is not None:
            value["last_failure"] = failure
            if reason == "no_maintenance_receipt":
                value["reason"] = failure_reason or "maintenance_failure"
        elif failure_reason is not None and reason == "no_maintenance_receipt":
            value["reason"] = failure_reason
        return value

    empty = empty_status()
    path = runtime / "status.json"
    try:
        if not path.is_file():
            return empty
        if path.stat().st_size > 65536:
            raise ValueError("Invalid maintenance receipt")
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value.get("schema") != STATUS_SCHEMA
            or value.get("service") != "bach-docs-maintenance"
            or type(value.get("pid")) is not int
            or value["pid"] <= 0
            or value.get("root_id")
            != hashlib.sha256(str(root.resolve()).encode()).hexdigest()
            or type(value.get("poll_seconds")) is not int
            or not 5 <= value["poll_seconds"] <= 300
            or type(value.get("create_time")) not in (int, float)
            or not math.isfinite(value["create_time"])
        ):
            raise ValueError("Invalid maintenance receipt")
        if (
            value.get("state") not in STATES
            or value.get("provider") != "ellmos-scheduler"
            or not re.fullmatch("[a-f0-9]{32}", value.get("generation", ""))
        ):
            raise ValueError("Invalid maintenance producer")
        config_path = config_path or runtime / "config.json"
        load_config(config_path)
        if (
            value.get("config_hash")
            != hashlib.sha256(config_path.read_bytes()).hexdigest()
        ):
            raise ValueError("Maintenance configuration changed")
        if process_factory is None:
            import psutil

            process_factory = psutil.Process
        process = process_factory(value["pid"])
        current = now or datetime.now(timezone.utc)
        observed = datetime.fromisoformat(value["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("Invalid maintenance time")
        age = (current - observed).total_seconds()
        command = process.cmdline()
        expected = root / "system/tools/maintenance/scheduler_maintenance.py"
        command_matches = (
            len(command) >= 3
            and Path(command[1]).resolve() == expected.resolve()
            and command[2] == "serve"
        )
        for flag, required in (("--config", config_path), ("--runtime-dir", runtime)):
            if flag in command:
                position = command.index(flag)
                command_matches = (
                    command_matches
                    and command.count(flag) == 1
                    and position + 1 < len(command)
                    and Path(command[position + 1]).resolve() == required.resolve()
                )
        if not command_matches:
            raise ValueError("Maintenance command mismatch")
        live = (
            process.is_running()
            and abs(process.create_time() - value["create_time"]) < 0.001
            and 0 <= age <= 2 * value["poll_seconds"] + 30
            and value.get("state") not in {"stopped", "disabled", "error"}
        )
        allowed = {
            "schema",
            "service",
            "pid",
            "generation",
            "poll_seconds",
            "observed_at",
            "provider",
            "state",
            "runs",
            "semantic_review_completed",
            "documentation",
        }
        public = {
            key: value[key]
            for key in allowed - {"runs", "documentation"}
            if key in value
        }
        public["semantic_review_completed"] = False
        runs = value.get("runs", [])
        if not isinstance(runs, list) or len(runs) > 10:
            raise ValueError("Invalid maintenance runs")
        public["runs"] = [
            {
                key: _safe_scalar(key, row[key])
                for key in (
                    "run_id",
                    "job_id",
                    "status",
                    "started_at",
                    "finished_at",
                    "exit_code",
                )
                if key in row
            }
            for row in runs
            if isinstance(row, dict)
        ]
        documentation = value.get("documentation", {})
        if not isinstance(documentation, dict):
            raise TypeError("Invalid documentation receipt")
        projected = {}
        item_fields = {
            "task_id",
            "revision",
            "dispatched_at",
            "task_status",
            "result_accepted",
            "result_id",
            "last_review_success",
            "last_repair_success",
        }
        for collection in ("packages", "routines"):
            items = documentation.get(collection, {})
            if not isinstance(items, dict) or len(items) > 6:
                raise ValueError("Invalid documentation receipt")
            if set(items) - (
                {*PACKAGES, "root"} if collection == "packages" else set(ROUTINES)
            ):
                raise ValueError("Invalid documentation source")
            projected[collection] = {
                name: {
                    key: _safe_scalar(key, item[key])
                    for key in item_fields
                    if key in item
                }
                for name, item in items.items()
                if isinstance(item, dict)
            }
        public["documentation"] = projected
        public["jobs"] = value.get("jobs", [])
        if not isinstance(public["jobs"], list) or len(public["jobs"]) > 5:
            raise ValueError("Invalid documentation job receipts")
        public["jobs"] = [
            {
                key: _safe_scalar(key, row[key])
                for key in ("id", "enabled", "next_due_at", "last_success")
                if key in row
            }
            for row in public["jobs"]
            if isinstance(row, dict)
        ]
        result = {
            **public,
            "running": live,
            "identity": "verified" if live else "unverified",
            "age_seconds": max(0, int(age)),
            "reason": "process_and_heartbeat" if live else "receipt_not_current",
        }
        if failure is not None:
            result["last_failure"] = failure
        return result
    except Exception:  # noqa: BLE001 - fail closed across optional process implementations
        return empty_status("maintenance_receipt_unverified")


def _configuration_bytes(config: dict) -> bytes:
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8")


def _binding_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _binding_path_guard(path: Path, guard):
    if os.name != "posix":
        raise PermissionError("maintenance_private_runtime_unavailable")
    path = Path(path)
    guard(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise PermissionError("maintenance_private_path_unverified")


def _read_private_json(path: Path, guard):
    _binding_path_guard(path, guard)
    try:
        info = path.lstat()
        if (
            not path.is_file()
            or info.st_size > 32768
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("maintenance_private_receipt_unverified")
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("maintenance_private_receipt_unverified") from None
    if not isinstance(value, dict):
        raise TypeError("maintenance_private_receipt_unverified")
    return data, value


def _atomic_write_bytes(
    path: Path,
    data: bytes,
    guard,
    *,
    mode: int,
    exclusive=False,
    expected_existing: bytes | None = None,
):
    if os.name != "posix":
        raise PermissionError("maintenance_private_runtime_unavailable")
    path = Path(path)
    _binding_path_guard(path, guard)
    if not path.parent.is_dir():
        raise FileNotFoundError("maintenance_runtime_unavailable")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    _binding_path_guard(temporary, guard)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        _binding_path_guard(path, guard)
        if expected_existing is not None and path.read_bytes() != expected_existing:
            raise RuntimeError("maintenance_configuration_conflict")
        if exclusive:
            os.link(temporary, path)
            temporary.unlink()
        else:
            if path.is_symlink():
                raise PermissionError("maintenance_private_path_unverified")
            os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            _binding_path_guard(temporary, guard)
            temporary.unlink()


def _write_private_json(path: Path, value: dict, guard, *, exclusive=False):
    data = json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    _atomic_write_bytes(path, data, guard, mode=0o600, exclusive=exclusive)
    return data


def _remove_private_json(path: Path, guard):
    if not path.exists():
        return
    _binding_path_guard(path, guard)
    _read_private_json(path, guard)
    path.unlink()
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _binding_ack_matches(ack: dict, request: dict, request_bytes: bytes) -> bool:
    required = {
        "schema",
        "nonce",
        "request_generation",
        "owner_generation",
        "request_sha256",
        "status",
        "error_code",
        "old_config_sha256",
        "new_config_sha256",
        "worker_binding",
        "observed_at",
    }
    if (
        set(ack) != required
        or ack.get("schema") != BINDING_ACK_SCHEMA
        or ack.get("nonce") != request.get("nonce")
        or ack.get("request_generation") != request.get("generation")
        or ack.get("request_sha256") != _binding_digest(request_bytes)
        or not isinstance(ack.get("owner_generation"), str)
        or re.fullmatch(r"[a-f0-9]{32}", ack["owner_generation"]) is None
        or ack.get("status") not in {"applied", "no_change", "rejected"}
        or not isinstance(ack.get("observed_at"), str)
    ):
        return False
    try:
        if datetime.fromisoformat(ack["observed_at"]).tzinfo is None:
            return False
    except ValueError:
        return False
    hashes = (ack.get("old_config_sha256"), ack.get("new_config_sha256"))
    if any(
        value is not None
        and (
            not isinstance(value, str)
            or re.fullmatch(r"[a-f0-9]{64}", value) is None
        )
        for value in hashes
    ):
        return False
    if ack.get("status") == "rejected":
        return ack.get("error_code") in {
            "maintenance_binding_request_invalid",
            "maintenance_configuration_unavailable",
            "maintenance_generation_conflict",
            "maintenance_binding_conflict",
            "maintenance_configuration_conflict",
        }
    return (
        ack["owner_generation"] == ack["request_generation"]
        and ack.get("error_code") is None
        and re.fullmatch(r"[a-f0-9]{64}", ack.get("old_config_sha256") or "")
        is not None
        and re.fullmatch(r"[a-f0-9]{64}", ack.get("new_config_sha256") or "")
        is not None
        and ack.get("worker_binding") == {}
    )


def request_provider_neutral_binding(
    root: Path,
    runtime: Path,
    config_path: Path,
    *,
    timeout_seconds: int | None = None,
) -> dict:
    """Ask the live owner to CAS-clear only the future task's slot/model binding."""
    if os.name != "posix":
        return {
            "ok": False,
            "status": "unavailable",
            "error_code": "private_runtime_unavailable",
        }
    if timeout_seconds is not None and (
        type(timeout_seconds) is not int or not 0 <= timeout_seconds <= 305
    ):
        return {
            "ok": False,
            "status": "unavailable",
            "error_code": "maintenance_binding_timeout_invalid",
        }
    root, runtime, config_path = Path(root), Path(runtime), Path(config_path)
    if (
        config_path.name != "config.json"
        or config_path.parent.resolve() != runtime.resolve()
        or runtime.is_symlink()
        or config_path.is_symlink()
    ):
        return {
            "ok": False,
            "status": "unavailable",
            "error_code": "maintenance_path_unverified",
        }
    try:
        config = load_config(config_path)
        if not config["enabled"]:
            raise ValueError("maintenance_not_activated")
        guard = CanonicalLockGuard(config)
        guard(runtime)
        guard(config_path)
        status = readonly_status(runtime, root=root, config_path=config_path)
        status_path = runtime / "status.json"
        guard(status_path)
        raw_status = json.loads(status_path.read_text(encoding="utf-8"))
        config_bytes = config_path.read_bytes()
        config_sha = _binding_digest(config_bytes)
        generation = status.get("generation")
        if (
            status.get("running") is not True
            or status.get("identity") != "verified"
            or not isinstance(generation, str)
            or re.fullmatch(r"[a-f0-9]{32}", generation) is None
            or raw_status.get("generation") != generation
            or raw_status.get("config_hash") != config_sha
        ):
            return {
                "ok": False,
                "status": "unavailable",
                "error_code": "maintenance_owner_unverified",
            }
        current = validate_config(json.loads(config_bytes.decode("utf-8")))
        desired = dict(current)
        desired["worker_binding"] = {}
        desired_bytes = _configuration_bytes(desired)
        request_path = runtime / "worker-binding.request.json"
        ack_path = runtime / "worker-binding.ack.json"
        guard(request_path)
        guard(ack_path)
        base = {
            "schema": BINDING_REQUEST_SCHEMA,
            "generation": generation,
            "expected_config_sha256": config_sha,
            "old_binding": current["worker_binding"],
            "desired_config": desired,
            "desired_config_sha256": _binding_digest(desired_bytes),
        }
        request = None
        request_bytes = None
        has_request = request_path.exists()
        has_ack = ack_path.exists()
        if has_request and has_ack:
            old_bytes, old_request = _read_private_json(request_path, guard)
            _, old_ack = _read_private_json(ack_path, guard)
            if not _binding_ack_matches(old_ack, old_request, old_bytes):
                raise ValueError("maintenance_binding_receipt_unverified")
            if (
                old_ack["status"] in {"applied", "no_change"}
                and config_sha == old_ack.get("new_config_sha256")
                and current == old_request.get("desired_config")
            ):
                return {
                    "ok": True,
                    "status": old_ack["status"],
                    "applied": old_ack["status"] == "applied",
                    "readback": True,
                    "generation": generation,
                    "config_sha256": config_sha,
                    "worker_binding": current["worker_binding"],
                    "reused_acknowledgement": True,
                }
            _remove_private_json(request_path, guard)
            _remove_private_json(ack_path, guard)
            has_request = has_ack = False
        elif has_request:
            request_bytes, request = _read_private_json(request_path, guard)
            comparable = {key: value for key, value in request.items() if key != "nonce"}
            if (
                comparable != base
                or not isinstance(request.get("nonce"), str)
                or re.fullmatch(r"[a-f0-9]{32}", request["nonce"]) is None
            ):
                return {
                    "ok": False,
                    "status": "unknown",
                    "error_code": "maintenance_binding_request_unresolved",
                    "request_retained": True,
                }
        elif has_ack:
            raise ValueError("maintenance_binding_receipt_unverified")
        if request is None:
            request = {**base, "nonce": uuid4().hex}
            request_bytes = _write_private_json(
                request_path, request, guard, exclusive=True
            )
        timeout = (
            min(305, config["poll_seconds"] + 5)
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = time.monotonic() + timeout
        while True:
            if ack_path.exists():
                _ack_bytes, ack = _read_private_json(ack_path, guard)
                if not _binding_ack_matches(ack, request, request_bytes):
                    return {
                        "ok": False,
                        "status": "unknown",
                        "error_code": "maintenance_binding_ack_unverified",
                        "request_retained": True,
                    }
                if ack["status"] == "rejected":
                    return {
                        "ok": False,
                        "status": "rejected",
                        "error_code": ack.get(
                            "error_code", "maintenance_binding_rejected"
                        ),
                        "request_retained": True,
                    }
                physical_bytes = config_path.read_bytes()
                physical_config = validate_config(
                    json.loads(physical_bytes.decode("utf-8"))
                )
                if (
                    _binding_digest(physical_bytes)
                    != ack.get("new_config_sha256")
                    or physical_config != desired
                    or ack.get("worker_binding") != {}
                ):
                    return {
                        "ok": False,
                        "status": "unknown",
                        "error_code": "maintenance_binding_readback_mismatch",
                        "request_retained": True,
                    }
                return {
                    "ok": True,
                    "status": ack["status"],
                    "applied": ack["status"] == "applied",
                    "readback": True,
                    "generation": generation,
                    "config_sha256": _binding_digest(physical_bytes),
                    "worker_binding": physical_config["worker_binding"],
                }
            if time.monotonic() >= deadline:
                return {
                    "ok": False,
                    "status": "unknown",
                    "error_code": "maintenance_binding_ack_timeout",
                    "request_retained": True,
                }
            time.sleep(0.1)
    except Exception:  # noqa: BLE001 - redact lock, path and receipt failures
        return {
            "ok": False,
            "status": "unavailable",
            "error_code": "maintenance_binding_unavailable",
        }



class MaintenanceRuntime:
    def __init__(
        self,
        root: Path,
        state_db: Path,
        runtime: Path,
        config_path: Path,
        *,
        task_api=None,
        result_reader=None,
        clock=None,
        guard=None,
        task_db=None,
    ):
        self.root, self.state_db, self.runtime, self.config_path = (
            root,
            state_db,
            runtime,
            config_path,
        )
        self.failure_phase = "runtime_init"
        self._failure_owner_generation = None
        self.task_db = Path(task_db) if task_db is not None else None
        self.config = load_config(config_path)
        self.owner_path = config_path.resolve().parent / "owner.lock"
        self.guard = guard or CanonicalLockGuard(self.config)
        if root.resolve() != Path(self.config["protected_roots"][0]).resolve():
            raise ValueError("BACH root must be protected")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stop_event = threading.Event()
        self._owner_thread = None
        self.generation = uuid4().hex
        self.adapter = None
        self.definitions = []
        self.failures = 0
        self.retry_at = None
        if task_api is None or result_reader is None:
            from hub._services.task_lease_client import TaskLeaseClient
            from hub.rheingold import get_lead_config

            from bach_api import task

            if get_lead_config().get("mode") not in {"lead", "isolated"}:
                raise RuntimeError("maintenance_requires_native_task_lead")

            task_api = task_api or task
            result_reader = (
                result_reader
                or TaskLeaseClient.for_task_db(task._connect).task_result_snapshot
            )
        self.dispatcher = DocumentationDispatcher(
            root,
            runtime / "documentation.json",
            task_api,
            result_reader,
            self.guard,
            clock=self.clock,
            binding=self.config["worker_binding"],
        )

    def _executor(self, payload, timeout_seconds):
        try:
            return self._dispatch_job(payload, timeout_seconds)
        except Exception as error:  # native errors may contain private data
            write_failure_receipt(
                self.runtime,
                self.root,
                "documentation_dispatch",
                error,
                self.guard,
                task_db=self.task_db,
                owner_generation=self._failure_owner_generation,
                now=self.clock(),
            )
            print(
                "maintenance failure "
                f"phase=documentation_dispatch exception={maintenance_exception_class(error)}",
                file=sys.stderr,
                flush=True,
            )
            raise

    def _dispatch_job(self, payload, timeout_seconds):
        if timeout_seconds != 60:
            raise ValueError("Invalid documentation job")
        if payload == {"schema": "bach.docs-delta-job.v1"}:
            return self.dispatcher.dispatch()
        for definition in self.definitions:
            if payload == {
                "schema": "bach.docs-routine-job.v1",
                "routine": definition["name"],
            }:
                job_id = "bach.docs.routine." + definition["name"]
                current = self.adapter.store.latest_runs_by_job().get(job_id, {})
                if (
                    current.get("status") != "running"
                    or current.get("claimed_by") != self.adapter.service.worker_id
                ):
                    raise RuntimeError("native_routine_run_unverified")
                return dispatch_routine(
                    self.dispatcher, definition, scheduled_for=current["scheduled_for"]
                )
        raise ValueError("Invalid documentation job")

    def _prepare(self):
        self.guard(self.state_db)
        from gui.daemon_identity import observe_identity

        old = observe_identity(
            self.root / "system/data/daemon.pid", self.root / "system"
        )
        if old["identity"] != "stopped":
            raise RuntimeError("legacy_scheduler_not_confirmed_stopped")
        self.definitions = routine_definitions(self.root, self.clock())
        adapter = create_documentation_scheduler(
            self.state_db,
            self._executor,
            worker_id=f"maintenance:{socket.gethostname()}:{os.getpid()}",
        )
        jobs = [row for row in adapter.store.list_jobs() if row["id"] == JOB_ID]
        expected = {"kind": "interval", "seconds": self.config["interval_seconds"]}
        payload = {"schema": "bach.docs-delta-job.v1"}
        if jobs:
            row = jobs[0]
            if (
                json.loads(row["schedule_json"]) != expected
                or row["executor"] != "bach-docs"
                or json.loads(row["payload_json"]) != payload
                or row["timeout_seconds"] != 60
            ):
                raise RuntimeError("existing_maintenance_job_conflict")
        else:
            self.guard(self.state_db)
            adapter.store.add_job(
                JOB_ID,
                expected,
                "bach-docs",
                payload,
                now=self.clock(),
                next_due_at=self.clock(),
                lease_seconds=180,
                timeout_seconds=60,
            )
        cache = read_state(self.dispatcher.state_path).get("routines", {})
        from datetime import timedelta

        for definition in self.definitions:
            job_id = "bach.docs.routine." + definition["name"]
            expected = {"kind": "interval", "seconds": definition["seconds"]}
            payload = {
                "schema": "bach.docs-routine-job.v1",
                "routine": definition["name"],
            }
            jobs = [row for row in adapter.store.list_jobs() if row["id"] == job_id]
            if jobs:
                row = jobs[0]
                if (
                    json.loads(row["schedule_json"]) != expected
                    or row["executor"] != "bach-docs"
                    or json.loads(row["payload_json"]) != payload
                    or row["timeout_seconds"] != 60
                    or bool(row["enabled"]) != definition["enabled"]
                ):
                    raise RuntimeError("existing_maintenance_job_conflict")
            else:
                old = cache.get(definition["name"])
                due = (
                    (
                        datetime.fromisoformat(old["dispatched_at"])
                        + timedelta(seconds=definition["seconds"])
                    )
                    if old
                    else definition["next_due_at"]
                )
                self.guard(self.state_db)
                adapter.store.add_job(
                    job_id,
                    expected,
                    "bach-docs",
                    payload,
                    now=self.clock(),
                    next_due_at=due,
                    enabled=definition["enabled"],
                    lease_seconds=180,
                    timeout_seconds=60,
                )
        self.adapter = adapter
        # Recover failure backoff from native receipts, including across restart.
        history = [
            row
            for row in adapter.store.recent_runs(limit=30)
            if row["job_id"] in JOB_IDS and row.get("finished_at")
        ]
        history.sort(
            key=lambda row: (
                datetime.fromisoformat(row["finished_at"]),
                row["status"] in {"failed", "timed_out"},
            ),
            reverse=True,
        )
        failures = []
        for row in history:
            if row["status"] not in {"failed", "timed_out"}:
                break
            failures.append(row)
        if failures:
            self.failures = min(len(failures), 6)
            ended = datetime.fromisoformat(failures[0]["finished_at"])
            self.retry_at = ended + timedelta(
                seconds=min(3600, 60 * 2 ** (self.failures - 1))
            )

    def tick(self) -> dict:
        if not self.config["enabled"]:
            raise RuntimeError("maintenance_not_activated")
        if self._owner_thread == threading.get_ident():
            self.failure_phase = "scheduler_tick"
            return self._tick()
        self.failure_phase = "owner_acquire"
        with process_owner(self.owner_path, self.guard):
            self._failure_owner_generation = self.generation
            self._owner_thread = threading.get_ident()
            self.failure_phase = "scheduler_tick"
            try:
                return self._tick()
            finally:
                self._owner_thread = None

    def _tick(self) -> dict:
        self.guard(self.state_db)
        import psutil

        files = [
            self.state_db,
            Path(str(self.state_db) + "-wal"),
            Path(str(self.state_db) + "-shm"),
        ]
        if (
            sum(path.stat().st_size for path in files if path.exists())
            > self.config["max_state_db_bytes"]
        ):
            return {"state": "storage_budget", "runs": []}
        if (
            psutil.virtual_memory().available
            < self.config["min_available_mib"] * 1048576
        ):
            return {"state": "busy", "runs": []}
        parent = self.runtime
        while not parent.exists():
            parent = parent.parent
        if psutil.disk_usage(parent).free < max(
            67108864, self.config["max_state_db_bytes"] * 2
        ):
            return {"state": "storage_reserve", "runs": []}
        if self.retry_at is not None and self.clock() < self.retry_at:
            return {"state": "backoff", "runs": []}
        if self.adapter is None:
            self._prepare()
        if self.retry_at is not None and self.clock() < self.retry_at:
            return {"state": "backoff", "runs": []}
        # Other imported jobs keep their definitions; this owner never starts them.
        job_ids = [
            JOB_ID,
            *["bach.docs.routine." + value["name"] for value in self.definitions],
        ]
        runs = self.adapter.service.tick(now=self.clock(), limit=1, job_ids=job_ids)
        if any(row.get("status") != "succeeded" for row in runs):
            from datetime import timedelta

            self.failures = min(self.failures + 1, 6)
            self.retry_at = self.clock() + timedelta(
                seconds=min(3600, 60 * 2 ** (self.failures - 1))
            )
        elif runs:
            self.failures, self.retry_at = 0, None
        return {"state": "running", "runs": runs}

    def job_receipts(self):
        if self.adapter is None:
            return []
        # Native store is consulted only by the owner, never by the read-only API.
        latest = self.adapter.store.latest_runs_by_job()
        return [
            {
                "id": row["id"],
                "enabled": bool(row["enabled"]),
                "next_due_at": row["next_due_at"],
                "last_success": latest.get(row["id"], {}).get("finished_at")
                if latest.get(row["id"], {}).get("status") == "succeeded"
                else None,
            }
            for row in self.adapter.store.list_jobs()
            if row["id"].startswith("bach.docs.")
        ]

    def run_receipts(self):
        if self.adapter is None:
            return []
        fields = (
            "run_id",
            "job_id",
            "status",
            "started_at",
            "finished_at",
            "exit_code",
        )
        return [
            {key: row[key] for key in fields if key in row}
            for row in self.adapter.store.recent_runs(limit=30)
            if row["job_id"] in JOB_IDS
        ][:5]

    def _consume_provider_neutral_request(self):
        if (
            os.name != "posix"
            or self._owner_thread != threading.get_ident()
            or self._failure_owner_generation != self.generation
        ):
            return False
        request_path = self.runtime / "worker-binding.request.json"
        ack_path = self.runtime / "worker-binding.ack.json"
        if not request_path.exists():
            return False
        raw_request, request = _read_private_json(request_path, self.guard)
        request_sha = _binding_digest(raw_request)
        if ack_path.exists():
            _, existing_ack = _read_private_json(ack_path, self.guard)
            if _binding_ack_matches(existing_ack, request, raw_request):
                return False
            return False

        nonce = request.get("nonce")
        request_generation = request.get("generation")
        if (
            not isinstance(nonce, str)
            or re.fullmatch(r"[a-f0-9]{32}", nonce) is None
            or not isinstance(request_generation, str)
            or re.fullmatch(r"[a-f0-9]{32}", request_generation) is None
        ):
            return False

        def acknowledge(status, error_code, old_sha, new_sha, binding):
            ack = {
                "schema": BINDING_ACK_SCHEMA,
                "nonce": nonce,
                "request_generation": request_generation,
                "owner_generation": self.generation,
                "request_sha256": request_sha,
                "status": status,
                "error_code": error_code,
                "old_config_sha256": old_sha,
                "new_config_sha256": new_sha,
                "worker_binding": binding,
                "observed_at": stamp(self.clock()),
            }
            _write_private_json(ack_path, ack, self.guard, exclusive=True)

        required = {
            "schema",
            "nonce",
            "generation",
            "expected_config_sha256",
            "old_binding",
            "desired_config",
            "desired_config_sha256",
        }
        if set(request) != required or request.get("schema") != BINDING_REQUEST_SCHEMA:
            acknowledge(
                "rejected",
                "maintenance_binding_request_invalid",
                None,
                None,
                None,
            )
            return True
        try:
            desired = validate_config(request["desired_config"])
            old_binding = request["old_binding"]
            expected_sha = request["expected_config_sha256"]
            desired_sha = request["desired_config_sha256"]
            if (
                not isinstance(old_binding, dict)
                or set(old_binding) - {"assigned_slot", "required_model"}
                or any(
                    not isinstance(value, str) or not value.strip() or len(value) > 128
                    for value in old_binding.values()
                )
                or desired["worker_binding"] != {}
                or re.fullmatch(r"[a-f0-9]{64}", expected_sha or "") is None
                or re.fullmatch(r"[a-f0-9]{64}", desired_sha or "") is None
                or _binding_digest(_configuration_bytes(desired)) != desired_sha
            ):
                raise ValueError("Invalid provider-neutral request")
        except (TypeError, ValueError):
            acknowledge(
                "rejected",
                "maintenance_binding_request_invalid",
                request.get("expected_config_sha256"),
                None,
                None,
            )
            return True

        current_bytes = self.config_path.read_bytes()
        current_sha = _binding_digest(current_bytes)
        try:
            current = validate_config(json.loads(current_bytes.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            acknowledge(
                "rejected",
                "maintenance_configuration_unavailable",
                expected_sha,
                current_sha,
                None,
            )
            return True
        if request_generation != self.generation:
            acknowledge(
                "rejected",
                "maintenance_generation_conflict",
                expected_sha,
                current_sha,
                current.get("worker_binding"),
            )
            return True
        if (
            {
                key: value
                for key, value in desired.items()
                if key != "worker_binding"
            }
            != {
                key: value
                for key, value in current.items()
                if key != "worker_binding"
            }
            or desired["worker_binding"] != {}
        ):
            acknowledge(
                "rejected",
                "maintenance_binding_conflict",
                expected_sha,
                current_sha,
                current.get("worker_binding"),
            )
            return True
        if current_sha == desired_sha and current == desired:
            prior_binding = self.config.get("worker_binding")
            same_prior = (
                prior_binding == old_binding
                and {
                    key: value
                    for key, value in self.config.items()
                    if key != "worker_binding"
                }
                == {
                    key: value
                    for key, value in desired.items()
                    if key != "worker_binding"
                }
            )
            if self.config != desired and not same_prior:
                acknowledge(
                    "rejected",
                    "maintenance_configuration_conflict",
                    expected_sha,
                    current_sha,
                    current.get("worker_binding"),
                )
                return True
            new_config = current
            status = "applied" if self.config != desired else "no_change"
        elif (
            current_sha == expected_sha
            and current == self.config
            and current.get("worker_binding") == old_binding
        ):
            if current == desired:
                new_config = current
                status = "no_change"
            else:
                new_bytes = _configuration_bytes(desired)
                mode = stat.S_IMODE(self.config_path.stat().st_mode)
                _atomic_write_bytes(
                    self.config_path,
                    new_bytes,
                    self.guard,
                    mode=mode,
                    expected_existing=current_bytes,
                )
                physical = self.config_path.read_bytes()
                new_config = validate_config(json.loads(physical.decode("utf-8")))
                if physical != new_bytes or new_config != desired:
                    raise RuntimeError("maintenance_binding_readback_mismatch")
                status = "applied"
        else:
            acknowledge(
                "rejected",
                "maintenance_configuration_conflict",
                expected_sha,
                current_sha,
                current.get("worker_binding"),
            )
            return True
        self.config = new_config
        self.dispatcher.binding = dict(new_config["worker_binding"])
        acknowledge(
            status,
            None,
            expected_sha,
            _binding_digest(self.config_path.read_bytes()),
            self.config["worker_binding"],
        )
        return True

    def serve(self, *, max_ticks=None):
        self.failure_phase = "serve"
        import psutil

        if not self.config["enabled"]:
            raise RuntimeError("maintenance_not_activated")
        self._failure_owner_generation = None
        self.failure_phase = "owner_acquire"
        with process_owner(self.owner_path, self.guard):
            self._failure_owner_generation = self.generation
            self._owner_thread = threading.get_ident()
            count = 0
            current = None
            try:
                while not self.stop_event.is_set():
                    self.failure_phase = "binding_request"
                    self._consume_provider_neutral_request()
                    self.failure_phase = "config_reload"
                    config = load_config(self.config_path)
                    if config != self.config:
                        raise RuntimeError(
                            "maintenance_configuration_changed_restart_required"
                        )
                    self.failure_phase = "scheduler_tick"
                    result = self.tick()
                    current = {
                        "schema": STATUS_SCHEMA,
                        "pid": os.getpid(),
                        "service": "bach-docs-maintenance",
                        "root_id": hashlib.sha256(
                            str(self.root.resolve()).encode()
                        ).hexdigest(),
                        "config_hash": hashlib.sha256(
                            self.config_path.read_bytes()
                        ).hexdigest(),
                        "create_time": psutil.Process().create_time(),
                        "generation": self.generation,
                        "poll_seconds": self.config["poll_seconds"],
                        "observed_at": stamp(self.clock()),
                        "provider": "ellmos-scheduler",
                        "state": result["state"],
                        "runs": self.run_receipts(),
                        "semantic_review_completed": False,
                        "documentation": read_state(
                            self.runtime / "documentation.json"
                        ),
                        "jobs": self.job_receipts(),
                    }
                    self.failure_phase = "status_write"
                    _write_status(self.runtime / "status.json", current, self.guard)
                    count += 1
                    if max_ticks is not None and count >= max_ticks:
                        break
                    self.failure_phase = "poll_wait"
                    self.stop_event.wait(self.config["poll_seconds"])
            finally:
                self._owner_thread = None
                failed_phase = self.failure_phase
                primary_active = sys.exc_info()[0] is not None
                if current is not None:
                    current.update(state="stopped", observed_at=stamp(self.clock()))
                    self.failure_phase = "shutdown_status_write"
                    try:
                        _write_status(
                            self.runtime / "status.json", current, self.guard
                        )
                    except Exception:
                        if not primary_active:
                            raise
                self.failure_phase = failed_phase if primary_active else "serve"
