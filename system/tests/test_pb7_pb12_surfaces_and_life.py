# -*- coding: utf-8 -*-
"""Contract tests for PB-7 Module Surfaces & PB-12 Life Area Measured Endpoints + Privacy Guard (#3991, #3995)."""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

SYSTEM_ROOT = Path(__file__).resolve().parents[1]
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.life_overview_service import (
    PII_PATTERNS,
    get_financial_summary,
    get_health_energy_summary,
    get_life_overview,
    get_module_surfaces_matrix,
    get_routines_summary,
    get_tasks_sequences_summary,
    sanitize_pii,
)
from gui.server import app

TEST_SCHEMA = """
CREATE TABLE IF NOT EXISTS financial_emails (
    id INTEGER PRIMARY KEY,
    email_date TEXT,
    category TEXT,
    document_type TEXT,
    betrag REAL,
    steuer_relevant INTEGER DEFAULT 0,
    status TEXT DEFAULT 'verarbeitet'
);
CREATE TABLE IF NOT EXISTS financial_subscriptions (
    id INTEGER PRIMARY KEY,
    provider_id TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    category TEXT NOT NULL,
    betrag_monatlich REAL,
    betrag_jaehrlich REAL,
    zahlungsintervall TEXT,
    naechste_zahlung TEXT,
    kuendigungslink TEXT,
    letzte_rechnung_id INTEGER,
    letzte_zahlung TEXT,
    zahlungen_count INTEGER DEFAULT 1,
    aktiv INTEGER DEFAULT 1,
    bestaetigt INTEGER DEFAULT 1,
    steuer_relevant INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS financial_summary (
    id INTEGER PRIMARY KEY,
    jahr INTEGER NOT NULL,
    monat INTEGER,
    summen_kategorie TEXT,
    total_ausgaben REAL DEFAULT 0,
    total_steuer_relevant REAL DEFAULT 0,
    total_abos REAL DEFAULT 0,
    anzahl_rechnungen INTEGER DEFAULT 0,
    anzahl_abos INTEGER DEFAULT 0,
    berechnet_am TEXT,
    dist_type INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT 'Alltag',
    interval_type TEXT DEFAULT 'daily',
    interval_value INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    next_due_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    category TEXT DEFAULT 'life',
    assigned_to TEXT DEFAULT 'user',
    last_modified TEXT,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS marblerun_chains (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    steps_json TEXT DEFAULT '[]',
    is_active INTEGER DEFAULT 1
);
"""


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_life.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(TEST_SCHEMA)
    today = date.today().isoformat()

    # Financial rows
    conn.execute(
        """
        INSERT INTO financial_emails (id, email_date, category, document_type, betrag, steuer_relevant, status)
        VALUES (1, ?, 'Software', 'rechnung', 42.50, 1, 'verarbeitet')
        """,
        (today,),
    )
    conn.execute(
        """
        INSERT INTO financial_subscriptions
            (id, provider_id, provider_name, category, betrag_monatlich, aktiv, bestaetigt)
        VALUES (1, 'p1', 'Cloud Service', 'Software', 9.99, 1, 1)
        """
    )

    # Routine rows
    conn.execute(
        """
        INSERT INTO routines (id, name, is_active, next_due_at)
        VALUES (1, 'Tagesplanung', 1, ?), (2, 'Abendreflexion', 1, ?)
        """,
        (today, today),
    )

    # Task rows
    conn.execute(
        """
        INSERT INTO tasks (id, title, status, category, assigned_to)
        VALUES (1, 'Steuerunterlagen sortieren', 'pending', 'life', 'user'),
               (2, 'Wasserfilter wechseln', 'open', 'life', 'user'),
               (3, 'Einkauf erledigt', 'done', 'life', 'user')
        """
    )

    # MarbleRun chains
    conn.execute(
        """
        INSERT INTO marblerun_chains (id, name, is_active)
        VALUES (1, 'Morgen-Workflow', 1), (2, 'Wochenabschluss', 1)
        """
    )

    conn.commit()
    conn.close()
    return db_file


# ── PB-7 CONTRACT TESTS ──

