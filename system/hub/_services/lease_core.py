# SPDX-License-Identifier: MIT
"""Neutraler Lease-Kern ohne Task-Bezug (Polaris (Polarstern) P1, BACH #2121).

Gemeinsame Helfer fuer Lease-Dienste: Zeitformat und -parsing, Validierung von
Worker- und Lease-Referenz, Ergebnis-/Ablehnungstyp, TTL-Profil-Konfiguration
und das kanonische Dateimanifest der Sync-Schranke.

``task_lease.py`` nutzt diesen Kern bewusst noch NICHT (Festlegung 7): die
Umstellung des Task-Lease-Hot-Paths ist eine eigene Folge-Task. Das Verhalten
von ``fmt``/``parse_ts``/``validate_worker``/``validate_lease_ref`` ist
deshalb absichtlich deckungsgleich zu den privaten Pendants dort.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}@[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
VERSION_RE = re.compile(r"^[0-9a-f]{64}$")
RESOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class LeaseValidationError(ValueError):
    """Ungueltige Eingabe (HTTP 422)."""


@dataclass
class LeaseResult:
    """Ergebnisobjekt aller Lease-Operationen. ``http_status`` 200 oder 409."""

    payload: dict[str, Any]
    http_status: int = 200

    @property
    def granted(self) -> bool:
        return bool(self.payload.get("granted"))


# ---------------------------------------------------------------------------
# Zeit
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fmt(dt: datetime) -> str:
    """UTC, feste Laenge, lexikografisch vergleichbar: 2026-10-05T00:10:00.000000Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(value: Any) -> datetime | None:
    """Parst gespeicherte Zeitstempel: mit Z/Offset wie angegeben, naiv mit T als
    Ortszeit, naiv mit Leerzeichen (SQLite ``datetime('now')``) als UTC."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    space_form = " " in raw and "T" not in raw
    iso = raw.replace(" ", "T", 1) if space_form else raw
    if iso.endswith(("Z", "z")):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    if space_form:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------

def validate_worker(worker_id: Any, host: Any) -> tuple[str, str]:
    if not isinstance(worker_id, str) or not WORKER_RE.fullmatch(worker_id):
        raise LeaseValidationError("worker_id muss das Format <agent>@<host> haben")
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        raise LeaseValidationError("host ist ungueltig")
    if worker_id.rsplit("@", 1)[1].lower() != host.lower():
        raise LeaseValidationError("host muss dem Hostteil von worker_id entsprechen")
    return worker_id, host


def validate_lease_ref(lease_id: Any, fence: Any) -> tuple[str, int]:
    try:
        parsed = uuid.UUID(str(lease_id))
    except (ValueError, AttributeError, TypeError):
        raise LeaseValidationError("lease_id muss eine UUID sein") from None
    if parsed.version != 4 or str(parsed) != lease_id:
        raise LeaseValidationError("lease_id muss eine kanonische UUIDv4 sein")
    if type(fence) is not int or fence <= 0:
        raise LeaseValidationError("fence muss eine positive Ganzzahl sein")
    return lease_id, fence


def validate_resource_name(name: Any) -> str:
    if not isinstance(name, str) or not RESOURCE_RE.fullmatch(name):
        raise LeaseValidationError("resource muss [a-z0-9._-], max. 64 Zeichen, haben")
    return name


def validate_request_id(request_id: Any) -> str:
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise LeaseValidationError("request_id muss 16-128 Zeichen [A-Za-z0-9._:-] haben")
    return request_id


def validate_version(value: Any) -> str | None:
    """``resource_version``/Manifest-Hash: None oder SHA-256-Hex."""
    if value is None:
        return None
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise LeaseValidationError("resource_version muss ein SHA-256-Hex-Wert sein")
    return value


def deny(reason: str, now: datetime, **extra: Any) -> LeaseResult:
    """Ablehnung ist ein Ergebnis, kein Fehler (HTTP 409)."""
    return LeaseResult({"granted": False, "reason": reason, **extra, "server_now": fmt(now)}, http_status=409)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

def load_profiles(defaults: Mapping[str, tuple[int, int]], env_var: str,
                  environ: Mapping[str, str]) -> dict[str, tuple[int, int]]:
    """Liest ``{"NAME": [ttl, max_total]}`` aus ``env_var``. Ungueltiges wird
    ganz verworfen (fail-safe, kein Teilzustand); nur bekannte Profile zaehlen."""
    profiles = dict(defaults)
    raw = environ.get(env_var)
    if not raw:
        return profiles
    try:
        candidate = {}
        for name, pair in json.loads(raw).items():
            ttl, max_total = int(pair[0]), int(pair[1])
            if name not in defaults or not 0 < ttl <= max_total:
                raise ValueError(name)
            candidate[name] = (ttl, max_total)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return dict(defaults)
    profiles.update(candidate)
    return profiles


def env_seconds(environ: Mapping[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(environ[name])
    except (KeyError, ValueError):
        return default
    return value if value >= minimum else default


# ---------------------------------------------------------------------------
# Kanonisches Manifest (Sync-Schranke, Festlegung 6)
# ---------------------------------------------------------------------------

def manifest_version(root: Path | str, paths: Iterable[str]) -> str:
    """SHA-256 ueber ein kanonisches Manifest: sortierte relative Pfade (``/``),
    Groesse und SHA-256 jeder Datei; fehlende Dateien gehen als ``MISSING`` ein.
    Ordner in ``paths`` werden rekursiv in ihre Dateien aufgeloest; ein fehlender
    Ordner zaehlt als fehlend. Die Pfadliste ist Teil des Vertrags der Ressource."""
    base = Path(root)
    entries: dict[str, str] = {}
    for rel in paths:
        target = base / rel
        key = Path(rel).as_posix()
        if target.is_dir():
            for sub in sorted(p for p in target.rglob("*") if p.is_file()):
                entries[sub.relative_to(base).as_posix()] = _file_line(sub)
        elif target.is_file():
            entries[key] = _file_line(target)
        else:
            entries[key] = "MISSING"
    body = "".join(f"{key}\t{entries[key]}\n" for key in sorted(entries))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_line(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"{path.stat().st_size}\t{digest.hexdigest()}"
