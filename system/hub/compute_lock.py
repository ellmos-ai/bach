#!/usr/bin/env python3
"""
Compute Lock Integration
=========================

Checks whether compute jobs are running before loading Ollama models.
Provides SIGSTOP/SIGCONT management and crash recovery.

Lock-file: ~/.memwatchdog/compute_active.lock (JSON with PIDs, RSS, command)
  Override via env BACH_COMPUTE_LOCK_PATH or the bot config (compute_lock.lock_path).
Check-script (optional): a script that exits 0 = free, 1 = active (JSON on stdout).
  Override via env BACH_COMPUTE_CHECK_SCRIPT or the bot config (compute_lock.check_script).
  Without it the lock file alone is used.
Fackel-preference: system/data/fackel_preference.json
  Override via env BACH_FACKEL_PREFERENCE_PATH. Legacy: ~/.memwatchdog/fackel_preference.json.

Usage:
    from hub.compute_lock import check_compute_active, pause_compute_jobs
    active, status = check_compute_active()
"""
import json
import logging
import math
import os
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional, Tuple

log = logging.getLogger("bach.compute_lock")

# Default paths (overridden by env or config)
DEFAULT_LOCK_PATH = os.environ.get(
    "BACH_COMPUTE_LOCK_PATH", "~/.memwatchdog/compute_active.lock")
# Candidates for the optional negotiation script. Site-specific queues set their
# own path via env/config; the generic candidate lives next to the lock file.
_CHECK_SCRIPT_CANDIDATES = [
    os.environ.get("BACH_COMPUTE_CHECK_SCRIPT", ""),
    "~/.memwatchdog/check_compute_active.sh",
]
PAUSED_PIDS_FILE = "~/.memwatchdog/bot_paused_pids.json"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FACKEL_PREFERENCE_LEGACY_FILE = "~/.memwatchdog/fackel_preference.json"
_FACKEL_PATH_FROM_ENV = "BACH_FACKEL_PREFERENCE_PATH" in os.environ
FACKEL_PREFERENCE_FILE = os.environ.get(
    "BACH_FACKEL_PREFERENCE_PATH", str(_DATA_DIR / "fackel_preference.json")
)
FACKEL_COMPUTE = "compute"
FACKEL_OLLAMA = "ollama"
VALID_FACKEL_PREFERENCES = (FACKEL_COMPUTE, FACKEL_OLLAMA)



def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path))


def _resolve_check_script() -> str:
    """Return the first existing candidate; queue layouts differ per machine."""
    for cand in _CHECK_SCRIPT_CANDIDATES:
        if cand and _expand(cand).is_file():
            return cand
    return _CHECK_SCRIPT_CANDIDATES[-1]


DEFAULT_CHECK_SCRIPT = _resolve_check_script()


