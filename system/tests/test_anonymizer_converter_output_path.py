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


def test_folder_into_its_own_source_is_rejected(tmp_path, monkeypatch):
    """Revision 3: gleiche Wurzeln werden vor jeder Schreibaktion abgelehnt (Details: N3-Tests unten)."""
    src, _dest = _folder_env(tmp_path, monkeypatch)
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    (src / "Akte.doc").write_bytes(b"synthetic-binary")
    before = _tree(src)

    with pytest.raises(ValueError):
        DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(src))

    assert _tree(src) == before


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


# =============================================================================
# Revision 3 (N1-N3): Bereinigungsfehler schlagen bis zur Workflowgrenze durch, tatsaechlich
# exklusiv angelegte Ausgaben werden im Fehlerpfad bereinigt, ueberlappende Wurzeln werden
# vor jeder Schreibaktion abgelehnt. Nur synthetische Daten; Textextraktoren gemockt.
# =============================================================================

import os  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from hub._services.document.anonymizer_service import (  # noqa: E402
    ArtifactCleanupError,
    copy_exclusive,
    discard_own_artifacts,
)


def _fulltree(root: Path) -> dict:
    """Dateien MIT Punktdateien (sha256) und Verzeichnisse (Marker) unter root."""
    found = {}
    for base, dirs, names in os.walk(root):
        for d in dirs:
            found[str((Path(base) / d).relative_to(root)) + "/"] = "dir"
        for name in names:
            path = Path(base) / name
            found[str(path.relative_to(root))] = "link" if path.is_symlink() else _sha(path)
    return dict(sorted(found.items()))


def _lock_unlink(monkeypatch, predicate, times=None):
    """Simuliert gesperrte Dateien: Path.unlink wirft PermissionError, solange predicate(path) gilt."""
    real = Path.unlink
    state = {"n": 0}

    def locked(self, *args, **kwargs):
        if predicate(self) and (times is None or state["n"] < times):
            state["n"] += 1
            raise PermissionError("gesperrt")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    return state


def _in_ano(path: Path, name: str) -> bool:
    return path.name == name and "data_ano" in path.parts


# --- N3: gleiche/verschachtelte Wurzeln ------------------------------------------


@pytest.mark.parametrize("layout", ["same", "dest_in_src", "src_in_dest", "dotdot"])
def test_folder_overlapping_roots_are_rejected_before_any_write(tmp_path, monkeypatch, layout):
    src, _dest = _folder_env(tmp_path, monkeypatch)
    writes = []
    monkeypatch.setattr(anonymizer_service, "encrypt_key_file", lambda *a, **k: writes.append(a))
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    (src / ".profil.json").write_text('{"vorhanden": true}', encoding="utf-8")
    (src / "Sub").mkdir()
    (src / "Sub" / "Akte.doc").write_bytes(b"synthetic-binary")
    dest = {"same": src, "dest_in_src": src / "Sub" / "neu", "src_in_dest": tmp_path,
            "dotdot": src / "Sub" / ".."}[layout]
    before = _fulltree(tmp_path)

    with pytest.raises(ValueError) as caught:
        DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert _fulltree(tmp_path) == before       # Originale, versteckte .profil.json und Verzeichnisse unveraendert
    assert writes == [] and not (tmp_path / "keys").exists()
    assert str(tmp_path) not in str(caught.value) and "Quell- und Ausgabeordner" in str(caught.value)


def test_folder_disjoint_roots_with_hidden_files_still_work(tmp_path, monkeypatch):
    src, dest = _folder_env(tmp_path, monkeypatch)
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    (src / ".versteckt").write_text("bleibt", encoding="utf-8")
    result = DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))
    assert result.errors == [] and result.anonymized_files == 1
    assert (src / ".versteckt").read_text(encoding="utf-8") == "bleibt" and not (dest / ".versteckt").exists()


