# SPDX-License-Identifier: MIT
"""Polaris (Polarstern): Ressourcen-Lease fuer Einzelschreiber-Ressourcen (BACH #2121, P1).

Fuer jede Ressource mit nur einem Schreiber schreibt nur, wer den Polaris star
haelt: ein Lease wie die Task-Leases, mit Fence. Dieses Modul ist die
Lead-seitige Authority (BACH auf dem Mac); es nutzt nur ``lease_core``.

Grundsaetze (strukturgleich zu ``task_lease.py``):

* **Eine Authority.** Zustand liegt in ``resource_leases`` der Lead-DB. Ohne
  erreichbare Authority gibt es keine Uebernahme (fail-closed, Festlegung 2).
* **Serverzeit.** Der Lead misst die Zeit erst unter der Schreibsperre
  (``BEGIN IMMEDIATE``); jede Antwort traegt ``server_now``.
* **Fencing.** ``fence`` steigt bei jedem Acquire um 1 und sinkt nie (die Zeile
  bleibt nach Release als Hochwassermarke bestehen); der UPDATE prueft den
  Fence im WHERE (CAS).
* **Kein Preempt.** Der Server (``server_role``) verdraengt einen Standby nie.
  Er markiert nur seinen Wunsch; ein Standby-Renew wird dann mit
  ``server_priority`` abgelehnt, der Standby beendet seine Transaktion und
  gibt frei. Der Standby uebernimmt nur, wenn die Server-Lease abgelaufen UND
  der Server laenger als ``server_down_after`` still ist.
* **Sync-Schranke.** ``resource_version`` ist der Manifest-Hash nach dem
  letzten abgeschlossenen Schreiben (``lease_core.manifest_version``). Der
  Halter meldet ihn bei Renew/Release; ein neuer Halter erwirbt nur mit
  passendem lokalem Hash, sonst ``stale_resource_version``.

Ehrliche Garantie (Festlegung 1): Das schliesst aus, dass zwei Writer
*gleichzeitig gueltig* schreiben duerfen. Ein angehaltener Alt-Halter, der nach
einer Uebernahme noch schreibt, ist ohne Compare-and-Set im Dateisystem nicht
zu verhindern; er wird erkannt (Fence-Stempel, ``stale_holder``-Ereignis) und
der Schaden begrenzt.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from typing import Any

try:
    from hub._services import lease_core as core
except ImportError:  # pragma: no cover - Paketimport aus system/hub
    from . import lease_core as core

LeaseValidationError = core.LeaseValidationError
LeaseResult = core.LeaseResult

POLARIS = "POLARIS"
#: Profil -> (TTL je Acquire/Renew, Hoechstlaufzeit ab issued_at), Sekunden.
DEFAULT_PROFILES: dict[str, tuple[int, int]] = {POLARIS: (120, 24 * 3600)}
DEFAULT_RENEW_SECONDS = 40
DEFAULT_MARGIN_SECONDS = 15
DEFAULT_SERVER_DOWN_AFTER_SECONDS = 120

_DEVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
_PATTERN_RE = re.compile(r"^[A-Za-z0-9*?._:+@-]{1,130}$")

_DDL = (
    """CREATE TABLE IF NOT EXISTS resource_registry (
        resource TEXT PRIMARY KEY,
        allowed_workers TEXT NOT NULL,
        server_role TEXT NOT NULL,
        standby_roles TEXT NOT NULL DEFAULT '[]',
        default_profile TEXT NOT NULL DEFAULT 'POLARIS',
        device_bindings TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS resource_leases (
        resource TEXT PRIMARY KEY,
        claim_id TEXT,
        claim_worker TEXT,
        claim_host TEXT,
        claim_role TEXT,
        claim_intent TEXT,
        claim_device TEXT,
        claim_issued_at TEXT,
        claim_expires_at TEXT,
        claim_heartbeat_at TEXT,
        fence INTEGER NOT NULL DEFAULT 0,
        ttl_profile TEXT,
        request_id TEXT,
        resource_version TEXT,
        server_last_at TEXT,
        server_wanted_at TEXT,
        version_inflight INTEGER NOT NULL DEFAULT 0,
        last_rebaseline_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS resource_lease_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resource TEXT NOT NULL,
        at TEXT NOT NULL,
        action TEXT NOT NULL,
        worker_id TEXT,
        fence INTEGER,
        detail TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_resource_lease_events_resource ON resource_lease_events(resource, id)",
)


class ResourceNotFound(LookupError):
    """Ressource ist nicht registriert (HTTP 404)."""


@dataclass(frozen=True)
class ResourceLeaseConfig:
    profiles: Mapping[str, tuple[int, int]] = field(default_factory=lambda: dict(DEFAULT_PROFILES))
    default_profile: str = POLARIS
    renew_seconds: int = DEFAULT_RENEW_SECONDS
    margin_seconds: int = DEFAULT_MARGIN_SECONDS
    server_down_after_seconds: int = DEFAULT_SERVER_DOWN_AFTER_SECONDS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ResourceLeaseConfig:
        """``BACH_POLARIS_PROFILES`` (JSON ``{"POLARIS": [120, 86400]}``),
        ``..._RENEW``, ``..._MARGIN``, ``..._SERVER_DOWN_AFTER`` (Sekunden)."""
        env = os.environ if environ is None else environ
        return cls(
            profiles=core.load_profiles(DEFAULT_PROFILES, "BACH_POLARIS_PROFILES", env),
            renew_seconds=core.env_seconds(env, "BACH_POLARIS_RENEW", DEFAULT_RENEW_SECONDS),
            margin_seconds=core.env_seconds(env, "BACH_POLARIS_MARGIN", DEFAULT_MARGIN_SECONDS, minimum=0),
            server_down_after_seconds=core.env_seconds(
                env, "BACH_POLARIS_SERVER_DOWN_AFTER", DEFAULT_SERVER_DOWN_AFTER_SECONDS),
        )


# ---------------------------------------------------------------------------
# Schema und Registrierung
# ---------------------------------------------------------------------------

def _expected_columns() -> dict[str, dict[str, str]]:
    """Spalten je Tabelle samt ALTER-tauglicher Deklaration, aus dem DDL abgeleitet."""
    mem = sqlite3.connect(":memory:")
    try:
        for stmt in _DDL:
            mem.execute(stmt)
        out: dict[str, dict[str, str]] = {}
        for table in ("resource_registry", "resource_leases", "resource_lease_events"):
            cols = {}
            for _cid, name, ctype, notnull, dflt, pk in mem.execute(f"PRAGMA table_info({table})"):
                if pk:
                    continue
                decl = ctype or "TEXT"
                if notnull:
                    decl += " NOT NULL DEFAULT " + (dflt if dflt is not None else "''")
                elif dflt is not None:
                    decl += f" DEFAULT {dflt}"
                cols[name] = decl
            out[table] = cols
        return out
    finally:
        mem.close()


_EXPECTED_COLUMNS = _expected_columns()


def ensure_resource_lease_schema(conn: sqlite3.Connection) -> None:
    """Legt Tabellen an und ergaenzt fehlende Spalten additiv (idempotent). Laeuft
    innerhalb einer offenen Transaktion (Migration) ohne eigenes Commit, sonst in eigener."""
    def present() -> dict[str, set[str]]:
        rows = conn.execute(
            "SELECT m.name, p.name FROM sqlite_master m, pragma_table_info(m.name) p "
            "WHERE m.type = 'table' AND m.name LIKE 'resource%'").fetchall()
        have: dict[str, set[str]] = {}
        for table, col in rows:
            have.setdefault(table, set()).add(col)
        return have

    def complete(have) -> bool:
        return all(t in have and set(cols) <= have[t] for t, cols in _EXPECTED_COLUMNS.items())

    def apply() -> None:
        for stmt in _DDL:
            conn.execute(stmt)
        have = present()
        for table, cols in _EXPECTED_COLUMNS.items():
            for name, decl in cols.items():
                if name not in have.get(table, set()):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    if complete(present()):
        return
    if conn.in_transaction:
        apply()
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply()
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


_validate_resource = core.validate_resource_name


def _validate_exact_workers(value: Any) -> list[str]:
    """device_bindings: nur exakte Worker-IDs ``agent@host`` (keine Wildcards)."""
    items = [value] if isinstance(value, str) else list(value or [])
    if not items or any(not isinstance(w, str) or not core.WORKER_RE.fullmatch(w) for w in items):
        raise LeaseValidationError("device_bindings braucht exakte Worker-IDs der Form agent@host (keine Wildcards)")
    return items


def _validate_patterns(value: Any, what: str, *, allow_empty: bool = False) -> list[str]:
    if isinstance(value, str):
        value = [value]
    items = list(value or [])
    if (not items and not allow_empty) or any(
            not isinstance(p, str) or not _PATTERN_RE.fullmatch(p) for p in items):
        raise LeaseValidationError(f"{what} braucht Muster der Form <agent>@<host> (Wildcards * ?)")
    return items


def register_resource(conn: sqlite3.Connection, resource: str, *, allowed_workers, server_role: str,
                      standby_roles=(), default_profile: str = POLARIS, device_bindings=None,
                      config: ResourceLeaseConfig | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Registriert oder aktualisiert eine Ressource (nur lokal an der Authority,
    keine HTTP-Route). ``allowed_workers`` ist die Zulassung (fnmatch auf
    ``agent@host``, case-insensitiv); ``server_role`` und ``standby_roles``
    bestimmen die Rolle innerhalb der zugelassenen Worker."""
    cfg = config or ResourceLeaseConfig.from_env()
    resource = _validate_resource(resource)
    allowed = _validate_patterns(allowed_workers, "allowed_workers")
    (server,) = _validate_patterns(server_role, "server_role")
    standby = _validate_patterns(standby_roles, "standby_roles", allow_empty=True)
    if default_profile not in cfg.profiles:
        raise LeaseValidationError(f"default_profile muss einer von {sorted(cfg.profiles)} sein")
    bindings = {}
    for device, patterns in dict(device_bindings or {}).items():
        if not isinstance(device, str) or not _DEVICE_RE.fullmatch(device):
            raise LeaseValidationError("device_bindings: Geraetename ungueltig")
        bindings[device] = _validate_exact_workers(patterns)
    ensure_resource_lease_schema(conn)
    stamp = core.fmt(now or core.utcnow())
    _begin(conn)
    try:
        conn.execute(
            """INSERT INTO resource_registry
                   (resource, allowed_workers, server_role, standby_roles, default_profile, device_bindings,
                    updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(resource) DO UPDATE SET allowed_workers=excluded.allowed_workers,
                   server_role=excluded.server_role, standby_roles=excluded.standby_roles,
                   default_profile=excluded.default_profile, device_bindings=excluded.device_bindings,
                   updated_at=excluded.updated_at""",
            (resource, json.dumps(allowed), server, json.dumps(standby), default_profile,
             json.dumps(bindings, sort_keys=True), stamp))
        conn.execute("INSERT OR IGNORE INTO resource_leases (resource) VALUES (?)", (resource,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"resource": resource, "allowed_workers": allowed, "server_role": server,
            "standby_roles": standby, "default_profile": default_profile, "device_bindings": bindings}


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _fetch(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([d[0] for d in cur.description], tuple(row)))


def _begin(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise RuntimeError("Lease-Operation braucht eine Verbindung ohne offene Transaktion")
    conn.execute("BEGIN IMMEDIATE")


def _registry(conn: sqlite3.Connection, resource: str) -> dict[str, Any]:
    reg = _fetch(conn, "SELECT * FROM resource_registry WHERE resource = ?", (resource,))
    if reg is None:
        raise ResourceNotFound(resource)
    for key in ("allowed_workers", "standby_roles", "device_bindings"):
        reg[key] = json.loads(reg[key])
    return reg


def _lease_row(conn: sqlite3.Connection, resource: str) -> dict[str, Any]:
    conn.execute("INSERT OR IGNORE INTO resource_leases (resource) VALUES (?)", (resource,))
    return _fetch(conn, "SELECT * FROM resource_leases WHERE resource = ?", (resource,))


def _match(worker_id: str, patterns) -> bool:
    worker = worker_id.lower()
    return any(fnmatchcase(worker, p.lower()) for p in patterns)


def _role(reg: Mapping[str, Any], worker_id: str) -> str | None:
    if not _match(worker_id, reg["allowed_workers"]):
        return None
    if _match(worker_id, [reg["server_role"]]):
        return "server"
    if _match(worker_id, reg["standby_roles"]):
        return "standby"
    return None


def _device_bound(reg: Mapping[str, Any], device: str | None, worker_id: str) -> bool:
    """HTTP-Weg: das authentifizierte Geraet darf nur als die ihm zugeordneten
    Worker handeln. Keine Zuordnung oder kein Geraet = fail-closed."""
    return bool(device) and worker_id in reg["device_bindings"].get(device, [])  # exakt, case-sensitiv


def _live(row: Mapping[str, Any], now: datetime) -> bool:
    expires = core.parse_ts(row.get("claim_expires_at"))
    return bool(row.get("claim_id")) and expires is not None and now < expires


def _holder_view(row: Mapping[str, Any]) -> dict[str, Any]:
    return {"worker_id": row.get("claim_worker"), "host": row.get("claim_host"),
            "role": row.get("claim_role"), "intent": row.get("claim_intent"),
            "expires_at": row.get("claim_expires_at")}


def _event(conn, resource, action, worker_id, fence, now, **detail) -> None:
    conn.execute(
        "INSERT INTO resource_lease_events (resource, at, action, worker_id, fence, detail) VALUES (?,?,?,?,?,?)",
        (resource, core.fmt(now), action, worker_id, fence, json.dumps(detail, sort_keys=True)))


def _ack(resource: str, row: Mapping[str, Any], now: datetime, cfg: ResourceLeaseConfig) -> dict[str, Any]:
    return {
        "granted": True, "resource": resource, "lease_id": row["claim_id"], "fence": int(row["fence"]),
        "worker_id": row["claim_worker"], "host": row["claim_host"], "role": row["claim_role"],
        "issued_at": row["claim_issued_at"], "expires_at": row["claim_expires_at"],
        "ttl_profile": row["ttl_profile"], "resource_version": row["resource_version"],
        "renew_after_seconds": cfg.renew_seconds, "margin_seconds": cfg.margin_seconds,
        "server_now": core.fmt(now),
    }


def _server_recent(row: Mapping[str, Any], now: datetime, cfg: ResourceLeaseConfig) -> bool:
    seen = core.parse_ts(row.get("server_last_at"))
    return seen is not None and now < seen + timedelta(seconds=cfg.server_down_after_seconds)


def _finish(conn, result: LeaseResult, *, keep: bool = False) -> LeaseResult:
    """Beendet die Transaktion einer Ablehnung. ``keep`` schreibt Beobachtungen
    (Server-Lebenszeichen, Wunsch, stale_holder-Ereignis) trotzdem fest."""
    conn.commit() if keep else conn.rollback()
    return result


# ---------------------------------------------------------------------------
# Operationen
# ---------------------------------------------------------------------------

def acquire_resource_lease(conn: sqlite3.Connection, resource: str, *, worker_id: str, host: str,
                           request_id: str, ttl_profile: str | None = None, intent: str = "",
                           resource_version: str | None = None, device: str | None = None,
                           enforce_device: bool = False, rebaseline: bool = False,
                           config: ResourceLeaseConfig | None = None,
                           now: datetime | None = None) -> LeaseResult:
    """Polaris star anfordern. ``rebaseline`` (nur Server-Rolle): bei abweichendem Manifest ohne
    offenen In-flight-Marker den gemeldeten Stand als neue Version uebernehmen (externe Aenderung,
    Ereignis ``rebaseline_external_change``). Ein offener In-flight-Marker blockiert auch den Server. ``enforce_device`` (HTTP-Weg) bindet den Worker an das
    authentifizierte Geraet; die Rolle ergibt sich aus Registrierung UND Geraet. Hoechstens ein lebender Halter je Ressource."""
    cfg = config or ResourceLeaseConfig.from_env()
    resource = _validate_resource(resource)
    worker_id, host = core.validate_worker(worker_id, host)
    request_id = core.validate_request_id(request_id)
    resource_version = core.validate_version(resource_version)
    intent = str(intent or "")[:500]
    ensure_resource_lease_schema(conn)

    _begin(conn)
    try:
        now = now if now is not None else core.utcnow()  # erst unter der Sperre messen
        reg = _registry(conn, resource)
        role = _role(reg, worker_id)
        if enforce_device and not _device_bound(reg, device, worker_id):
            _event(conn, resource, "device_not_bound", worker_id, None, now, device=device)
            return _finish(conn, core.deny("device_not_bound", now, resource=resource), keep=True)
        if role is None:
            return _finish(conn, core.deny("worker_not_allowed", now, resource=resource))
        row = _lease_row(conn, resource)
        live = _live(row, now)
        is_server = role == "server"
        if is_server:  # Lebenszeichen des Servers, auch bei Ablehnung
            conn.execute("UPDATE resource_leases SET server_last_at = ? WHERE resource = ?",
                         (core.fmt(now), resource))

        if live:
            if row["claim_worker"] == worker_id and row["request_id"] == request_id:
                return _finish(conn, LeaseResult(_ack(resource, row, now, cfg) | {"replayed": True}),
                               keep=is_server)
            reason = "already_held_by_caller" if row["claim_worker"] == worker_id else "held"
            extra: dict[str, Any] = {}
            if is_server and row["claim_role"] == "standby":
                conn.execute("UPDATE resource_leases SET server_wanted_at = ? WHERE resource = ?",
                             (core.fmt(now), resource))
                _event(conn, resource, "server_priority_requested", worker_id, row["fence"], now,
                       standby=row["claim_worker"])
                extra["server_priority"] = True
            return _finish(conn, core.deny(reason, now, resource=resource, holder=_holder_view(row), **extra),
                           keep=is_server)

        if role == "standby":
            if row["server_last_at"] is None:
                return _finish(conn, core.deny("server_unknown", now, resource=resource))
            if _server_recent(row, now, cfg):
                return _finish(conn, core.deny("server_active", now, resource=resource))

        stored = row["resource_version"]
        rebased = False
        if stored is not None and resource_version is None:
            return _finish(conn, core.deny("resource_version_required", now, resource=resource,
                                           expected_resource_version=stored), keep=is_server)
        if stored is not None and resource_version != stored:
            if not (rebaseline and is_server):
                return _finish(conn, core.deny("stale_resource_version", now, resource=resource,
                                               expected_resource_version=stored), keep=is_server)
            if row["version_inflight"]:  # offene Transaktion: erst Recovery, auch fuer den Server
                return _finish(conn, core.deny("inflight_open", now, resource=resource,
                                               expected_resource_version=stored), keep=True)
            rebased = True

        profile = (ttl_profile or reg["default_profile"] or cfg.default_profile).upper()
        if profile not in cfg.profiles:
            raise LeaseValidationError(f"ttl_profile muss einer von {sorted(cfg.profiles)} sein")
        ttl, _max_total = cfg.profiles[profile]
        lease_id = str(uuid.uuid4())
        issued = core.fmt(now)
        expires = core.fmt(now + timedelta(seconds=ttl))
        old_fence = int(row["fence"])
        cursor = conn.execute(
            """UPDATE resource_leases
                  SET claim_id = ?, claim_worker = ?, claim_host = ?, claim_role = ?, claim_intent = ?,
                      claim_device = ?, claim_issued_at = ?, claim_expires_at = ?, claim_heartbeat_at = ?,
                      fence = fence + 1, ttl_profile = ?, request_id = ?,
                      server_wanted_at = CASE WHEN ? = 'server' THEN NULL ELSE server_wanted_at END
                WHERE resource = ? AND fence = ?""",
            (lease_id, worker_id, host, role, intent or None, device, issued, expires, issued, profile, request_id,
             role, resource, old_fence))
        if cursor.rowcount != 1:  # unter BEGIN IMMEDIATE nicht erwartbar; fail-closed
            return _finish(conn, core.deny("conflict", now, resource=resource))
        if rebased:
            conn.execute("UPDATE resource_leases SET resource_version = ?, version_inflight = 0, "
                         "last_rebaseline_at = ? WHERE resource = ?", (resource_version, core.fmt(now), resource))
            _event(conn, resource, "rebaseline_external_change", worker_id, old_fence + 1, now,
                   previous_version=stored, new_version=resource_version, device=device)
        _event(conn, resource, "acquire", worker_id, old_fence + 1, now, role=role, host=host,
               device=device, previous=row["claim_worker"] if row["claim_id"] else None,
               previous_fence=old_fence if row["claim_id"] else None)
        ack = _ack(resource, _lease_row(conn, resource), now, cfg)
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return LeaseResult(ack)


def _check_holder(conn, resource, row, lease_id, fence, worker_hint, now, *, device=None,
                  enforce_device=False):
    """Stale-Pruefung fuer renew/release; protokolliert Alt-Halter (committet).
    Auf dem HTTP-Weg muss zusaetzlich dasselbe Geraet handeln, das erworben hat."""
    if row["claim_id"] != lease_id or int(row["fence"]) != fence:
        _event(conn, resource, "stale_holder", worker_hint, fence, now,
               current_fence=int(row["fence"]), current_holder=row["claim_worker"])
        return _finish(conn, core.deny("stale_fence", now, resource=resource, fence=int(row["fence"])),
                       keep=True)
    if enforce_device and (not device or row["claim_device"] != device):
        _event(conn, resource, "device_not_bound", row["claim_worker"], fence, now, device=device)
        return _finish(conn, core.deny("device_not_bound", now, resource=resource), keep=True)
    return None


def renew_resource_lease(conn: sqlite3.Connection, resource: str, *, lease_id: str, fence: int,
                         resource_version: str | None = None, device: str | None = None,
                         enforce_device: bool = False, inflight: bool = False,
                         config: ResourceLeaseConfig | None = None,
                         now: datetime | None = None) -> LeaseResult:
    """Heartbeat: verlaengert nie verkuerzend, nur lebend, gedeckelt auf die
    Hoechstlaufzeit. ``resource_version`` meldet den Commit-Marker."""
    cfg = config or ResourceLeaseConfig.from_env()
    resource = _validate_resource(resource)
    lease_id, fence = core.validate_lease_ref(lease_id, fence)
    resource_version = core.validate_version(resource_version)
    ensure_resource_lease_schema(conn)

    _begin(conn)
    try:
        now = now if now is not None else core.utcnow()
        _registry(conn, resource)
        row = _lease_row(conn, resource)
        denied = _check_holder(conn, resource, row, lease_id, fence, row["claim_worker"], now,
                               device=device, enforce_device=enforce_device)
        if denied:
            return denied
        if not _live(row, now):
            return _finish(conn, core.deny("expired", now, resource=resource))
        is_server = row["claim_role"] == "server"
        wanted = core.parse_ts(row["server_wanted_at"])
        if (row["claim_role"] == "standby" and wanted is not None
                and now < wanted + timedelta(seconds=cfg.server_down_after_seconds)):
            return _finish(conn, core.deny("server_priority", now, resource=resource, release_requested=True))
        profile = row["ttl_profile"] or cfg.default_profile
        ttl, max_total = cfg.profiles.get(profile, cfg.profiles[cfg.default_profile])
        issued = core.parse_ts(row["claim_issued_at"]) or now
        current = core.parse_ts(row["claim_expires_at"])
        cap = issued + timedelta(seconds=max_total)
        if current >= cap:
            return _finish(conn, core.deny("max_total_reached", now, resource=resource,
                                           expires_at=row["claim_expires_at"]))
        new_expires = core.fmt(min(max(current, now + timedelta(seconds=ttl)), cap))
        cursor = conn.execute(
            """UPDATE resource_leases
                  SET claim_expires_at = ?, claim_heartbeat_at = ?,
                      resource_version = COALESCE(?, resource_version),
                      version_inflight = CASE WHEN ? IS NULL THEN version_inflight ELSE ? END,
                      server_last_at = CASE WHEN ? THEN ? ELSE server_last_at END
                WHERE resource = ? AND claim_id = ? AND fence = ?""",
            (new_expires, core.fmt(now), resource_version, resource_version, int(bool(inflight)),
             int(is_server), core.fmt(now), resource, lease_id, fence))
        if cursor.rowcount != 1:
            return _finish(conn, core.deny("stale_fence", now, resource=resource))
        ack = _ack(resource, _lease_row(conn, resource), now, cfg)
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return LeaseResult(ack)


def release_resource_lease(conn: sqlite3.Connection, resource: str, *, lease_id: str, fence: int,
                           resource_version: str | None = None, device: str | None = None,
                           enforce_device: bool = False,
                           config: ResourceLeaseConfig | None = None,
                           now: datetime | None = None) -> LeaseResult:
    """Rueckgabe. Der Marker ``resource_version`` wird nur von einer noch gueltigen Lease
    uebernommen; ein spaeter Release wird quittiert, laesst ihn aber unveraendert.
    Ein abgelaufener, noch nicht uebernommener Polaris star darf noch
    zurueckgegeben werden (``late``); nach einer Uebernahme gilt ``stale_fence``."""
    cfg = config or ResourceLeaseConfig.from_env()
    resource = _validate_resource(resource)
    lease_id, fence = core.validate_lease_ref(lease_id, fence)
    resource_version = core.validate_version(resource_version)
    ensure_resource_lease_schema(conn)

    _begin(conn)
    try:
        now = now if now is not None else core.utcnow()
        _registry(conn, resource)
        row = _lease_row(conn, resource)
        denied = _check_holder(conn, resource, row, lease_id, fence, row["claim_worker"], now,
                               device=device, enforce_device=enforce_device)
        if denied:
            return denied
        late = not _live(row, now)
        is_server = row["claim_role"] == "server"
        cursor = conn.execute(
            """UPDATE resource_leases
                  SET claim_id = NULL, claim_worker = NULL, claim_host = NULL, claim_role = NULL,
                      claim_intent = NULL, claim_device = NULL, claim_issued_at = NULL, claim_expires_at = NULL,
                      claim_heartbeat_at = NULL, ttl_profile = NULL, request_id = NULL,
                      resource_version = COALESCE(?, resource_version),
                      version_inflight = CASE WHEN ? IS NULL THEN version_inflight ELSE 0 END,
                      server_last_at = CASE WHEN ? THEN ? ELSE server_last_at END
                WHERE resource = ? AND claim_id = ? AND fence = ?""",
            (None if late else resource_version, None if late else resource_version, int(is_server),
             core.fmt(now), resource, lease_id, fence))
        if cursor.rowcount != 1:
            return _finish(conn, core.deny("stale_fence", now, resource=resource))
        _event(conn, resource, "release", row["claim_worker"], fence, now, late=late)
        after = _lease_row(conn, resource)
        payload = {"released": True, "resource": resource, "fence": fence, "late": late,
                   "resource_version": after["resource_version"], "server_now": core.fmt(now)}
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    return LeaseResult(payload)


def read_resource_lease(conn: sqlite3.Connection, resource: str, *, lease_id: str | None = None,
                        config: ResourceLeaseConfig | None = None,
                        now: datetime | None = None) -> LeaseResult:
    """Status ohne lease_id; ``own`` nur bei passender lease_id."""
    cfg = config or ResourceLeaseConfig.from_env()
    resource = _validate_resource(resource)
    ensure_resource_lease_schema(conn)
    now = now or core.utcnow()
    reg = _registry(conn, resource)
    row = _fetch(conn, "SELECT * FROM resource_leases WHERE resource = ?", (resource,)) or {
        "claim_id": None, "fence": 0, "resource_version": None, "server_last_at": None,
        "server_wanted_at": None, "claim_expires_at": None}
    live = _live(row, now)
    payload: dict[str, Any] = {
        "resource": resource, "leased": live, "fence": int(row["fence"]),
        "resource_version": row["resource_version"], "server_active": _server_recent(row, now, cfg),
        "version_inflight": bool(row.get("version_inflight")),
        "last_rebaseline_at": row.get("last_rebaseline_at"),
        "server_role": reg["server_role"], "standby_roles": reg["standby_roles"],
        "renew_after_seconds": cfg.renew_seconds, "margin_seconds": cfg.margin_seconds,
        "server_now": core.fmt(now),
    }
    if live:
        payload.update({"holder": _holder_view(row), "issued_at": row["claim_issued_at"],
                        "expires_at": row["claim_expires_at"], "ttl_profile": row["ttl_profile"]})
        if lease_id and lease_id == row["claim_id"]:
            payload["own"] = True
    return LeaseResult(payload)


def list_events(conn: sqlite3.Connection, resource: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Ereignisprotokoll (acquire, release, stale_holder, server_priority_requested)."""
    ensure_resource_lease_schema(conn)
    cur = conn.execute("SELECT * FROM resource_lease_events WHERE resource = ? ORDER BY id DESC LIMIT ?",
                       (_validate_resource(resource), int(limit)))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, tuple(r))) for r in cur.fetchall()]
