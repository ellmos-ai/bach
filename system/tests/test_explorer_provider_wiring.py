# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""TRANSFER-05 (MODULRUECKTRANSFER Stufe 5): system-explorer-Verdrahtung.

Gepruefte Vertragspunkte:
1. Rollback-Schalter BACH_USE_EXTERNAL_EXPLORER=0 (Plan-Regel 4.1).
2. Native Audits (hub/system_audit.py): Ports, Zombies, Locks - unabhaengig
   vom externen Modul.
3. Adapter-Factory + begrenzter Topologie-Scan (fail-closed, Temp-Store).
4. Verdrahtung: setup preflight + upgrade --check (JSON & Text, Drift).
5. AST-Waechter gegen Code-Drift und Re-Monolithisierung.
"""
from __future__ import annotations

import ast
import json
import os
import socket
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACH_ROOT = Path(__file__).resolve().parent.parent
if str(BACH_ROOT) not in sys.path:
    sys.path.insert(0, str(BACH_ROOT))

from hub import system_audit
from hub.explorer_provider import (
    BUDGET_ENV_VAR,
    EXTERNAL_DIST,
    EXTERNAL_MODULE,
    ROLLBACK_ENV_VAR,
    create_external_topology_scanner,
    probe_explorer_provider,
    render_topology_evidence_lines,
    topology_evidence,
)

try:
    import system_explorer  # noqa: F401

    HAS_EXTERNAL = True
except ImportError:
    HAS_EXTERNAL = False


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    monkeypatch.delenv(ROLLBACK_ENV_VAR, raising=False)
    monkeypatch.delenv(BUDGET_ENV_VAR, raising=False)
    yield


# ---------------------------------------------------------------------------
# 1. Rollback-Schalter (Plan-Regel 4.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " 0 "])
def test_probe_rollback_env_forces_legacy(monkeypatch, value):
    monkeypatch.setenv(ROLLBACK_ENV_VAR, value)
    provider = probe_explorer_provider()
    assert provider.external is False
    assert provider.name == "bach-legacy"
    assert ROLLBACK_ENV_VAR in provider.reason


def test_probe_external_when_installed(monkeypatch):
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda name: object() if name == EXTERNAL_MODULE else None
    )
    provider = probe_explorer_provider()
    assert provider.external is True
    assert provider.module == EXTERNAL_MODULE


def test_probe_missing_module(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    provider = probe_explorer_provider()
    assert provider.external is False
    assert EXTERNAL_DIST in provider.reason


def test_probe_rollback_wins_over_installed(monkeypatch):
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda name: object() if name == EXTERNAL_MODULE else None
    )
    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    assert probe_explorer_provider().external is False


# ---------------------------------------------------------------------------
# 2. Native Audits: Ports, Zombies, Locks (unabhaengig vom Modul)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_audit_ports_free():
    port = _free_port()
    findings = system_audit.audit_ports([port])
    assert findings[0].state == "free"


def test_audit_ports_occupied_by_test_process():
    port = _free_port()
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(1)
    try:
        findings = system_audit.audit_ports([port])
        assert findings[0].state != "free"
        if findings[0].pid is not None:
            assert findings[0].pid == os.getpid()
    finally:
        server.close()


def test_audit_zombies_via_fake_process_iter(monkeypatch):
    if system_audit.psutil is None:
        pytest.skip("psutil nicht verfuegbar")

    def fake_iter(*_args, **_kwargs):
        return [
            SimpleNamespace(info={
                "pid": 111, "ppid": 1, "name": "zombA", "status": "zombie",
                "cmdline": ["/x/services/bach/system/gui/server.py"],
            }),
            SimpleNamespace(info={
                "pid": 222, "ppid": 1, "name": "alive", "status": "running",
                "cmdline": ["python"],
            }),
        ]

    monkeypatch.setattr(system_audit.psutil, "STATUS_ZOMBIE", "zombie", raising=False)
    findings = system_audit.audit_zombies(process_iter=fake_iter())
    assert len(findings) == 1
    assert findings[0].pid == 111
    assert findings[0].bach_related is True


def test_audit_locks_states(tmp_path, monkeypatch):
    # Deterministisch statt ueber os.getpid(): macOS liefert bei
    # psutil.cmdline() den aufgeloesten Interpreter-Pfad (Homebrew-
    # Framework), der keine BACH-Marker enthaelt -> 'live' waere je nach
    # Umgebung nicht reproduzierbar. Der Klassifikations-Status wird
    # daher ueber _pid_bach_states gestubb und deckt alle 4 Zustaende ab.
    (tmp_path / "daemon.pid").write_text("111", encoding="utf-8")
    (tmp_path / "stale.lock").write_text("222", encoding="utf-8")
    (tmp_path / "foreign.lock").write_text("333", encoding="utf-8")
    (tmp_path / "broken.pid").write_text("not-a-pid", encoding="utf-8")
    pid_states = {111: (True, True), 222: (False, False), 333: (True, False)}
    monkeypatch.setattr(
        system_audit, "_pid_bach_states",
        lambda pids: [pid_states[pid] for pid in pids],
    )
    findings = {f.path.name: f for f in system_audit.audit_locks(data_dir=tmp_path)}
    assert findings["daemon.pid"].state == "live"
    assert findings["daemon.pid"].kind == "pid"
    assert findings["stale.lock"].state == "stale"
    assert findings["foreign.lock"].state == "foreign"
    assert findings["broken.pid"].state == "unparseable"


def test_audit_locks_json_compute_lock(tmp_path):
    (tmp_path / "compute_active.lock").write_text(
        json.dumps({"pids": [2147483647, 2147483646]}), encoding="utf-8"
    )
    findings = system_audit.audit_locks(data_dir=tmp_path)
    assert findings[0].state == "stale"
    assert findings[0].kind == "lock"


def test_render_audit_lines_fail_on_foreign_port():
    port_lines = system_audit.render_audit_lines(
        [system_audit.PortFinding(port=8000, label="GUI-Server", state="foreign",
                                  pid=4711, process_name="node")],
        [], [],
    )
    assert port_lines[0][0] == "FAIL"
    assert "8000" in port_lines[0][1] and "fremden" in port_lines[0][1]


def test_render_audit_lines_ok_states():
    lines = system_audit.render_audit_lines(
        [system_audit.PortFinding(port=8000, label="GUI-Server", state="bach",
                                  pid=123, process_name="Python")],
        [], [],
    )
    assert lines[0][0] == "OK"
    assert "belegt durch BACH" in lines[0][1]


# ---------------------------------------------------------------------------
# 3. Adapter-Factory + Topologie-Scan (nur mit installiertem Modul)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_EXTERNAL, reason="system-explorer nicht installiert")
def test_factory_scan_on_fixture_tree(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: test-skill\n---\nInhalt\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    scanner = create_external_topology_scanner(root=tmp_path, time_budget_seconds=10)
    report = scanner.scan()
    assert report["adapter"] == EXTERNAL_DIST
    assert report["stats"]["files"] >= 3
    assert report["nodes"]
    assert report["duration_seconds"] >= 0
    # Temp-Store aufgeraeumt
    assert not list(tmp_path.parent.glob("bach_topology_*.db"))


def test_factory_fail_closed_on_contract_violation(monkeypatch):
    import hub.explorer_provider as provider_mod

    monkeypatch.setattr(provider_mod, "load_external_explorer", lambda: SimpleNamespace())
    # Auch den Submodul-Import stubben: sonst laedt die Factory die wirklich
    # installierten Submodule (Contract erfuellt) und es kaeme kein Fehler.
    monkeypatch.setattr(
        provider_mod.importlib, "import_module", lambda name: SimpleNamespace()
    )
    with pytest.raises(AttributeError, match="contract violation"):
        create_external_topology_scanner(root=Path("."))


def test_topology_evidence_disabled_and_error(tmp_path, monkeypatch):
    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    evidence = topology_evidence(tmp_path, state_dir=tmp_path / "s")
    assert evidence == {"enabled": False, "reason": evidence["reason"]}
    assert ROLLBACK_ENV_VAR in evidence["reason"]

    class _Boom:
        def scan(self):
            raise RuntimeError("budget")

    monkeypatch.delenv(ROLLBACK_ENV_VAR)
    monkeypatch.setattr(
        provider_mod_probe := "hub.explorer_provider.probe_explorer_provider",
        lambda: SimpleNamespace(external=True, reason="x"),
    )
    monkeypatch.setattr(
        "hub.explorer_provider.create_external_topology_scanner",
        lambda root, time_budget_seconds=None: _Boom(),
    )
    evidence = topology_evidence(tmp_path, state_dir=tmp_path / "s")
    assert evidence["enabled"] is True
    assert "budget" in evidence["error"]


@pytest.mark.skipif(not HAS_EXTERNAL, reason="system-explorer nicht installiert")
def test_topology_evidence_drift(tmp_path):
    (tmp_path / "tree" / "docs").mkdir(parents=True)
    (tmp_path / "tree" / "docs" / "a.md").write_text("# A\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    first = topology_evidence(
        tmp_path / "tree", state_dir=state_dir, persist_state=True, time_budget_seconds=10
    )
    assert first["enabled"] is True
    assert "drift" not in first  # kein frueherer Stand
    second = topology_evidence(
        tmp_path / "tree", state_dir=state_dir, persist_state=True, time_budget_seconds=10
    )
    assert second.get("drift") == []  # identisch -> keine Drift-Zeilen
    (tmp_path / "tree" / "docs" / "b.md").write_text("# B\n", encoding="utf-8")
    third = topology_evidence(
        tmp_path / "tree", state_dir=state_dir, persist_state=True, time_budget_seconds=10
    )
    assert any("files:" in line for line in third["drift"])


def test_render_topology_evidence_lines():
    info = render_topology_evidence_lines({"enabled": False, "reason": "nicht installiert"})
    assert info == ["  [INFO] Topologie-Scan: deaktiviert (nicht installiert)"]
    warn = render_topology_evidence_lines({"enabled": True, "error": "boom"})
    assert warn[0].startswith("  [WARN] Topologie-Scan:")
    ok = render_topology_evidence_lines({
        "enabled": True,
        "report": {"version": "9.9", "duration_seconds": 0.1,
                   "stats": {"files": 5}, "nodes": {"skill": 2}},
        "drift": ["files: 4 -> 5"],
    })
    assert ok[0].startswith("  [OK] Topologie-Scan (system-explorer v9.9)")
    assert "2 Skills" in ok[0]
    assert any("files: 4 -> 5" in line for line in ok[1:])


# ---------------------------------------------------------------------------
# 4. Verdrahtung: preflight + upgrade --check
# ---------------------------------------------------------------------------


def test_preflight_contains_audit_and_topology():
    from hub.setup import SetupHandler

    ok, output = SetupHandler(BACH_ROOT)._preflight([])
    assert "System- & Topologie-Audit:" in output
    assert "Port 8000" in output and "Port 8081" in output
    assert "Zombie-Prozesse" in output
    assert "Topologie-Scan" in output
    assert "Pre-Flight Checks:" in output  # Basis-Checks unveraendert


def test_preflight_topology_disabled_under_rollback(monkeypatch):
    from hub.setup import SetupHandler

    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    ok, output = SetupHandler(BACH_ROOT)._preflight([])
    assert "Topologie-Scan: deaktiviert" in output
    assert ROLLBACK_ENV_VAR in output


def test_upgrade_check_json_has_topology(tmp_path, monkeypatch):
    from hub.upgrade import UpgradeHandler

    # Isolierte Upgrade-DB mit dist-Schema: die Produktiv-DB dieser
    # Testumgebung kann das dist_file_versions-Schema fehlen (OperationalError
    # waere die Folge). Der JSON-Pfad von _check_updates soll aber echt
    # geprueft werden statt geskippt zu werden.
    db_path = tmp_path / "upgrade_test.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE dist_file_versions (
                file_path TEXT, version TEXT, file_hash TEXT,
                dist_type TEXT, created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE distribution_releases (
                version TEXT, release_date TEXT, status TEXT, is_stable INTEGER
            )
        """)
        conn.commit()
    finally:
        conn.close()

    handler = UpgradeHandler(BACH_ROOT)
    monkeypatch.setattr(handler, "db_path", db_path)

    monkeypatch.setattr(
        "hub.upgrade.topology_evidence",
        lambda base_path, **kwargs: {"enabled": False, "reason": "unit-test stub"},
    )
    ok, payload = handler._check_updates(json_output=True)
    data = json.loads(payload)
    assert data["topology"]["reason"] == "unit-test stub"
    assert data["no_tracked_versions"] is True


