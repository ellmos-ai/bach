# SPDX-License-Identifier: MIT
"""Duenner Client fuer Ressourcen-Leases (Polaris (Polarstern) P1, BACH #2121).

Erbt Transport, Lead-Erkennung und Geraete-Token von ``TaskLeaseClient``
(unveraendert). Ohne erreichbare Authority gibt es keine Uebernahme: ein
Worker-Host ohne Lead-URL oder mit unerreichbarem Lead scheitert fail-closed;
der lokale Direktweg gilt nur am Lead selbst (oder mit ``allow_isolated=True``
bzw. ``BACH_POLARIS_ALLOW_ISOLATED=1`` fuer Tests und Einzelbetrieb).

Zeit (Festlegung 8): Die lokale Frist wird aus ``server_now`` und einer
monotonen Uhr berechnet, nie aus der Wanduhr. Springt die Wanduhr gegenueber
dem Monoton-Takt um mehr als die Marge (Suspend), verlangt ``assert_valid``
vor dem Schreiben eine Online-Pruefung (``client.verify``).
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

try:
    from hub._services import lease_core as core
    from hub._services import task_lease_client as _tlc
    from hub._services.resource_lease import (
        LeaseValidationError,
        ResourceLeaseConfig,
        ResourceNotFound,
        acquire_resource_lease,
        read_resource_lease,
        release_resource_lease,
        renew_resource_lease,
    )
except ImportError:  # pragma: no cover
    from . import lease_core as core  # type: ignore
    from . import task_lease_client as _tlc  # type: ignore
    from .resource_lease import (  # type: ignore
        LeaseValidationError,
        ResourceLeaseConfig,
        ResourceNotFound,
        acquire_resource_lease,
        read_resource_lease,
        release_resource_lease,
        renew_resource_lease,
    )

LeaseError = _tlc.LeaseError
LeaseProtocolError = _tlc.LeaseProtocolError
LeaseConnectionError = _tlc.LeaseConnectionError


class ResourceLeaseDeniedError(_tlc.LeaseDeniedError):
    """Authority hat abgelehnt (HTTP 409) oder die Anfrage verworfen."""

    def __init__(self, resource: str, reason: str, payload: dict[str, Any]):
        LeaseError.__init__(self, f"Ressource {resource}: Lease abgelehnt ({reason})")
        self.task_id = 0
        self.resource = resource
        self.reason = reason
        self.payload = payload


class ResourceLeaseLostError(LeaseError):
    """Der Polaris star gehoert nicht mehr diesem Halter (star_lost): sofort stoppen."""


class ResourceLeaseExpiredError(LeaseError):
    """Lokale Frist abgelaufen oder Online-Pruefung noetig: nicht schreiben."""


@dataclass(frozen=True)
class ResourceLeaseAck:
    resource: str
    lease_id: str
    fence: int
    worker_id: str
    host: str
    role: str
    issued_at: str
    expires_at: str
    ttl_profile: str
    server_now: str
    resource_version: str | None = None
    renew_after_seconds: int = 40
    margin_seconds: int = 15
    replayed: bool = False
    received_mono: float = field(default_factory=time.monotonic)
    received_wall: float = field(default_factory=time.time)
    remaining_at_receipt: float = field(init=False)

    def __post_init__(self) -> None:
        try:
            if str(uuid.UUID(self.lease_id)) != self.lease_id:
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise LeaseProtocolError("Ungueltige Lease-ID") from None
        if type(self.fence) is not int or self.fence <= 0:
            raise LeaseProtocolError("Fence muss eine positive Ganzzahl sein")
        issued, now, expires = (_tlc._wire_time(v) for v in (self.issued_at, self.server_now, self.expires_at))
        if not issued <= now < expires:
            raise LeaseProtocolError("Ungueltige Lease-Fristen im ACK")
        object.__setattr__(self, "remaining_at_receipt", (expires - now).total_seconds())

    def remaining(self, now_mono: float | None = None) -> float:
        """Restlaufzeit in Sekunden, aus Serverfrist und Monoton-Uhr."""
        elapsed = (time.monotonic() if now_mono is None else now_mono) - self.received_mono
        return self.remaining_at_receipt - elapsed

    def is_valid(self, margin: float | None = None, now_mono: float | None = None) -> bool:
        return self.remaining(now_mono) > (self.margin_seconds if margin is None else margin)

    def needs_online_check(self, now_mono: float | None = None, now_wall: float | None = None,
                           margin: float | None = None) -> bool:
        """Wanduhr und Monoton-Takt laufen um mehr als die Marge auseinander
        (Suspend, Zeitsprung): der lokalen Frist ist nicht zu trauen."""
        mono = (time.monotonic() if now_mono is None else now_mono) - self.received_mono
        wall = (time.time() if now_wall is None else now_wall) - self.received_wall
        return abs(wall - mono) > (self.margin_seconds if margin is None else margin)

    def assert_valid(self, client: ResourceLeaseClient | None = None, margin: float | None = None) -> None:
        """Fail-closed Guard unmittelbar vor jeder Schreibaktion."""
        if not self.is_valid(margin):
            raise ResourceLeaseExpiredError(
                f"Ressource {self.resource}: lokale Frist (Marge "
                f"{self.margin_seconds if margin is None else margin}s) abgelaufen")
        if self.needs_online_check(margin=margin):
            if client is None:
                raise ResourceLeaseExpiredError(
                    f"Ressource {self.resource}: Zeitluecke erkannt, Online-Pruefung noetig")
            client.verify(self)


@dataclass(frozen=True)
class ResourceStatus:
    resource: str
    leased: bool
    fence: int
    server_now: str
    resource_version: str | None = None
    server_active: bool = False
    holder: dict[str, Any] | None = None
    expires_at: str | None = None
    own: bool = False


@dataclass(frozen=True)
class ResourceReleaseAck:
    resource: str
    fence: int
    late: bool
    resource_version: str | None
    server_now: str


class ResourceLeaseClient(_tlc.TaskLeaseClient):
    """Polaris-star-Client: acquire, renew, release, status, verify."""

    def __init__(self, *, allow_isolated: bool | None = None, **kwargs):
        super().__init__(**kwargs)
        if self.mode == "local" and _tlc.get_lead_config().get("mode") == "isolated":
            allowed = allow_isolated if allow_isolated is not None else (
                os.environ.get("BACH_POLARIS_ALLOW_ISOLATED") == "1")
            if not allowed:
                raise LeaseProtocolError("Keine erreichbare Lead-Authority: Ressource bleibt nur lesbar")

    @classmethod
    def for_db(cls, connection_factory, **kwargs):
        return cls.for_task_db(connection_factory, **kwargs)

    def _call(self, name, resource, payload=None, *, config=None, now=None, headers=None):
        core_name = core.validate_resource_name(resource)
        if self.mode == "remote":
            suffix = {"acquire": "", "read": "", "renew": "/renew", "release": "/release"}[name]
            status, data = self._http_request("GET" if name == "read" else "POST",
                                              f"/api/resources/{core_name}/lease{suffix}", payload, headers)
        else:
            conn = self._get_local_connection()
            try:
                funcs = {"acquire": acquire_resource_lease, "read": read_resource_lease,
                         "renew": renew_resource_lease, "release": release_resource_lease}
                kwargs = dict(payload or {})
                if name == "read" and headers and headers.get("X-Lease-Id"):
                    kwargs["lease_id"] = headers["X-Lease-Id"]
                result = funcs[name](conn, core_name, **kwargs, config=config, now=now)
                status, data = result.http_status, result.payload
            except (LeaseValidationError, ResourceNotFound) as exc:
                raise ResourceLeaseDeniedError(core_name, type(exc).__name__, {"detail": str(exc)}) from None
            finally:
                if self._conn is None:
                    conn.close()
        if status != 200:
            reason = data.get("reason") or data.get("detail") or f"http_{status}"
            raise ResourceLeaseDeniedError(core_name, str(reason), data)
        if not isinstance(data, dict) or data.get("resource") != core_name:
            raise LeaseProtocolError("ACK passt nicht zur angefragten Ressource")
        _tlc._wire_time(data.get("server_now"))
        return data

    @staticmethod
    def _ack(data: dict[str, Any]) -> ResourceLeaseAck:
        keys = ("resource", "lease_id", "fence", "worker_id", "host", "role", "issued_at", "expires_at",
                "ttl_profile", "server_now", "resource_version", "renew_after_seconds", "margin_seconds")
        try:
            return ResourceLeaseAck(**{k: data[k] for k in keys}, replayed=bool(data.get("replayed")))
        except KeyError as exc:
            raise LeaseProtocolError(f"ACK unvollstaendig: {exc}") from None

    def acquire(self, resource, *, worker_id, host=None, ttl_profile=None, intent="",
                resource_version=None, request_id=None, config=None, now=None) -> ResourceLeaseAck:
        host = host or worker_id.rsplit("@", 1)[-1]
        payload = {"worker_id": worker_id, "host": host, "request_id": request_id or "req-" + uuid.uuid4().hex,
                   "ttl_profile": ttl_profile, "intent": intent, "resource_version": resource_version}
        return self._ack(self._call("acquire", resource, payload, config=config, now=now))

    def renew(self, ack: ResourceLeaseAck, *, resource_version=None, config=None, now=None) -> ResourceLeaseAck:
        return self.renew_ref(ack.resource, ack.lease_id, ack.fence, resource_version=resource_version,
                              config=config, now=now)

    def renew_ref(self, resource, lease_id, fence, *, resource_version=None, config=None, now=None):
        payload = {"lease_id": lease_id, "fence": fence, "resource_version": resource_version}
        return self._ack(self._call("renew", resource, payload, config=config, now=now))

    def release(self, ack: ResourceLeaseAck, *, resource_version=None, config=None, now=None) -> ResourceReleaseAck:
        return self.release_ref(ack.resource, ack.lease_id, ack.fence, resource_version=resource_version,
                                config=config, now=now)

    def release_ref(self, resource, lease_id, fence, *, resource_version=None, config=None, now=None):
        payload = {"lease_id": lease_id, "fence": fence, "resource_version": resource_version}
        data = self._call("release", resource, payload, config=config, now=now)
        return ResourceReleaseAck(data["resource"], int(data["fence"]), bool(data.get("late")),
                                  data.get("resource_version"), data["server_now"])

    def status(self, resource, *, lease_id=None, config=None, now=None) -> ResourceStatus:
        headers = {"X-Lease-Id": lease_id} if lease_id else None
        data = self._call("read", resource, None, config=config, now=now, headers=headers)
        return ResourceStatus(
            resource=data["resource"], leased=bool(data["leased"]), fence=int(data["fence"]),
            server_now=data["server_now"], resource_version=data.get("resource_version"),
            server_active=bool(data.get("server_active")), holder=data.get("holder"),
            expires_at=data.get("expires_at"), own=bool(data.get("own")))

    def verify(self, ack: ResourceLeaseAck, *, config=None, now=None) -> ResourceStatus:
        """Nachpruefung beim Lead: Polaris star und Fence noch dieselben? Sonst ``star_lost``."""
        st = self.status(ack.resource, lease_id=ack.lease_id, config=config, now=now)
        if not (st.leased and st.own and st.fence == ack.fence):
            raise ResourceLeaseLostError(
                f"Ressource {ack.resource}: Polaris star verloren (Fence {ack.fence} -> {st.fence}); sofort stoppen")
        return st
