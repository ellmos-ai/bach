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


# =============================================================================
# Revision 2 (A1-A3): Namensreservierung VOR dem Kopieren, Eigenartefakt-
# Aufraeumen bei Rename-Fehlern, Erfolgsflag/Ausnahmen in allen Schleifen.
# Nur synthetische Daten; Textextraktoren gemockt, Dateisystemlogik echt.
# =============================================================================

from hub._services.document import report_workflow_service as wf_module  # noqa: E402


def _tree(root: Path) -> dict:
    """Alle regulaeren Dateien unter root (ohne Punktdateien wie .profil.json) -> sha256."""
    import os   # os.walk statt rglob: _force_order ersetzt Path.rglob

    found = {}
    for base, _dirs, names in os.walk(root):
        for name in names:
            if not name.startswith("."):
                path = Path(base) / name
                found[str(path.relative_to(root))] = _sha(path)
    return dict(sorted(found.items()))


def _folder_env(tmp_path, monkeypatch):
    """anonymize_folder ohne echten Schluesselspeicher (nur tmp)."""
    monkeypatch.setattr(anonymizer_service, "get_key_path", lambda cid: tmp_path / "keys" / f"{cid}.key")
    monkeypatch.setattr(anonymizer_service, "encrypt_key_file", lambda *a, **k: None)
    _fake_extractors(monkeypatch)
    src = tmp_path / "quelle"
    dest = tmp_path / "ziel"
    src.mkdir()
    return src, dest


def _force_order(monkeypatch, src: Path, names):
    """Erzwingt die Verarbeitungsreihenfolge von anonymize_folder (rglob ist sonst Dateisystem-Zufall)."""
    ordered = [src / n for n in names]
    monkeypatch.setattr(Path, "rglob", lambda self, pattern: iter(ordered))


# --- A1: anonymize_folder -----------------------------------------------------


@pytest.mark.parametrize("order", [("Akte.doc", "Akte.txt"), ("Akte.txt", "Akte.doc")])
def test_folder_doc_txt_collision_in_both_orders_is_loud_and_loses_nothing(tmp_path, monkeypatch, order):
    src, dest = _folder_env(tmp_path, monkeypatch)
    (src / "Akte.doc").write_bytes(b"synthetic-binary")
    (src / "Akte.txt").write_text("Max Mustermann, eigener Text", encoding="utf-8")
    originals = _tree(src)
    _force_order(monkeypatch, src, order)

    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    # nur die erste Quelle ist angelegt; die zweite wurde VOR dem Kopieren abgelehnt
    outputs = _tree(dest)
    assert len(outputs) == 1 and next(iter(outputs)).endswith(".txt")   # genau die erste Ausgabe, keine Rohkopie
    assert len(result.errors) == 1 and "Akte.txt" in result.errors[0]
    assert result.anonymized_files == 1
    assert _tree(src) == originals                       # Originale unveraendert
    out_file = dest / next(iter(outputs))
    assert "Max Mustermann" not in out_file.read_text(encoding="utf-8")   # erste Ausgabe bleibt anonymisiert


def test_folder_does_not_overwrite_a_foreign_existing_converter_target(tmp_path, monkeypatch):
    src, dest = _folder_env(tmp_path, monkeypatch)
    (src / "Akte.doc").write_bytes(b"synthetic-binary")
    dest.mkdir()
    foreign = dest / "Akte.txt"
    foreign.write_text("fremde Ausgabe", encoding="utf-8")
    before, original = _sha(foreign), _tree(src)

    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert _sha(foreign) == before
    assert _tree(dest) == {"Akte.txt": before}           # keine Rohkopie Akte.doc im Ziel
    assert len(result.errors) == 1 and result.anonymized_files == 0
    assert _tree(src) == original


def test_folder_into_its_own_source_changes_nothing(tmp_path, monkeypatch):
    src, _dest = _folder_env(tmp_path, monkeypatch)
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    (src / "Akte.doc").write_bytes(b"synthetic-binary")
    originals = _tree(src)

    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(src))

    assert _tree(src) == originals and len(result.errors) == 2 and result.anonymized_files == 0


