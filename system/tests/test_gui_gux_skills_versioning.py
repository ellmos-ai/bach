# SPDX-License-Identifier: MIT
"""Contract tests for Skills & Software, Prompt Library Import and Append-Only Versioning.

Covers:
- GUX-030: Dedicated top-level navigation area "Skills & Software" (id: 'skills')
- GUX-031: Blueprints and agents skill validation against authoritative registry
- GUX-063: MCP Cookbooks live discovery & verified clipboard copy
- GUX-064: Prompt-to-skill conversion following Creator Contract (YAML frontmatter, v1.0.0, provenance)
- GUX-065: Append-only versioning and restore (new INSERT with <version>_restore_<timestamp>)
- GUX-066: External artifacts discovery & fail-closed import into prompt_templates
- CAP-01/02: Steckdosen discovery & toggle
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui import server
from hub._services.skill_capabilities_service import (
    convert_prompt_to_skill,
    detect_external_artifacts,
    get_capabilities_tiers,
    get_mcp_cookbooks,
    get_plugin_sockets,
    import_external_artifact,
    restore_skill_version,
    save_skill_version,
    toggle_plugin_socket,
    validate_blueprint_skills,
)


@pytest.fixture
def test_db(tmp_path):
    """Provides a fresh SQLite connection with capabilities tables."""
    db_file = tmp_path / "test_capabilities.db"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def auth_client(monkeypatch):
    """FastAPI TestClient with bypassed device authentication for contract testing."""
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "gui-test-token" else None)
    return TestClient(
        server.app,
        raise_server_exceptions=True,
        headers={"Authorization": "Bearer gui-test-token"}
    )


def test_gux_030_nav_config_skills_area():
    """GUX-030: Skills & Software must have dedicated area 'skills' and not be under 'agenten'."""
    nav_file = SYSTEM_ROOT / "gui" / "web" / "src" / "config" / "nav_config.json"
    assert nav_file.exists(), f"nav_config.json not found at {nav_file}"

    with open(nav_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # nav_config.json is a list of area objects
    areas = {a["id"]: a for a in data if isinstance(a, dict) and "id" in a}

    assert "skills" in areas, "Navigation area 'skills' must exist"
    skills_area = areas["skills"]
    assert skills_area.get("label") == "Skills & Software"
    assert skills_area.get("icon") == "🔌"

    children = skills_area.get("children", [])
    child_hrefs = [c.get("href") for c in children if isinstance(c, dict)]
    assert "/skills" in child_hrefs, "/skills must be under area 'skills'"
    assert "/agents-board" in child_hrefs, "/agents-board must be under area 'skills'"

    agenten_area = areas.get("agenten", {})
    agenten_child_hrefs = [c.get("href") for c in agenten_area.get("children", []) if isinstance(c, dict)]
    assert "/skills" not in agenten_child_hrefs, "/skills must NOT be under 'agenten'"
    assert "/agents-board" not in agenten_child_hrefs, "/agents-board must NOT be under 'agenten'"


def test_gux_031_blueprint_skills_validation():
    """GUX-031: Blueprint skills must be validated against the authoritative registry."""
    # Test valid skills (should match real skills on system)
    val_res = validate_blueprint_skills(["pipeline-optimizer", "git-hygiene"])
    assert val_res.get("valid") is True
    assert val_res.get("total_referenced") == 2
    assert "matched" in val_res
    matched_ids = [m["id"] for m in val_res["matched"]]
    assert "pipeline-optimizer" in matched_ids
    assert "git-hygiene" in matched_ids

    # Test unknown/missing skill
    fake_skill = "nonexistent-super-custom-skill-404"
    val_res_invalid = validate_blueprint_skills([fake_skill])
    assert val_res_invalid["valid"] is False
    assert fake_skill in val_res_invalid["missing"]


def test_gux_063_mcp_cookbooks_discovery():
    """GUX-063: MCP Cookbooks must support live discovery from disk."""
    cookbooks_res = get_mcp_cookbooks()
    assert cookbooks_res.get("live_discovery") is True
    assert cookbooks_res.get("count", 0) > 0
    cookbooks = cookbooks_res.get("cookbooks", [])
    assert len(cookbooks) > 0

    first = cookbooks[0]
    assert "id" in first
    assert "title" in first
    assert "recipes" in first
    assert len(first["recipes"]) > 0


def test_gux_064_prompt_to_skill_conversion(test_db):
    """GUX-064: Prompt-to-Skill conversion following Creator Contract."""
    prompt_text = "Analysiere den gegebenen Code und generiere strukturierte Unit-Tests mit Pytest."
    res = convert_prompt_to_skill(
        conn=test_db,
        prompt_text=prompt_text,
        title="Pytest Test Generator",
        category="dev",
        author="test-engineer"
    )

    assert res.get("success") is True
    skill_name = res["skill_name"]
    assert skill_name == "pytest-test-generator"
    assert res["version"] == "v1.0.0"

    skill_content = res["skill_md"]
    assert skill_content.startswith("---")
    assert "name: pytest-test-generator" in skill_content
    assert "category: dev" in skill_content
    assert "description: Pytest Test Generator" in skill_content

    # Check skill_versions row
    row = test_db.execute(
        "SELECT * FROM skill_versions WHERE skill_name = ? AND version = 'v1.0.0'",
        (skill_name,)
    ).fetchone()
    assert row is not None
    assert row["author"] == "test-engineer"
    assert "Initial conversion from prompt" in row["changelog"]


def test_gux_065_append_only_restore(test_db):
    """GUX-065: Reversible Append-Only Restore of skill versions."""
    skill_name = "test-workflow-skill"

    # Save initial version v1.0.0
    v1 = save_skill_version(
        conn=test_db,
        skill_name=skill_name,
        version="v1.0.0",
        changelog="Initial release",
        author="dev1",
        content="Version 1 content"
    )
    assert v1["status"] == "success"

    # Save upgraded version v1.1.0
    v2 = save_skill_version(
        conn=test_db,
        skill_name=skill_name,
        version="v1.1.0",
        changelog="Added features",
        author="dev2",
        content="Version 2 content"
    )
    assert v2["status"] == "success"

    # Perform restore to v1.0.0
    restore_res = restore_skill_version(
        conn=test_db,
        skill_name=skill_name,
        target_version="v1.0.0"
    )
    assert restore_res["status"] == "success"
    assert restore_res["restored_from"] == "v1.0.0"
    new_version_tag = restore_res["active_version"]
    assert "restore" in new_version_tag

    # Verify append-only invariant: 3 total rows exist now, historical rows unchanged
    rows = test_db.execute(
        "SELECT * FROM skill_versions WHERE skill_name = ? ORDER BY id ASC",
        (skill_name,)
    ).fetchall()
    assert len(rows) == 3

    assert rows[0]["version"] == "v1.0.0"
    assert rows[0]["content"] == "Version 1 content"
    assert rows[1]["version"] == "v1.1.0"
    assert rows[1]["content"] == "Version 2 content"

    # Restored row has exact v1 content
    assert rows[2]["version"] == new_version_tag
    assert rows[2]["content"] == "Version 1 content"
    assert "Restored from version v1.0.0" in rows[2]["changelog"]

    # Verify error on non-existent version
    with pytest.raises(ValueError, match="nicht gefunden"):
        restore_skill_version(test_db, skill_name, "v99.9.9")


def test_gux_066_external_artifacts_discovery_and_import(test_db):
    """GUX-066: Discovery and fail-closed import of external artifacts."""
    artifacts = detect_external_artifacts()
    assert "profiprompt" in artifacts
    assert "promptboard" in artifacts
    assert "explorerpro" in artifacts

    # Test import of each discovered artifact
    for art_key in ["profiprompt", "promptboard", "explorerpro"]:
        art_info = artifacts[art_key]
        if art_info.get("detected"):
            res = import_external_artifact(art_key, test_db)
            assert res["status"] == "success"
            assert res["imported_count"] > 0
            assert res["total_existing"] >= res["imported_count"]

    # Invariant: unknown artifact must raise ValueError
    with pytest.raises(ValueError, match="nicht auf dem System gefunden oder nicht importierbar"):
        import_external_artifact("nonexistent-tool", test_db)


def test_cap_01_02_steckdosen_discovery_and_toggle(test_db):
    """CAP-01/02: Steckdosenleiste discovery and state toggle."""
    res = get_plugin_sockets(test_db)
    sockets = res.get("sockets", [])
    assert len(sockets) > 0
    socket = sockets[0]
    assert "name" in socket
    assert "is_plugged" in socket

    # Toggle socket state
    s_name = socket["name"]
    initial_plugged = socket["is_plugged"]
    toggle_res = toggle_plugin_socket(s_name, test_db)
    assert toggle_res["name"] == s_name
    assert toggle_res["is_plugged"] is not initial_plugged


def test_capabilities_tiers(test_db):
    """Verify 4 cognitive tiers categorization."""
    tiers_res = get_capabilities_tiers(test_db)
    assert "tiers" in tiers_res
    assert len(tiers_res["tiers"]) == 4

    tier_ids = [t["id"] for t in tiers_res["tiers"]]
    assert "executive" in tier_ids
    assert "process" in tier_ids
    assert "service" in tier_ids
    assert "capabilities" in tier_ids

    total_skills = sum(len(t["skills"]) for t in tiers_res["tiers"])
    assert total_skills > 0


def test_unified_api_routes(auth_client):
    """Test unified API endpoints via FastAPI TestClient."""
    # Steckdosen
    r = auth_client.get("/api/capabilities/steckdosen")
    assert r.status_code == 200, f"Failed with {r.status_code}: {r.text}"
    data = r.json()
    assert "sockets" in data

    # MCP Cookbooks
    r = auth_client.get("/api/capabilities/mcp/cookbooks")
    assert r.status_code == 200, f"Failed with {r.status_code}: {r.text}"
    assert r.json().get("live_discovery") is True

    # Tiers
    r = auth_client.get("/api/capabilities/tiers")
    assert r.status_code == 200, f"Failed with {r.status_code}: {r.text}"
    assert len(r.json().get("tiers", [])) == 4

    # External Artifacts
    r = auth_client.get("/api/system/external-artifacts")
    assert r.status_code == 200, f"Failed with {r.status_code}: {r.text}"
    assert "profiprompt" in r.json()

    # Blueprints skills validation endpoint
    r = auth_client.post("/api/capabilities/blueprints/validate-skills", json={"skills": ["git-hygiene", "unknown-xyz"]})
    assert r.status_code == 200, f"Failed with {r.status_code}: {r.text}"
    val = r.json()
    assert "unknown-xyz" in val.get("missing", [])
