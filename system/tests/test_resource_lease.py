# SPDX-License-Identifier: MIT
"""Tests fuer Polaris (Polarstern) P1: Ressourcen-Lease (BACH #2121).

Alle Zeitpunkte werden injiziert (``now=``), ausser beim Zwei-Prozess-Rennen.
Es wird ausschliesslich gegen temporaere SQLite-Dateien getestet.
"""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services import lease_core as core
from hub._services import resource_lease as rl
from hub._services.resource_lease import (
    ResourceLeaseConfig,
    ResourceNotFound,
    acquire_resource_lease,
    ensure_resource_lease_schema,
    list_events,
    read_resource_lease,
    register_resource,
    release_resource_lease,
    renew_resource_lease,
)
from hub._services.resource_lease_client import (
    LeaseConnectionError,
    LeaseProtocolError,
    ResourceLeaseClient,
    ResourceLeaseDeniedError,
    ResourceLeaseExpiredError,
    ResourceLeaseLostError,
)

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

T0 = datetime(2026, 10, 12, 3, 0, 0, tzinfo=timezone.utc)
CFG = ResourceLeaseConfig()
RES = "decisions-chain"
SERVER = "decision-writer@mac-studio"
STANDBY = "decision-writer@asus-gei"
V1 = "a" * 64
V2 = "b" * 64


def _rid() -> str:
    return "req-" + uuid.uuid4().hex


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _register(conn, name=RES, **kw):
    kw.setdefault("allowed_workers", ["decision-writer@*"])
    kw.setdefault("server_role", SERVER)
    kw.setdefault("standby_roles", [STANDBY])
    kw.setdefault("device_bindings", {"test-device": [SERVER, STANDBY], "other-device": [STANDBY]})
    return register_resource(conn, name, **kw)


def _acq(conn, worker=SERVER, resource=RES, now=T0, **kw):
    kw.setdefault("request_id", _rid())
    kw.setdefault("config", CFG)
    return acquire_resource_lease(conn, resource, worker_id=worker, host=worker.rsplit("@", 1)[1],
                                  now=now, **kw)


def _renew(conn, ack, now, **kw):
    return renew_resource_lease(conn, RES, lease_id=ack["lease_id"], fence=ack["fence"], now=now,
                                config=CFG, **kw)


def _release(conn, ack, now, **kw):
    return release_resource_lease(conn, RES, lease_id=ack["lease_id"], fence=ack["fence"], now=now,
                                  config=CFG, **kw)


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "data" / "bach.db"
    path.parent.mkdir(parents=True)
    conn = _connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_resource_lease_schema(conn)
    _register(conn)
    conn.close()
    return path


@pytest.fixture
def conn(db_path):
    c = _connect(db_path)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Kern, Konfiguration, Registrierung, Migration
# ---------------------------------------------------------------------------

def test_star_profile_defaults_and_env_override():
    cfg = ResourceLeaseConfig.from_env({})
    assert cfg.profiles["POLARIS"] == (120, 86400)
    assert (cfg.renew_seconds, cfg.margin_seconds) == (40, 15)
    env = {"BACH_POLARIS_PROFILES": '{"POLARIS": [60, 600]}', "BACH_POLARIS_RENEW": "20",
           "BACH_POLARIS_MARGIN": "5"}
    cfg = ResourceLeaseConfig.from_env(env)
    assert cfg.profiles["POLARIS"] == (60, 600) and cfg.renew_seconds == 20 and cfg.margin_seconds == 5
    bad = ResourceLeaseConfig.from_env({"BACH_POLARIS_PROFILES": '{"POLARIS": [900, 10]}'})
    assert bad.profiles["POLARIS"] == (120, 86400)  # ungueltig -> Startwerte


def test_register_validates_and_unknown_resource(conn):
    with pytest.raises(core.LeaseValidationError):
        register_resource(conn, "Bad Name", allowed_workers=["a@b"], server_role="a@b")
    with pytest.raises(core.LeaseValidationError):
        register_resource(conn, "ok", allowed_workers=[], server_role="a@b")
    with pytest.raises(ResourceNotFound):
        _acq(conn, resource="unbekannt")
    denied = _acq(conn, worker="intruder@mac-studio")
    assert denied.http_status == 409 and denied.payload["reason"] == "worker_not_allowed"
    # zugelassen, aber ohne Rolle
    register_resource(conn, "norole", allowed_workers=["*@*"], server_role="x@y")
    assert _acq(conn, resource="norole", worker="a@b").payload["reason"] == "worker_not_allowed"


def test_migration_is_idempotent_and_runs_inside_transaction(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m053", SYSTEM_ROOT / "data" / "schema" / "migrations" / "053_resource_leases.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db = sqlite3.connect(str(tmp_path / "m.db"))
    db.execute("CREATE TABLE _migrations (id INTEGER PRIMARY KEY, filename TEXT UNIQUE NOT NULL, applied_at TEXT)")
    db.execute("INSERT INTO _migrations (filename, applied_at) VALUES ('001_x.sql', 'x')")
    db.commit()
    db.execute("BEGIN")  # wie core.db.run_migrations: offene Transaktion
    mod.run_migration(db)
    db.commit()
    mod.run_migration(db)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"resource_registry", "resource_leases", "resource_lease_events"} <= tables
    # fremde Migrationen werden nicht angefasst/gebucht
    assert [r[0] for r in db.execute("SELECT filename FROM _migrations")] == ["001_x.sql"]


def test_manifest_version_covers_paths_missing_and_content(tmp_path):
    (tmp_path / "chain").mkdir()
    (tmp_path / "chain" / "a.txt").write_text("eins", encoding="utf-8")
    (tmp_path / "TO-DECIDE.txt").write_text("x", encoding="utf-8")
    paths = ["TO-DECIDE.txt", "DECIDED.md", "chain"]
    full = core.manifest_version(tmp_path, paths)
    assert full == core.manifest_version(tmp_path, reversed(paths))  # Reihenfolge egal
    (tmp_path / "DECIDED.md").write_text("", encoding="utf-8")
    assert core.manifest_version(tmp_path, paths) != full  # fehlend != leer vorhanden
    again = core.manifest_version(tmp_path, paths)
    (tmp_path / "chain" / "a.txt").write_text("zwei", encoding="utf-8")
    assert core.manifest_version(tmp_path, paths) != again