@pytest.mark.parametrize("where", ["same", "inside", "parent"])
def test_workflow_folder_rejects_overlapping_source_before_cleaning_data_ano(tmp_path, monkeypatch, where):
    _fake_extractors(monkeypatch)
    service, session = _workflow(tmp_path)
    ano = tmp_path / "base" / "data_ano"
    source = {"same": ano, "inside": ano / "sub", "parent": tmp_path / "base"}[where]
    source.mkdir(parents=True, exist_ok=True)
    (source / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    before = _fulltree(tmp_path)

    with pytest.raises(ValueError):
        service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert _fulltree(tmp_path) == before        # das Leeren von data_ano hat keine Originale geloescht
    assert session.anonymized is False


# --- N1: Bereinigungsfehler bis zur oeffentlichen Grenze ---------------------------


def _false_result(monkeypatch):
    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output",
                        lambda self, fp, prof: (False, 0, Path(fp)))


def _raising_result(monkeypatch):
    def boom(self, fp, prof):
        raise RuntimeError("Konverter kaputt")
    monkeypatch.setattr(DocumentAnonymizer, "anonymize_file_with_output", boom)


@pytest.mark.parametrize("fail", [_false_result, _raising_result])
@pytest.mark.parametrize("loop", ["folder", "standard"])
def test_unlink_failure_blocks_success_at_the_workflow_boundary(tmp_path, monkeypatch, loop, fail):
    fail(monkeypatch)
    service, session = _workflow(tmp_path)
    source = tmp_path / "quelle" if loop == "folder" else tmp_path / "base" / "data_roh"
    source.mkdir(parents=True, exist_ok=True)
    (source / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(source)
    _lock_unlink(monkeypatch, lambda p: _in_ano(p, "Notiz.txt"))

    with pytest.raises(ArtifactCleanupError) as caught:
        if loop == "folder":
            service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)
        else:
            service.anonymize_to_bundles(session, include_extended=True)

    assert session.anonymized is False and session.status == "error"
    assert "Notiz" not in str(caught.value) and "Mustermann" not in str(caught.value)
    assert _tree(source) == original              # Original unveraendert


def test_cleanup_failure_is_visible_at_the_api_route(tmp_path, monkeypatch):
    """Echte API-Grenze: POST /api/report/session/<id>/anonymize meldet success=false."""
    from gui import server

    _false_result(monkeypatch)
    service, session = _workflow(tmp_path)
    service._sessions[session.session_id] = session
    roh = tmp_path / "base" / "data_roh"
    roh.mkdir(parents=True, exist_ok=True)
    (roh / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    _lock_unlink(monkeypatch, lambda p: _in_ano(p, "Notiz.txt"))
    monkeypatch.setattr(server, "get_report_workflow_service", lambda: service)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "t4120" else None)
    api = TestClient(server.app, headers={"Authorization": "Bearer t4120"})
    try:
        res = api.post(f"/api/report/session/{session.session_id}/anonymize", json={"include_extended": True})
    finally:
        api.close()

    assert res.status_code == 200 and res.json()["success"] is False
    assert session.anonymized is False