def check_compute_active(
    lock_path: str = DEFAULT_LOCK_PATH,
    check_script: str = DEFAULT_CHECK_SCRIPT,
) -> Tuple[bool, dict]:
    """Check if compute jobs are running.

    Strategy: try check_script first; fall back to direct lock-file read.
    After reading, filters out already-stopped PIDs (state T) to avoid
    re-asking for jobs we already paused.
    Returns (is_active, status_dict). Graceful degradation: returns (False, {})
    if neither script nor lock file is available.
    """
    script = _expand(check_script)
    if script.is_file():
        try:
            result = subprocess.run(
                [str(script)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return False, {}
            # returncode 1 = active
            try:
                status = json.loads(result.stdout.strip())
            except (json.JSONDecodeError, ValueError):
                status = {"raw": result.stdout.strip()}
            return _filter_stopped_jobs(status)
        except (subprocess.TimeoutExpired, OSError) as e:
            log.warning("check_compute_active script failed: %s", e)

    # Fallback: read lock file directly
    lock = _expand(lock_path)
    if not lock.is_file():
        return False, {}

    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        return _filter_stopped_jobs(data)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not read lock file %s: %s", lock, e)
        return False, {}


def _pid_is_manageable(pid: int) -> bool:
    """Probe process existence/access without sending a signal on Windows.

    Windows does not provide the POSIX signal-zero existence probe.
    Use psutil, already required by BACH, without a signal or mutation.
    """
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        import psutil

        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _filter_stopped_jobs(status: dict) -> Tuple[bool, dict]:
    """Filter out PIDs that are already stopped (state T), gone, or unmanageable.

    The watchdog may keep stopped PIDs in the lock file. We only care
    about running ones to avoid asking the user to pause already-paused jobs.
    Processes we have no permission to signal (e.g. system daemons) or that
    are already dead are also filtered out.
    """
    jobs = status.get("active_compute_jobs", [])
    if not jobs:
        return False, {}

    running = []
    for job in jobs:
        pid = job.get("pid")
        if not pid:
            running.append(job)
            continue
        # If process cannot be signaled by current user or is gone, skip
        if not _pid_is_manageable(pid):
            log.debug("Skipping PID %s (%s): gone or inaccessible", pid, job.get("name", "?"))
            continue

        # Check live state if lock file reports a state
        if _pid_is_stopped(pid):
            log.debug("Skipping PID %d (already stopped)", pid)
            continue
        running.append(job)

    if not running:
        return False, {}

    filtered = dict(status)
    filtered["active_compute_jobs"] = running
    return True, filtered


_PAUSE_SCHEMA = "bach.compute-pauses.v2"
_PAUSE_STATES = {"paused", "pause_unconfirmed", "resume_unconfirmed",
                 "identity_unverified", "legacy_unverified"}
_PAUSE_MAX_BYTES = 131072
_PROCESS_STATE_WAIT_SECONDS = 1.0


class _PausedJobs(list):
    """Preserve the public PID-list contract while binding the originating pause."""
    def __init__(self, pids=(), receipts=()):
        super().__init__(pids)
        self.pause_receipts = tuple(dict(receipt) for receipt in receipts)


class ComputePauseError(RuntimeError):
    """Pause admission failed; confirmed own partial pauses remain recoverable."""
    def __init__(self, reason: str, paused_pids=None):
        self.reason = reason
        self.paused_pids = paused_pids if isinstance(paused_pids, _PausedJobs) else _PausedJobs()
        super().__init__(f"compute_pause_unconfirmed:{reason}")


def has_pending_compute_pauses() -> bool:
    try:
        _expand(PAUSED_PIDS_FILE).lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True  # unreadable evidence is not proof of an empty pause set


def _pause_identity(record: dict) -> dict:
    return {key: record[key] for key in ("pid", "create_time", "pause_id")}


def _read_paused_records(path: Path) -> list[dict]:
    """Read owned identities; legacy PIDs never become signal authority."""
    if path.is_symlink():
        raise ValueError("linked_pause_receipt")
    try:
        with path.open("rb") as handle:
            raw = handle.read(_PAUSE_MAX_BYTES + 1)
    except FileNotFoundError:
        return []
    if len(raw) > _PAUSE_MAX_BYTES:
        raise ValueError("pause_receipt_too_large")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_pause_field")
            value[key] = item
        return value

    def invalid(_value):
        raise ValueError("invalid_pause_number")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("invalid_pause_receipt")
    pids = value.get("paused_pids")
    if (not isinstance(pids, list) or len(pids) > 256
            or any(type(pid) is not int or pid <= 0 for pid in pids)
            or len(pids) != len(set(pids))):
        raise ValueError("invalid_paused_pids")
    if "schema" not in value:
        return [{"pid": pid, "state": "legacy_unverified"} for pid in pids]
    if value.get("schema") != _PAUSE_SCHEMA or value.get("source") != "bach_telegram_bot":
        raise ValueError("unknown_pause_receipt")
    records = value.get("processes")
    if not isinstance(records, list) or len(records) != len(pids):
        raise ValueError("invalid_process_records")
    for pid, record in zip(pids, records):
        if (not isinstance(record, dict) or type(record.get("pid")) is not int
                or record["pid"] != pid or record.get("state") not in _PAUSE_STATES):
            raise ValueError("invalid_process_record")
        expected = {"pid", "state"} if record["state"] == "legacy_unverified" else {
            "pid", "state", "create_time", "pause_id"}
        if set(record) != expected:
            raise ValueError("invalid_process_identity")
        if "create_time" in record:
            created = record["create_time"]
            if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
                raise ValueError("invalid_process_birth")
            pause_id = record["pause_id"]
            if (not isinstance(pause_id, str) or len(pause_id) != 32
                    or any(char not in "0123456789abcdef" for char in pause_id)):
                raise ValueError("invalid_pause_identity")
    return [dict(record) for record in records]


def _sync_pause_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_paused_records(path: Path, records: list[dict]) -> None:
    """Persist an effect intent before signalling; never discard unresolved PIDs."""
    if path.is_symlink():
        raise ValueError("linked_pause_receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.unlink(missing_ok=True)
        _sync_pause_directory(path.parent)
        return
    value = {"schema": _PAUSE_SCHEMA, "source": "bach_telegram_bot",
             "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "paused_pids": [record["pid"] for record in records], "processes": records,
             "manual_review_required": any(record["state"] != "paused" for record in records)}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_pause_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _process_for_pause_record(record: dict):
    import psutil

    if record["pid"] == os.getpid():
        raise ValueError("self_process_refused")
    process = psutil.Process(record["pid"])
    created = process.create_time()
    if (not process.is_running() or type(created) not in (int, float)
            or not math.isfinite(created)
            or abs(created - record["create_time"]) >= .001):
        raise ValueError("process_identity_changed")
    return process


def _verified_process_status(process):
    import psutil

    status = process.status()
    known = {value for name, value in vars(psutil).items()
             if name.startswith("STATUS_") and isinstance(value, str)}
    if not isinstance(status, str) or status not in known:
        raise ValueError("process_state_unknown")
    return status


def _confirm_process_state(record: dict, *, stopped: bool) -> bool:
    import psutil

    deadline = time.monotonic() + _PROCESS_STATE_WAIT_SECONDS
    while True:
        try:
            process = _process_for_pause_record(record)
            status = _verified_process_status(process)
        except psutil.NoSuchProcess:
            return not stopped  # after SIGCONT, an exited original no longer needs recovery
        if status in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
            return not stopped
        if status == psutil.STATUS_TRACING_STOP:
            return False
        if (status == psutil.STATUS_STOPPED) is stopped:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(.01)


def pause_compute_jobs(status: dict) -> List[int]:
    """Confirm every needed pause or raise with only confirmed partial ownership."""
    import psutil
    from hub._services.user_config_store import _exclusive_lock

    paused, identities = [], []

    def refuse(reason):
        log.warning("compute_pause_deferred reason=%s confirmed_pauses=%d", reason, len(paused))
        raise ComputePauseError(reason, _PausedJobs(paused, identities))

    if not hasattr(signal, "SIGSTOP") or not hasattr(signal, "SIGCONT"):
        refuse("unsupported_platform")
    jobs = status.get("active_compute_jobs") if isinstance(status, dict) else None
    if not isinstance(jobs, list) or len(jobs) > 256:
        refuse("invalid_compute_status")
    seen = set()
    for job in jobs:
        pid = job.get("pid") if isinstance(job, dict) else None
        if type(pid) is not int or pid <= 0 or pid == os.getpid() or pid in seen:
            refuse("invalid_compute_pid")
        seen.add(pid)
    if not jobs:
        return _PausedJobs()

    path = _expand(PAUSED_PIDS_FILE)
    try:
        with _exclusive_lock(path):
            records = _read_paused_records(path)
            for job in jobs:
                pid = job["pid"]
                if any(record["pid"] == pid for record in records):
                    refuse("existing_pause_unresolved")
                if len(records) >= 256:
                    refuse("receipt_capacity")
                try:
                    process = psutil.Process(pid)
                    created = process.create_time()
                    if (not process.is_running() or type(created) not in (int, float)
                            or not math.isfinite(created) or created <= 0):
                        refuse("process_identity_unverified")
                    state = _verified_process_status(process)
                    if state in {psutil.STATUS_STOPPED, psutil.STATUS_TRACING_STOP}:
                        refuse("process_already_stopped")
                    if state in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                        continue
                except psutil.NoSuchProcess:
                    continue  # this declared job is confirmed gone
                except ComputePauseError:
                    raise
                except Exception:
                    refuse("process_identity_unverified")
                record = {"pid": pid, "create_time": created,
                          "pause_id": uuid.uuid4().hex, "state": "pause_unconfirmed"}
                records.append(record)
                try:
                    _write_paused_records(path, records)
                except Exception:
                    refuse("pause_intent_unrecorded")
                try:
                    _process_for_pause_record(record).send_signal(signal.SIGSTOP)
                    if not _confirm_process_state(record, stopped=True):
                        refuse("pause_state_unconfirmed")
                except ComputePauseError:
                    raise
                except Exception:
                    refuse("pause_signal_unconfirmed")
                record["state"] = "paused"
                try:
                    _write_paused_records(path, records)
                except Exception:
                    refuse("pause_confirmation_unrecorded")
                paused.append(pid)
                identities.append(_pause_identity(record))
                log.info("compute_pause_confirmed pid=%d", pid)
    except ComputePauseError:
        raise
    except Exception:
        refuse("pause_receipt_unavailable")
    return _PausedJobs(paused, identities)


def _resume_owned_jobs(selected_pids: List[int] | None, *, expected_receipts=None) -> List[int]:
    import psutil
    from hub._services.user_config_store import _exclusive_lock

    if not hasattr(signal, "SIGCONT"):
        log.warning("compute_resume_deferred reason=unsupported_platform")
        return []
    path = _expand(PAUSED_PIDS_FILE)
    resumed = []
    try:
        with _exclusive_lock(path):
            records = _read_paused_records(path)
            had_records = bool(records)
            selected = {record["pid"] for record in records} if selected_pids is None else {
                pid for pid in selected_pids if type(pid) is int and pid > 0}
            for record in list(records):
                pid = record["pid"]
                if pid not in selected:
                    continue
                if expected_receipts is not None and not any(
                        isinstance(expected, dict) and set(expected) == {"pid", "create_time", "pause_id"}
                        and all(record.get(key) == value for key, value in expected.items())
                        for expected in expected_receipts):
                    log.warning("compute_resume_deferred pid=%d reason=pause_receipt_changed", pid)
                    continue
                if record["state"] not in {"paused", "resume_unconfirmed"}:
                    log.warning("compute_resume_deferred pid=%d reason=%s manual_review_required=true",
                                pid, record["state"])
                    continue
                try:
                    process = _process_for_pause_record(record)
                    status = _verified_process_status(process)
                    if status == psutil.STATUS_TRACING_STOP:
                        raise ValueError("process_traced")
                except psutil.NoSuchProcess:
                    records.remove(record)  # original process is confirmed gone; send no signal
                    _write_paused_records(path, records)
                    continue
                except Exception as error:
                    record["state"] = "identity_unverified"
                    _write_paused_records(path, records)
                    log.warning("compute_resume_deferred pid=%d reason=%s manual_review_required=true",
                                pid, type(error).__name__)
                    continue
                if status != psutil.STATUS_STOPPED:
                    records.remove(record)  # already resumed/ended; do not send SIGCONT again
                    _write_paused_records(path, records)
                    continue
                if record["state"] == "resume_unconfirmed":
                    log.warning("compute_resume_deferred pid=%d reason=resume_unconfirmed manual_review_required=true",
                                pid)
                    continue
                record["state"] = "resume_unconfirmed"
                _write_paused_records(path, records)
                try:
                    # psutil rechecks PID reuse at the signal boundary.
                    process.send_signal(signal.SIGCONT)
                    if not _confirm_process_state(record, stopped=False):
                        raise RuntimeError("resume_state_unconfirmed")
                    resumed.append(pid)
                    records.remove(record)
                    _write_paused_records(path, records)
                    log.info("compute_resume_confirmed pid=%d", pid)
                except Exception as error:
                    log.warning("compute_resume_deferred pid=%d reason=%s manual_review_required=true",
                                pid, type(error).__name__)
            if had_records and not path.exists():
                delete_session_flag()
    except Exception as error:
        log.warning("compute_resume_deferred reason=%s receipt_preserved=true", type(error).__name__)
    return resumed


def resume_compute_jobs(paused_pids: List[int]) -> List[int]:
    """Explicit resume: only confirmed own pause identities authorize SIGCONT."""
    expected = paused_pids.pause_receipts if isinstance(paused_pids, _PausedJobs) else None
    return _resume_owned_jobs(paused_pids, expected_receipts=expected)


def _pid_is_stopped(pid: int) -> bool:
    """Check if a PID exists and is in stopped state (T)."""
    if os.name == "nt":
        return False  # POSIX stopped state does not exist on Windows.
    try:
        result = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True, text=True, timeout=3,
        )
        state = result.stdout.strip()
        return "T" in state
    except (subprocess.TimeoutExpired, OSError):
        return False


def recover_paused_jobs(ollama_url: str = "http://localhost:11434",
                        paused_pids: List[int] | None = None) -> List[int]:
    """Automatic recovery requires empty Ollama and confirmed own identities.

    A partial-pause caller supplies its bound PID list; startup may reconcile
    all owned receipts. An explicitly empty list never adopts other pauses.
    """
    if paused_pids is not None and not paused_pids:
        return []
    if not has_pending_compute_pauses():
        return []
    loaded = _check_model_loaded(ollama_url)
    if loaded is not False:
        reason = "ollama_state_unknown" if loaded is None else "model_resident"
        log.warning("compute_recovery_deferred reason=%s receipt_preserved=true", reason)
        return []
    return (_resume_owned_jobs(None) if paused_pids is None
            else resume_compute_jobs(paused_pids))


SESSION_FLAG_PATH = "~/.memwatchdog/user_session_active.flag"


def get_effective_keep_alive(default: str = "5m") -> str:
    """Adaptive keep_alive: 5m when compute exists (running or paused), 30m otherwise."""
    if has_pending_compute_pauses():
        return "5m"
    try:
        is_active, _ = check_compute_active()
        return "5m" if is_active else "30m"
    except Exception:
        return default


_KA_MAP = {"5m": 300, "30m": 1800}


def get_effective_keep_alive_seconds() -> int:
    return _KA_MAP.get(get_effective_keep_alive(), 300)


def set_inferenz_active(active: bool) -> None:
    """Set model_active_inferenz in session flag (called around LLM calls)."""
    path = _expand(SESSION_FLAG_PATH)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["model_active_inferenz"] = active
        data["timestamp_last_request"] = int(time.time())
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to set inferenz flag: %s", e)


def write_session_flag(chat_id: str, model_name: str,
                       effective_keep_alive_seconds: int = 300) -> None:
    """Write/update user_session_active.flag for Watchdog cross-signal."""
    path = _expand(SESSION_FLAG_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "timestamp_last_request": int(time.time()),
            "effective_keep_alive_seconds": effective_keep_alive_seconds,
            "model_active_inferenz": False,
            "chat_id": chat_id,
            "model_name": model_name,
        }, indent=2), encoding="utf-8")
    except OSError as e:
        log.error("Failed to write session flag: %s", e)


