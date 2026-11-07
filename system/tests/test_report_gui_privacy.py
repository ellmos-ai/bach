# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""GUI-/API-Berichtsweg (/api/report/session/...) im Cloud-Modus (T-20261107-347299705).

Der Weg muss dieselbe Pseudonymisierung (Scan der importierten Akte + Namenserkennung) und
dieselbe Datenschutz-Sperre wie die Pipeline nutzen; ohne spaCy verweigert er mit Grund, und
die API liefert den Grund maschinenlesbar ohne Werte. Jeder weitere Cloud-Sendeweg im
Berichtskontext (Provider-Cloud-Port) haengt an derselben NER-Pflicht.
Nur synthetische Daten, kein Netz.
"""

import json
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui import server  # noqa: E402
from hub._services.document import anonymizer_service  # noqa: E402
from hub._services.document import report_workflow_service as rws  # noqa: E402

THIRD_PARTY = "Mirko Tannhäuser"  # nur ueber die Namenserkennung auffindbar
PHONE = "0000 1234 567"  # eindeutig fiktiv, nur ueber den Akten-Scan auffindbar
FORBIDDEN = [
    "jonas", "leonhardt", "sabine", "markus", "mirko", "tannhäuser", "gartenstraße", "79102",
    "freiburg", PHONE, "14.05.2017", "14.5.2017", "14. mai 2017", "2017-05-14",
]


def _akte(root: Path) -> Path:
    akte = root / "akte"
    akte.mkdir(parents=True)
    (akte / "Aktendeckblatt.txt").write_text(
        "Name: Jonas Leonhardt\nGeboren am 14.05.2017\nAdresse: Gartenstraße 18, 79102 Freiburg\n"
        "Eltern: Sabine Leonhardt, Markus Leonhardt\n", encoding="utf-8")
    (akte / "Verlaufsprotokoll_2025.txt").write_text(
        "Jonas Leonhardt (geb. 14.5.2017, laut Arztbrief 14. Mai 2017, im Formular 2017-05-14) "
        "zeigte Fortschritte in der Feinmotorik. Rueckruf der Mutter unter " + PHONE + ". "
        "Mitschueler " + THIRD_PARTY + " half beim Aufraeumen.\n", encoding="utf-8")
    return akte


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "report-fixture" else None)
    monkeypatch.setattr(server, "BACH_DIR", tmp_path)
    monkeypatch.setattr(server, "_report_workflow_service", rws.ReportWorkflowService(base_path=tmp_path / "Berichte"))
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    # Namenserkennung ohne Modelle nachgestellt: findet genau die Drittperson, wenn der Text gescannt wird.
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""))
    monkeypatch.setattr(anonymizer_service, "detect_person_names_ner",
                        lambda text, whitelist=None: [THIRD_PARTY] if THIRD_PARTY in text else [])
    client = TestClient(server.app, raise_server_exceptions=False,
                        headers={"Authorization": "Bearer report-fixture"})
    _akte(tmp_path)
    return client


def _session(client) -> str:
    started = client.post("/api/report/session/start").json()
    assert started["success"], started
    sid = started["session_id"]
    imported = client.post(f"/api/report/session/{sid}/import", json={"folder": "akte"}).json()
    assert imported["success"] and imported["imported_count"] == 2, imported
    return sid


PROFILE = {
    "client_name": "Jonas Leonhardt", "geburtsdatum": "14.05.2017",
    "parent_names": ["Sabine Leonhardt", "Markus Leonhardt"],
    "client_address": "Gartenstraße 18, 79102 Freiburg", "additional_terms": ["Gartenstraße"],
}


def test_api_cloud_prompt_contains_no_case_data(api):
    sid = _session(api)
    profile = api.post(f"/api/report/session/{sid}/profile", json=PROFILE).json()
    assert profile["success"], profile

    res = api.post(f"/api/report/session/{sid}/prompt", json={
        "berichtszeitraum": "01.01.2025 - 31.12.2025", "include_wissensdatenbank": False,
        "custom_instructions": "Gespraech mit Sabine Leonhardt (Geburtstag 14. Mai 2017) betonen.",
    }).json()

    assert res["success"], res
    low = res["prompt"].lower()
    for forbidden in FORBIDDEN:
        assert forbidden.lower() not in low, f"Falldatum im Cloud-Prompt: {forbidden!r}"
    assert "fortschritte" in low and "feinmotorik" in low  # Inhalt bleibt, nur die Identitaet faellt


def test_api_refuses_cloud_profile_without_spacy_and_names_the_reason(api, monkeypatch):
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (False, "spaCy ist nicht installiert"))
    sid = _session(api)

    res = api.post(f"/api/report/session/{sid}/profile", json=PROFILE).json()

    assert res["success"] is False and res["privacy_block"] is True
    assert res["error_code"] == "ner_unavailable"
    assert "spaCy" in res["error"] and "lokal" in res["error"]
    dumped = json.dumps(res, ensure_ascii=False).lower()
    assert "jonas" not in dumped and "leonhardt" not in dumped


def test_api_refuses_prompt_without_pseudonymisation_profile(api):
    sid = _session(api)

    res = api.post(f"/api/report/session/{sid}/prompt", json={"include_wissensdatenbank": False}).json()

    assert res["success"] is False and res["privacy_block"] is True
    assert res["error_code"] == "profile_missing"
    assert "prompt" not in res
    assert "jonas" not in json.dumps(res).lower()


def test_api_block_reason_is_machine_readable_without_values(api, tmp_path):
    # Kleinschreibung trifft die Ersetzung nicht -> die Sperre vor dem Senden muss greifen.
    (tmp_path / "akte" / "Mailverteiler.txt").write_text("Verteiler: familie jonas leonhardt\n", encoding="utf-8")
    sid = _session_with_three_files(api)
    assert api.post(f"/api/report/session/{sid}/profile", json=PROFILE).json()["success"]

    res = api.post(f"/api/report/session/{sid}/prompt", json={"include_wissensdatenbank": False}).json()

    assert res["success"] is False and res["privacy_block"] is True
    assert res["error_code"] == "identity_terms_in_prompt"
    assert "Datenschutz-Sperre" in res["error"]
    dumped = json.dumps(res, ensure_ascii=False).lower()
    for value in ("jonas", "leonhardt", "14.05.2017"):
        assert value not in dumped


def test_api_new_profile_after_a_block_rebuilds_the_bundle(api, tmp_path):
    """Ausweg aus der Sperre: Schreibweise in die Begriffsliste, Profil neu -> Prompt aus neuem Bundle."""
    (tmp_path / "akte" / "Mailverteiler.txt").write_text("Verteiler: familie jonas leonhardt\n", encoding="utf-8")
    sid = _session_with_three_files(api)
    assert api.post(f"/api/report/session/{sid}/profile", json=PROFILE).json()["success"]
    blocked = api.post(f"/api/report/session/{sid}/prompt", json={"include_wissensdatenbank": False}).json()
    assert blocked["error_code"] == "identity_terms_in_prompt"

    fixed = dict(PROFILE, additional_terms=[*PROFILE["additional_terms"], "familie jonas leonhardt"])
    assert api.post(f"/api/report/session/{sid}/profile", json=fixed).json()["success"]
    res = api.post(f"/api/report/session/{sid}/prompt", json={"include_wissensdatenbank": False}).json()

    assert res["success"], res
    low = res["prompt"].lower()
    for forbidden in FORBIDDEN:
        assert forbidden.lower() not in low, f"Falldatum im Cloud-Prompt: {forbidden!r}"


def _session_with_three_files(client) -> str:
    started = client.post("/api/report/session/start").json()
    sid = started["session_id"]
    imported = client.post(f"/api/report/session/{sid}/import", json={"folder": "akte"}).json()
    assert imported["success"] and imported["imported_count"] == 3, imported
    return sid


# --- gemeinsamer Codepfad: die Senke sperrt jeden Cloud-Prompt ohne Akten-Scan --------------------

def test_generate_prompt_refuses_cloud_profile_without_document_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""))
    service = rws.ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    service.create_temp_profile(session, "Jonas Leonhardt", "14.05.2017")  # ohne scan_folder

    with pytest.raises(rws.PromptPrivacyError) as exc:
        service.generate_prompt(session, include_wissensdatenbank=False)
    assert exc.value.code == "document_scan_missing"


def test_generate_prompt_refuses_cloud_without_ner(tmp_path, monkeypatch):
    monkeypatch.setattr(rws, "WISSENSDATENBANK", tmp_path / "kb")
    monkeypatch.setattr(anonymizer_service, "SPACY_AVAILABLE", False)
    service = rws.ReportWorkflowService(base_path=tmp_path)
    session = service.start_session()
    service.create_temp_profile(session, "Jonas Leonhardt", "14.05.2017", scan_folder=tmp_path / "data_roh")

    with pytest.raises(rws.PromptPrivacyError) as exc:
        service.generate_prompt(session, include_wissensdatenbank=False)
    assert exc.value.code == "ner_unavailable"


# --- weiterer Cloud-Sendeweg: Provider-Cloud-Port ------------------------------------------------

@pytest.mark.asyncio
async def test_provider_cloud_route_is_unavailable_without_ner(monkeypatch):
    from hub._services.document.report_provider_adapter import BachModelRoutePort, ReportHostPortError
    from hub._services.document.report_provider_contract import is_neutral_reason_code

    sent = []

    class Backend:
        async def chat(self, messages, *, tools, model):
            sent.append(messages)
            return {"content": "synthetic"}

    async def attest(_backend, _model):
        return {"verified": True, "route_id": "cloud_attested_route_1", "cloud_route": True,
                "fallback_disabled": True}

    monkeypatch.setattr(anonymizer_service, "SPACY_AVAILABLE", False)
    cloud = BachModelRoutePort(Backend(), "cloud-model", "cloud", cloud_attestor=attest)

    status = await cloud.route_status()
    assert status["available"] is False and status["reason_code"] == "ner_unavailable"
    assert is_neutral_reason_code(status["reason_code"])
    pin = await cloud.pin_route("run-ner", expected_mode="cloud", request_mode="cloud",
                                allow_fallback=False, local_only=False)
    assert pin["verified"] is False
    with pytest.raises(ReportHostPortError):
        await cloud.generate("synthetic", run_id="run-ner", mode="cloud", request_mode="cloud",
                             route_id="cloud_attested_route_1", route_ref="x" * 32,
                             allow_fallback=False, local_only=False)
    assert sent == []
