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
- POSIX-Abbruch: eigene neue Prozessgruppe, TERM/KILL und Leerprüfung;
  beobachtete Gruppenflucht oder unvollständige Prüfung bleibt unbestätigt.
  Windows behält seinen bisherigen Best-Effort-Pfad ohne Cleanupbestätigung.

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
import selectors
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
    cleanup_required: bool = False
    cleanup_confirmed: Optional[bool] = None
    cleanup_scope: Optional[str] = None
    watchdog_joined: bool = True
    cleanup_errors: tuple = ()
    memory_watchdog_triggered: bool = False


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


class _OwnedPosixGroup:
    """Only the new session created by this run; never discover a kill target.

    Keep the direct child unreaped until group shutdown. Its PID reserves the
    group identity even after an early leader exit. Detached/escaped observed
    descendants and incomplete inspection prevent a confirmed cleanup.
    """
    def __init__(self, proc):
        if not getattr(proc, "_bach_created_session", False) or proc.pid <= 1:
            raise RuntimeError("Owned process session is not established")
        if proc.pid in {os.getpid(), os.getpgrp(), os.getsid(0)}:
            raise RuntimeError("Caller process group is forbidden")
        self.proc = proc
        self.pgid = proc.pid
        self.uid = os.getuid()
        self.lock = threading.RLock()
        self.closed = False
        self.reaping = False
        self.confirmed = False
        self.errors = set()
        self.observed = {}
        self.required = False
        self.escaped = False
        try:
            root = psutil.Process(proc.pid)
            self.birth = root.create_time()
            if root.uids().real != self.uid:
                self.errors.add("ownership_unconfirmed")
            if root.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                if os.getpgid(proc.pid) != self.pgid or os.getsid(proc.pid) != self.pgid:
                    self.errors.add("ownership_unconfirmed")
        except (psutil.Error, OSError):
            self.birth = None
            self.errors.add("ownership_unconfirmed")

    def _members(self):
        members = []
        try:
            candidates = set(psutil.pids())
            # Record observable descendants even when they leave the session.
            root = psutil.Process(self.proc.pid)
            if root.create_time() == self.birth:
                for child in root.children(recursive=True):
                    self.observed.setdefault(child.pid, child.create_time())
        except psutil.NoSuchProcess:
            candidates = set(psutil.pids())
        except (psutil.Error, OSError):
            self.errors.add("inspection_unconfirmed")
            return None
        for pid in candidates | set(self.observed):
            if pid <= 0:
                continue
            try:
                sid = os.getsid(pid)
                if sid != self.pgid and pid not in self.observed:
                    continue
                process = psutil.Process(pid)
                birth = process.create_time()
                if pid in self.observed and self.observed[pid] != birth:
                    # A reused PID outside our held session is not our process.
                    if sid != self.pgid:
                        continue
                    # Numeric reuse can still be a new child in our own session.
                    # Keep it visible to group shutdown, but never confirm its
                    # lineage or cleanup after the identity proof has changed.
                    self.errors.add("member_identity_changed")
                if sid != self.pgid:
                    self.escaped = True
                    continue
                if process.uids().real != self.uid:
                    self.errors.add("member_identity_unconfirmed")
                self.observed.setdefault(pid, birth)
                pgid = os.getpgid(pid)
                if pgid != self.pgid:
                    self.escaped = True
                status = process.status()
                try:
                    rss = process.memory_info().rss
                except psutil.ZombieProcess:
                    rss = 0
                members.append((pid, status, rss, pgid))
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
            except (PermissionError, psutil.Error, OSError):
                self.errors.add("inspection_unconfirmed")
        return members

    @staticmethod
    def _live(members):
        return [item for item in (members or [])
                if item[1] not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}]

    @staticmethod
    def _quiescent(members):
        return members is not None and not _OwnedPosixGroup._live(members)

    def leader_exited(self):
        with self.lock:
            if self.closed or self.reaping:
                return True
            try:
                root = psutil.Process(self.proc.pid)
                if root.create_time() != self.birth:
                    self.errors.add("leader_identity_changed")
                    return True
                return root.status() in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
            except psutil.NoSuchProcess:
                self.errors.add("leader_reaped_outside_owner")
                return True
            except psutil.Error:
                self.errors.add("leader_state_unconfirmed")
                return False

    def rss(self):
        with self.lock:
            if self.closed:
                return 0
            members = self._members()
            if members is None:
                return 0
            return sum(item[2] for item in members)

    def _signal(self, sig):
        # No signal after wait/reap. A held direct-child PID anchors this PGID.
        try:
            root = psutil.Process(self.proc.pid)
            if (self.proc.returncode is not None or self.birth is None
                    or root.create_time() != self.birth
                    or root.uids().real != self.uid):
                self.errors.add("signal_ownership_unconfirmed")
                return False
            # Darwin getsid/getpgid may report ESRCH for our unreaped zombie.
            # Popen's successful start_new_session plus held PID/birth/UID is
            # still the original ownership proof; a session leader cannot join
            # a foreign group. Do not reap it until every signal is finished.
            if root.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                if (os.getsid(self.proc.pid) != self.pgid
                        or os.getpgid(self.proc.pid) != self.pgid):
                    self.errors.add("signal_ownership_unconfirmed")
                    return False
            try:
                os.killpg(self.pgid, sig)
            except ProcessLookupError:
                pass
            return True
        except ProcessLookupError:
            self.errors.add("signal_ownership_unconfirmed")
            return False
        except (PermissionError, psutil.Error, OSError):
            self.errors.add("signal_unconfirmed")
            return False

    def _shutdown_owned_group(self):
        """Bounded shutdown; caller holds the unreaped own group anchor."""
        self._signal(signal.SIGTERM)
        deadline = time.monotonic() + _TERM_GRACE_SEC
        while time.monotonic() < deadline:
            if self._quiescent(self._members()):
                break
            time.sleep(0.02)
        # The entire group is the condition, never just leader.wait().
        if not self._quiescent(self._members()):
            self._signal(signal.SIGKILL)
        deadline = time.monotonic() + _TERM_GRACE_SEC
        while time.monotonic() < deadline:
            if self._quiescent(self._members()):
                break
            time.sleep(0.02)

    def finish(self, *, abort=False):
        with self.lock:
            if self.closed:
                return self.confirmed
            members = self._members()
            self.required = bool(abort or self._live(members) or self.escaped or self.errors)
            if self.required:
                self._shutdown_owned_group()
            late_members = self._members()
            if not self.required and self._live(late_members):
                # A PID/session observation may have raced the first scan.
                # While our leader is still held, try one bounded shutdown
                # of that same owned group before reaping its identity anchor.
                self.required = True
                self._shutdown_owned_group()
                late_members = self._members()
            if self._live(late_members):
                self.errors.add("live_members_remain")
            self.reaping = True
            try:
                self.proc.wait(timeout=_TERM_GRACE_SEC)
            except (subprocess.TimeoutExpired, OSError):
                self.errors.add("leader_wait_unconfirmed")
            # No more signals once the leader may be reaped. Read-only finality.
            deadline = time.monotonic() + _TERM_GRACE_SEC
            final = self._members()
            while final and time.monotonic() < deadline:
                time.sleep(0.02)
                final = self._members()
            if final:
                self.errors.add("members_remain")
            if self.escaped:
                self.errors.add("escaped_descendant_unconfirmed")
            self.required = self.required or bool(self.escaped or self.errors or final)
            self.confirmed = final == [] and not self.errors and self.proc.returncode is not None
            self.closed = True
            return self.confirmed


