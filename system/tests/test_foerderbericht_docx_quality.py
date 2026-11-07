# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""PB-15: Der Foerderbericht muss ein echter Bericht aus der Vorlage sein.

Nur synthetische Daten und eine neutrale, im Test erzeugte Vorlage. Die private
private Vorlage und der private Generator werden nie gelesen.
"""

import re

import pytest
from docx import Document

from hub._services.document import report_workflow_service as module
from hub._services.document.report_workflow_service import (
    ReportWorkflowService,
    TempAnonymProfile,
    WorkflowSession,
)

REQUIRED_HEADINGS = ["Stammdaten", "Aktuelle Entwicklungen", "Empfehlung"]


def make_template(path):
    doc = Document()
    doc.add_heading("Stammdaten", 1)
    doc.add_paragraph("Name: {{NAME}}")
    doc.add_paragraph("Geburtsdatum: {{GEBURTSDATUM}}")
    doc.add_heading("Aktuelle Entwicklungen", 1)
    doc.add_paragraph("{{AKTUELLE_ENTWICKLUNGEN}}")
    doc.add_heading("Empfehlung", 1)
    doc.add_paragraph("{{EMPFEHLUNG}}")
    doc.save(path)
    return path


def service_with_session(tmp_path, monkeypatch, template=True):
    monkeypatch.setattr(module, "BACH_BASE", tmp_path / "kein-generator")
    monkeypatch.setattr(
        module, "TEMPLATE_PATH",
        make_template(tmp_path / "vorlage.docx") if template else tmp_path / "fehlt.docx",
    )
    service = object.__new__(ReportWorkflowService)
    service.base_path = tmp_path
    profile = TempAnonymProfile(
        tarnname="Felix Bergmann",
        original_name="Jonas Leonhardt",
        fake_geburtsdatum="01.01.2017",
        mappings={"names": {"Leonhardt": "Bergmann"}, "dates": {"14.05.2017": "01.01.2017"}},
    )
    return service, WorkflowSession(session_id="synthetic", profile=profile)


REPORT_JSON = {
    "aktuelle_entwicklungen": "Felix Bergmann hat die Feinmotorik verbessert.",
    "empfehlung": "Weiterbewilligung fuer Felix Bergmann.",
}


def test_json_report_is_filled_into_template_sections(tmp_path, monkeypatch):
    service, session = service_with_session(tmp_path, monkeypatch)
    path = service._generate_from_json(session, REPORT_JSON, True)

    doc = Document(str(path))
    texts = [p.text for p in doc.paragraphs]
    assert len([t for t in texts if t.strip()]) >= 6
    for heading in REQUIRED_HEADINGS:
        assert heading in texts, f"Pflichtueberschrift fehlt: {heading}"
    body = "\n".join(texts)
    assert "Jonas Leonhardt hat die Feinmotorik verbessert." in body
    assert "Weiterbewilligung fuer Jonas Leonhardt." in body
    assert "Felix Bergmann" not in body
    assert not re.search(r"[{}\"]|\{\{", body), "JSON-Reste oder Platzhalter im Bericht"


def test_json_report_without_template_is_an_error_not_a_document(tmp_path, monkeypatch):
    service, session = service_with_session(tmp_path, monkeypatch, template=False)
    result = service._generate_from_json(session, REPORT_JSON, True)

    assert result is None
    assert session.status == "error"
    assert "Vorlage" in session.error_message
    assert "fehlt.docx" in session.error_message
    assert not list((tmp_path / "output_berichte").glob("*.docx"))


def test_unmatched_sections_and_placeholders_are_reported(tmp_path, monkeypatch):
    service, session = service_with_session(tmp_path, monkeypatch)
    data = dict(REPORT_JSON, zusatz_ohne_platzhalter="Nur im JSON.")
    del data["empfehlung"]
    path = service._generate_from_json(session, data, True)

    assert path is not None
    joined = " ".join(session.warnings)
    assert "zusatz_ohne_platzhalter" in joined  # Inhalt ohne Platz in der Vorlage
    assert "EMPFEHLUNG" in joined  # Vorlagenfeld ohne Inhalt
