# SPDX-License-Identifier: MIT
"""Lead-seitiger Task-Lease-Dienst der BACH-TaskDB (BACH #1721, T793 LEASE 2/4).

Setzt den Vertrag ``docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md`` um:
acquire, read (who-has), renew und release/return für Tasks der Lead-TaskDB.

Grundsätze (Vertrag §3-§11):

* **Eine Authority.** Lease-Daten liegen als additive Spalten in ``tasks``;
  es gibt keine zweite Claim-Datenbank. Ressource ist ausschließlich die
  stabile ``tasks.id``.
* **Serverzeit.** Der Lead bestimmt alle Zeitpunkte (UTC) und das TTL-Profil.
  Jede Antwort trägt ``server_now``.
* **Atomar.** Jede Operation läuft in einer eigenen ``BEGIN IMMEDIATE``-
  Transaktion. Prüfung und Schreiben erfolgen unter derselben Schreibsperre;
  der abschließende UPDATE prüft Fence bzw. Vorzustand zusätzlich im WHERE.
* **Fencing.** ``claim_fence`` steigt bei jedem erfolgreichen Acquire um 1
  und sinkt nie. Renew/Release verlangen passende ``lease_id`` *und*
  ``fence`` bei lebendem Lease.
* **Capability.** ``lease_id`` geht nur an den Halter (ACK, idempotente
  Wiederholung, eigener Read mit ``X-Lease-Id``) und wird nie in
  Holder-Ansichten oder ``task_history`` geschrieben.
* **Ablehnung ist ein Ergebnis**, kein Fehler (``granted: false`` + ``reason``).

Nicht Teil dieses Moduls (Folgearbeit #1722): Umstellung der Clients
(``bach task``, ``bach_api``, Headless-API, Trithon-Dispatch) auf Leases.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from hub._services.task_schema import (
        ensure_task_claim_columns,
        ensure_task_slot_columns,
        inspect_task_dependencies,
    )
except ImportError:  # pragma: no cover - Paketimport aus system/hub
    from .task_schema import ensure_task_claim_columns, ensure_task_slot_columns, inspect_task_dependencies


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

#: Startwerte aus Vertrag §6: Profil -> (TTL je Acquire/Renew, Höchstlaufzeit ab issued_at), Sekunden.
DEFAULT_PROFILES: dict[str, tuple[int, int]] = {
    "S": (15 * 60, 2 * 3600),
    "M": (30 * 60, 8 * 3600),
    "L": (60 * 60, 24 * 3600),
    "XL": (120 * 60, 72 * 3600),
}
DEFAULT_PROFILE = "M"
#: Vertrag §8.6: Ersteller-Vorrang ab created_at.
DEFAULT_CREATOR_WINDOW_SECONDS = 10 * 60
#: Vertrag §11.2: Lebensdauer eines Alt-Claims ohne claim_id (wie claim_task_atomic).
LEGACY_CLAIM_SECONDS = 1800
#: Vertrag §6: XL nur bei estimated_minutes > 480 (sonst Herabstufung auf L).
XL_MIN_ESTIMATED_MINUTES = 480

CLAIMABLE_STATUSES = frozenset({"pending", "open"})
TERMINAL_STATUSES = frozenset({"done", "completed", "cancelled", "blocked"})
RELEASE_OUTCOMES = {"return": "pending", "done": "done", "blocked": "blocked"}

#: Additive Lease-Spalten (Vertrag §4 + §11.1). Keine Daten werden umgeschrieben.
LEASE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("claim_id", "TEXT"),
    ("claim_host", "TEXT"),
    ("claim_issued_at", "TEXT"),
    ("claim_expires_at", "TEXT"),
    ("claim_heartbeat_at", "TEXT"),
    ("claim_fence", "INTEGER NOT NULL DEFAULT 0"),
    ("claim_ttl_profile", "TEXT"),
    ("claim_salt_ref", "TEXT"),
    ("claim_intent", "TEXT"),
    ("claim_request_id", "TEXT"),
    ("claim_task_version", "TEXT"),
)
#: Spalten, die Release/Invalidierung leert; claim_fence bleibt als Hochwassermarke.
_CLEARED_ON_RELEASE = (
    "claim_id", "claim_host", "claim_issued_at", "claim_expires_at", "claim_heartbeat_at",
    "claim_ttl_profile", "claim_salt_ref", "claim_intent", "claim_request_id",
    "claimed_by", "claimed_at", "claim_task_version",
)

_WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}@[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
_TICKET_RE = re.compile(r"ticket:(T-\d{8}-[A-Za-z0-9-]+)")


@dataclass(frozen=True)
class LeaseConfig:
    """Serverseitig konfigurierbare Lease-Parameter (Vertrag §6, §8.6)."""

    profiles: Mapping[str, tuple[int, int]] = field(default_factory=lambda: dict(DEFAULT_PROFILES))
    default_profile: str = DEFAULT_PROFILE
    creator_window_seconds: int = DEFAULT_CREATOR_WINDOW_SECONDS
    legacy_claim_seconds: int = LEGACY_CLAIM_SECONDS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LeaseConfig:
        """Liest ``BACH_TASK_LEASE_PROFILES`` (JSON ``{"M": [1800, 28800], …}``)
        und ``BACH_TASK_LEASE_CREATOR_WINDOW`` (Sekunden). Ungültige Werte werden
        verworfen; es gelten dann die Startwerte (fail-safe, kein Teilzustand)."""
        env = os.environ if environ is None else environ
        profiles = dict(DEFAULT_PROFILES)
        raw = env.get("BACH_TASK_LEASE_PROFILES")
        if raw:
            try:
                parsed = json.loads(raw)
                candidate = {}
                for name, pair in parsed.items():
                    ttl, max_total = int(pair[0]), int(pair[1])
                    if name not in DEFAULT_PROFILES or not 0 < ttl <= max_total:
                        raise ValueError(name)
                    candidate[name] = (ttl, max_total)
                profiles.update(candidate)
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                profiles = dict(DEFAULT_PROFILES)
        window = DEFAULT_CREATOR_WINDOW_SECONDS
        raw_window = env.get("BACH_TASK_LEASE_CREATOR_WINDOW")
        if raw_window:
            try:
                window = max(0, int(raw_window))
            except ValueError:
                window = DEFAULT_CREATOR_WINDOW_SECONDS
        return cls(profiles=profiles, creator_window_seconds=window)


class LeaseValidationError(ValueError):
    """Ungültige Eingabe (HTTP 422)."""


class TaskNotFound(LookupError):
    """Task-ID existiert nicht (HTTP 404)."""


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

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    """UTC, feste Länge, lexikografisch vergleichbar: 2026-10-05T00:10:00.000000Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _local_naive(dt: datetime) -> str:
    """Format von ``task_audit._iso_now`` (servereigene Ortszeit, naiv, mit µs)
    für die Kompatibilitätsspalte ``claimed_at``."""
    return dt.astimezone().replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%f")


