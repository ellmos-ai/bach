# SPDX-License-Identifier: MIT
"""
Test Suite fuer NemoFold: Workflow-Lernen & Step-Ketten Synthese (Ocean Subsystem).

Testet:
1. Transcript-Parsing und Normalisierung von Werkzeugfolgen
2. Heuristik-Detektor und Step-Ketten-Synthese (Dev, Research, Review, Generic)
3. Workflow-TÜV und Rollback-Sicherheitsbewertung
4. Kandidaten-Queue, Speicherung und Statusfilter
5. Operator-Freigabe (Promotion nach marblerun_chains) und Ablehnung
6. Unified API Endpunkte (/api/learning/nemofold/* und /api/setup/ocean-map)
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from system.gui.api.unified_api import router as unified_router
from system.hub._services.nemofold_workflow_service import NemoFoldWorkflowService

# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_nemofold.db"
    return db_file


@pytest.fixture
def service(temp_db: Path) -> NemoFoldWorkflowService:
    return NemoFoldWorkflowService(db_path=str(temp_db))


# ═══════════════════════════════════════════════════════════════
# UNIT TESTS: SERVICE LOGIK
# ═══════════════════════════════════════════════════════════════

def test_service_initialization_and_schema(temp_db: Path):
    _ = NemoFoldWorkflowService(db_path=str(temp_db))
    conn = sqlite3.connect(str(temp_db))
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "nemofold_workflow_candidates" in tables
    assert "nemofold_synthesis_runs" in tables


def test_parse_events_from_jsonl(service: NemoFoldWorkflowService):
    jsonl_sample = """
    {"source": "agent", "tool_calls": [{"name": "fc_search_content", "args": {"query": "class Foo"}}]}
    {"source": "agent", "tool_calls": [{"name": "view_file", "args": {"path": "foo.py"}}]}
    {"source": "agent", "tool_calls": [{"name": "replace_file_content", "args": {"path": "foo.py"}}]}
    {"source": "agent", "content": "Running tests: call pytest() and ruff check"}
    {"source": "agent", "tool_calls": [{"name": "gh_pr_create", "args": {"title": "Fix"}}]}
    """
    events = service.parse_events_from_transcript(jsonl_sample)
    assert len(events) >= 4
    categories = [e["category"] for e in events]
    assert "search_inspect" in categories
    assert "edit_transform" in categories
    assert "verify_test" in categories
    assert "commit_release" in categories


def test_coalesce_events(service: NemoFoldWorkflowService):
    raw_events = [
        {"tool": "view_file", "category": "search_inspect", "agent": "Ati"},
        {"tool": "view_file", "category": "search_inspect", "agent": "Ati"},
        {"tool": "view_file", "category": "search_inspect", "agent": "Ati"},
        {"tool": "replace_file_content", "category": "edit_transform", "agent": "codex"}
    ]
    coalesced = service._coalesce_events(raw_events)
    assert len(coalesced) == 2
    assert coalesced[0]["repeat_count"] == 3
    assert coalesced[1]["repeat_count"] == 1


def test_synthesize_dev_renovation_chain(service: NemoFoldWorkflowService):
    events = [
        {"tool": "fc_search_content", "category": "search_inspect", "agent": "Ati"},
        {"tool": "cc_analyze_code", "category": "analyze_diagnose", "agent": "bach"},
        {"tool": "replace_file_content", "category": "edit_transform", "agent": "codex", "reversibility": "two_phase_journal"},
        {"tool": "pytest", "category": "verify_test", "agent": "Ollama Local"},
        {"tool": "gh_pr_create", "category": "commit_release", "agent": "Sentinel"}
    ]
    chains = service.synthesize_chains_from_events(events, context_name="Test Session")
    assert len(chains) >= 1
    dev_chain = next(c for c in chains if "Dev-Fix" in c["title"])
    assert len(dev_chain["steps"]) == 5
    assert dev_chain["confidence_score"] >= 0.9
    assert dev_chain["tuv_status"] == "certified"
    assert dev_chain["tuv_report"]["has_rollback_support"] is True


def test_synthesize_multi_agent_review_chain(service: NemoFoldWorkflowService):
    events = [
        {"tool": "cc_analyze_code", "category": "analyze_diagnose", "agent": "bach"},
        {"tool": "test_run", "category": "verify_test", "agent": "Ollama Local"},
        {"tool": "lock_status", "category": "security_gate", "agent": "Sentinel"}
    ]
    chains = service.synthesize_chains_from_events(events, context_name="Review Session")
    assert len(chains) >= 1
    review_chain = next(c for c in chains if "Review" in c["title"])
    assert len(review_chain["steps"]) == 3
    assert review_chain["confidence_score"] >= 0.9


def test_workflow_tuv_rejection_on_dangerous_pattern(service: NemoFoldWorkflowService):
    steps_without_rollback = [
        {"name": "Dangerous Direct Mod", "tool": "raw_sed", "category": "edit_transform", "action_journal_support": False},
        {"name": "Direct Push to Main", "tool": "git_push", "category": "commit_release", "inputs": {"branch": "main"}}
    ]
    status, report = service._evaluate_workflow_tuv(steps_without_rollback)
    assert status in ("needs_review", "rejected")
    assert report["has_rollback_support"] is False
    assert len(report["issues"]) >= 2


def test_store_and_list_candidates(service: NemoFoldWorkflowService):
    chain_sample = {
        "name": "sample-test-chain-1",
        "title": "Sample Test Chain",
        "description": "Eine Testkette",
        "trigger_type": "manual",
        "steps": [{"step_index": 1, "name": "Step 1"}],
        "confidence_score": 0.85,
        "tuv_status": "certified",
        "tuv_report": {"rating": "A+"},
        "provenance": {"source": "unit_test"}
    }
    cand_id = service.store_candidate(chain_sample)
    assert cand_id > 0

    candidates = service.list_candidates(status="pending")
    assert len(candidates) == 1
    assert candidates[0]["chain_name"] == "sample-test-chain-1"

    detail = service.get_candidate(cand_id)
    assert detail is not None
    assert detail["title"] == "Sample Test Chain"
    assert len(detail["steps"]) == 1


def test_approve_and_promote_candidate_to_marblerun(service: NemoFoldWorkflowService, temp_db: Path):
    chain_sample = {
        "name": "promotable-chain-42",
        "title": "Promotable Chain",
        "description": "Wird nach MarbleRun befoerdert",
        "trigger_type": "manual",
        "steps": [
            {"step_index": 1, "name": "Step 1", "agent": "Ati"},
            {"step_index": 2, "name": "Step 2", "agent": "codex"}
        ],
        "confidence_score": 0.9,
        "tuv_status": "certified",
        "tuv_report": {"rating": "A+"},
        "provenance": {"source": "unit_test"}
    }
    cand_id = service.store_candidate(chain_sample)

    with pytest.raises(ValueError, match="native Veröffentlichung"):
        service.approve_candidate(cand_id, operator="lukas", notes="Freigabe Test")
    cand = service.get_candidate(cand_id)
    assert cand["status"] == "pending"
    assert cand["promotion_available"] is False
    conn = sqlite3.connect(str(temp_db))
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='marblerun_chains'").fetchone() is None
    conn.close()


def test_reject_candidate(service: NemoFoldWorkflowService):
    chain_sample = {
        "name": "rejectable-chain-99",
        "title": "Rejectable Chain",
        "steps": [],
        "confidence_score": 0.5,
        "tuv_status": "needs_review"
    }
    cand_id = service.store_candidate(chain_sample)
    cand = service.get_candidate(cand_id)
    res = service.reject_candidate(cand_id, reason="Unzureichende Evidenz", operator="operator",
        expected_revision=cand["candidate_revision"], expected_digest=cand["candidate_digest"],
        request_id="nemo-reject-0001")
    assert res["success"] is True
    assert res["status"] == "rejected"

    cand = service.get_candidate(cand_id)
    assert cand["status"] == "rejected"
    assert cand["review_notes"] == "Unzureichende Evidenz"


def test_get_stats(service: NemoFoldWorkflowService):
    stats = service.get_stats()
    assert stats["subsystem"] == "Nemofold"
    assert stats["status"] == "active"
    assert "total_candidates" in stats
    assert "pending_candidates" in stats
    assert "approved_candidates" in stats


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TESTS: FASTAPI HTTP ENDPOINTS
# ═══════════════════════════════════════════════════════════════

def test_api_synthesis_and_candidates_flow(monkeypatch, temp_db: Path):
    test_service = NemoFoldWorkflowService(db_path=str(temp_db))
    monkeypatch.setattr("system.gui.api.unified_api._get_nemofold_service_instance", lambda: test_service)
    monkeypatch.setattr("system.gui.api.unified_api._get_conn", lambda timeout=30.0: sqlite3.connect(str(temp_db)))

    app = FastAPI()
    app.include_router(unified_router)
    client = TestClient(app)

    # 1. Synthese ausfuehren
    payload = {
        "source_type": "transcript",
        "source_ref": "Session #490",
        "raw_text": """
        User: Fix import issues.
        Agent: calling fc_search_content(query="import")
        Agent: calling cc_analyze_code(target="system/foo.py")
        Agent: calling replace_file_content(path="system/foo.py")
        Agent: running pytest
        Agent: calling gh_pr_create(title="fix imports")
        """
    }
    synth_resp = client.post("/api/learning/nemofold/synthesize", json=payload)
    assert synth_resp.status_code == 200
    synth_data = synth_resp.json()
    assert synth_data["success"] is True
    assert synth_data["chains_synthesized"] >= 1

    # 2. Kandidaten abrufen
    cand_resp = client.get("/api/learning/nemofold/candidates?status=pending")
    assert cand_resp.status_code == 200
    cand_data = cand_resp.json()
    assert cand_data["count"] >= 1
    target_id = cand_data["candidates"][0]["id"]

    # 3. Detailansicht
    detail_resp = client.get(f"/api/learning/nemofold/candidates/{target_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == target_id

    # 4. Freigabe
    appr_resp = client.post(f"/api/learning/nemofold/candidates/{target_id}/approve", json={"approved_by": "lead_operator"})
    assert appr_resp.status_code == 401  # Body labels confer no authority.

    # 5. Stats abrufen
    stats_resp = client.get("/api/learning/nemofold/stats")
    assert stats_resp.status_code == 200
    stats_data = stats_resp.json()
    assert stats_data["approved_candidates"] == 0


def test_api_ocean_map_contains_active_nemofold(monkeypatch, temp_db: Path):
    test_service = NemoFoldWorkflowService(db_path=str(temp_db))
    monkeypatch.setattr("system.gui.api.unified_api._get_nemofold_service_instance", lambda: test_service)
    monkeypatch.setattr("system.gui.api.unified_api._get_conn", lambda timeout=30.0: sqlite3.connect(str(temp_db)))

    app = FastAPI()
    app.include_router(unified_router)
    client = TestClient(app)

    res = client.get("/api/setup/ocean-map")
    assert res.status_code == 200
    data = res.json()
    subsystems = data.get("subsystems", [])
    nemofold_sub = next((s for s in subsystems if s.get("name") == "NemoFold"), None)
    assert nemofold_sub is not None
    assert nemofold_sub["status"] == "active"
    assert "metrics" in nemofold_sub
    assert nemofold_sub["metrics"]["status"] == "active"
