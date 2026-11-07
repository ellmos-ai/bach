# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB-15 Nacharbeit: Vorlagen-Fallback fuer schema-foermiges Bericht-JSON.

Nur synthetische Daten und eine neutrale, im Test erzeugte Vorlage (Platzhalter-
namen stammen aus dem oeffentlichen Code). Echte Vorlage und Generator werden
nie gelesen.
"""

import copy
import re
import textwrap

import pytest
from docx import Document

from hub._services.document import report_workflow_service as module
from hub._services.document.report_workflow_service import (
    ReportWorkflowService,
    TempAnonymProfile,
    WorkflowSession,
)

SCHEMA_JSON = {
    "stammdaten": {
        "name": "Felix Bergmann",
        "geburtsdatum": "01.01.2017",
        "landkreis": "Beispielkreis",
        "zeichen_amt": "AZ-0001",
        "amt_adresse": "Amtsweg 1, 00000 Beispielstadt",
        "sachbearbeiter": "Herr Muster",
        "therapeut_einzel": "Frau Test",
        "therapeut_gruppe": "",
        "kopie_an": "",
        "kostenzusage_ende": "31.12.2026",
        "weiterbewilligung_ab": "01.01.2027",
        "foerderungsbeginn": "01.01.2025",
        "diagnosen": [
            {"icd_code": "F00.0", "bezeichnung": "Synthetische Diagnose", "diagnostiker": "Testzentrum", "datum": "10.05.2023"}
        ],
    },
    "foerderziele": [
        {"icf_code": "d315", "zielformulierung": "Sprechen im Unterricht", "ist_stand": "Beteiligt sich", "erreicht": 2, "grund_nichterreichung": None},
        {"icf_code": "d330", "zielformulierung": "Sprechen vor der Klasse", "ist_stand": "Braucht Karten", "erreicht": 1, "grund_nichterreichung": None},
    ],
    "bereiche": {
        "selbstversorgung": {"aktiv": True, "text": "Zieht sich selbststaendig an."},
        "gesellschaft_freizeit": {"aktiv": False, "text": ""},
    },
    "umweltfaktoren": {
        "kommunikation": {"aktiv": True, "text": "Reizarme Umgebung hilft."},
        "wahrnehmung": {"aktiv": False, "text": ""},
    },
    "besondere_faehigkeiten": "Gutes visuelles Gedaechtnis.",
    "empfehlung": {
        "verlaengerung": True,
        "begruendung": ["therapieziele_nicht_erreicht"],
        "umfang": "2 Stunden woechentlich",
        "sonstige_empfehlung": "Runder Tisch fortfuehren.",
    },
    "abschluss": {
        "aktuelle_entwicklungen": "Deutliche Fortschritte im Vertrauensaufbau.",
        "bedingungsmodell": "Gute Passung der Methodik.",
    },
}

SINGLE_FIELDS = [
    "{{NAME}} / {{GEBURTSDATUM}} / {{LANDKREIS}} / {{Zeichen Amtschreiben}}",
    "{{SACHBEARBEITER}} {{THERAPEUT_EINZEL}} {{KOSTENZUSAGE_ENDE}} {{WEITERBEWILLIGUNG_AB}} {{FOERDERUNGSBEGINN}}",
    "{{DIAGNOSE_1}}",
    "Empfehlung: {{Empfehlung}} ({{Weiterbewilligung oder Beendigung}}), {{UMFANG}}, {{SONSTIGE_EMPFEHLUNG}}",
    "{{BEREICH_SELBSTVERSORGUNG}}",
    "{{BEREICH_GESELLSCHAFT_FREIZEIT}}",
    "{{UMWELT_KOMMUNIKATION}}",
    "{{UMWELT_WAHRNEHMUNG}}",
    "{{BESONDERE_FAEHIGKEITEN}}",
    "{{AKTUELLE_ENTWICKLUNGEN}}",
    "{{BEDINGUNGSMODELL}}",
]


def make_schema_template(path):
    doc = Document()
    doc.add_heading("Stammdaten", 1)
    for line in SINGLE_FIELDS:
        doc.add_paragraph(line)
    doc.add_table(rows=1, cols=2)  # Tabelle 1 und 2: Platzhalter der Vorlage
    doc.add_table(rows=1, cols=2)
    icf = doc.add_table(rows=1, cols=6)  # Tabelle 3: ICF-Kerntabelle
    for cell, text in zip(icf.rows[0].cells, ["Code", "Kapitel", "Ziel", "Ist", "E", "G"]):
        cell.text = text
    for code in ("D315", "D330", "D999"):
        cells = icf.add_row().cells
        cells[0].text = code
        cells[1].text = "Kapitel"
        for cell, suffix in zip(cells[2:], ["Ziel", "Ist", "E", "G"]):
            cell.text = "{" + code + "-" + suffix + "}"
    doc.save(path)
    return path


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "BACH_BASE", tmp_path / "kein-generator")
    monkeypatch.setattr(module, "TEMPLATE_PATH", make_schema_template(tmp_path / "vorlage.docx"))
    monkeypatch.delenv("FOERDERBERICHT_TEMPLATE", raising=False)
    service = object.__new__(ReportWorkflowService)
    service.base_path = tmp_path
    profile = TempAnonymProfile(
        tarnname="Felix Bergmann",
        original_name="Jonas Leonhardt",
        fake_geburtsdatum="01.01.2017",
        mappings={"names": {"Leonhardt": "Bergmann"}, "dates": {"14.05.2017": "01.01.2017"}},
    )
    return service, WorkflowSession(session_id="synthetic", profile=profile), tmp_path


def body_of(path):
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


def icf_rows(path):
    table = Document(str(path)).tables[2]
    return [[c.text for c in row.cells] for row in table.rows]


def test_complete_schema_case_fills_template_without_warnings(setup):
    service, session, _ = setup
    path = service._generate_from_json(session, copy.deepcopy(SCHEMA_JSON), True)

    assert path is not None
    assert session.warnings == []
    body = body_of(path)
    assert "{{" not in body
    assert "F00.0 Synthetische Diagnose (Diagnose Testzentrum, 10.05.2023)" in body  # Diagnose
    assert "AZ-0001" in body  # Zeichen Amtschreiben
    assert "Empfehlung: die Weiterbewilligung (Weiterbewilligung)," in body
    assert "verlaengerung" not in body and "True" not in body and "False" not in body
    assert "Zieht sich selbststaendig an." in body  # Bereichsfeld
    assert "Reizarme Umgebung hilft." in body  # Umweltfeld
    assert "Jonas Leonhardt" in body and "Felix Bergmann" not in body


def test_fallback_still_fills_the_icf_table(setup):
    service, session, _ = setup
    path = service._generate_from_json(session, copy.deepcopy(SCHEMA_JSON), True)

    rows = icf_rows(path)
    assert ["D315", "Kapitel", "Sprechen im Unterricht", "Beteiligt sich", "(2)", ""] in rows
    assert any(r[0] == "D330" and r[2] == "Sprechen vor der Klasse" for r in rows)
    assert not any(r[0] == "D999" for r in rows)  # Zeile ohne Ziel entfaellt


def test_termination_is_not_reported_as_continuation(setup):
    service, session, _ = setup
    data = copy.deepcopy(SCHEMA_JSON)
    data["empfehlung"]["verlaengerung"] = False
    data["empfehlung"]["begruendung"] = ["ziele_erreicht"]
    path = service._generate_from_json(session, data, True)

    body = body_of(path)
    assert "Empfehlung: die Beendigung (Beendigung)," in body
    assert "Weiterbewilligung" not in body


def test_real_gaps_are_warned_but_filled_fields_are_not(setup):
    service, session, _ = setup
    data = copy.deepcopy(SCHEMA_JSON)
    del data["stammdaten"]["zeichen_amt"]
    del data["umweltfaktoren"]["kommunikation"]
    path = service._generate_from_json(session, data, True)

    assert path is not None
    joined = " | ".join(session.warnings)
    assert "Zeichen Amtschreiben" in joined and "UMWELT_KOMMUNIKATION" in joined
    for filled in ("AKTUELLE_ENTWICKLUNGEN", "BEDINGUNGSMODELL", "DIAGNOSE_1", "BEREICH_SELBSTVERSORGUNG"):
        assert filled not in joined, f"Fehlalarm: {filled}"


def test_markdown_response_without_template_is_an_error_not_a_document(setup, monkeypatch):
    service, session, tmp_path = setup
    monkeypatch.setattr(module, "TEMPLATE_PATH", tmp_path / "fehlt.docx")

    result = service._generate_from_markdown(session, "# Empfehlung\n\nWeiter so.", True, None)

    assert result is None
    assert session.status == "error" and "Vorlage" in session.error_message
    assert "fehlt.docx" in session.error_message
    assert str(tmp_path) not in session.error_message  # kein absoluter Pfad in der Meldung
    assert not list((tmp_path / "output_berichte").glob("*.docx"))


def write_generator(tmp_path, body):
    folder = tmp_path / "gen" / "system" / "agents" / "_experts" / "report_generator"
    folder.mkdir(parents=True)
    (folder / "generator.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path / "gen"


def test_present_but_failing_generator_is_an_error_not_a_silent_fallback(setup, monkeypatch):
    service, session, tmp_path = setup
    monkeypatch.setattr(module, "BACH_BASE", write_generator(tmp_path, """
        def fill_template(template_path, report_data, output_path):
            raise RuntimeError("synthetischer Generatorfehler")
    """))

    result = service._generate_from_json(session, copy.deepcopy(SCHEMA_JSON), True)

    assert result is None
    assert session.status == "error" and "Generator" in session.error_message
    assert not list((tmp_path / "output_berichte").glob("*.docx"))


def test_working_generator_is_still_preferred_over_the_fallback(setup, monkeypatch):
    service, session, tmp_path = setup
    monkeypatch.setattr(module, "BACH_BASE", write_generator(tmp_path, """
        from types import SimpleNamespace
        from docx import Document

        def fill_template(template_path, report_data, output_path):
            doc = Document()
            doc.add_paragraph("vom Generator")
            doc.save(output_path)
            return SimpleNamespace(success=True, errors=[])
    """))
    (tmp_path / "output_berichte").mkdir()

    path = service._generate_from_json(session, copy.deepcopy(SCHEMA_JSON), True)

    assert path is not None and "vom Generator" in body_of(path)
