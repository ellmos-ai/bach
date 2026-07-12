# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionstests fuer die Umlaut-Nachbearbeitung im Foerderbericht-Generator."""

import sys
from pathlib import Path

GENERATOR_DIR = Path(__file__).parent.parent / "agents" / "_experts" / "report_generator"
if str(GENERATOR_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATOR_DIR))

from generator import _fix_umlauts_in_values


def test_ng_before_ue_is_never_converted_to_umlaut():
    """Regressionstest: Nach De-Anonymisierung wieder eingesetzte echte
    Klientennamen wie 'Nguendon' (kamerunischer Nachname) wurden faelschlich
    zu 'Ngündon' konvertiert -- die Buchstabenfolge 'ue' wurde blind als
    Umlaut-Digraph behandelt. Allgemeine Regel statt Einzelfall-Ausnahme:
    Steht 'ng' unmittelbar vor 'ue', bleibt es 'ue' (im Deutschen folgt auf
    'ng' praktisch nie ein Umlaut-Digraph -- typisches Muster bei
    transliterierten fremdsprachigen Eigennamen wie 'Nguendon' oder 'Nguyen')."""
    data = {"name": "Nguendon Kenhagho, Chris Darrell", "note": "Herr Nguyen kam vorbei."}
    result = _fix_umlauts_in_values(data)
    assert result["name"] == "Nguendon Kenhagho, Chris Darrell", (
        f"'Nguendon' wurde faelschlich veraendert: {result['name']!r}"
    )
    assert "Nguyen" in result["note"], f"'Nguyen' wurde faelschlich veraendert: {result['note']!r}"


def test_legitimate_umlauts_still_converted():
    """Die allgemeine 'ng+ue'-Regel darf normale deutsche Umlaut-Korrekturen
    nicht beeintraechtigen."""
    data = {
        "text1": "Das ist aktuell wichtig fuer die Fuehrung.",
        "text2": "Wir muessen die Aufgabenerfuellung ueberpruefen.",
    }
    result = _fix_umlauts_in_values(data)
    assert result["text1"] == "Das ist aktuell wichtig für die Führung."
    assert "über" in result["text2"] or "Über" in result["text2"]
    assert "müssen" in result["text2"]