def test_pb7_modules_surfaces_matrix_contract() -> None:
    """Verify PB-7 surface & integration matrix structure and demo markings."""
    matrix = get_module_surfaces_matrix()

    assert matrix.get("schema") == "bach.module_surfaces.v1"
    assert matrix.get("data_source") == "measured"
    assert matrix.get("data-source") == "measured"

    modules = matrix.get("modules")
    assert isinstance(modules, dict), "modules must be a dict"
    assert len(modules) >= 18, f"Expected at least 18 modules, found {len(modules)}"

    for mod_id, mod in modules.items():
        agent_only = mod.get("agent_only")
        ui = mod.get("ui")

        assert isinstance(agent_only, bool), f"{mod_id}: agent_only must be bool"
        assert isinstance(ui, dict), f"{mod_id}: ui must be dict"
        surfaces = ui.get("surfaces")
        assert isinstance(surfaces, list), f"{mod_id}: ui.surfaces must be a list"

        if agent_only:
            assert len(surfaces) == 0, f"{mod_id}: agent_only module must have empty ui.surfaces"
        else:
            assert len(surfaces) > 0, f"{mod_id}: non-agent-only module must have non-empty ui.surfaces"
            for r in surfaces:
                assert isinstance(r, str) and r.startswith("/"), f"{mod_id}: route {r} must start with '/'"

    # Demo mode markings (PB-7)
    homecontrol = modules.get("ellmos-homecontrol")
    assert homecontrol is not None
    assert homecontrol.get("demo_mode") is True
    assert homecontrol.get("integration_status") == "demo"

    robotics = modules.get("ellmos-robotics")
    assert robotics is not None
    assert robotics.get("demo_mode") is True
    assert robotics.get("integration_status") == "demo"


# ── PB-12 CONTRACT TESTS (DATA-SOURCE=MEASURED) ──

def test_pb12_financial_summary_measured(test_db: Path) -> None:
    """Verify /api/financial/summary produces measured data without assumptions."""
    summary = get_financial_summary(test_db)

    assert summary.get("schema") == "bach.financial_summary.v1"
    assert summary.get("data_source") == "measured"
    assert summary.get("data-source") == "measured"

    summaries = summary.get("summaries", [])
    assert len(summaries) >= 2
    month_summary = summaries[0]
    assert month_summary["total_ausgaben"] == 42.50
    assert month_summary["total_abos"] == 9.99
    assert month_summary["anzahl_rechnungen"] == 1
    assert month_summary["anzahl_abos"] == 1


def test_pb12_life_overview_measured(test_db: Path) -> None:
    """Verify /api/life/overview aggregates local-only measured sections."""
    overview = get_life_overview(test_db)

    assert overview.get("schema") == "bach.life_overview.v1"
    assert overview.get("data_source") == "measured"
    assert overview.get("data-source") == "measured"

    # 1. Finance (totals/counts only)
    finance = overview.get("finance", {})
    assert finance.get("data_source") == "measured"
    assert finance.get("total_ausgaben") == 42.50
    assert finance.get("total_abos") == 9.99
    assert finance.get("anzahl_rechnungen") == 1
    assert finance.get("anzahl_abos") == 1

    # 2. Routines (local SQLite)
    routines = overview.get("routines", {})
    assert routines.get("data_source") == "measured"
    assert routines.get("total") == 2
    assert routines.get("active") == 2
    assert routines.get("due_today") == 2

    # 3. Health & Energy (SpoonCheck local-only)
    health = overview.get("health_energy", {})
    assert health.get("data_source") == "measured"
    assert health.get("local_only") is True
    spoon_budget = health.get("spoon_budget", {})
    assert spoon_budget.get("spoons_total") == 12
    assert isinstance(spoon_budget.get("spoons_remaining"), int)
    assert spoon_budget.get("status") in ("balanced", "rest_recommended")

    # 4. Tasks & Sequences (MarbleRun)
    tasks_seq = overview.get("tasks_sequences", {})
    assert tasks_seq.get("data_source") == "measured"
    assert tasks_seq.get("open_tasks") == 2  # pending + open
    assert tasks_seq.get("active_sequences") == 2
    assert tasks_seq.get("marblerun_chains_count") == 2


# ── PB-12 PRIVACY & PII REDACTION TEST ──

