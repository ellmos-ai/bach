# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""TRANSFER-03 (MODULRUECKTRANSFER-PLAN Stufe 3): Provider-Seam-Verdrahtung.

Geprueft werden fuenf Vertragspunkte der ellmos-scheduler-Integration:
1. Rollback-Schalter BACH_USE_EXTERNAL_SCHEDULER=0 (Plan-Regel 4.1): probe
   meldet Legacy, explizite external-Befehle schlagen fail-closed fehl.
2. Adapter-Factory-Contract: create_external_scheduler_adapter delegiert an
   ellmos_scheduler.create_bach_adapter und scheitert laut bei Vertragsbruch.
3. Handler-Dispatch (status/jobs/verify) mit Stub-Adapter: Ausgabeformate,
   Dry-Run-Default, --apply, Fail-Closed ohne externen Provider.
4. Integration (nur wenn ellmos_scheduler installiert ist): echte Migration
   einer Fixture-Legacy-DB -- Intervall/Cron gemappt, chain/manual/event mit
   explizitem Grund uebersprungen, idempotentes --apply, Tick-Ausfuehrung
   im Sandbox-Store (Daemon-Faehigkeit), Legacy-Lesepfade unberuehrt.
5. AST-Waechter: kein hub-Modell importiert ellmos_scheduler direkt; nur der
   Provider-Seam bildet die Importgrenze (Re-Monolithisierungs-Schutz).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BACH_ROOT = Path(__file__).resolve().parent.parent
if str(BACH_ROOT) not in sys.path:
    sys.path.insert(0, str(BACH_ROOT))

from hub import scheduler as scheduler_module
from hub.scheduler import SchedulerHandler
from hub.scheduler_provider import (
    ADAPTER_FACTORY,
    EXTERNAL_MODULE,
    ROLLBACK_ENV_VAR,
    create_external_scheduler_adapter,
    probe_scheduler_provider,
)

try:
    import ellmos_scheduler  # noqa: F401

    HAS_EXTERNAL = True
except ImportError:  # pragma: no cover - Umgebung ohne Modul
    HAS_EXTERNAL = False

pytestmark = pytest.mark.usefixtures("_reset_external_env")


@pytest.fixture(autouse=True)
def _reset_external_env(monkeypatch):
    """Rollback- und State-DB-Schalter deterministisch halten."""
    monkeypatch.delenv(ROLLBACK_ENV_VAR, raising=False)
    monkeypatch.delenv("BACH_EXTERNAL_SCHEDULER_DB", raising=False)
    yield


# ---------------------------------------------------------------------------
# 1. Provider-Probe und Rollback-Schalter (Plan-Regel 4.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " 0 "])
def test_probe_rollback_env_forces_legacy(monkeypatch, value):
    monkeypatch.setenv(ROLLBACK_ENV_VAR, value)
    provider = probe_scheduler_provider()
    assert provider.external is False
    assert provider.name == "bach-legacy"
    assert provider.module is None
    assert "rollback" in provider.reason
    assert ROLLBACK_ENV_VAR in provider.reason


def test_probe_prefers_external_without_rollback():
    with patch("hub.scheduler_provider.importlib.util.find_spec", return_value=object()):
        provider = probe_scheduler_provider()
    assert provider.external is True
    assert provider.name == "ellmos-scheduler"
    assert provider.module == EXTERNAL_MODULE


def test_probe_rollback_env_overrides_importable_module(monkeypatch):
    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    with patch("hub.scheduler_provider.importlib.util.find_spec", return_value=object()):
        provider = probe_scheduler_provider()
    assert provider.external is False


# ---------------------------------------------------------------------------
# 2. Adapter-Factory-Contract (fail-closed, kein stiller Fallback)
# ---------------------------------------------------------------------------


def test_create_adapter_delegates_to_module_factory(monkeypatch):
    seen = {}

    class FakeAdapter:
        pass

    fake_module = SimpleNamespace(
        **{
            ADAPTER_FACTORY: lambda state_db: (seen.__setitem__("db", state_db), FakeAdapter())[1]
        }
    )
    monkeypatch.setitem(sys.modules, EXTERNAL_MODULE, fake_module)
    adapter = create_external_scheduler_adapter("/tmp/state.db")
    assert isinstance(adapter, FakeAdapter)
    assert seen["db"] == "/tmp/state.db"


