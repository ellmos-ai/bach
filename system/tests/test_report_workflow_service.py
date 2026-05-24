# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Privacy tests for ReportWorkflowService."""

import sys
import types
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document.report_workflow_service import ReportWorkflowService


def test_generate_prompt_contains_privacy_guardrails(tmp_path):
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    session.profile = types.SimpleNamespace(tarnname="Tarn Person")
    session.bundle = types.SimpleNamespace(core_text="CORE", stufe2_text="STUFE2")

    prompt = service.generate_prompt(session, include_wissensdatenbank=False)

    assert "SYSTEM-GRENZEN / DATENSCHUTZ-GATE" in prompt
    assert "Keine Dateisystem-Pruefungen" in prompt
    assert "KEINE Pfade, Dateinamen" in prompt


def test_sanitize_llm_response_removes_path_leaks(tmp_path):
    service = ReportWorkflowService(base_path=tmp_path)
    response = """
Ich pruefe kurz den Ordner.
Pfad: C:\\Users\\User\\OneDrive\\secret\\Max Mustermann
{
  "stammdaten": {
    "name": "Tarn Person"
  }
}
Gespeichert: /tmp/output_berichte/Foerderbericht_Max.docx
""".strip()

    cleaned = service.sanitize_llm_response(response)

    assert "Pfad:" not in cleaned
    assert "Gespeichert:" not in cleaned
    assert "Max Mustermann" not in cleaned
    assert '"name": "Tarn Person"' in cleaned
