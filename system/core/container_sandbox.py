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
core.container_sandbox - Container-Isolation (Sandbox Stufe 3)
==============================================================

ROADMAP Phase 4, Stufe 3: Docker-basierte Container-Isolation als
zusaetzliche Schicht neben Stufe 2 (core.sandbox, rlimit+Watchdog).

Haertung des Containers:
- --network none      : kein Netzwerkzugriff
- --read-only         : Root-Filesystem read-only
- --memory / --cpus   : Ressourcenlimits via cgroups (OS-unabhaengig,
                        loest das Stufe-2-Problem "rlimit OS-spezifisch")
- --pids-limit        : Fork-Bomb-Schutz
- -v workspace:/work  : einziges schreibbares Verzeichnis
- --rm                : Ephemeral, kein Container-Muell

Rollback-Disziplin:
- Bei ContainerUnavailable faellt der Caller auf run_isolated (Stufe 2)
  zurueck — die Aenderung ist rein additiv, kein Umbau von Stufe 2.
- BACH_SANDBOX_CONTAINER_DISABLED=1 (Env) deaktiviert Container sofort
  und hat Vorrang vor dem DB-Modus `sandbox.container_mode`
  (auto|on|off, verwaltet vom Hub-Handler system.hub.sandbox).

Nutzung:
    from core.container_sandbox import run_in_container, docker_available

    if docker_available():
        result = run_in_container("skript.py", limits, workspace)
    else:
        result = run_isolated(["python3", "skript.py"], limits=limits)

