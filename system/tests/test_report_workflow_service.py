# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Privacy tests for ReportWorkflowService."""

import sys
import types
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document.report_workflow_service import ReportWorkflowService
from hub._services.document import anonymizer_service
from hub._services.document.anonymizer_service import AnonymProfile, DocumentAnonymizer


def test_generate_prompt_contains_privacy_guardrails(tmp_path):
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    session.profile = types.SimpleNamespace(tarnname="Tarn Person")
    session.bundle = types.SimpleNamespace(core_text="CORE", stufe2_text="STUFE2")

    prompt = service.generate_prompt(session, include_wissensdatenbank=False)

    assert "SYSTEM-GRENZEN / DATENSCHUTZ-GATE" in prompt
    assert "Keine Dateisystem-Pruefungen" in prompt
    assert "KEINE Pfade, Dateinamen" in prompt


def test_sanitize_llm_response_removes_path_leaks(tmp_path):
    service = ReportWorkflowService(base_path=tmp_path)
    response = """
Ich pruefe kurz den Ordner.
Pfad: C:\\Users\\User\\OneDrive\\secret\\Max Mustermann
{
  "stammdaten": {
    "name": "Tarn Person"
  }
}
Gespeichert: /tmp/output_berichte/Foerderbericht_Max.docx
""".strip()

    cleaned = service.sanitize_llm_response(response)

    assert "Pfad:" not in cleaned
    assert "Gespeichert:" not in cleaned
    assert "Max Mustermann" not in cleaned
    assert '"name": "Tarn Person"' in cleaned


# ─────────────────────────────────────────────────────────────
# Regressionstests: mehrteilige Namen muessen VOLLSTAENDIG anonymisiert
# werden (nicht nur erstes/letztes Wort eines flachen Namens-Strings).
# Hintergrund: Ein realer Foerderbericht-Lauf zeigte, dass bei einem
# Klienten mit mehrteiligem Vor- ("Amara Wanjiru") und Nachnamen
# ("Osei Boateng") mittlere Namensteile im "anonymisierten" Prompt
# im Klartext stehen blieben. Alle Namen hier sind synthetisch.
# ─────────────────────────────────────────────────────────────

def test_create_temp_profile_maps_multiword_names_via_hints(tmp_path):
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Amara Wanjiru Osei Boateng",
        geburtsdatum="02.03.2014",
        vorname_hint="Amara Wanjiru",
        nachname_hint="Osei Boateng",
    )
    mapping = profile.get_all_mappings()
    for word in ["Amara", "Wanjiru", "Osei", "Boateng"]:
        assert word in mapping, f"'{word}' wurde nicht gemappt (mehrteiliger Name)"

    # Simuliert eine Dokument-Ersetzung wie in _anonymize_text/_anonymize_docx:
    # laengste Treffer zuerst ersetzen, damit keine Teilersetzung Reste hinterlaesst.
    text = (
        "Name Klient:in: Osei Boateng, Amara Wanjiru\n"
        "Amara Wanjiru Osei Boateng war anwesend.\n"
        "Amara Osei Boateng hat mitgespielt."
    )
    for old, new in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(old, new)

    for leaked in ["Osei", "Boateng", "Wanjiru", "Amara"]:
        assert leaked not in text, f"'{leaked}' ist trotz Anonymisierung noch im Text"


def test_create_temp_profile_handles_comma_format_multiword_without_hints(tmp_path):
    """Fallback-Pfad ohne explizite Hints: 'Nachname, Vorname' muss die
    Vorname/Nachname-Grenze weiterhin korrekt erkennen und beide Teile
    vollstaendig (Wort fuer Wort) mappen."""
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Osei Boateng, Amara Wanjiru",
        geburtsdatum="02.03.2014",
    )
    mapping = profile.get_all_mappings()
    for word in ["Amara", "Wanjiru", "Osei", "Boateng"]:
        assert word in mapping, f"'{word}' wurde nicht gemappt (Komma-Format, kein Hint)"


def test_create_temp_profile_maps_multiword_parent_names(tmp_path):
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="01.01.2015",
        parent_names=["Katarzyna Nowak Zielinska", "Dimitrios Osei Boateng"],
    )
    mapping = profile.get_all_mappings()
    for word in ["Katarzyna", "Nowak", "Zielinska", "Dimitrios", "Osei", "Boateng"]:
        assert word in mapping, f"'{word}' (Elternname) wurde nicht gemappt"


