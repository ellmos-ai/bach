# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Befunde R6 der Zweitpruefung zu bach#666 (T-20261107-347299705): Ersetzung und Datenschutz-Sperre.

R6-1 gebeugte Namensformen, R6-2 Datumsformen, R6-3 Umschriften und Dateinamen, R6-4 Cloud-Weg ohne
NER fail-closed (Modul-CLI), R6-5 kein alter Klartext-Prompt nach verweigertem Cloud-Lauf.
Nur erfundene Namen und Daten, kein Netz, kein Modellaufruf.
"""

import json
import sys
import unicodedata
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import anonymizer_service  # noqa: E402
from hub._services.document import report_workflow_service as rws  # noqa: E402
from hub._services.document.anonymizer_service import DocumentAnonymizer, _apply_replacements  # noqa: E402
from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline  # noqa: E402

CLIENT, DOB = "Jörg Grünwälder", "14.05.2017"
INFLECTED = ["Grünwälders Mutter berichtet.", "Bei Grünwälders zu Hause.", "Jörgs Fortschritte.",
             "Frau Grünwälderin rief an.", "GRÜNWÄLDERS Akte"]
DATES = ["14/05/2017", "14-05-2017", "14 Mai 2017", "14. 05. 2017", "05/14/2017", "2017/05/14",
         "14.Mai.2017", "14. Mai 17", "14 mai 2017"]
SPELLINGS = ["Joerg Gruenwaelder", "Jorg Grunwalder", "Bericht_Grünwälder_2025", "Bericht_Joerg_Gruenwaelder_2025",
             unicodedata.normalize("NFD", "Grünwälder") + " kam."]
LEAKS = INFLECTED + DATES + SPELLINGS


def _fold(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return text.replace("ae", "a").replace("oe", "o").replace("ue", "u").replace("_", " ")


def _profile(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    service = rws.ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(session, CLIENT, DOB)
    profile.document_scanned = True  # Scan-/NER-Sperre: eigene Tests (test_report_gui_privacy.py)
    return service, session, profile


class _Bundle:
    def __init__(self, text):
        self.core_text, self.stufe2_text = text, ""


@pytest.mark.parametrize("leak", LEAKS)
def test_gate_blocks_every_form_of_the_case_data(tmp_path, monkeypatch, leak):
    service, session, _ = _profile(tmp_path, monkeypatch)
    session.bundle = _Bundle(f"Protokoll: {leak}")

    with pytest.raises(rws.PromptPrivacyError) as exc:
        service.generate_prompt(session, include_wissensdatenbank=False)
    assert exc.value.code == "identity_terms_in_prompt"


@pytest.mark.parametrize("leak", LEAKS)
def test_replacement_removes_every_form_so_the_gate_lets_it_pass(tmp_path, monkeypatch, leak):
    service, session, profile = _profile(tmp_path, monkeypatch)
    replaced, _ = _apply_replacements(f"Protokoll: {leak}",
                                      DocumentAnonymizer._sorted_replacements(profile.to_anonym_profile()))
    session.bundle = _Bundle(replaced)

    prompt = service.generate_prompt(session, include_wissensdatenbank=False)  # keine Sperre

    folded = _fold(prompt)
    assert "grunwalder" not in folded and "jorg" not in folded, replaced
    assert anonymizer_service.date_pattern(DOB).search(prompt) is None, replaced


def test_inflected_pseudonym_restores_to_the_inflected_original(tmp_path, monkeypatch):
    service, _, profile = _profile(tmp_path, monkeypatch)
    tarn_last = profile.mappings["names"]["Grünwälder"]
    assert service._deanonymize_text(f"{tarn_last}s Mutter", profile) == "Grünwälders Mutter"


def test_other_date_spellings_restore_to_the_original(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "_generate_fake_date_same_age", lambda real: ("13.11.2015", 0))
    service, _, profile = _profile(tmp_path, monkeypatch)
    assert service._deanonymize_text("geb. 13/11/2015", profile) == "geb. 14/05/2017"
    assert service._deanonymize_text("13.11.2015", profile) == DOB  # Hauptform gewinnt weiter


def test_unrelated_dates_stay_untouched(tmp_path, monkeypatch):
    """05.03.2017 ist ein anderes Datum, auch wenn die US-Lesung des Geburtstags aehnlich aussieht."""
    service, session, profile = _profile(tmp_path, monkeypatch)
    text = "Termine am 05.03.2017, 14.06.2017 und 15.05.2017."
    replaced, count = _apply_replacements(text, DocumentAnonymizer._sorted_replacements(profile.to_anonym_profile()))
    assert replaced == text and count == 0
    session.bundle = _Bundle(text)
    service.generate_prompt(session, include_wissensdatenbank=False)  # keine Sperre


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""))
    monkeypatch.setattr(anonymizer_service, "detect_person_names_ner", lambda text, whitelist=None: [])
    return tmp_path


def test_pipeline_cloud_prompt_carries_none_of_the_r6_forms(cloud):
    client = cloud / "data_roh" / "Gruenwaelder, Joerg"
    client.mkdir(parents=True)
    (client / "Aktendeckblatt.txt").write_text(f"Name: {CLIENT}\nGeboren am {DOB}\n", encoding="utf-8")
    (client / "Bericht_Joerg_Gruenwaelder_2025.txt").write_text(
        "Verlauf: " + " ".join(LEAKS) + " Fortschritte in der Feinmotorik.\n", encoding="utf-8")

    res = FoerderberichtPipeline(base_path=cloud).prepare_prompt(client_name=CLIENT, geburtsdatum=DOB)

    assert res.success, res.error
    prompt = (cloud / "data_bundled" / "prompt.txt").read_text(encoding="utf-8")
    folded = _fold(prompt)
    for part in ("grunwalder", "jorg"):
        assert part not in folded, part
    assert anonymizer_service.date_pattern(DOB).search(prompt) is None
    assert "feinmotorik" in folded


def test_fake_email_never_reuses_a_real_name_part(monkeypatch):
    """Sonst sperrt die Sperre den eigenen Tarnwert ("jonas.hofmann@..."; zufaellig, etwa 1 von 40 e2e-Laeufen)."""
    monkeypatch.setattr(anonymizer_service.secrets, "choice",
                        lambda seq: next((s for s in seq if str(s).lower() in ("jonas", "leonhardt")), seq[0]))
    fake = anonymizer_service._generate_fake_email(excluded_name_parts=["Jonas Leonhardt", "Sabine Leonhardt"])
    assert "jonas" not in fake.lower() and "leonhardt" not in fake.lower()


# --- R6-4: Modul-CLI ohne NER ------------------------------------------------------------------

def test_module_cli_refuses_cloud_prompt_without_ner_before_touching_files(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "BERICHTE_BASE", tmp_path / "Berichte")
    monkeypatch.setattr(anonymizer_service, "SPACY_AVAILABLE", False)
    akte = tmp_path / "akte"
    akte.mkdir()
    (akte / "Protokoll.txt").write_text(f"{CLIENT} war da.", encoding="utf-8")

    with pytest.raises(rws.PromptPrivacyError) as exc:
        rws.quick_report(akte, CLIENT, DOB)
    assert exc.value.code == "ner_unavailable"
    assert not any((tmp_path / "Berichte" / "data_roh").glob("*"))


# --- R6-5: alter Klartext-Prompt -----------------------------------------------------------------

def test_refused_cloud_run_leaves_no_plaintext_prompt_of_an_earlier_local_run(tmp_path, monkeypatch):
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(anonymizer_service, "SPACY_AVAILABLE", False)
    client = tmp_path / "data_roh" / "Gruenwaelder, Joerg"
    client.mkdir(parents=True)
    (client / "Protokoll.txt").write_text(f"{CLIENT} war da.", encoding="utf-8")
    bundled = tmp_path / "data_bundled"
    bundled.mkdir()
    (bundled / "prompt.txt").write_text(f"Klartext: {CLIENT}", encoding="utf-8")  # frueherer Lauf, Modus lokal
    (bundled / "bundle.txt").write_text(f"Klartext: {CLIENT}", encoding="utf-8")
    (bundled / "session_info.json").write_text(json.dumps({"original_name": CLIENT}), encoding="utf-8")

    res = FoerderberichtPipeline(base_path=tmp_path).prepare_prompt(client_name=CLIENT, geburtsdatum=DOB)

    assert not res.success and "spaCy" in res.error
    assert not any(bundled.iterdir()), [p.name for p in bundled.iterdir()]
