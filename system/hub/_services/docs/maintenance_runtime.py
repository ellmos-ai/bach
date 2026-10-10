"""One process owner consuming ellmos-scheduler's native due/claim/run engine."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
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
from .maintenance_recurring import ROUTINES, dispatch_routine, routine_definitions

CONFIG_SCHEMA = "bach.maintenance-config.v1"
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
    empty = {
        "schema": STATUS_SCHEMA,
        "running": False,
        "identity": "unknown",
        "reason": "no_maintenance_receipt",
        "semantic_review_completed": False,
    }
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
        return {
            **public,
            "running": live,
            "identity": "verified" if live else "unverified",
            "age_seconds": max(0, int(age)),
            "reason": "process_and_heartbeat" if live else "receipt_not_current",
        }
    except Exception:  # noqa: BLE001 - fail closed across optional process implementations
        return {**empty, "reason": "maintenance_receipt_unverified"}


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
    ):
        self.root, self.state_db, self.runtime, self.config_path = (
            root,
            state_db,
            runtime,
            config_path,
        )
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
            return self._tick()
        with process_owner(self.owner_path, self.guard):
            self._owner_thread = threading.get_ident()
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

    def serve(self, *, max_ticks=None):
        import psutil

        if not self.config["enabled"]:
            raise RuntimeError("maintenance_not_activated")
        with process_owner(self.owner_path, self.guard):
            self._owner_thread = threading.get_ident()
            count = 0
            current = None
            try:
                while not self.stop_event.is_set():
                    config = load_config(self.config_path)
                    if config != self.config:
                        raise RuntimeError(
                            "maintenance_configuration_changed_restart_required"
                        )
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
                    _write_status(self.runtime / "status.json", current, self.guard)
                    count += 1
                    if max_ticks is not None and count >= max_ticks:
                        break
                    self.stop_event.wait(self.config["poll_seconds"])
            finally:
                self._owner_thread = None
                if current is not None:
                    current.update(state="stopped", observed_at=stamp(self.clock()))
                    _write_status(self.runtime / "status.json", current, self.guard)