Task: 1385
Version: 1.0.0
"""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Sequence, Union

from core.sandbox import SandboxLimits, SandboxResult

# Grace-Zeit zusaetzlich zum Nutzer-Timeout: docker run + Image-Start
# braucht eigene Zeit, sonst wuerde der aeussere subprocess-Timeout
# feuern bevor der Container sein inneres Limit melden kann.
_DOCKER_GRACE_SEC = 15

# Cache fuer docker_available() — docker info bei jedem Call waere
# zu teuer. reset_docker_cache() fuer Tests.
_docker_available_cache: Optional[bool] = None

# Image-Name: per Env ueberschreibbar (Rollback/Experimente)
DEFAULT_CONTAINER_IMAGE = "bach-sandbox:latest"


class ContainerUnavailable(Exception):
    """Docker-Daemon nicht erreichbar oder Image fehlt.

    Der Caller (Hub) faengt diese Exception ab und faellt auf
    core.sandbox.run_isolated (Stufe 2) zurueck.
    """


def container_disabled_by_env() -> bool:
    """Env-Kill-Switch fuer sofortiges Rollback ohne DB-Zugriff."""
    return os.environ.get("BACH_SANDBOX_CONTAINER_DISABLED", "") == "1"


def get_container_image() -> str:
    """Aktives Container-Image (Env BACH_SANDBOX_IMAGE ueberschreibt)."""
    return os.environ.get("BACH_SANDBOX_IMAGE", DEFAULT_CONTAINER_IMAGE)


def reset_docker_cache() -> None:
    """Leert den docker_available-Cache (fuer Tests und Hub-Status-Refresh)."""
    global _docker_available_cache
    _docker_available_cache = None


def docker_available(timeout: int = 3) -> bool:
    """Prueft ob Docker-CLI UND Daemon erreichbar sind (gecacht).

    False wenn:
    - BACH_SANDBOX_CONTAINER_DISABLED=1 (Rollback-Disziplin, Vorrang)
    - docker nicht im PATH
    - `docker info` fehlschlaegt (Daemon down) oder timeout
    """
    global _docker_available_cache
    if container_disabled_by_env():
        return False
    if _docker_available_cache is not None:
        return _docker_available_cache
    if shutil.which("docker") is None:
        _docker_available_cache = False
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=timeout,
        )
        _docker_available_cache = (proc.returncode == 0)
    except (subprocess.TimeoutExpired, OSError):
        _docker_available_cache = False
    return _docker_available_cache


def image_exists(image: Optional[str] = None) -> bool:
    """Prueft ob das Sandbox-Image lokal gebaut ist."""
    img = image or get_container_image()
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", img],
            capture_output=True,
            timeout=5,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def build_image(dockerfile_dir: Union[str, Path] = None,
                image: Optional[str] = None,
                timeout: int = 600) -> tuple:
    """Baut das Sandbox-Image.

    Returns:
        (ok: bool, message: str) — message = letzte docker-Ausgabe.
    """
    if not docker_available():
        return False, "docker nicht verfuegbar (Daemon/CLI oder DISABLED-Env)"
    dockerfile_dir = Path(dockerfile_dir) if dockerfile_dir else (
        Path(__file__).resolve().parent.parent / "sandbox")
    img = image or get_container_image()
    try:
        proc = subprocess.run(
            ["docker", "build", "-t", img, str(dockerfile_dir)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"docker build Timeout nach {timeout}s"
    except OSError as exc:
        return False, f"docker build OSError: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, tail[-1] if tail else f"docker build rc={proc.returncode}"
    return True, f"Image {img} gebaut"


def build_docker_cmd(script_path: Union[str, Path],
                     workspace: Union[str, Path],
                     memory_mb: int = 512,
                     timeout_sec: int = 30,
                     image: Optional[str] = None,
                     network_none: bool = True,
                     extra_env: Optional[Sequence[str]] = None,
                     name: Optional[str] = None) -> list:
    """Baut das docker-run-Kommando fuer ein Skript im Workspace.

    script_path muss innerhalb von workspace liegen (wird relativ zu
    /work gemappt). Liegt es ausserhalb, wird der Dateiname in /work
    erwartet (Fallback, dokumentiert).

    Args:
        name: Optionaler eindeutiger Container-Name; wird nach
            ``docker run`` und vor ``--rm`` eingefuegt.
    """
    img = image or get_container_image()
    ws = Path(workspace).resolve()
    sp = Path(script_path)
    try:
        script_rel = sp.resolve().relative_to(ws).as_posix()
    except (ValueError, OSError):
        script_rel = sp.name

    cmd = ["docker", "run"]
    if name:
        cmd += ["--name", name]
    cmd += [
        "--rm",
        "--read-only",
        "--memory", f"{int(memory_mb)}m",
        "--cpus", "1.0",
        "--pids-limit", "256",
        # tmpfs fuer Python-Temp/-Cache, da Root-FS read-only ist
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "-v", f"{ws}:/work:rw",
        "-w", "/work",
    ]
    if network_none:
        cmd += ["--network", "none"]
    for key in (extra_env or []):
        cmd += ["-e", key]
    # Inneres Timeout: leicht ueber aeusserem Limit ist kontraproduktiv;
    # das Skript soll sich am SandboxLimits-Timeout orientieren. Der
    # aeussere subprocess-Timeout (timeout+Grace) ist der harte Cutoff.
    cmd += [img, "python3", script_rel]
    return cmd


def _decode(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def run_in_container(script: Union[str, Path],
                     limits: Optional[SandboxLimits] = None,
                     workspace: Union[str, Path] = ".",
                     image: Optional[str] = None,
                     extra_env: Optional[Sequence[str]] = None) -> SandboxResult:
    """Fuehrt ein Python-Skript im Container aus (Stufe 3).

    Duck-kompatibles Ergebnis: liefert core.sandbox.SandboxResult.

    Raises:
        ContainerUnavailable: Docker nicht nutzbar oder Image fehlt —
            Caller faellt auf run_isolated (Stufe 2) zurueck.
    """
    limits = limits or SandboxLimits()
    img = image or get_container_image()

    if not docker_available():
        raise ContainerUnavailable(
            "Docker nicht verfuegbar (Daemon/CLI oder BACH_SANDBOX_CONTAINER_DISABLED)")
    if not image_exists(img):
        raise ContainerUnavailable(
            f"Image {img} fehlt — erst 'sandbox container build' ausfuehren")

    container_name = f"bach-sbx-{uuid.uuid4().hex[:12]}"

    mem_mb = limits.memory_mb if limits.memory_mb else 512
    timeout_sec = limits.timeout_sec or 30
    # Workspace-Fallback: Liegt das Skript NICHT im uebergebenen Workspace
    # (z.B. @DOCKER-Tests: workspace=".", Skript in tempfile.mkdtemp; oder
    # Hub-_eval: Skript in SYSTEMTEMP, workspace=base_path), weicht der
    # Mount auf das Skriptverzeichnis aus, damit das Skript in /work landet
    # und build_docker_cmd es via relative_to sauber einhaengt. Caller, deren
    # Skripte im Workspace liegen (Hub _run_file), bleiben unberuehrt.
    try:
        Path(script).resolve().relative_to(Path(workspace).resolve())
    except (ValueError, OSError):
        workspace = Path(script).parent
    cmd = build_docker_cmd(script, workspace, memory_mb=mem_mb,
                           timeout_sec=timeout_sec, image=img,
                           extra_env=extra_env, name=container_name)

    start = time.monotonic()
    timed_out = False
    oserr = None
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + _DOCKER_GRACE_SEC,
        )
        returncode = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = -9
        stdout = _decode(exc.stdout)
        stderr = _decode(exc.stderr) or (
            f"Container-Timeout nach {timeout_sec}s (+{_DOCKER_GRACE_SEC}s Grace)")
    except OSError as exc:
        oserr = exc
    finally:
        # Idempotenter Cleanup: entfernt den Container auch bei Timeout
        # oder Abbruch, falls --rm ihn nicht bereits aufgeraeumt hat.
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            # Cleanup ist best-effort; darf die eigentliche Fehlerbehandlung
            # nicht verschleiern.
            pass
    if oserr:
        raise ContainerUnavailable(f"docker run OSError: {oserr}")
    duration = time.monotonic() - start

    # OOM im Container: Docker meldet Exit 137 (SIGKILL durch OOM-Killer)
    # bzw. "OOMKilled" in der Ausgabe
    memory_exceeded = (returncode == 137) or ("OOMKilled" in stderr)
    # read-only-Verletzungen sind Sandbox-Wirkung, kein Fehler des Wrappers
    return SandboxResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        memory_exceeded=memory_exceeded,
        duration_sec=duration,
        rlimits_applied=False,   # Limits via cgroups, nicht rlimit
        watchdog_active=False,   # cgroup-Limits ersetzen den Watchdog
        backend="docker",
        args=cmd,
    )


def container_status() -> dict:
    """Statusuebersicht fuer `sandbox container status`."""
    img = get_container_image()
    avail = docker_available()
    return {
        "docker_available": avail,
        "disabled_by_env": container_disabled_by_env(),
        "image": img,
        "image_exists": image_exists(img) if avail else False,
        "hardening": ["--network none", "--read-only", "--memory",
                      "--cpus 1.0", "--pids-limit 256", "--rm"],
        "fallback": "core.sandbox.run_isolated (Stufe 2) bei ContainerUnavailable",
    }