# ---------------------------------------------------------------------------
# Rennen, Fence, Ablauf
# ---------------------------------------------------------------------------

def _race(db, names, barrier, queue, who):  # laeuft in eigenem Prozess
    conn = _connect(Path(db))
    barrier.wait()
    out = {}
    for name in names:
        res = acquire_resource_lease(conn, name, worker_id=who, host="mac-studio", request_id=_rid(),
                                     config=CFG)
        out[name] = (res.granted, res.payload.get("reason"))
    queue.put((who, out))


def test_two_processes_exactly_one_gets_the_star(tmp_path):
    db = tmp_path / "race.db"
    conn = _connect(db)
    names = [f"race-{i}" for i in range(15)]
    for name in names:
        register_resource(conn, name, allowed_workers=["*@mac-studio"], server_role="*@mac-studio")
    conn.close()
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=_race, args=(str(db), names, barrier, queue, who))
             for who in ("w1@mac-studio", "w2@mac-studio")]
    for p in procs:
        p.start()
    results = dict(queue.get(timeout=120) for _ in procs)
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    for name in names:
        granted = [who for who, out in results.items() if out[name][0]]
        assert len(granted) == 1, (name, results)
        loser = next(out[name] for who, out in results.items() if who not in granted)
        assert loser[1] == "held"
    with _connect(db) as c:
        assert {r[0] for r in c.execute("SELECT fence FROM resource_leases")} == {1}


def test_expiry_raises_fence_by_one_and_stale_holder_is_denied_and_logged(conn):
    first = _acq(conn).payload
    assert first["granted"] and first["fence"] == 1 and first["role"] == "server"
    assert first["renew_after_seconds"] == 40 and first["margin_seconds"] == 15
    other = "decision-writer@mac-studio"
    held = _acq(conn, worker=other, now=T0 + timedelta(seconds=60))
    assert held.http_status == 409 and held.payload["reason"] == "already_held_by_caller"
    assert first["lease_id"] not in json.dumps(held.payload)
    second = _acq(conn, now=T0 + timedelta(seconds=121)).payload
    assert second["granted"] and second["fence"] == 2  # Ablauf -> Fence + 1
    # Alt-Halter (pausiert) meldet sich nach der Uebernahme
    late_renew = _renew(conn, first, T0 + timedelta(seconds=130))
    late_release = _release(conn, first, T0 + timedelta(seconds=131))
    assert late_renew.payload["reason"] == late_release.payload["reason"] == "stale_fence"
    assert late_renew.payload["fence"] == 2
    seen = [e for e in list_events(conn, RES) if e["action"] == "stale_holder"]
    assert len(seen) == 2 and json.loads(seen[0]["detail"])["current_fence"] == 2
    # der aktuelle Halter ist unberuehrt
    assert read_resource_lease(conn, RES, lease_id=second["lease_id"], now=T0 + timedelta(seconds=140),
                               config=CFG).payload["own"] is True


def test_replay_renew_cap_and_release_keeps_fence_high_water(conn):
    rid = _rid()
    ack = _acq(conn, request_id=rid).payload
    replay = _acq(conn, request_id=rid, now=T0 + timedelta(seconds=5))
    assert replay.granted and replay.payload["replayed"] and replay.payload["lease_id"] == ack["lease_id"]
    renewed = _renew(conn, ack, T0 + timedelta(seconds=40)).payload
    assert renewed["expires_at"] > ack["expires_at"] and renewed["fence"] == 1
    assert _renew(conn, {**ack, "fence": 7}, T0 + timedelta(seconds=50)).payload["reason"] == "stale_fence"
    released = _release(conn, ack, T0 + timedelta(seconds=60)).payload
    assert released["released"] and released["late"] is False
    assert _release(conn, ack, T0 + timedelta(seconds=61)).payload["reason"] == "stale_fence"
    nxt = _acq(conn, now=T0 + timedelta(seconds=70)).payload
    assert nxt["fence"] == 2  # Hochwassermarke bleibt nach Release


def test_renew_is_capped_at_max_total(conn):
    short = ResourceLeaseConfig(profiles={"POLARIS": (120, 130)})
    ack = _acq(conn, config=short).payload
    kw = dict(lease_id=ack["lease_id"], fence=1, config=short)
    capped = renew_resource_lease(conn, RES, now=T0 + timedelta(seconds=100), **kw).payload
    assert capped["expires_at"] == core.fmt(T0 + timedelta(seconds=130))
    again = renew_resource_lease(conn, RES, now=T0 + timedelta(seconds=110), **kw)
    assert again.payload["reason"] == "max_total_reached"


def test_late_release_after_expiry_without_takeover_is_accepted(conn):
    ack = _acq(conn).payload
    res = _release(conn, ack, T0 + timedelta(seconds=500))
    assert res.http_status == 200 and res.payload["late"] is True
    assert _renew(conn, ack, T0 + timedelta(seconds=600)).payload["reason"] == "stale_fence"


# ---------------------------------------------------------------------------
# Sync-Schranke
# ---------------------------------------------------------------------------

def test_stale_resource_version_blocks_new_holder_until_manifest_matches(conn):
    first = _acq(conn).payload
    assert first["resource_version"] is None
    _renew(conn, first, T0 + timedelta(seconds=40), resource_version=V1)
    done = _release(conn, first, T0 + timedelta(seconds=50), resource_version=V2).payload
    assert done["resource_version"] == V2
    t = T0 + timedelta(seconds=60)
    stale = _acq(conn, resource_version=V1, now=t)
    assert stale.http_status == 409 and stale.payload["reason"] == "stale_resource_version"
    assert stale.payload["expected_resource_version"] == V2
    assert _acq(conn, now=t).payload["reason"] == "resource_version_required"
    ok = _acq(conn, resource_version=V2, now=t).payload
    assert ok["granted"] and ok["fence"] == 2 and ok["resource_version"] == V2
    with pytest.raises(core.LeaseValidationError):
        _acq(conn, resource_version="nicht-sha", now=t)


