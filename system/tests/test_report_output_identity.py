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
