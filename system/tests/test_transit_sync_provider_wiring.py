# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""TRANSFER-07 (MODULRUECKTRANSFER Stufe 7): sqlite-transit-sync-Verdrahtung.

Gepruefte Vertragspunkte:
1. Rollback-Schalter BACH_USE_EXTERNAL_TRANSITSYNC=0 (Plan-Regel 4.1).
2. Probe via find_spec (kein Import), Factory fail-closed bei Vertragsbruch.
3. Engine-Adapter gegen das reale Modul: Push/Pull, LWW-Konfliktloesung,
   State-Gate (Re-Pull = No-op), State ausserhalb des Transit-Verzeichnisses.
4. Verdrahtung: DBSyncManager.sync_on_start / sync_on_exit / sync routen
   ueber die Engine; Legacy-Pfad bleibt unter Rollback unveraendert.
5. Lokale 3-Wege-Simulation (WORKSTATION-LG, ASUS-GEI, mac-studio) als
   Ersatznachweis, bis der echte Multi-Host-Lauf (Task 1223 Restschritt)
   auf allen drei Geraeten stattfinden kann.
6. AST-Waechter gegen Code-Drift und Re-Monolithisierung.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

import pytest

BACH_ROOT = Path(__file__).resolve().parent.parent
if str(BACH_ROOT) not in sys.path:
    sys.path.insert(0, str(BACH_ROOT))

from hub import transit_sync_provider as tsp
from hub.db_sync import DBSyncManager

try:
    import sqlite_transit_sync  # noqa: F401

    HAS_EXTERNAL = True
except ImportError:
    HAS_EXTERNAL = False


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv(tsp.ROLLBACK_ENV_VAR, raising=False)
    yield


def _mkdb(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tasks ("
        "id INTEGER PRIMARY KEY, title TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS secrets ("
        "id INTEGER PRIMARY KEY, key TEXT, value TEXT)"
    )
    return conn


def _engine(tmp_path: Path, node: str, transit: Path):
    db = tmp_path / f"{node}.db"
    if not db.exists():
        _mkdb(db).close()
    return tsp.create_external_engine(
        db_path=db,
        transit_dir=transit,
        local_bach_dir=tmp_path / f"state_{node}",
        node_id=node,
    )


def _rows(db: Path):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute("SELECT id, title FROM tasks ORDER BY id").fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Rollback-Schalter (Plan-Regel 4.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " 0 "])
def test_probe_rollback_env_forces_legacy(monkeypatch, value):
    monkeypatch.setenv(tsp.ROLLBACK_ENV_VAR, value)
    provider = tsp.probe_transit_sync_provider()
    assert provider.external is False
    assert provider.module is None
    assert "rollback" in provider.reason


@pytest.mark.skipif(not HAS_EXTERNAL, reason="sqlite-transit-sync nicht installiert")
def test_probe_external_when_installed():
    provider = tsp.probe_transit_sync_provider()
    assert provider.external is True
    assert provider.module == tsp.EXTERNAL_MODULE


def test_probe_missing_module(monkeypatch):
    monkeypatch.setattr(tsp.importlib.util, "find_spec", lambda name: None)
    provider = tsp.probe_transit_sync_provider()
    assert provider.external is False
    assert tsp.EXTERNAL_DIST in provider.reason


@pytest.mark.skipif(not HAS_EXTERNAL, reason="sqlite-transit-sync nicht installiert")
def test_probe_rollback_wins_over_installed(monkeypatch):
    monkeypatch.setenv(tsp.ROLLBACK_ENV_VAR, "0")
    provider = tsp.probe_transit_sync_provider()
    assert provider.external is False


def test_if_active_returns_none_under_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv(tsp.ROLLBACK_ENV_VAR, "0")
    engine = tsp.create_external_engine_if_active(
        db_path=tmp_path / "x.db",
        transit_dir=tmp_path / "transit",
        local_bach_dir=tmp_path / "state",
    )
    assert engine is None


# ---------------------------------------------------------------------------
# 2. Factory fail-closed (Vertragsbruch)
# ---------------------------------------------------------------------------


def test_factory_fail_closed_on_contract_violation(monkeypatch, tmp_path):
    class BrokenModule:
        SyncConfig = object  # TransitSync, MergeReport, Snapshot fehlen

    monkeypatch.setattr(tsp, "load_external_transit_sync", lambda: BrokenModule)
    with pytest.raises(tsp.TransitSyncContractError) as excinfo:
        tsp.create_external_engine(
            db_path=tmp_path / "x.db",
            transit_dir=tmp_path / "transit",
            local_bach_dir=tmp_path / "state",
        )
    assert "TransitSync" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. Engine-Adapter gegen das reale Modul
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_EXTERNAL, reason="sqlite-transit-sync nicht installiert")
def test_engine_state_outside_transit(tmp_path):
    transit = tmp_path / "transit"
    transit.mkdir()
    engine = _engine(tmp_path, "mac-studio", transit)
    state_file = tmp_path / "state_mac-studio" / tsp.STATE_DIR_NAME / tsp.STATE_FILE_NAME
    # SyncConfig-Hardinvariante: State niemals im Transit (Klartext-Replica-Schutz)
    assert transit not in Path(engine._config.state).parents
    engine.push()
    # Modul-Detail: State wird erst bei einem realen Merge persistiert,
    # das State-Verzeichnis bereits beim Engine-Aufbau angelegt.
    assert state_file.parent.is_dir()
    peer = _engine(tmp_path, "ASUS-GEI", transit)
    peer.pull()
    peer_state = tmp_path / "state_ASUS-GEI" / tsp.STATE_DIR_NAME / tsp.STATE_FILE_NAME
    assert peer_state.exists()
    assert transit not in peer_state.parents