def test_create_temp_profile_does_not_print_plaintext_pii(tmp_path, capsys):
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="01.01.2015",
        parent_names=["Maria Musterfrau"],
        client_address="Geheimstr. 5, 12345 Testort",
    )
    captured = capsys.readouterr()
    assert "Maria Musterfrau" not in captured.out, "Klartext-Elternname im Log"
    assert "Geheimstr. 5" not in captured.out, "Klartext-Adresse im Log"


def test_create_temp_profile_detects_table_row_third_party_names(tmp_path):
    """Drittpersonen (z.B. andere Kinder in Gruppenprotokollen) werden von
    keiner explizit uebergebenen Namensliste erfasst -- die automatische
    Tabellenzeilen-Erkennung muss sie stattdessen finden."""
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "gruppenprotokoll.txt").write_text(
        "Teilnehmer | Beobachtungen, Bemerkungen\n"
        "Timon Ackerknecht | Teilt seine technische Expertise, dabei nicht ueberheblich\n"
        "Joris Vandenberghe | Gute Absprache mit anderen Teilnehmern\n",
        encoding="utf-8",
    )
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="01.01.2015",
        scan_folder=scan_dir,
    )
    mapping = profile.get_all_mappings()
    # Drittpersonen werden NUR als komplette Phrase gemappt (nicht wortweise) --
    # ein zufaellig gewoehnliches deutsches Wort als Nachname (z.B. "Herr")
    # duerfte sonst ueberall im Dokument ersetzt werden.
    for full_name in ["Timon Ackerknecht", "Joris Vandenberghe"]:
        assert full_name in mapping, f"Drittperson '{full_name}' wurde nicht erkannt/anonymisiert"
    assert "Teilnehmer" not in mapping, "Tabellen-Header wurde faelschlich als Name erkannt"


def test_create_temp_profile_detects_prose_names_via_ner(tmp_path):
    """Die enge Tabellenzeilen-Regel faengt nur 'Name | Text'-Zeilen. Echte
    Personennamen in normalem Fliesstext (nicht nur deutsche, siehe engl.
    Name hier) muessen zusaetzlich per spaCy-NER erkannt werden -- das ist
    der Hauptmechanismus fuer unbekannte/fremdsprachige Drittpersonen-Namen."""
    pytest.importorskip("spacy")
    scan_dir = tmp_path / "scan_ner"
    scan_dir.mkdir()
    (scan_dir / "protokoll.txt").write_text(
        "Heute war Priyanka Ramachandran zu Besuch und hat gut mitgemacht. "
        "Auch John Fitzgerald Whitmore war anwesend.",
        encoding="utf-8",
    )
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="01.01.2015",
        scan_folder=scan_dir,
    )
    mapping = profile.get_all_mappings()
    for full_name in ["Priyanka Ramachandran", "John Fitzgerald Whitmore"]:
        assert full_name in mapping, f"'{full_name}' (Fliesstext-Name) wurde nicht via NER erkannt"


def test_create_temp_profile_ignores_extended_reference_material(tmp_path):
    """Regressionstest: Ein realer Lauf scannte versehentlich ein generisches
    Referenzmaterial-Verzeichnis (Foerderplanung/Material/..., EXTENDED-
    Kategorie) mit -- NER erkannte darin hunderte zitierte (klienten-
    fremde) Namen als vermeintliche Drittpersonen. Nur CORE/STUFE2-Dokumente
    (dieselbe Auswahl wie im LLM-Prompt-Bundle) duerfen gescannt werden."""
    pytest.importorskip("spacy")
    client_dir = tmp_path / "data_roh" / "Testklient, Max"
    material_dir = client_dir / "Foerderplanung" / "Material"
    material_dir.mkdir(parents=True)

    # CORE-Dokument (Root-Datei) -- enthaelt eine echte Drittperson
    (client_dir / "Protokoll.txt").write_text(
        "Heute war Fatima El-Sayed zu Besuch und hat gut mitgemacht.",
        encoding="utf-8",
    )
    # EXTENDED-Referenzmaterial (generische Spielesammlung) mit einer
    # zitierten, klientenfremden Person -- darf NICHT gescannt werden.
    # Bewusst NUR 1 Name (unterhalb der generischen Sicherheits-Obergrenze),
    # damit dieser Test spezifisch die Ordner-/Kategorie-Filterung prueft
    # und nicht zufaellig nur durch die separate Mengen-Obergrenze "gerettet" wird.
    (material_dir / "Spielesammlung.txt").write_text(
        "Diese Sammlung zitiert Autorin Nachnamesiebzig als Quelle.",
        encoding="utf-8",
    )

    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="01.01.2015",
        scan_folder=client_dir.parent,
    )
    mapping = profile.get_all_mappings()
    assert "Fatima El-Sayed" in mapping, "Echte Drittperson im CORE-Dokument nicht erkannt"
    assert "Nachnamesiebzig" not in mapping, "Generisches Referenzmaterial wurde faelschlich gescannt"