def update_session_flag() -> None:
    """Update timestamp and keep_alive in existing session flag."""
    path = _expand(SESSION_FLAG_PATH)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["timestamp_last_request"] = int(time.time())
        data["effective_keep_alive_seconds"] = get_effective_keep_alive_seconds()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to update session flag: %s", e)


def delete_session_flag() -> None:
    """Remove session flag (session ended, compute resumed)."""
    path = _expand(SESSION_FLAG_PATH)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _check_model_loaded(ollama_url: str) -> Optional[bool]:
    """True: resident models; False: a validated empty list; None: unverified."""
    import urllib.request

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_ollama_field")
            value[key] = item
        return value

    def invalid(_value):
        raise ValueError("invalid_ollama_number")

    try:
        request = urllib.request.Request(f"{ollama_url.rstrip('/')}/api/ps")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            return None
        data = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            return None
        models = data["models"]
        if len(models) > 64:
            return None
        for model in models:
            if not isinstance(model, dict):
                return None
            name = model.get("name")
            if (not isinstance(name, str) or not name or len(name) > 512
                    or name != name.strip() or any(ord(char) < 32 for char in name)):
                return None
        # Another model still consumes the same host RAM; absence of just the
        # original target is not sufficient evidence to resume compute.
        return bool(models)
    except Exception:
        return None


