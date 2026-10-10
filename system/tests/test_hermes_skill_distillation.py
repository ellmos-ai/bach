# SPDX-License-Identifier: MIT
"""
test_hermes_skill_distillation.py - Tests fuer Hermes Skill-Destillation (Task #1689)
=====================================================================================

Prueft:
- Rauschreduktion (~76% Zielquote, Filterung von Grußformeln, Floskeln, Traceback-Wüsten)
- Lessons Learned Extraktion (memory_lessons)
- SKILL.md-Entwurfssynthese nach SentinelFleet-Standard mit YAML Frontmatter
- Human-in-the-Loop Freigabe- und Ablehnungs-Workflow (Promotion in skill_versions)
- REST-API Endpunkte (/api/learning/hermes/*) und Ocean Modulschaltplan-Status (active)
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from system.gui.api.unified_api import router as unified_router
from system.hub._services.hermes_distillation_service import (
    CleanedTranscriptResult,
    HermesDistillationService,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_hermes_bach.db"
    return db_file


@pytest.fixture
def hermes_service(temp_db: Path) -> HermesDistillationService:
    service = HermesDistillationService(db_path=temp_db)
    service.ensure_schema()
    return service


def test_hermes_noise_reduction(hermes_service: HermesDistillationService):
    """Testet die deterministische Rauschreduktion von Dialogtexten."""
    raw_transcript = [
        {"role": "user", "content": "Hallo! Guten Morgen lieber Assistent! Wie geht es dir heute?"},
        {
            "role": "assistant",
            "content": (
                "Hallo! Mir geht es ausgezeichnet, vielen Dank! "
                "Ich hoffe, du hast einen schönen Tag! Wie kann ich dir heute behilflich sein?"
            ),
        },
        {
            "role": "user",
            "content": (
                "Wir müssen den Pytest-Lauf unter Windows reparieren. "
                "Fehler: UnicodeEncodeError 'charmap' codec can't encode character. "
                "Bitte immer $env:PYTHONIOENCODING='utf-8' setzen!"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Alles klar, verstanden! Hier ist die Lösung:\n"
                "Traceback (most recent call last):\n"
                "  File 'run.py', line 12, in <module>\n"
                "UnicodeEncodeError: 'charmap' codec can't encode character '\\U0001f319'\n"
                "Lösung: Vor dem Aufruf immer $env:PYTHONIOENCODING='utf-8' setzen. "
                "Best Practice: UTF-8 explizit in allen Subprozessen erzwingen.\n"
                "Ich hoffe das hilft dir weiter! Sag Bescheid wenn du noch Fragen hast!"
            ),
        },
        {"role": "user", "content": "Vielen Dank und schönen Feierabend!"},
    ]

    cleaned: CleanedTranscriptResult = hermes_service.clean_transcript(raw_transcript)

    assert cleaned.raw_char_count > cleaned.cleaned_char_count
    assert cleaned.noise_reduction_percent > 30.0  # Deutliche Rauschreduktion
    assert cleaned.turns_count > 0
    assert "Testing / Pytest" in cleaned.detected_topics or "Windows OS & PowerShell" in cleaned.detected_topics
    assert "Fokus-Themen:" in cleaned.consolidated_summary


def test_hermes_lessons_extraction(hermes_service: HermesDistillationService):
    """Testet die Extraktion von Lessons Learned aus bereinigten Daten."""
    sample_text = [
        {
            "role": "user",
            "content": "Problem: UnicodeEncodeError charmap unter Windows PowerShell.",
        },
        {
            "role": "assistant",
            "content": "Merke: Vor Python-Aufrufen immer $env:PYTHONIOENCODING='utf-8' setzen.",
        },
        {
            "role": "assistant",
            "content": "Wichtig: Labels in Mermaid-Diagrammen immer quotieren wenn Klammern vorkommen: Node[\"Label (Info)\"].",
        },
    ]

    cleaned = hermes_service.clean_transcript(sample_text)
    lessons = hermes_service.extract_lessons(cleaned)

    assert len(lessons) >= 2
    titles = [l.title.lower() for l in lessons]
    assert any("unicode" in t or "power" in t for t in titles)
    assert any("mermaid" in t or "quotieren" in t for t in titles)


def test_hermes_skill_synthesis(hermes_service: HermesDistillationService):
    """Testet die Synthese eines vollstaendigen SKILL.md Entwurfs nach SentinelFleet-Schema."""
    sample_text = [
        {"role": "user", "content": "Erstelle eine Routine für FastAPI Backend-Tests mit Pytest."},
        {"role": "assistant", "content": "Ablauf: 1. Server starten 2. Endpunkte pruefen 3. Clean up."},
    ]
    cleaned = hermes_service.clean_transcript(sample_text)
    candidate = hermes_service.distill_skill(
        cleaned, session_id="test-session-123", skill_name_hint="fastapi-test-runner"
    )

    assert candidate.name == "fastapi-test-runner"
    assert candidate.category == "dev"
    assert candidate.version == "1.0.0"
    assert candidate.status == "pending"
    assert len(candidate.trigger_phrases) >= 2

    # Pruefe SKILL.md Struktur und Frontmatter
    assert candidate.content.startswith("---")
    assert "name: fastapi-test-runner" in candidate.content
    assert "distilled_by: hermes" in candidate.content
    assert "## 1. Übersicht & Zweck" in candidate.content
    assert "## 3. Verhaltensregeln & Leitplanken" in candidate.content
    assert "## 4. Standard-Ablauf" in candidate.content


def test_hermes_full_pipeline_persistence(hermes_service: HermesDistillationService, temp_db: Path):
    """Testet die vollstaendige Pipeline inkl. Ablage in allen DB-Tabellen."""
    raw_dialog = "Hallo! Fehler: charmap Encode. Lösung: PYTHONIOENCODING=utf-8 setzen. Danke!"

    res = hermes_service.run_pipeline(
        messages_or_text=raw_dialog,
        session_id="chat-run-001",
        skill_name_hint="windows-utf8-fixer",
        persist=True,
    )

    assert res.run_id > 0
    assert res.status == "completed"
    assert res.candidate is not None
    assert res.candidate["id"] is not None

    # DB Pruefung
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()

    cands = cur.execute("SELECT name, status FROM hermes_skill_candidates").fetchall()
    assert len(cands) == 1
    assert cands[0][0] == "windows-utf8-fixer"
    assert cands[0][1] == "pending"

    runs = cur.execute("SELECT raw_char_count, cleaned_char_count FROM hermes_distillation_runs").fetchall()
    assert len(runs) == 1

    lessons = cur.execute("SELECT title FROM memory_lessons").fetchall()
    assert lessons == []
    assert hermes_service.get_candidate(res.candidate["id"])["lessons_draft"]

    dreams = cur.execute("SELECT summary FROM memory_dream_log").fetchall()
    assert len(dreams) == 1

    conn.close()


def test_hermes_approval_and_rejection_workflow(hermes_service: HermesDistillationService, temp_db: Path):
    """Testet Human-in-the-Loop Freigabe und Ablehnung."""
    # Pipeline laufen lassen
    res = hermes_service.run_pipeline(
        messages_or_text="Merke: Always test before commit. Best Practice: Run ruff check.",
        skill_name_hint="git-pre-commit-ops",
        persist=True,
    )
    cand_id = res.candidate["id"]

    # 1. Kandidat pruefen
    cand = hermes_service.get_candidate(cand_id)
    assert cand is not None
    assert cand["status"] == "pending"

    # 2. Content review is bound and does not publish a native skill.
    with pytest.raises(ValueError, match="native Veröffentlichung"):
        hermes_service.approve_candidate(cand_id, approved_by="senior_architect")
    review = hermes_service.review_candidate(cand_id, actor="device:7", notes="Entwurf gelesen",
        expected_revision=cand["candidate_revision"], expected_digest=cand["candidate_digest"],
        request_id="hermes-review-0001")
    assert review["status"] == "reviewed"
    assert review["targets_published"] is False
    conn = sqlite3.connect(str(temp_db))
    cur = conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM skill_versions").fetchone()[0] == 0
    assert hermes_service.get_candidate(cand_id)["status"] == "reviewed"

    # 3. Zweiter Kandidat fuer Ablehnung
    res2 = hermes_service.run_pipeline(
        messages_or_text="Unsinniger Text ohne echten Nutzen.",
        skill_name_hint="junk-skill",
        persist=True,
    )
    cand2_id = res2.candidate["id"]
    cand2 = hermes_service.get_candidate(cand2_id)
    rej = hermes_service.reject_candidate(cand2_id, reason="Kein fachlicher Mehrwert", actor="device:7",
        expected_revision=cand2["candidate_revision"], expected_digest=cand2["candidate_digest"],
        request_id="hermes-reject-0002")
    assert rej["status"] == "rejected"

    cand2_updated = hermes_service.get_candidate(cand2_id)
    assert cand2_updated["status"] == "rejected"
    assert cand2_updated["rejection_reason"] == "Kein fachlicher Mehrwert"

    conn.close()


def test_hermes_stats(hermes_service: HermesDistillationService):
    """Testet die Aggregation von Kennzahlen."""
    hermes_service.run_pipeline("Test Text 1", persist=True)
    hermes_service.run_pipeline("Test Text 2", persist=True)

    stats = hermes_service.get_stats()
    assert stats["total_runs"] == 2
    assert stats["total_candidates"] == 2
    assert stats["status"] == "active"


def test_hermes_api_endpoints(monkeypatch, temp_db: Path):
    """Testet die REST-Endpunkte in unified_api.py."""
    # Mocke DB Pfad und Service
    service = HermesDistillationService(db_path=temp_db)
    service.ensure_schema()

    monkeypatch.setattr("system.gui.api.unified_api._get_hermes_service_instance", lambda: service)
    monkeypatch.setattr("system.gui.api.unified_api._get_conn", lambda timeout=30.0: service._get_connection())

    app = FastAPI()
    app.include_router(unified_router)
    client = TestClient(app)

    # 1. POST /api/learning/hermes/distill
    resp = client.post(
        "/api/learning/hermes/distill",
        json={
            "raw_text": "Problem: ModuleNotFoundError system. Lösung: PYTHONPATH=. setzen.",
            "skill_name_hint": "pythonpath-resolver",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    cand_id = data["skill_candidate"]["id"]

    # 2. GET /api/learning/hermes/candidates
    resp = client.get("/api/learning/hermes/candidates?status=pending")
    assert resp.status_code == 200
    cands_data = resp.json()
    assert cands_data["count"] >= 1
    assert any(c["id"] == cand_id for c in cands_data["candidates"])

    # 3. GET /api/learning/hermes/candidates/{id}
    resp = client.get(f"/api/learning/hermes/candidates/{cand_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "pythonpath-resolver"

    # 4. POST /api/learning/hermes/candidates/{id}/approve
    resp = client.post(f"/api/learning/hermes/candidates/{cand_id}/approve", json={"approved_by": "qa-lead"})
    assert resp.status_code == 401  # Bare author labels confer no device authority.

    # 5. GET /api/learning/hermes/stats
    resp = client.get("/api/learning/hermes/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["approved_candidates"] == 0

    # 6. GET /api/setup/ocean-map pruefen
    resp = client.get("/api/setup/ocean-map")
    assert resp.status_code == 200
    ocean_map = resp.json()
    hermes_sub = next((s for s in ocean_map["subsystems"] if s["name"] == "Hermes"), None)
    assert hermes_sub is not None
    assert hermes_sub["status"] == "active"