@pytest.mark.skipif(not HAS_EXTERNAL, reason="sqlite-transit-sync nicht installiert")
def test_engine_push_pull_lww_and_noop(tmp_path):
    transit = tmp_path / "transit"
    transit.mkdir()

    # Node A publiziert, Node B merged
    engine_a = _engine(tmp_path, "mac-studio", transit)
    conn = sqlite3.connect(str(tmp_path / "mac-studio.db"))
    conn.execute("INSERT INTO tasks VALUES (1, 'von A', '2026-09-12T10:00:00')")
    conn.commit()
    conn.close()
    snapshot_a = engine_a.push()
    assert snapshot_a.endswith(".sqlite-snapshot")

    engine_b = _engine(tmp_path, "WORKSTATION-LG", transit)
    assert engine_b.pending() == [snapshot_a]
    changed, names = engine_b.pull()
    assert names == [snapshot_a]
    assert changed == 1
    assert _rows(tmp_path / "WORKSTATION-LG.db") == [(1, "von A")]

    # B gewinnt den LWW-Konflikt (neuerer Timestamp), A uebernimmt
    conn = sqlite3.connect(str(tmp_path / "WORKSTATION-LG.db"))
    conn.execute(
        "UPDATE tasks SET title='von B', updated_at='2026-09-12T11:00:00' WHERE id=1"
    )
    conn.commit()
    conn.close()
    engine_b.push()
    changed, _ = engine_a.pull()
    assert changed == 1
    assert _rows(tmp_path / "mac-studio.db") == [(1, "von B")]

    # State-Gate: wiederholter Pull ist ein No-op (kein Replay)
    assert engine_a.pull() == (0, [])


