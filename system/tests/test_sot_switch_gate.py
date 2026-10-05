# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests fuer das SoT-Umschaltgate system/hub/sot_switch_gate.py (BACH20-08).

Vertrag dieser Tests:

1. Fail-Closed Defaults: Ohne environ-Parameter bewertet probe_sot_switch
   die reale Umgebung; ein abwesender Rollback-Schalter blockiert jeden
   Wechsel (MODULRUECKTRANSFER-PLAN §4 Regel 1).
2. Rollback-Matrix: Die Aus-Werte 0/false/no/off (nach strip+lower)
   erzwingen den Ruecktransfer, 1/true/on erlauben den Wechsel bei sonst
   gueltigem Nachweis; ein leer gesetzter Schalter blockiert Fail-Closed.
3. Nachweisdefekte: Fehlende Datei, ungueltiges JSON, falsches modul/stufe,
   offene Hostlaeufe und defekte Gates (status/host/exit_code) blockieren
   fail-closed.
4. Journal-Sequenz und single-writer: Ohne Journal ist nur die erste
   Stufe P0 moeglich; ein offener Wechsel blockiert ALLE Module; die
   Vorgaenger-Stufe muss gruen sein; der letzte Journalstatus gewinnt
   (last-wins).
5. record_switch und confirm_green schreiben bei not allowed nichts:
   Verifizieren bleibt lesend, Schreiben passiert nur bei erlaubtem
   Wechsel.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))

from hub.sot_switch_gate import (  # noqa: E402
    DEFAULT_EVIDENCE_DIR,
    DEFAULT_JOURNAL_PATH,
    SOT_MODULES,
    SOT_STAGES,
    SotSwitchProbe,
    confirm_green,
    probe_sot_switch,
    record_switch,
)

pytestmark = pytest.mark.usefixtures("_reset_external_env")


@pytest.fixture(autouse=True)
def _reset_external_env(monkeypatch):
    """Entfernt alle SoT-Rollback-Schalter aus der Umgebung (Isolation)."""
    for var in SOT_MODULES.values():
        monkeypatch.delenv(var, raising=False)


VAR = SOT_MODULES["scheduler"]


def gruen_gate(host="workstation-lg", **overrides):
    """Ein vollstaendig gruenes Gate mit plausiblen Werten."""
    gate = {
        "status": "gruen",
        "host": host,
        "timestamp": "2026-09-29T09:00:00Z",
        "exit_code": 0,
    }
    gate.update(overrides)
    return gate


