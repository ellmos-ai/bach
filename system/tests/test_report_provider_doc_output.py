# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression BACH-Task 4121: BachDocumentAnonymizerPort mit konvertierender DOC-Ausgabe.

Fehlerbild: Der Port rief ``anonymize_file()`` auf und las danach den durch die DOC->TXT-Konvertierung
entfernten ``source.doc``-Pfad; die Route endete fail-closed als ``anonymization_unavailable``. Verbindlich ist
der tatsaechlich erzeugte Ausgabepfad samt Medientyp (``text/plain``): Extraktion, Residualpruefung, Speicherung
und der kryptografisch gebundene Receipt arbeiten genau darauf.

Nur erfundene Fixtures. Der DOC-Textextraktor wird durch einen synthetischen Text ersetzt; Konvertierung,
Pfadlogik und Dateioperationen des echten ``DocumentAnonymizer`` sind echt. Async-Faelle laufen ueber
``asyncio.run``, damit kein pytest-asyncio-Plugin noetig ist.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import tempfile
from pathlib import Path

import pytest

from hub._services.document import anonymizer_service
from hub._services.document.report_provider_adapter import BachDocumentAnonymizerPort

_SOURCE_REF = "src_" + "2" * 48
_DOC_BYTES = b"synthetic legacy Word fixture"
_DOC_TEXT = "Sample Person completed a synthetic assessment."
_PROFILE = {"profile_id": "profile_" + "3" * 32, "policy_version": "policy_1"}