# ---------------------------------------------------------------------------
# Servermodus: server_priority statt Preempt, Standby nur bei stillem Server
# ---------------------------------------------------------------------------

def test_standby_takeover_needs_expired_server_lease_and_silent_server(conn):
    assert _acq(conn, worker=STANDBY).payload["reason"] == "server_unknown"  # nie ein Server gesehen
    server = _acq(conn, now=T0).payload
    live = _acq(conn, worker=STANDBY, now=T0 + timedelta(seconds=60))
    assert live.payload["reason"] == "held" and live.payload["holder"]["role"] == "server"
    # Server gibt sauber frei: noch kein Ausfall -> Standby wartet
    _release(conn, server, T0 + timedelta(seconds=10))
    assert _acq(conn, worker=STANDBY, now=T0 + timedelta(seconds=20)).payload["reason"] == "server_active"
    # nach der Stille uebernimmt der Standby
    taken = _acq(conn, worker=STANDBY, now=T0 + timedelta(seconds=140)).payload
    assert taken["granted"] and taken["role"] == "standby" and taken["fence"] == 2


def test_server_priority_without_preempt(conn):
    server = _acq(conn, now=T0).payload  # laeuft ohne Renew ab (Ausfall)
    standby = _acq(conn, worker=STANDBY, now=T0 + timedelta(seconds=125)).payload
    assert standby["granted"] and standby["fence"] == 2
    # Server kehrt zurueck: kein Preempt, nur Wunsch + Hinweis
    back = _acq(conn, now=T0 + timedelta(seconds=150))
    assert back.http_status == 409 and back.payload["reason"] == "held" and back.payload["server_priority"]
    assert back.payload["holder"]["worker_id"] == STANDBY
    # Der Standby behaelt seinen Stern bis zum Release, Renew wird aber abgelehnt
    denied = _renew(conn, standby, T0 + timedelta(seconds=160))
    assert denied.payload["reason"] == "server_priority" and denied.payload["release_requested"]
    assert read_resource_lease(conn, RES, now=T0 + timedelta(seconds=170), config=CFG).payload["leased"]
    assert _release(conn, standby, T0 + timedelta(seconds=175)).payload["released"]
    won = _acq(conn, now=T0 + timedelta(seconds=180)).payload
    assert won["granted"] and won["fence"] == 3 and won["role"] == "server"
    assert "server_priority_requested" in [e["action"] for e in list_events(conn, RES)]


def test_server_wish_expires_when_server_goes_silent_again(conn):
    cfg = ResourceLeaseConfig(server_down_after_seconds=30)
    kw = dict(config=cfg)
    _acq(conn, now=T0, **kw)
    standby = _acq(conn, worker=STANDBY, now=T0 + timedelta(seconds=125), **kw).payload
    _acq(conn, now=T0 + timedelta(seconds=150), **kw)  # Wunsch des Servers
    ref = dict(lease_id=standby["lease_id"], fence=standby["fence"], config=cfg)
    assert renew_resource_lease(conn, RES, now=T0 + timedelta(seconds=160), **ref).payload["reason"] == "server_priority"
    # 30 s ohne Lebenszeichen des Servers: der Wunsch ist verfallen, Renew wieder erlaubt
    assert renew_resource_lease(conn, RES, now=T0 + timedelta(seconds=200), **ref).granted


# ---------------------------------------------------------------------------
# Clients: zwei "Hosts", Zeit, fehlende Authority
# ---------------------------------------------------------------------------

def _client(db_path):
    return ResourceLeaseClient.for_db(lambda: _connect(db_path), allow_isolated=True)


def test_two_hosts_one_lead_pause_and_verify(db_path):
    with _client(db_path) as mac, _client(db_path) as asus:
        ack = mac.acquire(RES, worker_id=SERVER, now=T0)
        with pytest.raises(ResourceLeaseDeniedError) as err:
            asus.acquire(RES, worker_id=STANDBY, now=T0 + timedelta(seconds=30))
        assert err.value.reason == "held" and ack.lease_id not in str(err.value.payload)
        assert mac.status(RES, lease_id=ack.lease_id, now=T0 + timedelta(seconds=30)).own
        assert mac.verify(ack, now=T0 + timedelta(seconds=30)).fence == 1
        # Mac pausiert; Standby uebernimmt nach Ablauf
        taken = asus.acquire(RES, worker_id=STANDBY, now=T0 + timedelta(seconds=125))
        assert taken.fence == 2 and taken.role == "standby"
        # Alt-Halter wacht auf: Nachpruefung meldet star_lost, Renew/Release werden abgelehnt
        with pytest.raises(ResourceLeaseLostError):
            mac.verify(ack, now=T0 + timedelta(seconds=130))
        with pytest.raises(ResourceLeaseDeniedError) as late:
            mac.renew(ack, now=T0 + timedelta(seconds=131))
        assert late.value.reason == "stale_fence"
        assert asus.release(taken, resource_version=V1, now=T0 + timedelta(seconds=140)).resource_version == V1


def test_local_deadline_uses_monotonic_clock_and_detects_gaps(db_path):
    with _client(db_path) as client:
        ack = client.acquire(RES, worker_id=SERVER)  # echte Zeit: verify() fragt ohne now
        m0, w0 = ack.received_mono, ack.received_wall
        assert ack.is_valid(now_mono=m0 + 60) and not ack.is_valid(now_mono=m0 + 106)  # 120 - 15 Marge
        ack.assert_valid()  # frisch: ok
        assert not ack.needs_online_check(now_mono=m0 + 60, now_wall=w0 + 61)
        assert ack.needs_online_check(now_mono=m0 + 5, now_wall=w0 + 600)  # Suspend / Zeitsprung
        gap = replace(ack, received_mono=m0 - 1, received_wall=w0 - 600)
        with pytest.raises(ResourceLeaseExpiredError):
            gap.assert_valid()  # Luecke ohne Client -> kein Schreiben
        gap.assert_valid(client, margin=15)  # mit Client: Online-Pruefung bestanden
        stale = replace(ack, received_mono=m0 - 200)
        with pytest.raises(ResourceLeaseExpiredError):
            stale.assert_valid()


