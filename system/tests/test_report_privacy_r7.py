# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Befunde R7 der Zweitpruefung zu bach#683 (T-20261107-347299705): Ersetzung und Datenschutz-Sperre.

F1 Geburtsdatum fail-closed und in jeder Eingabeform, F2 Telefon-/Konto-/Kennnummern, F3 Namen in
Ableitungen und Komposita, F4 Strassenname ohne gleiche Hausnummer, F5 Import nach dem Profil,
F6 Datumsrestformen. Nur erfundene Namen und Daten, kein Netz, kein Modellaufruf.
"""

import json
import re
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

CLIENT, DOB = "Annika Berghofer", "03.07.2014"
PARENTS = ["Mara Berghofer", "Wolfgang Hauser"]
ADDRESS = "Lindenweg 12, 79102 Freiburg"
TERMS = ["Kirchzarten"]


def _fold(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return text.replace("ae", "a").replace("oe", "o").replace("ue", "u").replace("_", " ")


class _Bundle:
    def __init__(self, text):
        self.core_text, self.stufe2_text = text, ""


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""))
    monkeypatch.setattr(anonymizer_service, "detect_person_names_ner", lambda text, whitelist=None: [])
    return rws.ReportWorkflowService(base_path=tmp_path)


def _profile(service, dob=DOB, **kwargs):
    """Profil ohne Akten-Scan, als gescannt markiert: prueft Ersetzung und Sperre isoliert."""
    session = service.start_session()
    kwargs = {"parent_names": PARENTS, "client_address": ADDRESS, "additional_terms": TERMS, **kwargs}
    profile = service.create_temp_profile(session, CLIENT, dob, **kwargs)
    profile.document_scanned = True
    return session, profile


def _replace(profile, text):
    return _apply_replacements(text, DocumentAnonymizer._sorted_replacements(profile.to_anonym_profile()))[0]


def _prompt(service, session, text):
    session.bundle = _Bundle(text)
    return service.generate_prompt(session, include_wissensdatenbank=False)


def _assert_blocked(service, session, text):
    with pytest.raises(rws.PromptPrivacyError) as exc:
        _prompt(service, session, text)
    assert exc.value.code == "identity_terms_in_prompt"


def _akte(service, text, name="Verlaufsprotokoll_2025.txt"):
    folder = service.base_path / "data_roh" / "Berghofer, Annika"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder


# --- F1: Geburtsdatum ----------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["", "   ", "unbekannt", "31.02.2014", "14", None])
def test_cloud_profile_refuses_a_birth_date_it_cannot_read(service, value):
    session = service.start_session()

    with pytest.raises(rws.PromptPrivacyError) as exc:
        service.create_cloud_profile(session, CLIENT, value)

    assert exc.value.code == "birth_date_invalid"
    assert session.profile is None
    assert "31.02" not in str(exc.value) and "unbekannt" not in str(exc.value)


def test_cloud_profile_needs_the_birth_date_argument(service):
    """Kein stiller Platzhalter (frueher 01.01.2010): fehlt das Datum, verweigert der Cloud-Weg."""
    with pytest.raises(rws.PromptPrivacyError) as exc:
        service.create_cloud_profile(service.start_session(), CLIENT)
    assert exc.value.code == "birth_date_invalid"


INPUT_FORMS = ["3.7.14", "03.07.14", "3.7.2014", "2014-07-03", "03/07/2014", "03-07-2014", "03. Juli 2014",
               "3. Juli 2014", "3 Jul 2014", "July 3, 2014", "Jul 3 2014", "03072014", "20140703", " 03.07.2014 "]
AKTE_DATES = ("geb. 03.07.2014, im Arztbrief 3.7.14, im Formular 2014-07-03, laut Schule 03. Juli 2014, "
              "Elternbrief 03/07/2014, englischer Befund July 3, 2014.")


@pytest.mark.parametrize("form", INPUT_FORMS)
def test_birth_date_in_any_input_form_is_pseudonymized_in_every_output_form(service, form):
    session, profile = _profile(service, dob=form)

    assert next(iter(profile.mappings["dates"])) == DOB  # Hauptform fuer den GEBURTSDATUM-Platzhalter
    assert profile.fake_geburtsdatum != DOB and anonymizer_service._parse_date(profile.fake_geburtsdatum)
    replaced = _replace(profile, AKTE_DATES)
    assert anonymizer_service.date_pattern(DOB).search(replaced) is None, replaced
    _prompt(service, session, replaced)  # keine Sperre


@pytest.mark.parametrize("form", ["3.7.14", "July 3, 2014", "2014-07-03"])
def test_gate_blocks_the_real_birth_date_when_the_profile_got_another_input_form(service, form):
    session, _ = _profile(service, dob=form)
    _assert_blocked(service, session, "Geboren am 03.07.2014.")


def test_prompt_sink_refuses_a_profile_without_readable_birth_date(service):
    """Auch Wege an create_cloud_profile vorbei (quick_report, eigene Profile) sperren in der Senke."""
    session, _ = _profile(service, dob="")

    with pytest.raises(rws.PromptPrivacyError) as exc:
        _prompt(service, session, "Fortschritte in der Feinmotorik.")
    assert exc.value.code == "birth_date_invalid"


def test_quick_report_refuses_missing_birth_date_before_copying(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "BERICHTE_BASE", tmp_path / "Berichte")
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""))
    akte = tmp_path / "akte"
    akte.mkdir()
    (akte / "Protokoll.txt").write_text(f"{CLIENT}, geb. {DOB}", encoding="utf-8")

    with pytest.raises(rws.PromptPrivacyError) as exc:
        rws.quick_report(akte, CLIENT)
    assert exc.value.code == "birth_date_invalid"
    assert not any((tmp_path / "Berichte" / "data_roh").glob("*"))


def test_pipeline_without_cover_sheet_refuses_instead_of_using_a_placeholder_date(service):
    """R7-F1a: frueher 01.01.2010 als Platzhalter, das echte Datum der Akte ging unveraendert in den Prompt."""
    _akte(service, f"Verlauf: {CLIENT}, geb. {DOB}, zeigte Fortschritte in der Feinmotorik.\n")

    res = FoerderberichtPipeline(base_path=service.base_path).prepare_prompt(client_name=CLIENT)

    assert not res.success and "Geburtsdatum" in res.error
    assert not (service.base_path / "data_bundled" / "prompt.txt").exists()


def test_pipeline_reads_the_birth_date_from_the_cover_sheet_in_other_forms(service):
    folder = _akte(service, f"Verlauf: {CLIENT}, geb. 3.7.14, zeigte Fortschritte in der Feinmotorik.\n")
    (folder / "Aktendeckblatt.txt").write_text(f"Name: {CLIENT}\nGeburtsdatum: 3. Juli 2014\n", encoding="utf-8")

    res = FoerderberichtPipeline(base_path=service.base_path).prepare_prompt(client_name=CLIENT)

    assert res.success, res.error
    prompt = (service.base_path / "data_bundled" / "prompt.txt").read_text(encoding="utf-8")
    assert anonymizer_service.date_pattern(DOB).search(prompt) is None
    assert "berghofer" not in _fold(prompt) and "feinmotorik" in _fold(prompt)


# --- F2: Telefon-, Konto- und Kennnummern ---------------------------------------------------------

CONTACT_LEAKS = {
    "+49 (0)761 1234567": "1234567",
    "(0761) 7654321": "7654321",
    "0049 (0) 761 / 555 0199": "5550199",
    "DE89370400440532013000": "370400440532013000",
    "DE89 3704 0044 0532 0130 00": "370400440532013000",
    "COBADEFFXXX": "COBADEFF",
    "12 345 678 903": "12345678903",  # Steuer-Identifikationsnummer (fiktiv)
    "A123456780": "123456780",  # Krankenversichertennummer (fiktiv)
    "65 170839 J 003": "170839",  # Rentenversicherungsnummer (fiktiv)
}


def _digits_and_letters(text: str) -> str:
    return re.sub(r"[\s()/\-]", "", text)


@pytest.mark.parametrize("leak", CONTACT_LEAKS)
def test_contact_bank_and_id_numbers_are_found_and_replaced(service, leak):
    _akte(service, f"Rueckfragen und Abrechnung: {leak} (Mutter).\nFortschritte in der Feinmotorik.\n")
    session = service.start_session()
    service.create_cloud_profile(session, CLIENT, DOB, parent_names=PARENTS, client_address=ADDRESS)

    prompt = service.generate_prompt(session, include_wissensdatenbank=False)

    assert CONTACT_LEAKS[leak] not in _digits_and_letters(prompt), leak
    assert "feinmotorik" in _fold(prompt)


@pytest.mark.parametrize("leak", CONTACT_LEAKS)
def test_gate_blocks_contact_bank_and_id_numbers_the_scan_did_not_map(service, leak):
    session, _ = _profile(service)
    _assert_blocked(service, session, f"Abrechnung ueber {leak}.")


def test_gate_lets_generated_fake_phone_numbers_pass(service):
    session, profile = _profile(service)
    profile.mappings["phones"]["0761 5550123"] = "07742/123456"
    _prompt(service, session, _replace(profile, "Rueckruf unter 0761 5550123."))  # keine Sperre


# --- F3: Namen in Ableitungen und Komposita -------------------------------------------------------

DERIVED = ["Die Berghofersche Villa.", "Die Hausersche Familie.", "Eine Freiburgerin.", "Die Kirchzartenerin.",
           "Den Berghoferschen Garten.", "BERGHOFERSCHE Akte.", "Zwei Freiburgerinnen."]


@pytest.mark.parametrize("leak", DERIVED)
def test_names_in_derivations_are_replaced(service, leak):
    session, profile = _profile(service)
    replaced = _replace(profile, leak)
    for part in ("berghofer", "hauser", "freiburg", "kirchzarten"):
        assert part not in _fold(replaced), replaced
    _prompt(service, session, replaced)  # keine Sperre


COMPOUNDS = ["Sie besucht die Annikaschule.", "Im Berghoferhaus.", "Das Hauserteam.", "Das Berghoferkind spielt."]


@pytest.mark.parametrize("leak", COMPOUNDS)
def test_gate_blocks_names_inside_compounds(service, leak):
    """Komposita ersetzt die Ersetzung bewusst nicht (sonst "Kleinkind" -> "Bauerkind" bei Familie Klein)."""
    session, profile = _profile(service)
    _assert_blocked(service, session, _replace(profile, leak))


def test_compound_in_the_term_list_is_replaced_and_passes(service):
    """Ausweg aus der Sperre: das Kompositum in die Begriffsliste."""
    session, profile = _profile(service, additional_terms=[*TERMS, "Berghoferkind"])
    replaced = _replace(profile, "Das Berghoferkind spielt.")
    assert "berghofer" not in _fold(replaced)
    _prompt(service, session, replaced)  # keine Sperre


def test_replacement_never_splits_a_compound_of_a_common_word_name(service):
    """Gegenprobe Familie Klein: "Kleinkind", "Kleinigkeit", "kleinen" bleiben Woerter (nur die Sperre greift)."""
    session = service.start_session()
    profile = service.create_temp_profile(session, "Paula Klein", DOB)
    text = "Das Kleinkind ordnet Kleinigkeiten."
    assert _replace(profile, text) == text


COUNTERCHECK = ("Fortschritte in der Feinmotorik und Wahrnehmung, Hausaufgaben, Bergwanderung, Annahme, "
                "Lindenblüte, Wolfsburg-Ausflug, Marathonlauf, Freizeit am Bergsee.")


def test_counterchecks_keep_technical_terms_and_pass_the_gate(service):
    session, profile = _profile(service)
    replaced = _replace(profile, COUNTERCHECK)
    assert replaced == COUNTERCHECK
    _prompt(service, session, replaced)  # keine Sperre


def test_compound_false_positive_can_be_released_by_the_whitelist(service):
    """Ausweg aus einem Falschtreffer der Teilwort-Pruefung ("Ernst" in "Ernstfall"): Whitelist."""
    session = service.start_session()
    profile = service.create_temp_profile(session, "Ernst Berghofer", DOB)
    profile.document_scanned = True
    _assert_blocked(service, session, "Fuer den Ernstfall gibt es einen Plan.")

    session = service.start_session()
    profile = service.create_temp_profile(session, "Ernst Berghofer", DOB, whitelist=["Ernstfall"])
    profile.document_scanned = True
    _prompt(service, session, _replace(profile, "Fuer den Ernstfall gibt es einen Plan."))  # keine Sperre


# --- F4: Strassenname ohne gleiche Hausnummer -----------------------------------------------------

@pytest.mark.parametrize("leak", ["Treffpunkt Lindenweg.", "Lindenweg Nr. 12", "Lindenweg 12a", "Lindenstr. 12",
                                  "Lindenstraße 12", "LINDENWEG 12"])
def test_street_name_is_replaced_without_the_same_house_number(service, leak):
    session, profile = _profile(service)
    replaced = _replace(profile, leak)
    assert "linden" not in _fold(replaced), replaced
    _prompt(service, session, replaced)  # keine Sperre


@pytest.mark.parametrize("leak", ["Hauptstr. 5", "Hauptstrasse 5", "Hauptstraße", "Hauptstr 7"])
def test_street_type_abbreviations_are_replaced(service, leak):
    session, profile = _profile(service, client_address="Hauptstraße 5, 79102 Freiburg")
    replaced = _replace(profile, leak)
    assert "hauptstr" not in _fold(replaced), replaced
    _prompt(service, session, replaced)  # keine Sperre


def test_gate_blocks_the_street_name_alone(service):
    session, _ = _profile(service)
    _assert_blocked(service, session, "Treffpunkt Lindenweg.")


def test_street_without_postcode_is_still_split(service):
    session, profile = _profile(service, client_address="Lindenweg 12")
    assert "linden" not in _fold(_replace(profile, "Am Lindenweg 14 gespielt."))


# --- F5: Import nach dem Profil ------------------------------------------------------------------

def test_import_after_the_profile_invalidates_scan_and_bundle(service, tmp_path):
    _akte(service, f"Verlauf: {CLIENT} zeigte Fortschritte in der Feinmotorik.\n")
    session = service.start_session()
    service.create_cloud_profile(session, CLIENT, DOB, parent_names=PARENTS, client_address=ADDRESS)
    service.generate_prompt(session, include_wissensdatenbank=False)  # vorher ok
    later = tmp_path / "spaeter"
    later.mkdir()
    (later / "Nachtrag_Protokoll.txt").write_text("Rueckruf unter 0761 5550123, Frau Ilse Kaltenbach.",
                                                  encoding="utf-8")

    service.import_from_folder(session, later)

    assert session.profile.document_scanned is False and session.bundle is None and session.anonymized is False
    with pytest.raises(rws.PromptPrivacyError) as exc:
        service.generate_prompt(session, include_wissensdatenbank=False)
    assert exc.value.code == "document_scan_missing"
    with pytest.raises(rws.PromptPrivacyError) as exc:
        service.require_cloud_session(session)
    assert exc.value.code == "document_scan_missing"


def test_new_profile_after_the_later_import_scans_the_new_file(service, tmp_path):
    _akte(service, f"Verlauf: {CLIENT} zeigte Fortschritte in der Feinmotorik.\n")
    session = service.start_session()
    service.create_cloud_profile(session, CLIENT, DOB)
    later = tmp_path / "spaeter"
    later.mkdir()
    (later / "Nachtrag_Protokoll.txt").write_text("Rueckruf unter 0761 5550123.", encoding="utf-8")
    service.import_from_folder(session, later)

    service.create_cloud_profile(session, CLIENT, DOB)
    prompt = service.generate_prompt(session, include_wissensdatenbank=False)

    assert "5550123" not in _digits_and_letters(prompt)
    service.require_cloud_session(session)  # bereit


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from gui import server

    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "report-fixture" else None)
    monkeypatch.setattr(server, "BACH_DIR", tmp_path)
    monkeypatch.setattr(server, "_report_workflow_service", rws.ReportWorkflowService(base_path=tmp_path / "Berichte"))
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""))
    monkeypatch.setattr(anonymizer_service, "detect_person_names_ner", lambda text, whitelist=None: [])
    akte = tmp_path / "akte"
    akte.mkdir()
    (akte / "Verlaufsprotokoll_2025.txt").write_text(
        f"Verlauf: {CLIENT}, geb. {DOB}, zeigte Fortschritte in der Feinmotorik.\n", encoding="utf-8")
    later = tmp_path / "spaeter"
    later.mkdir()
    (later / "Nachtrag_Protokoll.txt").write_text("Rueckruf unter 0761 5550123.", encoding="utf-8")
    return TestClient(server.app, raise_server_exceptions=False, headers={"Authorization": "Bearer report-fixture"})


def _api_session(api) -> str:
    sid = api.post("/api/report/session/start").json()["session_id"]
    assert api.post(f"/api/report/session/{sid}/import", json={"folder": "akte"}).json()["success"]
    return sid


def test_api_profile_without_birth_date_is_a_privacy_block(api):
    sid = _api_session(api)

    res = api.post(f"/api/report/session/{sid}/profile", json={"client_name": CLIENT}).json()

    assert res["success"] is False and res["privacy_block"] is True
    assert res["error_code"] == "birth_date_invalid"
    assert "berghofer" not in json.dumps(res, ensure_ascii=False).lower()


def test_api_profile_accepts_other_birth_date_forms(api):
    sid = _api_session(api)
    assert api.post(f"/api/report/session/{sid}/profile",
                    json={"client_name": CLIENT, "geburtsdatum": "3.7.14"}).json()["success"]

    res = api.post(f"/api/report/session/{sid}/prompt", json={"include_wissensdatenbank": False}).json()

    assert res["success"], res
    assert anonymizer_service.date_pattern(DOB).search(res["prompt"]) is None


def test_api_readiness_of_a_session_reflects_an_import_after_the_profile(api):
    sid = _api_session(api)
    assert api.post(f"/api/report/session/{sid}/profile",
                    json={"client_name": CLIENT, "geburtsdatum": DOB}).json()["success"]
    ready = api.get("/api/report/readiness", params={"session_id": sid}).json()
    assert ready == {"success": True, "cloud_ready": True, "error_code": None, "error": None}

    assert api.post(f"/api/report/session/{sid}/import", json={"folder": "spaeter"}).json()["success"]
    res = api.get("/api/report/readiness", params={"session_id": sid}).json()

    assert res["success"] is True and res["cloud_ready"] is False
    assert res["error_code"] == "document_scan_missing"
    blocked = api.post(f"/api/report/session/{sid}/prompt", json={"include_wissensdatenbank": False}).json()
    assert blocked["privacy_block"] is True and blocked["error_code"] == "document_scan_missing"


def test_api_readiness_without_session_stays_global(api):
    assert api.get("/api/report/readiness").json() == {
        "success": True, "cloud_ready": True, "error_code": None, "error": None}


# --- F6: Datumsrestformen ------------------------------------------------------------------------

REST_FORMS = ["030714", "03072014", "20140703", "July 3, 2014", "3.7.'14", "Jul 3, 2014", "3rd July 2014",
              "July 3rd, 2014"]


@pytest.mark.parametrize("leak", REST_FORMS)
def test_gate_blocks_the_remaining_date_forms(service, leak):
    session, _ = _profile(service)
    _assert_blocked(service, session, f"Geburt: {leak}.")


@pytest.mark.parametrize("leak", REST_FORMS)
def test_replacement_covers_the_remaining_date_forms(service, leak):
    session, profile = _profile(service)
    replaced = _replace(profile, f"Geburt: {leak}.")
    assert anonymizer_service.date_pattern(DOB).search(replaced) is None, replaced
    _prompt(service, session, replaced)  # keine Sperre


def test_month_and_year_alone_are_no_birth_date_and_pass(service):
    """Bewusst nicht gesperrt: Monat/Jahr allein ("Juli 2014") stehen in jeder Akte fuer Termine."""
    session, profile = _profile(service)
    text = "Termine im Juli 2014 und 07/2014, Schuljahr 2014/2015, Zahl 140703."
    assert _replace(profile, text) == text
    _prompt(service, session, text)  # keine Sperre
