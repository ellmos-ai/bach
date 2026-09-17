"""Inherited host-process guard for Python children spawned by BACH tests."""

import os
import re
import subprocess
from pathlib import Path

_GUARD_DIR = Path(__file__).resolve().parent


def _render_command(command):
    if isinstance(command, (str, bytes)):
        return os.fsdecode(command)
    if isinstance(command, (list, tuple)):
        return " ".join(
            os.fsdecode(part)
            for part in command
            if isinstance(part, (str, bytes, os.PathLike))
        )
    return ""


def _dangerous_command(command):
    rendered = _render_command(command).casefold()
    if isinstance(command, (list, tuple)):
        executable = os.fsdecode(command[0]).casefold() if command else ""
    else:
        executable = rendered
    executable_name = Path(executable).name
    unguarded_python = re.compile(
        r"(?:^|[;&|]\s*)(?:\"[^\"]*python(?:\d+(?:\.\d+)*)?\.exe\"|"
        r"[^\s\"]*python(?:\d+(?:\.\d+)*)?(?:\.exe)?)\s+"
        r"[^\r\n;&|]*?-[a-z]*[eis][a-z]*(?:\s|$)",
        re.IGNORECASE,
    )
    if unguarded_python.search(_render_command(command)):
        return True
    if executable_name.startswith("python") and isinstance(command, (list, tuple)):
        if any(str(part) in {"-E", "-I", "-S"} for part in command[1:]):
            return True
    if "onedrive" in executable and "/shutdown" in rendered:
        return True
    if any(token in executable for token in (
        "taskkill", "stop-process", "kill-process", "pkill", "killall",
    )) or ("osascript" in executable and "quit" in rendered):
        return True
    return executable_name in {
        "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
        "sh", "bash", "zsh",
    } and any(token in rendered for token in (
        "taskkill", "stop-process", "kill-process", "pkill", "killall",
        "onedrive.exe /shutdown", "onedrive.exe\" /shutdown", " kill ",
    ))


def _protected_env(env=None):
    protected = dict(os.environ if env is None else env)
    existing = protected.get("PYTHONPATH", "")
    paths = [part for part in existing.split(os.pathsep) if part]
    guard = str(_GUARD_DIR)
    paths = [part for part in paths if Path(part) != _GUARD_DIR]
    protected["PYTHONPATH"] = os.pathsep.join([guard, *paths])
    protected["BACH_TEST_MODE"] = "1"
    protected["BACH_RUNTIME_DIR"] = os.environ["BACH_RUNTIME_DIR"]
    return protected


def _is_own_child(pid):
    if pid == os.getpid():
        return True
    try:
        import psutil

        process = psutil.Process(pid)
        while process is not None:
            if process.ppid() == os.getpid():
                return True
            process = process.parent()
    except Exception:
        return False
    return False


if os.environ.get("BACH_TEST_MODE") == "1":
    _real_run = subprocess.run
    _real_popen = subprocess.Popen
    _real_os_kill = os.kill

    def _guarded_run(args, *popenargs, **kwargs):
        if _dangerous_command(args):
            raise RuntimeError(f"host process control blocked in test child: {args!r}")
        kwargs["env"] = _protected_env(kwargs.get("env"))
        return _real_run(args, *popenargs, **kwargs)

    class _GuardedPopen(_real_popen):
        def __init__(self, args, *popenargs, **kwargs):
            if _dangerous_command(args):
                raise RuntimeError(
                    f"host process control blocked in test child: {args!r}"
                )
            kwargs["env"] = _protected_env(kwargs.get("env"))
            super().__init__(args, *popenargs, **kwargs)

    def _guarded_os_kill(pid, sig):
        if sig != 0 and not _is_own_child(pid):
            raise RuntimeError(f"foreign PID blocked in test child: {pid}")
        return _real_os_kill(pid, sig)

    subprocess.run = _guarded_run
    subprocess.Popen = _GuardedPopen
    os.kill = _guarded_os_kill

    try:
        import psutil
    except ImportError:
        psutil = None

    if psutil is not None:
        _real_terminate = psutil.Process.terminate
        _real_kill = psutil.Process.kill

        def _guarded_terminate(process):
            if not _is_own_child(process.pid):
                raise RuntimeError(f"foreign PID blocked in test child: {process.pid}")
            return _real_terminate(process)

        def _guarded_kill(process):
            if not _is_own_child(process.pid):
                raise RuntimeError(f"foreign PID blocked in test child: {process.pid}")
            return _real_kill(process)

        psutil.Process.terminate = _guarded_terminate
        psutil.Process.kill = _guarded_kill