def test_no_reachable_authority_fails_closed(db_path, monkeypatch):
    # Worker-Host mit totem Lead: keine Uebernahme, keine stille Rueckfallebene
    dead = ResourceLeaseClient(lead_url="http://127.0.0.1:9", device_token="x", timeout=0.5)
    assert dead.mode == "remote"
    with pytest.raises(LeaseConnectionError):
        dead.acquire(RES, worker_id=STANDBY)
    with pytest.raises(LeaseConnectionError):
        dead.status(RES)
    # ohne Lead-Authority und ohne ausdrueckliche Freigabe kein lokaler Direktweg
    monkeypatch.delenv("BACH_POLARIS_ALLOW_ISOLATED", raising=False)
    with pytest.raises(LeaseProtocolError):
        ResourceLeaseClient.for_db(lambda: _connect(db_path))


# ---------------------------------------------------------------------------
# CAS: Negativkontrolle
# ---------------------------------------------------------------------------

class _Interloper(sqlite3.Connection):
    """Schiebt unmittelbar vor dem Acquire-UPDATE einen fremden Fence-Sprung ein."""
    armed = False

    def execute(self, sql, *args):
        if self.armed and "SET claim_id = ?" in sql and "fence + 1" in sql:
            self.armed = False
            super().execute("UPDATE resource_leases SET fence = fence + 1 WHERE resource = ?", (RES,))
        return super().execute(sql, *args)


def _cas_scenario(module, db_path):
    conn = sqlite3.connect(str(db_path), timeout=10.0, factory=_Interloper)
    conn.row_factory = sqlite3.Row
    conn.armed = True
    try:
        return module.acquire_resource_lease(conn, RES, worker_id=SERVER, host="mac-studio",
                                             request_id=_rid(), config=CFG, now=T0)
    finally:
        conn.close()


def test_fence_cas_blocks_interleaved_writer_and_removed_cas_turns_red(db_path, tmp_path, monkeypatch):
    result = _cas_scenario(rl, db_path)
    assert result.http_status == 409 and result.payload["reason"] == "conflict"
    with _connect(db_path) as c:
        assert c.execute("SELECT claim_id FROM resource_leases").fetchone()[0] is None
    # Mutant ohne CAS: dieselbe Pruefung muss versagen (also wuerde der Test rot)
    source = (SYSTEM_ROOT / "hub" / "_services" / "resource_lease.py").read_text(encoding="utf-8")
    needle = 'WHERE resource = ? AND fence = ?""",\n            (lease_id'
    assert source.count(needle) == 1
    mutant_src = source.replace(needle, 'WHERE resource = ? AND ? IS NOT NULL""",\n            (lease_id')
    mutant = type(sys)("resource_lease_mutant")
    monkeypatch.setitem(sys.modules, "resource_lease_mutant", mutant)  # dataclasses braucht das Modul
    exec(compile(mutant_src, "resource_lease_mutant.py", "exec"), mutant.__dict__)
    path2 = tmp_path / "mutant.db"
    c2 = _connect(path2)
    ensure_resource_lease_schema(c2)
    _register(c2)
    c2.close()
    wrong = _cas_scenario(mutant, path2)
    assert wrong.granted, "ohne CAS wird trotz fremdem Fence-Sprung gewaehrt"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_round_trip(db_path, monkeypatch, tmp_path):
    from hub.lease import LeaseHandler
    from hub._services import task_lease_client as tlc
    monkeypatch.setattr(tlc, "get_lead_config", lambda: {"mode": "lead", "lead_url": None})
    handler = LeaseHandler(tmp_path)
    monkeypatch.setattr(handler, "_canonical_db", db_path, raising=False)
    ok, msg = handler.handle("cli-res", ["register", "--allowed", "agent@*", "--server-role", "agent@mac-studio"])
    assert ok, msg
    ok, msg = handler.handle("cli-res", ["acquire", "--by", "agent@mac-studio", "--intent", "test"])
    assert ok and "Fence 1" in msg, msg
    assert "Lease-Capability" not in msg  # Standard: keine Capability auf stdout
    lease_id = _own_lease(db_path, "cli-res")
    handler.handle("cli-res-b", ["register", "--allowed", "agent@*", "--server-role", "agent@mac-studio"])
    ok, shown = handler.handle("cli-res-b", ["acquire", "--by", "agent@mac-studio", "--show-capability"])
    assert ok and "Lease-Capability: " in shown
    assert handler.handle("cli-res", ["status", "--lease-id", lease_id])[1].count("OWN POLARIS STAR") == 1
    ok, msg = handler.handle("cli-res", ["acquire", "--by", "agent@mac-studio"])
    assert not ok and "already_held_by_caller" in msg
    assert handler.handle("cli-res", ["renew", "--lease-id", lease_id, "--fence", "1"])[0]
    assert handler.handle("cli-res", ["release", "--lease-id", lease_id, "--fence", "1", "--version", V1])[0]
    ok, msg = handler.handle("cli-res", ["release", "--lease-id", lease_id, "--fence", "1"])
    assert not ok and "stale_fence" in msg
    assert handler.handle("cli-res", ["status"])[0]
    assert "Usage" in handler.handle("cli-res", [])[1]
    assert handler.handle("cli-res", ["acquire", "--by", "agent@mac-studio"], dry_run=True)[1].startswith("[DRY-RUN]")


def _own_lease(db_path, resource):
    with _connect(db_path) as c:
        return c.execute("SELECT claim_id FROM resource_leases WHERE resource = ?", (resource,)).fetchone()[0]


