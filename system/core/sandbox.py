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
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
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
    backend: str = "local"   # 'local' (Stufe 2) oder 'docker' (Stufe 3)


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
                 input_text: Optional[str] = None,
                 backend: str = "local") -> SandboxResult:
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
    backend = (backend or "local").lower()
    if backend in ("docker", "auto") and docker_available(DEFAULT_DOCKER_IMAGE):
        return docker_run_isolated(cmd, limits=limits, cwd=cwd, env=env,
                                  shell=shell, input_text=input_text)
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
        backend="local",
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


# --- Stufe 3: Docker-Container-Isolation (Task #1385) ---
DEFAULT_DOCKER_IMAGE = "python:3.12-slim"

_DOCKER_CACHE: dict = {}


def docker_available(image: str = DEFAULT_DOCKER_IMAGE, force: bool = False) -> bool:
    """True wenn Docker-Daemon laeuft UND Image lokal existiert (kein Auto-Pull)."""
    if not force and image in _DOCKER_CACHE:
        return _DOCKER_CACHE[image]
    available = False
    try:
        if shutil.which("docker") is None:
            return False
        daemon = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, timeout=10,
        )
        if daemon.returncode != 0:
            return False
        img = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True, timeout=10,
        )
        available = img.returncode == 0
    except Exception:
        available = False
    _DOCKER_CACHE[image] = available
    return available


def _map_image_command(cmd: Union[Sequence[str], str]) -> list:
    """Mappt Host-Befehl auf im Basis-Image verfuegbaren Befehl."""
    if not cmd:
        return list(cmd)
    if os.path.basename(str(cmd[0])).startswith("python"):
        return ["python3"] + list(cmd[1:])
    return list(cmd)


