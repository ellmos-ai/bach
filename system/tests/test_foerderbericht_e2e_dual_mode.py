# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""End-to-End Dual-Mode Tests fuer FoerderberichtPipeline (lokal vs. cloud mit Synthetik-Akte)."""

import io
import json
import re
import sys
from pathlib import Path

import pytest
from docx import Document

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub._services.document import foerderbericht_pipeline as fp
from hub._services.document.foerderbericht_pipeline import FoerderberichtPipeline


REQUIRED_HEADINGS = ["Stammdaten", "Aktuelle Entwicklungen", "Empfehlung"]


@pytest.fixture(autouse=True)
def _synthetic_template(tmp_path, monkeypatch):
    """Neutrale Vorlage; der private Generator ist im Testlauf nie vorhanden."""
    from hub._services.document import report_workflow_service as rws

    template = tmp_path.parent / f"{tmp_path.name}_vorlage.docx"
    doc = Document()
    doc.add_heading("Stammdaten", 1)
    doc.add_paragraph("Name: {{KLIENT_NAME}}")
    doc.add_paragraph("Geburtsdatum: {{GEBURTSDATUM}}")
    doc.add_heading("Aktuelle Entwicklungen", 1)
    doc.add_paragraph("{{AKTUELLE_ENTWICKLUNGEN}}")
    doc.add_heading("Empfehlung", 1)
    doc.add_paragraph("{{EMPFEHLUNG}}")
    doc.save(template)
    monkeypatch.setattr(rws, "TEMPLATE_PATH", template)
    monkeypatch.setattr(rws, "BACH_BASE", tmp_path / "kein-generator")
    # Cloud-Sperre ohne NER hat eigene Tests (test_foerderbericht_privacy_gates.py). Hier geht es um den
    # Durchstich; wo spaCy fehlt (CI, Mac), laeuft er ohne NER. Echte NER-Abdeckung nur mit spaCy.
    from hub._services.document import anonymizer_service
    monkeypatch.setattr(anonymizer_service, "ner_ready", lambda: (True, ""))


def _assert_real_report(path: Path) -> None:
    """Echter Bericht: Pflichtueberschriften der Vorlage, Absaetze, keine JSON-Reste."""
    texts = [p.text for p in Document(str(path)).paragraphs]
    assert len([t for t in texts if t.strip()]) >= 6
    for heading in REQUIRED_HEADINGS:
        assert heading in texts, f"Pflichtueberschrift fehlt: {heading}"
    body = "\n".join(texts)
    assert not re.search(r'[{}"]', body), "JSON-Reste oder Platzhalter im Bericht"


def _create_synthetic_case(base_path: Path) -> dict:
    """Legt eine vollstaendig synthetische Klientenakte in data_roh/ an."""
    client_dir = base_path / "data_roh" / "Leonhardt, Jonas"
    client_dir.mkdir(parents=True, exist_ok=True)

    (client_dir / "Aktendeckblatt.txt").write_text(
        "Name: Jonas Leonhardt\n"
        "Geboren am 14.05.2017\n"
        "Adresse: Gartenstraße 18, 79102 Freiburg\n"
        "Eltern: Sabine Leonhardt, Markus Leonhardt\n"
        "Telefon: 0761-5550100\n"
        "E-Mail: sabine.leonhardt@example.org\n"
        "Einzeltherapeutin: Frau Bergmann\n",
        encoding="utf-8",
    )
    (client_dir / "Verlaufsprotokoll_2025.txt").write_text(
        "Im Berichtszeitraum zeigte Jonas Leonhardt deutliche Fortschritte in der Feinmotorik "
        "und im Sozialverhalten. Mutter Sabine Leonhardt und Vater Markus Leonhardt berichteten "
        "im Elterngespraech mit Frau Bergmann ueber entspanntere Hausaufgabensituationen in "
        "der Gartenstraße 18 in Freiburg.\n",
        encoding="utf-8",
    )
    return {
        "client_name": "Jonas Leonhardt",
        "geburtsdatum": "14.05.2017",
        "parent_names": ["Sabine Leonhardt", "Markus Leonhardt"],
        "client_address": "Gartenstraße 18, 79102 Freiburg",
        "additional_terms": ["Frau Bergmann", "Gartenstraße"],
        "forbidden_in_cloud_prompt": [
            "Jonas",
            "Leonhardt",
            "Sabine",
            "Markus",
            "Bergmann",
            "14.05.2017",
            "Gartenstraße",
            "Gartenstrasse",
            "Freiburg",
            "79102",
            "0761-5550100",
            "sabine.leonhardt@example.org",
        ],
        # Fachbegriffe sind keine Personen und muessen fuer das Cloud-Modell lesbar bleiben
        "required_in_cloud_prompt": [
            "Fortschritte", "Feinmotorik", "Sozialverhalten", "Elterngespraech", "Hausaufgabensituationen",
        ],
    }