def test_create_adapter_fails_closed_on_missing_factory(monkeypatch):
    monkeypatch.setitem(sys.modules, EXTERNAL_MODULE, SimpleNamespace())
    with pytest.raises(AttributeError, match=ADAPTER_FACTORY):
        create_external_scheduler_adapter("/tmp/state.db")


# ---------------------------------------------------------------------------
# 3. Handler-Dispatch: Fail-Closed, Stub-Ausgaben, Dry-Run/Apply
# ---------------------------------------------------------------------------


def _make_handler() -> SchedulerHandler:
    return SchedulerHandler(BACH_ROOT)


def test_external_gate_fails_closed_without_module():
    handler = _make_handler()
    with patch("hub.scheduler_provider.importlib.util.find_spec", return_value=None):
        ok, out = handler.handle("external", ["status"])
    assert ok is False
    assert "Externer Scheduler nicht verfuegbar" in out
    assert "nicht installiert" in out


def test_external_gate_reports_rollback_hint(monkeypatch):
    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    handler = _make_handler()
    ok, out = handler.handle("external", ["verify"])
    assert ok is False
    assert "Externer Scheduler nicht verfuegbar" in out
    assert ROLLBACK_ENV_VAR in out
    assert "Rollback aktiv" in out


def test_external_help_works_without_provider(monkeypatch):
    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    handler = _make_handler()
    ok, out = handler.handle("external", ["help"])
    assert ok is True
    for token in ("status", "jobs", "verify", "--apply", ROLLBACK_ENV_VAR):
        assert token in out


def test_external_state_db_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "custom.db"))
    handler = _make_handler()
    assert handler._external_state_db() == (tmp_path / "custom.db").resolve()


def test_external_state_db_default_is_isolated_from_legacy_store():
    handler = _make_handler()
    state_db = handler._external_state_db()
    assert state_db.parent.name == "scheduler_external"
    assert state_db != handler.user_db
    assert "scheduler_external" in str(state_db)


def _stub_report(*, total=6, ready=2, skipped=4, mode="dry-run", extra_items=None):
    items = extra_items or [
        {"source_job_id": "1", "target_job_id": "bach:1", "action": "ready", "reason": ""},
        {"source_job_id": "2", "target_job_id": "bach:2", "action": "ready", "reason": ""},
        {"source_job_id": "3", "target_job_id": "bach:3", "action": "skipped", "reason": "no automatic due parity"},
        {"source_job_id": "4", "target_job_id": "bach:4", "action": "skipped", "reason": "shell operators"},
    ]
    payload = {
        "source_db": "/legacy/bach.db",
        "target_db": "/state/state.db",
        "dry_run": mode == "dry-run",
        "total": total,
        "imported": 0 if mode == "dry-run" else ready,
        "ready": ready if mode == "dry-run" else 0,
        "skipped": skipped,
        "items": items,
    }
    return SimpleNamespace(
        total=total,
        skipped=skipped,
        to_dict=lambda: dict(payload),
    )


def _patch_provider_external(monkeypatch, adapter):
    """Schiebt einen Stub-Adapter unter den Provider-Seam (Provider 'external')."""
    monkeypatch.setattr(
        scheduler_module,
        "create_external_scheduler_adapter",
        lambda state_db: adapter,
    )
    monkeypatch.setattr(
        "hub.scheduler_provider.importlib.util.find_spec", lambda name: object()
    )


