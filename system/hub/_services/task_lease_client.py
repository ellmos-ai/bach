# SPDX-License-Identifier: MIT
"""Einheitlicher Client-Adapter für Salt-Leases der BACH-TaskDB (BACH #1722, T793 LEASE 3/4).

Bietet eine gemeinsame Abstraktion für alle Task-Claim-Clients (CLI, bach_api, Trithon,
künftige Ocean- und Task-Master-Worker) gemäss Vertrag:
``docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md``.

Unterstützt zwei Betriebsmodi:
1. **Lokal / Embedded (Direct SQLite Driver):**
   Wird verwendet, wenn der Prozess direkt auf dem Rheingold-Lead (Mac Studio)
   oder in isolierten Tests/Entwicklungsumgebungen läuft. Ruft atomar die Funktionen
   aus ``hub._services.task_lease`` auf.
2. **Entfernt / HTTP (Remote Lead Driver):**
   Wird verwendet, wenn der Host als Worker konfiguriert ist (z. B. auf ASUS-GEI
   oder WORKSTATION-LG mit ``lead_url``). Führt HTTP-Anfragen gegen
   ``/api/tasks/{id}/lease[/renew|/release]`` mit Authentifizierung und Timeouts aus.

Besondere Eigenschaften:
- Berechnet für Offline-Holder die lokale Sicherheitsfrist:
  ``local_deadline = local_receive_time + (expires_at - server_now) - 60s`` (Vertrag §8.1).
- Fail-Closed: Veraltete Fences, abgelaufene Leases oder Lease-Konflikte lösen
  spezifische Exceptions aus, die eine unberechtigte Task-Modifikation verhindern.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

try:
    from hub._services.task_lease import (
        DEFAULT_PROFILE,
        LeaseConfig,
        LeaseResult,
        acquire_lease,
        ensure_task_lease_schema,
        parse_ts,
        read_lease,
        release_lease,
        renew_lease,
    )
except ImportError:  # pragma: no cover
    from .task_lease import (  # type: ignore
        DEFAULT_PROFILE,
        LeaseConfig,
        LeaseResult,
        acquire_lease,
        ensure_task_lease_schema,
        parse_ts,
        read_lease,
        release_lease,
        renew_lease,
    )

try:
    from hub.rheingold import get_lead_config
except ImportError:  # pragma: no cover
    def get_lead_config() -> dict[str, Any]:
        return {"mode": "isolated", "lead_url": None}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LeaseError(Exception):
    """Basisklasse für alle Client-Lease-Fehler."""


class LeaseDeniedError(LeaseError):
    """Lease wurde von der Authority abgelehnt (HTTP 409)."""

    def __init__(self, task_id: int, reason: str, payload: dict[str, Any]):
        super().__init__(f"Task {task_id}: Lease abgelehnt ({reason})")
        self.task_id = task_id
        self.reason = reason
        self.payload = payload


class LeaseStaleFenceError(LeaseDeniedError):
    """Fence passt nicht zur aktuellen Lease-Epoche (stale_fence)."""


class LeaseExpiredError(LeaseDeniedError):
    """Lease ist bereits abgelaufen (expired)."""


class LeaseMaxTotalReachedError(LeaseDeniedError):
    """Maximale Gesamtlaufzeit des TTL-Profils erreicht."""


class LeaseConnectionError(LeaseError):
    """Verbindung zum Lead-Server fehlgeschlagen oder Timeout."""


class LeaseOfflineDeadlineExceeded(LeaseError):
    """Lokale Sicherheitsfrist (local_deadline) für Offline-Arbeit überschritten."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

def _calc_local_deadline(
    issued_at_str: Optional[str],
    expires_at_str: Optional[str],
    server_now_str: Optional[str],
    local_receive_time: datetime,
) -> datetime:
    """Berechnet local_deadline gemäss Vertrag §8.1:
    local_deadline = local_receive_time + (expires_at - server_now) - 60s
    """
    exp = parse_ts(expires_at_str)
    s_now = parse_ts(server_now_str)
    if exp and s_now:
        ttl_left = max(timedelta(0), exp - s_now)
        safety_margin = timedelta(seconds=60)
        # Wenn Frist kürzer als Sicherheitsmarge, nimm verbleibende Zeit ohne Marge
        if ttl_left > safety_margin:
            return local_receive_time + (ttl_left - safety_margin)
        return local_receive_time + ttl_left
    # Fallback: 29 Minuten ab Empfang
    return local_receive_time + timedelta(seconds=1740)


