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
import re
import sqlite3
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from hub._services.task_lease import (
        LeaseConfig,
        LeaseResult,
        LeaseValidationError,
        TaskNotFound,
        acquire_lease,
        decompose_lease,
        parse_ts,
        read_lease,
        release_lease,
        renew_lease,
    )
except ImportError:  # pragma: no cover
    from .task_lease import (  # type: ignore
        LeaseConfig,
        LeaseResult,
        LeaseValidationError,
        TaskNotFound,
        acquire_lease,
        decompose_lease,
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


class LeaseProtocolError(LeaseError):
    """Invalid authority configuration or uncorrelated/malformed ACK."""


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
    issued_at_str: str | None,
    expires_at_str: str | None,
    server_now_str: str | None,
    local_receive_time: datetime,
) -> datetime:
    """Berechnet local_deadline gemäss Vertrag §8.1:
    local_deadline = local_receive_time + (expires_at - server_now) - 60s
    """
    issued = _wire_time(issued_at_str)
    exp = _wire_time(expires_at_str)
    server_now = _wire_time(server_now_str)
    if not issued <= server_now < exp or local_receive_time.tzinfo is None:
        raise LeaseProtocolError("Ungültige Lease-Fristen im ACK")
    return local_receive_time + (exp - server_now) - timedelta(seconds=60)


def _wire_time(value: str | None) -> datetime:
    if not isinstance(value, str):
        raise LeaseProtocolError("Lease-ACK braucht UTC-Zeitstempel")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise LeaseProtocolError("Ungültiger Lease-Zeitstempel") from None
    if stamp.tzinfo is None:
        raise LeaseProtocolError("Lease-Zeitstempel ohne Zeitzone")
    return stamp.astimezone(timezone.utc)


def _version(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise LeaseProtocolError("Ungültige Auftragsversion")
    return value


def _identity(task_id, lease_id=None, fence=None):
    if type(task_id) is not int or task_id <= 0:
        raise LeaseProtocolError("Task-ID muss eine positive Ganzzahl sein")
    if lease_id is not None:
        try:
            if not isinstance(lease_id, str) or str(uuid.UUID(lease_id)) != lease_id:
                raise ValueError
        except (ValueError, AttributeError):
            raise LeaseProtocolError("Ungültige Lease-ID") from None
    if fence is not None and (type(fence) is not int or fence <= 0):
        raise LeaseProtocolError("Fence muss eine positive Ganzzahl sein")


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
    local_receive_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    local_deadline: datetime = field(init=False)
    replayed: bool = False
    task_version: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.lease_id, str) or type(self.fence) is not int or self.fence <= 0
                or not isinstance(self.ttl_profile, str) or not self.ttl_profile):
            raise LeaseProtocolError("Ungültige Lease-Capability oder Profil")
        _identity(self.task_id, self.lease_id, self.fence)
        _version(self.task_version)
        if (not isinstance(self.worker_id, str) or not isinstance(self.host, str)
                or self.worker_id.rsplit("@", 1)[-1].lower() != self.host.lower()):
            raise LeaseProtocolError("Ungültiger Lease-Halter")
        deadline = _calc_local_deadline(
            self.issued_at,
            self.expires_at,
            self.server_now,
            self.local_receive_time,
        )
        object.__setattr__(self, "local_deadline", deadline)

    @property
    def ttl_seconds(self) -> int:
        """Liefert die gewährte Fristdauer in Sekunden."""
        exp = parse_ts(self.expires_at)
        iss = parse_ts(self.issued_at)
        if exp and iss:
            return int((exp - iss).total_seconds())
        return 0

    @property
    def is_locally_valid(self) -> bool:
        """Prüft, ob die lokale Arbeitsfrist (Vertrag §8.1/§8.2) noch nicht abgelaufen ist."""
        return self.is_valid_at(datetime.now(timezone.utc))

    def is_valid_at(self, ref_time: datetime) -> bool:
        """Prüft, ob die lokale Arbeitsfrist zu einem bestimmten Zeitpunkt noch gültig ist."""
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        return ref_time < self.local_deadline

    def assert_locally_valid(self, now: datetime | None = None) -> None:
        """Fail-closed Guard vor schreibenden Operationen."""
        check_time = now or datetime.now(timezone.utc)
        if not self.is_valid_at(check_time):
            raise LeaseOfflineDeadlineExceeded(
                f"Task {self.task_id}: local_deadline ({self.local_deadline.isoformat()}) "
                f"ist abgelaufen. Keine weiteren lokalen Schreiboperationen erlaubt."
            )


