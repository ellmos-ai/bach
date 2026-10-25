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
    "Anziehen", "Gruppengespräch", "Schulbericht", "Hilfeplanzeitraum",
    "Zuständig", "Alltag", "Situationen", "Förderprotokoll", "Bildplan",
])
def test_common_german_words_are_not_names(word):
    assert an._is_common_german_word(word)


@pytest.mark.parametrize("word,text", [
    ("Begrüßung", "Bei der Begrüßung hielt er Blickkontakt."),
    ("Förderung", "Die Förderung läuft weiter."),
    ("Entwicklung", "Seine Entwicklung ist positiv."),
])
def test_suffix_words_are_common_only_with_noun_context(word, text):
    assert an._is_common_german_word(word, text)
    assert not an._is_common_german_word(word, f"{word} rief an."), "ohne Artikel-Kontext konservativ: Name"


def _fake_ner(monkeypatch, text, names):
    def ent(t):
        return types.SimpleNamespace(label_="PER", text=t, end_char=text.index(t) + len(t))

    class FakeNlp:
        max_length = 10_000

        def __call__(self, chunk):
            return types.SimpleNamespace(ents=[ent(n) for n in names])

    monkeypatch.setattr(an, "SPACY_AVAILABLE", True)
    monkeypatch.setattr(an, "_get_spacy_model", lambda name: FakeNlp())


def test_surname_with_common_suffix_is_kept_when_ner_finds_it(monkeypatch):
    """P2 aus der Zweitpruefung: 'Hartung' (Endung -ung, > 6 Zeichen) ist ein Nachname und darf nicht
    allein wegen der Endung verworfen werden."""
    text = "Hartung rief an. Rosenheit kam spaeter."
    _fake_ner(monkeypatch, text, ["Hartung", "Rosenheit"])
    found = an.detect_person_names_ner(text)
    assert "Hartung" in found and "Rosenheit" in found


def test_same_hit_with_noun_context_is_dropped(monkeypatch):
    """Gegenprobe: derselbe Treffer MIT Artikel-Kontext ('Bei der Begruessung') wird verworfen."""
    text = "Bei der Begrüßung gab es nichts."
    _fake_ner(monkeypatch, text, ["Begrüßung"])
    assert "Begrüßung" not in an.detect_person_names_ner(text)


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


def test_manual_term_list_expands_names_with_titles_and_unique_placeholders():
    from hub._services.document.report_workflow_service import _expand_manual_terms

    pairs = _expand_manual_terms(["Nachtigall", "Anna Hoffmann", "Musterstr. 5"], set())
    forms = dict(pairs)
    for f in ("Nachtigall", "Frau Nachtigall", "Herr Nachtigall", "Dr. Nachtigall", "NACHTIGALL",
              "Anna Hoffmann", "Frau Anna Hoffmann", "Hoffmann", "Frau Hoffmann", "Anna", "Musterstr. 5"):
        assert f in forms, f
    assert "Frau Musterstr. 5" not in forms  # Adresse ist kein Name
    # eigener Platzhalter je Schreibweise; GROSS-Variante teilt den der Normalform
    normal = {f: p for f, p in pairs if not f.isupper() or f == f.lower()}
    assert forms["NACHTIGALL"] == forms["Nachtigall"]
    assert len({forms[f] for f in ("Nachtigall", "Frau Nachtigall", "Herr Nachtigall")}) == 3
    # Whitelist wird respektiert
    assert "Frau Nachtigall" not in dict(_expand_manual_terms(["Nachtigall"], {"Frau Nachtigall"}))


def test_manual_term_list_masks_names_that_detection_cannot_find_and_roundtrips(tmp_path, no_spacy):
    """Vorrangige Quelle: 'Nachtigall' steht teils ohne Anrede im Text (weder NER noch
    Anrede-Regel greifen). Die manuelle Liste je Klient maskiert alle Schreibweisen und die
    Rueckuebersetzung stellt jede Schreibweise einzeln und unverwechselt wieder her."""
    akte = tmp_path / "data_roh" / "Mustermann, Max"
    akte.mkdir(parents=True)
    (akte / "Protokoll_1.txt").write_text(
        "Max Mustermann kam ruhig. Frau Nachtigall begruesste ihn. Spaeter sagte Nachtigall: weiter so. "
        "Anruf bei NACHTIGALL und Beispielweg 7.\n", encoding="utf-8")
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session, client_name="Max Mustermann", geburtsdatum="15.03.2016",
        scan_folder=tmp_path / "data_roh", additional_terms=["Nachtigall", "Beispielweg 7"],
    )
    service.anonymize_to_bundles(session)
    bundle = service.extract_bundle_text(session)
    sent = bundle.core_text + (bundle.stufe2_text or "")
    for clear in ("Nachtigall", "NACHTIGALL", "Beispielweg", "Mustermann"):
        assert clear not in sent, f"{clear!r} im Modell-Input"

    m = profile.get_all_mappings()
    assert m["Frau Nachtigall"].startswith("BEGRIFF_"), "manuelle Liste muss vor der Erkennung gewinnen"
    llm = {"a": f"{m['Frau Nachtigall']} und {m['Nachtigall']} wohnen in {m['Beispielweg 7']}."}
    back = service._deanonymize_json(llm, profile)
    assert back["a"] == "Frau Nachtigall und Nachtigall wohnen in Beispielweg 7."
    assert "BEGRIFF_" not in repr(back)



@pytest.mark.parametrize("text", [
    "Kontakt: Frau  Beispiel kam.",       # doppeltes Leerzeichen
    "Kontakt: Frau\tBeispiel kam.",       # Tab
    "Kontakt: Frau\nBeispiel kam.",       # Zeilenumbruch
    "Kontakt: Frau Beispiel kam.",        # Kontrolle: einfaches Leerzeichen
])
def test_titled_name_candidates_actually_mask_all_whitespace_variants(no_spacy, text):
    """P2 aus der Zweitpruefung: Erkennung ohne Ersetzung. Jetzt behalten die Kandidaten die exakte
    Quell-Schreibweise; die echte Ersetzungsfunktion muss 'Beispiel' tatsaechlich entfernen."""
    found = an.detect_person_names_ner(text)
    masked = text
    for cand in sorted(found, key=len, reverse=True):
        masked, _ = an._replace_word_boundary(masked, cand, "PersonXYZ")
    assert "Beispiel" not in masked, (found, masked)
    assert "PersonXYZ" in masked


def test_titled_name_with_irregular_whitespace_roundtrips_through_workflow(tmp_path, no_spacy):
    akte = tmp_path / "data_roh" / "Mustermann, Max"
    akte.mkdir(parents=True)
    (akte / "Protokoll_1.txt").write_text(
        "Max Mustermann kam. Frau  Nachtigall begruesste ihn, danach Herr\tKaiser.\n", encoding="utf-8")
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session, client_name="Max Mustermann", geburtsdatum="15.03.2016", scan_folder=tmp_path / "data_roh")
    service.anonymize_to_bundles(session)
    sent = service.extract_bundle_text(session).core_text
    for clear in ("Nachtigall", "Kaiser", "Mustermann"):
        assert clear not in sent, f"{clear!r} im Modell-Input"