def test_pb12_privacy_guard_no_pii_in_logs_or_errors(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that synthetic PII (IBAN, email, diagnosis, names) in DB rows is never logged."""
    pii_db = tmp_path / "pii_test.db"
    conn = sqlite3.connect(str(pii_db))
    conn.executescript(TEST_SCHEMA)

    today = date.today().isoformat()
    synthetic_iban = "DE89370400440532013000"
    synthetic_email = "john.doe.patient@example.org"
    synthetic_name = "Alice Smith"
    synthetic_diagnosis = "Diagnosis: severe chronic exhaustion and adhd"

    # Inject synthetic sensitive data into category, provider, description
    conn.execute(
        """
        INSERT INTO financial_emails (id, email_date, category, document_type, betrag, steuer_relevant, status)
        VALUES (1, ?, ?, 'rechnung', 120.0, 0, 'verarbeitet')
        """,
        (today, f"Patient {synthetic_name} - {synthetic_iban}"),
    )
    conn.execute(
        """
        INSERT INTO financial_subscriptions
            (id, provider_id, provider_name, category, betrag_monatlich, aktiv, bestaetigt)
        VALUES (1, 'p1', ?, ?, 49.00, 1, 1)
        """,
        (f"Therapie Praxis {synthetic_email}", synthetic_diagnosis),
    )
    conn.execute(
        """
        INSERT INTO routines (id, name, description, is_active, next_due_at)
        VALUES (1, ?, ?, 1, ?)
        """,
        (f"Medikamenteneinnahme {synthetic_name}", f"Details: {synthetic_diagnosis}", today),
    )
    conn.execute(
        """
        INSERT INTO tasks (id, title, description, status, category, assigned_to)
        VALUES (1, ?, ?, 'pending', 'life', 'user')
        """,
        (f"Überweisung an {synthetic_name} {synthetic_iban}", f"Kontakt: {synthetic_email}"),
    )
    conn.commit()
    conn.close()

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        # Trigger overview calculation
        overview = get_life_overview(pii_db)
        fin = get_financial_summary(pii_db)

    # 1. Assertions on returned payloads: no PII in summary fields
    overview_str = json.dumps(overview)
    assert synthetic_iban not in overview_str, "IBAN leaked into life overview response"
    assert synthetic_email not in overview_str, "Email leaked into life overview response"
    assert synthetic_diagnosis not in overview_str, "Diagnosis leaked into life overview response"
    assert synthetic_name not in overview_str, "Name leaked into life overview response"

    fin_str = json.dumps(fin)
    assert synthetic_iban not in fin_str, "IBAN leaked into financial summary response"
    assert synthetic_email not in fin_str, "Email leaked into financial summary response"
    assert synthetic_diagnosis not in fin_str, "Diagnosis leaked into financial summary response"
    assert synthetic_name not in fin_str, "Name leaked into financial summary response"

    # 2. Strict log capture check: PII must NEVER appear in logger output
    all_logs = caplog.text
    assert synthetic_iban not in all_logs, f"Synthetic IBAN leaked into logs: {all_logs}"
    assert synthetic_email not in all_logs, f"Synthetic email leaked into logs: {all_logs}"
    assert synthetic_name not in all_logs, f"Synthetic name leaked into logs: {all_logs}"
    assert "severe chronic exhaustion" not in all_logs, f"Diagnosis leaked into logs: {all_logs}"


# ── FASTAPI ROUTE INTEGRATION TESTS ──

def test_fastapi_server_endpoints_pb7_pb12() -> None:
    """Verify FastAPI server exposes /api/modules/surfaces, /api/financial/summary, and /api/life/overview."""
    client = TestClient(app)

    # 1. GET /api/modules/surfaces
    res_surfaces = client.get("/api/modules/surfaces")
    assert res_surfaces.status_code == 200
    data_surfaces = res_surfaces.json()
    assert data_surfaces.get("schema") == "bach.module_surfaces.v1"
    assert data_surfaces.get("data_source") == "measured"
    assert "ellmos-homecontrol" in data_surfaces.get("modules", {})
    assert data_surfaces["modules"]["ellmos-homecontrol"].get("demo_mode") is True

    # 2. GET /api/financial/summary
    res_fin = client.get("/api/financial/summary")
    assert res_fin.status_code == 200
    data_fin = res_fin.json()
    assert data_fin.get("schema") == "bach.financial_summary.v1"
    assert data_fin.get("data_source") == "measured"
    assert "summaries" in data_fin

    # 3. GET /api/life/overview
    res_life = client.get("/api/life/overview")
    assert res_life.status_code == 200
    data_life = res_life.json()
    assert data_life.get("schema") == "bach.life_overview.v1"
    assert data_life.get("data_source") == "measured"
    assert "finance" in data_life
    assert "routines" in data_life
    assert "health_energy" in data_life
    assert "tasks_sequences" in data_life
