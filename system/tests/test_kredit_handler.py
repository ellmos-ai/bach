# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for KreditHandler (hub/kredit.py) -- synthetic data only."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.alltag_import import AlltagImportError
from hub._services.ocean_stack_bridge import load_credits_core_module
from hub.kredit import KreditHandler, records_from_state

try:
    load_credits_core_module()
except ImportError:  # credits-core is a private Ocean module; not installed in every CI job
    pytest.skip("credits-core not installed", allow_module_level=True)

MIGRATION = SYSTEM_ROOT / "data" / "schema" / "migrations" / "055_credit_contracts.sql"


def _state():
    return {
        "schema": "umschuldung-state/1",
        "kredite": [
            {"id": "K1", "glaeubiger": "Testbank Nord", "art": "Ratenkredit", "status": "laeuft",
             "betrag": 12000, "rate": 250.0, "laufzeit_monate": 60, "zins_eff": 9.9,
             "rest_geschaetzt": [5800, 6200], "rest_art": "offene Raten inkl. Zinsen", "offen": [], "belege": []},
            {"id": "K2", "glaeubiger": "Testbank Sued", "art": "Ratenkauf", "status": "erledigt",
             "betrag": 900, "rest_geschaetzt": [0, 0], "offen": [], "belege": []},
            {"id": "K3", "glaeubiger": "Testkasse", "art": "Studienkredit", "status": "unklar",
             "rate": 100.0, "zins_eff": [3.0, 4.0], "rest_geschaetzt": [2000, 2500],
             "rest_art": "Restschuld ohne Zinsen", "offen": ["Kontoauszug fehlt"], "belege": []},
            {"id": "K4", "glaeubiger": "Testfinanz", "art": "Kreditkarte", "status": "vermutlich erledigt",
             "rate": 50.0, "rest_geschaetzt": [300, 300], "offen": [], "belege": []},
        ],
    }


def test_state_mapping():
    recs = {r["source_id"]: r for r in records_from_state(_state())}
    assert recs["K1"]["active"] == 1 and recs["K1"]["remaining_basis"] == "payments"
    assert (recs["K1"]["eff_rate_min"], recs["K1"]["eff_rate_max"]) == (9.9, 9.9)
    assert recs["K2"]["active"] == 0
    assert recs["K3"]["active"] is None and recs["K3"]["remaining_basis"] == "principal"
    assert (recs["K3"]["eff_rate_min"], recs["K3"]["eff_rate_max"]) == (3.0, 4.0)
    assert recs["K4"]["active"] is None and recs["K4"]["remaining_basis"] == "unknown"


@pytest.mark.parametrize("bad", [
    {"id": "K1"},                      # duplicate id
    {"id": "K9", "rate": "250"},       # string instead of number
    {"id": "K9", "rest_geschaetzt": [1, 2, 3]},
    {"id": "K9", "laufzeit_monate": 0},
])
def test_state_mapping_rejects_bad_input(bad):
    state = _state()
    state["kredite"].append({"glaeubiger": "X", "status": "laeuft", **bad})
    with pytest.raises(AlltagImportError):
        records_from_state(state)


@pytest.fixture
def env(tmp_path):
    base = tmp_path / "bach" / "system"
    (base / "data").mkdir(parents=True)
    db = base / "data" / "bach.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    state = tmp_path / "state.json"
    state.write_text(json.dumps(_state()), encoding="utf-8")
    return KreditHandler(base), state, db


def test_import_is_idempotent_and_dry_run_writes_nothing(env):
    handler, state, db = env
    ok, msg = handler.handle("import", [str(state)], dry_run=True)
    assert ok and "4 neu" in msg
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM credit_contracts").fetchone()[0] == 0
    assert "4 neu" in handler.handle("import", [str(state)])[1]
    assert "4 aktualisiert" in handler.handle("import", [str(state)])[1]


def test_import_rejects_wrong_schema(env, tmp_path):
    handler, _state_file, _db = env
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema": "abos-analyse-state/1", "kredite": []}), encoding="utf-8")
    ok, msg = handler.handle("import", [str(wrong)])
    assert not ok and "Falsches Schema" in msg


def test_overview_and_compare(env):
    handler, state, _db = env
    handler.handle("import", [str(state)])
    ok, text = handler.handle("ueberblick", [])
    assert ok and "aktiv 1, unklar 2, erledigt 1" in text
    ok, text = handler.handle("vergleich", ["--angebot", "4.9/24"])
    assert ok and "Abgelöst würden 1 Kredite" in text and "Ersparnis" in text
    ok, text = handler.handle("vergleich", ["--angebot", "4.9/24", "--mit-unklaren"])
    assert ok and "Abgelöst würden 2 Kredite" in text


@pytest.mark.parametrize("args", [[], ["--angebot", "abc"], ["--angebot", "5/0"], ["--quatsch"]])
def test_compare_rejects_bad_args(env, args):
    handler, _state_file, _db = env
    ok, msg = handler.handle("vergleich", args)
    assert not ok and msg.startswith("[ERROR]")


def test_missing_table_gives_migration_hint(tmp_path):
    base = tmp_path / "bach" / "system"
    (base / "data").mkdir(parents=True)
    sqlite3.connect(base / "data" / "bach.db").close()
    ok, msg = KreditHandler(base).handle("list", [])
    assert not ok and "055_credit_contracts.sql" in msg