def _read_docx_full_text(docx_path: Path) -> str:
    doc = Document(str(docx_path))
    parts = [p.text for p in doc.paragraphs if p.text]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    parts.append(cell.text)
    return "\n".join(parts)


def test_e2e_lokal_mode_without_anonymization_produces_docx(tmp_path, monkeypatch):
    """Pfad 1 (lokal): Keine Anonymisierung, lokales Ollama-Backend, vollständiger .docx-Durchstich."""
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.delenv("FOERDERBERICHT_SSH_TUNNEL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")

    meta = _create_synthetic_case(tmp_path)
    pipe = FoerderberichtPipeline(base_path=tmp_path)

    captured_Prompts = []

    class FakeOllamaOpener:
        def open(self, req, timeout=None):
            if req.full_url.endswith("/api/ps"):
                return io.BytesIO(json.dumps({"models": [{"name": "qwen3.8:27b-mlx", "context_length": 16384}]}).encode("utf-8"))
            payload = json.loads(req.data.decode("utf-8"))
            prompt_text = payload["messages"][0]["content"]
            captured_Prompts.append(prompt_text)
            llm_json = {
                "klient_name": "Jonas Leonhardt",
                "geburtsdatum": "14.05.2017",
                "berichtszeitraum": "01.01.2025 - 31.12.2025",
                "aktuelle_entwicklungen": (
                    "Jonas Leonhardt (geb. 14.05.2017) hat im Berichtszeitraum mit Unterstuetzung "
                    "von Sabine Leonhardt, Markus Leonhardt und Frau Bergmann seine Feinmotorik "
                    "und Gruppeninteraktion nachhaltig verbessert."
                ),
                "empfehlung": "Weiterbewilligung der heilpaedagogischen Foerderung.",
            }
            resp = {
                "message": {"content": json.dumps(llm_json, ensure_ascii=False)},
                "done_reason": "stop",
                "prompt_eval_count": 420,
                "eval_count": 180,
            }
            return io.BytesIO(json.dumps(resp).encode("utf-8"))

    monkeypatch.setattr(fp.urllib.request, "build_opener", lambda *h: FakeOllamaOpener())

    res = pipe.run_full_pipeline(
        modus="lokal",
        berichtszeitraum="01.01.2025 - 31.12.2025",
        auto_cleanup=False,
    )

    assert res.success, f"Lokal-Pipeline fehlgeschlagen: {res.error}"
    assert res.output_path is not None and res.output_path.is_file()
    assert res.output_path.suffix == ".docx"
    _assert_real_report(res.output_path)

    # Prompt im lokalen Modus enthaelt Klartext (keine Person###-Platzhalter)
    assert len(captured_Prompts) == 1
    assert "Jonas Leonhardt" in captured_Prompts[0]
    assert "14.05.2017" in captured_Prompts[0]
    assert not re.search(r"Person\d{3}", captured_Prompts[0])

    session_info = json.loads((tmp_path / "data_bundled" / "session_info.json").read_text(encoding="utf-8"))
    assert session_info["modus"] == "lokal"
    assert session_info["mappings"] == {}

    docx_text = _read_docx_full_text(res.output_path)
    assert "Jonas Leonhardt" in docx_text
    assert "14.05.2017" in docx_text


