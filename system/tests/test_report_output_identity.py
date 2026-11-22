"""Synthetic output identity and non-cascading report restoration regressions."""

import pytest
from docx import Document
from hub._services.document import report_workflow_service as module
from hub._services.document.report_workflow_service import (
    ReportWorkflowService,
    TempAnonymProfile,
    WorkflowSession,
)


def synthetic(tmp_path, monkeypatch, mode="cloud", template=True):
    service = object.__new__(ReportWorkflowService)
    service.base_path = tmp_path
    original = "Jonas Leonhardt"
    alias = "Felix Bergmann" if mode == "cloud" else original
    profile = TempAnonymProfile(
        tarnname=alias,
        original_name=original,
        fake_geburtsdatum="01.01.2017",
        mappings={
            "names": {"Leonhardt": "Bergmann"} if mode == "cloud" else {},
            "dates": {"14.05.2017": "01.01.2017"},
            "misc": {"Frau Bergmann": "BEGRIFF_01"} if mode == "cloud" else {},
        },
    )
    session = WorkflowSession(session_id="synthetic", profile=profile)
    template_path = tmp_path / "template.docx"
    if template:
        doc = Document()
        doc.add_paragraph("{{NAME}} | {{VORNAME}} | {{NACHNAME}} | {{GEBURTSDATUM}}")
        doc.add_paragraph("{{BERICHT_TEXT}}")
        doc.save(template_path)
    monkeypatch.setattr(module, "TEMPLATE_PATH", template_path)
    return service, session


def document_text(path):
    return "\n".join(paragraph.text for paragraph in Document(path).paragraphs)


def test_missing_explicit_generator_reports_failure_without_fallback(tmp_path, monkeypatch):
    service, session = synthetic(tmp_path, monkeypatch)
    monkeypatch.setenv("FOERDERBERICHT_GENERATOR", str(tmp_path / "missing.py"))

    result = service.generate_report(session, '{"summary":"Synthetischer Text"}')

    assert result is None
    assert session.status == "error"
    assert session.error_message.startswith("Generator nicht gefunden")
    assert not list(tmp_path.rglob("Foerderbericht_*.docx"))


@pytest.mark.parametrize("mode", ["local", "cloud"])
@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("template", [False, True])
def test_markdown_filename_and_content_follow_explicit_identity_policy(
    tmp_path, monkeypatch, mode, restore, template
):
    service, session = synthetic(tmp_path, monkeypatch, mode, template)
    alias = session.profile.tarnname
    response = "# Aktuelle Entwicklungen\n\n" + alias + " trifft BEGRIFF_01."
    path = service._generate_from_markdown(session, response, restore, None)
    if not template:
        # PB-15: wie beim JSON-Weg kein Ersatzdokument, sondern eine klare Fehlermeldung
        assert path is None and session.status == "error"
        assert "Vorlage" in session.error_message
        assert not list((tmp_path / "output_berichte").glob("*.docx"))
        return
    expected_name = session.profile.original_name if restore else alias
    assert path.name.startswith("Foerderbericht_" + expected_name + "_")
    text = document_text(path)
    if mode == "cloud":
        if restore:
            assert "Jonas Leonhardt" in text
            assert "Frau Bergmann" in text
            assert "Frau Leonhardt" not in text
            assert alias not in text and "BEGRIFF_01" not in text
        else:
            assert "Jonas" not in text and "Leonhardt" not in text
            assert alias in text
            if template:
                assert "14.05.2017" not in text
                assert "01.01.2017" in text


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("template", [False, True])
def test_json_fallback_retains_public_identity_choice_without_second_restoration(
    tmp_path, monkeypatch, restore, template
):
    service, session = synthetic(tmp_path, monkeypatch, template=template)
    monkeypatch.setattr(module, "BACH_BASE", tmp_path / "missing-generator")
    path = service._generate_from_json(
        session, {"summary": "Felix Bergmann trifft BEGRIFF_01."}, restore
    )
    if not template:
        # PB-15: ohne Vorlage kein Ersatzdokument, sondern eine klare Fehlermeldung
        assert path is None and session.status == "error"
        assert "Vorlage" in session.error_message
        return
    text = document_text(path)
    name = "Jonas Leonhardt" if restore else "Felix Bergmann"
    assert path.name.startswith("Foerderbericht_" + name + "_")
    assert name in text
    if restore:
        assert "Frau Bergmann" in text and "Frau Leonhardt" not in text
        assert "Felix Bergmann" not in text
    else:
        assert "Jonas" not in text and "Leonhardt" not in text
        assert "BEGRIFF_01" in text