@dataclass(frozen=True)
class LeaseHolderView:
    """Holder-Ansicht einer Task (Vertrag §5.2)."""

    task_id: int
    status: str | None
    leased: bool
    fence: int
    legacy: bool
    server_now: str
    holder: dict[str, Any] | None = None
    issued_at: str | None = None
    expires_at: str | None = None
    ttl_profile: str | None = None
    own: bool = False
    task_version: str | None = None


@dataclass(frozen=True)
class LeaseReleaseAck:
    """Bestätigung der Lease-Freigabe (Vertrag §5.4)."""

    released: bool
    task_id: int
    outcome: str
    status: str | None
    fence: int
    server_now: str


# ---------------------------------------------------------------------------
# TaskLeaseClient
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaseDecomposeAck:
    task_id: int
    created_ids: tuple[int, ...]
    created_count: int
    parent_closed: bool
    fence: int
    task_version: str
    server_now: str


class TaskLeaseClient:
    """Role-bound authority adapter; never fall back from a worker to its projection."""

    def __init__(self, *, conn=None, db_path=None, lead_url=None, device_token=None, timeout=8.0):
        self._conn = conn
        self._db_path = Path(db_path) if db_path else None
        self._owns_conn = False
        self._device_token = device_token or os.environ.get("BACH_DEVICE_TOKEN")
        self._timeout = timeout
        self._held = {}
        cfg = get_lead_config()
        if lead_url or cfg.get("mode") == "worker":
            candidate = lead_url or cfg.get("lead_url")
            from urllib.parse import urlsplit
            try:
                parts = urlsplit(str(candidate or ""))
            except ValueError:
                raise LeaseProtocolError("Fester Lead ist ungültig") from None
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                    or parts.username or parts.password or parts.query or parts.fragment):
                raise LeaseProtocolError("Fester Lead fehlt oder ist ungültig")
            self._lead_url = str(candidate).rstrip("/")
            self._mode = "remote"
        elif cfg.get("mode") in {"lead", "isolated"}:
            self._lead_url = None
            self._mode = "local"
        else:
            raise LeaseProtocolError("Unbekannte Lead-Rolle")

    @classmethod
    def for_task_db(cls, connection_factory, **kwargs):
        client = cls(**kwargs)
        if client.mode == "local":
            client._conn = connection_factory()
            client._owns_conn = True
        return client

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def mode(self):
        return self._mode

    @property
    def lead_url(self):
        return self._lead_url

    def _get_local_connection(self):
        if self._conn is not None:
            return self._conn
        path = self._db_path or Path.home() / ".bach" / "bach.db"
        conn = sqlite3.connect(str(path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _http_request(self, method, path, payload=None, headers=None):
        if not self._device_token:
            raise LeaseDeniedError(0, "device_auth_required", {})
        req_headers = {"Accept": "application/json", "Authorization": f"Bearer {self._device_token}"}
        if headers:
            req_headers.update(headers)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self._lead_url}{path}", data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.status
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            status = err.code
            body = err.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError):
            # Request may have committed at the Lead. Never retry a mutation here.
            raise LeaseConnectionError("Lead nicht erreichbar; Bestätigung fehlt") from None
        try:
            parsed = json.loads(body) if body else {}
        except (ValueError, TypeError):
            raise LeaseProtocolError("Lead lieferte kein gültiges JSON-ACK") from None
        if not isinstance(parsed, dict):
            raise LeaseProtocolError("Lead-ACK muss ein Objekt sein")
        if status in (401, 403):
            raise LeaseDeniedError(0, "device_auth_rejected", {})
        if status >= 500:
            raise LeaseConnectionError("Lead verweigert die Operation")
        return status, parsed

    def _call(self, name, task_id, payload=None, *, config=None, now=None, headers=None):
        _identity(task_id)
        if self.mode == "remote":
            suffix = {"acquire": "", "read": "", "renew": "/renew", "release": "/release", "decompose": "/decompose"}[name]
            status, data = self._http_request("GET" if name == "read" else "POST",
                                             f"/api/tasks/{task_id}/lease{suffix}", payload, headers)
        else:
            conn = self._get_local_connection()
            try:
                funcs = {"acquire": acquire_lease, "read": read_lease, "renew": renew_lease,
                         "release": release_lease, "decompose": decompose_lease}
                result = funcs[name](conn, task_id, **(payload or {}), config=config, now=now)
                status, data = result.http_status, result.payload
            except (LeaseValidationError, TaskNotFound):
                raise LeaseProtocolError("Ungültige Lease-Anfrage oder Task fehlt") from None
            finally:
                if self._conn is None:
                    conn.close()
        if status != 200:
            self._raise_denied(task_id, data)
        if not isinstance(data, dict) or type(data.get("task_id")) is not int or data["task_id"] != task_id:
            raise LeaseProtocolError("ACK passt nicht zur angefragten Task")
        _wire_time(data.get("server_now"))
        return data

    def _grant(self, data, *, worker_id=None, host=None, lease_id=None, fence=None,
               task_version=None, receive_time):
        if data.get("granted") is not True:
            raise LeaseProtocolError("ACK bestätigt keine Lease-Erteilung")
        for key, expected in (("worker_id", worker_id), ("host", host), ("lease_id", lease_id),
                              ("fence", fence), ("task_version", task_version)):
            if expected is not None and data.get(key) != expected:
                raise LeaseProtocolError("Lease-ACK stimmt nicht mit der Anfrage überein")
        required = ("task_id", "lease_id", "fence", "worker_id", "host", "issued_at", "expires_at", "ttl_profile", "server_now")
        if any(key not in data for key in required):
            raise LeaseProtocolError("Lease-ACK ist unvollständig")
        ack = LeaseAck(**{key: data[key] for key in required}, task_version=data.get("task_version"),
                       replayed=data.get("replayed") is True, local_receive_time=receive_time)
        self._held[ack.task_id] = ack
        return ack

    def acquire(self, task_id, *, worker_id, host, request_id=None, ttl_profile="M", intent="",
                task_version=None, config=None, now=None):
        _version(task_version)
        sent_at = now or datetime.now(timezone.utc)
        body = dict(worker_id=worker_id, host=host, request_id=request_id or str(uuid.uuid4()),
                    ttl_profile=ttl_profile, intent=intent, task_version=task_version)
        data = self._call("acquire", task_id, body, config=config, now=now)
        # Sending time is conservative: response latency cannot extend the local deadline.
        return self._grant(data, worker_id=worker_id, host=host, task_version=task_version, receive_time=sent_at)

    def read(self, task_id, *, lease_id=None, config=None, now=None):
        headers = {"X-Lease-Id": lease_id} if lease_id else None
        body = {"lease_id": lease_id} if self.mode == "local" else None
        data = self._call("read", task_id, body, config=config, now=now, headers=headers)
        if type(data.get("leased")) is not bool or type(data.get("fence")) is not int or data["fence"] < 0:
            raise LeaseProtocolError("Ungültiger Lease-Readback")
        _version(data.get("task_version"))
        return LeaseHolderView(task_id=task_id, status=data.get("status"), leased=data["leased"],
            fence=data["fence"], legacy=data.get("legacy") is True, server_now=data["server_now"],
            holder=data.get("holder"), issued_at=data.get("issued_at"), expires_at=data.get("expires_at"),
            ttl_profile=data.get("ttl_profile"), own=data.get("own") is True, task_version=data.get("task_version"))

    def renew(self, task_id, *, lease_id, fence, task_version=None, config=None, now=None):
        _identity(task_id, lease_id, fence)
        _version(task_version)
        sent_at = now or datetime.now(timezone.utc)
        data = self._call("renew", task_id, dict(lease_id=lease_id, fence=fence, task_version=task_version), config=config, now=now)
        previous = self._held.get(task_id)
        return self._grant(data, lease_id=lease_id, fence=fence, task_version=task_version,
                           worker_id=previous.worker_id if previous else None,
                           host=previous.host if previous else None, receive_time=sent_at)

    def release(self, task_id, *, lease_id, fence, task_version=None, outcome="done", result_ref="", note="", config=None, now=None):
        _identity(task_id, lease_id, fence)
        _version(task_version)
        data = self._call("release", task_id, dict(lease_id=lease_id, fence=fence, task_version=task_version,
                         outcome=outcome, result_ref=result_ref, note=note), config=config, now=now)
        statuses = {"done": "done", "return": "pending", "blocked": "blocked"}
        if (data.get("released") is not True or type(data.get("fence")) is not int or data["fence"] != fence
                or data.get("outcome") != outcome or data.get("status") != statuses.get(outcome)):
            raise LeaseProtocolError("Release-ACK passt nicht zur Anfrage")
        self._held.pop(task_id, None)
        return LeaseReleaseAck(True, task_id, outcome, data["status"], fence, data["server_now"])

    def decompose(self, task_id, *, lease_id, fence, task_version, subtasks, close_parent=True, sequential=False, config=None, now=None):
        _identity(task_id, lease_id, fence)
        _version(task_version, required=True)
        body = dict(lease_id=lease_id, fence=fence, task_version=task_version, subtasks=subtasks,
                    close_parent=close_parent, sequential=sequential)
        data = self._call("decompose", task_id, body, config=config, now=now)
        ids = data.get("created_ids")
        if (data.get("decomposed") is not True or type(data.get("parent_closed")) is not bool
                or data["parent_closed"] != close_parent or type(data.get("fence")) is not int or data["fence"] != fence
                or not isinstance(ids, list) or len(ids) != len(subtasks) or not ids
                or any(type(i) is not int or i <= 0 or i == task_id for i in ids)
                or len(set(ids)) != len(ids) or type(data.get("created_count")) is not int
                or data["created_count"] != len(ids)):
            raise LeaseProtocolError("Zerlegungs-ACK passt nicht zur Anfrage")
        version = _version(data.get("task_version"), required=True)
        if version == task_version:
            raise LeaseProtocolError("Zerlegungs-ACK hat keine neue Inhaltsversion")
        previous = self._held.get(task_id)
        if close_parent:
            self._held.pop(task_id, None)
        elif previous:
            self._held[task_id] = replace(previous, task_version=version)
        return LeaseDecomposeAck(task_id, tuple(ids), len(ids), close_parent, fence, version, data["server_now"])

    def _raise_denied(self, task_id, payload):
        known = {"stale_fence", "expired", "max_total_reached", "held", "already_held_by_caller",
                 "stale_task_version", "not_claimable", "creator_priority", "completion_guard", "conflict"}
        reason = payload.get("reason") if isinstance(payload, dict) else None
        if reason not in known:
            reason = "denied"
        classes = {"stale_fence": LeaseStaleFenceError, "expired": LeaseExpiredError,
                   "max_total_reached": LeaseMaxTotalReachedError}
        raise classes.get(reason, LeaseDeniedError)(task_id, reason, {"task_id": task_id, "reason": reason})