def test_cli_register_refused_unless_real_lead_authority(db_path, monkeypatch, tmp_path):
    from hub.lease import LeaseHandler
    monkeypatch.setenv("BACH_POLARIS_ALLOW_ISOLATED", "1")  # auch mit Freigabe: isolated ist keine Authority
    handler = LeaseHandler(tmp_path)
    monkeypatch.setattr(handler, "_canonical_db", db_path, raising=False)
    ok, msg = handler.handle("zz", ["register", "--allowed", "a@*", "--server-role", "a@b"])
    assert not ok and "Lead-Authority" in msg
    with _connect(db_path) as c:
        assert c.execute("SELECT 1 FROM resource_registry WHERE resource = 'zz'").fetchone() is None
    from hub._services import task_lease_client as tlc
    monkeypatch.setattr(tlc, "get_lead_config", lambda: {"mode": "lead", "lead_url": None})
    ok, msg = handler.handle("zz", ["register", "--allowed", "a@*", "--server-role", "a@b", "--bind", "dev1=a@b"])
    assert ok, msg
    with _connect(db_path) as c:
        row = c.execute("SELECT device_bindings FROM resource_registry WHERE resource = 'zz'").fetchone()
    assert json.loads(row[0]) == {"dev1": ["a@b"]}


def test_cli_discovered_by_registry():
    from core.registry import HandlerRegistry
    reg = HandlerRegistry()
    reg.discover(SYSTEM_ROOT / "hub")
    assert "polaris" in reg._handlers