# --- A2: Rename-Fehler hinterlassen keine Klartext-Eigenartefakte -------------


@pytest.mark.parametrize("name,extractor_suffix", [("Brief Max Mustermann.txt", None), ("Mail Max Mustermann.msg", ".msg")])
def test_folder_rename_collision_removes_own_clear_named_output_only(tmp_path, monkeypatch, name, extractor_suffix):
    src, dest = _folder_env(tmp_path, monkeypatch)
    (src / name).write_bytes(b"synthetic-binary" if extractor_suffix else "Max Mustermann".encode())
    dest.mkdir()
    # fremde Datei, die genau dem anonymisierten Zielnamen entspricht
    foreign = dest / (name.replace("Max Mustermann", "Felix Bergmann").rsplit(".", 1)[0] + ".txt" if extractor_suffix
                      else name.replace("Max Mustermann", "Felix Bergmann"))
    foreign.write_text("fremde Datei", encoding="utf-8")
    before, original = _sha(foreign), _tree(src)

    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert _tree(dest) == {foreign.name: before}         # weder Klartextname noch Rohkopie uebrig, Fremdes unveraendert
    assert len(result.errors) == 1 and result.anonymized_files == 0
    assert _tree(src) == original


def test_folder_rename_oserror_removes_own_clear_named_output(tmp_path, monkeypatch):
    src, dest = _folder_env(tmp_path, monkeypatch)
    (src / "Brief Max Mustermann.txt").write_text("Max Mustermann", encoding="utf-8")
    original = _tree(src)

    def boom(self, target):
        raise PermissionError("rename gesperrt")

    monkeypatch.setattr(Path, "rename", boom)
    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert _tree(dest) == {}
    assert len(result.errors) == 1 and "rename gesperrt" in result.errors[0] and result.anonymized_files == 0
    assert _tree(src) == original


# --- A3: success=False und Ausnahmen -------------------------------------------


@pytest.mark.parametrize("returned", ["same_path", "none"])
def test_folder_false_result_removes_raw_copy_and_counts_skipped(tmp_path, monkeypatch, returned):
    src, dest = _folder_env(tmp_path, monkeypatch)
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(src)

    def fake(self, filepath, profile):
        return False, 0, (Path(filepath) if returned == "same_path" else None)

    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output", fake)
    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert _tree(dest) == {}                              # keine Rohkopie im Ziel
    assert result.skipped_files == 1 and result.anonymized_files == 0 and result.errors == []
    assert _tree(src) == original


def test_folder_exception_removes_raw_copy_and_reports_error(tmp_path, monkeypatch):
    src, dest = _folder_env(tmp_path, monkeypatch)
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(src)

    def boom(self, filepath, profile):
        raise RuntimeError("Konverter kaputt")

    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output", boom)
    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert _tree(dest) == {}
    assert len(result.errors) == 1 and "Konverter kaputt" in result.errors[0] and result.anonymized_files == 0
    assert _tree(src) == original


# --- Workflow-Schleifen -------------------------------------------------------


def _reverse_scan(monkeypatch, reverse: bool):
    """Erzwingt beide Verarbeitungsreihenfolgen der Workflow-Schleifen."""
    original_scan = wf_module.DocumentCollector.scan_folder

    def scan(self, *args, **kwargs):
        res = original_scan(self, *args, **kwargs)
        if reverse:
            res.documents.reverse()
        return res

    monkeypatch.setattr(wf_module.DocumentCollector, "scan_folder", scan)


@pytest.mark.parametrize("reverse", [False, True])
def test_workflow_doc_txt_collision_both_orders_leaves_no_raw_and_no_loss(tmp_path, monkeypatch, reverse):
    _fake_extractors(monkeypatch)
    _reverse_scan(monkeypatch, reverse)
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Akte.doc").write_bytes(b"synthetic-binary")
    (source / "Akte.txt").write_text("Max Mustermann, eigener Text", encoding="utf-8")
    originals = _tree(source)
    service, session = _workflow(tmp_path)

    with pytest.raises(FileExistsError, match="Akte.txt"):
        service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    ano = tmp_path / "base" / "data_ano"
    assert sorted(_tree(ano)) == ["Akte.txt"]            # genau die erste Ausgabe, keine Rohkopie Akte.doc
    assert "Max Mustermann" not in (ano / "Akte.txt").read_text(encoding="utf-8")
    assert _tree(source) == originals