def test_external_status_formats_output(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "state.db"))
    adapter = SimpleNamespace(
        status=lambda: {
            "provider": "ellmos-scheduler",
            "database": str(tmp_path / "state.db"),
            "jobs": {"total": 2, "enabled": 1},
            "runs": {"total": 5, "succeeded": 4, "failed": 1, "active": 0},
            "last_tick_at": "2026-09-12T01:00:00+00:00",
        }
    )
    _patch_provider_external(monkeypatch, adapter)
    handler = _make_handler()
    ok, out = handler.handle("external", ["status"])
    assert ok is True
    assert "EXTERNAL SCHEDULER STATUS" in out
    assert "Fail-Closed-Fallback" in out
    ok_json, out_json = handler.handle("external", ["status", "--json"])
    assert ok_json is True
    payload = json.loads(out_json)
    assert payload["provider"] == "ellmos-scheduler"
    assert payload["state_db"] == str((tmp_path / "state.db").resolve())


def test_external_jobs_formats_output(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "state.db"))
    adapter = SimpleNamespace(
        jobs=lambda: [
            {
                "id": "7",
                "scheduler_id": "bach:7",
                "name": "Log Rotation",
                "job_type": "interval",
                "status": "scheduled",
                "next_run": "2026-09-12T02:00:00+00:00",
                "last_run": None,
                "last_result": None,
            }
        ]
    )
    _patch_provider_external(monkeypatch, adapter)
    handler = _make_handler()
    ok, out = handler.handle("external", ["jobs"])
    assert ok is True
    assert "Log Rotation" in out
    assert "interval" in out


def test_external_verify_defaults_to_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "state.db"))
    calls = {}

    def fake_import_legacy(source_db, **options):
        calls["source"] = source_db
        calls.update(options)
        return _stub_report(mode="dry-run")

    adapter = SimpleNamespace(import_legacy=fake_import_legacy)
    _patch_provider_external(monkeypatch, adapter)
    handler = _make_handler()
    ok, out = handler.handle("external", ["verify"])
    assert ok is True
    assert "DRY-RUN" in out
    assert calls["dry_run"] is True
    assert calls["timezone_name"]
    assert calls["bach_root"] == BACH_ROOT.parent
    assert "uebersprungen" in out
    assert "no automatic due parity" in out


def test_external_verify_apply_writes_idempotently(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "state.db"))
    calls = {}

    def fake_import_legacy(source_db, **options):
        calls.update(options)
        return _stub_report(mode="apply")

    adapter = SimpleNamespace(import_legacy=fake_import_legacy)
    _patch_provider_external(monkeypatch, adapter)
    handler = _make_handler()
    ok, out = handler.handle("external", ["verify", "--apply"])
    assert ok is True
    assert calls["dry_run"] is False
    assert "APPLY" in out
    assert "idempotent" in out
    assert "14-Tage-Parallelbetrieb" in out


def test_external_verify_handler_dry_run_wins_over_apply(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "state.db"))
    calls = {}

    def fake_import_legacy(source_db, **options):
        calls.update(options)
        return _stub_report(mode="dry-run")

    adapter = SimpleNamespace(import_legacy=fake_import_legacy)
    _patch_provider_external(monkeypatch, adapter)
    handler = _make_handler()
    ok, out = handler.handle("external", ["verify", "--apply"], dry_run=True)
    assert ok is True
    assert calls["dry_run"] is True
    assert "DRY-RUN" in out


def test_external_verify_reports_missing_source_db(monkeypatch, tmp_path):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "state.db"))
    adapter = SimpleNamespace(
        import_legacy=lambda source_db, **options: (_ for _ in ()).throw(FileNotFoundError(source_db))
    )
    _patch_provider_external(monkeypatch, adapter)
    handler = _make_handler()
    handler.user_db = tmp_path / "gibt_es_nicht.db"
    ok, out = handler.handle("external", ["verify"])
    assert ok is False
    assert "Legacy-DB nicht gefunden" in out


def test_external_unknown_subcommand(monkeypatch):
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", "/tmp/state.db")
    _patch_provider_external(monkeypatch, SimpleNamespace())
    handler = _make_handler()
    ok, out = handler.handle("external", ["tobogan"])
    assert ok is False
    assert "Unbekanntes external-Subkommando" in out


def test_doctor_provider_check_reports_rollback(monkeypatch):
    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    handler = _make_handler()
    check = handler._check_scheduler_provider()
    assert check["status"] == "warn"
    assert "Rollback aktiv" in check["message"]
    assert check["details"]["rollback_env_var"] == ROLLBACK_ENV_VAR


