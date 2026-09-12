# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Aequivalenz des Dokument-Seams an ECHTEN Dokumenten (T-20260818-903104603, Einheit 5b).

Warum diese Datei neben `test_doc_extract_seam.py` steht: Jene prueft den Vertrag
(fail-closed, Default, Dispatch) mit aufgezeichneten Formen und laeuft ueberall.
Diese hier prueft die AUSSAGE UEBER DIE WIRKLICHKEIT -- dass das kanonische Modul
denselben Text liefert wie der Altpfad -- und kann das nur an echten Dokumenten.

Die Messdokumente sind private Forschungsdateien und liegen deshalb NICHT im Repo.
Fehlen sie, ueberspringen die Tests; auf dem Messhost laufen sie und schlagen an,
wenn jemand den Seam, die Ausgabeform oder die Modul-Praeferenz veraendert.

Aufgezeichnet am 2026-09-13 auf ASUS-GEI:

    Weg                       Woerter   Tokens ohne Entsprechung in der .tex-Quelle
    pypdf (BACH)               14.856   6,0 %
    Modul, markitdown           8.698   36,9 %
    Modul, produces="text"     14.856   6,0 %   (byte-identisch zu pypdf)
"""

import os
import re
import sys
import unicodedata
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document.pdf_service import (  # noqa: E402
    DOC_ENGINE_CANONICAL,
    DOC_ENGINE_ENV,
    PDFProcessor,
)

# Die Messdokumente. Der Ort ist ueber eine Variable ueberschreibbar, damit ein
# anderer Host dieselbe Messung mit eigenen Dateien fahren kann.
RESEARCH = Path(
    os.environ.get(
        "BACH_DOC_EQUIV_ROOT",
        r"C:\Users\User\OneDrive\.TOPICS\.RESEARCH\.LAB",
    )
)
LATEX_PDF = RESEARCH / ".GOD/Theologie/DRAFT__Theologie_der_Offenheit/Theologie_der_Offenheit_v6_ger.pdf"
LATEX_TEX = LATEX_PDF.with_suffix(".tex")
PLAIN_PDF = RESEARCH / ".GOD/Theologie/DRAFT__Theologie_der_Offenheit/NOTIZEN/Theologie_der_Offenheit.pdf"

doc_services = pytest.importorskip(
    "doc_services", reason="das kanonische Modul ist auf diesem Host nicht installiert"
)

WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def _words(text):
    return [w.lower() for w in WORD.findall(unicodedata.normalize("NFKC", text))]


def _tex_vocabulary(path):
    """Echte Woerter der LaTeX-Quelle -- ohne Befehle, Kommentare und Mathematik."""
    src = path.read_text(encoding="utf-8", errors="replace")
    src = re.sub(r"%.*", " ", src)
    src = re.sub(r"\\[a-zA-Z@]+\s*(\[[^\]]*\])?", " ", src)
    src = re.sub(r"[{}$&]", " ", src)
    return set(_words(src))


def _foreign_ratio(text, vocab):
    """Anteil der Tokens, die es in der Quelle gar nicht gibt.

    Steigt, wenn Wortabstaende verloren gehen: zusammengeklebte Woerter ergeben
    Tokens, die in keinem Quelltext vorkommen.
    """
    toks = [w for w in _words(text) if len(w) > 3]
    assert toks, "kein Text extrahiert"
    return sum(1 for w in toks if w not in vocab) / len(toks)


needs_latex = pytest.mark.skipif(
    not (LATEX_PDF.exists() and LATEX_TEX.exists()),
    reason=f"Messdokument fehlt: {LATEX_PDF}",
)
needs_plain = pytest.mark.skipif(
    not PLAIN_PDF.exists(), reason=f"Messdokument fehlt: {PLAIN_PDF}"
)


@pytest.fixture
def canonical(monkeypatch):
    monkeypatch.setenv(DOC_ENGINE_ENV, DOC_ENGINE_CANONICAL)


@needs_latex
def test_canonical_matches_the_legacy_path_byte_for_byte(canonical):
    """Der eigentliche Aequivalenzbeweis -- an einem echten LaTeX-PDF."""
    monkey_free_bundled = PDFProcessor._extract_text_bundled(str(LATEX_PDF))
    assert PDFProcessor.extract_text(str(LATEX_PDF)) == monkey_free_bundled


@needs_plain
def test_canonical_matches_the_legacy_path_on_a_non_latex_pdf(canonical):
    """Gegenprobe: ohne LaTeX war nie etwas kaputt, und es bleibt auch so."""
    assert PDFProcessor.extract_text(str(PLAIN_PDF)) == PDFProcessor._extract_text_bundled(
        str(PLAIN_PDF)
    )


@needs_latex
def test_the_markdown_backend_really_does_lose_word_spacing():
    """Die Begruendung fuer produces='text' -- gemessen, nicht behauptet.

    Faellt dieser Test eines Tages aus, weil markitdown besser geworden ist, ist
    das eine gute Nachricht und ein Anlass, die Begruendung neu zu bewerten --
    nicht, den Test zu streichen.
    """
    vocab = _tex_vocabulary(LATEX_TEX)
    legacy = PDFProcessor._extract_text_bundled(str(LATEX_PDF))
    markdown = doc_services.extrahieren(LATEX_PDF, nur_backend="markitdown", lernen=False).text

    assert _foreign_ratio(legacy, vocab) < 0.15, "der Altpfad selbst ist die Messlatte"
    assert _foreign_ratio(markdown, vocab) > 0.25, "erwartet: verklebte Woerter"
    assert len(_words(markdown)) < 0.75 * len(_words(legacy)), (
        "erwartet: deutlich weniger Wortgrenzen als im Altpfad"
    )


@needs_latex
def test_asking_for_text_selects_a_text_backend():
    """Ohne diese Wahl waere die Aequivalenz oben gar nicht erreichbar."""
    ergebnis = doc_services.extrahieren(LATEX_PDF, produces="text", lernen=False)
    assert ergebnis.produces == "text"
    assert ergebnis.text == PDFProcessor._extract_text_bundled(str(LATEX_PDF))
