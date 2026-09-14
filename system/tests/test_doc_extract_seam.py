# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Tests for the document-extraction provider seam (T-20260818-903104603, unit 5).

Contract from ellmos-homebase-mcp/MODE-CONTRACT.md:

    mode = canonical + target unreachable  =>  clear error.
    NEVER a silent switch back to the legacy path.

The payloads here are **recorded from real calls**, not invented with mocks. In unit
4b a MagicMock with attributes let a broken adapter pass its tests and fail against
real data — a mock takes any shape, including one that does not exist. So the
canonical result is exercised through a stand-in that returns the same fields the
module actually returned:

    Ergebnis(pfad=..., format='pdf', text='Probe Dokument Text\\n\\n',
             backend='markitdown', produces='markdown',
             versuche=[('markitdown', 'ok')], hinweise=[...])

The PDF below is a real, minimal PDF; `pypdf` reads 'Probe Dokument Text' from it.
"""

import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document.pdf_service import (  # noqa: E402
    DOC_ENGINE_BUNDLED,
    DOC_ENGINE_CANONICAL,
    DOC_ENGINE_DEFAULT,
    DOC_ENGINE_ENV,
    CanonicalDocEngineUnavailable,
    DocEngineConfigError,
    PDFProcessor,
    resolve_doc_engine,
)

MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 54>>stream
BT /F1 12 Tf 20 50 Td (Probe Dokument Text) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF
"""

RECORDED_TEXT = "Probe Dokument Text\n\n"


class _RecordedErgebnis:
    """Die Felder, die `doc_services.extrahieren` tatsaechlich zurueckgab."""

    def __init__(self, pfad):
        self.pfad = pfad
        self.format = "pdf"
        self.text = RECORDED_TEXT
        self.backend = "markitdown"
        self.produces = "markdown"
        self.versuche = [("markitdown", "ok")]
        self.hinweise = ["LaTeX-PDFs verlieren bei diesem Weg Wortabstaende."]


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "probe.pdf"
    path.write_bytes(MINIMAL_PDF)
    return path


def _install_fake_module(monkeypatch, extrahieren):
    module = type(sys)("doc_services")
    module.extrahieren = extrahieren
    monkeypatch.setitem(sys.modules, "doc_services", module)


# --- engine resolution ---------------------------------------------------------------

def test_default_is_the_legacy_path():
    """Nothing changes for existing installations until equivalence is proven."""
    assert DOC_ENGINE_DEFAULT == DOC_ENGINE_BUNDLED
    assert resolve_doc_engine({}) == DOC_ENGINE_BUNDLED


def test_empty_value_falls_back_to_the_default():
    assert resolve_doc_engine({DOC_ENGINE_ENV: "   "}) == DOC_ENGINE_BUNDLED


def test_canonical_is_selectable_case_insensitively():
    assert resolve_doc_engine({DOC_ENGINE_ENV: "CANONICAL"}) == DOC_ENGINE_CANONICAL


def test_unknown_value_fails_closed():
    """A typo must not quietly read as 'legacy path'."""
    with pytest.raises(DocEngineConfigError) as excinfo:
        resolve_doc_engine({DOC_ENGINE_ENV: "canonicle"})
    assert "canonicle" in str(excinfo.value)


# --- the legacy path still works -----------------------------------------------------

def test_legacy_path_reads_the_pdf(pdf):
    """The recorded baseline: pypdf returns this text for this file."""
    assert PDFProcessor.extract_text(str(pdf)).strip() == "Probe Dokument Text"


def test_legacy_path_is_used_when_explicitly_selected(pdf, monkeypatch):
    monkeypatch.setenv(DOC_ENGINE_ENV, DOC_ENGINE_BUNDLED)

    def _must_not_run(*_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("the module was used although bundled was selected")

    _install_fake_module(monkeypatch, _must_not_run)

    assert PDFProcessor.extract_text(str(pdf)).strip() == "Probe Dokument Text"


# --- the fail-closed contract --------------------------------------------------------

def test_canonical_without_the_module_raises_and_does_not_fall_back(pdf, monkeypatch):
    """The core of the contract: loud failure, no silent fallback to pypdf."""
    monkeypatch.setenv(DOC_ENGINE_ENV, DOC_ENGINE_CANONICAL)
    monkeypatch.setattr(
        PDFProcessor, "_extract_text_bundled",
        staticmethod(lambda *_: pytest.fail("the legacy path ran although canonical was selected")),
    )
    monkeypatch.setitem(sys.modules, "doc_services", None)

    with pytest.raises(CanonicalDocEngineUnavailable) as excinfo:
        PDFProcessor.extract_text(str(pdf))

    message = str(excinfo.value)
    assert "doc-services" in message
    assert DOC_ENGINE_BUNDLED in message, "the message must name the way back"


def test_unknown_engine_value_fails_the_call(pdf, monkeypatch):
    monkeypatch.setenv(DOC_ENGINE_ENV, "nonsense")
    with pytest.raises(DocEngineConfigError):
        PDFProcessor.extract_text(str(pdf))


# --- the canonical path, against the recorded shape ----------------------------------

def test_canonical_path_returns_the_modules_text(pdf, monkeypatch):
    """Uses the fields the module really returned, not an invented shape."""
    monkeypatch.setenv(DOC_ENGINE_ENV, DOC_ENGINE_CANONICAL)
    seen = {}

    def _extrahieren(path, produces=None, **_kwargs):
        seen["path"] = path
        seen["produces"] = produces
        return _RecordedErgebnis(path)

    _install_fake_module(monkeypatch, _extrahieren)

    assert PDFProcessor.extract_text(str(pdf)) == RECORDED_TEXT
    assert seen["path"] == str(pdf)
    assert seen["produces"] == "text", (
        "der Seam muss Fliesstext verlangen -- Markdown verliert bei LaTeX-PDFs "
        "die Wortabstaende (Einheit 5b)"
    )


def test_canonical_result_without_text_field_fails_closed(pdf, monkeypatch):
    """Guards the assumption that broke the web-scrape adapter in unit 4b."""
    monkeypatch.setenv(DOC_ENGINE_ENV, DOC_ENGINE_CANONICAL)
    _install_fake_module(monkeypatch, lambda path, produces=None, **_kw: object())

    with pytest.raises(CanonicalDocEngineUnavailable) as excinfo:
        PDFProcessor.extract_text(str(pdf))
    assert "text" in str(excinfo.value)


def test_recorded_texts_agree_after_trimming(pdf):
    """What the equivalence step will have to hold — recorded, not assumed.

    The legacy path reads via pypdf, the module via markitdown, so the raw strings
    differ in trailing whitespace already. This pins the one comparison that held on
    a simple document; whether it holds on real-world PDFs is unit 5's follow-up.
    """
    legacy = PDFProcessor.extract_text(str(pdf))
    assert legacy.strip() == RECORDED_TEXT.strip()
    assert legacy != RECORDED_TEXT, "the raw strings are not identical — trailing newlines differ"
