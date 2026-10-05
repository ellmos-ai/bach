import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

import pytest

from hub.module_update_gate import (
    UPDATE_MODULES,
    UPDATE_STAGES,
    ModuleUpdateProbe,
    confirm_green,
    probe_module_update,
    record_update,
    rollback_module,
)

MODUL = "scheduler"


def good_gate():
    return {"status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z", "exit_code": 0}


def good_gates():
    return {"gate_{}".format(i): good_gate() for i in range(1, 6)}


def write_evidence(ev_dir, modul, stufe, **overrides):
    doc = {
        "modul": modul,
        "stufe": stufe,
        "pin": "a1b2c3d4e5f6/v1.2.3",
        "manifest_hash": "a" * 64,
        "offene_hostlaeufe": [],
        "gates": good_gates(),
    }
    doc.update(overrides)
    mod_dir = ev_dir / modul
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / (stufe + ".json")).write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def write_journal(path, *entries):
    lines = []
    for entry in entries:
        if isinstance(entry, dict):
            lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        else:
            lines.append(entry)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def write_rollback(ev_dir, modul, name="rollback_code", **overrides):
    doc = {"modul": modul, "status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"}
    doc.update(overrides)
    mod_dir = ev_dir / modul
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / (name + ".json")).write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def test_a_unbekannte_werte_werfen_valueerror(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    with pytest.raises(ValueError):
        probe_module_update("unbekannt", "stage", evidence_dir=ev, journal_path=journ)
    with pytest.raises(ValueError):
        probe_module_update(MODUL, "flug", evidence_dir=ev, journal_path=journ)
    with pytest.raises(ValueError):
        record_update("unbekannt", "stage", host="h1", timestamp="2026-01-01T00:00:00Z", journal_path=journ, evidence_dir=ev)
    with pytest.raises(ValueError):
        record_update(MODUL, "flug", host="h1", timestamp="2026-01-01T00:00:00Z", journal_path=journ, evidence_dir=ev)
    with pytest.raises(ValueError):
        confirm_green("unbekannt", "stage", evidence_dir=ev, journal_path=journ)
    with pytest.raises(ValueError):
        confirm_green(MODUL, "flug", evidence_dir=ev, journal_path=journ)
    with pytest.raises(ValueError):
        rollback_module("unbekannt", host="h1", timestamp="2026-01-01T00:00:00Z", evidence_dir=ev)


def test_b_probe_stage_sauber_ohne_journal(tmp_path):
    assert UPDATE_STAGES[0] == "stage"
    assert MODUL in UPDATE_MODULES
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "stage")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert isinstance(probe, ModuleUpdateProbe)
    assert probe.modul == MODUL
    assert probe.stufe == "stage"
    assert probe.allowed
    assert probe.reasons == ()