def parse_ts(value: Any) -> datetime | None:
    """Parst gespeicherte Zeitstempel deterministisch nach Schreibweg:

    * mit ``Z``/Offset: wie angegeben;
    * naiv mit ``T`` (``datetime.now().isoformat()``, ``_iso_now``): Ortszeit des Leads;
    * naiv mit Leerzeichen (SQLite ``datetime('now')``, Lease-Adapter): UTC.
    """
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
    return dt.astimezone(timezone.utc)  # naiv -> lokale Zeit des Leads


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}


def ensure_task_lease_schema(conn: sqlite3.Connection) -> None:
    """Legt die additiven Lease-Spalten an (idempotent, eigene Transaktion)."""
    if conn.in_transaction:
        raise RuntimeError("Lease-Schema braucht eine Verbindung ohne offene Transaktion")
    conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_task_claim_columns(conn)
        ensure_task_slot_columns(conn)
        existing = _columns(conn)
        if not {"id", "status"} <= existing:
            raise RuntimeError("tasks-Tabelle mit id/status fehlt")
        for name, decl in LEASE_COLUMNS:
            if name not in existing:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {decl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_claim_expires_at ON tasks(claim_expires_at)")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _row(conn: sqlite3.Connection, task_id: int) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(zip([d[0] for d in cur.description], row))


def _validate_task_id(task_id: Any) -> int:
    if type(task_id) is not int or task_id <= 0:
        raise LeaseValidationError("task_id muss eine positive Ganzzahl sein")
    return task_id


def _validate_worker(worker_id: Any, host: Any) -> tuple[str, str]:
    if not isinstance(worker_id, str) or not _WORKER_RE.fullmatch(worker_id):
        raise LeaseValidationError("worker_id muss das Format <agent>@<host> haben")
    if not isinstance(host, str) or not _HOST_RE.fullmatch(host):
        raise LeaseValidationError("host ist ungültig")
    if worker_id.rsplit("@", 1)[1].lower() != host.lower():
        raise LeaseValidationError("host muss dem Hostteil von worker_id entsprechen")
    return worker_id, host


def _validate_lease_ref(lease_id: Any, fence: Any) -> tuple[str, int]:
    try:
        parsed = uuid.UUID(str(lease_id))
    except (ValueError, AttributeError, TypeError):
        raise LeaseValidationError("lease_id muss eine UUID sein") from None
    if parsed.version != 4 or str(parsed) != lease_id:
        raise LeaseValidationError("lease_id muss eine kanonische UUIDv4 sein")
    if type(fence) is not int or fence <= 0:
        raise LeaseValidationError("fence muss eine positive Ganzzahl sein")
    return lease_id, fence


def _salt_ref(source: Any) -> str | None:
    """Vertrag §7: Claim-Salt nur bei Ticket-Provenienz; reine Dedup-Referenz."""
    match = _TICKET_RE.search(str(source or ""))
    if not match:
        return None
    return hashlib.sha256(("claim-salt:v1:" + match.group(1)).encode("utf-8")).hexdigest()


def _is_creator(worker_id: str, created_by: Any) -> bool:
    creator = str(created_by or "").strip().lower()
    if not creator:
        return False
    return worker_id.lower() == creator or worker_id.rsplit("@", 1)[0].lower() == creator


def _lease_state(row: Mapping[str, Any], now: datetime, cfg: LeaseConfig) -> dict[str, Any]:
    """Klassifiziert den aktuellen Halter: none | lease | legacy, jeweils live/abgelaufen."""
    status = row.get("status")
    if row.get("claim_id"):
        expires = parse_ts(row.get("claim_expires_at"))
        live = status == "in_progress" and expires is not None and now < expires
        return {"kind": "lease", "live": live, "expires_at": expires}
    if status == "in_progress" and row.get("claimed_by"):
        claimed = parse_ts(row.get("claimed_at"))
        expires = claimed + timedelta(seconds=cfg.legacy_claim_seconds) if claimed else None
        # Unbekannter Zeitstempel darf nie Ablauf bedeuten (wie Reaper): fail-closed.
        live = expires is None or now < expires
        return {"kind": "legacy", "live": live, "expires_at": expires}
    return {"kind": "none", "live": False, "expires_at": None}


def _holder_view(row: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "worker_id": row.get("claimed_by"),
        "host": row.get("claim_host"),
        "intent": row.get("claim_intent"),
        "expires_at": _fmt(state["expires_at"]) if state.get("expires_at") else None,
    }


def task_content_version(row: Mapping[str, Any]) -> str:
    """Fingerprint des Auftrags; Status/Heartbeat ändern dessen Inhalt nicht."""
    volatile = {"claimed_by", "claimed_at", "status", "updated_at", "started_at", "completed_at", "task_version"}
    content = {key: value for key, value in row.items()
               if not key.startswith("claim_") and key not in volatile and value is not None}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_task_version(value: Any, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise LeaseValidationError("task_version muss ein SHA-256-Fingerprint sein")
    return value


def _ack(row: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "granted": True,
        "task_id": row["id"],
        "lease_id": row["claim_id"],
        "fence": int(row["claim_fence"]),
        "worker_id": row["claimed_by"],
        "host": row["claim_host"],
        "issued_at": row["claim_issued_at"],
        "expires_at": row["claim_expires_at"],
        "ttl_profile": row["claim_ttl_profile"],
        "server_now": _fmt(now),
        "task_version": row.get("claim_task_version"),
    }


def _deny(task_id: int, reason: str, now: datetime, **extra: Any) -> LeaseResult:
    payload = {"granted": False, "task_id": task_id, "reason": reason, **extra, "server_now": _fmt(now)}
    return LeaseResult(payload, http_status=409)


def _history(conn: sqlite3.Connection, task_id: int, action: str, changed_by: str,
             now: datetime, detail: Mapping[str, Any], old_value: Any = None) -> None:
    """Audit-Zeile ohne lease_id (Capability gehört nicht ins Protokoll)."""
    conn.execute(
        """INSERT INTO task_history
           (task_id, action, field_changed, old_value, new_value, changed_by, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (task_id, action, "lease", old_value, json.dumps(dict(detail), ensure_ascii=False, sort_keys=True),
         changed_by, _local_naive(now)),
    )


def _begin(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise RuntimeError("Lease-Operation braucht eine Verbindung ohne offene Transaktion")
    conn.execute("BEGIN IMMEDIATE")


def _choose_profile(requested: str | None, row: Mapping[str, Any], cfg: LeaseConfig) -> str:
    name = (requested or cfg.default_profile).upper()
    if name not in cfg.profiles:
        raise LeaseValidationError(f"ttl_profile muss einer von {sorted(cfg.profiles)} sein")
    if name == "XL":
        try:
            estimated = int(row.get("estimated_minutes") or 0)
        except (TypeError, ValueError):
            estimated = 0
        if estimated <= XL_MIN_ESTIMATED_MINUTES:
            name = "L"  # Vertrag §6: Lead stuft herab, ACK nennt das vergebene Profil
    return name


# ---------------------------------------------------------------------------
# Operationen
# ---------------------------------------------------------------------------

def acquire_lease(conn: sqlite3.Connection, task_id: int, *, worker_id: str, host: str,
                  request_id: str, ttl_profile: str | None = None, intent: str = "",
                  task_version: str | None = None,
                  device: str | None = None, config: LeaseConfig | None = None,
                  now: datetime | None = None) -> LeaseResult:
    """Vertrag §5.1. Gewährt höchstens einen lebenden Lease pro Task."""
    cfg = config or LeaseConfig.from_env()
    task_id = _validate_task_id(task_id)
    worker_id, host = _validate_worker(worker_id, host)
    task_version = _validate_task_version(task_version)
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise LeaseValidationError("request_id muss 16-128 Zeichen [A-Za-z0-9._:-] haben")
    intent = str(intent or "")[:500]
    ensure_task_lease_schema(conn)

    _begin(conn)
    try:
        # BEGIN IMMEDIATE may wait past expiry; sample live time only under the lock.
        now = now if now is not None else _utcnow()
        row = _row(conn, task_id)
        if row is None:
            raise TaskNotFound(task_id)
        version = task_content_version(row)
        if task_version is not None and task_version != version:
            conn.rollback()
            return _deny(task_id, "stale_task_version", now)
        state = _lease_state(row, now, cfg)

        if state["live"]:
            if (state["kind"] == "lease" and row.get("claimed_by") == worker_id
                    and row.get("claim_request_id") == request_id):
                conn.rollback()
                if row.get("claim_task_version") != version:
                    return _deny(task_id, "stale_task_version", now)
                return LeaseResult(_ack(row, now) | {"replayed": True})
            conn.rollback()
            reason = "already_held_by_caller" if row.get("claimed_by") == worker_id else "held"
            return _deny(task_id, reason, now, holder=_holder_view(row, state),
                         legacy=state["kind"] == "legacy")

        status = row.get("status")
        if status in TERMINAL_STATUSES or (status not in CLAIMABLE_STATUSES and status != "in_progress"):
            conn.rollback()
            return _deny(task_id, "not_claimable", now, status=status)

        deps = inspect_task_dependencies(conn, row.get("depends_on"))
        if deps["blocked"]:
            conn.rollback()
            return _deny(task_id, "not_claimable", now, status=status,
                         blocked_by={k: deps[k] for k in ("unfinished", "missing", "invalid")})

        created = parse_ts(row.get("created_at"))
        if created is not None and cfg.creator_window_seconds > 0 and created <= now + timedelta(seconds=60):
            until = created + timedelta(seconds=cfg.creator_window_seconds)
            if now < until and not _is_creator(worker_id, row.get("created_by")):
                conn.rollback()
                return _deny(task_id, "creator_priority", now, until=_fmt(until))

        profile = _choose_profile(ttl_profile, row, cfg)
        ttl, _max_total = cfg.profiles[profile]
        lease_id = str(uuid.uuid4())
        issued = _fmt(now)
        expires = _fmt(now + timedelta(seconds=ttl))
        old_fence = int(row.get("claim_fence") or 0)
        cursor = conn.execute(
            """UPDATE tasks
                  SET status = 'in_progress', claim_id = ?, claimed_by = ?, claim_host = ?,
                      claim_issued_at = ?, claim_expires_at = ?, claim_heartbeat_at = ?,
                      claim_fence = COALESCE(claim_fence, 0) + 1, claim_ttl_profile = ?,
                      claim_salt_ref = ?, claim_intent = ?, claim_request_id = ?, claim_task_version = ?,
                      claimed_at = ?, updated_at = ?,
                      started_at = COALESCE(started_at, ?)
                WHERE id = ? AND COALESCE(claim_fence, 0) = ? AND status = ?""",
            (lease_id, worker_id, host, issued, expires, issued, profile, _salt_ref(row.get("source")),
             intent or None, request_id, version, _local_naive(now), _local_naive(now), _local_naive(now),
             task_id, old_fence, status),
        )
        if cursor.rowcount != 1:  # unter BEGIN IMMEDIATE nicht erwartbar; fail-closed
            conn.rollback()
            return _deny(task_id, "conflict", now)
        _history(conn, task_id, "lease_acquire", worker_id, now, {
            "fence": old_fence + 1, "host": host, "ttl_profile": profile, "expires_at": expires,
            "requested_profile": (ttl_profile or cfg.default_profile).upper(),
            "took_over": state["kind"], "device": device,
        }, old_value=status)
        ack = _ack(_row(conn, task_id) or {}, now)
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return LeaseResult(ack)


def read_lease(conn: sqlite3.Connection, task_id: int, *, lease_id: str | None = None,
               config: LeaseConfig | None = None, now: datetime | None = None) -> LeaseResult:
    """Vertrag §5.2. Holder-Ansicht ohne lease_id; ``own`` nur bei passender lease_id."""
    cfg = config or LeaseConfig.from_env()
    task_id = _validate_task_id(task_id)
    ensure_task_lease_schema(conn)
    now = now or _utcnow()
    row = _row(conn, task_id)
    if row is None:
        raise TaskNotFound(task_id)
    state = _lease_state(row, now, cfg)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": row.get("status"),
        "leased": bool(state["live"]),
        "fence": int(row.get("claim_fence") or 0),
        "legacy": state["kind"] == "legacy",
        "server_now": _fmt(now),
        "task_version": task_content_version(row),
    }
    if state["live"]:
        payload.update({
            "holder": _holder_view(row, state),
            "issued_at": row.get("claim_issued_at") if state["kind"] == "lease" else None,
            "expires_at": _fmt(state["expires_at"]) if state["expires_at"] else None,
            "ttl_profile": row.get("claim_ttl_profile"),
        })
        if lease_id and state["kind"] == "lease" and lease_id == row.get("claim_id"):
            payload["own"] = True
    return LeaseResult(payload)


def _load_for_holder(conn, task_id, lease_id, fence, now, cfg, task_version=None):
    """Gemeinsame Prüfung für renew/release unter Schreibsperre."""
    row = _row(conn, task_id)
    if row is None:
        raise TaskNotFound(task_id)
    if row.get("claim_id") != lease_id or int(row.get("claim_fence") or 0) != fence:
        return row, "stale_fence"
    state = _lease_state(row, now, cfg)
    if not state["live"]:
        return row, "expired"
    version = row.get("claim_task_version")
    if not version or version != task_content_version(row) or (task_version is not None and task_version != version):
        return row, "stale_task_version"
    return row, None


def renew_lease(conn: sqlite3.Connection, task_id: int, *, lease_id: str, fence: int,
                task_version: str | None = None,
                config: LeaseConfig | None = None, now: datetime | None = None) -> LeaseResult:
    """Vertrag §5.3. Verlängert nie verkürzend, nur lebend, gedeckelt auf profile_max_total."""
    cfg = config or LeaseConfig.from_env()
    task_id = _validate_task_id(task_id)
    lease_id, fence = _validate_lease_ref(lease_id, fence)
    task_version = _validate_task_version(task_version)
    ensure_task_lease_schema(conn)
    _begin(conn)
    try:
        # BEGIN IMMEDIATE may wait past expiry; sample live time only under the lock.
        now = now if now is not None else _utcnow()
        row, problem = _load_for_holder(conn, task_id, lease_id, fence, now, cfg, task_version)
        if problem:
            conn.rollback()
            return _deny(task_id, problem, now)
        profile = row.get("claim_ttl_profile") or cfg.default_profile
        ttl, max_total = cfg.profiles.get(profile, cfg.profiles[cfg.default_profile])
        issued = parse_ts(row.get("claim_issued_at")) or now
        current = parse_ts(row.get("claim_expires_at"))
        cap = issued + timedelta(seconds=max_total)
        if current >= cap:
            conn.rollback()
            return _deny(task_id, "max_total_reached", now, expires_at=row.get("claim_expires_at"))
        new_expires = _fmt(min(max(current, now + timedelta(seconds=ttl)), cap))
        cursor = conn.execute(
            """UPDATE tasks SET claim_expires_at = ?, claim_heartbeat_at = ?, claimed_at = ?, updated_at = ?
                WHERE id = ? AND claim_id = ? AND claim_fence = ? AND status = 'in_progress'""",
            (new_expires, _fmt(now), _local_naive(now), _local_naive(now), task_id, lease_id, fence),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return _deny(task_id, "stale_fence", now)
        _history(conn, task_id, "lease_renew", row.get("claimed_by") or "unknown", now,
                 {"fence": fence, "expires_at": new_expires})
        ack = _ack(_row(conn, task_id) or {}, now)
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return LeaseResult(ack)


def release_lease(conn: sqlite3.Connection, task_id: int, *, lease_id: str, fence: int,
                  task_version: str | None = None,
                  outcome: str, result_ref: str = "", note: str = "",
                  config: LeaseConfig | None = None, now: datetime | None = None) -> LeaseResult:
    """Vertrag §5.4 + §8.4. Einziger Weg für den Abschluss einer geleasten Task.

    Bei veraltetem Fence oder abgelaufenem Lease wird nichts am Status geändert;
    ein mitgeliefertes Ergebnis wird nur als ``late_result`` protokolliert.
    """
    cfg = config or LeaseConfig.from_env()
    task_id = _validate_task_id(task_id)
    lease_id, fence = _validate_lease_ref(lease_id, fence)
    task_version = _validate_task_version(task_version)
    if outcome not in RELEASE_OUTCOMES:
        raise LeaseValidationError(f"outcome muss einer von {sorted(RELEASE_OUTCOMES)} sein")
    result_ref = str(result_ref or "")[:500]
    note = str(note or "")[:4000]
    ensure_task_lease_schema(conn)

    try:
        from hub.task_audit import GateReopenBlocked, apply_task_field_changes
    except ImportError:  # pragma: no cover
        from ..task_audit import (  # type: ignore
            GateReopenBlocked,
            apply_task_field_changes,
        )

    _begin(conn)
    try:
        # BEGIN IMMEDIATE may wait past expiry; sample live time only under the lock.
        now = now if now is not None else _utcnow()
        row, problem = _load_for_holder(conn, task_id, lease_id, fence, now, cfg, task_version)
        if problem:
            recorded = False
            if result_ref or note:
                _history(conn, task_id, "late_result", "lease-holder", now,
                         {"fence": fence, "outcome": outcome, "result_ref": result_ref,
                          "note": note, "reason": problem})
                conn.commit()
                recorded = True
            else:
                conn.rollback()
            return _deny(task_id, problem, now, late_result_recorded=recorded)

        worker = row.get("claimed_by") or "lease-holder"
        new_status = RELEASE_OUTCOMES[outcome]
        try:
            apply_task_field_changes(conn, task_id, row, {"status": new_status},
                                     changed_by=worker, allow_reopen=True,
                                     lease_authorized=True)
        except (ValueError, GateReopenBlocked) as exc:  # z. B. Abschluss-Guard "Codeänderungen ohne PR"
            conn.rollback()
            return _deny(task_id, "completion_guard", now, detail=str(exc))
        assignments = ", ".join(f"{name} = NULL" for name in _CLEARED_ON_RELEASE)
        cursor = conn.execute(
            f"UPDATE tasks SET {assignments} WHERE id = ? AND claim_id = ? AND claim_fence = ?",
            (task_id, lease_id, fence),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return _deny(task_id, "stale_fence", now)
        _history(conn, task_id, "lease_release", worker, now,
                 {"fence": fence, "outcome": outcome, "result_ref": result_ref, "note": note},
                 old_value="in_progress")
        after = _row(conn, task_id) or {}
        ack = {
            "released": True, "task_id": task_id, "outcome": outcome, "status": after.get("status"),
            "fence": int(after.get("claim_fence") or 0), "server_now": _fmt(now),
        }
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return LeaseResult(ack)


def decompose_lease(conn: sqlite3.Connection, task_id: int, *, lease_id: str, fence: int,
                    task_version: str, subtasks: list[dict[str, Any]], close_parent: bool = True,
                    sequential: bool = False, config: LeaseConfig | None = None,
                    now: datetime | None = None) -> LeaseResult:
    """Lease, Taskversion, Teilaufgaben und Elternabschluss bilden eine Transaktion."""
    from hub.task_audit import apply_task_field_changes

    cfg = config or LeaseConfig.from_env()
    task_id = _validate_task_id(task_id)
    lease_id, fence = _validate_lease_ref(lease_id, fence)
    task_version = _validate_task_version(task_version, required=True)
    if type(close_parent) is not bool or type(sequential) is not bool:
        raise LeaseValidationError("close_parent und sequential müssen boolesch sein")
    if not isinstance(subtasks, list) or not 1 <= len(subtasks) <= 100:
        raise LeaseValidationError("subtasks braucht 1 bis 100 Teilaufgaben")
    allowed = {"title", "description", "priority", "depends_on", "assigned_to", "category",
               "required_model", "assigned_slot"}
    normalized = []
    for item in subtasks:
        if not isinstance(item, dict) or set(item) - allowed:
            raise LeaseValidationError("Unbekannte Teilaufgabenfelder")
        if not isinstance(item.get("title"), str) or not item["title"].strip():
            raise LeaseValidationError("Jede Teilaufgabe braucht einen Titel")
        if any(not isinstance(value, str) for value in item.values()):
            raise LeaseValidationError("Teilaufgabenfelder müssen Text sein")
        normalized.append({**item, "title": item["title"].strip()})

    ensure_task_lease_schema(conn)
    _begin(conn)
    try:
        # BEGIN IMMEDIATE may wait past expiry; sample live time only under the lock.
        now = now if now is not None else _utcnow()
        parent, problem = _load_for_holder(conn, task_id, lease_id, fence, now, cfg, task_version)
        if problem:
            conn.rollback()
            return _deny(task_id, problem, now)
        created = []
        for item in normalized:
            dependency = item.get("depends_on") or (str(created[-1]) if sequential and created else "")
            dependencies = inspect_task_dependencies(conn, dependency)
            if dependencies["missing"] or dependencies["invalid"]:
                raise LeaseValidationError("Teilaufgabe hat ungültige oder fehlende Abhängigkeiten")
            cursor = conn.execute(
                """INSERT INTO tasks (title, description, priority, category, assigned_to,
                                      depends_on, created_by, required_model, assigned_slot,
                                      status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (item["title"], item.get("description", ""), item.get("priority") or parent.get("priority") or "P3",
                 item.get("category") or parent.get("category") or "",
                 item.get("assigned_to") or parent.get("assigned_to") or "bach", dependency,
                 parent.get("claimed_by") or "lease-holder",
                 item.get("required_model", parent.get("required_model")),
                 item.get("assigned_slot", parent.get("assigned_slot")),
                 _local_naive(now), _local_naive(now)),
            )
            created.append(cursor.lastrowid)
        changes = {"description": (parent.get("description") or "") +
                   f"\n[In {len(created)} Teilaufgaben zerlegt: {created}]"}
        if close_parent:
            changes["status"] = "done"
        try:
            apply_task_field_changes(conn, task_id, parent, changes,
                                     changed_by=parent.get("claimed_by") or "lease-holder",
                                     now=_local_naive(now), lease_authorized=True)
        except ValueError as exc:
            conn.rollback()
            return _deny(task_id, "completion_guard", now, detail=str(exc))
        after = _row(conn, task_id)
        version = task_content_version(after)
        if close_parent:
            assignments = ", ".join(f"{name} = NULL" for name in _CLEARED_ON_RELEASE)
            cursor = conn.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ? AND claim_id = ? AND claim_fence = ? AND claim_task_version = ?",
                (task_id, lease_id, fence, task_version),
            )
        else:
            cursor = conn.execute(
                "UPDATE tasks SET claim_task_version = ? WHERE id = ? AND claim_id = ? AND claim_fence = ? AND claim_task_version = ?",
                (version, task_id, lease_id, fence, task_version),
            )
        if cursor.rowcount != 1:
            conn.rollback()
            return _deny(task_id, "stale_fence", now)
        _history(conn, task_id, "lease_decompose", parent.get("claimed_by") or "lease-holder", now,
                 {"fence": fence, "created_ids": created, "parent_closed": close_parent,
                  "previous_task_version": task_version, "task_version": version})
        payload = {"decomposed": True, "task_id": task_id, "created_ids": created,
                   "created_count": len(created), "parent_closed": close_parent,
                   "fence": fence, "task_version": version, "server_now": _fmt(now)}
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return LeaseResult(payload)


# ---------------------------------------------------------------------------
# Schutz der Altpfade (Vertrag §5.4 letzter Absatz, §11.3)
# ---------------------------------------------------------------------------
# Liegt zentral in hub.task_audit, damit GUI-PUT, Headless-API, CLI und Chat
# denselben Choke-Point nutzen:
#   * apply_task_field_changes -> LeaseRequired bei Statuswechsel auf lebendem Lease
#   * claim_task_atomic / release_claim -> übernehmen/geben keinen lebenden Lease frei
#     und entwerten verwaiste Lease-Spalten
#   * reap_stale_in_progress_tasks -> entscheidet bei geleasten Tasks nach claim_expires_at