# ---------------------------------------------------------------------------
# 4. Integration gegen das echte ellmos-scheduler-Modul
# ---------------------------------------------------------------------------

LEGACY_SCHEMA = """
CREATE TABLE scheduler_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    job_type TEXT NOT NULL,
    schedule TEXT,
    command TEXT NOT NULL,
    script_path TEXT,
    arguments TEXT,
    parameters TEXT,
    is_active INTEGER DEFAULT 0,
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    run_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    last_result TEXT,
    last_output TEXT,
    timeout_seconds INTEGER DEFAULT 300,
    retry_on_fail INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    dist_type INTEGER DEFAULT 1
);
"""


@pytest.fixture
def legacy_db(tmp_path):
    """Legacy-Store mit je einem Job je Verifikationsklasse."""
    import sqlite3

    db_path = tmp_path / "legacy" / "bach.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(LEGACY_SCHEMA)
    jobs = [
        ("Intervall Script", "interval", "30s", "", str(tmp_path / "noop.py"), "", 1),
        ("Cron Command", "cron", "0 7 * * *", str(Path(sys.executable)), "", "-V", 1),
        ("Chain Job", "chain", "", "", "", "", 1),
        ("Event Job", "event", "", "", "", "", 1),
        ("Manual Job", "manual", "", "", "", "", 1),
        ("Shell Operator Job", "interval", "1h", "echo hi && echo there", "", "", 1),
    ]
    conn.executemany(
        "INSERT INTO scheduler_jobs (name, job_type, schedule, command,"
        " script_path, arguments, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
        jobs,
    )
    conn.commit()
    conn.close()
    (tmp_path / "noop.py").write_text("print('noop')\n", encoding="utf-8")
    return db_path


def _integration_handler(monkeypatch, tmp_path, legacy_path) -> SchedulerHandler:
    monkeypatch.setenv("BACH_EXTERNAL_SCHEDULER_DB", str(tmp_path / "state" / "state.db"))
    handler = SchedulerHandler(BACH_ROOT)
    handler.user_db = legacy_path
    return handler


@pytest.mark.skipif(not HAS_EXTERNAL, reason="ellmos-scheduler ist nicht installiert")
def test_integration_verify_dry_run_maps_and_skips(monkeypatch, tmp_path, legacy_db):
    """Intervall/Cron werden gemappt; chain/event/manual/Shell-Metas explizit uebersprungen."""
    handler = _integration_handler(monkeypatch, tmp_path, legacy_db)

    ok, out = handler.handle("external", ["verify", "--json"])
    assert ok is True
    report = json.loads(out)

    assert report["mode"] == "dry-run"
    assert report["total"] == 6
    assert report["ready"] == 2
    assert report["skipped"] == 4
    assert report["imported"] == 0

    by_source = {item["source_job_id"]: item for item in report["items"]}
    assert by_source["1"]["action"] == "ready"
    assert by_source["2"]["action"] == "ready"
    assert "no automatic due parity" in by_source["3"]["reason"]  # chain
    assert "no automatic due parity" in by_source["4"]["reason"]  # event
    assert "no automatic due parity" in by_source["5"]["reason"]  # manual
    assert by_source["6"]["action"] == "skipped"  # Shell-Operatoren

    # Dry-Run darf keine Jobs in den Ziel-Store uebernehmen.
    ok, out = handler.handle("external", ["jobs", "--json"])
    assert ok is True
    assert json.loads(out)["jobs"] == []