class _Store:
    """Test store that records the media type it is given."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.media_types: list[str] = []

    def put(self, run_id, content, media_type):
        self.media_types.append(media_type)
        artifact_ref = "art_" + secrets.token_hex(24)
        (self.root / (artifact_ref + ".bin")).write_bytes(content)
        return {"artifact_ref": artifact_ref, "content_sha256": hashlib.sha256(content).hexdigest()}

    def read(self, run_id, artifact_ref):
        return (self.root / (artifact_ref + ".bin")).read_bytes()

    def delete(self, run_id, artifact_ref):
        return True


class _Receipts:
    _PUBLIC = ("verified", "coverage", "policy_version", "run_id", "source_ref", "source_revision",
               "artifact_ref", "receipt_ref", "input_sha256", "output_sha256")

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def issue(self, payload):
        receipt_ref = "rcpt_" + secrets.token_hex(24)
        record = {**payload, "receipt_ref": receipt_ref, "verified": True, "coverage": "complete"}
        (self.root / (receipt_ref + ".json")).write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        return {key: record[key] for key in self._PUBLIC}

    def verify(self, receipt_ref, expected):
        record = json.loads((self.root / (receipt_ref + ".json")).read_text(encoding="utf-8"))
        ok = record.get("verified") is True and all(record.get(k) == v for k, v in expected.items())
        return {key: ({**record, "verified": ok})[key] for key in self._PUBLIC}

    def records(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("rcpt_*.json"))]


class _Profiles:
    def create(self, profile_id, policy_version):
        return {
            "profile_id": profile_id,
            "policy_version": policy_version,
            "profile": {
                "client_id": "synthetic-client", "tarnname": "Testperson", "fake_geburtsdatum": "01.01.2000",
                "mappings": {"names": {"Sample Person": "Example Person"}}, "created": "2026-10-11",
                "version": 1, "whitelist": [],
            },
        }


class _FakeService:
    """Records what the port extracts/scans; converter behaviour is injected per test."""

    def __init__(self, produce, residual=None):
        self._produce = produce
        self._residual = residual or {}
        self.extracted: list[Path] = []

    def anonymize_file_with_output(self, filepath, profile):
        return self._produce(Path(filepath))

    def extract_text_from_file(self, filepath):
        self.extracted.append(Path(filepath))
        return Path(filepath).read_text(encoding="utf-8")

    def scan_text_for_sensitive_data(self, text):
        return self._residual if "@" in text else {}


@pytest.fixture
def env(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(work))  # nothing from the port may linger here
    return type("Env", (), {
        "work": work, "store": _Store(tmp_path / "store"), "receipts": _Receipts(tmp_path / "receipts"),
    })


def _file(content: bytes, media_type: str):
    return {
        "source_ref": _SOURCE_REF,
        "source_revision": hashlib.sha256(content).hexdigest(),
        "media_type": media_type,
        "content": content,
        "anonymization_profile": dict(_PROFILE),
    }


def _anonymize(port, content, media_type):
    return asyncio.run(port.anonymize(_file(content, media_type), run_id="run-test"))


def _port(env, service=None):
    return BachDocumentAnonymizerPort(env.store, _Profiles(), env.receipts, service=service)


def _real_doc_service(monkeypatch):
    monkeypatch.setattr(anonymizer_service, "_extract_legacy_doc_text", lambda p: _DOC_TEXT)
    return anonymizer_service.DocumentAnonymizer()


def test_converted_doc_is_stored_and_receipted_as_text_plain(env, monkeypatch):
    port = _port(env, _real_doc_service(monkeypatch))
    original = bytes(_DOC_BYTES)

    result = _anonymize(port, original, "application/msword")

    assert result["status"] == "ok", result
    stored = env.store.read("run-test", result["artifact_ref"])
    assert b"Sample Person" not in stored and b"Example Person" in stored
    assert env.store.media_types == ["text/plain"]  # never application/msword for converted text
    (record,) = env.receipts.records()
    assert record["media_type"] == "text/plain"
    assert record["input_sha256"] == hashlib.sha256(_DOC_BYTES).hexdigest()
    assert record["output_sha256"] == hashlib.sha256(stored).hexdigest()
    assert original == _DOC_BYTES and list(env.work.iterdir()) == []  # original untouched, no leftovers


def test_converted_doc_receipt_verifies_and_reads_back(env, monkeypatch):
    port = _port(env, _real_doc_service(monkeypatch))
    result = _anonymize(port, _DOC_BYTES, "application/msword")
    input_sha = hashlib.sha256(_DOC_BYTES).hexdigest()

    verified = asyncio.run(port.verify_receipt(
        result["receipt_ref"], run_id="run-test", source_ref=_SOURCE_REF,
        source_revision=hashlib.sha256(_DOC_BYTES).hexdigest(), artifact_ref=result["artifact_ref"],
        expected_input_sha256=input_sha,
    ))
    readback = asyncio.run(port.read_artifact(result["artifact_ref"], run_id="run-test"))

    assert verified["verified"] is True and verified["coverage"] == "complete"
    assert verified["output_sha256"] == hashlib.sha256(readback).hexdigest()
    assert b"Example Person" in readback


def test_port_extracts_and_scans_the_actual_converted_file_not_the_staged_doc(env):
    def convert(staged: Path):
        text_path = staged.with_suffix(".txt")
        text_path.write_text("Example Person completed an assessment.", encoding="utf-8")
        staged.unlink()  # a converter drops the staged .doc
        return True, 1, text_path

    service = _FakeService(convert)
    result = _anonymize(_port(env, service), _DOC_BYTES, "application/msword")

    assert result["status"] == "ok", result
    assert [p.name for p in service.extracted] == ["source.txt"]  # extraction ran on the real output
    assert env.store.media_types == ["text/plain"]


def test_residual_data_in_the_converted_output_is_blocked(env):
    def convert(staged: Path):
        text_path = staged.with_suffix(".txt")
        text_path.write_text("Contact: person@example.org", encoding="utf-8")
        staged.unlink()
        return True, 1, text_path

    result = _anonymize(_port(env, _FakeService(convert, residual={"emails": ["person@example.org"]})),
                        _DOC_BYTES, "application/msword")

    assert result["status"] == "unsupported" and result["reason_code"] == "residual_data_detected"
    assert env.store.media_types == [] and env.receipts.records() == []  # nothing stored, no receipt


@pytest.mark.parametrize("media_type,content", [
    ("text/plain", b"Sample Person completed a synthetic assessment."),
    ("text/markdown", b"# Sample Person\n\ncompleted a synthetic assessment."),
])
def test_in_place_formats_keep_their_own_media_type(env, media_type, content):
    result = _anonymize(_port(env), content, media_type)

    assert result["status"] == "ok", result
    assert b"Example Person" in env.store.read("run-test", result["artifact_ref"])
    assert env.store.media_types == [media_type]
    assert env.receipts.records()[0]["media_type"] == media_type


def test_failed_doc_conversion_is_unsupported_and_stores_nothing(env, monkeypatch):
    monkeypatch.setattr(anonymizer_service, "_extract_legacy_doc_text", lambda p: "")
    result = _anonymize(_port(env, anonymizer_service.DocumentAnonymizer()), _DOC_BYTES, "application/msword")

    assert result == {"status": "unsupported", "reason_code": "anonymization_unsupported",
                      "source_revision": hashlib.sha256(_DOC_BYTES).hexdigest()}
    assert env.store.media_types == [] and env.receipts.records() == []


def _wrong_suffix(staged: Path):
    other = staged.with_suffix(".pdf")
    other.write_bytes(b"%PDF-1.4 synthetic")
    staged.unlink()
    return True, 1, other


def _no_output(staged: Path):
    staged.unlink()
    return True, 1, None


def _outside_work_dir(staged: Path):
    outside = staged.parent.parent / "elsewhere.txt"
    outside.write_text("Example Person", encoding="utf-8")
    return True, 1, outside


def _missing_file(staged: Path):
    staged.unlink()
    return True, 1, staged.with_suffix(".txt")


@pytest.mark.parametrize("produce", [_wrong_suffix, _no_output, _outside_work_dir, _missing_file])
def test_unreliable_converter_output_fails_closed(env, produce):
    result = _anonymize(_port(env, _FakeService(produce)), _DOC_BYTES, "application/msword")

    assert result["status"] == "unsupported" and result["reason_code"] == "anonymization_unsupported"
    assert env.store.media_types == [] and env.receipts.records() == []


def test_symlinked_output_is_rejected(env):
    def convert(staged: Path):
        real = staged.parent.parent / "real.txt"
        real.write_text("Example Person", encoding="utf-8")
        link = staged.with_suffix(".txt")
        try:
            link.symlink_to(real)
        except OSError:
            pytest.skip("symlinks not available")
        staged.unlink()
        return True, 1, link

    result = _anonymize(_port(env, _FakeService(convert)), _DOC_BYTES, "application/msword")

    assert result["status"] == "unsupported" and result["reason_code"] == "anonymization_unsupported"
    assert env.store.media_types == []


def test_service_without_output_path_cannot_convert_doc_but_still_handles_plain_text(env):
    class LegacyService:  # only the old two-value API
        def anonymize_file(self, filepath, profile):
            path = Path(filepath)
            path.write_text(path.read_text(encoding="utf-8").replace("Sample Person", "Example Person"), encoding="utf-8")
            return True, 1

        def extract_text_from_file(self, filepath):
            return Path(filepath).read_text(encoding="utf-8")

        def scan_text_for_sensitive_data(self, text):
            return {}

    port = _port(env, LegacyService())
    doc = _anonymize(port, _DOC_BYTES, "application/msword")
    txt = _anonymize(port, b"Sample Person completed a synthetic assessment.", "text/plain")

    assert doc["status"] == "unsupported" and doc["reason_code"] == "anonymization_unsupported"
    assert txt["status"] == "ok" and env.store.media_types == ["text/plain"]
