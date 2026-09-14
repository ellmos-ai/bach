# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
core.sandbox - Subprocess-Isolation (Sandbox Stufe 2)
=====================================================

ROADMAP Phase 4, Stufe 2: Resource-Bounds fuer Subprozesse.

Zweischichtige Durchsetzung (Plattform-Realitaet):
- Kind-Seite (rlimit, POSIX): RLIMIT_AS/CPU/FSIZE/NPROC via preexec.
  Wirkt zuverlaessig unter Linux; macOS ignoriert RLIMIT_AS fuer
  VM-Allokationen weitgehend (deshalb Schicht 2).
- Eltern-Seite (Watchdog): Monitor-Thread misst RSS des
  Prozessbaums (psutil, Fallback: ps-Aufruf) und killt die
  Prozessgruppe bei Ueberschreitung. Plattformunabhaengig wirksam.
- Timeout: Prozessgruppen-Kill (SIGTERM, Grace, SIGKILL) —
  keine verwaisten Enkelprozesse. Windows-Fallback: nur direktes Kind.

Nutzung:
    from core.sandbox import SandboxLimits, run_isolated

    limits = SandboxLimits(timeout_sec=30, memory_mb=512)
    result = run_isolated(["python3", "skript.py"], limits=limits)
    if result.timed_out or result.memory_exceeded:
        ...

Task: 1071
Version: 1.0.0
"""

import os
import signal
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union

# Plattform-Faehigkeit
IS_POSIX = (os.name == "posix")
try:
    import resource
    HAS_RLIMIT = True
except ImportError:  # Windows
    resource = None
    HAS_RLIMIT = False
try:
    import psutil  # harte BACH-Dependency (requirements.txt)
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

DEFAULT_TIMEOUT_SEC = 30
DEFAULT_MEMORY_MB = 512
# Grace-Zeit zwischen SIGTERM und SIGKILL beim Kill
_TERM_GRACE_SEC = 2.0
# Poll-Intervall des Memory-Watchdogs
_WATCHDOG_INTERVAL_SEC = 0.25


@dataclass
class SandboxLimits:
    """Resource-Grenzen fuer einen isolierten Subprozess.

    None = kein Limit. rlimit-Werte werden auf POSIX im Kindprozess
    gesetzt (preexec), zusaetzlich ueberwacht der Eltern-Watchdog
    den Speicher (memory_mb) plattformunabhaengig.
    """
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    memory_mb: Optional[int] = DEFAULT_MEMORY_MB
    cpu_sec: Optional[int] = None
    max_file_mb: Optional[int] = None
    max_processes: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "timeout_sec": self.timeout_sec,
            "memory_mb": self.memory_mb,
            "cpu_sec": self.cpu_sec,
            "max_file_mb": self.max_file_mb,
            "max_processes": self.max_processes,
        }


@dataclass
class SandboxResult:
    """Ergebnis einer isolierten Ausfuehrung (duck-kompatibel zu
    subprocess.CompletedProcess fuer _format_result)."""
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    memory_exceeded: bool = False
    duration_sec: float = 0.0
    rlimits_applied: bool = False   # POSIX-rlimit im Kind gesetzt
    watchdog_active: bool = False   # Eltern-Watchdog lief
    args: Union[Sequence[str], str, None] = None


def _child_preexec(limits: SandboxLimits):
    """Baut die preexec_fn, die im Kindprozess rlimits setzt (nur POSIX).

    Hinweis: preexec_fn darf nur aufgerufen werden, solange im Eltern-
    prozess noch keine zusaetzlichen Threads laufen — run_isolated
    startet den Watchdog-Thread daher erst NACH dem Popen-Aufruf.
    """
    if not (IS_POSIX and HAS_RLIMIT):
        return None

    def apply():
        # Core-Dumps grundsaetzlich aus (Sicherheits-Default)
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass
        if limits.memory_mb:
            try:
                nbytes = int(limits.memory_mb) * 1024 * 1024
                # RLIMIT_AS (Adressraum). Wirkt unter Linux; macOS
                # ignoriert VM-Limits weitgehend — dort traegt der
                # Watchdog die Durchsetzung.
                resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))
            except (ValueError, OSError):
                pass
        if limits.cpu_sec:
            try:
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (int(limits.cpu_sec), int(limits.cpu_sec) + 5),
                )
            except (ValueError, OSError):
                pass
        if limits.max_file_mb:
            try:
                nbytes = int(limits.max_file_mb) * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (nbytes, nbytes))
            except (ValueError, OSError):
                pass
        if limits.max_processes and hasattr(resource, "RLIMIT_NPROC"):
            try:
                resource.setrlimit(
                    resource.RLIMIT_NPROC,
                    (int(limits.max_processes), int(limits.max_processes)),
                )
            except (ValueError, OSError):
                pass

    return apply


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Beendet die gesamte Prozessgruppe (SIGTERM, dann SIGKILL)."""
    if IS_POSIX:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, PermissionError):
            pgid = None
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.wait(timeout=_TERM_GRACE_SEC)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    proc.wait(timeout=_TERM_GRACE_SEC)
                except subprocess.TimeoutExpired:
                    pass
            return
    # Fallback: nur direktes Kind (Windows)
    try:
        proc.kill()
        proc.wait(timeout=_TERM_GRACE_SEC)
    except Exception:
        pass


def _tree_rss_bytes(pid: int) -> int:
    """RSS-Summe von Prozess + allen Kindern in Bytes (psutil)."""
    total = 0
    try:
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
    except psutil.Error:
        return 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            pass
    return total


