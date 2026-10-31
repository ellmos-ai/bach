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
import hashlib
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
        LeaseConfig as LeaseConfig,
        LeaseResult as LeaseResult,
        LeaseValidationError,
        LeaseSelfCheckRequired,
        TaskNotFound,
        acquire_lease,
        _acquire_native_creator_lease,
        decompose_lease,
        parse_ts,
        read_lease,
        release_lease,
        renew_lease,
        update_lease,
        ensure_task_lease_schema,
        task_content_version,
    )
except ImportError:  # pragma: no cover
    from .task_lease import (  # type: ignore
        LeaseConfig as LeaseConfig,
        LeaseResult as LeaseResult,
        LeaseValidationError,
        LeaseSelfCheckRequired,
        TaskNotFound,
        acquire_lease,
        _acquire_native_creator_lease,
        decompose_lease,
        parse_ts,
        read_lease,
        release_lease,
        renew_lease,
        update_lease,
        ensure_task_lease_schema,
        task_content_version,
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


class LeaseSelfCheckRequiredError(LeaseProtocolError):
    """Confirmed local validation denial without a submission or lease mutation."""

    user_message = ("Ergebnis noch nicht vollständig: Für einfache Tasks ohne Vertrag "
                    "einen echten Selbstcheck abgeben; Teilstand mit update(status='pending') zurückgeben.")


class LeaseRequestRejectedError(LeaseProtocolError):
    """The lease service validated the request and rejected it before applying anything."""

    user_message = ("Taskoperation abgelehnt, nichts geändert: Argumente ungültig. Teilaufgaben brauchen title; "
                    "description, priority, category, assigned_to und depends_on sind Text, depends_on nennt "
                    "bestehende Task-IDs. Argumente korrigieren und erneut aufrufen.")


class LeaseDeniedError(LeaseError):
    """Lease wurde von der Authority abgelehnt (HTTP 409)."""

    def __init__(self, task_id: int, reason: str, payload: dict[str, Any]):
        super().__init__(f"Task {task_id}: Lease abgelehnt ({reason})")
        self.task_id = task_id
        self.reason = reason
        self.payload = dict(payload)
        # Only _raise_denied populates these with authority-validated UTC values.
        self.until = self.payload.get("until")
        self.server_now = self.payload.get("server_now")


class LeaseStaleFenceError(LeaseDeniedError):
    """Fence passt nicht zur aktuellen Lease-Epoche (stale_fence)."""


class LeaseExpiredError(LeaseDeniedError):
    """Lease ist bereits abgelaufen (expired)."""


class LeaseMaxTotalReachedError(LeaseDeniedError):
    """Maximale Gesamtlaufzeit des TTL-Profils erreicht."""


class LeaseConnectionError(LeaseError):
    """Verbindung zum Lead-Server fehlgeschlagen oder Timeout."""


class TaskResultOperationError(LeaseError):
    """Stable, redacted error returned by the result operator API."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


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


_SAFE_DENIAL_REASONS = frozenset({
    "stale_fence", "expired", "max_total_reached", "held", "already_held_by_caller",
    "stale_task_version", "not_claimable", "creator_priority", "completion_guard", "conflict",
    "creator_delegation_invalid", "creator_delegation_revoked", "creator_delegation_consumed",
    "unresolved_tool_trace", "tool_trace_unavailable",
})
_SAFE_UTC_DENIAL_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z"
)


def _validated_denial_utc(value):
    """Parse the authority's bounded UTC timestamp form without retaining raw payloads."""
    if type(value) is not str or not _SAFE_UTC_DENIAL_TIME.fullmatch(value):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        stamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        return None
    return stamp.astimezone(timezone.utc)


def _format_denial_utc(stamp):
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _version(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise LeaseProtocolError("Ungültige Auftragsversion")
    return value


def _generation(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
        raise LeaseProtocolError("Ungültige Workergeneration")
    return value


def _trace_ack(data, *, task_id, request_id, phase):
    from hub._services.chat.worker_tool_trace import SCHEMA, PHASES
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA
            or data.get("accepted") is not True
            or type(data.get("event_id")) is not int or data["event_id"] <= 0
            or type(data.get("task_id")) is not int or data["task_id"] != task_id
            or data.get("request_id") != request_id or not isinstance(phase, str)
            or phase not in PHASES or data.get("phase") != phase):
        raise LeaseProtocolError("Werkzeug-Trace-ACK passt nicht zur Anfrage")
    return {"schema": SCHEMA, "accepted": True, "event_id": data["event_id"],
            "task_id": task_id, "request_id": request_id, "phase": phase}


@dataclass(frozen=True)
class ToolTraceStartAck:
    schema: str
    accepted: bool
    event_id: int
    task_id: int
    request_id: str
    phase: str
    completion_token: str = field(repr=False)


def _trace_start_ack(data, *, task_id, request_id):
    from hub._services.chat.worker_tool_trace import _COMPLETION_TOKEN
    base = _trace_ack(data, task_id=task_id, request_id=request_id, phase="started")
    token = data.get("completion_token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not _COMPLETION_TOKEN.fullmatch(token):
        raise LeaseProtocolError("Werkzeug-Trace-Start-ACK ist unvollständig")
    return ToolTraceStartAck(**base, completion_token=token)


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
    result_generation: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.lease_id, str) or type(self.fence) is not int or self.fence <= 0
                or not isinstance(self.ttl_profile, str) or not self.ttl_profile):
            raise LeaseProtocolError("Ungültige Lease-Capability oder Profil")
        _identity(self.task_id, self.lease_id, self.fence)
        _version(self.task_version)
        _generation(self.result_generation)
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


@dataclass(frozen=True)
class WorkerResultAck:
    """Correlated Review release plus the exact canonical submitted result."""
    release: LeaseReleaseAck
    record: dict


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
    reused_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class LeaseUpdateAck:
    task_id: int
    fence: int
    previous_task_version: str
    task_version: str
    fields: tuple[str, ...]
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

    def ensure_worker_resolver(self, worker_id, error_code):
        """Local controller only: one open resolver task for a worker that ended in error."""
        if self.mode != "local":
            return None
        from hub.task_audit import ensure_worker_error_resolver
        conn = self._get_local_connection()
        try:
            if conn.in_transaction:
                return None
            conn.execute("BEGIN IMMEDIATE")
            try:
                resolver = ensure_worker_error_resolver(conn, worker_id, error_code)
                conn.commit()
                return resolver
            except BaseException:
                conn.rollback()
                raise
        finally:
            if self._conn is None:
                conn.close()

    def _model_execution_call(self, operation, binding, *args, **kwargs):
        """Private controller path; HTTP workers cannot self-attest model calls."""
        if self.mode != "local" or getattr(binding, "_client", None) is not self:
            return None if operation == "start_execution" else False
        from . import worker_execution_evidence
        conn = self._get_local_connection()
        try:
            return getattr(worker_execution_evidence, operation)(conn, binding, *args, **kwargs)
        finally:
            if self._conn is None:
                conn.close()

    def _start_model_execution(self, binding, *, backend_id, requested_model, slot_id,
                               request_sha256, route_sha256=None):
        kwargs = {"backend_id": backend_id, "requested_model": requested_model,
                  "slot_id": slot_id, "request_sha256": request_sha256}
        if route_sha256 is not None:
            kwargs["route_sha256"] = route_sha256
        return self._model_execution_call("start_execution", binding, **kwargs)

    def _finish_model_execution(self, binding, handle, *, result=None, failed=False, route_sha256=None,
                                failure=None):
        kwargs = {"result": result, "failed": failed}
        if route_sha256 is not None:
            kwargs["route_sha256"] = route_sha256
        if failure is not None:
            kwargs["failure"] = failure
        return self._model_execution_call("finish_execution", binding, handle, **kwargs)

    def _link_model_execution(self, binding, handle):
        return self._model_execution_call("link_execution", binding, handle)

    def _capture_task_scope(self, binding):
        """Private local capture, never a remote worker self-attestation route."""
        if self.mode != "local" or getattr(binding, "_client", None) is not self:
            return False
        from .worker_scope_evidence import capture_scope_evidence
        conn = self._get_local_connection()
        try:
            return capture_scope_evidence(conn, binding)
        finally:
            if self._conn is None:
                conn.close()

    def _reconcile_task_completion(self, task_id):
        """Local controller hook; remote workers never assert completion facts."""
        if self.mode != "local" or type(task_id) is not int or task_id <= 0:
            return None
        from .worker_completion_policy import reconcile_current_result
        conn = self._get_local_connection()
        try:
            if conn.in_transaction:
                return None
            return reconcile_current_result(conn, task_id)
        finally:
            if self._conn is None:
                conn.close()

    def _prepare_review_task(self, binding):
        """Create an eligible result-review task only in the canonical local TaskDB."""
        if self.mode != "local" or getattr(binding, "_client", None) is not self:
            return None
        from .worker_result_review import prepare_review_task
        conn = self._get_local_connection()
        try:
            return prepare_review_task(conn, binding)
        finally:
            if self._conn is None:
                conn.close()

    def _review_task_metadata(self, task_id):
        """Read validated private review intent from the local TaskDB only."""
        if self.mode != "local":
            return None
        _identity(task_id)
        from .worker_result_review import review_task_metadata
        conn = self._get_local_connection()
        try:
            return review_task_metadata(conn, task_id)
        finally:
            if self._conn is None:
                conn.close()

    def _review_candidates(self, limit=100, offset=0):
        """Read pending review jobs locally; remote leads carry no private grant authority."""
        if (type(limit) is not int or not 1 <= limit <= 100
                or type(offset) is not int or offset < 0):
            raise LeaseProtocolError("Ungültige Review-Taskseite")
        if self.mode != "local":
            return {"tasks": [], "has_more": False, "offset": offset}
        from .worker_result_review import list_review_candidates
        conn = self._get_local_connection()
        try:
            raw = list_review_candidates(conn, limit=limit, offset=offset)
            has_more = False
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='worker_result_review_intents'"
            ).fetchone() is not None
            if table_exists:
                raw_total = conn.execute(
                    "SELECT COUNT(*) FROM tasks t JOIN worker_result_review_intents i "
                    "ON i.review_task_id=t.id WHERE t.status IN ('pending','open')"
                ).fetchone()[0]
                has_more = offset + limit < raw_total
        finally:
            if self._conn is None:
                conn.close()
        snapshots = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("review_intent"), dict):
                continue
            snapshot = self._public_snapshot(item)
            intent = item["review_intent"]
            if (intent.get("schema") not in {
                        "bach.worker-result-review-intent.v1",
                        "bach.worker-result-review-intent.external-attested.v1"}
                    or intent.get("review_task_id") != snapshot["id"]
                    or intent.get("task_version") != snapshot["task_version"]
                    or intent.get("status") not in {"pending", "open"}):
                continue
            snapshots.append({**snapshot, "review_intent": intent})
        return {"tasks": snapshots, "has_more": has_more, "offset": offset}

    def _issue_review_grant(self, task_id, *, worker_id, host, generation, slot_id,
                            route, requested_model, is_current, stop_event, clock):
        """Mint a process-private, single-task review grant on the local authority."""
        if self.mode != "local":
            return None
        _identity(task_id)
        from .worker_result_review import issue_review_grant
        conn = self._get_local_connection()
        try:
            return issue_review_grant(conn, task_id, worker_id=worker_id, host=host,
                generation=generation, slot_id=slot_id, route=route,
                requested_model=requested_model, is_current=is_current,
                stop_event=stop_event, clock=clock)
        finally:
            if self._conn is None:
                conn.close()

    def _guard_review_dispatch(self, binding, *, route, requested_model):
        """Recheck current target Git/policy outside the binding lock; never remote-fallback."""
        if self.mode != "local" or getattr(binding, "_client", None) is not self:
            return False
        from .worker_result_review import guard_review_dispatch
        conn = self._get_local_connection()
        try:
            return guard_review_dispatch(conn, binding, route=route,
                                         requested_model=requested_model) is True
        finally:
            if self._conn is None:
                conn.close()

    def _record_result_review(self, binding):
        """Persist only a canonical review linked to its local child submission."""
        if self.mode != "local" or getattr(binding, "_client", None) is not self:
            return None
        from .worker_result_review import record_review, cancel_obsolete_review_child
        conn = self._get_local_connection()
        try:
            evidence = record_review(conn, binding)
            if evidence is None:
                evidence = cancel_obsolete_review_child(conn, binding)
        finally:
            if self._conn is None:
                conn.close()
        if isinstance(evidence, dict) and evidence.get("availability") == "recorded":
            try:
                self._reconcile_task_completion(evidence["task_id"])
            except Exception:
                pass
        return evidence

    def _recover_invalid_review_child(self, task_id, *, result_id, status_revision):
        """Local controller recovery through the canonical correction writer."""
        if self.mode != "local":
            return None
        _identity(task_id)
        from .worker_result_review import recover_invalid_review_child
        conn = self._get_local_connection()
        try:
            return recover_invalid_review_child(conn, task_id, result_id=result_id,
                                                status_revision=status_revision)
        finally:
            if self._conn is None:
                conn.close()

    def _repair_machine_false_acceptance(self, task_id, *, expected, request_id,
                                         repo_root=None, worktrees_dir=None):
        """Local, private controller path for a proven machine false acceptance."""
        if self.mode != "local":
            return None
        _identity(task_id)
        from .machine_false_acceptance_recovery import repair_machine_false_acceptance
        conn = self._get_local_connection()
        try:
            return repair_machine_false_acceptance(conn, task_id, expected=expected,
                request_id=request_id, repo_root=repo_root,
                worktrees_dir=worktrees_dir)
        finally:
            if self._conn is None:
                conn.close()

    def _allows_server_error_response(self, status: int, payload: dict[str, Any]) -> bool:
        """Let existing subclasses opt in to their one validated error shape."""
        return False

    def _allows_result_service_server_error(
        self, status: int, payload: dict[str, Any], method: str, path: str
    ) -> bool:
        """Result-service clients may opt in to one exact route-specific 503 DTO."""
        return False

    def _http_request_core(self, method, path, payload=None, headers=None, *, service_auth=False):
        if service_auth:
            if (not isinstance(headers, dict) or "X-BACH-Result-Service" not in headers
                    or "Authorization" in headers or "Cookie" in headers):
                raise LeaseProtocolError("Service-Anmeldung ist nicht kanonisch")
            req_headers = {"Accept": "application/json"}
            req_headers.update(headers)
        else:
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
        if status in (401, 403) and not service_auth:
            raise LeaseDeniedError(0, "device_auth_rejected", {})
        allowed_error = (
            self._allows_server_error_response(status, parsed)
            or (service_auth and self._allows_result_service_server_error(status, parsed, method, path))
        )
        if status >= 500 and not allowed_error:
            raise LeaseConnectionError("Lead verweigert die Operation")
        return status, parsed

    def _http_request(self, method, path, payload=None, headers=None):
        return self._http_request_core(method, path, payload, headers, service_auth=False)

    def _http_service_request(self, method, path, payload=None, headers=None):
        return self._http_request_core(method, path, payload, headers, service_auth=True)

    def _call(self, name, task_id, payload=None, *, config=None, now=None, headers=None):
        _identity(task_id)
        if self.mode == "remote":
            if isinstance(payload, dict) and ({"_review_grant", "_review_binding", "_project_binding"} & payload.keys()):
                raise LeaseProtocolError("Private Reviewgrants und Projektbindungen dürfen nicht über HTTP gesendet werden")
            suffix = {"acquire": "", "read": "", "renew": "/renew", "release": "/release", "decompose": "/decompose", "update": "/update"}[name]
            status, data = self._http_request("GET" if name == "read" else "POST",
                                             f"/api/tasks/{task_id}/lease{suffix}", payload, headers)
            if status == 422:
                detail = data.get("detail") if isinstance(data, dict) else None
                if detail == "Vollständiger Selbstcheck erforderlich" or (
                        isinstance(detail, dict) and detail.get("code") == "self_check_required"):
                    raise LeaseSelfCheckRequiredError(LeaseSelfCheckRequiredError.user_message) from None
                raise LeaseRequestRejectedError(LeaseRequestRejectedError.user_message) from None
        else:
            conn = self._get_local_connection()
            try:
                funcs = {"acquire": acquire_lease, "read": read_lease, "renew": renew_lease,
                         "release": release_lease, "decompose": decompose_lease, "update": update_lease}
                result = funcs[name](conn, task_id, **(payload or {}), config=config, now=now)
                status, data = result.http_status, result.payload
            except LeaseSelfCheckRequired:
                raise LeaseSelfCheckRequiredError(LeaseSelfCheckRequiredError.user_message) from None
            except LeaseValidationError:
                # Validation runs before the transaction or inside one that is rolled back: nothing was applied.
                raise LeaseRequestRejectedError(LeaseRequestRejectedError.user_message) from None
            except TaskNotFound:
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

    @staticmethod
    def _public_snapshot(data, task_id=None):
        if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] <= 0:
            raise LeaseProtocolError("Ungültiger Task-Readback")
        if task_id is not None and data["id"] != task_id:
            raise LeaseProtocolError("Readback passt nicht zur angefragten Task")
        _version(data.get("task_version"), required=True)
        if "result_max_chars" in data:
            limit = data["result_max_chars"]
            if limit is not None and (
                type(limit) is not int or not 1 <= limit <= 3000
            ):
                raise LeaseProtocolError("Ungültiges Task-Ergebnislimit im Readback")
        return {key: value for key, value in data.items()
                if key not in {"claim_id", "claim_request_id", "claim_task_version"}}

    def task_snapshot(self, task_id):
        """Read canonical content and version together, without bearer capabilities."""
        _identity(task_id)
        if self.mode == "remote":
            status, data = self._http_request("GET", f"/api/tasks/{task_id}")
            if status != 200:
                self._raise_denied(task_id, data)
        else:
            conn = self._get_local_connection()
            try:
                ensure_task_lease_schema(conn)
                cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                if row is None:
                    raise LeaseProtocolError("Task fehlt")
                data = dict(row) if isinstance(row, sqlite3.Row) else dict(zip(
                    (column[0] for column in cursor.description), row))
                data["task_version"] = task_content_version(data)
            finally:
                if self._conn is None:
                    conn.close()
        return self._public_snapshot(data, task_id)

    def task_capabilities(self):
        """Read versioned task-field capabilities; old APIs fail closed."""
        expected = {
            "schema": "bach.task-capabilities.v1",
            "result_max_chars": {
                "supported": True,
                "min": 1,
                "max": 3000,
                "nullable": True,
            },
        }
        if self.mode == "remote":
            status, data = self._http_request("GET", "/api/task-capabilities")
            if status != 200:
                raise LeaseProtocolError("Task-Fähigkeiten nicht verfügbar")
        else:
            data = expected
        if data != expected:
            raise LeaseProtocolError("Task-Fähigkeiten nicht kanonisch bestätigt")
        return data

    def task_correction_context(self, task_id, *, lease_id, fence, task_version, generation):
        """Read a pending correction under the exact live task lease; never retries."""
        _identity(task_id)
        if (not isinstance(lease_id, str) or not lease_id or type(fence) is not int or fence <= 0
                or not isinstance(task_version, str) or not isinstance(generation, str)):
            raise LeaseProtocolError("Task-Korrekturbindung ungültig")
        if self.mode == "remote":
            from urllib.parse import urlencode
            query = urlencode({"fence": fence, "task_version": task_version, "generation": generation})
            status, data = self._http_request(
                "GET", f"/api/tasks/{task_id}/lease/correction-context?{query}",
                headers={"X-Lease-Id": lease_id},
            )
            if status != 200:
                raise LeaseProtocolError("Task-Korrekturkontext nicht bestätigt")
        else:
            from .task_result_service import read_correction_context, CorrectionContextDenied
            conn = self._get_local_connection()
            try:
                data = read_correction_context(conn, task_id, lease_id=lease_id, fence=fence,
                                               task_version=task_version, generation=generation)
            except CorrectionContextDenied:
                raise LeaseProtocolError("Task-Korrekturkontext nicht bestätigt") from None
            finally:
                if self._conn is None:
                    conn.close()
        if (not isinstance(data, dict) or data.get("schema") != "bach.task-result-correction-context.v1"
                or data.get("task_id") != task_id or data.get("fence") != fence
                or data.get("task_version") != task_version or data.get("generation") != generation):
            raise LeaseProtocolError("Task-Korrekturkontext nicht kanonisch bestätigt")
        correction = data.get("correction")
        if correction is not None:
            if not isinstance(correction, dict):
                raise LeaseProtocolError("Task-Korrekturquelle nicht kanonisch bestätigt")
            source = correction.get("source_result")
            if (type(correction.get("correction_id")) is not int
                    or type(correction.get("correction_round")) is not int
                    or not isinstance(correction.get("correction_note"), str)
                    or not isinstance(source, dict) or type(source.get("result_id")) is not int
                    or not isinstance(source.get("text"), str)
                    or source.get("result_sha256") != hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
                    or type(source.get("fence")) is not int or not isinstance(source.get("generation"), str)
                    or not isinstance(source.get("task_version"), str)):
                raise LeaseProtocolError("Task-Korrekturquelle nicht kanonisch bestätigt")
        return data

    def task_result_snapshot(self, task_id, *, operator_token=None):
        """Fresh canonical result/acceptance, never a provider or receipt cache."""
        _identity(task_id)
        if operator_token is not None and (not isinstance(operator_token, str) or not operator_token.strip()):
            raise LeaseProtocolError("Result-Operator-Token ist ungültig")
        headers = {"X-BACH-Result-Operator": operator_token} if operator_token is not None else None
        if self.mode == "remote":
            status, data = self._http_request("GET", f"/api/tasks/{task_id}/result", headers=headers)
            if status != 200:
                self._raise_denied(task_id, data)
        else:
            from .task_result_service import read_result
            conn = self._get_local_connection()
            try:
                data = read_result(conn, task_id, operator_token=operator_token)
                outside_snapshot = not conn.in_transaction
            finally:
                if self._conn is None:
                    conn.close()
            if outside_snapshot:
                from .worker_scope_evidence import project_scope_evidence
                data = project_scope_evidence(data)
        if (not isinstance(data, dict) or data.get("schema") != "bach.task-result-readback.v1"
                or type(data.get("task_id")) is not int or data["task_id"] != task_id
                or data.get("verified") is not True or type(data.get("status_revision")) is not int):
            raise LeaseProtocolError("Kanonischer Ergebnis-Readback nicht bestätigt")
        _version(data.get("task_version"), required=True)
        record = data.get("result")
        if record is not None:
            if (not isinstance(record, dict) or record.get("schema") != "bach.worker-result.v1"
                    or type(record.get("task_id")) is not int or record["task_id"] != task_id
                    or not isinstance(record.get("result"), str)
                    or record.get("result_sha256") != hashlib.sha256(record["result"].encode("utf-8")).hexdigest()
                    or type(record.get("accepted")) is not bool):
                raise LeaseProtocolError("Kanonischer Ergebnisinhalt nicht bestätigt")
            if record["accepted"] and (data.get("status") not in {"done", "completed"}
                    or record.get("task_version") != data["task_version"]
                    or record.get("accepted_status_event_id") != data["status_revision"]
                    or not record.get("accepted_by") or type(record.get("acceptance_event_id")) is not int):
                raise LeaseProtocolError("Aktuelle kanonische Abnahme nicht bestätigt")
        capabilities = data.get("operator_capabilities")
        if capabilities is not None and (
            not isinstance(capabilities, dict)
            or type(capabilities.get("accept_result")) is not bool
            or type(capabilities.get("request_correction")) is not bool
        ):
            raise LeaseProtocolError("Result-Operatorfähigkeiten nicht kanonisch bestätigt")
        return data

    def task_result_history(self, task_id, *, before_event_id=None, limit=20):
        _identity(task_id)
        if before_event_id is not None and (type(before_event_id) is not int or before_event_id <= 0):
            raise LeaseProtocolError("Ungültiger Result-Historiencursor")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise LeaseProtocolError("Result-Historienlimit muss zwischen 1 und 50 liegen")
        if self.mode == "remote":
            from urllib.parse import urlencode
            query = {"limit": limit}
            if before_event_id is not None:
                query["before_event_id"] = before_event_id
            status, data = self._http_request(
                "GET", f"/api/tasks/{task_id}/result/history?{urlencode(query)}")
            if status != 200:
                self._raise_denied(task_id, data)
        else:
            from .task_result_service import read_result_history
            conn = self._get_local_connection()
            try:
                data = read_result_history(conn, task_id, before_event_id=before_event_id, limit=limit)
            finally:
                if self._conn is None:
                    conn.close()
        events = data.get("events") if isinstance(data, dict) else None
        if (not isinstance(data, dict) or data.get("schema") != "bach.task-result-history.v1"
                or data.get("task_id") != task_id or not isinstance(events, list)
                or len(events) > limit or type(data.get("has_more")) is not bool):
            raise LeaseProtocolError("Result-Historie nicht kanonisch bestätigt")
        ids = []
        for event in events:
            if (not isinstance(event, dict) or type(event.get("event_id")) is not int
                    or event["event_id"] <= 0 or not isinstance(event.get("occurred_at"), str)):
                raise LeaseProtocolError("Result-Historienereignis unvollständig")
            ids.append(event["event_id"])
            if event.get("type") == "result_submitted":
                result = event.get("result")
                if (not isinstance(result, dict) or type(result.get("result_id")) is not int
                        or not isinstance(result.get("text"), str)
                        or result.get("result_sha256") != hashlib.sha256(result["text"].encode("utf-8")).hexdigest()):
                    raise LeaseProtocolError("Historisches Originalergebnis nicht bestätigt")
            elif event.get("type") == "result_accepted":
                result = event.get("result")
                if not isinstance(result, dict) or type(result.get("result_id")) is not int:
                    raise LeaseProtocolError("Historische Abnahme nicht bestätigt")
            elif event.get("type") == "correction_requested":
                correction = event.get("correction")
                if (not isinstance(correction, dict) or type(correction.get("correction_id")) is not int
                        or not isinstance(correction.get("note"), str)):
                    raise LeaseProtocolError("Historische Korrektur nicht bestätigt")
            else:
                raise LeaseProtocolError("Unbekannter Result-Historientyp")
        if ids != sorted(set(ids), reverse=True):
            raise LeaseProtocolError("Result-Historie ist nicht absteigend sortiert")
        cursor = data.get("next_before_event_id")
        if data["has_more"]:
            if (len(events) != limit or not events or type(cursor) is not int
                    or cursor != events[-1]["event_id"]):
                raise LeaseProtocolError("Result-Historiencursor passt nicht zur Seite")
        elif cursor is not None:
            raise LeaseProtocolError("Unerwarteter Result-Historiencursor")
        return data

    def request_result_correction(self, task_id, payload, *, operator_token):
        _identity(task_id)
        if not isinstance(payload, dict) or not isinstance(operator_token, str) or not operator_token.strip():
            raise LeaseProtocolError("Korrekturanfrage oder Operator-Token ungültig")
        headers = {"X-BACH-Result-Operator": operator_token}
        if self.mode == "remote":
            status, data = self._http_request("POST", f"/api/tasks/{task_id}/result/correction",
                                              payload=payload, headers=headers)
            if status != 200:
                detail = data.get("detail") if isinstance(data, dict) else None
                if isinstance(detail, dict):
                    raise TaskResultOperationError(status, detail.get("code", "denied"),
                                                   detail.get("message", "Korrekturanfrage abgelehnt"))
                raise TaskResultOperationError(status, "denied", "Korrekturanfrage abgelehnt")
        else:
            from .task_result_service import request_result_correction
            conn = self._get_local_connection()
            try:
                data = request_result_correction(conn, task_id, payload, operator_token=operator_token)
            finally:
                if self._conn is None:
                    conn.close()
        if (not isinstance(data, dict) or data.get("schema") != "bach.task-result-correction-request.v1"
                or data.get("task_id") != task_id or data.get("request_id") != payload.get("request_id")
                or type(data.get("correction_id")) is not int or data["correction_id"] <= 0
                or type(data.get("correction_round")) is not int or data["correction_round"] <= 0
                or data.get("source_result_id") != payload.get("result_id")
                or data.get("source_result_sha256") != payload.get("result_sha256")
                or data.get("status") != "pending" or type(data.get("replayed")) is not bool):
            raise LeaseProtocolError("Korrektur-ACK passt nicht zur Anfrage")
        _version(data.get("next_task_version"), required=True)
        return data

    def task_candidates(self, *, limit=100, offset=0):
        """Canonical pending/open/in-progress page; Acquire decides claimability."""
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise LeaseProtocolError("Ungültige Task-Seite")
        if self.mode == "remote":
            from urllib.parse import urlencode
            query = urlencode({"status": "pending,in_progress", "limit": limit, "offset": offset})
            status, data = self._http_request("GET", f"/api/tasks?{query}")
            if status != 200:
                self._raise_denied(0, data)
        else:
            conn = self._get_local_connection()
            try:
                ensure_task_lease_schema(conn)
                where = "LOWER(TRIM(status)) IN ('pending', 'open', 'in_progress', 'progress')"
                # Legacy isolated schemas need not have created_at.
                columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
                # Review metadata is never a positive authority here. The
                # reserved marker and raw intent relation are exclusion-only,
                # so damaged review jobs cannot leak into ordinary pickup.
                if "source" in columns:
                    where += " AND COALESCE(source, '') NOT LIKE 'worker-result-review:v1:%'"
                intent_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='worker_result_review_intents'"
                ).fetchone() is not None
                if intent_table:
                    where += " AND NOT EXISTS (SELECT 1 FROM worker_result_review_intents r " \
                             "WHERE r.review_task_id=tasks.id)"
                total = conn.execute(f"SELECT COUNT(*) FROM tasks WHERE {where}").fetchone()[0]
                order = ("COALESCE(needs_split, 0) DESC, " + ("CASE UPPER(TRIM(priority)) "
                         "WHEN 'P1' THEN 1 WHEN '1' THEN 1 WHEN 'HIGH' THEN 1 WHEN 'HOCH' THEN 1 WHEN 'KRITISCH' THEN 1 "
                         "WHEN 'P2' THEN 2 WHEN '2' THEN 2 WHEN 'MEDIUM' THEN 2 WHEN 'MITTEL' THEN 2 WHEN 'WICHTIG' THEN 2 "
                         "WHEN 'P3' THEN 3 WHEN '3' THEN 3 WHEN 'LOW' THEN 3 WHEN 'NIEDRIG' THEN 3 WHEN 'NORMAL' THEN 3 "
                         "WHEN 'P4' THEN 4 WHEN '4' THEN 4 WHEN 'MINIMAL' THEN 4 ELSE 5 END, "
                         if "priority" in columns else ""))
                order += "created_at DESC, id DESC" if "created_at" in columns else "id DESC"
                cursor = conn.execute(f"SELECT * FROM tasks WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                                      (limit + 1, offset))
                names = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
                tasks = []
                for row in rows[:limit]:
                    item = dict(row) if isinstance(row, sqlite3.Row) else dict(zip(names, row))
                    item["task_version"] = task_content_version(item)
                    tasks.append(item)
                data = {"success": True, "tasks": tasks, "count": len(tasks), "total": total,
                        "has_more": len(rows) > limit, "offset": offset}
            finally:
                if self._conn is None:
                    conn.close()
        if (not isinstance(data, dict) or data.get("success") is not True
                or not isinstance(data.get("tasks"), list) or len(data["tasks"]) > limit
                or type(data.get("count")) is not int or data["count"] != len(data["tasks"])
                or type(data.get("total")) is not int or data["total"] < data["count"]
                or type(data.get("has_more")) is not bool
                or type(data.get("offset")) is not int or data["offset"] != offset):
            raise LeaseProtocolError("Ungültige kanonische Task-Seite")
        tasks = [self._public_snapshot(item) for item in data["tasks"]]
        if self.mode == "remote":
            # A remote worker has no local DB or private review authority.
            # Filter only as a defense-in-depth exclusion; never infer a grant
            # from a title, category, source, or remote metadata.
            tasks = [item for item in tasks if not (
                (type(item.get("source")) is str
                 and item["source"].startswith("worker-result-review:v1:"))
                or isinstance(item.get("review_intent"), dict)
                or item.get("category") == "worker-review")]
        if len({item["id"] for item in tasks}) != len(tasks):
            raise LeaseProtocolError("Doppelte Task in kanonischer Seite")
        return {"tasks": tasks, "total": data["total"], "has_more": data["has_more"], "offset": offset}

    def _grant(self, data, *, worker_id=None, host=None, lease_id=None, fence=None,
               task_version=None, result_generation=None, receive_time):
        if not isinstance(data, dict) or data.get("granted") is not True:
            raise LeaseProtocolError("ACK bestätigt keine Lease-Erteilung")
        for key, expected in (("worker_id", worker_id), ("host", host), ("lease_id", lease_id),
                              ("fence", fence), ("task_version", task_version)):
            if expected is not None and data.get(key) != expected:
                raise LeaseProtocolError("Lease-ACK stimmt nicht mit der Anfrage überein")
        required = ("task_id", "lease_id", "fence", "worker_id", "host", "issued_at",
                    "expires_at", "ttl_profile", "server_now", "task_version")
        if any(key not in data for key in required):
            raise LeaseProtocolError("Lease-ACK ist unvollständig")
        _version(data["task_version"], required=True)
        generation = _generation(data.get("result_generation"), required=result_generation is not None)
        if result_generation is not None and generation != result_generation:
            raise LeaseProtocolError("Lease-ACK stimmt nicht mit der Workergeneration überein")
        ack = LeaseAck(**{key: data[key] for key in required},
                       replayed=data.get("replayed") is True, local_receive_time=receive_time,
                       result_generation=generation)
        self._held[ack.task_id] = ack
        return ack

    def acquire(self, task_id, *, worker_id, host, request_id=None, ttl_profile="M", intent="",
                task_version=None, result_generation=None, config=None, now=None,
                _review_grant=None):
        if _review_grant is not None and self.mode != "local":
            raise LeaseProtocolError("Private Reviewgrants werden nur lokal eingelöst")
        _version(task_version)
        result_generation = _generation(result_generation)
        sent_at = now or datetime.now(timezone.utc)
        body = dict(worker_id=worker_id, host=host, request_id=request_id or str(uuid.uuid4()),
                    ttl_profile=ttl_profile, intent=intent, task_version=task_version)
        if result_generation is not None:
            body["result_generation"] = result_generation
        if _review_grant is not None:
            body["_review_grant"] = _review_grant
        data = self._call("acquire", task_id, body, config=config, now=now)
        # Sending time is conservative: response latency cannot extend the local deadline.
        return self._grant(data, worker_id=worker_id, host=host, task_version=task_version,
                           result_generation=result_generation, receive_time=sent_at)

    def _acquire_native_creator(self, task_id, *, delegation, worker_id, host,
                                task_version, ttl_profile="M", config=None, now=None):
        """Private lead-local entry; it has no HTTP equivalent or fallback."""
        if self.mode != "local":
            raise LeaseProtocolError("Creator-Delegation wird ausschließlich am lokalen TaskDB-Lead eingelöst")
        _identity(task_id)
        _version(task_version, required=True)
        sent_at = now or datetime.now(timezone.utc)
        conn = self._get_local_connection()
        try:
            result = _acquire_native_creator_lease(conn, task_id, delegation=delegation,
                worker_id=worker_id, host=host, task_version=task_version,
                ttl_profile=ttl_profile, config=config, now=now)
            status, data = result.http_status, result.payload
        except (LeaseValidationError, TaskNotFound):
            raise LeaseProtocolError("Private Creator-Delegation oder Task ungültig") from None
        finally:
            if self._conn is None:
                conn.close()
        if status != 200:
            self._raise_denied(task_id, data)
        if not isinstance(data, dict) or type(data.get("task_id")) is not int or data["task_id"] != task_id:
            raise LeaseProtocolError("Creator-ACK passt nicht zur gebundenen Task")
        _wire_time(data.get("server_now"))
        if data.get("result_generation") != delegation.generation:
            raise LeaseProtocolError("Creator-Reviewpflicht dieser Generation nicht bestätigt")
        return self._grant(data, worker_id=worker_id, host=host, task_version=task_version,
                           result_generation=delegation.generation, receive_time=sent_at)

    def worker_leases(self, worker_id):
        """Read every live lease of one exact physical worker without capabilities."""
        from hub._services.task_lease import read_worker_leases, _WORKER_RE
        if not isinstance(worker_id, str) or not _WORKER_RE.fullmatch(worker_id):
            raise LeaseProtocolError("Ungültige physische Worker-ID")
        if self.mode == "remote":
            from urllib.parse import urlencode
            status, data = self._http_request(
                "GET", "/api/tasks/leases/by-worker?" + urlencode({"worker_id": worker_id}))
            if status != 200:
                raise LeaseProtocolError("Worker-Leases nicht kanonisch lesbar")
        else:
            conn = self._get_local_connection()
            try:
                data = read_worker_leases(conn, worker_id).payload
            finally:
                if self._conn is None:
                    conn.close()
        if (not isinstance(data, dict) or set(data) != {
                "schema", "worker_id", "server_now", "complete", "leases"}
                or data.get("schema") != "bach.worker-leases.v1"
                or data.get("worker_id") != worker_id or data.get("complete") is not True
                or not isinstance(data.get("leases"), list)):
            raise LeaseProtocolError("Unvollständiger Worker-Lease-Readback")
        _wire_time(data.get("server_now"))
        seen = set()
        for lease in data["leases"]:
            if (not isinstance(lease, dict) or set(lease) != {
                    "task_id", "fence", "expires_at", "legacy"}
                    or type(lease["task_id"]) is not int or lease["task_id"] <= 0
                    or lease["task_id"] in seen or type(lease["fence"]) is not int
                    or lease["fence"] < 0 or type(lease["legacy"]) is not bool):
                raise LeaseProtocolError("Ungültiger Worker-Lease-Readback")
            if lease["expires_at"] is not None:
                _wire_time(lease["expires_at"])
            seen.add(lease["task_id"])
        return data

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

    def renew(self, task_id, *, lease_id, fence, task_version=None, _project_binding=None, config=None, now=None):
        _identity(task_id, lease_id, fence)
        _version(task_version)
        sent_at = now or datetime.now(timezone.utc)
        data = self._call("renew", task_id, dict(lease_id=lease_id, fence=fence, task_version=task_version, **({"_project_binding": _project_binding} if _project_binding is not None else {})), config=config, now=now)
        previous = self._held.get(task_id)
        return self._grant(data, lease_id=lease_id, fence=fence, task_version=task_version,
                           worker_id=previous.worker_id if previous else None,
                           host=previous.host if previous else None,
                           result_generation=previous.result_generation if previous else None,
                           receive_time=sent_at)

    def tool_trace_start(self, identity, *, lease_id, arguments_sha256):
        """Persist a tool start through the same canonical task authority."""
        from hub._services.chat.worker_tool_trace import TraceIdentity, append_started
        if not isinstance(identity, TraceIdentity):
            raise LeaseProtocolError("Werkzeug-Trace-Identität fehlt")
        _identity(identity.task_id, lease_id, identity.fence)
        if self.mode == "remote":
            payload = {"schema": "bach.worker-tool-trace.v1", "fence": identity.fence,
                       "worker_id": identity.worker_id, "generation": identity.generation,
                       "task_version": identity.task_version, "request_id": identity.request_id,
                       "source": identity.source, "tool_name": identity.tool_name,
                       "arguments_sha256": arguments_sha256}
            status, data = self._http_request(
                "POST", f"/api/tasks/{identity.task_id}/tool-trace/start", payload,
                headers={"X-Lease-Id": lease_id})
            if status != 200:
                self._raise_denied(identity.task_id, data)
            return _trace_start_ack(data, task_id=identity.task_id,
                                    request_id=identity.request_id)
        conn = self._get_local_connection()
        try:
            data = append_started(conn, identity, lease_id=lease_id,
                                  arguments_sha256=arguments_sha256)
            return _trace_start_ack(data, task_id=identity.task_id,
                                    request_id=identity.request_id)
        except Exception:
            raise LeaseProtocolError("Kanonischer Werkzeug-Trace-Start fehlgeschlagen") from None
        finally:
            if self._conn is None:
                conn.close()

    def tool_trace_phase(self, identity, phase, *, receipt_id=None, result_sha256=None,
                         completion_token=None):
        """Append a phase correlated to a privately bound durable start."""
        from hub._services.chat.worker_tool_trace import (
            TraceIdentity, append_phase, _COMPLETION_TOKEN,
        )
        if not isinstance(identity, TraceIdentity):
            raise LeaseProtocolError("Werkzeug-Trace-Identität fehlt")
        if (not isinstance(completion_token, str)
                or not _COMPLETION_TOKEN.fullmatch(completion_token)):
            raise LeaseProtocolError("Werkzeug-Trace-Abschluss fehlt")
        payload = {"schema": "bach.worker-tool-trace.v1", "fence": identity.fence,
                   "worker_id": identity.worker_id, "generation": identity.generation,
                   "task_version": identity.task_version, "request_id": identity.request_id,
                   "source": identity.source, "tool_name": identity.tool_name,
                   "phase": phase, "receipt_id": receipt_id, "result_sha256": result_sha256}
        if self.mode == "remote":
            status, data = self._http_request(
                "POST", f"/api/tasks/{identity.task_id}/tool-trace/events", payload,
                headers={"X-Trace-Completion": completion_token})
            if status != 200:
                self._raise_denied(identity.task_id, data)
            return _trace_ack(data, task_id=identity.task_id,
                              request_id=identity.request_id, phase=phase)
        conn = self._get_local_connection()
        try:
            data = append_phase(conn, identity, phase, receipt_id=receipt_id,
                                result_sha256=result_sha256,
                                completion_token=completion_token)
            return _trace_ack(data, task_id=identity.task_id,
                              request_id=identity.request_id, phase=phase)
        except Exception:
            raise LeaseProtocolError("Kanonische Werkzeug-Trace-Phase fehlgeschlagen") from None
        finally:
            if self._conn is None:
                conn.close()

    def tool_trace_events(self, task_id, *, limit=100, offset=0):
        """Read a bounded safe page from the canonical task database or lead."""
        from hub._services.chat.worker_tool_trace import (
            SCHEMA, SOURCES, PHASES, _GENERATION, _HASH, _ID, _TOOL, _WORKER, list_events,
        )
        _identity(task_id)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 100_000:
            raise LeaseProtocolError("Ungültige Werkzeug-Trace-Seite")
        if self.mode == "remote":
            status, data = self._http_request(
                "GET", f"/api/tasks/{task_id}/tool-trace/events?limit={limit}&offset={offset}")
            if status != 200:
                self._raise_denied(task_id, data)
        else:
            conn = self._get_local_connection()
            try:
                data = list_events(conn, task_id, limit=limit, offset=offset)
            except Exception:
                raise LeaseProtocolError("Kanonischer Werkzeug-Trace ist nicht verfügbar") from None
            finally:
                if self._conn is None:
                    conn.close()
        expected_fields = {"event_id", "schema", "task_id", "fence", "worker_id",
                           "generation", "task_version", "request_id", "receipt_id",
                           "source", "tool_name", "phase", "occurred_at",
                           "arguments_sha256", "result_sha256", "effect_status"}
        if not isinstance(data, dict):
            raise LeaseProtocolError("Kanonischer Werkzeug-Trace-Readback ist ungültig")
        events = data.get("events")
        if (data.get("schema") != SCHEMA or type(data.get("task_id")) is not int
                or data["task_id"] != task_id or type(data.get("limit")) is not int
                or data["limit"] != limit or type(data.get("offset")) is not int
                or data["offset"] != offset or not isinstance(events, list)
                or len(events) > limit or type(data.get("count")) is not int
                or data["count"] != len(events)):
            raise LeaseProtocolError("Kanonischer Werkzeug-Trace-Readback ist ungültig")
        for event in events:
            if (not isinstance(event, dict) or set(event) != expected_fields
                    or event.get("schema") != SCHEMA
                    or type(event.get("event_id")) is not int or event["event_id"] <= 0
                    or type(event.get("task_id")) is not int or event["task_id"] != task_id
                    or type(event.get("fence")) is not int or event["fence"] <= 0
                    or not isinstance(event.get("worker_id"), str) or not _WORKER.fullmatch(event["worker_id"])
                    or not isinstance(event.get("generation"), str) or not _GENERATION.fullmatch(event["generation"])
                    or not isinstance(event.get("task_version"), str) or not re.fullmatch(r"[a-f0-9]{64}", event["task_version"])
                    or not isinstance(event.get("request_id"), str) or not _ID.fullmatch(event["request_id"])
                    or not isinstance(event.get("source"), str) or event["source"] not in SOURCES
                    or not isinstance(event.get("tool_name"), str) or not _TOOL.fullmatch(event["tool_name"])
                    or not isinstance(event.get("phase"), str) or event["phase"] not in PHASES
                    or event.get("effect_status") != "unknown"):
                raise LeaseProtocolError("Kanonischer Werkzeug-Trace-Eintrag ist ungültig")
            _wire_time(event.get("occurred_at"))
            receipt = event.get("receipt_id")
            args_hash = event.get("arguments_sha256")
            result_hash = event.get("result_sha256")
            if ((receipt is not None and (not isinstance(receipt, str) or not _ID.fullmatch(receipt)))
                    or (args_hash is not None and (not isinstance(args_hash, str) or not _HASH.fullmatch(args_hash)))
                    or (result_hash is not None and (not isinstance(result_hash, str) or not _HASH.fullmatch(result_hash)))):
                raise LeaseProtocolError("Kanonischer Werkzeug-Trace-Digest ist ungültig")
            phase = event["phase"]
            if ((phase == "started" and (receipt is not None or args_hash is None or result_hash is not None))
                    or (phase == "returned" and (receipt is None or args_hash is not None or result_hash is None))
                    or (phase == "failed" and (receipt is not None or args_hash is not None or result_hash is not None))
                    or (phase == "acknowledged" and (receipt is None or args_hash is not None or result_hash is not None))):
                raise LeaseProtocolError("Kanonischer Werkzeug-Trace-Phaseninhalt ist ungültig")
        return {"schema": SCHEMA, "task_id": task_id, "events": events,
                "count": len(events), "limit": limit, "offset": offset}

    def submit_result(self, task_id, *, lease_id, fence, task_version, generation, result,
                      config=None, now=None, _review_binding=None, _project_binding=None):
        from .task_result_service import validate_submission
        _identity(task_id, lease_id, fence)
        _version(task_version, required=True)
        try:
            _, _, digest = validate_submission({"generation": generation, "result": result})
        except ValueError as exc:
            raise LeaseProtocolError(str(exc)) from None
        data = self._call("release", task_id, {
            "lease_id": lease_id, "fence": fence, "task_version": task_version,
            "outcome": "review", "worker_result": {"generation": generation, "result": result},
            **({"_review_binding": _review_binding} if _review_binding is not None else {}),
            **({"_project_binding": _project_binding} if _project_binding is not None else {}),
        }, config=config, now=now)
        record = data.get("worker_result")
        if (data.get("released") is not True or data.get("outcome") != "review"
                or data.get("status") != "review" or type(data.get("fence")) is not int or data["fence"] != fence
                or not isinstance(record, dict) or record.get("schema") != "bach.worker-result.v1"
                or type(record.get("result_id")) is not int or record["result_id"] <= 0
                or type(record.get("task_id")) is not int or record["task_id"] != task_id
                or type(record.get("fence")) is not int or record["fence"] != fence
                or record.get("generation") != generation or record.get("task_version") != task_version
                or record.get("result_sha256") != digest or record.get("result") != result
                or record.get("accepted") is not False
                or type(record.get("submission_event_id")) is not int
                or type(record.get("status_revision")) is not int
                or not 0 < record["status_revision"] < record["submission_event_id"]):
            raise LeaseProtocolError("Ergebnisabgabe nicht kanonisch bestätigt")
        self._held.pop(task_id, None)
        return WorkerResultAck(LeaseReleaseAck(True, task_id, "review", "review", fence, data["server_now"]), record)

    def release(self, task_id, *, lease_id, fence, task_version=None, outcome="done", result_ref="", note="", _project_binding=None, config=None, now=None):
        _identity(task_id, lease_id, fence)
        _version(task_version)
        data = self._call("release", task_id, dict(lease_id=lease_id, fence=fence, task_version=task_version,
                         outcome=outcome, result_ref=result_ref, note=note, **({"_project_binding": _project_binding} if _project_binding is not None else {})), config=config, now=now)
        statuses = {"done": "done", "return": "pending", "blocked": "blocked", "review": "review"}
        if (data.get("released") is not True or type(data.get("fence")) is not int or data["fence"] != fence
                or data.get("outcome") != outcome or data.get("status") != statuses.get(outcome)):
            raise LeaseProtocolError("Release-ACK passt nicht zur Anfrage")
        self._held.pop(task_id, None)
        return LeaseReleaseAck(True, task_id, outcome, data["status"], fence, data["server_now"])

    def update(self, task_id, *, lease_id, fence, task_version, changes, _project_binding=None, config=None, now=None):
        _identity(task_id, lease_id, fence)
        _version(task_version, required=True)
        if not isinstance(changes, dict) or not changes:
            raise LeaseProtocolError("Inhaltsupdate braucht Felder")
        data = self._call("update", task_id, dict(lease_id=lease_id, fence=fence,
                         task_version=task_version, changes=changes, **({"_project_binding": _project_binding} if _project_binding is not None else {})), config=config, now=now)
        version = _version(data.get("task_version"), required=True)
        if (data.get("updated") is not True or type(data.get("fence")) is not int
                or data["fence"] != fence or data.get("previous_task_version") != task_version
                or data.get("fields") != sorted(changes)):
            raise LeaseProtocolError("Inhaltsupdate-ACK passt nicht zur Anfrage")
        previous = self._held.get(task_id)
        if previous:
            self._held[task_id] = replace(previous, task_version=version)
        return LeaseUpdateAck(task_id, fence, task_version, version,
                              tuple(data["fields"]), data["server_now"])

    def decompose(self, task_id, *, lease_id, fence, task_version, subtasks, close_parent=True, sequential=False, _project_binding=None, config=None, now=None):
        _identity(task_id, lease_id, fence)
        _version(task_version, required=True)
        body = dict(lease_id=lease_id, fence=fence, task_version=task_version, subtasks=subtasks,
                    close_parent=close_parent, sequential=sequential, **({"_project_binding": _project_binding} if _project_binding is not None else {}))
        data = self._call("decompose", task_id, body, config=config, now=now)
        ids = data.get("created_ids")
        if (data.get("decomposed") is not True or type(data.get("parent_closed")) is not bool
                or data["parent_closed"] != close_parent or type(data.get("fence")) is not int or data["fence"] != fence
                or not isinstance(ids, list) or len(ids) != len(subtasks) or not ids
                or any(type(i) is not int or i <= 0 or i == task_id for i in ids)
                or len(set(ids)) != len(ids) or type(data.get("created_count")) is not int
                or data["created_count"] != len(ids)):
            raise LeaseProtocolError("Zerlegungs-ACK passt nicht zur Anfrage")
        reused = data.get("reused_ids", [])  # absent on older authorities: nothing reused
        if (not isinstance(reused, list) or len(set(reused)) != len(reused)
                or any(type(i) is not int or i not in ids for i in reused)):
            raise LeaseProtocolError("Zerlegungs-ACK passt nicht zur Anfrage")
        version = _version(data.get("task_version"), required=True)
        if version == task_version:
            raise LeaseProtocolError("Zerlegungs-ACK hat keine neue Inhaltsversion")
        previous = self._held.get(task_id)
        if close_parent:
            self._held.pop(task_id, None)
        elif previous:
            self._held[task_id] = replace(previous, task_version=version)
        return LeaseDecomposeAck(task_id, tuple(ids), len(ids), close_parent, fence, version, data["server_now"],
                                 tuple(reused))

    def _raise_denied(self, task_id, payload):
        raw_reason = payload.get("reason") if isinstance(payload, dict) else None
        reason = raw_reason if type(raw_reason) is str and raw_reason in _SAFE_DENIAL_REASONS else "denied"
        safe_payload = {"task_id": task_id, "reason": reason}

        if reason != "denied":
            server_now = _validated_denial_utc(payload.get("server_now"))
            if server_now is None:
                reason = "denied"
                safe_payload = {"task_id": task_id, "reason": reason}
            elif reason == "creator_priority":
                until = _validated_denial_utc(payload.get("until"))
                if until is None or until <= server_now:
                    reason = "denied"
                    safe_payload = {"task_id": task_id, "reason": reason}
                else:
                    safe_payload["server_now"] = _format_denial_utc(server_now)
                    safe_payload["until"] = _format_denial_utc(until)
            else:
                safe_payload["server_now"] = _format_denial_utc(server_now)

        classes = {"stale_fence": LeaseStaleFenceError, "expired": LeaseExpiredError,
                   "max_total_reached": LeaseMaxTotalReachedError}
        raise classes.get(reason, LeaseDeniedError)(task_id, reason, safe_payload)



_RESULT_SERVICE_SAFE_ERRORS = {
    "service_credential_invalid": "Service-Anmeldung ungültig",
    "service_revoked": "Service wurde widerrufen",
    "service_scope_denied": "Service-Scope lehnt die Aktion ab",
    "scope_denied": "Service-Scope lehnt die Aktion ab",
    "self_review": "Eigene Ergebnisse dürfen nicht geprüft werden",
    "producer_binding_missing": "Ergebnisherkunft ist nicht bestätigt",
    "invalid_request": "Service-Anfrage ist ungültig",
    "ambiguous_credentials": "Mehrdeutige Ergebnisanmeldung",
    "service_revision_required": "Service-Scope-Version muss bestätigt werden",
    "service_revision_conflict": "Service-Scope hat sich geändert; bitte neu laden",
    "result_changed_reload": "Ergebnis oder Task hat sich geändert; bitte neu laden",
    "task_not_revisable": "Task ist für diese Aktion nicht freigegeben",
    "completion_policy_operator_review_required": "Policyverwalteter Abschluss benötigt die Operator-Prüfung",
    "correction_request_invalid": "Korrekturanfrage ist ungültig",
    "result_service_unavailable": "Ergebnisreview-Dienst ist nicht verfügbar",
    "result_history_unavailable": "Ergebnisverlauf ist nicht verfügbar",
    "task_not_found": "Task nicht gefunden",
}


class TaskResultServiceClient(TaskLeaseClient):
    """Result-service client; general task and worker APIs are unavailable."""

    def __init__(self, *, service_id, service_token, **kwargs):
        if (not isinstance(service_id, str) or not service_id.strip()
                or service_id != service_id.strip() or len(service_id) > 128 or "\x00" in service_id
                or not isinstance(service_token, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{43,256}", service_token) is None):
            raise LeaseProtocolError("Service-Anmeldung ist ungültig")
        configured_device_token = kwargs.pop("device_token", None)
        if configured_device_token:
            raise LeaseProtocolError("Service-Client akzeptiert keine Geräteanmeldung")
        self._result_service_id = service_id
        self._result_service_token = service_token
        super().__init__(**kwargs)
        # TaskLeaseClient also reads ambient BACH_DEVICE_TOKEN. This adapter must
        # keep that worker/operator credential out of its identity entirely.
        self._device_token = None

    def _deny_general_task_api(self, *_args, **_kwargs):
        raise LeaseProtocolError("Service-Client darf keine allgemeine Task-API verwenden")

    # These inherited paths can use a device bearer remotely or direct SQLite
    # locally. Result-service methods below bypass them and use service auth.
    _http_request = _deny_general_task_api
    _call = _deny_general_task_api
    _acquire_native_creator = _deny_general_task_api
    task_snapshot = _deny_general_task_api
    task_capabilities = _deny_general_task_api
    task_correction_context = _deny_general_task_api
    task_candidates = _deny_general_task_api
    tool_trace_start = _deny_general_task_api
    tool_trace_phase = _deny_general_task_api
    tool_trace_events = _deny_general_task_api

    def _allows_result_service_server_error(self, status, payload, method, path):
        if status != 503:
            return False
        route = path.split("?", 1)[0]
        if re.fullmatch(r"/api/tasks/[1-9][0-9]*/result(?:/history|/correction|/accept)?", route) is None:
            return False
        detail = payload.get("detail") if isinstance(payload, dict) else None
        return (isinstance(detail, dict) and set(payload) == {"detail"}
                and set(detail) == {"code", "message"}
                and detail.get("code") == "result_service_unavailable"
                and isinstance(detail.get("message"), str) and len(detail["message"]) <= 200)

    def _service_headers(self, revision=None):
        headers = {"X-BACH-Result-Service-ID": self._result_service_id,
                   "X-BACH-Result-Service": self._result_service_token}
        if revision is not None:
            if type(revision) is not int or revision <= 0:
                raise LeaseProtocolError("Service-Scope-Version muss bestätigt werden")
            headers["X-BACH-Result-Service-Revision"] = str(revision)
        return headers

    def _service_error(self, status, payload):
        detail = payload.get("detail") if isinstance(payload, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        if not isinstance(code, str) or code not in _RESULT_SERVICE_SAFE_ERRORS:
            code = "service_request_denied"
            message = "Service-Anfrage wurde abgelehnt"
        else:
            message = _RESULT_SERVICE_SAFE_ERRORS[code]
        raise TaskResultOperationError(status, code, message)

    def _service_http(self, method, path, payload=None, revision=None):
        status, data = self._http_service_request(
            method, path, payload=payload, headers=self._service_headers(revision))
        if status != 200:
            self._service_error(status, data)
        return data

    @staticmethod
    def _validate_service_capabilities(data, task_id):
        if (not isinstance(data, dict) or data.get("schema") != "bach.task-result-readback.v1"
                or type(data.get("task_id")) is not int or data["task_id"] != task_id
                or data.get("verified") is not True or type(data.get("status_revision")) is not int
                or "operator_capabilities" in data):
            raise LeaseProtocolError("Service-Readback ist nicht kanonisch bestätigt")
        _version(data.get("task_version"), required=True)
        capabilities = data.get("service_capabilities")
        if (not isinstance(capabilities, dict)
                or capabilities.get("schema") != "bach.task-result-service-capabilities.v1"
                or type(capabilities.get("revision")) is not int or capabilities["revision"] <= 0
                or not isinstance(capabilities.get("actions"), dict)
                or set(capabilities["actions"]) != {"read", "history", "accept", "correction"}
                or any(type(value) is not bool for value in capabilities["actions"].values())
                or not isinstance(capabilities.get("reasons"), dict)
                or not set(capabilities["reasons"]) <= set(capabilities["actions"])
                or any(capabilities["actions"].get(key) is not False
                       for key in capabilities["reasons"])):
            raise LeaseProtocolError("Service-Fähigkeiten sind nicht kanonisch bestätigt")
        record = data.get("result")
        if record is not None and (
                not isinstance(record, dict) or record.get("schema") != "bach.worker-result.v1"
                or type(record.get("task_id")) is not int or record["task_id"] != task_id
                or not isinstance(record.get("result"), str)
                or record.get("result_sha256") != hashlib.sha256(record["result"].encode("utf-8")).hexdigest()
                or type(record.get("accepted")) is not bool):
            raise LeaseProtocolError("Kanonischer Ergebnisinhalt nicht bestätigt")
        return data

    def task_result_snapshot(self, task_id):
        _identity(task_id)
        if self.mode == "remote":
            data = self._service_http("GET", f"/api/tasks/{task_id}/result")
        else:
            from .task_result_service import read_result
            conn = self._get_local_connection()
            try:
                data = read_result(conn, task_id, service_id=self._result_service_id,
                                    service_token=self._result_service_token)
            finally:
                if self._conn is None:
                    conn.close()
        return self._validate_service_capabilities(data, task_id)

    def task_result_history(self, task_id, *, before_event_id=None, limit=20):
        _identity(task_id)
        if before_event_id is not None and (type(before_event_id) is not int or before_event_id <= 0):
            raise LeaseProtocolError("Ungültiger Result-Historiencursor")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise LeaseProtocolError("Result-Historienlimit muss zwischen 1 und 50 liegen")
        if self.mode == "remote":
            from urllib.parse import urlencode
            query = {"limit": limit}
            if before_event_id is not None:
                query["before_event_id"] = before_event_id
            data = self._service_http("GET", f"/api/tasks/{task_id}/result/history?{urlencode(query)}")
        else:
            from .task_result_service import read_result_history
            conn = self._get_local_connection()
            try:
                data = read_result_history(conn, task_id, before_event_id=before_event_id,
                                          limit=limit, service_id=self._result_service_id,
                                          service_token=self._result_service_token)
            finally:
                if self._conn is None:
                    conn.close()
        events = data.get("events") if isinstance(data, dict) else None
        if (not isinstance(data, dict) or data.get("schema") != "bach.task-result-history.v1"
                or type(data.get("task_id")) is not int or data["task_id"] != task_id
                or not isinstance(events, list) or len(events) > limit
                or type(data.get("has_more")) is not bool
                or type(data.get("service_revision")) is not int or data["service_revision"] <= 0):
            raise LeaseProtocolError("Service-Historie ist nicht kanonisch bestätigt")
        ids = []
        for event in events:
            if (not isinstance(event, dict) or type(event.get("event_id")) is not int
                    or event["event_id"] <= 0 or not isinstance(event.get("occurred_at"), str)):
                raise LeaseProtocolError("Service-Historienereignis unvollständig")
            ids.append(event["event_id"])
            if event.get("type") == "result_submitted":
                result = event.get("result")
                if (not isinstance(result, dict) or type(result.get("result_id")) is not int
                        or not isinstance(result.get("text"), str)
                        or result.get("result_sha256") != hashlib.sha256(result["text"].encode("utf-8")).hexdigest()):
                    raise LeaseProtocolError("Historisches Originalergebnis nicht bestätigt")
            elif event.get("type") == "result_accepted":
                result = event.get("result")
                if (not isinstance(result, dict) or type(result.get("result_id")) is not int
                        or not isinstance(result.get("result_sha256"), str)):
                    raise LeaseProtocolError("Historische Abnahme nicht bestätigt")
            elif event.get("type") == "correction_requested":
                correction = event.get("correction")
                if (not isinstance(correction, dict) or type(correction.get("correction_id")) is not int
                        or not isinstance(correction.get("note"), str)):
                    raise LeaseProtocolError("Historische Korrektur nicht bestätigt")
            else:
                raise LeaseProtocolError("Unbekannter Result-Historientyp")
        if ids != sorted(set(ids), reverse=True):
            raise LeaseProtocolError("Service-Historie ist nicht absteigend sortiert")
        cursor = data.get("next_before_event_id")
        if data["has_more"]:
            if len(events) != limit or not events or type(cursor) is not int or cursor != events[-1]["event_id"]:
                raise LeaseProtocolError("Service-Historiencursor passt nicht zur Seite")
        elif cursor is not None:
            raise LeaseProtocolError("Unerwarteter Service-Historiencursor")
        return data

    def request_result_correction(self, task_id, payload, *, service_revision):
        _identity(task_id)
        if not isinstance(payload, dict):
            raise LeaseProtocolError("Korrekturanfrage ist ungültig")
        if self.mode == "remote":
            data = self._service_http("POST", f"/api/tasks/{task_id}/result/correction",
                                      payload=payload, revision=service_revision)
        else:
            from .task_result_service import request_result_correction
            conn = self._get_local_connection()
            try:
                data = request_result_correction(conn, task_id, payload,
                    service_id=self._result_service_id, service_token=self._result_service_token,
                    service_revision=service_revision)
            finally:
                if self._conn is None:
                    conn.close()
        if (not isinstance(data, dict) or data.get("schema") != "bach.task-result-correction-request.v1"
                or type(data.get("task_id")) is not int or data["task_id"] != task_id
                or data.get("request_id") != payload.get("request_id")
                or type(data.get("correction_id")) is not int or data["correction_id"] <= 0
                or type(data.get("correction_round")) is not int or data["correction_round"] <= 0
                or data.get("source_result_id") != payload.get("result_id")
                or data.get("source_result_sha256") != payload.get("result_sha256")
                or data.get("status") != "pending" or type(data.get("replayed")) is not bool
                or data.get("service_revision") != service_revision):
            raise LeaseProtocolError("Service-Korrektur-ACK passt nicht zur Anfrage")
        _version(data.get("next_task_version"), required=True)
        return data

    def accept_result(self, task_id, *, result_id, digest, task_version, status_revision,
                      service_revision):
        _identity(task_id)
        if (type(result_id) is not int or result_id <= 0
                or not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                or type(status_revision) is not int or status_revision < 0
                or type(service_revision) is not int or service_revision <= 0):
            raise LeaseProtocolError("Service-Abnahme-CAS ist ungültig")
        _version(task_version, required=True)
        payload = {"result_id": result_id, "result_sha256": digest,
                   "task_version": task_version, "status_revision": status_revision}
        if self.mode == "remote":
            data = self._service_http("POST", f"/api/tasks/{task_id}/result/accept",
                                      payload=payload, revision=service_revision)
        else:
            from .task_result_service import accept_result
            conn = self._get_local_connection()
            try:
                data = accept_result(conn, task_id, result_id, digest=digest,
                    task_version=task_version, status_revision=status_revision,
                    service_id=self._result_service_id, service_token=self._result_service_token,
                    service_revision=service_revision)
            finally:
                if self._conn is None:
                    conn.close()
        if (not isinstance(data, dict)
                or data.get("schema") != "bach.task-result-service-acceptance.v1"
                or type(data.get("task_id")) is not int or data["task_id"] != task_id
                or data.get("result_id") != result_id or data.get("result_sha256") != digest
                or data.get("task_version") != task_version
                or data.get("source_status_revision") != status_revision
                or type(data.get("accepted_status_revision")) is not int
                or data.get("accepted_status_revision") <= status_revision
                or data.get("accepted") is not True or data.get("service_revision") != service_revision):
            raise LeaseProtocolError("Service-Abnahme-ACK passt nicht zur Anfrage")
        return data