@pytest.mark.skipif(not HAS_EXTERNAL, reason="ellmos-scheduler ist nicht installiert")
def test_integration_apply_is_idempotent_and_never_overwrites(monkeypatch, tmp_path, legacy_db):
    handler = _integration_handler(monkeypatch, tmp_path, legacy_db)

    ok, out = handler.handle("external", ["verify", "--apply", "--json"])
    assert ok is True
    first = json.loads(out)
    assert first["mode"] == "apply"
    assert first["imported"] == 2

    ok, out = handler.handle("external", ["verify", "--json"])
    second = json.loads(out)
    assert second["mode"] == "dry-run"
    assert second["imported"] == 0
    assert second["skipped"] == 6
    assert all(
        "already exists" in item["reason"]
        for item in second["items"]
        if item["action"] == "skipped" and item["source_job_id"] in {"1", "2"}
    )

    ok, out = handler.handle("external", ["jobs", "--json"])
    assert ok is True
    jobs = json.loads(out)["jobs"]
    assert len(jobs) == 2
    names = {job["name"] for job in jobs}
    assert names == {"Intervall Script", "Cron Command"}
    assert all(job["scheduler_id"].startswith("bach:") for job in jobs)


@pytest.mark.skipif(not HAS_EXTERNAL, reason="ellmos-scheduler ist nicht installiert")
def test_integration_adapter_tick_executes_due_job(monkeypatch, tmp_path, legacy_db):
    """Daemon-Faehigkeit: ein faelliger, uebernommener Job laeuft mit Run-Receipt."""
    handler = _integration_handler(monkeypatch, tmp_path, legacy_db)
    marker = tmp_path / "tick_marker.txt"
    job_script = tmp_path / "tick_job.py"
    job_script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ok')\n",
        encoding="utf-8",
    )

    import sqlite3

    conn = sqlite3.connect(legacy_db)
    conn.execute(
        "INSERT INTO scheduler_jobs (name, job_type, schedule, command,"
        " script_path, arguments, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Tick Probe", "interval", "1s", "", str(job_script), "", 1),
    )
    conn.commit()
    conn.close()

    ok, out = handler.handle("external", ["verify", "--apply", "--json"])
    assert ok is True
    assert json.loads(out)["imported"] == 3

    adapter = scheduler_module.create_external_scheduler_adapter(handler._external_state_db())
    due = datetime.now(UTC) + timedelta(seconds=5)
    runs = adapter.tick(now=due)
    assert runs, "Tick musste den faelligen Job ausfuehren"
    assert any(run["status"] == "succeeded" for run in runs)
    assert marker.exists()

    status = adapter.status()
    assert status["provider"] == "ellmos-scheduler"
    assert status["runs"]["succeeded"] >= 1


@pytest.mark.skipif(not HAS_EXTERNAL, reason="ellmos-scheduler ist nicht installiert")
def test_integration_rollback_env_leaves_legacy_intact(monkeypatch, tmp_path, legacy_db):
    """Rollback: BACH bleibt vollstaendig auf dem Legacy-Pfad funktionsfaehig."""
    import sqlite3

    monkeypatch.setenv(ROLLBACK_ENV_VAR, "0")
    handler = SchedulerHandler(BACH_ROOT)
    handler.user_db = legacy_db

    ok, out = handler.handle("external", ["status"])
    assert ok is False
    assert "Rollback aktiv" in out

    ok, out = handler.handle("jobs", ["--json"])
    assert ok is True
    payload = json.loads(out)
    assert len(payload["jobs"]) == 6  # Legacy-Lesepfad bleibt unberuehrt

    conn = sqlite3.connect(f"file:{legacy_db}?mode=ro", uri=True)
    rows = conn.execute("SELECT COUNT(*) FROM scheduler_jobs").fetchone()[0]
    conn.close()
    assert rows == 6  # kein Schreibzugriff auf den Legacy-Store


# ---------------------------------------------------------------------------
# 5. AST-Waechter: Importgrenze liegt nur im Provider-Seam
# ---------------------------------------------------------------------------


def test_no_direct_external_import_outside_provider_seam():
    """Kein hub-Modul darf ellmos_scheduler direkt importieren (Plan 1.4)."""
    hub_dir = BACH_ROOT / "hub"
    offender = re.compile(r"^\s*(from|import)\s+ellmos_scheduler", re.MULTILINE)
    violations = []
    for py_file in hub_dir.glob("*.py"):
        if py_file.name == "scheduler_provider.py":
            continue
        text = py_file.read_text(encoding="utf-8", errors="replace")
        if offender.search(text):
            violations.append(py_file.name)
    assert not violations, f"Direktimporte ausserhalb des Seams: {violations}"