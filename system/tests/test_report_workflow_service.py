# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Privacy tests for ReportWorkflowService."""

import sys
import types
from pathlib import Path

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document.report_workflow_service import ReportWorkflowService


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
    for word in ["Timon", "Ackerknecht", "Joris", "Vandenberghe"]:
        assert word in mapping, f"Drittperson '{word}' wurde nicht erkannt/anonymisiert"
    assert "Teilnehmer" not in mapping, "Tabellen-Header wurde faelschlich als Name erkannt"
