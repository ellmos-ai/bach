# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests: E-Mail-Anonymisierung .eml/.msg (Task #802).

Deckt:
  - extract_text_from_file fuer .eml (Scanning-Pfad fuer sensible Daten)
  - _anonymize_eml: strukturerhaltende Anonymisierung von Kopfzeilen,
    Textkoerper und Anlage-DATEINAMEN (Unterstreich-Schreibweise!)
  - Rundlauf Anonymisieren -> De-Anonymisieren (Reverse-Mappings)
  - Fail-closed: ungueltiger Eingang wird entfernt, nicht durchgewunken
  - _anonymize_msg: fail-closed bei ungueltiger .msg (ohne echte Datei
    pruefbar, da extract_msg keine .msg SCHREIBEN kann)
"""

import sys
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document.anonymizer_service import (
    AnonymProfile,
    DocumentAnonymizer,
    DocumentDeanonymizer,
)


def _make_profile():
    return AnonymProfile(
        client_id="K_TEST",
        tarnname="Felix Bergmann",
        fake_geburtsdatum="07.04.2014",
        mappings={
            "names": {"Max Mustermann": "Felix Bergmann"},
            "dates": {"02.03.2014": "07.04.2014"},
            "addresses": {"Musterstr. 5": "Waldweg 12"},
            "misc": {
                "max.mustermann@beispiel.de": "felix.bergmann@example.org",
                "07761/123456": "07741/987654",
            },
        },
    )


def _write_simple_eml(path: Path):
    m = EmailMessage()
    m["From"] = "Max Mustermann <max.mustermann@beispiel.de>"
    m["To"] = "Jugendamt Musterstadt <jugendamt@musterstadt.de>"
    m["Subject"] = "Elternbrief Max Mustermann"
    m.set_content("Guten Tag, hier Max Mustermann, Telefon 07761/123456.")
    path.write_bytes(m.as_bytes())


def test_extract_text_from_file_eml(tmp_path):
    """Scanning-Pfad: Kopfzeilen + Body muessen im extrahierten Text landen."""
    path = tmp_path / "Mail.eml"
    _write_simple_eml(path)

    text = DocumentAnonymizer().extract_text_from_file(str(path))
    assert "Max Mustermann" in text
    assert "max.mustermann@beispiel.de" in text
    assert "Elternbrief" in text
    assert "07761/123456" in text


def test_anonymize_eml_headers_body_and_deanonymize_roundtrip(tmp_path):
    """Kopfzeilen + Body anonymisieren, anschliessend Rueckweg pruefen."""
    path = tmp_path / "Mail.eml"
    _write_simple_eml(path)

    anonymizer = DocumentAnonymizer()
    ok, count = anonymizer.anonymize_file(str(path), _make_profile())
    assert ok, "EML-Anonymisierung schlug fehl"
    assert count >= 4, f"Erwartet >=4 Ersetzungen (Name/Name/Mail/Telefon), got {count}"

    raw = path.read_bytes()
    assert b"Max Mustermann" not in raw, "Klartextname verbleibt in der EML"
    assert b"max.mustermann@beispiel.de" not in raw, "Klartext-Mailadresse verbleibt"

    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert "Felix Bergmann" in str(msg["From"])
    assert "felix.bergmann@example.org" in str(msg["From"])
    assert "Felix Bergmann" in str(msg["Subject"])
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Felix Bergmann" in body
    assert "07741/987654" in body

    # De-Anonymisierung (Rueckweg ueber DocumentDeanonymizer / Reverse-Mappings)
    ok2, _ = DocumentDeanonymizer().deanonymize_file(str(path), _make_profile())
    assert ok2
    raw_back = path.read_bytes()
    assert b"Max Mustermann" in raw_back
    assert b"max.mustermann@beispiel.de" in raw_back


def test_anonymize_eml_attachment_name_and_intact_payload(tmp_path):
    """
    Multipart: Anlage-DATEINAMEN werden ersetzt (auch Unterstrich-Schreibweise,
    \b-Wortgrenzen greifen dort nicht), Anlagen-INHALTE bleiben intakt
    (dokumentierte Grenze: Anlagen sind separate Dokumente).
    """
    path = tmp_path / "Anhangsmail.eml"
    m = EmailMessage()
    m["From"] = "Max Mustermann <max.mustermann@beispiel.de>"
    m["Subject"] = "Unterlagen"
    m.set_content("Bericht ueber Max Mustermann im Anhang.")
    payload = b"PDFDATA-Bytes Max Mustermann"
    m.add_attachment(
        payload, maintype="application", subtype="octet-stream",
        filename="Bericht_Max_Mustermann.pdf",
    )
    path.write_bytes(m.as_bytes())

    ok, count = DocumentAnonymizer().anonymize_file(str(path), _make_profile())
    assert ok

    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    att = next(p for p in msg.walk() if p.get_filename())
    assert att.get_filename() == "Bericht_Felix_Bergmann.pdf", (
        f"Anlagenname nicht anonymisiert: {att.get_filename()!r}"
    )
    # Anlagen-Inhalt MUSS byteidentisch bleiben
    assert att.get_payload(decode=True) == payload
    # Body ebenfalls anonymisiert
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Felix Bergmann" in body


def test_anonymize_eml_fail_closed_on_garbage(tmp_path):
    """Ungueltige Eingabe: Datei entfernen, KEIN Erfolg melden."""
    path = tmp_path / "garbage.eml"
    path.write_bytes(b"\x00\x01 kein gueltiges Mailformat")

    ok, count = DocumentAnonymizer().anonymize_file(str(path), _make_profile())
    assert not ok
    assert not path.exists(), "Unanonymisierbarer Muelleingang wurde im Output belassen"


def test_anonymize_msg_fail_closed_on_invalid_file(tmp_path):
    """Ungueltige .msg (binaerer Muelleingang): fail-closed wie bei .eml."""
    path = tmp_path / "garbage.msg"
    path.write_bytes(b"\x00m\x00ull kein OLE")

    ok, count = DocumentAnonymizer().anonymize_file(str(path), _make_profile())
    assert not ok
    assert not path.exists(), "Unlesbare .msg wurde unanonymisiert im Output belassen"