def test_anonymize_doc_replaces_content_and_removes_original(tmp_path, monkeypatch):
    """Regressionstest: .doc-Dateien (altes Word-Binaerformat) wurden bisher
    nur roh nach data_ano/ kopiert und NIE tatsaechlich anonymisiert (python-
    docx kann dieses Format nicht schreiben) -- ein Aktendeckblatt.doc landete
    dadurch zu 100% im Klartext im "anonymisierten" Ordner. Die Datei muss
    jetzt als anonymisierte .txt-Datei ersetzt werden, das Original geloescht."""
    doc_path = tmp_path / "Aktendeckblatt_Testklient.doc"
    doc_path.write_bytes(b"placeholder-binaerinhalt")  # Inhalt irrelevant, wird gemockt

    monkeypatch.setattr(
        anonymizer_service,
        "_extract_legacy_doc_text",
        lambda filepath: "Name: Nguyen Beispiel\nE-Mail: nguyen.beispiel@yahoo.com",
    )

    profile = AnonymProfile(
        client_id="TEST",
        tarnname="Tarn Person",
        fake_geburtsdatum="01.01.2015",
        mappings={"names": {"Nguyen Beispiel": "Tarn Person"}, "emails": {"nguyen.beispiel@yahoo.com": "tarn@beispiel.de"}},
    )

    anon = DocumentAnonymizer()
    success, count = anon.anonymize_file(str(doc_path), profile)

    assert success is True
    assert count > 0
    assert not doc_path.exists(), "Original .doc wurde nicht geloescht"
    txt_path = doc_path.with_suffix(".txt")
    assert txt_path.exists(), "Anonymisierte .txt-Datei wurde nicht erstellt"
    content = txt_path.read_text(encoding="utf-8")
    assert "Nguyen Beispiel" not in content
    assert "nguyen.beispiel@yahoo.com" not in content
    assert "Tarn Person" in content


def test_scan_files_for_sensitive_data_includes_doc_files(tmp_path, monkeypatch):
    """Regressionstest: .doc-Extraktion wurde in extract_text_from_file()
    ergaenzt, aber die separate 'supported'-Dateiendungsliste in
    scan_files_for_sensitive_data() wurde dabei vergessen -- .doc-Dateien
    (z.B. Aktendeckblatt) wurden dadurch beim Sensible-Daten-Scan komplett
    uebersprungen (E-Mail des Vaters blieb im echten Klientenfall dadurch
    unentdeckt, obwohl die Extraktion selbst schon funktionierte)."""
    doc_path = tmp_path / "Aktendeckblatt.doc"
    doc_path.write_bytes(b"placeholder-binaerinhalt")

    monkeypatch.setattr(
        anonymizer_service,
        "_extract_legacy_doc_text",
        lambda filepath: "Kontakt: vater.beispiel@yahoo.com",
    )

    anon = DocumentAnonymizer()
    found = anon.scan_files_for_sensitive_data([doc_path])
    assert "vater.beispiel@yahoo.com" in found["emails"], ".doc-Datei wurde beim Scan uebersprungen"


def test_many_third_party_mappings_do_not_corrupt_ordinary_text(tmp_path):
    """Regressionstest fuer einen realen Vorfall: Mit vielen (real: 178)
    NER-erkannten Drittpersonen-Namen, die auf den kleinen Pool "echt
    klingender" Tarnnamen gemappt wurden (~34 Eintraege, mehrere davon
    normale deutsche Woerter wie "Vogel"/"Bauer"/"Fischer"/"Richter"),
    wurde ein kompletter Foerderbericht bis zur Unlesbarkeit korrumpiert.
    Mit eindeutigen "PersonNNN"-Platzhaltern (statt Namen aus diesem Pool)
    darf gewoehnlicher deutscher Fliesstext nicht mehr angetastet werden."""
    mappings = {"names": {}}
    for i in range(80):
        mappings["names"][f"Drittperson{i} Nachname{i}"] = f"Person{i:03d}"

    profile = AnonymProfile(
        client_id="TEST",
        tarnname="Tarn Person",
        fake_geburtsdatum="01.01.2015",
        mappings=mappings,
    )

    # Gewoehnlicher deutscher Text ohne jeden Bezug zu den Drittpersonen-Namen
    original_text = (
        "Der Vogel sang schoen im Garten. Der Bauer arbeitete auf dem Feld. "
        "Der Fischer warf sein Netz aus. Herr Richter kam spaeter dazu."
    )
    doc_path = tmp_path / "protokoll.txt"
    doc_path.write_text(original_text, encoding="utf-8")

    anon = DocumentAnonymizer()
    success, _ = anon.anonymize_file(str(doc_path), profile)
    result_text = doc_path.read_text(encoding="utf-8")

    assert success is True
    assert result_text == original_text, (
        "Gewoehnlicher Text wurde durch Drittpersonen-Mappings veraendert/korrumpiert"
    )