def start_resume_monitor(
    model_name: str,
    paused_pids: List[int],
    callback: Optional[Callable[[List[int]], None]] = None,
    ollama_url: str = "http://localhost:11434",
    poll_interval: float = 30.0,
    idle_wait: float = 90.0,
    timeout: float = 14400.0,
) -> threading.Thread:
    """Resume own compute jobs only after sustained, confirmed model absence.

    Unknown observations reset the idle window. Timeout preserves the pause
    receipts for explicit recovery; it never authorizes a signal or cleanup.
    """
    if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
           for value in (poll_interval, idle_wait, timeout)):
        raise ValueError("Resume monitor durations must be positive and finite")
    if isinstance(paused_pids, _PausedJobs):
        observed_pauses = paused_pids.pause_receipts
    else:
        # Compatibility for callers holding a plain PID list: freeze the
        # currently persisted ownership now, never adopt a later replacement.
        from hub._services.user_config_store import _exclusive_lock
        path = _expand(PAUSED_PIDS_FILE)
        try:
            with _exclusive_lock(path):
                observed_pauses = tuple(_pause_identity(record) for record in _read_paused_records(path)
                                        if record["pid"] in paused_pids and record["state"] == "paused")
        except Exception:
            observed_pauses = ()
            log.warning("compute_resume_deferred reason=pause_receipt_unverified")
    owned_pids = _PausedJobs(paused_pids, observed_pauses)

    def _monitor():
        deadline = time.monotonic() + timeout
        unload_seen_at = None
        while time.monotonic() < deadline:
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                break
            loaded = _check_model_loaded(ollama_url)
            now = time.monotonic()
            if now >= deadline:
                break
            if loaded is not False:
                unload_seen_at = None
                if loaded is None:
                    log.warning("compute_resume_deferred reason=ollama_state_unknown")
                continue
            if unload_seen_at is None:
                unload_seen_at = now
                log.info("Ollama empty; starting compute idle wait (%.0fs)", idle_wait)
                continue
            if now - unload_seen_at < idle_wait:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                break
            time.sleep(5)
            loaded = _check_model_loaded(ollama_url)
            if time.monotonic() >= deadline:
                break
            if loaded is not False:
                unload_seen_at = None
                continue
            resumed = resume_compute_jobs(owned_pids)
            if callback and resumed:
                callback(resumed)
            return

        log.warning("compute_resume_deferred reason=monitor_timeout receipt_preserved=true model=%s",
                    model_name)

    thread = threading.Thread(target=_monitor, daemon=True, name="compute-resume-monitor")
    thread.start()
    return thread