def write_evidence(ev, pfad_modul, pfad_stufe, **overrides):
    """Schreibt einen Nachweis: Pfad aus pfad_modul/pfad_stufe, doc-Felder via overrides uebersteuerbar."""
    doc = {
        "modul": pfad_modul,
        "stufe": pfad_stufe,
        "offene_hostlaeufe": [],
        "gates": {f"gate_{i}": gruen_gate() for i in range(1, 6)},
    }
    doc.update(overrides)
    (ev / pfad_modul).mkdir(parents=True, exist_ok=True)
    (ev / pfad_modul / f"{pfad_stufe}.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _journal_line(modul, stufe, status, host="workstation-lg", timestamp="2026-09-29T09:00:00Z"):
    """Eine gueltige Journalzeile als dict."""
    return {
        "modul": modul,
        "stufe": stufe,
        "status": status,
        "host": host,
        "timestamp": timestamp,
    }


def write_journal(path, *entries):
    """Schreibt Journalzeilen (dicts) zeilenweise als JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )


# --- Kanon (Konstanten) ---------------------------------------------


def test_kanon_defaultpfade_zeigen_auf_zentrales_state_verzeichnis():
    assert DEFAULT_EVIDENCE_DIR == SYSTEM_ROOT.parent / "data" / "state" / "sot-gate" / "evidence"
    assert DEFAULT_JOURNAL_PATH == SYSTEM_ROOT.parent / "data" / "state" / "sot-gate" / "journal.jsonl"


def test_kanon_stufen_und_module():
    assert SOT_STAGES == ("P0", "P2", "P3", "P4")
    assert set(SOT_MODULES) == {
        "scheduler",
        "explorer",
        "memoryhooks",
        "workflowhooks",
        "transitsync",
        "agent_registry",
    }
    assert VAR == "BACH_USE_EXTERNAL_SCHEDULER"


# --- (a) Validierung von modul/stufe --------------------------------


@pytest.mark.parametrize(
    "modul,stufe",
    [("schedulerx", "P0"), ("scheduler", "P1"), ("scheduler", "p0")],
)
def test_validate_lehnt_unbekannte_werte_ab(modul, stufe, tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    with pytest.raises(ValueError):
        probe_sot_switch(modul, stufe)
    with pytest.raises(ValueError):
        record_switch(
            modul,
            stufe,
            environ={VAR: "1"},
            host="workstation-lg",
            timestamp="2026-09-29T09:00:00Z",
            evidence_dir=ev,
            journal_path=jp,
        )
    with pytest.raises(ValueError):
        confirm_green(
            modul,
            stufe,
            host="workstation-lg",
            timestamp="2026-09-29T09:00:00Z",
            evidence_dir=ev,
            journal_path=jp,
        )


# --- (b) Fail-Closed Defaults ohne kwargs ----------------------------


def test_probe_ohne_kwargs_nutzt_reale_umgebung_fail_closed():
    probe = probe_sot_switch("scheduler", "P0")
    assert isinstance(probe, SotSwitchProbe)
    assert probe.allowed is False
    assert probe.modul == "scheduler"
    assert probe.stufe == "P0"
    assert any(VAR in reason for reason in probe.reasons)


# --- (c) Rollback-Matrix ---------------------------------------------


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "OFF", " 0 "])
def test_rollback_aus_blockiert_jeden_wechsel(raw, tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: raw}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("steht auf Aus" in reason for reason in probe.reasons)


@pytest.mark.parametrize("raw", ["1", "true", "on", " 1 "])
def test_rollback_an_erlaubt_wechsel(raw, tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: raw}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is True
    assert probe.reasons == ()


# --- (d) abwesender und leerer Schalter -------------------------------


def test_rollback_schalter_abwesend_blockiert(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = probe_sot_switch("scheduler", "P0", environ={}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("ist nicht gesetzt" in reason for reason in probe.reasons)


@pytest.mark.parametrize("raw", ["", "   "])
def test_rollback_schalter_leer_blockiert_fail_closed(raw, tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: raw}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("ist leer gesetzt" in reason for reason in probe.reasons)


# --- (e) Nachweisdefekte ----------------------------------------------


def test_nachweis_datei_fehlt_blockiert(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("Nachweis fehlt" in reason for reason in probe.reasons)


def test_nachweis_ungueltiges_json_blockiert(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    (ev / "scheduler" / "P0.json").write_text("{ kein json", encoding="utf-8")
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("ist kein gueltiges JSON" in reason for reason in probe.reasons)


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"gates": {}}, "gates enthaelt"),
        ({"offene_hostlaeufe": ["mac-studio offen"]}, "nicht leer"),
        ({"offene_hostlaeufe": None}, "offene_hostlaeufe fehlt"),
        ({"modul": "explorer"}, "modul ist 'explorer', erwartet 'scheduler'"),
        ({"stufe": "P2"}, "stufe ist 'P2', erwartet 'P0'"),
    ],
)
def test_nachweisdefekte_dokumentebene_blockieren(overrides, expected, tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0", **overrides)
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any(expected in reason for reason in probe.reasons)


def _del_gate_4(doc):
    del doc["gates"]["gate_4"]


def _gate_3_status_gelb(doc):
    doc["gates"]["gate_3"]["status"] = "gelb"


def _gate_2_exit_bool(doc):
    doc["gates"]["gate_2"]["exit_code"] = True


def _gate_2_exit_eins(doc):
    doc["gates"]["gate_2"]["exit_code"] = 1


def _gate_1_host_leer(doc):
    doc["gates"]["gate_1"]["host"] = ""


@pytest.mark.parametrize(
    "mutator,expected",
    [
        (_del_gate_4, "gate_4 fehlt"),
        (_gate_3_status_gelb, "'gelb', erwartet 'gruen'"),
        (_gate_2_exit_bool, "Boolean"),
        (_gate_2_exit_eins, "1 statt 0"),
        (_gate_1_host_leer, "keine nicht-leere Zeichenkette"),
    ],
)
def test_nachweisdefekte_gateebene_blockieren(mutator, expected, tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    path = ev / "scheduler" / "P0.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutator(doc)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any(expected in reason for reason in probe.reasons)


# --- (f) Journal: Sequenz und single-writer ---------------------------


def test_journal_fehlt_p0_ist_erlaubt(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is True
    assert probe.reasons == ()


def test_journal_fehlt_nur_erste_stufe_p0(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P2")
    probe = probe_sot_switch("scheduler", "P2", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("erste Stufe" in reason for reason in probe.reasons)


def test_vorgaenger_stufe_muss_gruen_sein(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P2")
    write_journal(jp, _journal_line("explorer", "P0", "gruen"))
    probe = probe_sot_switch("scheduler", "P2", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("Vorgaenger-Stufe P0" in reason for reason in probe.reasons)


def test_offener_wechsel_blockiert_alle_module(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "explorer", "P0")
    write_journal(jp, _journal_line("scheduler", "P0", "offen"))
    probe = probe_sot_switch(
        "explorer",
        "P0",
        environ={SOT_MODULES["explorer"]: "1"},
        evidence_dir=ev,
        journal_path=jp,
    )
    assert probe.allowed is False
    assert any("blockiert ALLE" in reason for reason in probe.reasons)


def test_journal_ungueltiger_status_blockiert(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    write_journal(jp, _journal_line("scheduler", "P0", "gruenx"))
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is False
    assert any("Journal Zeile 1" in reason for reason in probe.reasons)


def test_journal_last_wins_offen_dann_gruen(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P2")
    write_journal(
        jp,
        _journal_line("scheduler", "P0", "offen"),
        _journal_line("scheduler", "P0", "gruen"),
    )
    probe = probe_sot_switch("scheduler", "P2", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is True


# --- (g) record_switch: Schreiben nur bei erlaubtem Wechsel -----------


def test_record_switch_schreibt_offen_eintrag(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = record_switch(
        "scheduler",
        "P0",
        environ={VAR: "1"},
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert probe.allowed is True
    lines = jp.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "modul": "scheduler",
        "stufe": "P0",
        "status": "offen",
        "host": "workstation-lg",
        "timestamp": "2026-09-29T09:00:00Z",
    }


def test_record_switch_not_allowed_schreibt_nichts(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = record_switch(
        "scheduler",
        "P0",
        environ={},
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert probe.allowed is False
    assert jp.is_file() is False


def test_record_switch_zweiter_versuch_blockiert(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    erster = record_switch(
        "scheduler",
        "P0",
        environ={VAR: "1"},
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert erster.allowed is True
    zweiter = record_switch(
        "scheduler",
        "P0",
        environ={VAR: "1"},
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert zweiter.allowed is False
    assert any("blockiert ALLE" in reason for reason in zweiter.reasons)
    lines = jp.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


# --- (h) confirm_green: Bestaetigen ist Verwaltung, kein Wechsel -------


def test_confirm_green_ohne_journal_lehnt_ab(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = confirm_green(
        "scheduler",
        "P0",
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert probe.allowed is False
    assert any(
        "Journal fehlt: kein offener Eintrag fuer scheduler/P0 zu bestaetigen" in reason
        for reason in probe.reasons
    )
    assert jp.is_file() is False


def test_confirm_green_prueft_nachweis_nach_record(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    record_switch(
        "scheduler",
        "P0",
        environ={VAR: "1"},
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    (ev / "scheduler" / "P0.json").write_text("{ kein json", encoding="utf-8")
    probe = confirm_green(
        "scheduler",
        "P0",
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert probe.allowed is False
    assert any("ist kein gueltiges JSON" in reason for reason in probe.reasons)
    lines = jp.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "offen"


def test_confirm_green_bestaetigt_offen_eintrag(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    record_switch(
        "scheduler",
        "P0",
        environ={VAR: "1"},
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    probe = confirm_green(
        "scheduler",
        "P0",
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert probe.allowed is True
    assert probe.reasons == ()
    lines = jp.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1]) == {
        "modul": "scheduler",
        "stufe": "P0",
        "status": "gruen",
        "host": "workstation-lg",
        "timestamp": "2026-09-29T09:00:00Z",
    }
    zweiter = confirm_green(
        "scheduler",
        "P0",
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    )
    assert zweiter.allowed is False
    assert any(
        "Kein offener Eintrag fuer scheduler/P0 im Journal: nichts zu bestaetigen" in reason
        for reason in zweiter.reasons
    )


# --- (i) Vollzyklus: record, blockiert, Vorgaenger, gruen, frei --------


def test_full_cycle_von_record_bis_gruen(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    env = {VAR: "1"}
    write_evidence(ev, "scheduler", "P0")
    assert record_switch(
        "scheduler",
        "P0",
        environ=env,
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    ).allowed is True
    erster = probe_sot_switch("scheduler", "P0", environ=env, evidence_dir=ev, journal_path=jp)
    assert erster.allowed is False
    assert any("blockiert ALLE" in reason for reason in erster.reasons)
    write_evidence(ev, "scheduler", "P2")
    p2 = probe_sot_switch("scheduler", "P2", environ=env, evidence_dir=ev, journal_path=jp)
    assert p2.allowed is False
    assert any("Vorgaenger-Stufe P0" in reason for reason in p2.reasons)
    assert confirm_green(
        "scheduler",
        "P0",
        host="workstation-lg",
        timestamp="2026-09-29T09:00:00Z",
        journal_path=jp,
        evidence_dir=ev,
    ).allowed is True
    assert probe_sot_switch("scheduler", "P2", environ=env, evidence_dir=ev, journal_path=jp).allowed is True


# --- (j) Helper-Gueltigkeit -------------------------------------------


def test_helper_erzeugen_gueltigen_nachweis(tmp_path):
    ev = tmp_path / "evidence"
    jp = tmp_path / "journal.jsonl"
    write_evidence(ev, "scheduler", "P0")
    probe = probe_sot_switch("scheduler", "P0", environ={VAR: "1"}, evidence_dir=ev, journal_path=jp)
    assert probe.allowed is True
    assert probe.modul == "scheduler"
    assert probe.stufe == "P0"