@dataclass(frozen=True)
class LeaseAck:
    """Erfolgreiche Lease-Erteilung oder -Verlängerung (Vertrag §5.1 / §5.3)."""

    task_id: int
    lease_id: str
    fence: int
    worker_id: str
    host: str
    issued_at: str
    expires_at: str
    ttl_profile: str
    server_now: str
    local_receive_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    local_deadline: datetime = field(init=False)
    replayed: bool = False

    def __post_init__(self) -> None:
        deadline = _calc_local_deadline(
            self.issued_at,
            self.expires_at,
            self.server_now,
            self.local_receive_time,
        )
        object.__setattr__(self, "local_deadline", deadline)

    @property
    def is_locally_valid(self) -> bool:
        """Prüft, ob die lokale Arbeitsfrist (Vertrag §8.1/§8.2) noch nicht abgelaufen ist."""
        return datetime.now(timezone.utc) < self.local_deadline

    def assert_locally_valid(self) -> None:
        """Fail-closed Guard vor schreibenden Operationen."""
        if not self.is_locally_valid:
            raise LeaseOfflineDeadlineExceeded(
                f"Task {self.task_id}: local_deadline ({self.local_deadline.isoformat()}) "
                f"ist abgelaufen. Keine weiteren lokalen Schreiboperationen erlaubt."
            )


@dataclass(frozen=True)
class LeaseHolderView:
    """Holder-Ansicht einer Task (Vertrag §5.2)."""

    task_id: int
    status: Optional[str]
    leased: bool
    fence: int
    legacy: bool
    server_now: str
    holder: Optional[dict[str, Any]] = None
    issued_at: Optional[str] = None
    expires_at: Optional[str] = None
    ttl_profile: Optional[str] = None
    own: bool = False


@dataclass(frozen=True)
class LeaseReleaseAck:
    """Bestätigung der Lease-Freigabe (Vertrag §5.4)."""

    released: bool
    task_id: int
    outcome: str
    status: Optional[str]
    fence: int
    server_now: str


# ---------------------------------------------------------------------------
# TaskLeaseClient
# ---------------------------------------------------------------------------