def format_status_message(status: dict) -> str:
    """Format compute status for display in Telegram."""
    jobs = status.get("active_compute_jobs", [])
    if not jobs:
        return "Compute-Jobs aktiv (Details nicht verfuegbar)"

    lines = ["Compute-Jobs laufen:"]
    for job in jobs:
        name = job.get("name", "?")
        pid = job.get("pid", "?")
        rss_kb = job.get("rss_kb", "0")
        elapsed = job.get("elapsed", "?")
        try:
            rss_gb = int(rss_kb) / 1024 / 1024
            rss_str = f"{rss_gb:.1f} GB"
        except (ValueError, TypeError):
            rss_str = f"{rss_kb} KB"
        lines.append(f"  {name} (PID {pid}) — {rss_str} RAM, {elapsed}")

    lines.append("")
    lines.append("Soll ich die Jobs pausieren (SIGSTOP) fuer den Ollama-Load?")
    lines.append("Antwort: JA oder NEIN")
    return "\n".join(lines)


def _record_fackel_activity(
    alt: str,
    neu: str,
    quelle: str,
    datei: str,
) -> None:
    """Record a Fackel preference change in the chat activity log.

    Isolated into a helper so test suites can monkeypatch/neutralize it cleanly.
    """
    try:
        from hub._services.chat.slots_config import record_activity
        record_activity(
            source="fackel",
            activity=f"Fackel-Vorrang {alt} -> {neu} (Quelle: {quelle})",
            status="ok",
            details={
                "alt": alt,
                "neu": neu,
                "quelle": quelle,
                "datei": str(datei),
            },
        )
    except Exception as e:
        log.warning("Could not record fackel activity: %s", e)


