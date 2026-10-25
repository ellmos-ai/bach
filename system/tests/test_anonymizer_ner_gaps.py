# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionstests: Anrede+Name-Erkennung und Gattungsbegriffe bei der NER-Anonymisierung.

Befund (synthetische Akte): 'Frau Beispiel' blieb im Prompt stehen (Nachname = Gattungsbegriff,
NER verfehlt ihn); 'Anziehen', 'Begruessung', 'Hilfeplanzeitraum' u. a. wurden als Namen maskiert.
"""

import re
import sys
import types
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import anonymizer_service as an
from hub._services.document.report_workflow_service import ReportWorkflowService


@pytest.fixture
def no_spacy(monkeypatch):
    monkeypatch.setattr(an, "SPACY_AVAILABLE", False)


def test_titled_names_are_detected_without_ner(no_spacy):
    text = (
        "Frau Beispiel begruesste ihn. Herr Kaiser vom Jugendamt rief an. "
        "Dr. med. Weber empfahl Struktur. Frau Anna Hoffmann kam spaeter."
    )
    found = an.detect_person_names_ner(text)
    for expected in ("Frau Beispiel", "Herr Kaiser", "Dr. med. Weber", "Frau Anna Hoffmann", "Frau Anna", "Hoffmann"):
        assert expected in found, f"{expected!r} fehlt in {found}"


def test_titled_names_ignore_roles_whitelist_and_lowercase(no_spacy):
    text = "Frau Mutter kam. Die frau beispiel bleibt klein. Frau Haendle ist bekannt. Herr der Ringe."
    found = an.detect_person_names_ner(text, whitelist=["Frau Haendle"])
    assert not any("Mutter" in f for f in found)
    assert not any("beispiel" in f.lower() for f in found)
    assert "Frau Haendle" not in found
    assert not any(f.startswith("Herr der") for f in found)


@pytest.mark.parametrize("word", [
    "Anziehen", "Begrüßung", "Gruppengespräch", "Schulbericht", "Hilfeplanzeitraum",
    "Zuständig", "Alltag", "Situationen", "Förderprotokoll", "Bildplan",
])
def test_common_german_words_are_not_names(word):
    assert an._is_common_german_word(word)


@pytest.mark.parametrize("name", [
    "Hoffmann", "Kaiser", "Weber", "Ehrlich", "Hennig", "Muster", "Tim", "Lena", "Jung", "Zeising",
    "Max Muster", "Frau Beispiel",
])
def test_real_names_are_not_filtered(name):
    assert not an._is_common_german_word(name)


def test_leading_role_noun_is_stripped():
    assert an._strip_leading_role_noun("Freund Tim") == "Tim"
    assert an._strip_leading_role_noun("Mutter Erika") == "Erika"
    assert an._strip_leading_role_noun("Mutter") == "Mutter"
    assert an._strip_leading_role_noun("Max Muster") == "Max Muster"


def test_ner_hits_are_filtered_and_cleaned(monkeypatch):
    """NER-Treffer: Gattungsbegriffe fliegen raus, 'Freund Tim' wird zu 'Tim'."""
    text = "Anziehen klappt. Sein Freund Tim kam. Hoffmann sagte nichts. Im Gruppengespraech."

    def ent(t):
        start = text.index(t)
        return types.SimpleNamespace(label_="PER", text=t, end_char=start + len(t))

    class FakeNlp:
        max_length = 10_000

        def __call__(self, chunk):
            return types.SimpleNamespace(ents=[ent(t) for t in ("Anziehen", "Freund Tim", "Hoffmann")])

    monkeypatch.setattr(an, "SPACY_AVAILABLE", True)
    monkeypatch.setattr(an, "_get_spacy_model", lambda name: FakeNlp())
    found = an.detect_person_names_ner(text)
    assert "Tim" in found and "Hoffmann" in found
    assert "Anziehen" not in found and "Freund Tim" not in found


def test_prompt_contains_no_cleartext_names_and_roundtrip_is_complete(tmp_path, no_spacy):
    """Leck-Test ueber den echten Workflow: Was ans Modell geht, enthaelt keine
    Klartext-Namen (auch nicht 'Frau Beispiel'); die Rueckuebersetzung stellt alles her,
    ohne Platzhalter-Reste und ohne Verwechslung."""
    akte = tmp_path / "data_roh" / "Mustermann, Max"
    akte.mkdir(parents=True)
    (akte / "Aktendeckblatt.txt").write_text(
        "Name: Max Mustermann\nGeboren am 15.03.2016\nEltern: Erika Mustermann, Hans Mustermann\n",
        encoding="utf-8",
    )
    (akte / "Protokoll_1.txt").write_text(
        "Max kam ruhig in die Gruppe. Frau Beispiel begruesste ihn. Herr Kaiser vom Jugendamt rief an. "
        "Seine Mutter Erika war dabei.\n",
        encoding="utf-8",
    )
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="15.03.2016",
        scan_folder=tmp_path / "data_roh",
        parent_names=["Erika Mustermann", "Hans Mustermann"],
    )
    service.anonymize_to_bundles(session)
    bundle = service.extract_bundle_text(session)
    sent = bundle.core_text + (bundle.stufe2_text or "")

    for clear in ("Max", "Mustermann", "Erika", "Hans", "Beispiel", "Kaiser", "15.03.2016"):
        assert not re.search(r"(?<!\w)" + re.escape(clear) + r"(?!\w)", sent), f"Klartext {clear!r} im Modell-Input"

    third = profile.get_all_mappings()
    assert "Frau Beispiel" in third and "Herr Kaiser" in third

    llm = {
        "stammdaten": {"name": profile.tarnname, "geburtsdatum": profile.fake_geburtsdatum},
        "text": [f"{third['Frau Beispiel']} begruesste {profile.tarnname}.", f"Anruf von {third['Herr Kaiser']}."],
    }
    back = service._deanonymize_json(llm, profile)
    assert back["stammdaten"]["name"] == "Max Mustermann"
    assert back["stammdaten"]["geburtsdatum"] == "15.03.2016"
    assert back["text"] == ["Frau Beispiel begruesste Max Mustermann.", "Anruf von Herr Kaiser."]
    flat = repr(back)
    assert not re.search(r"Person\d{3}", flat) and profile.tarnname not in flat


def test_multiline_ner_hit_is_still_rejected(monkeypatch):
    """Regression: Das Entfernen fuehrender Rollenbegriffe darf den Zeilenumbruch-Check
    nicht umgehen ('Frau Hoffmann\nEinrichtung' darf kein Name werden)."""
    text = "Therapeutin: Frau Hoffmann\nEinrichtung: Zentrum"
    ent = types.SimpleNamespace(label_="PER", text="Hoffmann\nEinrichtung", end_char=len("Therapeutin: Frau Hoffmann\nEinrichtung"))

    class FakeNlp:
        max_length = 10_000

        def __call__(self, chunk):
            return types.SimpleNamespace(ents=[ent])

    monkeypatch.setattr(an, "SPACY_AVAILABLE", True)
    monkeypatch.setattr(an, "_get_spacy_model", lambda name: FakeNlp())
    found = an.detect_person_names_ner(text)
    assert not any("\n" in f or "Einrichtung" in f for f in found), found
    assert "Frau Hoffmann" in found