class TaskLeaseClient:
    """Einheitlicher Client für Lease-Operationen."""

    def __init__(
        self,
        *,
        conn: Optional[sqlite3.Connection] = None,
        db_path: Optional[str | Path] = None,
        lead_url: Optional[str] = None,
        device_token: Optional[str] = None,
        timeout: float = 8.0,
    ) -> None:
        self._conn = conn
        self._db_path = Path(db_path) if db_path else None
        self._device_token = device_token or os.environ.get("BACH_DEVICE_TOKEN")
        self._timeout = timeout

        # Modus ermitteln
        if lead_url:
            self._lead_url = lead_url.rstrip("/")
            self._mode = "remote"
        elif conn is not None or db_path is not None:
            self._lead_url = None
            self._mode = "local"
        else:
            cfg = get_lead_config()
            if cfg.get("mode") == "worker" and cfg.get("lead_url"):
                self._lead_url = str(cfg["lead_url"]).rstrip("/")
                self._mode = "remote"
            else:
                self._lead_url = None
                self._mode = "local"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def lead_url(self) -> Optional[str]:
        return self._lead_url

    # -----------------------------------------------------------------------
    # Lokale Verbindungshilfe
    # -----------------------------------------------------------------------

    def _get_local_connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._db_path is not None:
            conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            return conn
        # Standard: ~/.bach/bach.db
        default_db = Path.home() / ".bach" / "bach.db"
        conn = sqlite3.connect(str(default_db), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    # -----------------------------------------------------------------------
    # HTTP-Hilfen
    # -----------------------------------------------------------------------

    def _http_request(
        self,
        method: str,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, dict[str, Any]]:
        assert self._lead_url is not None
        url = f"{self._lead_url}{path}"
        req_headers = {"Accept": "application/json"}
        if self._device_token:
            req_headers["X-Device-Token"] = self._device_token
        if headers:
            req_headers.update(headers)

        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
                return status, json.loads(body) if body else {}
        except urllib.error.HTTPError as err:
            status = err.code
            body = err.read().decode("utf-8")
            try:
                parsed = json.loads(body) if body else {}
            except Exception:
                parsed = {"detail": body}
            return status, parsed
        except urllib.error.URLError as err:
            raise LeaseConnectionError(f"Verbindung zu {url} fehlgeschlagen: {err.reason}") from err
        except Exception as err:
            raise LeaseConnectionError(f"Netzwerkfehler bei {url}: {err}") from err

    # -----------------------------------------------------------------------
    # Operation: Acquire
    # -----------------------------------------------------------------------

    def acquire(
        self,
        task_id: int,
        *,
        worker_id: str,
        host: str,
        request_id: Optional[str] = None,
        ttl_profile: str = "M",
        intent: str = "",
        config: Optional[LeaseConfig] = None,
        now: Optional[datetime] = None,
    ) -> LeaseAck:
        """Beansprucht eine Task als gefencten Lease (Vertrag §5.1)."""
        req_id = request_id or str(uuid.uuid4())
        receive_time = datetime.now(timezone.utc)

        if self._mode == "local":
            conn = self._get_local_connection()
            try:
                res: LeaseResult = acquire_lease(
                    conn,
                    task_id,
                    worker_id=worker_id,
                    host=host,
                    request_id=req_id,
                    ttl_profile=ttl_profile,
                    intent=intent,
                    config=config,
                    now=now,
                )
                if not res.granted:
                    self._raise_denied(task_id, res.payload)
                data = res.payload
                return LeaseAck(
                    task_id=data["task_id"],
                    lease_id=data["lease_id"],
                    fence=int(data["fence"]),
                    worker_id=data["worker_id"],
                    host=data["host"],
                    issued_at=data["issued_at"],
                    expires_at=data["expires_at"],
                    ttl_profile=data["ttl_profile"],
                    server_now=data["server_now"],
                    local_receive_time=receive_time,
                    replayed=bool(data.get("replayed")),
                )
            finally:
                if self._conn is None:
                    conn.close()

        # Remote / HTTP
        body = {
            "worker_id": worker_id,
            "host": host,
            "request_id": req_id,
            "ttl_profile": ttl_profile,
            "intent": intent,
        }
        status, data = self._http_request("POST", f"/api/tasks/{task_id}/lease", payload=body)
        if status == 200 and data.get("granted"):
            return LeaseAck(
                task_id=data["task_id"],
                lease_id=data["lease_id"],
                fence=int(data["fence"]),
                worker_id=data["worker_id"],
                host=data["host"],
                issued_at=data["issued_at"],
                expires_at=data["expires_at"],
                ttl_profile=data["ttl_profile"],
                server_now=data["server_now"],
                local_receive_time=receive_time,
                replayed=bool(data.get("replayed")),
            )
        self._raise_denied(task_id, data)

    # -----------------------------------------------------------------------
    # Operation: Read
    # -----------------------------------------------------------------------

    def read(
        self,
        task_id: int,
        *,
        lease_id: Optional[str] = None,
        config: Optional[LeaseConfig] = None,
        now: Optional[datetime] = None,
    ) -> LeaseHolderView:
        """Liest die Holder-Ansicht einer Task (Vertrag §5.2)."""
        if self._mode == "local":
            conn = self._get_local_connection()
            try:
                res: LeaseResult = read_lease(
                    conn,
                    task_id,
                    lease_id=lease_id,
                    config=config,
                    now=now,
                )
                data = res.payload
                return LeaseHolderView(
                    task_id=data["task_id"],
                    status=data.get("status"),
                    leased=bool(data.get("leased")),
                    fence=int(data.get("fence") or 0),
                    legacy=bool(data.get("legacy")),
                    server_now=data.get("server_now", ""),
                    holder=data.get("holder"),
                    issued_at=data.get("issued_at"),
                    expires_at=data.get("expires_at"),
                    ttl_profile=data.get("ttl_profile"),
                    own=bool(data.get("own")),
                )
            finally:
                if self._conn is None:
                    conn.close()

        # Remote / HTTP
        headers = {}
        if lease_id:
            headers["X-Lease-Id"] = lease_id
        status, data = self._http_request("GET", f"/api/tasks/{task_id}/lease", headers=headers)
        if status == 200:
            return LeaseHolderView(
                task_id=data["task_id"],
                status=data.get("status"),
                leased=bool(data.get("leased")),
                fence=int(data.get("fence") or 0),
                legacy=bool(data.get("legacy")),
                server_now=data.get("server_now", ""),
                holder=data.get("holder"),
                issued_at=data.get("issued_at"),
                expires_at=data.get("expires_at"),
                ttl_profile=data.get("ttl_profile"),
                own=bool(data.get("own")),
            )
        self._raise_denied(task_id, data)

    # -----------------------------------------------------------------------
    # Operation: Renew
    # -----------------------------------------------------------------------

    def renew(
        self,
        task_id: int,
        *,
        lease_id: str,
        fence: int,
        config: Optional[LeaseConfig] = None,
        now: Optional[datetime] = None,
    ) -> LeaseAck:
        """Verlängert einen bestehenden Lease (Vertrag §5.3)."""
        receive_time = datetime.now(timezone.utc)

        if self._mode == "local":
            conn = self._get_local_connection()
            try:
                res: LeaseResult = renew_lease(
                    conn,
                    task_id,
                    lease_id=lease_id,
                    fence=fence,
                    config=config,
                    now=now,
                )
                if not res.granted:
                    self._raise_denied(task_id, res.payload)
                data = res.payload
                return LeaseAck(
                    task_id=data["task_id"],
                    lease_id=data["lease_id"],
                    fence=int(data["fence"]),
                    worker_id=data["worker_id"],
                    host=data["host"],
                    issued_at=data["issued_at"],
                    expires_at=data["expires_at"],
                    ttl_profile=data["ttl_profile"],
                    server_now=data["server_now"],
                    local_receive_time=receive_time,
                )
            finally:
                if self._conn is None:
                    conn.close()

        # Remote / HTTP
        body = {"lease_id": lease_id, "fence": fence}
        status, data = self._http_request("POST", f"/api/tasks/{task_id}/lease/renew", payload=body)
        if status == 200 and data.get("granted"):
            return LeaseAck(
                task_id=data["task_id"],
                lease_id=data["lease_id"],
                fence=int(data["fence"]),
                worker_id=data["worker_id"],
                host=data["host"],
                issued_at=data["issued_at"],
                expires_at=data["expires_at"],
                ttl_profile=data["ttl_profile"],
                server_now=data["server_now"],
                local_receive_time=receive_time,
            )
        self._raise_denied(task_id, data)

    # -----------------------------------------------------------------------
    # Operation: Release
    # -----------------------------------------------------------------------

    def release(
        self,
        task_id: int,
        *,
        lease_id: str,
        fence: int,
        outcome: str = "done",
        result_ref: str = "",
        note: str = "",
        config: Optional[LeaseConfig] = None,
        now: Optional[datetime] = None,
    ) -> LeaseReleaseAck:
        """Gibt einen Lease frei oder schliesst die Task ab (Vertrag §5.4)."""
        if self._mode == "local":
            conn = self._get_local_connection()
            try:
                res: LeaseResult = release_lease(
                    conn,
                    task_id,
                    lease_id=lease_id,
                    fence=fence,
                    outcome=outcome,
                    result_ref=result_ref,
                    note=note,
                    config=config,
                    now=now,
                )
                if res.http_status != 200 or not res.payload.get("released"):
                    self._raise_denied(task_id, res.payload)
                data = res.payload
                return LeaseReleaseAck(
                    released=bool(data.get("released")),
                    task_id=data["task_id"],
                    outcome=data["outcome"],
                    status=data.get("status"),
                    fence=int(data["fence"]),
                    server_now=data["server_now"],
                )
            finally:
                if self._conn is None:
                    conn.close()

        # Remote / HTTP
        body = {
            "lease_id": lease_id,
            "fence": fence,
            "outcome": outcome,
            "result_ref": result_ref,
            "note": note,
        }
        status, data = self._http_request("POST", f"/api/tasks/{task_id}/lease/release", payload=body)
        if status == 200 and data.get("released"):
            return LeaseReleaseAck(
                released=bool(data["released"]),
                task_id=data["task_id"],
                outcome=data["outcome"],
                status=data.get("status"),
                fence=int(data["fence"]),
                server_now=data["server_now"],
            )
        self._raise_denied(task_id, data)

    # -----------------------------------------------------------------------
    # Fehlerabbildung
    # -----------------------------------------------------------------------

    def _raise_denied(self, task_id: int, payload: dict[str, Any]) -> None:
        reason = str(payload.get("reason") or payload.get("detail") or "denied")
        if reason == "stale_fence":
            raise LeaseStaleFenceError(task_id, reason, payload)
        if reason == "expired":
            raise LeaseExpiredError(task_id, reason, payload)
        if reason == "max_total_reached":
            raise LeaseMaxTotalReachedError(task_id, reason, payload)
        raise LeaseDeniedError(task_id, reason, payload)
