# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regressionstests: Anrede+Name-Erkennung und Gattungsbegriffe bei der NER-Anonymisierung.

Befund (synthetische Akte): 'Frau Beispiel' blieb im Prompt stehen (Nachname = Gattungsbegriff,
NER verfehlt ihn); 'Anziehen', 'Begruessung', 'Hilfeplanzeitraum' u. a. wurden als Namen maskiert.
"""

import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import anonymizer_service as an
from hub._services.document.report_workflow_service import (
    DEFAULT_WHITELIST,
    ReportWorkflowService,
)


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


# Task 2620: only synthetic inputs; no provider/LLM invocation.
@pytest.fixture
def offline_real_ner(monkeypatch):
    import socket

    import spacy

    def no_network(*args, **kwargs):
        raise AssertionError("Network access is forbidden in synthetic anonymizer tests")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert an.SPACY_AVAILABLE
    for model_name in an.NER_MODELS:
        model = an._get_spacy_model(model_name)
        assert isinstance(model, spacy.language.Language), model_name
        assert "ner" in model.pipe_names
        assert model.meta["version"] == "3.8.0"


@pytest.mark.parametrize("phone", ["07623 / 555123", "0761 / 2012345", "07623 555123", "0761/2012345"])
def test_2620_phone_separator_variants_are_complete(phone, no_spacy):
    found = an.DocumentAnonymizer().scan_text_for_sensitive_data("Telefon: " + phone)
    assert phone in found["phones"]


@pytest.mark.parametrize("date", ["2026-10-25", "2016-03-15", "Bericht_2026-10-25.txt", "15.03.2016"])
def test_2620_dates_are_not_phone_numbers(date, no_spacy):
    assert not an.DocumentAnonymizer().scan_text_for_sensitive_data(date)["phones"]


def test_2620_title_only_surname_becomes_word_bounded_alias(no_spacy):
    found = an.detect_person_names_ner("Frau Beispiel kommt.")
    assert "Beispiel" in found
    text = "Beispiel sagte zu. Die Beispiele und Beispielweg bleiben unverändert."
    masked, count = an._replace_word_boundary(text, "Beispiel", "PersonXYZ")
    assert count == 1
    assert masked == "PersonXYZ sagte zu. Die Beispiele und Beispielweg bleiben unverändert."
    for excluded in ("Alltag", "Anziehen", "Essen", "Mutter", "Hilfeplanzeitraum"):
        assert excluded not in an.detect_person_names_ner("Frau " + excluded + " kommt.")
    assert "Beispiel" not in an.detect_person_names_ner("Frau Beispiel kommt.", whitelist=["Frau Beispiel"])


def test_2620_known_parent_email_is_masked_without_name_in_document(tmp_path, offline_real_ner):
    folder = tmp_path / "data_roh" / "Muster, Max"
    folder.mkdir(parents=True)
    private = ("erika.beispiel@example.org", "ERIKA.BEISPIEL@familie.invalid")
    retained = ("info@jugendamt.example", "kontakt@firma.example", "maximal@firma.example", "Erika.Beispiel@amt.example")
    (folder / "Protokoll_1.txt").write_text("Kontakt: " + "; ".join(private + retained), encoding="utf-8")
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(session, client_name="Max Muster", geburtsdatum="15.03.2016",
        parent_names=["Erika Beispiel"], whitelist=[retained[-1]], scan_folder=tmp_path / "data_roh")
    try:
        service.anonymize_to_bundles(session)
        sent = service.extract_bundle_text(session).core_text
        for email in private:
            assert email not in sent
            assert email in profile.mappings["emails"]
        for email in retained:
            assert email in sent
    finally:
        profile.cleanup()


def test_2620_real_spacy_workflow_leak_and_roundtrip(tmp_path, offline_real_ner):
    folder = tmp_path / "data_roh" / "Muster, Max"
    folder.mkdir(parents=True)
    (folder / "Protokoll_1.txt").write_text(
        "Max Muster kam. Frau Beispiel begrüßte ihn. Eltern: Erika Muster und Hans Muster. "
        "Telefon: 07623 / 555123. E-Mail: erika.muster@example.org. Datum: 2026-10-25.\n", encoding="utf-8")
    (folder / "Protokoll_2.txt").write_text("Beispiel sagte später zu. Beispiele und Beispielweg sind keine Namen.\n", encoding="utf-8")
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(session, client_name="Max Muster", geburtsdatum="15.03.2016",
        parent_names=["Erika Muster", "Hans Muster"], scan_folder=tmp_path / "data_roh")
    try:
        service.anonymize_to_bundles(session)
        bundle = service.extract_bundle_text(session)
        sent = bundle.core_text + (bundle.stufe2_text or "")
        for clear in ("Max", "Muster", "Erika", "Hans", "Beispiel", "07623 / 555123", "erika.muster@example.org"):
            assert not re.search(r"(?<!\w)" + re.escape(clear) + r"(?!\w)", sent), clear
        assert "2026-10-25" in sent and "Beispielweg" in sent and "Beispiele" in sent
        mappings = profile.get_all_mappings()
        expected = {"name": "Max Muster", "parent": "Erika Muster", "title": "Frau Beispiel", "surname": "Beispiel",
                    "phone": "07623 / 555123", "email": "erika.muster@example.org"}
        # A local synthetic echo stands in for a model response; real spaCy above is untouched.
        model_response = {key: mappings[value] for key, value in expected.items()}
        restored = service._deanonymize_json(model_response, profile)
        assert restored == expected
        assert not re.search(r"Person\d{3}|BEGRIFF_", repr(restored))
    finally:
        profile.cleanup()


@pytest.mark.parametrize("term,email", [("Nachtigall", "Nachtigall@familie.invalid"),
                                      ("familie.invalid", "kontakt@familie.invalid"),
                                      ("familie", "kontakt@familie.invalid")])
def test_2620_manual_name_term_masks_whole_email_and_roundtrips(tmp_path, no_spacy, term, email):
    folder = tmp_path / "data_roh" / "Muster, Max"
    folder.mkdir(parents=True)
    (folder / "Protokoll.txt").write_text("Kontakt: " + email, encoding="utf-8")
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(session, client_name="Max Muster", geburtsdatum="15.03.2016",
        additional_terms=[term], scan_folder=tmp_path / "data_roh")
    try:
        service.anonymize_to_bundles(session)
        sent = service.extract_bundle_text(session).core_text
        assert email not in sent and "Nachtigall" not in sent
        mapped = profile.mappings["emails"][email]
        assert service._deanonymize_json({"email": mapped}, profile) == {"email": email}
    finally:
        profile.cleanup()


@pytest.mark.parametrize("client,parents,email", [
    ("Bo Li", [], "Bo.Li@example.org"),
    ("Bo Li", [], "BoLi@example.org"),
    ("Max Muster", ["Nora Li"], "li@example.org"),
    ("Anna Essen", [], "essen@example.org"),
    ("Max Muster", [], "kontakt@Muster.example"),
])
def test_2620_review_trusted_profile_email_roundtrip(tmp_path, offline_real_ner, client, parents, email):
    folder = tmp_path / "data_roh" / "Synthetic"
    folder.mkdir(parents=True)
    retained = ("kontakt@firma.example", "bolivia@firma.example", "essential@firma.example")
    (folder / "Protokoll.txt").write_text("Kontakt: " + "; ".join((email, *retained)), encoding="utf-8")
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(session, client_name=client, parent_names=parents,
        geburtsdatum="15.03.2016", scan_folder=tmp_path / "data_roh")
    try:
        service.anonymize_to_bundles(session)
        sent = service.extract_bundle_text(session).core_text
        assert email not in sent and all(address in sent for address in retained)
        fake = profile.mappings["emails"][email]
        assert service._deanonymize_json({"email": fake}, profile) == {"email": email}
    finally:
        profile.cleanup()


@pytest.mark.parametrize("allowed", ["Max.Mustermann@amt.example", "amt.example"])
@pytest.mark.parametrize("suffix", [".txt", ".docx"])
def test_2620_review_direct_profile_whole_email_and_roundtrip(tmp_path, no_spacy, allowed, suffix):
    anon = an.DocumentAnonymizer()
    retained = "Max.Mustermann@amt.example"
    profile = anon.create_profile(real_name="Max Mustermann", geburtsdatum="15.03.2016",
        weitere_daten={"secret": "Nachtigall", "email": retained}, whitelist=[allowed])
    private = ("Max.Mustermann@example.org", "Nachtigall@familie.invalid", "kontakt@Mustermann.example")
    original = "Max Mustermann; " + "; ".join((*private, retained, "kontakt@firma.example"))
    def write(path):
        if suffix == ".docx":
            assert an.DOCX_AVAILABLE
            doc = an.Document()
            doc.add_paragraph(original)
            doc.save(path)
        else:
            path.write_text(original, encoding="utf-8")

    def read(path):
        if suffix == ".docx":
            return "\n".join(p.text for p in an.Document(path).paragraphs)
        return path.read_text(encoding="utf-8")

    path = tmp_path / ("direct" + suffix)
    write(path)
    ok, _ = anon.anonymize_file(str(path), profile)
    assert ok
    masked = read(path)
    for email in private:
        assert email not in masked
        assert email in profile.mappings["emails"]
        assert profile.mappings["emails"][email] in masked
    assert retained in masked and "kontakt@firma.example" in masked
    mappings = dict(profile.mappings["emails"])
    repeated = tmp_path / ("repeat" + suffix)
    write(repeated)
    assert anon.anonymize_file(str(repeated), profile)[0]
    assert read(repeated) == masked
    assert profile.mappings["emails"] == mappings
    assert an.DocumentDeanonymizer().deanonymize_file(str(path), profile)[0]
    assert read(path) == original


@pytest.mark.parametrize("allowed", ["Bo.Li@example.org", "example.org"])
def test_2620_review_trusted_short_name_whitelist(tmp_path, offline_real_ner, allowed):
    folder = tmp_path / "data_roh" / "Synthetic"
    folder.mkdir(parents=True)
    email = "Bo.Li@example.org"
    (folder / "Protokoll.txt").write_text("Kontakt: " + email, encoding="utf-8")
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(session, client_name="Bo Li", geburtsdatum="15.03.2016",
        whitelist=[allowed], scan_folder=tmp_path / "data_roh")
    try:
        service.anonymize_to_bundles(session)
        assert email in service.extract_bundle_text(session).core_text
        assert email not in profile.mappings["emails"]
    finally:
        profile.cleanup()


def test_2620_review_temp_profile_whitelist_default_and_conversion(tmp_path, no_spacy):
    from hub._services.document.report_workflow_service import TempAnonymProfile

    legacy = TempAnonymProfile("Tarnname", "01.01.2016", {})
    assert legacy.whitelist == [] and legacy.to_anonym_profile().whitelist == []
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(session, client_name="Bo Li", geburtsdatum="15.03.2016",
        whitelist=["example.org"])
    try:
        assert isinstance(profile.whitelist, list)
        assert profile.whitelist == sorted({*DEFAULT_WHITELIST, "example.org"})
        assert profile.to_anonym_profile().whitelist == profile.whitelist
    finally:
        profile.cleanup()


@pytest.mark.parametrize("allowed_domain", ["muster.org", "gmail.com"])
def test_2620_review_reverse_uses_mapping_namespace_only(tmp_path, no_spacy, monkeypatch, allowed_domain):
    # Only the synthetic fake-address generator is deterministic; no NER mock
    # is substituted for the separate real-spaCy workflow tests.
    fake = "maskiert@" + allowed_domain
    monkeypatch.setattr(an, "_generate_fake_email", lambda original=None: fake)
    anon = an.DocumentAnonymizer()
    profile = anon.create_profile(real_name="Max Mustermann", geburtsdatum="15.03.2016",
        weitere_daten={"secret": "Nachtigall"}, whitelist=[allowed_domain])
    private = "Nachtigall@familie.invalid"
    retained = "kontakt@" + allowed_domain
    original = private + "; " + retained
    path = tmp_path / "reverse.txt"
    path.write_text(original, encoding="utf-8")
    assert anon.anonymize_file(str(path), profile)[0]
    assert path.read_text(encoding="utf-8") == fake + "; " + retained
    assert profile.mappings["emails"] == {private: fake}
    assert an.DocumentDeanonymizer().deanonymize_file(str(path), profile)[0]
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("mode", ["direct", "workflow"])
@pytest.mark.parametrize("client,private,family,tld", [
    ("Marie de Vries", "marie.de.vries@example.org", "kontakt@familie-de-vries.example", "de"),
    ("Bo Li", "bo.li@example.org", "kontakt@familie-li.example", "li"),
    ("Ada Com", "ada.com@example.org", "kontakt@familie-com.example", "com"),
])
def test_2620_tld_is_not_profile_identity(tmp_path, offline_real_ner, mode, client, private, family, tld):
    retained = ("info@jugendamt." + tld, "kontakt@firma." + tld)
    original = "Kontakt: " + "; ".join((private, family, *retained))
    if mode == "direct":
        anon = an.DocumentAnonymizer()
        profile = anon.create_profile(real_name=client, geburtsdatum="15.03.2016")
        path = tmp_path / "direct.txt"
        path.write_text(original, encoding="utf-8")
        assert anon.anonymize_file(str(path), profile)[0]
        sent = path.read_text(encoding="utf-8")
    else:
        folder = tmp_path / "data_roh" / "Synthetic"
        folder.mkdir(parents=True)
        (folder / "Protokoll.txt").write_text(original, encoding="utf-8")
        service = ReportWorkflowService(base_path=tmp_path)
        session = service.start_session()
        profile = service.create_temp_profile(session, client_name=client, geburtsdatum="15.03.2016",
            scan_folder=tmp_path / "data_roh")
        service.anonymize_to_bundles(session)
        sent = service.extract_bundle_text(session).core_text
    try:
        assert all(email in sent for email in retained)
        assert all(email not in sent for email in (private, family))
        assert set(profile.mappings["emails"]) == {private, family}
        if mode == "direct":
            assert an.DocumentDeanonymizer().deanonymize_file(str(path), profile)[0]
            assert path.read_text(encoding="utf-8") == original
        else:
            expected = {"private": private, "family": family}
            response = {key: profile.mappings["emails"][value] for key, value in expected.items()}
            assert service._deanonymize_json(response, profile) == expected
    finally:
        if mode == "workflow":
            profile.cleanup()


@pytest.mark.parametrize("case", ["percent_only", "percent_then_address", "long_local"])
def test_2620_email_pattern_repetition_finishes_with_whole_matches(case):
    if case == "long_local":
        text = "a" * 100_000 + "@example.org"
        expected = [[0, len(text)]]
    else:
        text = "%" * 100_000
        expected = []
        if case == "percent_then_address":
            text += " max.muster@example.org"
            expected = [[100_001, len(text)]]
    # Execute only the actual pattern, inheriting the suite's child safety guard.
    # A timeout kills the pathological search without hanging the test worker.
    script = (
        "import json,re,sys\n"
        "spec=json.load(sys.stdin)\n"
        "pattern=re.compile(spec['pattern'],spec['flags'])\n"
        "print(json.dumps([list(m.span('email')) for m in pattern.finditer(spec['text'])]))\n"
    )
    result = subprocess.run([sys.executable, "-c", script],
        input=json.dumps({"pattern": an.EMAIL_PATTERN.pattern, "flags": an.EMAIL_PATTERN.flags, "text": text}),
        capture_output=True, text=True, check=True, timeout=5)
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("text,expected", [
    ("a@b.de", ["a@b.de"]),
    ("<a@b.de>;b@c.org", ["a@b.de", "b@c.org"]),
    ("a@b.de\nb@c.org", ["a@b.de", "b@c.org"]),
    ("(a@b.de)(b@c.org)", ["a@b.de", "b@c.org"]),
    ("word+tag@example.org A.B@Example.COM", ["word+tag@example.org", "A.B@Example.COM"]),
    ("İ@i.org ı@İ.org ſ@k.org K@i.org", ["İ@i.org", "ı@İ.org", "ſ@k.org", "K@i.org"]),
    ("%%% @not.an.address a@@b.de", []),
    ("a@b.de@c@d.org", ["a@b.de", "c@d.org"]),
    ("a@b.de,b@c.org;c@d.net", ["a@b.de", "b@c.org", "c@d.net"]),
])
def test_2620_named_email_capture_values_spans_and_findall(text, expected):
    assert an.EMAIL_PATTERN.groups == 1
    matches = list(an.EMAIL_PATTERN.finditer(text))
    assert [match.group("email") for match in matches] == expected
    assert an.EMAIL_PATTERN.findall(text) == expected
    spans = []
    cursor = 0
    for email in expected:
        start = text.index(email, cursor)
        cursor = start + len(email)
        spans.append((start, cursor))
    assert [match.span("email") for match in matches] == spans


def test_2620_named_email_capture_keeps_document_delimiters_and_roundtrip(tmp_path):
    anon = an.DocumentAnonymizer()
    retained = "Max.Mustermann@amt.example"
    profile = anon.create_profile(real_name="Max Mustermann", geburtsdatum="15.03.2016",
        weitere_daten={"secret": "Nachtigall"}, whitelist=[retained])
    private = ("Max.Mustermann@example.org", "Nachtigall@familie.invalid")
    original = f"Max Mustermann <{private[0]}>; {private[1]}\nKeep: {retained}."
    path = tmp_path / "delimiters.txt"
    path.write_text(original, encoding="utf-8")
    assert anon.anonymize_file(str(path), profile)[0]
    masked = path.read_text(encoding="utf-8")
    assert masked == (f"{profile.tarnname} <{profile.mappings['emails'][private[0]]}>; "
        f"{profile.mappings['emails'][private[1]]}\nKeep: {retained}.")
    assert set(profile.mappings["emails"]) == set(private)
    assert an.DocumentDeanonymizer().deanonymize_file(str(path), profile)[0]
    assert path.read_text(encoding="utf-8") == original