def test_c_probe_ohne_nachweis(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("Nachweis fehlt:" in r for r in probe.reasons)


def test_d_offene_hostlaeufe(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"

    # Key komplett weggelassen
    doc = {
        "modul": MODUL,
        "stufe": "stage",
        "pin": "a1b2c3d4e5f6/v1.2.3",
        "manifest_hash": "a" * 64,
        "gates": good_gates(),
    }
    mod_dir = ev / MODUL
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / "stage.json").write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("keine Liste" in r for r in probe.reasons)

    # Wert ist keine Liste
    write_evidence(ev, MODUL, "stage", offene_hostlaeufe="x")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("keine Liste" in r for r in probe.reasons)

    # Liste nicht leer
    write_evidence(ev, MODUL, "stage", offene_hostlaeufe=["lauf-9"])
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("nicht leer" in r for r in probe.reasons)


def test_e_gates_rahmen(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"

    # Key komplett weggelassen
    doc = {
        "modul": MODUL,
        "stufe": "stage",
        "pin": "a1b2c3d4e5f6/v1.2.3",
        "manifest_hash": "a" * 64,
        "offene_hostlaeufe": [],
    }
    mod_dir = ev / MODUL
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / "stage.json").write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("kein Objekt" in r for r in probe.reasons)

    # Wert ist kein Objekt
    write_evidence(ev, MODUL, "stage", gates="x")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("kein Objekt" in r for r in probe.reasons)

    # Nur 4 von 5 Keys
    write_evidence(ev, MODUL, "stage", gates={"gate_{}".format(i): good_gate() for i in range(1, 5)})
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("enthaelt" in r for r in probe.reasons)


def test_f_gate_details(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"

    def probe_with_gate1(value):
        gates = good_gates()
        gates["gate_1"] = value
        write_evidence(ev, MODUL, "stage", gates=gates)
        return probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)

    probe = probe_with_gate1(None)
    assert not probe.allowed
    assert any("gate_1" in r and "fehlt" in r for r in probe.reasons)

    probe = probe_with_gate1("x")
    assert not probe.allowed
    assert any("gate_1" in r and "ist kein Objekt" in r for r in probe.reasons)

    gate = good_gate()
    gate["status"] = "rot"
    probe = probe_with_gate1(gate)
    assert not probe.allowed
    assert any("erwartet 'gruen'" in r for r in probe.reasons)

    gate = good_gate()
    gate["host"] = ""
    probe = probe_with_gate1(gate)
    assert not probe.allowed
    assert any("keine nicht-leere Zeichenkette" in r for r in probe.reasons)

    gate = good_gate()
    gate["exit_code"] = True
    probe = probe_with_gate1(gate)
    assert not probe.allowed
    assert any("ist ein Boolean" in r for r in probe.reasons)

    gate = good_gate()
    gate["exit_code"] = 7
    probe = probe_with_gate1(gate)
    assert not probe.allowed
    assert any("statt 0" in r for r in probe.reasons)


def test_g_pin_bei_stage_blockiert(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"

    write_evidence(ev, MODUL, "stage", pin=None)
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("pin ist" in r for r in probe.reasons)

    write_evidence(ev, MODUL, "stage", pin="xyz/v1")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("pin ist" in r for r in probe.reasons)


def test_h_activate_erlaubt(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "activate")
    write_journal(
        journ,
        {"modul": MODUL, "stufe": "stage", "status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
        {"modul": MODUL, "stufe": "gate", "status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = probe_module_update(MODUL, "activate", evidence_dir=ev, journal_path=journ)
    assert probe.allowed, probe.reasons
    assert probe.reasons == ()


def test_i_gate_prueft_pin_nicht(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "gate", pin="xyz/v1")
    write_journal(
        journ,
        {"modul": MODUL, "stufe": "stage", "status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = probe_module_update(MODUL, "gate", evidence_dir=ev, journal_path=journ)
    assert probe.allowed, probe.reasons


def test_j_manifest_hash(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"

    write_evidence(ev, MODUL, "stage", manifest_hash="a" * 63)
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("manifest_hash" in r for r in probe.reasons)

    write_evidence(ev, MODUL, "stage", manifest_hash="A" * 64)
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("manifest_hash" in r for r in probe.reasons)


def test_k_gate_ohne_journal(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "gate")
    probe = probe_module_update(MODUL, "gate", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("nur die erste Stufe" in r for r in probe.reasons)


def test_l_single_writer_blockiert_alle_module(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "stage")
    write_journal(
        journ,
        {"modul": "explorer", "stufe": "stage", "status": "offen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("blockiert ALLE Module" in r for r in probe.reasons)


def test_m_vorgaenger_stufe_fehlt(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "gate")
    write_journal(
        journ,
        {"modul": "explorer", "stufe": "stage", "status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = probe_module_update(MODUL, "gate", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("Vorgaenger-Stufe" in r for r in probe.reasons)


def test_n_journal_kaputt(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "stage")

    write_journal(journ, "")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("leere Zeile" in r for r in probe.reasons)

    write_journal(journ, "kein json{")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("kein gueltiges JSON" in r for r in probe.reasons)

    write_journal(journ, "[1,2]")
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("kein JSON-Objekt" in r for r in probe.reasons)

    write_journal(
        journ,
        {"modul": "unbekannt", "stufe": "stage", "status": "offen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("kein bekanntes Update-Modul" in r for r in probe.reasons)

    write_journal(
        journ,
        {"modul": MODUL, "stufe": "flug", "status": "offen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("keine bekannte Stufe" in r for r in probe.reasons)

    write_journal(
        journ,
        {"modul": MODUL, "stufe": "stage", "status": "vielleicht", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = probe_module_update(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("weder 'offen' noch" in r for r in probe.reasons)


def test_o_record_update_erlaubt_schreibt_offen(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "stage")
    probe = record_update(MODUL, "stage", host="h1", timestamp="2026-01-01T00:00:00Z", journal_path=journ, evidence_dir=ev)
    assert probe.allowed, probe.reasons
    assert journ.exists()
    lines = journ.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    assert last["modul"] == MODUL
    assert last["stufe"] == "stage"
    assert last["status"] == "offen"
    assert last["host"] == "h1"


def test_p_record_update_blockiert_schreibt_nichts(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    probe = record_update(MODUL, "stage", host="h1", timestamp="2026-01-01T00:00:00Z", journal_path=journ, evidence_dir=ev)
    assert not probe.allowed
    assert any("Nachweis fehlt:" in r for r in probe.reasons)
    assert not journ.exists()


def test_q_confirm_green(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"
    write_evidence(ev, MODUL, "stage")

    # Ohne offenen Eintrag (nur gruen im Journal)
    write_journal(
        journ,
        {"modul": MODUL, "stufe": "stage", "status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = confirm_green(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert not probe.allowed
    assert any("nichts zu bestaetigen" in r for r in probe.reasons)

    # Ohne Journal komplett
    journ2 = tmp_path / "journal2.jsonl"
    probe = confirm_green(MODUL, "stage", evidence_dir=ev, journal_path=journ2)
    assert not probe.allowed
    assert any("kein offener Eintrag" in r for r in probe.reasons)

    # OK-Pfad: offener Eintrag wird gruen bestaetigt
    write_journal(
        journ,
        {"modul": MODUL, "stufe": "stage", "status": "offen", "host": "h9", "timestamp": "2026-01-01T00:00:00Z"},
    )
    probe = confirm_green(MODUL, "stage", evidence_dir=ev, journal_path=journ)
    assert probe.allowed, probe.reasons
    lines = journ.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    assert last["modul"] == MODUL
    assert last["stufe"] == "stage"
    assert last["status"] == "gruen"
    assert last["host"] == "h1"


def test_r_rollback(tmp_path):
    ev = tmp_path / "evidence"
    journ = tmp_path / "journal.jsonl"

    # OK: alle drei Rollback-Nachweise vorhanden und gruen
    for name in ("rollback_code", "rollback_manifest", "rollback_daten"):
        write_rollback(ev, MODUL, name=name)
    probe = rollback_module(MODUL, host="h1", timestamp="2026-01-01T00:00:00Z", evidence_dir=ev)
    assert probe.allowed, probe.reasons
    assert probe.stufe == "activate"
    assert probe.reasons == ()
    # rollback schreibt niemals ins Journal
    assert not journ.exists()

    # Nur 2 von 3 Nachweisen
    ev2 = tmp_path / "evidence2"
    write_rollback(ev2, MODUL, name="rollback_code")
    write_rollback(ev2, MODUL, name="rollback_manifest")
    probe = rollback_module(MODUL, host="h1", timestamp="2026-01-01T00:00:00Z", evidence_dir=ev2)
    assert not probe.allowed
    assert any("Rollback-Nachweis fehlt" in r for r in probe.reasons)

    # Kaputtes JSON
    ev3 = tmp_path / "evidence3"
    for name in ("rollback_code", "rollback_manifest", "rollback_daten"):
        write_rollback(ev3, MODUL, name=name)
    (ev3 / MODUL / "rollback_code.json").write_text("kein json{", encoding="utf-8")
    probe = rollback_module(MODUL, host="h1", timestamp="2026-01-01T00:00:00Z", evidence_dir=ev3)
    assert not probe.allowed
    assert any("kein gueltiges JSON" in r for r in probe.reasons)

    # Falsches modul im Doc
    ev4 = tmp_path / "evidence4"
    for name in ("rollback_code", "rollback_manifest", "rollback_daten"):
        write_rollback(ev4, MODUL, name=name)
    doc = {"modul": "explorer", "status": "gruen", "host": "h1", "timestamp": "2026-01-01T00:00:00Z"}
    (ev4 / MODUL / "rollback_code.json").write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    probe = rollback_module(MODUL, host="h1", timestamp="2026-01-01T00:00:00Z", evidence_dir=ev4)
    assert not probe.allowed
    assert any("erwartet" in r for r in probe.reasons)

    # Status rot
    ev5 = tmp_path / "evidence5"
    for name in ("rollback_code", "rollback_manifest", "rollback_daten"):
        write_rollback(ev5, MODUL, name=name)
    write_rollback(ev5, MODUL, name="rollback_code", status="rot")
    probe = rollback_module(MODUL, host="h1", timestamp="2026-01-01T00:00:00Z", evidence_dir=ev5)
    assert not probe.allowed
    assert any("BACH20-10 §3" in r for r in probe.reasons)

    # Host leer
    ev6 = tmp_path / "evidence6"
    for name in ("rollback_code", "rollback_manifest", "rollback_daten"):
        write_rollback(ev6, MODUL, name=name)
    write_rollback(ev6, MODUL, name="rollback_code", host="")
    probe = rollback_module(MODUL, host="h1", timestamp="2026-01-01T00:00:00Z", evidence_dir=ev6)
    assert not probe.allowed
    assert any("keine nicht-leere Zeichenkette" in r for r in probe.reasons)