# ---------------------------------------------------------------------------
# HTTP-Routen mit Geraete-Token
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi nicht installiert")
class TestResourceLeaseRoutes:
    @pytest.fixture
    def client(self, db_path, tmp_path, monkeypatch):
        import gui.server as srv
        monkeypatch.setattr(srv, "BACH_DB", db_path)
        monkeypatch.setattr(srv, "USER_DB", db_path)
        monkeypatch.setattr(srv, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(srv, "BACH_DIR", tmp_path)
        monkeypatch.setattr(srv, "GUI_DIR", tmp_path / "gui")
        devices = {"star-fixture": {"id": 1, "name": "test-device"},
                   "other-fixture": {"id": 2, "name": "other-device"},
                   "unbound-fixture": {"id": 3, "name": "unbound-device"}}
        monkeypatch.setattr(srv, "validate_token", lambda token: devices.get(token))
        self.db_path = db_path
        return TestClient(srv.app, raise_server_exceptions=False,
                          headers={"Authorization": "Bearer star-fixture"})

    def _body(self, worker=SERVER, **extra):
        return {"worker_id": worker, "host": worker.rsplit("@", 1)[1], "request_id": _rid(), **extra}

    def test_full_cycle(self, client):
        r = client.post(f"/api/resources/{RES}/lease", json=self._body())
        assert r.status_code == 200, r.text
        ack = r.json()
        assert ack["granted"] and ack["fence"] == 1 and ack["role"] == "server"
        r = client.post(f"/api/resources/{RES}/lease", json=self._body(STANDBY))
        assert r.status_code == 409 and r.json()["reason"] == "held" and ack["lease_id"] not in r.text
        r = client.get(f"/api/resources/{RES}/lease")
        assert r.status_code == 200 and r.json()["leased"] and "own" not in r.json()
        assert ack["lease_id"] not in r.text
        r = client.get(f"/api/resources/{RES}/lease", headers={"X-Lease-Id": ack["lease_id"]})
        assert r.json()["own"] is True
        ref = {"lease_id": ack["lease_id"], "fence": 1}
        r = client.post(f"/api/resources/{RES}/lease/renew", json={**ref, "resource_version": V1})
        assert r.status_code == 200 and r.json()["resource_version"] == V1
        r = client.post(f"/api/resources/{RES}/lease/release", json=ref)
        assert r.status_code == 200 and r.json()["released"] is True
        r = client.post(f"/api/resources/{RES}/lease/release", json=ref)
        assert r.status_code == 409 and r.json()["reason"] == "stale_fence"
        r = client.post(f"/api/resources/{RES}/lease", json=self._body(resource_version=V2))
        assert r.status_code == 409 and r.json()["reason"] == "stale_resource_version"

    def test_error_mapping(self, client):
        assert client.post("/api/resources/unbekannt/lease", json=self._body()).status_code == 404
        assert client.get("/api/resources/unbekannt/lease").status_code == 404
        bad = self._body()
        bad["request_id"] = "kurz"
        assert client.post(f"/api/resources/{RES}/lease", json=bad).status_code == 422
        assert client.post(f"/api/resources/{RES}/lease/renew",
                           json={"lease_id": "x", "fence": 1}).status_code == 422
        assert client.post(f"/api/resources/{RES}/lease",
                           json={**self._body(), "unbekannt": 1}).status_code == 422

    def test_requires_device_token(self, client):
        import gui.server as srv
        anon = TestClient(srv.app, raise_server_exceptions=False)
        assert anon.get(f"/api/resources/{RES}/lease").status_code == 401
        assert anon.post(f"/api/resources/{RES}/lease", json=self._body()).status_code == 401
        wrong = TestClient(srv.app, raise_server_exceptions=False, headers={"Authorization": "Bearer nope"})
        assert wrong.post(f"/api/resources/{RES}/lease", json=self._body()).status_code in (401, 403)
        assert anon.post(f"/api/resources/{RES}/lease/renew",
                         json={"lease_id": str(uuid.uuid4()), "fence": 1}).status_code == 401
        assert anon.post(f"/api/resources/{RES}/lease/release",
                         json={"lease_id": str(uuid.uuid4()), "fence": 1}).status_code == 401

    def _as(self, token):
        import gui.server as srv
        return TestClient(srv.app, raise_server_exceptions=False, headers={"Authorization": f"Bearer {token}"})

    def test_worker_is_bound_to_authenticated_device(self, client):
        other, unbound = self._as("other-fixture"), self._as("unbound-fixture")
        # Geraet B gibt die Server-Identitaet an: abgelehnt, keine Rolle aus Request-Feldern
        r = other.post(f"/api/resources/{RES}/lease", json=self._body(SERVER))
        assert r.status_code == 409 and r.json()["reason"] == "device_not_bound"
        # Geraet ohne Zuordnung: fail-closed, auch mit zugelassenem Worker
        r = unbound.post(f"/api/resources/{RES}/lease", json=self._body(STANDBY))
        assert r.status_code == 409 and r.json()["reason"] == "device_not_bound"
        # das zugeordnete Geraet darf
        ack = client.post(f"/api/resources/{RES}/lease", json=self._body(SERVER)).json()
        assert ack["granted"] and ack["role"] == "server"
        # Fremdes Geraet kennt lease_id/fence, kann aber weder verlaengern noch freigeben
        ref = {"lease_id": ack["lease_id"], "fence": ack["fence"]}
        for action in ("renew", "release"):
            r = other.post(f"/api/resources/{RES}/lease/{action}", json=ref)
            assert r.status_code == 409 and r.json()["reason"] == "device_not_bound"
        assert client.post(f"/api/resources/{RES}/lease/renew", json=ref).status_code == 200
        with _connect(self.db_path) as c:
            actions = [e["action"] for e in list_events(c, RES)]
        assert actions.count("device_not_bound") >= 4

    def test_auth_for_slash_variants_and_methods(self, client):
        import gui.server as srv
        anon = TestClient(srv.app, raise_server_exceptions=False, follow_redirects=False)
        authed = TestClient(srv.app, raise_server_exceptions=False, follow_redirects=False,
                            headers={"Authorization": "Bearer star-fixture"})
        paths = [f"/api/resources/{RES}/lease", f"/api/resources/{RES}/lease/",
                 f"/api/resources/{RES}/lease/renew", f"/api/resources/{RES}/lease/renew/",
                 f"/api/resources/{RES}/lease/release", f"/api/resources/{RES}/lease/release/"]
        for path in paths:
            for method in ("get", "post", "put", "delete", "patch"):
                assert getattr(anon, method)(path).status_code == 401, (method, path)
        for method in ("put", "delete", "patch"):
            for path in paths[::2]:
                assert getattr(authed, method)(path).status_code == 405, (method, path)
        assert authed.get(f"/api/resources/{RES}/lease/renew").status_code == 405
        assert authed.get(f"/api/resources/{RES}/lease/release").status_code == 405
        for path in paths[1::2]:  # Slash-Varianten: Weiterleitung/404/405, nie eine Gewaehrung
            r = authed.post(path, json=self._body())
            assert r.status_code in (307, 404, 405) and "lease_id" not in r.text, (path, r.status_code)


# ---------------------------------------------------------------------------
# R28-Nachbesserung
# ---------------------------------------------------------------------------

def test_late_release_does_not_change_resource_version(conn):
    first = _acq(conn).payload
    _renew(conn, first, T0 + timedelta(seconds=40), resource_version=V1)
    # Pause nach Ablauf (Lease endet T0+160): spaeter Release meldet einen unvollstaendigen Stand
    late = _release(conn, first, T0 + timedelta(seconds=400), resource_version=V2)
    assert late.http_status == 200 and late.payload["late"] is True
    assert late.payload["resource_version"] == V1  # Marker unveraendert
    nxt = _acq(conn, resource_version=V1, now=T0 + timedelta(seconds=410))
    assert nxt.granted
    # gueltiger Release uebernimmt den Marker
    done = _release(conn, nxt.payload, T0 + timedelta(seconds=420), resource_version=V2)
    assert done.payload["late"] is False and done.payload["resource_version"] == V2


def test_enforce_device_binding_at_service_level(conn):
    denied = _acq(conn, device="other-device", enforce_device=True)
    assert denied.payload["reason"] == "device_not_bound"
    assert _acq(conn, device=None, enforce_device=True).payload["reason"] == "device_not_bound"
    assert _acq(conn, device="nirgends", enforce_device=True).payload["reason"] == "device_not_bound"
    ack = _acq(conn, device="test-device", enforce_device=True).payload
    assert ack["granted"]
    res = renew_resource_lease(conn, RES, lease_id=ack["lease_id"], fence=1, device="other-device",
                               enforce_device=True, config=CFG, now=T0 + timedelta(seconds=5))
    assert res.payload["reason"] == "device_not_bound"
    with pytest.raises(core.LeaseValidationError):
        register_resource(conn, "bad", allowed_workers=["a@b"], server_role="a@b",
                          device_bindings={"": ["a@b"]})


def test_local_deadline_starts_at_send_time_and_slow_answers_fail_closed(db_path, monkeypatch):
    import time as _time
    from hub._services import resource_lease_client as rlc
    real = rlc.acquire_resource_lease

    def slow(*args, **kwargs):
        _time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(rlc, "acquire_resource_lease", slow)
    with ResourceLeaseClient.for_db(lambda: _connect(db_path), allow_isolated=True,
                                    max_response_seconds=5) as client:
        ack = client.acquire(RES, worker_id=SERVER)
        # Restlaufzeit ist um die Antwortlaufzeit (>= 0.3 s) gekuerzt, nicht ab Empfang gerechnet
        assert ack.remaining_at_receipt == pytest.approx(120, abs=1)
        assert ack.remaining() < 120 - 0.25
        client.release(ack)
    with ResourceLeaseClient.for_db(lambda: _connect(db_path), allow_isolated=True,
                                    max_response_seconds=0.1) as client:
        with pytest.raises(ResourceLeaseExpiredError):
            client.acquire(RES, worker_id=SERVER, request_id=_rid())


def test_real_migration_runner_with_unbooked_052(tmp_path):
    from core.db import Database
    root = SYSTEM_ROOT / "data" / "schema"
    mig = sorted(f.name for f in (root / "migrations").glob("*")
                 if f.suffix in (".sql", ".py") and not f.name.startswith("_"))
    assert "052_blueprint_template_provider.py" in mig and "053_resource_leases.py" in mig

    def prepared(path, booked):
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE _migrations (id INTEGER PRIMARY KEY, filename TEXT UNIQUE NOT NULL, applied_at TEXT NOT NULL)")
        c.executemany("INSERT INTO _migrations (filename, applied_at) VALUES (?, 'x')", [(m,) for m in booked])
        c.commit()
        c.close()

    # A) 052 und 053 ungebucht, Rest gebucht: der echte Runner bucht beide in Reihenfolge, 2. Lauf leer
    a = tmp_path / "a.db"
    prepared(a, [m for m in mig if m[:3] not in ("052", "053")])
    db = Database(a, root)
    assert db.migration_backlog() == []
    applied, error = db.run_migrations()
    assert error is None and applied == ["052_blueprint_template_provider.py", "053_resource_leases.py"]
    assert db.run_migrations() == ([], None)
    tables = {r[0] for r in sqlite3.connect(a).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"resource_registry", "resource_leases", "resource_lease_events"} <= tables

    # B) 053 gebucht, aber 052 bleibt ungebucht (Bestands-DB): 052 ist Rueckstand, nichts wird angefasst;
    #    der Dienst legt seine Tabellen trotzdem selbst an (ensure), ohne 052 zu buchen
    b = tmp_path / "b.db"
    prepared(b, [m for m in mig if m[:3] != "052"])
    db = Database(b, root)
    assert db.migration_backlog() == ["052_blueprint_template_provider.py"]
    conn = sqlite3.connect(b)
    ensure_resource_lease_schema(conn)
    conn.close()
    booked = [r[0] for r in sqlite3.connect(b).execute("SELECT filename FROM _migrations")]
    assert "052_blueprint_template_provider.py" not in booked
    names = {r[0] for r in sqlite3.connect(b).execute("SELECT name FROM sqlite_master")}
    assert "resource_leases" in names and "agent_blueprints" not in names  # 052 unberuehrt


def test_migration_053_only_via_dispatch_books_nothing_else(tmp_path):
    from core.db import dispatch_py_migration
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m053b", SYSTEM_ROOT / "data" / "schema" / "migrations" / "053_resource_leases.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    path = tmp_path / "d.db"
    conn = sqlite3.connect(path)
    dispatch_py_migration(mod, conn, path)
    conn.commit()
    dispatch_py_migration(mod, conn, path)  # idempotent
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
        "resource_registry", "resource_leases", "resource_lease_events", "sqlite_sequence"}
    default = [r for r in conn.execute("PRAGMA table_info(resource_registry)") if r[1] == "default_profile"][0]
    assert default[4] == "'POLARIS'"