@pytest.mark.skipif(not HAS_EXTERNAL, reason="sqlite-transit-sync nicht installiert")
def test_engine_snapshot_excludes_secrets(tmp_path):
    transit = tmp_path / "transit"
    transit.mkdir()
    engine_a = _engine(tmp_path, "mac-studio", transit)
    conn = sqlite3.connect(str(tmp_path / "mac-studio.db"))
    conn.execute("INSERT INTO secrets VALUES (1, 'api', 'GEHEIM')")
    conn.execute("INSERT INTO tasks VALUES (1, 'oeffentlich', '2026-09-12T10:00:00')")
    conn.commit()
    conn.close()
    engine_a.push()

    engine_b = _engine(tmp_path, "ASUS-GEI", transit)
    engine_b.pull()
    conn = sqlite3.connect(str(tmp_path / "ASUS-GEI.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. DBSyncManager-Verdrahtung
# ---------------------------------------------------------------------------


class _FakeEngine:
    node_id = "test-node"

    def __init__(self):
        self.calls = []

    def pending(self):
        return []

    def pull(self):
        self.calls.append("pull")
        return 3, ["snap-1"]

    def push(self):
        self.calls.append("push")
        return "snap-out"

    def sync(self):
        self.calls.append("sync")
        return True, "externer Sync"


@pytest.fixture
def manager(tmp_path, monkeypatch):
    db = tmp_path / ".bach" / "bach.db"
    db.parent.mkdir(parents=True)
    _mkdb(db).close()
    transit = tmp_path / "transit"
    transit.mkdir()
    mgr = DBSyncManager(db_path=db, transit_dir=transit)
    mgr.local_bach_dir = tmp_path / ".bach"
    mgr.base_path = tmp_path / "system"
    mgr.base_path.mkdir()
    return mgr


def test_manager_routes_start_exit_sync_via_engine(manager):
    fake = _FakeEngine()
    manager._external_engine = fake
    manager._external_probed = True

    ok, msg = manager.sync_on_start()
    assert ok and "TransitSync Pull: 3 Zeilen" in msg

    ok, msg = manager.sync_on_exit()
    assert ok and msg == "TransitSync Push: snap-out"

    ok, msg = manager.sync(auto_confirm=True)
    assert ok and msg == "externer Sync"
    assert fake.calls == ["pull", "push", "sync"]


def test_manager_surfaces_engine_error(manager):
    class Boom:
        def pull(self):
            raise OSError("transit nicht erreichbar")

    manager._external_engine = Boom()
    manager._external_probed = True
    ok, msg = manager.sync_on_start()
    assert ok is False
    assert "TransitSync Pull fehlgeschlagen" in msg


def test_manager_legacy_path_under_rollback(manager, monkeypatch):
    monkeypatch.setenv(tsp.ROLLBACK_ENV_VAR, "0")
    assert manager._get_external_engine() is None
    ok, msg = manager.sync_on_exit()
    assert ok and "ProSync Push" in msg


def test_manager_contract_violation_is_fail_closed_visible(manager, monkeypatch):
    def _broken(**kwargs):
        raise tsp.TransitSyncContractError("vertrag gebrochen")

    monkeypatch.setattr(
        "hub.transit_sync_provider.create_external_engine_if_active", _broken
    )
    assert manager._get_external_engine() is None
    assert "vertrag gebrochen" in manager._external_error
    assert "deaktiviert" in manager.get_status()


def test_manager_status_shows_external_engine(manager):
    manager._external_engine = _FakeEngine()
    manager._external_probed = True
    status = manager.get_status()
    assert "sqlite-transit-sync (extern" in status


# ---------------------------------------------------------------------------
# 5. Lokale 3-Wege-Simulation (Ersatznachweis fuer den Multi-Host-Lauf)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_EXTERNAL, reason="sqlite-transit-sync nicht installiert")
def test_three_way_convergence_simulation(tmp_path):
    """Drei simulierte Hosts ueber einem gemeinsamen Transit-Verzeichnis.

    Jeder Host schreibt eigene Zeilen, danach ziehen alle gegenseitig.
    Erwartung (Plan Stufe 7): konfliktfreie Konvergenz - alle drei Knoten
    sehen am Ende denselben Zeilenbestand, ohne Duplikate und ohne dass
    ein Knoten seine eigenen Snapshots re-importiert.
    """
    transit = tmp_path / "transit"
    transit.mkdir()
    hosts = ["WORKSTATION-LG", "ASUS-GEI", "mac-studio"]
    engines = {host: _engine(tmp_path, host, transit) for host in hosts}

    for i, host in enumerate(hosts, start=1):
        conn = sqlite3.connect(str(tmp_path / f"{host}.db"))
        conn.execute(
            "INSERT INTO tasks VALUES (?, ?, ?)",
            (i, f"task-von-{host}", f"2026-09-12T0{i}:00:00"),
        )
        conn.commit()
        conn.close()
        engines[host].push()

    expected = sorted((i, f"task-von-{host}") for i, host in enumerate(hosts, 1))
    for host in hosts:
        changed, names = engines[host].pull()
        assert len(names) == 2  # nur die beiden fremden Snapshots
        assert changed == 2
        rows = sorted(_rows(tmp_path / f"{host}.db"))
        assert rows == expected
        # Konvergenz stabil: Zweitpull ist fuer alle ein No-op
        assert engines[host].pull() == (0, [])


# ---------------------------------------------------------------------------
# 6. AST-Waechter (Code-Drift, Re-Monolithisierung, Unabhaengigkeit)
# ---------------------------------------------------------------------------


def _source(rel: str) -> str:
    return (BACH_ROOT / rel).read_text(encoding="utf-8")


def test_guard_db_sync_wires_provider():
    src = _source("hub/db_sync.py")
    assert "transit_sync_provider" in src
    assert "_get_external_engine" in src


def test_guard_provider_lazy_import_only():
    tree = ast.parse(_source("hub/transit_sync_provider.py"))
    for node in tree.body:  # nur Modulebene
        if isinstance(node, ast.Import):
            assert all(alias.name != tsp.EXTERNAL_MODULE for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "") != tsp.EXTERNAL_MODULE


def test_guard_no_direct_external_import_in_hub():
    for path in (BACH_ROOT / "hub").glob("*.py"):
        if path.name in {"transit_sync_provider.py"}:
            continue
        src = path.read_text(encoding="utf-8")
        assert f"import {tsp.EXTERNAL_MODULE}" not in src, path.name
        assert f"from {tsp.EXTERNAL_MODULE}" not in src, path.name


def test_guard_core_stays_independent():
    for path in (BACH_ROOT / "core").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "transit_sync_provider" not in src, path.name
        assert tsp.EXTERNAL_MODULE not in src, path.name


def test_guard_rollback_env_documented():
    src = _source("hub/transit_sync_provider.py")
    assert tsp.ROLLBACK_ENV_VAR in src
    plan = (BACH_ROOT.parent / "docs/architecture/MODULRUECKTRANSFER-PLAN.md")
    assert tsp.ROLLBACK_ENV_VAR in plan.read_text(encoding="utf-8")


def test_guard_requirements_pin():
    requirements = (BACH_ROOT.parent / "requirements.txt").read_text(encoding="utf-8")
    assert f"{tsp.EXTERNAL_DIST} @ git+" in requirements
