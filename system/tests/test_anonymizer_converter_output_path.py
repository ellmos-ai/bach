# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression T-20261111-860504302 / BACH-Task 4120: Konverter-Rueckgabepfad (.msg/.doc -> .txt).

Fehlerbild: Die Konvertierung schreibt <name>.txt und entfernt nur die Stage-Kopie;
die nachfolgende Dateinamen-Anonymisierung bekam teils weiter den nicht mehr
vorhandenen .msg-Pfad (FileNotFoundError / WinError 2). Verbindlich ist der vom
Konverter gemeldete Ausgabepfad. Ausserdem darf eine Konvertierung/Umbenennung
nie still eine vorhandene Datei gleichen Namens ueberschreiben.

Nur erfundene Fixtures; die Textextraktoren (extract-msg/antiword/LibreOffice)
werden durch synthetische Texte ersetzt, Pfadlogik und Dateioperationen sind echt.
"""

import hashlib
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import anonymizer_service
from hub._services.document.anonymizer_service import AnonymProfile, DocumentAnonymizer
from hub._services.document.report_workflow_service import (
    ReportWorkflowService,
    TempAnonymProfile,
    WorkflowSession,
)

MSG_TEXT = "Von: Max Mustermann\nBetreff: Elternbrief\nMax Mustermann berichtet."
DOC_TEXT = "Aktendeckblatt Max Mustermann, geboren 02.03.2014."


def _profile():
    return AnonymProfile(
        client_id="K_TEST",
        tarnname="Felix Bergmann",
        fake_geburtsdatum="07.04.2014",
        mappings={"names": {"Max Mustermann": "Felix Bergmann"}, "dates": {"02.03.2014": "07.04.2014"}},
    )


def _fake_extractors(monkeypatch):
    monkeypatch.setattr(anonymizer_service, "_extract_msg_text", lambda p: MSG_TEXT)
    monkeypatch.setattr(anonymizer_service, "_extract_legacy_doc_text", lambda p: DOC_TEXT)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("suffix", [".msg", ".doc"])
def test_conversion_reports_the_actual_txt_output_path(tmp_path, monkeypatch, suffix):
    _fake_extractors(monkeypatch)
    stage = tmp_path / f"Mail{suffix}"
    stage.write_bytes(b"synthetic-binary")

    ok, count, output = DocumentAnonymizer().anonymize_file_with_output(str(stage), _profile())

    assert ok is True and count > 0
    assert output == tmp_path / "Mail.txt"
    assert output.exists() and not stage.exists()
    text = output.read_text(encoding="utf-8")
    assert "Max Mustermann" not in text and "Felix Bergmann" in text


@pytest.mark.parametrize("suffix", [".msg", ".doc"])
def test_anonymize_file_keeps_its_two_value_contract(tmp_path, monkeypatch, suffix):
    _fake_extractors(monkeypatch)
    stage = tmp_path / f"Mail{suffix}"
    stage.write_bytes(b"synthetic-binary")
    result = DocumentAnonymizer().anonymize_file(str(stage), _profile())
    assert isinstance(result, tuple) and len(result) == 2 and result[0] is True


@pytest.mark.parametrize("suffix,extractor", [(".msg", "_extract_msg_text"), (".doc", "_extract_legacy_doc_text")])
def test_failed_conversion_has_no_output_and_leaves_no_binary(tmp_path, monkeypatch, suffix, extractor):
    monkeypatch.setattr(anonymizer_service, extractor, lambda p: "")
    stage = tmp_path / f"Mail{suffix}"
    stage.write_bytes(b"synthetic-binary")

    ok, count, output = DocumentAnonymizer().anonymize_file_with_output(str(stage), _profile())

    assert (ok, count, output) == (False, 0, None)
    assert not stage.exists() and not (tmp_path / "Mail.txt").exists()


def test_in_place_format_reports_its_own_path(tmp_path):
    path = tmp_path / "Notiz.txt"
    path.write_text("Max Mustermann war da.", encoding="utf-8")
    ok, _count, output = DocumentAnonymizer().anonymize_file_with_output(str(path), _profile())
    assert ok and output == path and "Felix Bergmann" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("suffix", [".msg", ".doc"])
def test_conversion_never_overwrites_an_existing_txt(tmp_path, monkeypatch, suffix):
    _fake_extractors(monkeypatch)
    existing = tmp_path / "Mail.txt"
    existing.write_text("vorhandene, andere Quelle", encoding="utf-8")
    before = _sha(existing)
    stage = tmp_path / f"Mail{suffix}"
    stage.write_bytes(b"synthetic-binary")

    with pytest.raises(FileExistsError, match="Mail.txt"):
        DocumentAnonymizer().anonymize_file_with_output(str(stage), _profile())

    assert _sha(existing) == before          # vorhandene Datei unveraendert
    assert not stage.exists()                # kein unkonvertierter Rest im Output (fail-closed)


def test_filename_anonymization_never_overwrites_an_existing_file(tmp_path):
    existing = tmp_path / "Brief_Felix_Bergmann.txt"
    existing.write_text("andere Datei", encoding="utf-8")
    source = tmp_path / "Brief_Max_Mustermann.txt"
    source.write_text("x", encoding="utf-8")

    with pytest.raises(FileExistsError):
        DocumentAnonymizer()._anonymize_filename(source, _profile())

    assert existing.read_text(encoding="utf-8") == "andere Datei" and source.exists()


# --- Workflow (Legacy-Berichtsroute) ---------------------------------------


def _workflow(tmp_path):
    service = ReportWorkflowService(base_path=tmp_path / "base")
    (tmp_path / "base" / "data_ano").mkdir(parents=True, exist_ok=True)
    profile = TempAnonymProfile(
        tarnname="Felix Bergmann",
        fake_geburtsdatum="07.04.2014",
        mappings={"names": {"Max Mustermann": "Felix Bergmann"}},
    )
    return service, WorkflowSession(session_id="t4120", profile=profile)


def test_workflow_msg_with_sensitive_filename_ends_as_renamed_txt(tmp_path, monkeypatch):
    """Kernfall des Tickets: .msg wird zu .txt, der sensible Dateiname wird am
    echten Ausgabepfad umbenannt (frueher: Rename auf den nicht mehr vorhandenen .msg-Pfad)."""
    _fake_extractors(monkeypatch)
    source = tmp_path / "quelle"
    source.mkdir()
    original = source / "Mail Max Mustermann.msg"
    original.write_bytes(b"synthetic-binary")
    before = _sha(original)
    service, session = _workflow(tmp_path)

    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    names = sorted(p.name for p in (tmp_path / "base" / "data_ano").iterdir())
    assert names == ["Mail Felix Bergmann.txt"], names
    assert "Max Mustermann" not in (tmp_path / "base" / "data_ano" / names[0]).read_text(encoding="utf-8")
    assert _sha(original) == before         # Original-Quelle unveraendert


def test_workflow_doc_with_sensitive_filename_ends_as_renamed_txt(tmp_path, monkeypatch):
    _fake_extractors(monkeypatch)
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Deckblatt Max Mustermann.doc").write_bytes(b"synthetic-binary")
    service, session = _workflow(tmp_path)

    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert sorted(p.name for p in (tmp_path / "base" / "data_ano").iterdir()) == ["Deckblatt Felix Bergmann.txt"]


def test_workflow_failed_conversion_is_skipped_without_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(anonymizer_service, "_extract_msg_text", lambda p: "")
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Mail Max Mustermann.msg").write_bytes(b"synthetic-binary")
    service, session = _workflow(tmp_path)

    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert list((tmp_path / "base" / "data_ano").iterdir()) == []   # fail-closed: nichts im Output


@pytest.mark.parametrize("first,second", [("Mail.doc", "Mail.msg"), ("Mail.txt", "Mail.msg"), ("Mail.msg", "Mail.txt")])
def test_workflow_same_basename_collision_is_loud_and_never_overwrites(tmp_path, monkeypatch, first, second):
    _fake_extractors(monkeypatch)
    source = tmp_path / "quelle"
    source.mkdir()
    for name in (first, second):
        (source / name).write_bytes(b"synthetic-binary" if not name.endswith(".txt") else "Max Mustermann, eigener Text".encode())
    hashes = {p.name: _sha(p) for p in source.iterdir()}
    service, session = _workflow(tmp_path)

    with pytest.raises(FileExistsError, match="Mail.txt"):
        service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert {p.name: _sha(p) for p in source.iterdir()} == hashes     # Originale unveraendert
