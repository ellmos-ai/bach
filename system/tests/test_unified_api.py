# SPDX-License-Identifier: MIT
"""
Tests for Unified API Router (Tasks #1643 - #1648)
==================================================
Covers:
- Agent Studio: Blueprints, Materialization, Living & Running, Animus Matrix
- Capabilities Hub & Binding
- MarbleRun Chains, Execution, Agents-Map
- Governance: Locks, Decisions, Policies
- Deep Memory, KnowledgeDigest, Gardener Search, Compare-Race
- Domains & Software Discovery
- Artifacts: Listing, Safe Content View, Directory Traversal Protection
"""
import json
import sqlite3
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from gui.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_agent_studio_blueprints(client):
    # 1. List blueprints (should contain seeded templates)
    resp = client.get("/api/agent-studio/blueprints")
    assert resp.status_code == 200
    data = resp.json()
    assert "templates" in data
    assert "blueprints" in data
    assert data["total_templates"] >= 4
    template_names = [t["name"] for t in data["templates"]]
    assert "buddha" in template_names
    assert "wartungsagent" in template_names
    assert "claude_avatar" in template_names

    # 2. Create custom blueprint
    new_bp = {
        "name": "test_researcher",
        "title": "Test Researcher Agent",
        "description": "Custom agent for tests",
        "persona_role": "Lead Researcher",
        "persona_prompt": "Research carefully",
        "skills": ["think", "decide"],
        "animus_type": "api",
        "contractus": {"max_turns": 20},
        "modus": "trigger"
    }
    create_resp = client.post("/api/agent-studio/blueprints", json=new_bp)
    assert create_resp.status_code == 200
    assert create_resp.json()["success"] is True

    # 3. Read back
    resp2 = client.get("/api/agent-studio/blueprints")
    all_names = [b["name"] for b in resp2.json()["blueprints"] + resp2.json()["templates"]]
    assert "test_researcher" in all_names

    # 4. Materialize custom blueprint
    custom_item = next(b for b in resp2.json()["blueprints"] if b["name"] == "test_researcher")
    mat_resp = client.post(f"/api/agent-studio/blueprints/{custom_item['id']}/materialize")
    assert mat_resp.status_code == 200
    assert mat_resp.json()["success"] is True

    # 5. Delete custom blueprint
    del_resp = client.delete(f"/api/agent-studio/blueprints/{custom_item['id']}")
    assert del_resp.status_code == 200

    # 6. Deleting a template must fail with 403
    template_item = resp2.json()["templates"][0]
    del_template_resp = client.delete(f"/api/agent-studio/blueprints/{template_item['id']}")
    assert del_template_resp.status_code == 403


def test_living_agents(client):
    resp = client.get("/api/agent-studio/living")
    assert resp.status_code == 200
    data = resp.json()
    assert "living_agents" in data
    assert data["count"] > 0
    names = [a["name"] for a in data["living_agents"]]
    assert any("claude" in n for n in names)


def test_capabilities_hub(client):
    resp = client.get("/api/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "tools" in data
    assert "mcps" in data
    assert "skills_by_category" in data

    # Bind capability test
    bind_resp = client.post("/api/capabilities/bind", json={
        "agent_id": "buddha",
        "capabilities": ["think", "decide", "brainstorm"]
    })
    assert bind_resp.status_code == 200
    assert bind_resp.json()["success"] is True


def test_marblerun_chains_and_agents_map(client):
    # 1. Create a chain
    chain_data = {
        "name": "test_chain_workflow",
        "title": "Test Chain Pipeline",
        "description": "2-step pipeline test",
        "steps": [
            {"step_id": 1, "name": "Collect Input", "agent": "claude", "animus": "subscription"},
            {"step_id": 2, "name": "Summarize", "agent": "gemini", "animus": "subscription"}
        ]
    }
    create_resp = client.post("/api/marblerun/chains", json=chain_data)
    assert create_resp.status_code == 200
    assert create_resp.json()["steps_count"] == 2

    # 2. Get chains
    list_resp = client.get("/api/marblerun/chains")
    assert list_resp.status_code == 200
    chains = list_resp.json()["chains"]
    target = next((c for c in chains if c["name"] == "test_chain_workflow"), None)
    assert target is not None

    # 3. Run chain
    run_resp = client.post(f"/api/marblerun/chains/{target['id']}/run", json={"input": "Hello Chain"})
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["success"] is True
    assert run_data["steps_executed"] == 2

    # 4. Agents-Map graph
    map_resp = client.get("/api/marblerun/agents-map")
    assert map_resp.status_code == 200
    map_data = map_resp.json()
    assert "nodes" in map_data
    assert "links" in map_data
    assert map_data["stats"]["total_nodes"] > 0

    # 5. Clean up chain
    del_resp = client.delete(f"/api/marblerun/chains/{target['id']}")
    assert del_resp.status_code == 200


def test_governance_endpoints(client):
    # Status
    status_resp = client.get("/api/governance/status")
    assert status_resp.status_code == 200
    assert "policies" in status_resp.json()
    assert len(status_resp.json()["policies"]) >= 4

    # Locks
    locks_resp = client.get("/api/governance/locks")
    assert locks_resp.status_code == 200
    assert "locks" in locks_resp.json()

    # Decisions
    dec_resp = client.get("/api/governance/decisions")
    assert dec_resp.status_code == 200
    assert "decisions" in dec_resp.json()

    # Policies
    pol_resp = client.get("/api/governance/policies")
    assert pol_resp.status_code == 200
    assert pol_resp.json()["count"] == 7


def test_deep_memory_and_compare_race(client):
    # KnowledgeDigest
    kd_resp = client.get("/api/memory/knowledge-digest")
    assert kd_resp.status_code == 200
    assert "knowledge_folders" in kd_resp.json()

    # Gardener search
    gardener_resp = client.get("/api/gardener/search?q=architecture")
    assert gardener_resp.status_code == 200
    assert "results" in gardener_resp.json()

    # Compare-Race
    race_resp = client.post("/api/chat/compare-race", json={
        "prompt": "Explain quantum computing briefly",
        "models": ["claude", "gemini"]
    })
    assert race_resp.status_code == 200
    race_data = race_resp.json()
    assert "candidates" in race_data
    assert len(race_data["candidates"]) == 2
    assert "winner" in race_data


def test_domains(client):
    resp = client.get("/api/domains")
    assert resp.status_code == 200
    data = resp.json()
    assert "domains" in data
    assert "software_count" in data


def test_artifacts_and_security(client, tmp_path):
    # List artifacts
    resp = client.get("/api/artifacts")
    assert resp.status_code == 200
    assert "artifacts" in resp.json()

    # Path traversal attack must be blocked (HTTP 403 or 404)
    unsafe_resp = client.get("/api/artifacts/content?path=../../../../windows/system32/cmd.exe")
    assert unsafe_resp.status_code in (403, 404)

    # Sensitive pattern must be blocked
    token_resp = client.get("/api/artifacts/content?path=C:/Users/User/.bach/token.txt")
    assert token_resp.status_code in (403, 404)


def test_unified_ocean_dashboard_pages(client):
    # Test /ocean route
    ocean_resp = client.get("/ocean")
    assert ocean_resp.status_code == 200
    assert "BACH / OCEAN Unified Workstation" in ocean_resp.text

    # Test /unified route
    unified_resp = client.get("/unified")
    assert unified_resp.status_code == 200
    assert "Live Cluster Taskboard" in unified_resp.text