def test_e2e_cloud_mode_with_pseudonymization_and_deanonymization_produces_docx(tmp_path, monkeypatch):
    """Pfad 2 (cloud): Lokale Pseudonymisierung -> 0 PII im Prompt -> Cloud-LLM -> vollständige Rückersetzung im .docx."""
    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    meta = _create_synthetic_case(tmp_path)
    pipe = FoerderberichtPipeline(base_path=tmp_path)

    captured_cloud_prompt = {}

    def fake_cloud_llm(self, prompt: str, backend: str, model: str) -> str:
        captured_cloud_prompt["prompt"] = prompt
        captured_cloud_prompt["backend"] = backend
        captured_cloud_prompt["model"] = model
        session_info = json.loads((tmp_path / "data_bundled" / "session_info.json").read_text(encoding="utf-8"))
        tarnname = session_info["tarnname"]
        fake_geb = session_info["fake_geburtsdatum"]
        # Suche Tarn-Token fuer Sabine Leonhardt und Frau Bergmann aus den Mappings
        all_maps = {}
        for cat in session_info["mappings"].values():
            all_maps.update(cat)
        sabine_tarn = all_maps.get("Sabine Leonhardt", "Elternteil")
        bergmann_tarn = all_maps.get("Frau Bergmann", "Fachkraft")

        llm_json = {
            "klient_name": tarnname,
            "geburtsdatum": fake_geb,
            "berichtszeitraum": "01.01.2025 - 31.12.2025",
            "aktuelle_entwicklungen": (
                f"{tarnname} (geb. {fake_geb}) zeigte im Berichtszeitraum sehr gute Fortschritte. "
                f"Im Austausch mit {sabine_tarn} und {bergmann_tarn} konnten die Ziele erreicht werden."
            ),
            "empfehlung": f"Weiterbewilligung fuer {tarnname} wird empfohlen.",
        }
        return json.dumps(llm_json, ensure_ascii=False)

    monkeypatch.setattr(FoerderberichtPipeline, "_call_llm", fake_cloud_llm)

    res = pipe.run_full_pipeline(
        modus="cloud",
        client_name=meta["client_name"],
        geburtsdatum=meta["geburtsdatum"],
        parent_names=meta["parent_names"],
        client_address=meta["client_address"],
        additional_terms=meta["additional_terms"],
        berichtszeitraum="01.01.2025 - 31.12.2025",
        auto_cleanup=False,
    )

    assert res.success, f"Cloud-Pipeline fehlgeschlagen: {res.error}"
    assert res.output_path is not None and res.output_path.is_file()
    assert res.output_path.suffix == ".docx"
    _assert_real_report(res.output_path)

    prompt = captured_cloud_prompt["prompt"]
    # Gesamter Prompt (nicht nur das Bundle), Gross-/Kleinschreibung egal
    lowered = prompt.lower()
    for forbidden in meta["forbidden_in_cloud_prompt"]:
        assert forbidden.lower() not in lowered, f"PII-Leck im Cloud-Prompt gefunden: {forbidden!r}"
    assert not re.search(r"stra(ß|ss)e\s*18", lowered), "Strasse mit Hausnummer im Cloud-Prompt"
    for term in meta["required_in_cloud_prompt"]:
        assert term in prompt, f"Fachbegriff wurde mitpseudonymisiert: {term!r}"

    docx_text = _read_docx_full_text(res.output_path)
    assert "Jonas Leonhardt" in docx_text
    assert "14.05.2017" in docx_text
    assert "Sabine Leonhardt" in docx_text
    assert "Frau Bergmann" in docx_text
    assert res.tarnname not in docx_text, f"Tarnname {res.tarnname!r} wurde nicht zurueckuebersetzt"
    assert not re.search(r"Person\d{3}", docx_text)
    assert not re.search(r"BEGRIFF_\d{2}", docx_text)


def test_e2e_missing_template_fails_with_clear_error_and_no_document(tmp_path, monkeypatch):
    """Fehlende Vorlage: klare Fehlermeldung, kein Dokument, das wie ein Bericht aussieht."""
    from hub._services.document import report_workflow_service as rws

    monkeypatch.setattr(FoerderberichtPipeline, "_find_onedrive_exe", staticmethod(lambda: None))
    monkeypatch.setattr(rws, "TEMPLATE_PATH", tmp_path / "gibt-es-nicht.docx")
    monkeypatch.setattr(
        FoerderberichtPipeline, "_call_llm",
        lambda self, prompt, backend, model: json.dumps({"empfehlung": "Weiterbewilligung."}),
    )
    meta = _create_synthetic_case(tmp_path)

    res = FoerderberichtPipeline(base_path=tmp_path).run_full_pipeline(
        modus="cloud",
        client_name=meta["client_name"],
        geburtsdatum=meta["geburtsdatum"],
        parent_names=meta["parent_names"],
        client_address=meta["client_address"],
        additional_terms=meta["additional_terms"],
        berichtszeitraum="01.01.2025 - 31.12.2025",
        auto_cleanup=False,
    )

    assert not res.success
    assert "Vorlage" in res.error and "gibt-es-nicht.docx" in res.error
    assert res.output_path is None or res.output_path.suffix != ".docx"
    assert not list((tmp_path / "output_berichte").glob("*.docx"))
