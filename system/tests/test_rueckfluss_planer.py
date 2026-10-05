# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""BACH20-05 (task #1353): Waechter-Tests fuer hub/rueckfluss_planer.py.

Gepruefte Vertragspunkte:
1. Ausgabevertrag: genau 1 Ergebnis pro plane()-Aufruf, Status
   KANDIDAT|NO_OP|BLOCKED, Begruendung genau 1 Satz (endet auf ".",
   genau 1 Punkt), kandidat nur bei KANDIDAT gesetzt.
2. Null-Mutation: keine Datei-/DB-/Env-Zugriffe zur Laufzeit
   (monkeypatch-Waechter), Determinismus, AST-Waechter gegen
   verbotene Imports (os/sys/sqlite/pathlib/hub/subprocess) und
   OS-Attribute (env/environ/getenv/popen/system).
3. Disqualifikationsregeln des Registers (Stand 2026-09-28): R1
   Transfertests-Gate, R2 Tageslimit (NO_OP), Rollen gesperrt/
   hinterlegt/beobachtet, Drift, Datenvertrag, Pin, rote Gates,
   offene Gegenproben; Sortierung nach (prio, -score, name).
"""
from __future__ import annotations

import ast
import os
import sqlite3
import sys
from pathlib import Path

import pytest

BACH_ROOT = Path(__file__).resolve().parent.parent
if str(BACH_ROOT) not in sys.path:
    sys.path.insert(0, str(BACH_ROOT))

from hub.rueckfluss_planer import (
    GUELTIGE_STATUS,
    KANDIDATEN,
    STATUS_BLOCKED,
    STATUS_KANDIDAT,
    STATUS_NO_OP,
    Kandidat,
    PlanErgebnis,
    disqualifiziere,
    plane,
)

MODUL = BACH_ROOT / "hub" / "rueckfluss_planer.py"

VERBOTENE_IMPORTE = ("os", "sys", "sqlite3", "pathlib", "hub", "subprocess")
VERBOTENE_ATTRIBUTE = frozenset({"env", "environ", "getenv", "popen", "system"})

REGISTER_NAMEN = {
    "ellmos-scheduler",
    "memoryhooker",
    "ellmos-tests",
    "workflowhooker",
    "sqlite-transit-sync",
    "assistant-core",
    "ellmos-agent_registry",
    "accounts-core",
    "agent-launcher",
}


def _registerkandidat(name: str) -> Kandidat:
    for eintrag in KANDIDATEN:
        if eintrag.name == name:
            return eintrag
    raise AssertionError(f"Registerkandidat {name!r} fehlt im Snapshot")


def _verboten(*_args, **_kwargs):
    raise AssertionError("Seiteneffekt im Planer verboten (null Mutation)")


# ---------------------------------------------------------------------------
# 1. Ausgabevertrag: genau 1 Ergebnis, genau 1 Satz
# ---------------------------------------------------------------------------


def test_plane_liefert_genau_einen_belegten_kandidaten():
    ergebnis = plane()
    assert ergebnis.status == STATUS_KANDIDAT
    assert ergebnis.status in GUELTIGE_STATUS
    assert ergebnis.kandidat == "memoryhooker"
    assert ergebnis.begruendung.endswith(".")
    assert ergebnis.begruendung.count(".") == 1
    assert ergebnis.register_stand == "2026-09-28"


def test_ergebnis_validiert_status_satzform_und_kandidat():
    with pytest.raises(ValueError):
        PlanErgebnis(status="WURSCHT", kandidat=None, begruendung="Ein Satz.")
    with pytest.raises(ValueError):
        PlanErgebnis(status=STATUS_KANDIDAT, kandidat=None, begruendung="Ein Satz.")
    with pytest.raises(ValueError):
        PlanErgebnis(status=STATUS_NO_OP, kandidat="memoryhooker", begruendung="Ein Satz.")
    with pytest.raises(ValueError):
        PlanErgebnis(status=STATUS_NO_OP, kandidat=None, begruendung="Zwei. Saetze.")
    with pytest.raises(ValueError):
        PlanErgebnis(status=STATUS_NO_OP, kandidat=None, begruendung="Kein Punkt")


# ---------------------------------------------------------------------------
# 2. Null-Mutation: Laufzeit-Waechter, Determinismus, AST-Waechter
# ---------------------------------------------------------------------------


def test_plane_mutiert_nichts_und_ist_deterministisch(monkeypatch):
    monkeypatch.setattr("builtins.open", _verboten)
    monkeypatch.setattr("sqlite3.connect", _verboten)
    monkeypatch.setattr("os.environ.__setitem__", _verboten)
    monkeypatch.setattr("pathlib.Path.write_text", _verboten)
    monkeypatch.setattr("pathlib.Path.write_bytes", _verboten)
    erst = plane(datum="2026-09-29")
    zweit = plane(datum="2026-09-29")
    assert erst == zweit
    assert erst.datum == "2026-09-29"
    assert erst.kandidat == "memoryhooker"


@pytest.mark.parametrize("funktion", [plane, lambda: plane(heute_bereits_umgeschaltet=True)])
def test_kein_env_zugriff_unabhaengig_vom_datum(monkeypatch, funktion):
    monkeypatch.delenv("BACH_USE_EXTERNAL_EXPLORER", raising=False)
    monkeypatch.setattr("os.environ.__getitem__", _verboten)
    monkeypatch.setattr("os.getenv", _verboten)
    assert funktion().status in GUELTIGE_STATUS


def test_ast_waechter_keine_os_db_fs_hub_importe():
    quelltext = MODUL.read_text(encoding="utf-8")
    baum = ast.parse(quelltext)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for alias in knoten.names:
                assert alias.name.split(".")[0] not in VERBOTENE_IMPORTE, alias.name
        elif isinstance(knoten, ast.ImportFrom):
            wurzel = (knoten.module or "").split(".")[0]
            assert wurzel not in VERBOTENE_IMPORTE, knoten.module
        elif isinstance(knoten, ast.Attribute):
            assert knoten.attr not in VERBOTENE_ATTRIBUTE, knoten.attr


# ---------------------------------------------------------------------------
# 3. Disqualifikationsregeln R1/R2 und Register-Snapshot
# ---------------------------------------------------------------------------


def test_register_snapshot_enthaelt_alle_neun_kandidaten():
    assert {eintrag.name for eintrag in KANDIDATEN} == REGISTER_NAMEN


def test_r2_tageslimit_erzwingt_no_op():
    ergebnis = plane(heute_bereits_umgeschaltet=True)
    assert ergebnis.status == STATUS_NO_OP
    assert ergebnis.kandidat is None
    assert "R2" in ergebnis.begruendung


def test_nur_gesperrter_kandidat_blockiert():
    gesperrt = Kandidat(
        name="nur-gesperrt", prio=1, score=1, pin="",
        rolle="gesperrt", transfertests_gruen=True,
    )
    ergebnis = plane(kandidaten=[gesperrt])
    assert ergebnis.status == STATUS_BLOCKED
    assert ergebnis.kandidat is None
    assert any("rolle_gesperrt" in beleg for beleg in ergebnis.belege)


def test_leere_kandidatenliste_blockiert():
    ergebnis = plane(kandidaten=[])
    assert ergebnis.status == STATUS_BLOCKED
    assert ergebnis.kandidat is None


def test_register_disqualifikationen_des_snapshots():
    gruende = disqualifiziere(_registerkandidat("accounts-core"))
    assert "rolle_gesperrt" in gruende
    assert "drift:0166805!=9e0d0e9" in gruende
    assert "datenvertrag_fehlt" in disqualifiziere(
        _registerkandidat("ellmos-agent_registry"))
    assert "pin_unklar" in disqualifiziere(_registerkandidat("ellmos-tests"))
    gruende = disqualifiziere(_registerkandidat("agent-launcher"))
    assert "rolle_beobachtet" in gruende
    assert "gate_rot:OC-B" in gruende
    assert "rolle_hinterlegt" in disqualifiziere(
        _registerkandidat("sqlite-transit-sync"))
    assert sum(
        1 for g in disqualifiziere(_registerkandidat("ellmos-scheduler"))
        if g.startswith("gegenprobe_offen:")) == 4
    assert disqualifiziere(_registerkandidat("memoryhooker")) == []


def test_r1_ohne_beleg_gruener_transfertests_nicht_planbar():
    unbelegt = Kandidat(name="unbelegt", prio=1, score=9, pin="abc")
    assert unbelegt.transfertests_gruen is None
    assert disqualifiziere(unbelegt) == []
    ergebnis = plane(kandidaten=[unbelegt])
    assert ergebnis.status == STATUS_BLOCKED
    assert any(
        "R1:transfertests_gruen_nicht_belegt" in beleg
        for beleg in ergebnis.belege)


def test_niedrigere_prio_zahl_gewinnt_unabhaengig_von_reihenfolge():
    spaet = Kandidat(name="spaet", prio=5, score=30, pin="a", transfertests_gruen=True)
    frueh = Kandidat(name="frueh", prio=2, score=10, pin="b", transfertests_gruen=True)
    ergebnis = plane(kandidaten=[spaet, frueh])
    assert ergebnis.status == STATUS_KANDIDAT
    assert ergebnis.kandidat == "frueh"


def test_memoryhooker_siegt_nach_disqualifikation_des_hoeherprioren():
    ergebnis = plane()
    assert ergebnis.kandidat == "memoryhooker"
    assert "ellmos-scheduler" in ergebnis.begruendung