def get_fackel_preference(path: Optional[str] = None, *, migrate: bool = True) -> str:
    """Return the current Fackel (resource priority) preference.

    Order of resolution:
        1. path (primary file, defaults to FACKEL_PREFERENCE_FILE)
        2. FACKEL_PREFERENCE_LEGACY_FILE (only if path is the derived default path,
           not when set via BACH_FACKEL_PREFERENCE_PATH) with one-time migration
           to the primary file path.
        3. slots_config.json
        4. FACKEL_COMPUTE ('compute')

    Returns:
        'ollama' or 'compute' (default: 'compute').
    """
    is_default = False
    if path is None:
        path = FACKEL_PREFERENCE_FILE
        is_default = True
    elif path == FACKEL_PREFERENCE_FILE:
        is_default = True

    f = _expand(path)
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            pref = str(data.get("preference", "")).lower().strip()
            if pref in VALID_FACKEL_PREFERENCES:
                return pref
        except Exception as e:
            log.warning("Could not read fackel preference file %s: %s", f, e)

    # Secondary fallback with migration: legacy file, but ONLY if path is the
    # derived default, not explicitly configured via BACH_FACKEL_PREFERENCE_PATH.
    # Ein gesetzter Env-Pfad ist eine bewusste Ansage des Betreibers; still daran
    # vorbei die Altdatei zu lesen wuerde sie unterlaufen.
    if is_default and not _FACKEL_PATH_FROM_ENV:
        legacy = _expand(FACKEL_PREFERENCE_LEGACY_FILE)
        if legacy.is_file():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
                legacy_pref = str(data.get("preference", "")).lower().strip()
                if legacy_pref in VALID_FACKEL_PREFERENCES:
                    if not migrate:
                        return legacy_pref
                    # One-time migration to new location (atomic write)
                    try:
                        f.parent.mkdir(parents=True, exist_ok=True)
                        payload = {
                            "preference": legacy_pref,
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }
                        tmp = f.with_suffix(".tmp")
                        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                        tmp.replace(f)
                        log.info(
                            "Migrated fackel preference from legacy %s to %s (value: %s)",
                            legacy,
                            f,
                            legacy_pref,
                        )
                    except Exception as e:
                        log.warning(
                            "Could not migrate fackel preference from %s to %s: %s",
                            legacy,
                            f,
                            e,
                        )
                    return legacy_pref
            except Exception as e:
                log.warning("Could not read legacy fackel preference file %s: %s", legacy, e)

    # Tertiary persistent fallback: slots_config.json
    try:
        from hub._services.chat.slots_config import load_slots_config
        cfg = load_slots_config()
        pref = str(cfg.get("fackel_preference", "")).lower().strip()
        if pref in VALID_FACKEL_PREFERENCES:
            return pref
    except Exception:
        pass

    return FACKEL_COMPUTE