def test_upgrade_topology_payload_helper(tmp_path, monkeypatch):
    from hub.upgrade import UpgradeHandler

    monkeypatch.setattr(
        "hub.upgrade.topology_evidence",
        lambda base_path, **kwargs: {"enabled": True, "error": "scan failed: test"},
    )
    payload = UpgradeHandler(BACH_ROOT)._topology_evidence_payload()
    assert payload["enabled"] is True and "test" in payload["error"]


# ---------------------------------------------------------------------------
# 5. AST-Waechter (Code-Drift, Re-Monolithisierung, Unabhaengigkeit)
# ---------------------------------------------------------------------------


def _source(rel: str) -> str:
    return (BACH_ROOT / rel).read_text(encoding="utf-8")


def test_guard_setup_wires_audit_and_explorer():
    src = _source("hub/setup.py")
    assert "system_audit" in src
    assert "explorer_provider" in src


def test_guard_upgrade_wires_explorer():
    src = _source("hub/upgrade.py")
    assert "from hub.explorer_provider import" in src
    assert "topology_evidence" in src


def test_guard_system_audit_stays_independent():
    src = _source("hub/system_audit.py")
    assert "system_explorer" not in src.replace("system_audit", "")


def test_guard_explorer_provider_lazy_import_only():
    tree = ast.parse(_source("hub/explorer_provider.py"))
    for node in tree.body:  # nur Modulebene
        if isinstance(node, ast.Import):
            assert all(alias.name != EXTERNAL_MODULE for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "") != EXTERNAL_MODULE


def test_guard_no_direct_explorer_import_in_hub():
    for path in (BACH_ROOT / "hub").glob("*.py"):
        if path.name in {"explorer_provider.py"}:
            continue
        src = path.read_text(encoding="utf-8")
        assert "import system_explorer" not in src, path.name
        assert f"from {EXTERNAL_MODULE}" not in src, path.name


def test_guard_topology_budget_env_documented():
    src = _source("hub/explorer_provider.py")
    assert BUDGET_ENV_VAR in src and ROLLBACK_ENV_VAR in src