def test_folder_unlink_failure_aborts_the_run_without_key_or_profile(tmp_path, monkeypatch):
    src, dest = _folder_env(tmp_path, monkeypatch)
    writes = []
    monkeypatch.setattr(anonymizer_service, "encrypt_key_file", lambda *a, **k: writes.append(a))
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    (src / "Zweite.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    original = _tree(src)
    _false_result(monkeypatch)
    _lock_unlink(monkeypatch, lambda p: p.name == "Notiz.txt" and "ziel" in p.parts)

    with pytest.raises(ArtifactCleanupError):
        DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert writes == [] and not (dest / ".profil.json").exists()   # kein Profil-/Schluesselerfolg
    assert _tree(src) == original


def test_transient_unlink_failure_is_retried_by_the_caller_and_leaves_nothing(tmp_path, monkeypatch):
    """Scheitert nur der erste Loeschversuch, raeumt der Aufrufer nach; kein Rest, kein Sicherheitsfehler."""
    _fake_extractors(monkeypatch)
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Mail Max Mustermann.msg").write_bytes(b"synthetic-binary")
    service, session = _workflow(tmp_path)
    state = _lock_unlink(monkeypatch, lambda p: p.suffix == ".msg" and "data_ano" in p.parts, times=1)

    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert state["n"] == 1
    assert _tree(tmp_path / "base" / "data_ano") == {}            # weder .msg-Rohkopie noch Klartext-.txt
    assert any("Mail Max Mustermann.msg" in w for w in session.warnings)


# --- N2: Konverter erfasst seine tatsaechliche Exklusiverstellung ------------------


def test_converter_removes_its_own_txt_when_the_stage_copy_cannot_be_removed(tmp_path, monkeypatch):
    _fake_extractors(monkeypatch)
    stage = tmp_path / "Mail Max Mustermann.msg"
    stage.write_bytes(b"synthetic-binary")
    _lock_unlink(monkeypatch, lambda p: p.suffix == ".msg")

    with pytest.raises(PermissionError):
        DocumentAnonymizer().anonymize_file_with_output(str(stage), _profile())

    assert not (tmp_path / "Mail Max Mustermann.txt").exists()   # kein halbfertiges TXT mit Klarnamen
    assert stage.exists()                                         # Stage bleibt: der Aufrufer entfernt sie


def test_converter_removes_its_own_txt_after_a_write_failure(tmp_path):
    stage = tmp_path / "Akte.doc"
    stage.write_bytes(b"synthetic-binary")
    with pytest.raises(TypeError):
        DocumentAnonymizer._write_converted_txt(stage, object())   # Schreiben scheitert nach dem Anlegen
    assert not (tmp_path / "Akte.txt").exists() and stage.exists()


def test_converter_reports_cleanup_failure_when_its_own_txt_stays(tmp_path, monkeypatch):
    _fake_extractors(monkeypatch)
    stage = tmp_path / "Mail.msg"
    stage.write_bytes(b"synthetic-binary")
    _lock_unlink(monkeypatch, lambda p: p.name in ("Mail.msg", "Mail.txt"))

    with pytest.raises(ArtifactCleanupError) as caught:
        DocumentAnonymizer().anonymize_file_with_output(str(stage), _profile())

    assert isinstance(caught.value.__cause__, PermissionError)


def test_converter_never_deletes_a_target_that_a_stranger_put_in_place(tmp_path, monkeypatch):
    """Eigentum folgt aus der Exklusiverstellung, nicht aus 'war vorher nicht da': wird das TXT
    inzwischen durch eine fremde Datei ersetzt (andere Identitaet), bleibt sie unveraendert."""
    _fake_extractors(monkeypatch)
    stage = tmp_path / "Mail.msg"
    stage.write_bytes(b"synthetic-binary")
    txt = tmp_path / "Mail.txt"
    real_unlink = Path.unlink

    def swap_then_fail(self, *args, **kwargs):
        if self == stage:
            stranger = tmp_path / "fremd.tmp"
            stranger.write_text("fremde Datei", encoding="utf-8")
            os.replace(stranger, txt)               # ersetzt unser TXT atomar durch eine fremde Datei
            raise PermissionError("gesperrt")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", swap_then_fail)

    with pytest.raises(PermissionError):
        DocumentAnonymizer().anonymize_file_with_output(str(stage), _profile())

    assert txt.read_text(encoding="utf-8") == "fremde Datei"


def test_stranger_target_appearing_between_reservation_and_creation_stays_untouched(tmp_path, monkeypatch):
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Mail.msg").write_bytes(b"synthetic-binary")
    service, session = _workflow(tmp_path)
    foreign = tmp_path / "base" / "data_ano" / "Mail.txt"

    def extract_and_collide(path):
        foreign.write_text("fremde Ausgabe", encoding="utf-8")     # erscheint NACH Reservierung und Kopie
        return MSG_TEXT

    monkeypatch.setattr(anonymizer_service, "_extract_msg_text", extract_and_collide)
    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert foreign.read_text(encoding="utf-8") == "fremde Ausgabe"
    assert _tree(tmp_path / "base" / "data_ano") == {"Mail.txt": _sha(foreign)}   # keine Rohkopie, Fremdes unveraendert
    assert any("Mail.msg" in w for w in session.warnings)


def test_converter_failure_with_stuck_stage_blocks_success_at_the_boundary(tmp_path, monkeypatch):
    _fake_extractors(monkeypatch)
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Mail Max Mustermann.msg").write_bytes(b"synthetic-binary")
    service, session = _workflow(tmp_path)
    _lock_unlink(monkeypatch, lambda p: p.suffix == ".msg" and "data_ano" in p.parts)

    with pytest.raises(ArtifactCleanupError):
        service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    ano = tmp_path / "base" / "data_ano"
    assert not list(ano.glob("*.txt"))               # das vom Konverter angelegte TXT ist entfernt
    assert session.anonymized is False


# --- gescheiterte Teilkopie, exklusive Kopie ---------------------------------------


def test_partial_copy_is_removed_and_original_untouched(tmp_path, monkeypatch):
    import shutil as shutil_module

    src = tmp_path / "quelle.txt"
    src.write_text("Max Mustermann", encoding="utf-8")
    dest = tmp_path / "ziel.txt"
    before = _sha(src)

    def half_copy(reader, writer, *args, **kwargs):
        writer.write(b"Max")
        raise OSError("Platte voll")

    monkeypatch.setattr(shutil_module, "copyfileobj", half_copy)
    with pytest.raises(OSError, match="Platte voll"):
        copy_exclusive(src, dest)

    assert not dest.exists() and _sha(src) == before


def test_partial_copy_that_cannot_be_removed_is_a_cleanup_error(tmp_path, monkeypatch):
    import shutil as shutil_module

    src = tmp_path / "quelle.txt"
    src.write_text("Max Mustermann", encoding="utf-8")
    dest = tmp_path / "ziel.txt"

    def half_copy(reader, writer, *args, **kwargs):
        writer.write(b"Max")
        raise OSError("Platte voll")

    monkeypatch.setattr(shutil_module, "copyfileobj", half_copy)
    _lock_unlink(monkeypatch, lambda p: p.name == "ziel.txt")
    with pytest.raises(ArtifactCleanupError):
        copy_exclusive(src, dest)


def test_copy_never_overwrites_a_stranger_that_appeared_after_the_reservation(tmp_path, monkeypatch):
    _fake_extractors(monkeypatch)
    source = tmp_path / "quelle"
    source.mkdir()
    (source / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    service, session = _workflow(tmp_path)
    foreign = tmp_path / "base" / "data_ano" / "Notiz.txt"
    real_claim = wf_module.claim_output_name

    def claim_then_stranger(claimed, target, src, check_disk=False):
        final = real_claim(claimed, target, src, check_disk=check_disk)
        foreign.write_text("fremde Datei", encoding="utf-8")        # nach der Pruefung, vor dem Kopieren
        return final

    monkeypatch.setattr(wf_module, "claim_output_name", claim_then_stranger)
    service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert foreign.read_text(encoding="utf-8") == "fremde Datei"
    assert any("Notiz.txt" in w for w in session.warnings)


# --- discard_own_artifacts: Symlinks und Grenzen -----------------------------------


def test_discard_never_follows_a_symlink_and_stays_below_root(tmp_path):
    root = tmp_path / "ziel"
    root.mkdir()
    original = tmp_path / "original.txt"
    original.write_text("Original", encoding="utf-8")
    outside = tmp_path / "ausserhalb.txt"
    outside.write_text("fremd", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(original)
    sub = root / "ordner"
    sub.mkdir()
    own = root / "eigen.txt"
    own.write_text("eigen", encoding="utf-8")

    discard_own_artifacts(root, link, outside, sub, tmp_path / "gibt-es-nicht.txt", None, own)

    assert original.read_text(encoding="utf-8") == "Original" and link.is_symlink()
    assert outside.exists() and sub.is_dir() and not own.exists()


def test_discard_reports_every_stuck_file_after_trying_all(tmp_path, monkeypatch):
    root = tmp_path / "ziel"
    root.mkdir()
    stuck, free = root / "a.txt", root / "b.txt"
    stuck.write_text("x", encoding="utf-8")
    free.write_text("y", encoding="utf-8")
    _lock_unlink(monkeypatch, lambda p: p.name == "a.txt")

    with pytest.raises(ArtifactCleanupError, match="1 eigene"):
        discard_own_artifacts(root, stuck, free)

    assert stuck.exists() and not free.exists()      # alle Pfade wurden versucht


# =============================================================================
# Revision 4 (R1, P3): Wurzelvergleich ueber die tatsaechliche Dateiidentitaet (case-insensitive APFS),
# fehlende Dateiidentitaet -> ArtifactCleanupError statt blindem unlink. Echte Mac-Fixtures, keine Mocks
# fuer das Dateisystemverhalten; nur synthetische Daten.
# =============================================================================

from hub._services.document.anonymizer_service import ensure_disjoint_roots  # noqa: E402


def _is_case_insensitive(directory: Path) -> bool:
    probe = directory / "CaseProbeAbc"
    probe.mkdir()
    try:
        return (directory / "caseprobeabc").exists()
    finally:
        probe.rmdir()


@pytest.fixture
def ci_dir(tmp_path):
    """tmp_path, aber nur auf einem case-insensitiven Volume (echte Eigenschaft, nicht angenommen)."""
    if not _is_case_insensitive(tmp_path):
        pytest.skip("Dateisystem ist case-sensitive; die Gegenprobe steht in den case-sensitive-Tests")
    return tmp_path


@pytest.mark.parametrize("layout", ["same_dir_other_case", "dest_in_src_other_case", "dest_new_parts_other_case",
                                    "src_in_dest_other_case"])
def test_folder_roots_differing_only_in_case_are_rejected_before_any_write(ci_dir, monkeypatch, layout):
    _fake_extractors(monkeypatch)
    writes = []
    monkeypatch.setattr(anonymizer_service, "get_key_path", lambda cid: ci_dir / "keys" / f"{cid}.key")
    monkeypatch.setattr(anonymizer_service, "encrypt_key_file", lambda *a, **k: writes.append(a))
    holder = ci_dir / "Elt"
    src = holder / "Quelle"
    (src / "Sub").mkdir(parents=True)
    (src / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    (src / ".profil.json").write_text('{"vorhanden": true}', encoding="utf-8")
    (src / "Sub" / "Akte.doc").write_bytes(b"synthetic-binary")
    dest = {"same_dir_other_case": holder / "QUELLE",
            "dest_in_src_other_case": holder / "quelle" / "SUB" / "neu",
            "dest_new_parts_other_case": holder / "QUELLE" / "ausgabe" / "tief",
            "src_in_dest_other_case": ci_dir / "ELT"}[layout]
    before = _fulltree(ci_dir)

    with pytest.raises(ValueError) as caught:
        DocumentAnonymizer().anonymize_folder(str(src), _profile(), "pw", output_folder=str(dest))

    assert _fulltree(ci_dir) == before            # Originale, Punktdateien, Verzeichnisse: nichts neu angelegt
    assert writes == [] and "Quell- und Ausgabeordner" in str(caught.value) and str(ci_dir) not in str(caught.value)


@pytest.mark.parametrize("where", ["data_ano_other_case", "inside_other_case", "base_other_case"])
def test_workflow_roots_differing_only_in_case_do_not_clean_the_originals(ci_dir, monkeypatch, where):
    _fake_extractors(monkeypatch)
    service, session = _workflow(ci_dir)
    base = ci_dir / "base"
    (base / "data_ano" / "sub").mkdir(parents=True, exist_ok=True)
    source = {"data_ano_other_case": base / "DATA_ANO", "inside_other_case": base / "Data_Ano" / "sub",
              "base_other_case": ci_dir / "BASE"}[where]
    (source / "Notiz.txt").write_text("Max Mustermann war da.", encoding="utf-8")
    (source / ".versteckt").write_text("bleibt", encoding="utf-8")
    before = _fulltree(ci_dir)

    with pytest.raises(ValueError):
        service.anonymize_to_bundles_from_folder(session, str(source), include_extended=True)

    assert _fulltree(ci_dir) == before            # _deep_cleanup(data_ano) hat keine Quelloriginale geloescht
    assert session.anonymized is False


def test_distinct_siblings_with_similar_names_are_still_allowed(tmp_path):
    (tmp_path / "Quelle").mkdir()
    (tmp_path / "Quelle2").mkdir()
    (tmp_path / "ziel").mkdir()
    ensure_disjoint_roots(tmp_path / "Quelle", tmp_path / "Quelle2")
    ensure_disjoint_roots(tmp_path / "Quelle", tmp_path / "ziel" / "neu")


@pytest.fixture(scope="module")
def case_sensitive_volume(tmp_path_factory):
    """Echtes case-sensitive APFS-Volume (Sparse-Image), damit KEINE pauschale casefold-Annahme getestet wird."""
    import shutil
    import subprocess

    if sys.platform != "darwin" or not shutil.which("hdiutil"):
        pytest.skip("hdiutil nicht verfuegbar")
    base = tmp_path_factory.mktemp("csvol")
    mount = base / "mnt"
    mount.mkdir()
    made = subprocess.run(["hdiutil", "create", "-size", "20m", "-fs", "Case-sensitive APFS", "-volname", "cs4120",
                           "-type", "SPARSE", str(base / "cs")], capture_output=True, text=True, timeout=120)
    if made.returncode != 0:
        pytest.skip("case-sensitive Image nicht anlegbar")
    attached = subprocess.run(["hdiutil", "attach", str(base / "cs.sparseimage"), "-mountpoint", str(mount),
                               "-nobrowse"], capture_output=True, text=True, timeout=120)
    if attached.returncode != 0:
        pytest.skip("case-sensitive Image nicht einhaengbar")
    try:
        yield mount
    finally:
        subprocess.run(["hdiutil", "detach", str(mount), "-force"], capture_output=True, text=True, timeout=120)


def test_case_sensitive_volume_keeps_differently_cased_directories_distinct(case_sensitive_volume):
    mount = case_sensitive_volume
    (mount / "Quelle").mkdir()
    (mount / "quelle").mkdir()
    assert not os.path.samefile(mount / "Quelle", mount / "quelle")        # echte Eigenschaft des Volumes
    ensure_disjoint_roots(mount / "Quelle", mount / "quelle")              # verschieden -> erlaubt
    ensure_disjoint_roots(mount / "Quelle", mount / "quelle" / "ausgabe")
    with pytest.raises(ValueError):                                         # gleiche Schreibweise bleibt abgelehnt
        ensure_disjoint_roots(mount / "Quelle", mount / "Quelle" / "ausgabe")


# --- P3: fehlende Dateiidentitaet -> nie blind loeschen -----------------------------


def test_missing_identity_after_exclusive_copy_is_a_cleanup_error_not_a_blind_unlink(tmp_path, monkeypatch):
    import shutil as shutil_module

    src = tmp_path / "quelle.txt"
    src.write_text("Max Mustermann", encoding="utf-8")
    dest = tmp_path / "ziel.txt"

    def no_identity(_st):
        raise OSError("keine Dateiidentitaet")

    def half_copy(reader, writer, *args, **kwargs):
        writer.write(b"Max")
        raise OSError("Platte voll")

    monkeypatch.setattr(anonymizer_service, "_file_identity", no_identity)
    monkeypatch.setattr(shutil_module, "copyfileobj", half_copy)
    with pytest.raises(ArtifactCleanupError):
        copy_exclusive(src, dest)

    assert dest.exists()           # nicht blind geloescht: Eigentum ist nicht beweisbar, der Fehler ist laut


def test_missing_identity_in_the_converter_is_a_cleanup_error_not_a_blind_unlink(tmp_path, monkeypatch):
    stage = tmp_path / "Akte.doc"
    stage.write_bytes(b"synthetic-binary")

    def no_identity(_st):
        raise OSError("keine Dateiidentitaet")

    monkeypatch.setattr(anonymizer_service, "_file_identity", no_identity)
    with pytest.raises(ArtifactCleanupError):
        DocumentAnonymizer._write_converted_txt(stage, "Text")
        # (fstat scheitert direkt nach der Exklusiverstellung -> identity None)
    # Der Schreibversuch selbst lief nicht (Exception vor dem Schreiben); Eigentum nicht beweisbar -> TXT bleibt sichtbar
    assert (tmp_path / "Akte.txt").exists()
