# SPDX-License-Identifier: MIT
"""Unit tests for Cognitive Architecture (Baddeley & SDT) and Capabilities Hub endpoints."""

import pytest
from fastapi.testclient import TestClient
import sys
import sqlite3
from pathlib import Path

# Add system directory to path
SYS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYS_DIR))
sys.path.insert(0, str(SYS_DIR / "gui"))

from gui.server import app
from gui import device_auth
from gui.device_auth import _hash_token, init_devices_db

client = TestClient(app)
TOKEN = "test-only-cognitive-gui-token-20261003"
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def setup_device_auth(tmp_path, monkeypatch):
    db_path = tmp_path / "devices.db"

    def get_test_connection():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(device_auth, "GET_CONNECTION", get_test_connection)
    conn = get_test_connection()
    init_devices_db(conn)
    token_hash = _hash_token(TOKEN)
    conn.execute(
        "INSERT OR REPLACE INTO devices (name, token_hash, status) VALUES ('asus-gei', ?, 'active')",
        (token_hash,)
    )
    conn.commit()
    conn.close()


def test_cognitive_memory_state():
    """Validates the full cognitive state based on Baddeley, Norman & Shallice (SAS), TOTE and Kahneman."""
    res = client.get("/api/memory/cognitive-state", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert "zentrale_exekutive" in data
    assert "phonologische_schleife" in data
    assert "startprompt" in data
    assert "hooker_governance" in data
    assert "disambiguierung_knoten" in data
    assert "schaltplan_flow" in data
    assert "visueller_notizblock" in data
    assert "episodischer_puffer" in data
    assert "prozedurales_gedaechtnis" in data
    assert "langzeit_gedaechtnis" in data
    assert "kognitives_lernsystem" in data

    # Verify Startprompt Formula & Agent decomposition
    sp = data["startprompt"]
    assert "Agent" in sp["formula"]
    assert "Systemprompt" in sp["formula"]
    assert "Aufgabenprompt" in sp["formula"]
    assert "Governance" in sp["agent_formula"]

    # The diagram is conceptual; this endpoint does not attest runtime guards.
    hg = data["hooker_governance"]
    assert hg["status"] == "Nicht geprüft"
    assert len(hg["safety_rules"]) >= 3
    assert len(hg["channels"]) >= 4

    # Verify Disambiguation Node: Stress, Accomodation & Safety Signals
    dis = data["disambiguierung_knoten"]
    assert "psychology" in dis
    assert "pathways" in dis
    assert "internal_self_awareness" in dis["pathways"]
    assert "external_context_detection" in dis["pathways"]

    # Verify Circuit Flow Signals
    flow = data["schaltplan_flow"]
    assert len(flow["signals"]) >= 10

    # Verify Central Executive: SAS & TOTE
    ze = data["zentrale_exekutive"]
    assert "models" in ze
    assert "sas" in ze["models"]
    assert "tote" in ze["models"]
    assert "kahneman" in ze["models"]
    assert len(ze["metaskills"]) > 0

    # Verify Phonological Loop: Active Context Window & 5 Hooker Trigger Types
    pl = data["phonologische_schleife"]
    assert "hooker_injectors" in pl
    triggers = pl["hooker_injectors"]["triggers"]
    assert len(triggers) == 5
    trigger_names = [t["name"] for t in triggers]
    assert "Lifecycle-Trigger" in trigger_names
    assert "Sicherheits-Guard" in trigger_names
    assert "Lern-Injektor" in trigger_names

    # Verify Visuospatial Sketchpad
    vsp = data["visueller_notizblock"]
    assert "spatial_reasoning" in vsp

    # Verify Long-Term Memory Pillars
    lzg = data["langzeit_gedaechtnis"]
    assert "facts" in lzg
    assert "lessons" in lzg
    assert "working" in lzg
    assert "sessions" in lzg

    # Verify Cognitive Learning Loop
    learn = data["kognitives_lernsystem"]
    assert "dual_success_axes" in learn
    assert "user_success" in learn["dual_success_axes"]
    assert "task_success" in learn["dual_success_axes"]


def test_memory_tables_crud():
    """Tests the real SQLite CRUD endpoints for facts, lessons, working memory and sessions."""
    # 1. Facts
    f_res = client.get("/api/memory/facts", headers=AUTH_HEADER)
    assert f_res.status_code == 200
    assert "facts" in f_res.json()

    create_f = client.post("/api/memory/facts", headers=AUTH_HEADER, json={
        "category": "pytest",
        "key": "test_fact_key",
        "value": "Cognitive Architecture Verified"
    })
    assert create_f.status_code == 200
    assert create_f.json()["status"] == "created"

    # 2. Lessons
    l_res = client.get("/api/memory/lessons", headers=AUTH_HEADER)
    assert l_res.status_code == 200
    assert "lessons" in l_res.json()

    create_l = client.post("/api/memory/lessons", headers=AUTH_HEADER, json={
        "category": "best_practice",
        "title": "Pytest Cognitive Lesson",
        "solution": "Always couple phonological loop to central executive"
    })
    assert create_l.status_code == 200
    assert create_l.json()["status"] == "created"

    # 3. Working Memory
    w_res = client.get("/api/memory/working", headers=AUTH_HEADER)
    assert w_res.status_code == 200
    assert "working" in w_res.json()

    create_w = client.post("/api/memory/working", headers=AUTH_HEADER, json={
        "content": "Active scratchpad test item",
        "type": "scratchpad"
    })
    assert create_w.status_code == 200
    assert create_w.json()["status"] == "created"

    # 4. Sessions
    s_res = client.get("/api/memory/sessions", headers=AUTH_HEADER)
    assert s_res.status_code == 200
    assert "sessions" in s_res.json()



def test_capabilities_steckdosen():
    """Validates the plugin power strip (Steckdosenleiste) and plug toggle."""
    res = client.get("/api/capabilities/steckdosen", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert "sockets" in data
    assert len(data["sockets"]) >= 4

    # Test toggling the first socket
    target_plugin = data["sockets"][0]["name"]
    initial_plugged = data["sockets"][0]["is_plugged"]

    toggle_res = client.post(
        "/api/capabilities/plugins/toggle",
        headers=AUTH_HEADER,
        json={"name": target_plugin}
    )
    assert toggle_res.status_code == 200
    toggle_data = toggle_res.json()
    assert toggle_data["is_plugged"] != initial_plugged

    # Toggle back to restore
    toggle_back = client.post(
        "/api/capabilities/plugins/toggle",
        headers=AUTH_HEADER,
        json={"name": target_plugin}
    )
    assert toggle_back.status_code == 200
    assert toggle_back.json()["is_plugged"] == initial_plugged


def test_mcp_cookbooks():
    """Validates the MCP Cookbooks (Tool books with ingredients and recipes)."""
    res = client.get("/api/capabilities/mcp/cookbooks", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert "cookbooks" in data
    assert len(data["cookbooks"]) >= 3
    first_book = data["cookbooks"][0]
    assert "ingredients" in first_book
    assert "recipes" in first_book


def test_capabilities_tiers_and_versioning():
    """Tests the 4 tiers and SentinelFleet versioning / rollback."""
    res = client.get("/api/capabilities/tiers", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert "tiers" in data
    assert len(data["tiers"]) == 4

    # Test version creation
    ver_res = client.post(
        "/api/capabilities/skills/version",
        headers=AUTH_HEADER,
        json={
            "skill_name": "test-persona-skill",
            "version": "v1.2.0",
            "changelog": "Test commit",
            "author": "pytest",
            "content": "You are a test agent"
        }
    )
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["status"] == "success"
    assert ver_data["version"] == "v1.2.0"

    # Test rollback
    roll_res = client.post(
        "/api/capabilities/skills/rollback",
        headers=AUTH_HEADER,
        json={
            "skill_name": "test-persona-skill",
            "target_version": "v1.2.0"
        }
    )
    assert roll_res.status_code == 200
    assert roll_res.json()["status"] == "success"


def test_agent_studio_governance():
    """Validates governance presets and blueprint governance binding in Agent Studio."""
    # 1. Governance Presets
    presets_res = client.get("/api/agent-studio/governance-presets", headers=AUTH_HEADER)
    assert presets_res.status_code == 200
    p_data = presets_res.json()
    assert "presets" in p_data
    assert len(p_data["presets"]) >= 3
    preset_ids = [p["id"] for p in p_data["presets"]]
    assert "fail_closed_standard" in preset_ids

    # 2. Save Blueprint with Governance
    bp_res = client.post(
        "/api/agent-studio/blueprints",
        headers=AUTH_HEADER,
        json={
            "name": "governed_test_agent",
            "title": "Governed Test Agent",
            "description": "Test Agent with strict governance binding",
            "persona_role": "Security Guard",
            "persona_prompt": "You are a guarded agent",
            "skills": ["git-hygiene", "lock-master"],
            "governance": {
                "profile": "fail_closed_standard",
                "tool_whitelist": ["read_files", "search_content"],
                "tool_blacklist": ["git_push"],
                "hooker_auditing": True
            }
        }
    )
    assert bp_res.status_code == 200

    # 3. Read back Blueprint and check governance
    list_res = client.get("/api/agent-studio/blueprints", headers=AUTH_HEADER)
    assert list_res.status_code == 200
    bps = list_res.json()["blueprints"]
    found = [b for b in bps if b["name"] == "governed_test_agent"]
    assert len(found) == 1
    assert "governance" in found[0]
    assert found[0]["governance"]["profile"] == "fail_closed_standard"
    assert "git_push" in found[0]["governance"]["tool_blacklist"]