def docker_run_isolated(cmd: Union[Sequence[str], str],
                        limits: Optional[SandboxLimits] = None,
                        cwd: Optional[Union[str, Path]] = None,
                        env: Optional[dict] = None,
                        shell: bool = False,
                        input_text: Optional[str] = None,
                        image: str = DEFAULT_DOCKER_IMAGE,
                        name: Optional[str] = None) -> SandboxResult:
    """Stufe 3: Befehl in isoliertem Container (net=none, read-only, cap-drop ALL).

    Der Container wird ohne ``--rm`` gestartet, damit nach Beenden die
    OOM-Information aus ``docker inspect`` gelesen werden kann. In jedem
    Fall (Erfolg, Timeout, Exception) wird der Container anschliessend mit
    ``docker rm -f`` entfernt.

    Timeout-Handling arbeitet mit ``subprocess.Popen`` plus einem
    Watchdog-Thread. Bei Ueberschreitung des Limits wird zuerst
    ``docker stop`` (mit Grace-Periode) und danach ``docker kill`` auf den
    laufenden Container ausgefuehrt -- nicht nur der lokale
    ``docker run``-Client-Prozess wird gekillt.
    """
    limits = limits or SandboxLimits()
    name = name or "bach-sbx-" + uuid.uuid4().hex[:12]
    argv = ["docker", "run", "--name", name, "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt",
            "no-new-privileges", "--user", "1000:1000",
            "--tmpfs", "/tmp:rw,size=64m"]
    if limits.memory_mb:
        argv += ["--memory", f"{limits.memory_mb}m",
                 "--memory-swap", f"{limits.memory_mb}m"]
    argv += ["--pids-limit", str(limits.max_processes or 256)]
    argv += ["--ulimit", "core=0"]
    if limits.max_file_mb:
        argv += ["--ulimit", f"fsize={int(limits.max_file_mb) * 1024 * 1024}"]
    if limits.cpu_sec:
        argv += ["--ulimit", f"cpu={limits.cpu_sec}"]
    if input_text is not None:
        argv += ["-i"]
    if cwd:
        workdir = os.path.abspath(cwd)
        argv += ["-w", workdir, "-v", f"{workdir}:{workdir}"]
    if env:
        for key in sorted(env):
            if key.startswith(("PYTHON", "BACH", "LANG", "LC_")):
                argv += ["-e", f"{key}={env[key]}"]
    argv += ["-e", "PYTHONIOENCODING=utf-8", "-e", "PYTHONUNBUFFERED=1", image]
    if shell:
        argv += ["sh", "-c", cmd if isinstance(cmd, str) else " ".join(cmd)]
    else:
        argv += _map_image_command(list(cmd))

    timed_out_event = threading.Event()
    _cleanup_lock = threading.Lock()
    _cleanup_done = threading.Event()
    _cleanup_oom_result = [False]  # wird vom einmaligen Cleanup gesetzt

    def _docker_cleanup(oom_check: bool = True) -> bool:
        """Stoppe/entferne Container und gib OOMKilled-Status zurueck.

        Thread-sicher und idempotent: docker stop/kill/rm -f wird nur
        einmal ausgefuehrt; danach liefert jeder weitere Aufruf das
        gespeicherte OOM-Ergebnis zurueck.
        """
        if _cleanup_done.is_set():
            return _cleanup_oom_result[0]

        with _cleanup_lock:
            if _cleanup_done.is_set():
                return _cleanup_oom_result[0]

            try:
                if proc.poll() is None:
                    try:
                        subprocess.run(
                            ["docker", "stop", "-t", str(int(_TERM_GRACE_SEC)), name],
                            capture_output=True,
                            timeout=_TERM_GRACE_SEC + 5,
                        )
                    except Exception:
                        pass
                    if proc.poll() is None:
                        try:
                            subprocess.run(
                                ["docker", "kill", name],
                                capture_output=True, timeout=10,
                            )
                        except Exception:
                            pass
                    try:
                        proc.wait(timeout=_TERM_GRACE_SEC + 5)
                    except Exception:
                        pass
                if oom_check:
                    try:
                        inspect = subprocess.run(
                            ["docker", "inspect", name, "--format",
                             "{{.State.OOMKilled}}"],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=5,
                        )
                        _cleanup_oom_result[0] = "true" in (inspect.stdout or "").lower()
                    except Exception:
                        _cleanup_oom_result[0] = False
            finally:
                try:
                    subprocess.run(["docker", "rm", "-f", name],
                                   capture_output=True, timeout=15)
                except Exception:
                    pass
                _cleanup_oom_result[0] = _cleanup_oom_result[0] if oom_check else False
                _cleanup_done.set()
            return _cleanup_oom_result[0]

    def _timeout_watcher() -> None:
        try:
            deadline = time.monotonic() + limits.timeout_sec
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(min(0.2, deadline - time.monotonic()))
            if proc.poll() is None:
                timed_out_event.set()
                _docker_cleanup(oom_check=False)
        except Exception:
            pass

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return SandboxResult(
            returncode=-1, stdout="",
            stderr=f"Docker-Fehler: {exc}",
            timed_out=False, memory_exceeded=False,
            args=cmd, backend="docker",
        )

    watcher = threading.Thread(
        target=_timeout_watcher, name=f"docker-timeout-{name}", daemon=True,
    )
    watcher.start()

    start = time.monotonic()
    try:
        stdout, stderr = proc.communicate(input=input_text)
    except Exception as exc:
        _docker_cleanup(oom_check=False)
        return SandboxResult(
            returncode=-1, stdout="",
            stderr=f"Docker-Fehler: {exc}",
            timed_out=False, memory_exceeded=False,
            args=cmd, backend="docker",
        )
    finally:
        watcher.join(timeout=_TERM_GRACE_SEC + 3)

    oom_killed = _docker_cleanup(oom_check=True)
    duration = time.monotonic() - start
    stderr = stderr or ""
    stdout = stdout or ""
    timed_out = timed_out_event.is_set()
    returncode = proc.returncode if proc.returncode is not None else -1
    if timed_out:
        returncode = -1
    memory_exceeded = (
        oom_killed
        or returncode == 137
        or "MemoryError" in stderr
        or "Killed" in stderr
    )

    return SandboxResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        memory_exceeded=memory_exceeded,
        duration_sec=round(duration, 3),
        args=cmd,
        backend="docker",
    )