def set_fackel_preference(
    pref: str,
    path: Optional[str] = None,
    quelle: str = "unbekannt",
) -> str:
    """Set the Fackel resource preference ('compute' or 'ollama') and persist it.

    Args:
        pref: Target preference ('compute' or 'ollama').
        path: Path to the preference file (defaults to FACKEL_PREFERENCE_FILE).
        quelle: Source triggering the update ('telegram', 'api', 'tray', 'cli',
            'test', etc.). Without quelle, it was previously impossible to trace
            which caller triggered a preference switch.

    Returns:
        The normalized preference string.
    """
    pref_norm = str(pref).lower().strip()
    if pref_norm not in VALID_FACKEL_PREFERENCES:
        raise ValueError(
            f"Invalid fackel preference: {pref!r}. Must be one of {VALID_FACKEL_PREFERENCES}"
        )
    if path is None:
        path = FACKEL_PREFERENCE_FILE

    try:
        alt = get_fackel_preference(path)
    except Exception:
        alt = "unbekannt"

    f = _expand(path)
    file_saved = False
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "preference": pref_norm,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(f)
        log.info(
            "Fackel preference %s -> %s (Quelle: %s, Datei: %s)",
            alt,
            pref_norm,
            quelle,
            f,
        )
        file_saved = True
    except Exception as e:
        log.error("Failed to persist fackel preference to %s: %s", f, e)

    # Dual persistence: also save to slots_config.json
    try:
        from hub._services.chat.slots_config import update_fackel_preference
        update_fackel_preference(pref_norm)
    except Exception as e:
        log.warning("Could not persist fackel preference to slots_config: %s", e)
        if not file_saved:
            raise

    # Activity log persistence: record for /activity GUI timeline
    _record_fackel_activity(alt, pref_norm, quelle, str(f))

    return pref_norm