# ---------------------------------------------------------------------------
# R28b
# ---------------------------------------------------------------------------

_OLD_SHAPE = (
    "CREATE TABLE resource_registry (resource TEXT PRIMARY KEY, allowed_workers TEXT NOT NULL,"
    " server_role TEXT NOT NULL, standby_roles TEXT NOT NULL DEFAULT '[]',"
    " default_profile TEXT NOT NULL DEFAULT 'POLARIS', updated_at TEXT NOT NULL)",
    "CREATE TABLE resource_leases (resource TEXT PRIMARY KEY, claim_id TEXT, claim_worker TEXT,"
    " claim_host TEXT, claim_role TEXT, claim_intent TEXT, claim_issued_at TEXT, claim_expires_at TEXT,"
    " claim_heartbeat_at TEXT, fence INTEGER NOT NULL DEFAULT 0, ttl_profile TEXT, request_id TEXT,"
    " resource_version TEXT, server_last_at TEXT, server_wanted_at TEXT)",
    "CREATE TABLE resource_lease_events (id INTEGER PRIMARY KEY AUTOINCREMENT, resource TEXT NOT NULL,"
    " at TEXT NOT NULL, action TEXT NOT NULL, worker_id TEXT, fence INTEGER, detail TEXT)",
)


def test_ensure_adds_missing_columns_additively_and_idempotently(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    for stmt in _OLD_SHAPE:  # aeltere Tabellenform: ohne device_bindings und claim_device
        old.execute(stmt)
    old.execute("INSERT INTO resource_registry VALUES ('decisions-chain', '[\"decision-writer@*\"]',"
                " 'decision-writer@mac-studio', '[]', 'POLARIS', 'x')")
    old.execute("INSERT INTO resource_leases (resource, fence) VALUES ('decisions-chain', 4)")
    old.commit()
    old.close()

    def shape():
        c = sqlite3.connect(path)
        try:
            return [(t, [r[1] for r in c.execute(f"PRAGMA table_info({t})")]) for t in
                    ("resource_registry", "resource_leases", "resource_lease_events")]
        finally:
            c.close()

    conn = _connect(path)
    ensure_resource_lease_schema(conn)
    after = shape()
    assert "device_bindings" in dict(after)["resource_registry"] and "claim_device" in dict(after)["resource_leases"]
    # R29-5: auch die Rebaseline-/In-flight-Spalten kommen an einer alten Tabelle additiv dazu
    assert {"version_inflight", "last_rebaseline_at"} <= set(dict(after)["resource_leases"])
    ack = _acq(conn).payload  # Bestandsdaten bleiben nutzbar, Fence setzt bei 4 fort
    assert ack["granted"] and ack["fence"] == 5
    assert _acq(conn, device="x", enforce_device=True, worker=STANDBY, now=T0 + timedelta(seconds=1)
                ).payload["reason"] == "device_not_bound"  # leere Zuordnung (Default '{}')
    ensure_resource_lease_schema(conn)  # zweiter Lauf aendert nichts
    assert shape() == after
    conn.close()


def test_device_bindings_are_exact_worker_ids_without_wildcards(conn):
    for bad in (["decision-writer@*"], ["*@mac-studio"], ["decision-writer@mac-?tudio"], ["decision-writer"],
                ["*"], [], [""]):
        with pytest.raises(core.LeaseValidationError):
            register_resource(conn, "wild", allowed_workers=["a@b"], server_role="a@b",
                              device_bindings={"dev": bad})
    assert conn.execute("SELECT 1 FROM resource_registry WHERE resource = 'wild'").fetchone() is None
    # exakter Vergleich, case-sensitiv
    register_resource(conn, "exact", allowed_workers=["*@*"], server_role="Agent@Mac-Studio",
                      device_bindings={"dev": ["Agent@Mac-Studio"]})
    ok = acquire_resource_lease(conn, "exact", worker_id="Agent@Mac-Studio", host="Mac-Studio",
                                request_id=_rid(), device="dev", enforce_device=True, now=T0, config=CFG)
    assert ok.granted
    other_case = acquire_resource_lease(conn, "exact", worker_id="agent@mac-studio", host="mac-studio",
                                        request_id=_rid(), device="dev", enforce_device=True, now=T0, config=CFG)
    assert other_case.payload["reason"] == "device_not_bound"


# ---------------------------------------------------------------------------
# Folge: Manifest-Testvektor (identisch im decision-clicker), rebaseline
# ---------------------------------------------------------------------------

#: Gemeinsamer Vektor: a.txt = "x", b.txt fehlt, leer/ ist ein leerer Ordner (== fehlend).
SHARED_MANIFEST_VECTOR = "025c824ad9189e559d0844f99372867f61b3b56b7c8d5e5b6d8266e2b86dea47"


def test_manifest_shared_vector_and_empty_dir_equals_missing(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    (tmp_path / "leer").mkdir()
    assert core.manifest_version(tmp_path, ["leer", "b.txt", "a.txt"]) == SHARED_MANIFEST_VECTOR
    assert core.manifest_version(tmp_path, ["a.txt", "b.txt", "leer"]) == SHARED_MANIFEST_VECTOR
    (tmp_path / "leer").rmdir()  # fehlender Ordner: derselbe Hash
    assert core.manifest_version(tmp_path, ["leer", "b.txt", "a.txt"]) == SHARED_MANIFEST_VECTOR


def _commit_version(conn, version, *, inflight=False, worker=SERVER, now=T0):
    ack = _acq(conn, worker=worker, now=now).payload
    res = _renew(conn, ack, now + timedelta(seconds=5), resource_version=version, inflight=inflight)
    assert res.granted
    _release(conn, ack, now + timedelta(seconds=6))


def test_rebaseline_only_server_role_without_open_inflight(conn):
    _commit_version(conn, V1)
    t = T0 + timedelta(seconds=30)
    # Externer Edit: lokales Manifest V2 weicht ab. Ohne rebaseline: wie bisher abgelehnt
    assert _acq(conn, resource_version=V2, now=t).payload["reason"] == "stale_resource_version"
    # Server mit rebaseline: uebernimmt den lokalen Stand, Ereignis + Status
    ok = _acq(conn, resource_version=V2, rebaseline=True, now=t).payload
    assert ok["granted"] and ok["resource_version"] == V2
    status = read_resource_lease(conn, RES, now=t + timedelta(seconds=1), config=CFG).payload
    assert status["last_rebaseline_at"] and status["version_inflight"] is False
    ev = [e for e in list_events(conn, RES) if e["action"] == "rebaseline_external_change"]
    assert len(ev) == 1 and json.loads(ev[0]["detail"])["previous_version"] == V1
    assert json.loads(ev[0]["detail"])["new_version"] == V2


def test_rebaseline_is_ignored_for_standby_and_blocked_by_open_inflight(conn):
    _commit_version(conn, V1)
    # Standby: rebaseline wirkt nicht (exakter Abgleich bleibt)
    t = T0 + timedelta(seconds=300)
    standby = _acq(conn, worker=STANDBY, resource_version=V2, rebaseline=True, now=t)
    assert standby.payload["reason"] in ("stale_resource_version", "server_active")
    # Offener In-flight-Marker blockiert auch den Server
    first = _acq(conn, now=t + timedelta(seconds=1), resource_version=V1).payload
    _renew(conn, first, t + timedelta(seconds=2), resource_version=V2, inflight=True)
    blocked = _acq(conn, resource_version="c" * 64, rebaseline=True, now=t + timedelta(seconds=200))
    assert blocked.payload["reason"] == "inflight_open"
    # R29-2: die Ablehnung verraet dem Standby, dass ein In-flight-Marker offen ist (Journal fehlt lokal)
    stale = _acq(conn, resource_version="c" * 64, now=t + timedelta(seconds=201))
    assert stale.payload["reason"] == "stale_resource_version" and stale.payload["version_inflight"] is True
    # Recovery (Version = In-flight-Marker) wird weiter exakt akzeptiert; Commit raeumt das Flag
    recovered = _acq(conn, resource_version=V2, now=t + timedelta(seconds=210)).payload
    assert recovered["granted"]
    _renew(conn, recovered, t + timedelta(seconds=215), resource_version="d" * 64)  # Commit-Marker
    assert read_resource_lease(conn, RES, now=t + timedelta(seconds=216), config=CFG).payload["version_inflight"] is False


def test_rebaseline_over_http(client_for_rebaseline):
    client, ref = client_for_rebaseline
    r = client.post(f"/api/resources/{RES}/lease", json={**ref, "resource_version": V1})
    assert r.status_code == 200
    ack = r.json()
    body = {"lease_id": ack["lease_id"], "fence": ack["fence"]}
    assert client.post(f"/api/resources/{RES}/lease/renew",
                       json={**body, "resource_version": V1, "inflight": False}).status_code == 200
    assert client.post(f"/api/resources/{RES}/lease/release", json=body).status_code == 200
    r = client.post(f"/api/resources/{RES}/lease", json={**ref, "resource_version": V2})
    assert r.json()["reason"] == "stale_resource_version"
    r = client.post(f"/api/resources/{RES}/lease", json={**ref, "resource_version": V2, "rebaseline": True})
    assert r.status_code == 200 and r.json()["resource_version"] == V2


@pytest.fixture
def client_for_rebaseline(db_path, tmp_path, monkeypatch):
    import gui.server as srv
    monkeypatch.setattr(srv, "BACH_DB", db_path)
    monkeypatch.setattr(srv, "USER_DB", db_path)
    monkeypatch.setattr(srv, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(srv, "BACH_DIR", tmp_path)
    monkeypatch.setattr(srv, "GUI_DIR", tmp_path / "gui")
    monkeypatch.setattr(srv, "validate_token",
                        lambda token: {"id": 1, "name": "test-device"} if token == "star-fixture" else None)
    http = TestClient(srv.app, raise_server_exceptions=False, headers={"Authorization": "Bearer star-fixture"})
    return http, {"worker_id": SERVER, "host": "mac-studio", "request_id": _rid()}