def test_ner_ignores_generic_role_nouns_like_klient(tmp_path):
    """Regressionstest: Das englische NER-Modell markierte auf deutschem
    Fliesstext faelschlich das generische Wort 'Klienten' (keine Person,
    sondern die Bezeichnung fuer den Klienten selbst) als PERSON -- die
    Ersetzung erzeugte grammatisch kaputte Fragmente wie 'Person168en',
    da die deutsche Deklinationsendung an der Ersetzung kleben blieb.
    Kein Datenschutzleck, aber ein Qualitaets-/Lesbarkeitsproblem."""
    pytest.importorskip("spacy")
    scan_dir = tmp_path / "scan_klient"
    scan_dir.mkdir()
    (scan_dir / "protokoll.txt").write_text(
        "Wahrnehmungsbesonderheiten des Klienten\nKommunikation des Klienten",
        encoding="utf-8",
    )
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="01.01.2015",
        scan_folder=scan_dir,
    )
    mapping = profile.get_all_mappings()
    assert not any("klient" in k.lower() for k in mapping), (
        "'Klient(en)' wurde faelschlich als Personenname erkannt/gemappt"
    )


def test_ner_ignores_prefix_of_compound_german_word(tmp_path):
    """Regressionstest: NER erkannte 'Wahrnehmung' als vermeintlichen
    Personennamen-Anfang von 'Wahrnehmungsbesonderheiten' -- die Ersetzung
    hinterliess ein kaputtes Fragment ('Person026sbesonderheiten'). Folgt
    einer erkannten Entitaet direkt (ohne Trennzeichen) ein Kleinbuchstabe,
    ist sie nur der Anfang eines zusammengesetzten Wortes und darf nicht
    ersetzt werden."""
    pytest.importorskip("spacy")
    scan_dir = tmp_path / "scan_compound"
    scan_dir.mkdir()
    (scan_dir / "protokoll.txt").write_text(
        "Wahrnehmungsbesonderheiten des Kindes wurden dokumentiert.",
        encoding="utf-8",
    )
    service = ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    profile = service.create_temp_profile(
        session,
        client_name="Max Mustermann",
        geburtsdatum="01.01.2015",
        scan_folder=scan_dir,
    )
    mapping = profile.get_all_mappings()
    assert not any("wahrnehmung" in k.lower() for k in mapping), (
        "'Wahrnehmung' (Wortanfang) wurde faelschlich als Personenname gemappt"
    )


def test_anonymize_text_replaces_only_at_word_boundaries(tmp_path):
    """Regressionstest fuer den konkreten Korruptionsfall: Ein Mapping-Key
    ("Wahrnehmung") kann an EINER Stelle im Dokument als eigenstaendiges Wort
    auftauchen (legitime Ersetzung) und an ANDERER Stelle Praefix eines
    laengeren Kompositums sein ("Wahrnehmungsbesonderheiten"). Blinde
    Teilstring-Ersetzung zerstoert Letzteres ("Person026sbesonderheiten").
    Die Ersetzung darf nur an Wortgrenzen greifen."""
    profile = AnonymProfile(
        client_id="TEST",
        tarnname="Tarn Person",
        fake_geburtsdatum="01.01.2015",
        mappings={"names": {"Wahrnehmung": "Person026"}},
    )
    doc_path = tmp_path / "protokoll.txt"
    doc_path.write_text(
        "Wahrnehmungsbesonderheiten des Klienten. Die Wahrnehmung war auffaellig.",
        encoding="utf-8",
    )

    anon = DocumentAnonymizer()
    success, count = anon.anonymize_file(str(doc_path), profile)
    result_text = doc_path.read_text(encoding="utf-8")

    assert success is True
    assert count == 1
    assert "Wahrnehmungsbesonderheiten" in result_text, (
        "Zusammengesetztes Wort wurde faelschlich fragmentiert"
    )
    assert "Die Person026 war auffaellig" in result_text, (
        "Eigenstaendiges Wort wurde nicht korrekt ersetzt"
    )
