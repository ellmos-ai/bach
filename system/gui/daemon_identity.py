"""Read-only identity proof for the local scheduler daemon.

The legacy numeric PID file alone never proves ownership. The sidecar is
written only by DaemonService.run and never returned to API clients.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SCHEMA = "bach-daemon-identity.v1"
SERVICE = "bach-scheduler-daemon"
MAX_BYTES = 1024


def identity_path(pid_file: Path) -> Path:
    return pid_file.with_suffix(".identity.json")


def _root_id(bach_root: Path) -> str:
    return hashlib.sha256(str(bach_root.resolve(strict=True)).encode("utf-8")).hexdigest()


def make_identity(pid_file: Path, bach_root: Path, owner_kind: str) -> dict:
    if owner_kind not in {"gui", "standalone"}:
        raise ValueError("invalid_owner_kind")
    import psutil
    process = psutil.Process(os.getpid())
    return {
        "schema": SCHEMA,
        "service": SERVICE,
        "pid": process.pid,
        "create_time": process.create_time(),
        "root_id": _root_id(bach_root),
        "owner_kind": owner_kind,
    }


def observe_identity(pid_file: Path, bach_root: Path, local_service=None) -> dict:
    """No subprocess or filesystem mutation; GUI ownership also needs a live object."""
    result = {"running": False, "identity": "unknown", "reason": "legacy_pid_unverified",
              "pid": None, "control_available": False}
    try:
        if not pid_file.exists() and not identity_path(pid_file).exists():
            return {**result, "identity": "stopped", "reason": "no_process_record"}
        if not pid_file.exists() or not identity_path(pid_file).exists():
            return result
        if identity_path(pid_file).stat().st_size > MAX_BYTES:
            return {**result, "reason": "identity_invalid"}
        data = json.loads(identity_path(pid_file).read_text(encoding="utf-8"))
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if not (data.get("schema") == SCHEMA and data.get("service") == SERVICE
                and data.get("pid") == pid and isinstance(data.get("create_time"), (int, float))
                and data.get("root_id") == _root_id(bach_root)
                and data.get("owner_kind") in {"gui", "standalone"}):
            return {**result, "reason": "identity_mismatch"}
        import psutil
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return {**result, "reason": "process_not_running"}
        if abs(process.create_time() - float(data["create_time"])) > 0.001:
            return {**result, "reason": "birthtime_mismatch"}
        if data["owner_kind"] == "gui":
            if (pid != os.getpid() or local_service is None
                    or not local_service.running or local_service._shutdown_event.is_set()):
                return {**result, "reason": "gui_service_not_observed"}
            control = True
        else:
            canonical = (bach_root / "gui" / "daemon_service.py").resolve(strict=True)
            if not any(Path(arg).resolve(strict=False) == canonical
                       for arg in process.cmdline() if str(arg).endswith("daemon_service.py")):
                return {**result, "reason": "standalone_command_mismatch"}
            control = False
        return {"running": True, "identity": "verified", "reason": "process_identity_observed",
                "pid": pid, "control_available": control}
    except Exception:
        # psutil raises process-specific errors on races and access denial.
        return {**result, "reason": "identity_unavailable"}
