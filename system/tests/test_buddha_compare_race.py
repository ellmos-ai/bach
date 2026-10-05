# SPDX-License-Identifier: MIT
"""Unit and integration tests for Buddha-Chat Compare-Race Multi-Model Evaluation.

Tests compliance with GUX-075 / T-20261003-605028960:
1. Parallel execution across configured candidate lanes.
2. SpendAuthority guard: paid commercial APIs report 'unavailable'/'blocked' with 0 ct when unauthorized.
3. Transparent evidence_kind tracking ('live', 'simulated', 'blocked', 'unavailable', 'failed').
4. NemoFold Inter-Rater Reliability evaluation (Cohen's Kappa & Agreement %).
5. Unified REST API endpoints for discovery, history, and evaluation.
"""

from __future__ import annotations

import pytest
from hub._services.chat.compare_race_service import (
    CompareLane,
    CompareRaceService,
    CostReceipt,
    EvidenceKind,
    LaneStatus,
    SpendAuthority,
)
from starlette.testclient import TestClient


@pytest.fixture
def isolated_service(tmp_path) -> CompareRaceService:
    history_file = tmp_path / "test_compare_race_history.json"
    return CompareRaceService(history_file=history_file)


def test_compare_lane_spend_authority_guard():
    """Paid lanes must be blocked without SpendAuthority."""
    paid_lane = CompareLane(
        id="claude",
        name="Claude 3.7",
        provider="anthropic",
        model="claude-3-7-sonnet",
        is_paid=True,
        requires_auth=True,
        description="Paid lane",
    )
    # 1. No spend authority
    avail, status, msg, ev = paid_lane.check_availability(None)
    assert not avail
    assert status == LaneStatus.BLOCKED
    assert ev == EvidenceKind.UNAVAILABLE
    assert "SpendAuthority nicht erteilt" in msg

    # 2. Spend authority approved but zero budget
    unbudgeted = SpendAuthority(approved=True, max_budget_cents=0.0)
    avail, status, msg, ev = paid_lane.check_availability(unbudgeted)
    assert not avail
    assert status == LaneStatus.BLOCKED

    # 3. Synthetic lane is always ready as simulated
    syn_lane = CompareLane(
        id="synthetic_a",
        name="Synthetic A",
        provider="synthetic",
        model="syn-a",
        is_paid=False,
        requires_auth=False,
        description="Synthetic",
    )
    avail, status, msg, ev = syn_lane.check_availability(None)
    assert avail
    assert status == LaneStatus.READY
    assert ev == EvidenceKind.SIMULATED


def test_cost_receipt_structure():
    """Cost receipts must capture financial, token and evidence metadata."""
    receipt = CostReceipt(
        evidence_kind=EvidenceKind.SIMULATED.value,
        spend_authorized=False,
        estimated_cost_cents=0.0,
        actual_cost_cents=0.0,
        tokens_input=12,
        tokens_output=48,
        provider="synthetic",
        model="test-model",
    )
    d = receipt.to_dict()
    assert d["evidence_kind"] == "simulated"
    assert d["actual_cost_cents"] == 0.0
    assert d["tokens_input"] == 12
    assert d["tokens_output"] == 48
    assert "timestamp" in d


@pytest.mark.asyncio
async def test_execute_race_synthetic_fixtures(isolated_service: CompareRaceService):
    """Synthetic race runs deterministically, computes receipts and NemoFold inter-rater reliability."""
    prompt = "Welche Vorteile hat eine ereignisgesteuerte Architektur?"
    result = await isolated_service.execute_race(
        prompt=prompt,
        lane_ids=["synthetic_fixture_a", "synthetic_fixture_b"],
        synthetic_fixtures=True,
    )

    assert result["prompt"] == prompt
    assert result["total_candidates"] == 2
    assert result["simulated_count"] == 2
    assert result["unavailable_count"] == 0

    # Inspect candidates
    candidates = result["candidates"]
    for c in candidates:
        assert c["evidence_kind"] == "simulated"
        assert c["status"] == "ready"
        assert c["latency_ms"] >= 45
        assert len(c["response"]) > 20
        assert c["receipt"]["evidence_kind"] == "simulated"
        assert c["receipt"]["actual_cost_cents"] == 0.0

    # Inspect NemoFold Inter-Rater Reliability
    ev = result["evaluation"]
    assert ev["status"] == "evaluated"
    assert ev["schema"] == "nemofold.interrater.v1"
    assert ev["evaluated_pairs_count"] == 1
    assert ev["overall_agreement_percent"] is not None
    assert ev["overall_agreement_percent"] > 0

    pairwise = ev["pairwise"][0]
    assert pairwise["rater_a"] == "synthetic_fixture_a"
    assert pairwise["rater_b"] == "synthetic_fixture_b"
    assert pairwise["items_compared"] > 0
    assert pairwise["cohens_kappa"] is not None or pairwise["kappa_note"] != ""

    # Winner exists
    assert result["winner"] in {"synthetic_fixture_a", "synthetic_fixture_b"}