def _communicate_owned(proc, owner, timeout, input_text):
    """Collect POSIX pipes without wait()/poll() reaping the group anchor."""
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    pending = memoryview((input_text or "").encode("utf-8"))
    for stream, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    if proc.stdin is not None:
        if pending:
            os.set_blocking(proc.stdin.fileno(), False)
            selector.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            proc.stdin.close()
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(0.05, remaining)):
                stream = key.fileobj
                try:
                    if key.data == "stdin":
                        count = os.write(stream.fileno(), pending[:65536])
                        pending = pending[count:]
                        if not pending:
                            selector.unregister(stream)
                            stream.close()
                    else:
                        data = os.read(stream.fileno(), 65536)
                        if data:
                            output[key.data].extend(data)
                        else:
                            selector.unregister(stream)
                            stream.close()
                except BlockingIOError:
                    continue
                except BrokenPipeError:
                    selector.unregister(stream)
                    stream.close()
            if not selector.get_map() and owner.leader_exited():
                break
    finally:
        selector.close()
    return (output["stdout"].decode("utf-8", "replace"),
            output["stderr"].decode("utf-8", "replace"), timed_out)


def _kill_process_group(proc: subprocess.Popen) -> bool:
    """Beendet die gesamte Prozessgruppe (SIGTERM, dann SIGKILL)."""
    if IS_POSIX:
        owner = getattr(proc, "_bach_owned_group", None)
        if owner is None:
            return False
        return owner.finish(abort=True)
    # Fallback: Windows -- kein echtes killpg. Bei shell=True ist proc selbst
    # cmd.exe /c <befehl>; der eigentliche Befehl laeuft als Enkel und ueberlebt
    # proc.kill() unbeeindruckt. Deshalb zuerst den gesamten Nachkommenbaum
    # beenden und auf dessen Ende warten, bevor der Aufrufer aufraeumt.
    descendants = []
    if HAS_PSUTIL:
        try:
            descendants = psutil.Process(proc.pid).children(recursive=True)
        except psutil.Error:
            descendants = []
        for child in descendants:
            try:
                child.kill()
            except psutil.Error:
                pass
    try:
        proc.kill()
        proc.wait(timeout=_TERM_GRACE_SEC)
    except Exception:
        pass
    for child in descendants:
        try:
            child.wait(timeout=_TERM_GRACE_SEC)
        except psutil.Error:
            pass
    return False


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
    """Measure the owned group even after an early leader exit."""
    limit_bytes = int(limits.memory_mb) * 1024 * 1024
    owner = getattr(proc, "_bach_owned_group", None)
    while not stop.is_set():
        if owner is not None:
            if owner.closed:
                return
            rss = owner.rss()
        elif proc.poll() is not None:
            return
        elif HAS_PSUTIL:
            rss = _tree_rss_bytes(proc.pid)
        else:
            return
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
    if IS_POSIX and (not HAS_PSUTIL or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL):
        raise RuntimeError("Confirmed POSIX process ownership is unavailable")
    preexec = _child_preexec(limits)
    popen_kwargs = dict(
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None,
        env=env, shell=shell,
    )
    if IS_POSIX:
        popen_kwargs["start_new_session"] = True
        if preexec is not None:
            popen_kwargs["preexec_fn"] = preexec
    proc = subprocess.Popen(cmd, **popen_kwargs)
    owner = None
    if IS_POSIX:
        proc._bach_created_session = True
        owner = _OwnedPosixGroup(proc)
        proc._bach_owned_group = owner
    mem_exceeded = threading.Event()
    watchdog_stop = threading.Event()
    watchdog_thread = None
    watchdog_active = bool(limits.memory_mb) and (HAS_PSUTIL or IS_POSIX)
    if watchdog_active:
        watchdog_thread = threading.Thread(
            target=_watchdog, args=(proc, limits, mem_exceeded, watchdog_stop),
            name="sandbox-watchdog", daemon=True)
        watchdog_thread.start()
    timed_out = False
    stdout = stderr = ""
    cleanup = None
    try:
        if owner is not None:
            stdout, stderr, timed_out = _communicate_owned(
                proc, owner, limits.timeout_sec, input_text)
        else:
            try:
                stdout, stderr = proc.communicate(input=input_text, timeout=limits.timeout_sec)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process_group(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except Exception:
                    stdout, stderr = "", ""
    finally:
        watchdog_stop.set()
        if owner is not None:
            cleanup = owner.finish(abort=timed_out or mem_exceeded.is_set())
        if watchdog_thread is not None:
            watchdog_thread.join(timeout=_TERM_GRACE_SEC + 1)
        watchdog_joined = watchdog_thread is None or not watchdog_thread.is_alive()
        if not watchdog_joined:
            cleanup = False
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()
    stderr = stderr or ""
    memory_exceeded = mem_exceeded.is_set() or "MemoryError" in stderr
    return SandboxResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout or "", stderr=stderr, timed_out=timed_out,
        memory_exceeded=memory_exceeded,
        duration_sec=round(time.monotonic() - start, 3),
        rlimits_applied=preexec is not None, watchdog_active=watchdog_active, args=cmd,
        cleanup_required=bool(timed_out or memory_exceeded or (owner and owner.required)),
        cleanup_confirmed=cleanup,
        cleanup_scope="owned_posix_process_group" if owner is not None else None,
        watchdog_joined=watchdog_joined,
        cleanup_errors=tuple(sorted(owner.errors)) if owner is not None else (),
        memory_watchdog_triggered=mem_exceeded.is_set(),
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