def test_workflow_foreign_existing_output_is_refused_and_unchanged(tmp_path, monkeypatch):
    _fake_extractors(monkeypatch)
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Akte.doc").write_bytes(b"synthetic-binary")
    service, session = _workflow(tmp_path)
    monkeypatch.setattr(service, "_deep_cleanup", lambda *a, **k: None)   # simuliert gesperrte Altdatei
    foreign = tmp_path / "base" / "data_ano" / "Akte.txt"
    foreign.write_text("fremde Altdatei", encoding="utf-8")
    before = _sha(foreign)

    with pytest.raises(FileExistsError):
        service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert _tree(tmp_path / "base" / "data_ano") == {"Akte.txt": before}


def test_workflow_false_result_removes_raw_copy_and_warns(tmp_path, monkeypatch):
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(source)
    service, session = _workflow(tmp_path)
    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output",
                        lambda self, fp, prof: (False, 0, Path(fp)))

    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert _tree(tmp_path / "base" / "data_ano") == {}
    assert any("Notiz.txt" in w for w in session.warnings)
    assert _tree(source) == original


def test_workflow_false_result_in_standard_loop_removes_raw_copy_and_warns(tmp_path, monkeypatch):
    service, session = _workflow(tmp_path)
    roh = tmp_path / "base" / "data_roh"
    roh.mkdir(parents=True, exist_ok=True)
    (roh / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(roh)
    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output",
                        lambda self, fp, prof: (False, 0, Path(fp)))

    service.anonymize_to_bundles(session, include_extended=True)

    assert _tree(tmp_path / "base" / "data_ano") == {}
    assert any("Notiz.txt" in w for w in session.warnings)
    assert _tree(roh) == original


def test_workflow_exception_removes_raw_copy_folder_loop_warns_and_continues(tmp_path, monkeypatch):
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(source)
    service, session = _workflow(tmp_path)

    def boom(self, fp, prof):
        raise RuntimeError("Konverter kaputt")

    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output", boom)
    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert _tree(tmp_path / "base" / "data_ano") == {}
    assert any("Notiz.txt" in w for w in session.warnings)
    assert _tree(source) == original


def test_workflow_exception_in_standard_loop_removes_raw_copy_and_propagates(tmp_path, monkeypatch):
    service, session = _workflow(tmp_path)
    roh = tmp_path / "base" / "data_roh"
    roh.mkdir(parents=True, exist_ok=True)
    (roh / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(roh)

    def boom(self, fp, prof):
        raise RuntimeError("Konverter kaputt")

    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output", boom)
    with pytest.raises(RuntimeError, match="Konverter kaputt"):
        service.anonymize_to_bundles(session, include_extended=True)

    assert _tree(tmp_path / "base" / "data_ano") == {}
    assert session.anonymized is False                    # kein Erfolg gemeldet
    assert _tree(roh) == original


@pytest.mark.parametrize("loop", ["folder", "standard"])
def test_workflow_rename_failure_leaves_no_clear_named_output(tmp_path, monkeypatch, loop):
    _fake_extractors(monkeypatch)
    service, session = _workflow(tmp_path)
    if loop == "folder":
        source = tmp_path / "quelle"
    else:
        source = tmp_path / "base" / "data_roh"
    source.mkdir(parents=True, exist_ok=True)
    (source / "Mail Max Mustermann.msg").write_bytes(b"synthetic-binary")
    original = _tree(source)

    def boom(self, filepath, profile):
        raise PermissionError("rename gesperrt")

    monkeypatch.setattr(ReportWorkflowService, "_anonymize_filename", boom)
    if loop == "folder":
        service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)
        assert any("Mail Max Mustermann.msg" in w for w in session.warnings)
    else:
        with pytest.raises(PermissionError):
            service.anonymize_to_bundles(session, include_extended=True)

    assert _tree(tmp_path / "base" / "data_ano") == {}   # weder Klartext-.txt noch Rohkopie .msg
    assert _tree(source) == original
