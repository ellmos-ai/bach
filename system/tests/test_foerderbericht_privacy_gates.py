# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB-15 Datenschutz-Auflagen aus der Zweitpruefung O2 (bach#666).

N1 Tarnorte sind keine echten Orte, N2 Cloud-Modus ohne NER verweigert, N3 nicht
platzierte Ziele bleiben sichtbar, N4/N5 Empfehlung/leere Pflichtfelder, N6
Zusatzanweisungen, Wissensdatenbank und Datumsvarianten im Cloud-Prompt.
Nur synthetische Daten, neutrale Vorlage, kein Netz.
"""

import copy
import json
import random
import re
import sys
from pathlib import Path

import pytest
from docx import Document

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import anonymizer_service  # noqa: E402
from hub._services.document import foerderbericht_pipeline as fp  # noqa: E402
from hub._services.document import report_workflow_service as rws  # noqa: E402
from hub._services.document.anonymizer_service import DocumentAnonymizer, _apply_replacements  # noqa: E402
from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline  # noqa: E402

DATE_VARIANTS = ["14.05.2017", "14.5.2017", "14. Mai 2017", "2017-05-14"]


def _case(base: Path) -> dict:
    client = base / "data_roh" / "Leonhardt, Jonas"
    client.mkdir(parents=True, exist_ok=True)
    (client / "Aktendeckblatt.txt").write_text(
        "Name: Jonas Leonhardt\nGeboren am 14.05.2017\nAdresse: Gartenstraße 18, 79102 Freiburg\n"
        "Eltern: Sabine Leonhardt, Markus Leonhardt\n", encoding="utf-8")
    (client / "Verlaufsprotokoll_2025.txt").write_text(
        "Jonas Leonhardt (geb. 14.5.2017, laut Arztbrief 14. Mai 2017, im Formular 2017-05-14) "
        "zeigte Fortschritte in der Feinmotorik.\n", encoding="utf-8")
    return dict(client_name="Jonas Leonhardt", geburtsdatum="14.05.2017",
                parent_names=["Sabine Leonhardt", "Markus Leonhardt"],
                client_address="Gartenstraße 18, 79102 Freiburg", additional_terms=["Gartenstraße"])


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    """Cloud-Lauf mit abgefangenem Modellaufruf; NER-Pruefung bewusst freigegeben (eigene Tests unten)."""
    template = tmp_path / "vorlage.docx"
    doc = Document()
    doc.add_paragraph("{{NAME}} {{GEBURTSDATUM}} {{AKTUELLE_ENTWICKLUNGEN}}")
    doc.save(template)
    monkeypatch.setattr(rws, "TEMPLATE_PATH", template)
    monkeypatch.setattr(rws, "BACH_BASE", tmp_path / "kein-generator")
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""), raising=False)
    seen = {}

    def fake_llm(self, prompt, backend, model):
        seen["prompt"] = prompt
        return json.dumps({"aktuelle_entwicklungen": "Fortschritte."})

    monkeypatch.setattr(FoerderberichtPipeline, "_call_llm", fake_llm)
    return tmp_path, seen


# --- N6: Zusatzanweisungen, Wissensdatenbank, Datumsvarianten ---------------------------------

def test_cloud_prompt_has_no_case_data_from_instructions_kb_or_date_variants(cloud):
    base, seen = cloud
    kb = base / "kb" / "ICF"
    kb.mkdir(parents=True)
    (kb / "notiz.md").write_text("ICF-Notiz: Jonas Leonhardt profitiert von Struktur.", encoding="utf-8")
    meta = _case(base)

    res = FoerderberichtPipeline(base_path=base).run_full_pipeline(
        modus="cloud", auto_cleanup=False,
        custom_instructions="Bitte das Gespraech mit Jonas' Mutter Sabine Leonhardt betonen "
                            "(Geburtstag 14. Mai 2017, ISO 2017-05-14).",
        **meta)

    assert res.success, res.error
    low = seen["prompt"].lower()
    for forbidden in ["jonas", "leonhardt", "sabine", *[v.lower() for v in DATE_VARIANTS]]:
        assert forbidden not in low, f"Klientendatum im Cloud-Prompt: {forbidden!r}"
    assert "fortschritte" in low and "struktur" in low  # Inhalt bleibt, nur die Identitaet faellt


def test_prompt_gate_blocks_remaining_case_data_without_naming_it(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    service = rws.ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    service.create_temp_profile(session, "Jonas Leonhardt", "14.05.2017")

    class Bundle:  # klein geschrieben: die Ersetzung trifft es nicht, die Sperre muss es finden
        core_text = "Kontakt: familie jonas leonhardt (mail-verteiler)"
        stufe2_text = ""

    session.bundle = Bundle()
    with pytest.raises(Exception) as exc:
        service.generate_prompt(session, include_wissensdatenbank=False)
    assert "Datenschutz-Sperre" in str(exc.value)
    assert "jonas" not in str(exc.value).lower()


# --- N1: Tarnorte ------------------------------------------------------------------------------

def test_fake_addresses_use_no_real_places():
    for _ in range(60):
        street_nr, place = anonymizer_service._generate_fake_address().split(", ", 1)
        plz, town = place.split(" ", 1)
        assert re.fullmatch(r"00\d{3}", plz), f"reale PLZ als Tarnwert: {plz}"  # 00xxx gibt es nicht
        assert "Tarn" in town and "Tarn" in street_nr
    assert all("Tarn" in anonymizer_service._generate_fake_institution("Grundschule X") for _ in range(20))


def test_case_town_never_survives_as_pseudonym(tmp_path, monkeypatch):
    """Frueher: Tarnort zufaellig gleich dem echten Ort (Landkreis Waldshut) -> Ort blieb stehen."""
    rnd = random.SystemRandom()
    monkeypatch.setattr(anonymizer_service.secrets, "choice",
                        lambda seq: next((s for s in seq if "Waldshut" in str(s)), None) or rnd.choice(seq))
    service = rws.ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session, "Jonas Leonhardt", "14.05.2017", client_address="Lindenstr. 4, 79761 Waldshut")

    text = "Familie in Waldshut (Lindenstr. 4, 79761 Waldshut); Schule ebenfalls in Waldshut."
    out, _ = _apply_replacements(text, DocumentAnonymizer._sorted_replacements(profile.to_anonym_profile()))
    for real in ("waldshut", "79761", "lindenstr"):
        assert real not in out.lower(), f"echter Ort im Ergebnis: {real}"
        assert not any(real in v.lower() for v in profile.mappings["addresses"].values())


# --- N2: Cloud-Modus ohne NER ------------------------------------------------------------------

def _no_llm(monkeypatch):
    calls = []
    monkeypatch.setattr(FoerderberichtPipeline, "_call_llm", lambda self, *a: calls.append(a) or "{}")
    return calls


def test_cloud_mode_refuses_without_spacy(tmp_path, monkeypatch):
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(anonymizer_service, "SPACY_AVAILABLE", False)
    calls = _no_llm(monkeypatch)
    meta = _case(tmp_path)

    res = FoerderberichtPipeline(base_path=tmp_path).run_full_pipeline(modus="cloud", auto_cleanup=False, **meta)

    assert not res.success
    assert "spaCy" in res.error and "lokal" in res.error
    assert calls == [] and not (tmp_path / "data_bundled" / "prompt.txt").exists()


def test_cloud_mode_refuses_when_a_ner_model_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(anonymizer_service, "SPACY_AVAILABLE", True)
    monkeypatch.setattr(anonymizer_service, "_get_spacy_model",
                        lambda name: None if name == "de_core_news_lg" else object())
    calls = _no_llm(monkeypatch)
    meta = _case(tmp_path)

    res = FoerderberichtPipeline(base_path=tmp_path).run_full_pipeline(modus="cloud", auto_cleanup=False, **meta)

    assert not res.success and "de_core_news_lg" in res.error
    assert calls == []


def test_lokal_mode_does_not_need_ner(tmp_path, monkeypatch):
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(anonymizer_service, "SPACY_AVAILABLE", False)
    calls = _no_llm(monkeypatch)
    monkeypatch.setattr(FoerderberichtPipeline, "finish_report",
                        lambda self, **kw: kw.get("_result") or fp.PipelineResult(success=True))
    _case(tmp_path)

    FoerderberichtPipeline(base_path=tmp_path).run_full_pipeline(modus="lokal", client_name="Jonas Leonhardt")

    assert len(calls) == 1


# --- N3-N5: Vorlagen-Fallback ------------------------------------------------------------------

SCHEMA = {
    "stammdaten": {"name": "Felix Muster", "geburtsdatum": "01.01.2017", "landkreis": "Beispielkreis",
                   "zeichen_amt": "AZ-0001", "amt_adresse": "Amtsweg 1", "sachbearbeiter": "Herr Muster",
                   "therapeut_einzel": "Frau Test", "therapeut_gruppe": "", "kopie_an": "",
                   "kostenzusage_ende": "31.12.2026", "weiterbewilligung_ab": "01.01.2027",
                   "foerderungsbeginn": "01.01.2025",
                   "diagnosen": [{"icd_code": "F00.0", "bezeichnung": "Synth", "diagnostiker": "T", "datum": "2023"}]},
    "foerderziele": [
        {"icf_code": "D315", "zielformulierung": "Z1", "ist_stand": "I1", "erreicht": 2, "grund_nichterreichung": None},
    ],
    "bereiche": {"selbstversorgung": {"aktiv": True, "text": "B1"}},
    "umweltfaktoren": {"kommunikation": {"aktiv": True, "text": "U1"}},
    "besondere_faehigkeiten": "BF",
    "neue_ziele": [{"icf_code": "D7503", "kapitel": "d7", "zielformulierung": "N1", "ist_stand": "S1"}],
    "empfehlung": {"verlaengerung": True, "begruendung": [], "umfang": "2 Stunden", "sonstige_empfehlung": ""},
    "abschluss": {"aktuelle_entwicklungen": "AE", "bedingungsmodell": "BM"},
}
FIELDS = [
    "{{NAME}} {{GEBURTSDATUM}} {{Zeichen Amtschreiben}} {{SACHBEARBEITER}} {{THERAPEUT_EINZEL}} "
    "{{THERAPEUT_GRUPPE}} {{KOPIE_AN}} {{DIAGNOSE_1}}",
    "Empfehlung: {{Empfehlung}} ({{Weiterbewilligung oder Beendigung}}), {{UMFANG}}",
    "{{AKTUELLE_ENTWICKLUNGEN}} {{BEDINGUNGSMODELL}} {{BESONDERE_FAEHIGKEITEN}}",
]


def _template(path, t4_rows=1):
    doc = Document()
    for line in FIELDS:
        doc.add_paragraph(line)
    doc.add_table(rows=1, cols=2)
    doc.add_table(rows=1, cols=2)
    icf = doc.add_table(rows=1, cols=6)
    cells = icf.add_row().cells
    cells[0].text, cells[1].text = "D315", "Kapitel"
    for cell, suffix in zip(cells[2:], ["Ziel", "Ist", "E", "G"]):
        cell.text = "{D315-" + suffix + "}"
    doc.add_table(rows=1 + t4_rows, cols=4)
    doc.save(path)
    return path


def _fallback(tmp_path, monkeypatch, data, t4_rows=1):
    monkeypatch.setattr(rws, "TEMPLATE_PATH", _template(tmp_path / "vorlage.docx", t4_rows))
    monkeypatch.setattr(rws, "BACH_BASE", tmp_path / "kein-generator")
    monkeypatch.delenv("FOERDERBERICHT_TEMPLATE", raising=False)
    service = object.__new__(rws.ReportWorkflowService)
    service.base_path = tmp_path
    profile = rws.TempAnonymProfile(tarnname="Felix Muster", original_name="Max Probe",
                                    fake_geburtsdatum="01.01.2017", mappings={"names": {}, "dates": {}})
    session = rws.WorkflowSession(session_id="synthetic", profile=profile)
    path = service._generate_from_json(session, copy.deepcopy(data), True)
    assert path is not None, session.error_message
    doc = Document(str(path))
    body = "\n".join(p.text for p in doc.paragraphs)
    return session, doc, body


def test_unplaced_icf_goal_is_appended_and_warned(tmp_path, monkeypatch):
    data = copy.deepcopy(SCHEMA)
    data["foerderziele"].append({"icf_code": "D999", "zielformulierung": "ZIEL_OHNE_ZEILE",
                                 "ist_stand": "x", "erreicht": 3, "grund_nichterreichung": None})
    session, doc, _ = _fallback(tmp_path, monkeypatch, data)

    rows = [[c.text for c in r.cells] for r in doc.tables[2].rows]
    assert any(r[0] == "D999" and r[2] == "ZIEL_OHNE_ZEILE" and r[4] == "(3)" for r in rows)
    assert any("D999" in w for w in session.warnings)


def test_new_goals_beyond_template_rows_are_added_and_warned(tmp_path, monkeypatch):
    data = copy.deepcopy(SCHEMA)
    data["neue_ziele"] = [{"icf_code": f"D75{i}", "kapitel": "d7", "zielformulierung": f"NZ{i}", "ist_stand": "s"}
                          for i in range(3)]
    session, doc, _ = _fallback(tmp_path, monkeypatch, data, t4_rows=1)

    texts = [r.cells[2].text for r in doc.tables[3].rows]
    assert all(f"NZ{i}" in texts for i in range(3))
    assert any("neue" in w.lower() and "Ziel" in w for w in session.warnings)


def test_textual_no_means_termination_and_unclear_value_blanks_with_warning(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    data = copy.deepcopy(SCHEMA)
    data["empfehlung"]["verlaengerung"] = "nein"
    _, _, body = _fallback(tmp_path / "a", monkeypatch, data)
    assert "Empfehlung: die Beendigung (Beendigung)," in body

    data["empfehlung"]["verlaengerung"] = "unklar"
    session, _, body = _fallback(tmp_path / "b", monkeypatch, data)
    line = next(x for x in body.splitlines() if x.startswith("Empfehlung:"))
    assert "Weiterbewilligung" not in line and "verlaengerung" not in line
    assert any("Empfehlung" in w for w in session.warnings)


def test_empty_required_fields_are_warned_optional_ones_not(tmp_path, monkeypatch):
    data = copy.deepcopy(SCHEMA)
    data["stammdaten"]["zeichen_amt"] = ""
    data["stammdaten"]["diagnosen"] = []
    session, _, _ = _fallback(tmp_path, monkeypatch, data)

    joined = " | ".join(session.warnings)
    assert "Zeichen Amtschreiben" in joined and "DIAGNOSE_1" in joined
    assert "THERAPEUT_GRUPPE" not in joined and "KOPIE_AN" not in joined