def test_restoration_is_simultaneous_longest_first_and_preserves_email_boundaries(
    tmp_path, monkeypatch
):
    service, session = synthetic(tmp_path, monkeypatch, template=False)
    source = "Felix Bergmann trifft BEGRIFF_01; Bergmann; Bergmannschaft; Bergmann@example.test"
    expected = "Jonas Leonhardt trifft Frau Bergmann; Leonhardt; Bergmannschaft; Bergmann@example.test"
    assert service._deanonymize_text(source, session.profile) == expected
    assert service._deanonymize_json({"nested": [source]}, session.profile) == {
        "nested": [expected]
    }


@pytest.mark.parametrize(
    "source,alias,original",
    [
        ("Telefon +49 123 456.", "+49 123 456", "+49 987 654"),
        ("Telefon 0123 456.", "0123 456", "0987 654"),
        ("Adresse (Beispielweg 1), Ende.", "Beispielweg 1", "Originalweg 9"),
        ("Adresse (Beispielweg 1), Ende.", "(Beispielweg 1)", "(Originalweg 9)"),
        (
            "Kontakt person001@example.test.",
            "person001@example.test",
            "original@example.test",
        ),
        ("Person001, Person001s; (Person001)!", "Person001", "Originalperson"),
        (
            "Kontakt Person001@example.test und Person001.",
            "Person001",
            "Originalperson",
        ),
    ],
)
def test_simultaneous_helper_preserves_existing_phone_address_email_boundaries(
    source, alias, original
):
    from hub._services.document.anonymizer_service import _replace_word_boundary

    expected, _ = _replace_word_boundary(source, alias, original)
    assert module._restore_original_values(source, {alias: original}) == expected


@pytest.mark.parametrize("failed_attempt", ["partial_failure", "no_output", "invalid_docx"])
def test_failed_generation_keeps_the_previous_report(tmp_path, monkeypatch, failed_attempt):
    service, session = synthetic(tmp_path, monkeypatch)
    generator = tmp_path / "fixture_generator.py"
    generator.write_text(
        '''
from pathlib import Path
from types import SimpleNamespace
from docx import Document

def fill_template(template_path, report_data, output_path):
    text = report_data["summary"]
    target = Path(output_path)
    if text == "partial_failure":
        target.write_bytes(b"unfinished")
        return SimpleNamespace(success=False, errors=["synthetischer Schreibfehler"])
    if text == "no_output":
        return SimpleNamespace(success=True)
    if text == "invalid_docx":
        target.write_bytes(b"not a DOCX")
        return SimpleNamespace(success=True)
    doc = Document(template_path)
    doc.add_paragraph(text)
    doc.save(target)
    return SimpleNamespace(success=True)
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("FOERDERBERICHT_GENERATOR", str(generator))

    original_path = service.generate_report(session, '{"summary":"Erster Bericht"}')
    original_bytes = original_path.read_bytes()
    assert "Erster Bericht" in document_text(original_path)

    failed = service.generate_report(session, '{"summary":"' + failed_attempt + '"}')
    assert failed is None
    assert session.status == "error"
    assert session.error_message.startswith("Generator-Fehler")
    assert original_path.read_bytes() == original_bytes
    assert list(original_path.parent.iterdir()) == [original_path]

    retry = service.generate_report(session, '{"summary":"Überarbeiteter Bericht"}')
    assert retry == original_path
    assert "Überarbeiteter Bericht" in document_text(retry)
    assert session.status == "completed"


def test_markdown_write_failure_preserves_the_previous_report(tmp_path, monkeypatch):
    from pathlib import Path
    from docx.document import Document as WordDocument

    service, session = synthetic(tmp_path, monkeypatch)
    original_path = service.generate_report(session, "# Erster Bericht")
    original_bytes = original_path.read_bytes()

    def partial_save(_doc, target):
        Path(target).write_bytes(b"unfinished")
        raise OSError("synthetic write failure")

    monkeypatch.setattr(WordDocument, "save", partial_save)
    assert service.generate_report(session, "# Überarbeiteter Bericht") is None
    assert session.status == "error"
    assert original_path.read_bytes() == original_bytes
    assert list(original_path.parent.iterdir()) == [original_path]