def _group_rss_bytes_posix(pgid: int) -> int:
    """RSS-Summe der Prozessgruppe ohne psutil (ps-Fallback, KB -> Bytes)."""
    try:
        out = subprocess.run(
            ["ps", "-eo", "pgid=,rss="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return 0
    total_kb = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            if int(parts[0]) == pgid:
                total_kb += int(parts[1])
    return total_kb * 1024


def _watchdog(proc: subprocess.Popen, limits: SandboxLimits,
              exceeded: threading.Event, stop: threading.Event) -> None:
    """Monitor-Thread: killt die Prozessgruppe bei Speicher-Ueberschreitung."""
    limit_bytes = int(limits.memory_mb) * 1024 * 1024
    pgid = None
    if IS_POSIX:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, PermissionError):
            pgid = None
    while not stop.is_set():
        if proc.poll() is not None:
            return
        if HAS_PSUTIL:
            rss = _tree_rss_bytes(proc.pid)
        elif pgid is not None:
            rss = _group_rss_bytes_posix(pgid)
        else:
            return  # Windows ohne psutil: keine Messung moeglich
        if rss > limit_bytes:
            exceeded.set()
            _kill_process_group(proc)
            return
        stop.wait(_WATCHDOG_INTERVAL_SEC)


def run_isolated(cmd: Union[Sequence[str], str],
                 limits: Optional[SandboxLimits] = None,
                 cwd: Optional[Union[str, Path]] = None,
                 env: Optional[dict] = None,
                 shell: bool = False,
                 input_text: Optional[str] = None) -> SandboxResult:
    """Fuehrt einen Befehl mit Resource-Bounds aus.

    Args:
        cmd: Argumentliste (oder String bei shell=True)
        limits: SandboxLimits (Default: timeout 30s, memory 512MB)
        cwd: Arbeitsverzeichnis
        env: Environment (Default: aktuelles)
        shell: Ueber Shell ausfuehren (wie subprocess)
        input_text: Optionaler stdin-Input

    Returns:
        SandboxResult mit returncode/stdout/stderr/timed_out/memory_exceeded
    """
    limits = limits or SandboxLimits()
    start = time.monotonic()
    preexec = _child_preexec(limits)
    popen_kwargs = dict(
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        env=env,
        shell=shell,
    )
    if IS_POSIX:
        # Eigene Session => Prozessgruppe kann komplett gekillt werden
        popen_kwargs["start_new_session"] = True
        if preexec is not None:
            popen_kwargs["preexec_fn"] = preexec

    proc = subprocess.Popen(cmd, **popen_kwargs)

    # Memory-Watchdog (erst nach Popen starten: preexec_fn/Thread-Regel)
    mem_exceeded = threading.Event()
    watchdog_stop = threading.Event()
    watchdog_thread = None
    watchdog_active = bool(limits.memory_mb) and (HAS_PSUTIL or IS_POSIX)
    if watchdog_active:
        watchdog_thread = threading.Thread(
            target=_watchdog, args=(proc, limits, mem_exceeded, watchdog_stop),
            name="sandbox-watchdog", daemon=True,
        )
        watchdog_thread.start()

    timed_out = False
    try:
        stdout, stderr = proc.communicate(
            input=input_text, timeout=limits.timeout_sec
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
        # Nach dem Kill Restausgabe einsammeln (blockiert nicht mehr)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            stdout, stderr = "", ""
    finally:
        watchdog_stop.set()
        if watchdog_thread is not None:
            watchdog_thread.join(timeout=_TERM_GRACE_SEC + 1)

    duration = time.monotonic() - start
    stderr = stderr or ""
    # Memory-Ueberschreitung: Watchdog-Kill ODER rlimit-MemoryError im Kind
    memory_exceeded = mem_exceeded.is_set() or "MemoryError" in stderr
    returncode = proc.returncode if proc.returncode is not None else -1

    return SandboxResult(
        returncode=returncode,
        stdout=stdout or "",
        stderr=stderr,
        timed_out=timed_out,
        memory_exceeded=memory_exceeded,
        duration_sec=round(duration, 3),
        rlimits_applied=(preexec is not None),
        watchdog_active=watchdog_active,
        args=cmd,
    )


def load_limits_from_db(db_path: Optional[Union[str, Path]],
                        default_timeout: int = DEFAULT_TIMEOUT_SEC,
                        default_memory_mb: Optional[int] = DEFAULT_MEMORY_MB
                        ) -> SandboxLimits:
    """Laedt Limits aus system_config (Keys sandbox.timeout_sec,
    sandbox.memory_limit_mb). Faellt bei jedem Fehler auf Defaults."""
    timeout = default_timeout
    memory = default_memory_mb
    if not db_path or not Path(db_path).exists():
        return SandboxLimits(timeout_sec=timeout, memory_mb=memory)
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            for key, target in (("sandbox.timeout_sec", "timeout"),
                                ("sandbox.memory_limit_mb", "memory")):
                row = conn.execute(
                    "SELECT value FROM system_config WHERE key = ?", (key,)
                ).fetchone()
                if row and row[0] is not None:
                    val = int(str(row[0]).strip())
                    if val > 0:
                        if target == "timeout":
                            timeout = val
                        else:
                            memory = val
        finally:
            conn.close()
    except Exception:
        pass
    return SandboxLimits(timeout_sec=timeout, memory_mb=memory)
