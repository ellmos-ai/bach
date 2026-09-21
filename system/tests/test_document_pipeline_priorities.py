# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionstest fuer die Dokumenten-Priorisierung in DocumentPipeline -- Task #803.

Schema (Task #803, verfeinert im Report-Workflow-Prompt):
  Prio1 (HOCH): Doku/Protokolle, Hilfeplan, Aktendeckblatt, Bewilligung
                -- inkl. root_dokument (Root-Dateien sind laut DOC_TYPE_PRIORITY
                   das Hauptprotokoll/Verlaufsprotokoll)
  Prio2:        Foerderstellen-Berichte (CORE-MEDIUM), Arzt-/Schulberichte
                aktuell (STUFE2, nach CORE)
  Prio3/Rest:   Alte Dokumente (>10 Jahre / EXTENDED) nur auf Anforderung

Zusaetzlich: Fehler- und Platzhalter-Texte der Extraktion
([FEHLER ...], [PDF-Extraktion fehlgeschlagen ...], [.doc-Extraktion
fehlgeschlagen ...]) duerfen niemals als "Dokumentinhalt" ins LLM-Bundle leaken.
"""
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document.document_pipeline import (
    DocumentPipeline,
    DocumentCategory,
)

_SYNTHETIC_AKTE = {
    # Root: kein Pattern-Match, kein .docx -> root_dokument (Hauptprotokoll)
    "Klient_Akte.txt": "INHALT ROOT VERLAUFSPROTOKOLL HAUPTDOKUMENT",
    # Root: unlesbares PDF -> Extraktion schlaegt fehl, darf nicht ins Bundle
    "Kaputter_Scan.pdf": "KEIN ECHTES PDF FORMAT",
    "Dokumentation/Protokoll_Einzeltherapie_2026-08.txt": "INHALT EINZELTHERAPIE PROTOKOLL",
    "Dokumentation/Foerderbericht_proAutismus_2025.txt": "INHALT PROAUTISMUS BERICHT",
    "Hilfeplan/Hilfeplan_2025.txt": "INHALT HILFEPLAN KOSTENZUSAGE",
    "Aktendeckblatt/Aktendeckblatt_Klient.txt": "INHALT AKTENDECKBLATT STAMMDATEN",
    "Arzt/Arztbericht_2026-03.txt": "INHALT ARZTBERICHT AKTUELL",
    "Schule/Schulbericht_2026-06.txt": "INHALT SCHULBERICHT AKTUELL",
    "Archiv/Arztbericht_2010-05.txt": "INHALT ARZTBERICHT ALT",
}


def _build_akte(base: Path) -> Path:
    """Legt die synthetische Klienten-Akte unter base/klient an."""
    root = base / "klient"
    for rel_path, content in _SYNTHETIC_AKTE.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def test_bundle_prioritaet_prio1_bis_rest(tmp_path):
    root = _build_akte(tmp_path)
    pipeline = DocumentPipeline()
    result = pipeline.scan_folder(str(root), recursive=True)
    bundle = pipeline.extract_bundle(result.documents, include_extended=False)

    core, stufe2 = bundle.core_text, bundle.stufe2_text
    hi = core.find("HOHE PRIORITAET")
    mi = core.find("MITTLERE PRIORITAET")

    # Sections vorhanden und in richtiger Reihenfolge
    assert hi != -1, "HIGH-Section fehlt im Bundle"
    assert mi != -1, "MEDIUM-Section fehlt im Bundle"
    assert hi < mi, "HIGH-Section muss vor MEDIUM stehen"

    # Prio1: Doku/Hilfeplan/Aktendeckblatt (+ root_dokument-Hauptprotokoll)
    for needle in (
        "EINZELTHERAPIE PROTOKOLL",
        "HILFEPLAN KOSTENZUSAGE",
        "AKTENDECKBLATT STAMMDATEN",
        "ROOT VERLAUFSPROTOKOLL HAUPTDOKUMENT",
    ):
        assert hi < core.find(needle) < mi, f"Prio1 verletzt: {needle} nicht in HIGH"

    # Prio2: Foerderstellen-Bericht in CORE-MEDIUM, Arzt/Schule aktuell in STUFE2
    assert mi < core.find("PROAUTISMUS BERICHT"), "Foerderstellen-Bericht fehlt in MEDIUM"
    assert "ARZTBERICHT AKTUELL" in stufe2, "Arztbericht aktuell gehoert in STUFE2"
    assert "SCHULBERICHT AKTUELL" in stufe2, "Schulbericht aktuell gehoert in STUFE2"

    # Prio3/Rest: alter Arztbericht ist EXTENDED und ohne include_extended draussen
    assert "ARZTBERICHT ALT" not in core and "ARZTBERICHT ALT" not in stufe2

    # root_dokument darf nicht in STUFE2/EXTENDED landen
    assert "ROOT VERLAUFSPROTOKOLL" not in stufe2


def test_bundle_schliesst_extraktionsfehler_aus(tmp_path):
    """Fehler-/Platzhalter-Texte der Extraktion duerfen nicht ins Bundle leaken."""
    root = _build_akte(tmp_path)
    pipeline = DocumentPipeline()
    result = pipeline.scan_folder(str(root), recursive=True)

    # Gegenprobe: das kaputte PDF wird gescannt (Metadaten), ...
    scanned = [d for d in result.documents if d.filename == "Kaputter_Scan.pdf"]
    assert scanned, "kaputtes PDF fehlt im Scan-Ergebnis"

    # ... aber sein Fehler-Text darf im Bundle nicht auftauchen.
    bundle = pipeline.extract_bundle(result.documents, include_extended=False)
    for marker in ("PDF-Extraktion fehlgeschlagen", "FEHLER bei"):
        assert marker not in bundle.core_text
        assert marker not in bundle.stufe2_text


def test_scan_kategorisiert_nach_relevanz(tmp_path):
    """Scan-Kategorien: CORE (Prio1/2), STUFE2 (Arzt/Schule aktuell), EXTENDED (alt)."""
    root = _build_akte(tmp_path)
    pipeline = DocumentPipeline()
    result = pipeline.scan_folder(str(root), recursive=True)

    by_name = {d.filename: d for d in result.documents}
    assert by_name["Hilfeplan_2025.txt"].category == DocumentCategory.CORE
    assert by_name["Aktendeckblatt_Klient.txt"].category == DocumentCategory.CORE
    assert by_name["Protokoll_Einzeltherapie_2026-08.txt"].category == DocumentCategory.CORE
    assert by_name["Klient_Akte.txt"].doc_type == "root_dokument"
    assert by_name["Klient_Akte.txt"].category == DocumentCategory.CORE
    assert by_name["Arztbericht_2026-03.txt"].category == DocumentCategory.STUFE2
    assert by_name["Schulbericht_2026-06.txt"].category == DocumentCategory.STUFE2
    assert by_name["Arztbericht_2010-05.txt"].category == DocumentCategory.EXTENDED

    # Sortierung: CORE vor STUFE2 vor EXTENDED
    cats = [d.category for d in result.documents]
    order = {DocumentCategory.CORE: 0, DocumentCategory.STUFE2: 1, DocumentCategory.EXTENDED: 2}
    ranks = [order[c] for c in cats]
    assert ranks == sorted(ranks), f"Kategorie-Reihenfolge falsch: {cats}"