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

Usage:
    from hub.compute_lock import check_compute_active, pause_compute_jobs
    active, status = check_compute_active()
"""
import json
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

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


def _filter_stopped_jobs(status: dict) -> Tuple[bool, dict]:
    """Filter out PIDs that are already stopped (state T).

    The watchdog may keep stopped PIDs in the lock file. We only care
    about running ones to avoid asking the user to pause already-paused jobs.
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


def pause_compute_jobs(status: dict) -> List[int]:
    """Send SIGSTOP to all compute PIDs from status dict.

    Returns list of successfully paused PIDs.
    Saves paused PIDs to PAUSED_PIDS_FILE for crash recovery.
    """
    jobs = status.get("active_compute_jobs", [])
    paused = []

    for job in jobs:
        pid = job.get("pid")
        if not pid:
            continue
        try:
            os.kill(pid, signal.SIGSTOP)
            paused.append(pid)
            log.info("SIGSTOP sent to PID %d (%s)", pid, job.get("name", "?"))
        except ProcessLookupError:
            log.warning("PID %d not found, skipping", pid)
        except PermissionError:
            log.warning("No permission to stop PID %d", pid)

    if paused:
        _save_paused_pids(paused)

    return paused


def resume_compute_jobs(paused_pids: List[int]) -> None:
    """Send SIGCONT to previously paused PIDs. Cleans up paused-pids file."""
    for pid in paused_pids:
        try:
            os.kill(pid, signal.SIGCONT)
            log.info("SIGCONT sent to PID %d", pid)
        except ProcessLookupError:
            log.warning("PID %d gone, skipping SIGCONT", pid)
        except PermissionError:
            log.warning("No permission to resume PID %d", pid)

    _cleanup_paused_pids()


def _save_paused_pids(pids: List[int]) -> None:
    """Persist paused PIDs for crash recovery."""
    path = _expand(PAUSED_PIDS_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "paused_pids": pids,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "bach_telegram_bot",
        }, indent=2), encoding="utf-8")
    except OSError as e:
        log.error("Failed to save paused PIDs: %s", e)


def _cleanup_paused_pids() -> None:
    """Remove the paused-pids file."""
    path = _expand(PAUSED_PIDS_FILE)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_is_stopped(pid: int) -> bool:
    """Check if a PID exists and is in stopped state (T)."""
    try:
        result = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True, text=True, timeout=3,
        )
        state = result.stdout.strip()
        return "T" in state
    except (subprocess.TimeoutExpired, OSError):
        return False


def recover_paused_jobs() -> List[int]:
    """Crash recovery: resume any PIDs that are still stopped from a previous session.

    Called at bot startup. Returns list of resumed PIDs.
    """
    path = _expand(PAUSED_PIDS_FILE)
    if not path.is_file():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not read paused PIDs file: %s", e)
        _cleanup_paused_pids()
        return []

    pids = data.get("paused_pids", [])
    resumed = []

    for pid in pids:
        if _pid_is_stopped(pid):
            try:
                os.kill(pid, signal.SIGCONT)
                resumed.append(pid)
                log.info("Crash recovery: SIGCONT sent to PID %d", pid)
            except (ProcessLookupError, PermissionError) as e:
                log.warning("Crash recovery: could not resume PID %d: %s", pid, e)
        else:
            log.info("Crash recovery: PID %d not stopped (already running or gone)", pid)

    _cleanup_paused_pids()
    delete_session_flag()
    return resumed


SESSION_FLAG_PATH = "~/.memwatchdog/user_session_active.flag"


def get_effective_keep_alive(default: str = "5m") -> str:
    """Adaptive keep_alive: 5m when compute exists (running or paused), 30m otherwise."""
    paused = _expand(PAUSED_PIDS_FILE)
    if paused.is_file():
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


def start_resume_monitor(
    model_name: str,
    paused_pids: List[int],
    callback: Optional[Callable[[List[int]], None]] = None,
    ollama_url: str = "http://localhost:11434",
    poll_interval: float = 30.0,
    idle_wait: float = 90.0,
    timeout: float = 14400.0,  # 4 hours max
) -> threading.Thread:
    """Start a background thread that monitors Ollama model status.

    Waits for sustained model unload (idle_wait seconds of consecutive
    empty /api/ps polls), then double-checks before sending SIGCONT.
    """
    def _check_model_loaded() -> bool:
        import urllib.request
        try:
            req = urllib.request.Request(f"{ollama_url}/api/ps")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            loaded = [m.get("name", "") for m in data.get("models", [])]
            return model_name in loaded
        except Exception:
            return False

    def _monitor():
        start = time.time()
        unload_seen_at = None

        while time.time() - start < timeout:
            time.sleep(poll_interval)

            if _check_model_loaded():
                if unload_seen_at is not None:
                    log.info("Model %s re-loaded during idle wait, resetting", model_name)
                unload_seen_at = None
                continue

            now = time.time()
            if unload_seen_at is None:
                unload_seen_at = now
                log.info("Model %s unloaded, starting idle wait (%.0fs)", model_name, idle_wait)
                continue

            if now - unload_seen_at < idle_wait:
                continue

            time.sleep(5)
            if _check_model_loaded():
                log.info("Model %s re-loaded during double-check, resetting", model_name)
                unload_seen_at = None
                continue

            log.info("Model %s confirmed unloaded after %.0fs idle, resuming compute", model_name, idle_wait)
            break

        delete_session_flag()
        resume_compute_jobs(paused_pids)
        if callback:
            callback(paused_pids)

    thread = threading.Thread(target=_monitor, daemon=True,
                              name="compute-resume-monitor")
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
