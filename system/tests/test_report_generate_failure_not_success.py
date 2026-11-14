"""A failed report generation must not look like a success (finding R9, Foerderplaner A13).

generate_report() returns None and sets session.error_message when no document was made
(template missing, generator failed, python-docx missing). The GUI route used to answer
{"success": true, "output_path": "None"}. Synthetic data only.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


def _call(monkeypatch, tmp_path, *, output, error_message="", status="error"):
    from gui import server as gui_server
    session = SimpleNamespace(status=status, error_message=error_message)
    service = SimpleNamespace(
        get_session=lambda _sid: session,
        generate_report=lambda *_a, **_k: output,
    )
    monkeypatch.setattr(gui_server, "get_report_workflow_service", lambda: service)
    return asyncio.run(gui_server.generate_session_report("s1", {"llm_response": "Synthetischer Text"}))


@pytest.mark.parametrize("message,reason", [
    ("Vorlage nicht gefunden: vorlage.docx. Pfad per Umgebungsvariable binden", "template_missing"),
    ("Generator-Fehler: Feld Mustername leer", "generator_failed"),
    ("python-docx nicht installiert", "docx_missing"),
    ("", "unknown"),
])
def test_none_from_generate_report_is_a_failure_with_code_and_reason(monkeypatch, tmp_path, message, reason):
    result = _call(monkeypatch, tmp_path, output=None, error_message=message)
    assert result["success"] is False
    assert result["code"] == "report_not_generated"
    assert result["reason"] == reason
    assert "output_path" not in result
    assert "Mustername" not in str(result), "session error text may carry case data; only finite reasons"


def test_missing_file_is_a_failure_too(monkeypatch, tmp_path):
    result = _call(monkeypatch, tmp_path, output=tmp_path / "gibt_es_nicht.docx", status="completed")
    assert result["success"] is False and result["code"] == "report_not_generated"


def test_real_document_is_still_a_success(monkeypatch, tmp_path):
    doc = tmp_path / "Bericht.docx"
    doc.write_bytes(b"x")
    result = _call(monkeypatch, tmp_path, output=doc, status="completed")
    assert result["success"] is True
    assert Path(result["output_path"]) == doc