@pytest.mark.asyncio
async def test_execute_race_paid_unauthorized_blocks_cleanly(isolated_service: CompareRaceService):
    """Paid lanes without SpendAuthority return 'unavailable' and 0 cost, never simulating success."""
    prompt = "Erstelle ein Budgetkonzept für 2027."
    result = await isolated_service.execute_race(
        prompt=prompt,
        lane_ids=["claude", "gpt"],
        spend_auth=None,  # No authorization
        synthetic_fixtures=False,
    )

    assert result["total_candidates"] == 2
    assert result["unavailable_count"] == 2
    assert result["live_count"] == 0

    for c in result["candidates"]:
        assert c["evidence_kind"] == "unavailable"
        assert c["status"] in {"blocked", "missing_credentials"}
        assert c["response"] == ""
        assert c["score"] == 0.0
        assert c["receipt"]["actual_cost_cents"] == 0.0
        assert "SpendAuthority" in c["receipt"]["error"] or "Key" in c["receipt"]["error"]

    # No winner when all candidates are unavailable
    assert result["winner"] is None


@pytest.mark.asyncio
async def test_compare_race_history(isolated_service: CompareRaceService):
    """Completed runs are persisted and retrievable via get_history()."""
    await isolated_service.execute_race(
        prompt="Test Run 1",
        lane_ids=["synthetic_fixture_a", "synthetic_fixture_b"],
        synthetic_fixtures=True,
    )
    await isolated_service.execute_race(
        prompt="Test Run 2",
        lane_ids=["synthetic_fixture_a", "synthetic_fixture_b"],
        synthetic_fixtures=True,
    )

    history = isolated_service.get_history(limit=10)
    assert len(history) == 2
    assert history[0]["prompt"] == "Test Run 2"
    assert history[1]["prompt"] == "Test Run 1"


def test_unified_api_compare_race_endpoints(tmp_path, monkeypatch):
    """Verify FastAPI routes for compare-race lanes, history, and Buddha evaluation."""
    monkeypatch.setenv(
        "BACH_COMPARE_RACE_HISTORY_PATH", str(tmp_path / "api_race_history.json")
    )
    from gui.server import app

    client = TestClient(
        app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False
    )

    # 1. Lanes discovery
    lanes_resp = client.get("/api/chat/buddha/compare-race/lanes")
    assert lanes_resp.status_code == 200
    lanes_data = lanes_resp.json()
    assert "lanes" in lanes_data
    lane_ids = {lane["id"] for lane in lanes_data["lanes"]}
    assert "ollama" in lane_ids
    assert "claude" in lane_ids
    assert "synthetic_fixture_a" in lane_ids

    # 2. History listing
    hist_resp = client.get("/api/chat/buddha/compare-race/history")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert "runs" in hist_data

    # 3. Empty prompt validation
    err_resp = client.post("/api/chat/buddha/compare-race", json={"prompt": ""})
    assert err_resp.status_code == 400

    # 4. Successful execution with synthetic fixtures
    run_resp = client.post(
        "/api/chat/buddha/compare-race",
        json={
            "prompt": "Vergleiche Microservices vs. Monolith",
            "models": ["synthetic_fixture_a", "synthetic_fixture_b"],
            "synthetic_fixtures": True,
        },
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["prompt"] == "Vergleiche Microservices vs. Monolith"
    assert len(run_data["candidates"]) == 2
    assert run_data["candidates"][0]["evidence_kind"] == "simulated"
    assert run_data["evaluation"]["schema"] == "nemofold.interrater.v1"

    # 5. POST /api/chat/compare-race/buddha
    buddha_resp = client.post(
        "/api/chat/compare-race/buddha",
        json={
            "prompt": "Test Direkter Aufruf über Buddha Alias",
            "models": ["synthetic_fixture_a", "synthetic_fixture_b"],
            "synthetic_fixtures": True,
        },
    )
    assert buddha_resp.status_code == 200
    buddha_data = buddha_resp.json()
    assert buddha_data["synthetic_fixtures"] is True

    # 6. Authenticated POST /api/chat/compare-race with runner: "buddha"
    from unittest.mock import patch
    with patch("gui.server.validate_token", return_value={"id": 1, "name": "test-device"}), \
         patch("gui.api.unified_api._require_memory_device", return_value=1):
        delegated_resp = client.post(
            "/api/chat/compare-race",
            headers={"Authorization": "Bearer test-token"},
            json={
                "prompt": "Test Delegierung an Buddha Runner",
                "models": ["synthetic_fixture_a", "synthetic_fixture_b"],
                "runner": "buddha",
                "synthetic_fixtures": True,
            },
        )
        assert delegated_resp.status_code == 200
        delegated_data = delegated_resp.json()
        assert delegated_data["synthetic_fixtures"] is True
