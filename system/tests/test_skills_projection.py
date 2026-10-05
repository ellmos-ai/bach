# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer tools/maintenance/skills_projection.py.

Geprueft wird die Read-only-Projektion von skills/tools/handlers aus der
Produktiv-DB: Zaehl-Paritaet, Provenienz, Trigger-Erhaltung, Read-only-
Garantie (Hash-Paritaet + Schreibversuch + Quelltext-Scan) und Output-
Schreiben. Die Produktiv-DB wird hart referenziert (PROD_DB), weil conftest
BACH_DB auf tmp umbiegt.
"""
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from tools.maintenance import skills_projection as sp  # ruff: noqa: E402

PROD_DB = (SYSTEM_ROOT / "data" / "bach.db").resolve()
CTX_WHERE = "FROM context_triggers WHERE source='skill' AND agent_id='default'"

# Erstprojektion (verifiziert via CLI --stats und Verify-Skript):
EXPECTED_SKILLS = 128
EXPECTED_TOOLS = 341
# 2026-09-29: 110 → 111: +1 contract_cockpit (provenance handler_registry, Convenience-Proxy bach_api.py Z.756; legit-geprüft, siehe Session-Zettel)
EXPECTED_HANDLERS = 111
EXPECTED_TRIGGER_UNMATCHED = 45


def _ro_connect(db_path):
    return sqlite3.connect(f"file:{db_path}?mode=ro&immutable=0", uri=True)


def _ro_count(conn, sql):
    return conn.execute(sql).fetchone()[0]


@pytest.fixture(scope="module")
def full_projection():
    """Einmalige Erstprojektion inkl. Handler-Discovery (Modulcache)."""
    return sp.build_projection(db_path=str(PROD_DB), include_handlers=True)


# (a) Zaehl-Paritaet Projektion vs. Produktiv-DB
def test_counts_parity(full_projection):
    proj = full_projection
    with _ro_connect(PROD_DB) as conn:
        ro_skills = _ro_count(conn, "SELECT COUNT(1) FROM skills")
        ro_tools = _ro_count(conn, "SELECT COUNT(1) FROM tools")
    assert len(proj["skills"]) == ro_skills
    assert len(proj["tools"]) == ro_tools
    assert proj["counts"]["skills"] == len(proj["skills"])
    assert proj["counts"]["tools"] == len(proj["tools"])
    assert proj["counts"]["handlers"] == len(proj["handlers"])
    # Hard-Asserts der Erstprojektion
    assert len(proj["skills"]) == EXPECTED_SKILLS
    assert len(proj["tools"]) == EXPECTED_TOOLS
    assert len(proj["handlers"]) == EXPECTED_HANDLERS


# (b) Provenienz je Liste + Vereinigung == PROVENANCES
def test_provenance(full_projection):
    proj = full_projection
    assert {s["provenance"] for s in proj["skills"]} == {sp.PROVENANCE_SKILLS}
    assert {t["provenance"] for t in proj["tools"]} == {sp.PROVENANCE_TOOLS}
    assert {h["provenance"] for h in proj["handlers"]} == {sp.PROVENANCE_HANDLERS}
    union = (
        {s["provenance"] for s in proj["skills"]}
        | {t["provenance"] for t in proj["tools"]}
        | {h["provenance"] for h in proj["handlers"]}
    )
    assert union == set(sp.PROVENANCES)


# (c) Trigger-Erhaltung: matched + unmatched == truthy ctx-Trigger
def test_trigger_preservation():
    proj = sp.build_projection(db_path=str(PROD_DB), include_handlers=False)
    matched = sum(len(s["trigger_phrases"]) for s in proj["skills"])
    unmatched = sum(1 for w in proj["warnings"] if w.startswith("trigger_unmatched:"))
    with _ro_connect(PROD_DB) as conn:
        ro_total = _ro_count(conn, f"SELECT COUNT(1) {CTX_WHERE}")
        ro_truthy = _ro_count(
            conn,
            f"SELECT COUNT(1) {CTX_WHERE}"
            " AND trigger_phrase IS NOT NULL AND TRIM(trigger_phrase) != ''",
        )
    assert matched + unmatched == ro_truthy
    assert matched <= ro_total
    # Erstprojektion: 51 truthy ctx-Trigger, keine Duplikate -> 45 unmatched
    assert unmatched == EXPECTED_TRIGGER_UNMATCHED


# (d) Read-only: DB-Hash vor/nach build_projection identisch
def test_readonly_parity(tmp_path):
    copy_db = tmp_path / "copy.db"
    shutil.copyfile(PROD_DB, copy_db)
    before = hashlib.sha256(copy_db.read_bytes()).hexdigest()
    sp.build_projection(db_path=str(copy_db), include_handlers=False)
    after = hashlib.sha256(copy_db.read_bytes()).hexdigest()
    assert before == after


# (e) Read-only: Schreibversuch auf ro-Verbindung schlaegt fehl
def test_readonly_write_fails(tmp_path):
    copy_db = tmp_path / "copy.db"
    shutil.copyfile(PROD_DB, copy_db)
    conn = sqlite3.connect(f"file:{copy_db}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO skills(name) VALUES('__x__')")
    finally:
        conn.close()


# (f) Kein Schreib-SQL im Modul-Quelltext
def test_no_write_statements_source_scan():
    source = (SYSTEM_ROOT / "tools" / "maintenance" / "skills_projection.py").read_text(
        encoding="utf-8"
    )
    assert re.findall(r"\b(INSERT|UPDATE|DELETE|REPLACE)\b", source) == []


# (g) Output-Schreiben: JSON-Struktur und Konsistenz
def test_output_write(tmp_path, full_projection):
    out = tmp_path / "out.json"
    sp.write_projection(out, full_projection)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data.keys()) == {
        "generated_at",
        "db_path",
        "counts",
        "skills",
        "tools",
        "handlers",
        "warnings",
    }
    assert data["counts"]["skills"] == len(data["skills"])
    assert data["counts"]["tools"] == len(data["tools"])
    assert data["counts"]["handlers"] == len(data["handlers"])
