"""Natives System-Audit: Ports, Zombie-Prozesse und Lock-Dateien.

MODULRUECKTRANSFER-PLAN Stufe 5 (Task 1221) fordert ein UNABHAENGIGES
Scannen von Port 8000 (GUI-Server), Port 8081 (BACH_CONTROL_PORT) und
Zombie-Prozessen. Diese Audits laufen bewusst OHNE das externe
``system-explorer``-Modul (sie sind BACH-eigene Gesundheitspruefungen)
und verwenden nur ``psutil``, das ohnehin eine BACH-Erstabhängigkeit ist
(requirements.txt: psutil>=7.0.0).

Oeffentliche API (alle Funktionen fail-soft, werfen nie):
  audit_ports(...)     - belegte/freie Ports + Prozess-Zuordnung
  audit_zombies(...)   - Zombie-Prozesse (Status defunct)
  audit_locks(...)     - Lock-/PID-Dateien im DATA_DIR mit PID-Live-Check
  render_audit_lines() - menschenlesbare Praeflight-Zeilen
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - psutil ist BACH-Pflichtabhaengigkeit
    psutil = None

# Kanonische BACH-Ports (gui/server.py: GUI 127.0.0.1:8000,
# BACH_CONTROL_PORT Default 8081; startup.py:1697 port = 8000)
GUI_PORT = 8000
CONTROL_PORT = 8081
DEFAULT_PORTS = (GUI_PORT, CONTROL_PORT)

PORT_LABELS = {
    GUI_PORT: "GUI-Server",
    CONTROL_PORT: "Control-Port",
}

DEFAULT_LOCK_GLOBS = ("*.lock", "*.pid")

_BACH_CMDLINE_MARKERS = (
    "daemon_service.py",
    "gui/server.py",
    "gui/api/",
    "bach.py",
    "services/bach",
    "/bach/",
    "\\bach\\",
    "mcp serve",
)


@dataclass(frozen=True)
class PortFinding:
    port: int
    label: str
    state: str          # 'free' | 'bach' | 'foreign' | 'unknown'
    pid: int | None = None
    process_name: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ZombieFinding:
    pid: int
    ppid: int | None = None
    name: str | None = None
    bach_related: bool = False


@dataclass(frozen=True)
class LockFinding:
    path: Path
    kind: str            # 'lock' | 'pid'
    state: str           # 'live' | 'stale' | 'foreign' | 'unparseable'
    pids: tuple = field(default_factory=tuple)
    error: str | None = None


def _is_bach_cmdline(cmdline_parts) -> bool:
    """Heuristik: gehoert der Prozess zu BACH?"""
    try:
        joined = " ".join(str(part) for part in cmdline_parts if part)
    except TypeError:
        return False
    return any(marker in joined for marker in _BACH_CMDLINE_MARKERS)


def audit_ports(ports=DEFAULT_PORTS, timeout=0.2) -> list[PortFinding]:
    """Prueft, ob die BACH-Ports frei oder durch Prozesse belegt sind.

    Reihenfolge: connect-Test (hoert dort jemand?), danach Besitzer-
    Identifikation via psutil (nur eigene Prozesse sicher identifizierbar).
    """
    findings: list[PortFinding] = []
    for port in ports:
        label = PORT_LABELS.get(port, f"Port {port}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex(("127.0.0.1", port))
            if result != 0:
                findings.append(PortFinding(port=port, label=label, state="free"))
                continue
        except OSError as exc:
            findings.append(PortFinding(
                port=port, label=label, state="unknown", error=str(exc)))
            continue

        pid, name = _identify_port_owner(port)
        if pid is None:
            findings.append(PortFinding(
                port=port, label=label, state="unknown",
                error="Prozess nicht identifizierbar (Rechte?)"))
            continue

        bach_owner = False
        if psutil is not None:
            try:
                proc = psutil.Process(pid)
                bach_owner = _is_bach_cmdline(proc.cmdline())
                name = name or proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                bach_owner = False
        findings.append(PortFinding(
            port=port, label=label,
            state="bach" if bach_owner else "foreign",
            pid=pid, process_name=name))
    return findings


def _identify_port_owner(port: int):
    """Findet die PID, die an <port> lauscht (best effort).

    psutil.net_connections() verweigert auf macOS ohne Root den Zugriff;
    dort (und nur dort) greift ein lesender lsof-Fallback. Unter Linux und
    Windows liefert psutil die Zuordnung direkt.
    """
    if psutil is not None:
        try:
            connections = psutil.net_connections(kind="inet")
            for conn in connections:
                laddr = getattr(conn, "laddr", None)
                if laddr is None:
                    continue
                if (getattr(laddr, "port", None) == port
                        and conn.status == psutil.CONN_LISTEN
                        and conn.pid):
                    return _pid_and_name(int(conn.pid))
        except (psutil.AccessDenied, psutil.Error, OSError):
            pass  # -> lsof-Fallback
    return _identify_port_owner_lsof(port)


def _identify_port_owner_lsof(port: int):
    """Lesender lsof-Fallback (macOS ohne Root-Rechte)."""
    import shutil
    import subprocess
    import sys

    lsof = shutil.which("lsof")
    if not lsof and sys.platform == "darwin":
        candidate = Path("/usr/sbin/lsof")
        if candidate.exists():
            lsof = str(candidate)
    if not lsof:
        return None, None
    try:
        result = subprocess.run(
            [lsof, "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    for token in result.stdout.split():
        if token.isdigit():
            return _pid_and_name(int(token))
    return None, None


def _pid_and_name(pid: int):
    if psutil is None:
        return pid, None
    try:
        return pid, psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return pid, None


def audit_zombies(limit: int = 50, process_iter=None) -> list[ZombieFinding]:
    """Sammelt Zombie-Prozesse (defunct). BACH-eigene Zombies werden markiert."""
    if psutil is None:
        return []
    if process_iter is None:
        process_iter = psutil.process_iter(
            ["pid", "ppid", "name", "status", "cmdline"])
    findings: list[ZombieFinding] = []
    try:
        for proc in process_iter:
            info = getattr(proc, "info", {}) or {}
            if info.get("status") != getattr(psutil, "STATUS_ZOMBIE", "zombie"):
                continue
            pid = info.get("pid")
            if pid is None:
                continue
            cmdline = info.get("cmdline") or []
            findings.append(ZombieFinding(
                pid=int(pid),
                ppid=info.get("ppid"),
                name=info.get("name"),
                bach_related=_is_bach_cmdline(cmdline),
            ))
            if len(findings) >= limit:
                break
    except Exception:  # fail-soft: Audit darf Preflight nie abstuerzen lassen
        return findings
    return findings


def audit_locks(data_dir=None, lock_globs=DEFAULT_LOCK_GLOBS) -> list[LockFinding]:
    """Prueft Lock-/PID-Dateien im BACH-Datenverzeichnis.

    Zustand je Datei: 'live' (BACH-Prozess haelt sie), 'stale' (alle PIDs tot),
    'foreign' (lebender, nicht-BACH-Prozess) oder 'unparseable'.
    """
    if data_dir is None:
        try:
            from .bach_paths import DATA_DIR
            data_dir = DATA_DIR
        except Exception:
            return []
    data_dir = Path(data_dir)
    if not data_dir.exists():
        return []

    findings: list[LockFinding] = []
    paths = []
    for pattern in lock_globs:
        paths.extend(data_dir.glob(pattern))
    for path in sorted(set(paths)):
        kind = "pid" if path.suffix == ".pid" else "lock"
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            findings.append(LockFinding(
                path=path, kind=kind, state="unparseable", error=str(exc)))
            continue

        pids = _parse_pids(raw)
        if not pids:
            findings.append(LockFinding(
                path=path, kind=kind, state="unparseable",
                error="keine PID lesbar"))
            continue

        live_states = _pid_bach_states(pids)
        if not any(alive for alive, _ in live_states):
            findings.append(LockFinding(
                path=path, kind=kind, state="stale", pids=tuple(pids)))
        elif all(alive and bach for alive, bach in live_states):
            findings.append(LockFinding(
                path=path, kind=kind, state="live", pids=tuple(pids)))
        elif any(alive and bach for alive, bach in live_states):
            findings.append(LockFinding(
                path=path, kind=kind, state="live", pids=tuple(pids)))
        else:
            findings.append(LockFinding(
                path=path, kind=kind, state="foreign", pids=tuple(pids)))
    return findings


def _parse_pids(raw: str) -> list[int]:
    """Extrahiert PIDs aus Lock-Inhalt (int-Text oder JSON mit 'pids')."""
    pids: list[int] = []
    stripped = raw.strip()
    if stripped.isdigit():
        pids.append(int(stripped))
        return pids
    try:
        payload = json.loads(stripped)
    except (ValueError, TypeError):
        # Fallback: erste Zeile, die nur aus Ziffern besteht
        for line in stripped.splitlines():
            if line.strip().isdigit():
                pids.append(int(line.strip()))
                break
        return pids
    if isinstance(payload, dict):
        value = payload.get("pids")
        if isinstance(value, list):
            pids = [int(p) for p in value if str(p).strip().isdigit()]
        elif isinstance(payload.get("pid"), int):
            pids = [int(payload["pid"])]
    return pids


def _pid_bach_states(pids) -> list[tuple[bool, bool]]:
    """Liefert je PID (alive, bach_related)."""
    states: list[tuple[bool, bool]] = []
    if psutil is None:
        # Ohne psutil: Existenz-Test via kill(pid, 0) ist auf Windows nicht
        # portabel -> als 'alive unbekannt' behandeln (fail-soft, kein false
        # 'stale').
        return [(False, False)] * len(pids)
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            alive = True
            bach = _is_bach_cmdline(proc.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            alive, bach = False, False
        states.append((alive, bach))
    return states


def render_audit_lines(
    port_findings: list[PortFinding],
    zombie_findings: list[ZombieFinding],
    lock_findings: list[LockFinding],
) -> list[tuple[str, str]]:
    """Rendert (status, zeile)-Paare fuer den Preflight-Report.

    status: 'OK' | 'WARN' | 'FAIL' | 'INFO'
    """
    lines: list[tuple[str, str]] = []

    for finding in port_findings:
        if finding.state == "free":
            lines.append(("OK", f"Port {finding.port} ({finding.label}): frei"))
        elif finding.state == "bach":
            lines.append((
                "OK",
                f"Port {finding.port} ({finding.label}): belegt durch BACH "
                f"(PID {finding.pid}{_name_suffix(finding)})",
            ))
        elif finding.state == "foreign":
            lines.append((
                "FAIL",
                f"Port {finding.port} ({finding.label}): belegt durch fremden "
                f"Prozess{finding.pid and ' PID ' + str(finding.pid) or ''}"
                f"{_name_suffix(finding)}",
            ))
        else:
            detail = f": {finding.error}" if finding.error else ": Status unklar"
            lines.append(("WARN", f"Port {finding.port} ({finding.label}){detail}"))

    if zombie_findings:
        bach_zombies = [z for z in zombie_findings if z.bach_related]
        example = ", ".join(str(z.pid) for z in zombie_findings[:5])
        hint = ""
        if bach_zombies:
            hint = " - 'bach daemon kill-all' bereinigt BACH-Daemons"
        lines.append((
            "WARN",
            f"Zombie-Prozesse: {len(zombie_findings)} (z.B. PID {example}){hint}",
        ))
    else:
        lines.append(("OK", "Zombie-Prozesse: keine"))

    if lock_findings:
        stale = [f for f in lock_findings if f.state == "stale"]
        foreign = [f for f in lock_findings if f.state == "foreign"]
        live = [f for f in lock_findings if f.state == "live"]
        unparseable = [f for f in lock_findings if f.state == "unparseable"]
        for finding in stale:
            lines.append((
                "WARN",
                f"Verwaiste Lock-Datei: {finding.path.name} "
                f"(PID {', '.join(str(p) for p in finding.pids)} tot)"
                " - 'bach daemon kill-all' bereinigt",
            ))
        for finding in foreign:
            lines.append((
                "WARN",
                f"Lock-Datei {finding.path.name} verweist auf fremden Prozess "
                f"(PID {', '.join(str(p) for p in finding.pids)})",
            ))
        for finding in unparseable:
            detail = f" ({finding.error})" if finding.error else ""
            lines.append((
                "WARN",
                f"Lock-Datei {finding.path.name}: ohne PID, nicht pruefbar{detail}",
            ))
        lines.append((
            "INFO" if not (stale or foreign or unparseable) else "WARN",
            f"Lock-Audit: {len(lock_findings)} Datei(en) geprueft, "
            f"{len(live)} aktiv, {len(stale)} verwaist, "
            f"{len(unparseable)} unklar",
        ))
    else:
        lines.append(("OK", "Lock-Audit: keine Lock-/PID-Dateien im Datenverzeichnis"))

    return lines


def _name_suffix(finding: PortFinding) -> str:
    if finding.process_name:
        return f", {finding.process_name}"
    return ""