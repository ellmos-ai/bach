"""Real stored teams, additive migrations and compare-and-swap editing."""
import asyncio
import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from gui.api import unified_api as api
from hub._services import blueprint_service as service


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "studio.db"
    with sqlite3.connect(path) as conn:
        service.seed_default_blueprints(conn)
    monkeypatch.setattr(api, "BACH_DB", path)
    return path


def payload(**changes):
    return {"name":"Mein Team","description":"Entwicklung und Prüfung","leader_agent":"buddha",
        "member_agents":"buddha, wartungsagent","strategy":"swarm_hierarchy","expected_version":0, **changes}


def test_empty_get_has_no_demo_teams_and_no_ddl(database):
    before = (database.stat().st_mtime_ns, hashlib.sha256(database.read_bytes()).hexdigest())
    result = asyncio.run(api.get_agent_teams())
    assert result["teams"] == [] and result["count"] == 0
    assert before == (database.stat().st_mtime_ns, hashlib.sha256(database.read_bytes()).hexdigest())
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='agent_teams'").fetchone() is None


def test_team_crud_requires_current_version_and_configured_members(database):
    saved = asyncio.run(api.create_agent_team(payload()))
    assert saved["version"] == 1 and saved["worker_started"] is False
    listed = asyncio.run(api.get_agent_teams())["teams"]
    assert listed[0]["name"] == "Mein Team" and listed[0]["leader_agent"] == "buddha"
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(api.update_agent_team(saved["id"], payload(description="stale")))
    assert conflict.value.status_code == 409
    updated = asyncio.run(api.update_agent_team(saved["id"], payload(description="Aktuell", expected_version=1)))
    assert updated["version"] == 2
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(api.delete_agent_team(saved["id"], expected_version=1))
    assert conflict.value.status_code == 409
    assert asyncio.run(api.delete_agent_team(saved["id"], expected_version=2))["success"]
    assert asyncio.run(api.get_agent_teams())["teams"] == []


@pytest.mark.parametrize("changes", [
    {"member_agents":"unknown", "leader_agent":"unknown"},
    {"member_agents":"buddha, buddha"},
    {"leader_agent":"unknown"},
    {"strategy":"invented"},
    {"expected_version": True},
    {"member_models":{"buddha":42}},
])
def test_invalid_teams_fail_without_a_row(database, changes):
    with pytest.raises(HTTPException):
        asyncio.run(api.create_agent_team(payload(**changes)))
    assert asyncio.run(api.get_agent_teams())["teams"] == []


def test_team_name_cannot_be_duplicated(database):
    asyncio.run(api.create_agent_team(payload()))
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(api.create_agent_team(payload()))
    assert conflict.value.status_code == 409
    assert len(asyncio.run(api.get_agent_teams())["teams"]) == 1


def test_ro_endpoint_does_not_create_a_missing_database(tmp_path, monkeypatch):
    path = tmp_path / "absent.db"
    monkeypatch.setattr(api,"BACH_DB",path)
    with pytest.raises(HTTPException) as unavailable:
        asyncio.run(api.get_agent_teams())
    assert unavailable.value.status_code == 503 and not path.exists()


def test_capability_binding_cannot_bypass_revisions_or_template_protection(database):
    with sqlite3.connect(database) as conn:
        custom = service.save_blueprint(conn, {"name":"custom","title":"Mein Agent","persona_prompt":"Prüfe die Aufgabe."})
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(api.bind_agent_capabilities({"agent_id":custom["id"],"capabilities":["readme"]}))
    assert conflict.value.status_code == 409
    saved = asyncio.run(api.bind_agent_capabilities({"agent_id":custom["id"],"capabilities":["readme"],"expected_version":1}))
    assert saved["version"] == 2
    with sqlite3.connect(database) as conn:
        template = conn.execute("SELECT id FROM agent_blueprints WHERE name='buddha'").fetchone()[0]
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(api.bind_agent_capabilities({"agent_id":template,"capabilities":[],"expected_version":1}))
    assert conflict.value.status_code == 409


def test_editing_members_preserves_models_for_remaining_members(database):
    saved = asyncio.run(api.create_agent_team(payload(member_models={"buddha":"configured-model","wartungsagent":"other-model"})))
    updated = asyncio.run(api.update_agent_team(saved["id"], payload(member_agents="buddha",expected_version=1)))
    assert updated["version"] == 2
    assert asyncio.run(api.get_agent_teams())["teams"][0]["member_models"] == {"buddha":"configured-model"}


def test_no_referenced_skills_does_not_scan_any_filesystem(monkeypatch):
    from hub._services import skill_capabilities_service
    class ForbiddenPath:
        def exists(self): raise AssertionError("Empty references must not trigger a directory scan")
    monkeypatch.setattr(skill_capabilities_service,"SKILLS_SEARCH_PATHS",[ForbiddenPath()])
    assert skill_capabilities_service.validate_blueprint_skills([])["valid"] is True


def test_legacy_model_editor_requires_a_revision_and_increments_it(database):
    saved = asyncio.run(api.create_agent_team(payload()))
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(api.beseelen_team(saved["id"], {"member_models":{"buddha":"requested-model"}}))
    assert conflict.value.status_code == 409
    result = asyncio.run(api.beseelen_team(saved["id"], {"expected_version":1,"member_models":{"buddha":"requested-model"}}))
    assert result["version"] == 2 and result["worker_started"] is False


def test_team_route_is_registered_once():
    routes=[route for route in api.router.routes if route.path=="/api/agenten/teams/{team_id}" and "DELETE" in route.methods]
    assert len(routes)==1
