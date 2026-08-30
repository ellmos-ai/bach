# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionstest fuer DocumentPipeline._extract_docx() -- Ticket T-20260817-825816579.

`row.cells` liefert in python-docx eine ueber mehrere Rasterspalten verbundene
Zelle einmal PRO SPALTE. Ohne Dedup ueber die Identitaet des zugrunde
liegenden <w:tc>-Elements wird der Zellinhalt so oft wiederholt, wie er
Spalten ueberspannt (gemessen: Faktor 17,8x an einer realen Formular-DOCX).
Dieser Test baut eine synthetische DOCX mit einer horizontal verbundenen
Zelle und prueft, dass der extrahierte Text jeden eindeutigen Zellinhalt
genau einmal enthaelt.
"""
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

docx = pytest.importorskip("docx")

from hub._services.document.document_pipeline import DocumentPipeline


def _build_docx_with_merged_header(path: Path) -> None:
    """Tabelle mit 4 Spalten; Zeile 1 ist eine ueber alle 4 Spalten verbundene
    Ueberschriftszelle ("LERNVEREINBARUNG"), Zeile 2 hat vier eigenstaendige
    Zellen -- genau das Formular-Muster aus dem Ticket."""
    doc = docx.Document()
    table = doc.add_table(rows=2, cols=4)
    header_cell = table.cell(0, 0).merge(table.cell(0, 3))
    header_cell.text = "LERNVEREINBARUNG"
    for i, text in enumerate(["Name", "Datum", "Ort", "Unterschrift"]):
        table.cell(1, i).text = text
    doc.save(str(path))


def test_extract_docx_deduplicates_merged_cells(tmp_path):
    docx_path = tmp_path / "merged.docx"
    _build_docx_with_merged_header(docx_path)

    # Gegenprobe: row.cells zaehlt die verbundene Zelle 4x, tc-Identitaet nur 1x.
    doc = docx.Document(str(docx_path))
    row0 = doc.tables[0].rows[0]
    assert len(row0.cells) == 4
    assert len({id(c._tc) for c in row0.cells}) == 1

    pipeline = DocumentPipeline()
    extracted = pipeline._extract_docx(str(docx_path))

    lines = [line for line in extracted.split("\n") if line.strip()]
    header_lines = [line for line in lines if "LERNVEREINBARUNG" in line]

    assert header_lines == ["LERNVEREINBARUNG"], (
        f"verbundene Ueberschriftszelle wurde vervielfacht statt dedupliziert: {header_lines!r}"
    )
    assert "Name | Datum | Ort | Unterschrift" in extracted


def test_extract_docx_keeps_unmerged_rows_unchanged(tmp_path):
    """Reine Nicht-Regression: eine Tabelle ohne verbundene Zellen bleibt
    unveraendert (jede Zelle einmal, in Reihenfolge)."""
    docx_path = tmp_path / "plain.docx"
    doc = docx.Document()
    table = doc.add_table(rows=1, cols=3)
    for i, text in enumerate(["A", "B", "C"]):
        table.cell(0, i).text = text
    doc.save(str(docx_path))

    pipeline = DocumentPipeline()
    extracted = pipeline._extract_docx(str(docx_path))

    assert "A | B | C" in extracted
