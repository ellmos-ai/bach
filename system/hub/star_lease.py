"""Polaris Stern-Lease (Ebene 2) fuer BACH-Hub-Mutationen.

Rekonstruktion gem. Task #3746 auf Grundlage von:

- system/hub/star_lease_INTEGRATION.md (API-Spezifikation: Schichtenmodell,
  Fehlerklassen mit CLI-Tags, Parameter DEFAULT_TTL / MAX_ACQUIRE_ATTEMPTS)
- system/hub/lease.py (CLI-Semantik der Aktionen acquire/renew/release/
  status/register, Erfolgsmeldungen "[OK] ...", Haltestatus-Beleg
  "[OWN POLARIS STAR CONFIRMED]")

Abgrenzung (INTEGRATION.md, Abschnitte "Abgrenzung" und "Freigabestatus"):

- Kein LeaseManager als Python-Klasse: die Anbindung ist ausschliesslich
  CLI-basiert ueber die lease.py-Aktionen (`bach polaris <resource> <action>`).
- Eine Integration in schreibende Komponenten (writer.py u.a.) ist ausdruecklich
  NICHT Bestandteil dieses Baums; die Polarstern-Freigabe ist nicht erteilt.
- Alle Mutationen muessen die Schichtenreihenfolge einhalten:

    Ebene 1: MUTATION_LOCK (threading.RLock, prozessintern)
    Ebene 2: Stern-Lease (prozessuebergreifend) - erst NACH Ebene 1

  Grundregel:  acquire -> try { check_fence(), mutate() } finally { release() }
  Das Ignorieren dieser Reihenfolge kann Deadlocks oder inkonsistente
  Zustaende verursachen (INTEGRATION.md "Haftungsausschluss").

Fehlerklassen (CLI-Tags, siehe lease.py-Fehlermapping):
- LeaseDeniedError      -> "[CONFLICT]"    nicht mutieren; Vorgang abbrechen/ablehnen
- LeaseUnavailableError -> "[UNAVAILABLE]" retry bis verfuegbar (Exponential Backoff)
- LeaseViolation        -> "[VIOLATION]"   nur loggen; niemals weiterschreiben

Parameter:
- DEFAULT_TTL = 30.0       Uebergabe an acquire, wenn kein ttl explizit gesetzt ist
- MAX_ACQUIRE_ATTEMPTS = 3 Versuche beim acquire, mit Exponential Backoff dazwischen
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "BASE_BACKOFF_SECONDS",
    "DEFAULT_TTL",
    "MAX_ACQUIRE_ATTEMPTS",
    "MUTATION_LOCK",
    "LeaseDeniedError",
    "LeaseHandle",
    "LeaseUnavailableError",
    "LeaseViolation",
    "StarLeaseError",
    "acquire",
    "check_fence",
    "default_runner",
    "mutation_lock_held",
    "mutate",
    "register",
    "release",
    "renew",
    "status",
]

DEFAULT_TTL = 30.0
MAX_ACQUIRE_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 0.5
OWN_STAR_TAG = "[OWN POLARIS STAR CONFIRMED]"

# Ebene 1: prozessinterne Mutationssperre - IMMER vor der Stern-Lease (Ebene 2) halten.
MUTATION_LOCK = threading.RLock()

# Runner-Schnittstelle: (resource, action, opts) -> (ok, message)
Runner = Callable[[str, str, Dict[str, Any]], Tuple[bool, str]]

# Meldungsmuster laut lease.py: acquire/renew/release nutzen "Fence <n>",
# die status-Zeile nutzt "Fence=<n>".
_FENCE_RE = re.compile(r"Fence[= ](\d+)")
_LEASE_ID_RE = re.compile(r"Lease-Capability: (\S+)")
_RENEW_AFTER_RE = re.compile(r"Renew alle (\d+)s")
_PROFILE_RE = re.compile(r"Profil ([^,\s)]+)")
_EXPIRES_RE = re.compile(r"Frist bis ([^,\s)]+)")
_STATUS_RE = re.compile(
    r"^(\S+): Leased=(\w+), Fence=(\d+), Version=(\S+), Server aktiv=(\w+)",
    re.MULTILINE,
)
_HOLDER_RE = re.compile(r"^Halter: (\S+) \(([^)]*)\), Ablauf (\S+)", re.MULTILINE)


class StarLeaseError(RuntimeError):
    """Basisklasse aller Stern-Lease-Fehler (unbekanntes Mapping -> "[ERROR]")."""

    TAG = "[ERROR]"

    def __init__(self, message: str) -> None:
        text = str(message).strip()
        if not text.startswith("["):
            text = f"{self.TAG} {text}"
        super().__init__(text)


class LeaseDeniedError(StarLeaseError):
    """Lease abgelehnt ("[CONFLICT]"): nicht mutieren; Vorgang abbrechen/ablehnen."""

    TAG = "[CONFLICT]"


class LeaseUnavailableError(StarLeaseError):
    """Lease nicht verfuegbar ("[UNAVAILABLE]"): retry mit Backoff bis verfuegbar."""

    TAG = "[UNAVAILABLE]"


class LeaseViolation(StarLeaseError):
    """Lease-Verletzt ("[VIOLATION]"): nur loggen; niemals weiterschreiben."""

    TAG = "[VIOLATION]"


class LeaseHandle:
    """Gehaltener Stern-Lease: Identitaet plus aktuelles Fence-Token."""

    def __init__(self, resource: str, lease_id: str, fence: int, *,
                 ttl_profile: Optional[str] = None,
                 renew_after_seconds: Optional[int] = None,
                 expires_at: Optional[str] = None,
                 intent: str = "") -> None:
        self.resource = resource
        self.lease_id = lease_id
        self.fence = fence
        self.ttl_profile = ttl_profile
        self.renew_after_seconds = renew_after_seconds
        self.expires_at = expires_at
        self.intent = intent

    def __repr__(self) -> str:  # pragma: no cover - rein informativ
        return (f"LeaseHandle(resource={self.resource!r}, lease_id={self.lease_id!r}, "
                f"fence={self.fence}, ttl_profile={self.ttl_profile!r})")


def _split_tag(text: str) -> Tuple[str, str]:
    """Teilt "[TAG] rest" in (TAG, rest); ohne Tag: ("", text)."""
    text = (text or "").strip()
    if text.startswith("[") and "]" in text:
        tag, _, rest = text.partition("]")
        return tag[1:].strip(), rest.strip()
    return "", text.strip()


def _match_int(regex, message: str, fallback: Optional[int] = None) -> Optional[int]:
    m = regex.search(message or "")
    return int(m.group(1)) if m else fallback


def _match_str(regex, message: str, fallback: Optional[str] = None) -> Optional[str]:
    m = regex.search(message or "")
    return m.group(1) if m else fallback


def _raise_failure(operation: str, message: str) -> None:
    """Mappt eine CLI-Fehlermeldung auf die Doku-Fehlerklassen."""
    text = (message or "").strip()
    tag, body = _split_tag(text)
    context = f"{operation}: {body if tag else text}"
    if tag == "CONFLICT":
        raise LeaseDeniedError(context)
    if tag == "UNAVAILABLE":
        raise LeaseUnavailableError(context)
    if tag == "VIOLATION":
        raise LeaseViolation(context)
    raise StarLeaseError(text if text.startswith("[") else f"{operation}: {text}")


def default_runner(resource: str, action: str, opts: Optional[Dict[str, Any]] = None
                   ) -> Tuple[bool, str]:
    """Standard-Runner: ruft die lease.py-Aktionen CLI-basiert auf
    (`bach polaris <resource> <action> [--option [wert]]`)."""
    argv: List[str] = ["bach", "polaris", str(resource), str(action)]
    for key, value in (opts or {}).items():
        if value is None or value == "" or value is False:
            continue
        if value is True:
            argv.append(f"--{key}")
        else:
            argv.extend([f"--{key}", str(value)])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"[ERROR] {action}: CLI-Aufruf fehlgeschlagen ({exc})"
    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    return proc.returncode == 0, combined.strip()


def mutation_lock_held() -> bool:
    """True, wenn MUTATION_LOCK (Ebene 1) vom aufrufenden Thread gehalten wird."""
    try:
        return bool(MUTATION_LOCK._is_owned())  # noqa: SLF001 - CPython-RLock-Detail
    except AttributeError:  # pragma: no cover - Nicht-CPython-RLock
        return False


def acquire(resource: str, by: str, *, host: Optional[str] = None,
            ttl: Optional[float] = None, intent: str = "",
            version: Optional[str] = None, show_capability: bool = True,
            runner: Optional[Runner] = None,
            pause: Callable[[float], None] = time.sleep) -> LeaseHandle:
    """Ebene 2: Stern-Lease via lease.py-Aktion acquire holen.

    Retry nur bei "[UNAVAILABLE]" (bis MAX_ACQUIRE_ATTEMPTS) mit Exponential
    Backoff; "[CONFLICT]" fuehrt sofort zu LeaseDeniedError (nicht mutieren).
    """
    runner = runner or default_runner
    opts: Dict[str, Any] = {
        "by": by,
        "intent": intent,
        # ttl bleibt unveraendert als DEFAULT_TTL-Uebergabe (Sekunden) formatiert.
        "ttl": str(ttl if ttl is not None else DEFAULT_TTL),
    }
    if host:
        opts["host"] = host
    if version:
        opts["version"] = version
    if show_capability:
        opts["show-capability"] = True

    last_error: Optional[LeaseUnavailableError] = None
    for attempt in range(1, MAX_ACQUIRE_ATTEMPTS + 1):
        ok, message = runner(resource, "acquire", opts)
        text = (message or "").strip()
        if ok:
            lease_id = _match_str(_LEASE_ID_RE, text)
            if not lease_id:
                raise StarLeaseError(f"acquire: Meldung ohne Lease-Capability: {text}")
            fence = _match_int(_FENCE_RE, text)
            if fence is None:
                raise StarLeaseError(f"acquire: Meldung ohne Fence: {text}")
            return LeaseHandle(
                resource, lease_id, fence,
                ttl_profile=_match_str(_PROFILE_RE, text),
                renew_after_seconds=_match_int(_RENEW_AFTER_RE, text),
                expires_at=_match_str(_EXPIRES_RE, text),
                intent=intent,
            )
        tag, body = _split_tag(text)
        if tag == "CONFLICT":
            raise LeaseDeniedError(f"acquire: {body}")
        if tag != "UNAVAILABLE":
            raise StarLeaseError(f"acquire: {text}")
        last_error = LeaseUnavailableError(f"acquire: {body}")
        if attempt < MAX_ACQUIRE_ATTEMPTS:
            pause(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    assert last_error is not None  # Versuchsanzahl >= 1
    raise last_error


def check_fence(lease: LeaseHandle, runner: Optional[Runner] = None) -> int:
    """Vor jeder Mutation pruefen, dass der eigene Stern-Lease noch haelt.

    Liest den status ueber die lease.py-CLI: ohne
    "[OWN POLARIS STAR CONFIRMED]" oder bei Fence-Divergenz -> LeaseViolation.
    """
    runner = runner or default_runner
    ok, message = runner(lease.resource, "status", {"lease-id": lease.lease_id})
    text = (message or "").strip()
    if not ok:
        raise StarLeaseError(f"check_fence: {text}")
    if OWN_STAR_TAG not in text:
        raise LeaseViolation(
            f"check_fence: Stern-Lease {lease.lease_id} haelt nicht mehr "
            f"fuer {lease.resource}"
        )
    fence = _match_int(_FENCE_RE, text)
    if fence is None or fence != lease.fence:
        raise LeaseViolation(
            f"check_fence: Fence-Divergenz bei {lease.resource}: "
            f"gehalten {lease.fence}, aktiv {fence}"
        )
    return fence


def renew(lease: LeaseHandle, *, version: Optional[str] = None,
          runner: Optional[Runner] = None) -> LeaseHandle:
    """Verlaengert den Stern-Lease (lease.py-Aktion renew) und aktualisiert den Fence."""
    runner = runner or default_runner
    opts: Dict[str, Any] = {"lease-id": lease.lease_id, "fence": str(lease.fence)}
    if version:
        opts["version"] = version
    ok, message = runner(lease.resource, "renew", opts)
    if not ok:
        _raise_failure("renew", message)
    lease.fence = _match_int(_FENCE_RE, message or "", lease.fence)
    return lease


def release(lease: LeaseHandle, *, version: Optional[str] = None,
            runner: Optional[Runner] = None) -> str:
    """Gibt den Stern-Lease zurueck (lease.py-Aktion release)."""
    runner = runner or default_runner
    opts: Dict[str, Any] = {"lease-id": lease.lease_id, "fence": str(lease.fence)}
    if version:
        opts["version"] = version
    ok, message = runner(lease.resource, "release", opts)
    if not ok:
        _raise_failure("release", message)
    return (message or "").strip()


def status(resource: str, *, lease_id: Optional[str] = None,
           runner: Optional[Runner] = None) -> Dict[str, Any]:
    """Liest den Lease-Status (lease.py-Aktion status, inkl. Own-Beleg)."""
    runner = runner or default_runner
    opts: Dict[str, Any] = {"lease-id": lease_id} if lease_id else {}
    ok, message = runner(resource, "status", opts)
    if not ok:
        _raise_failure("status", message)
    text = (message or "").strip()
    info: Dict[str, Any] = {
        "resource": resource, "leased": False, "fence": None, "version": None,
        "server_active": False, "holder": None, "role": None, "expires_at": None,
        "own": OWN_STAR_TAG in text, "raw": text,
    }
    header = _STATUS_RE.search(text)
    if header:
        info["resource"] = header.group(1)
        info["leased"] = header.group(2).lower() == "true"
        info["fence"] = int(header.group(3))
        info["version"] = header.group(4)
        info["server_active"] = header.group(5).lower() == "true"
    holder = _HOLDER_RE.search(text)
    if holder:
        info["holder"] = holder.group(1)
        info["role"] = holder.group(2)
        info["expires_at"] = holder.group(3)
    return info


def register(resource: str, *, allowed_workers: Optional[Sequence[str]] = None,
             device_bindings: Optional[Dict[str, Sequence[str]]] = None,
             server_role: str = "", standby_roles: Optional[Sequence[str]] = None,
             runner: Optional[Runner] = None) -> str:
    """Registriert die Ressource (lease.py-Aktion register; nur Lead-Authority)."""
    runner = runner or default_runner
    opts: Dict[str, Any] = {}
    bind_parts = [
        f"{device}={pattern}"
        for device, patterns in (device_bindings or {}).items()
        for pattern in patterns
    ]
    if bind_parts:
        opts["bind"] = ",".join(bind_parts)
    if allowed_workers:
        opts["allowed"] = ",".join(allowed_workers)
    if server_role:
        opts["server-role"] = server_role
    if standby_roles:
        opts["standby"] = ",".join(standby_roles)
    ok, message = runner(resource, "register", opts)
    if not ok:
        _raise_failure("register", message)
    return (message or "").strip()


def mutate(resource: str, by: str, callback: Callable[[LeaseHandle], Any], *,
           host: Optional[str] = None, ttl: Optional[float] = None,
           intent: str = "", version: Optional[str] = None,
           runner: Optional[Runner] = None,
           pause: Callable[[float], None] = time.sleep) -> Any:
    """Grundregel laut INTEGRATION.md, in korrekter Schichtenreihenfolge:

    Ebene 1: MUTATION_LOCK (RLock) halten
    Ebene 2: acquire(...)            -> prozessuebergreifende Stern-Lease
             try { check_fence(), callback(lease) } finaliy { release(lease) }
    """
    runner = runner or default_runner
    with MUTATION_LOCK:
        lease = acquire(resource, by, host=host, ttl=ttl, intent=intent,
                        version=version, runner=runner, pause=pause)
        try:
            check_fence(lease, runner=runner)
            return callback(lease)
        finally:
            try:
                release(lease, runner=runner)
            except Exception:
                # Freigabefehler duerfen den Fehler der Mutation nicht maskieren.
                pass
