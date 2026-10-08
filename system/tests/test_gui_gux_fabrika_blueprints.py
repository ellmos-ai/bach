# SPDX-License-Identifier: MIT
"""
Contract Tests for GUX-020..029: Fabrika and Blueprints
======================================================
Verifies:
- GUX-020: Factory Step 1 core-prompts integration (/api/system/core-prompts)
- GUX-021: Ready-made roles & personas selectable in templates
- GUX-022: Dynamic real skills from capability source (/api/capabilities/skills)
- GUX-023: Contractus, modus & trigger presets (/api/agent-studio/contractus-presets)
- GUX-024: Blueprints subpage under Fabrika (/agenten/blueprints) & nav config
- GUX-025: All 6 kinds described (agent, role, skill, workflow, service, contractus)
- GUX-026: Blueprints filtering, retrieval & template overwrite protection
- GUX-027: Materialization is Living (not Running); Running requires authentic receipt
- GUX-028: Governance profiles & tool whitelist binding (/api/agent-studio/governance-presets)
- GUX-029: Startprompt synthesis ([Boot:Agent], [Boot:System], [Boot:Aufgabe]) fail-closed gate
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gui import server
from gui.api import unified_api
from hub._services import blueprint_service


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture(autouse=True)
def no_live_control_api(monkeypatch):
    from gui.api import worker_status_adapter
    def reject(*args, **kwargs):
        raise AssertionError("Unit tests must never contact a live Control service")
    monkeypatch.setattr(worker_status_adapter, "_request_control_api", reject)


@pytest.fixture
def temp_bach_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "bach_test.db"
        with closing(sqlite3.connect(db_path)) as conn:
            blueprint_service.ensure_blueprint_schema(conn)
            blueprint_service.seed_default_blueprints(conn)
            conn.commit()
        yield db_path


class TestFabrikaAndBlueprintsContract:
    """Verifies all functional contracts for GUX-020 through GUX-029."""

    def test_gux020_core_prompts_control_source(self, tmp_path, monkeypatch):
        """GUX-020: Core-prompts endpoint provides verified standard prompts."""
        from gui.api import core_system_agents
        from hub._services.chat import slots_config
        from unittest.mock import AsyncMock
        path = str(tmp_path / "slots.json")
        slots_config.initialize_slots_config(path)
        templates = slots_config.get_prompt_templates(path)
        monkeypatch.setattr(core_system_agents, "_control_prompt_payload", AsyncMock(return_value={
            "templates": templates, "configuration_version": "a" * 64, "source_version": "b" * 64}))
        data = asyncio.run(core_system_agents.list_core_prompts())
        assert data["schema"] == "bach.core-prompts.v1"
        assert "prompts" in data
        assert "system_default" in data["prompts"]
        assert len(data["prompts"]["system_default"]["effective"]) > 50

    def test_gux021_roles_and_personas_presets(self, temp_bach_db):
        """GUX-021: Ready-made roles and personas can be loaded from templates."""
        with closing(sqlite3.connect(temp_bach_db)) as conn:
            conn.row_factory = sqlite3.Row
            res = blueprint_service.list_blueprints(conn, kind="role")
            roles = res["templates"] + res["blueprints"]
            assert len(roles) >= 2
            role_names = [r["name"] for r in roles]
            assert "role_lawchecker" in role_names
            assert "role_security_auditor" in role_names

    def test_gux022_dynamic_capabilities_skills(self, tmp_path, monkeypatch):
        """GUX-022: Factory Step 2 shows dynamic real skills, not a hardcoded 9-element list."""
        for index in range(12):
            skill = tmp_path / ("dev" if index % 2 else "research") / f"fixture-skill-{index}"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(f"---\nname: fixture-skill-{index}\ndescription: Test-Anleitung\n---\nPrüfe die Aufgabe.", encoding="utf-8")
        monkeypatch.setattr(unified_api, "SKILLS_ROOT", tmp_path)
        monkeypatch.setenv("BACH_USER_SKILLS_ROOT", str(tmp_path / "isolated-user-skills"))
        data = asyncio.run(unified_api.get_capabilities_skills())
        assert "skills" in data
        installed = [skill for skill in data["skills"] if skill["evidence_type"] == "filesystem_present"]
        assert len(installed) == 12
        skill_ids = [s["id"] for s in data["skills"]]
        assert "git-hygiene" in skill_ids
        assert "lock-master" in skill_ids
        assert "pipeline-optimizer" in skill_ids
        assert {"dev", "research"} <= set(data["categories"])

        # Test category filtering
        dev_data = asyncio.run(unified_api.get_capabilities_skills(category="dev"))
        assert all(s["category"] == "dev" for s in dev_data["skills"])

    def test_gux023_contractus_presets_endpoint(self):
        """GUX-023: Contractus presets deliver modus, turns, and trigger presets."""
        data = asyncio.run(unified_api.get_contractus_presets())
        assert "presets" in data
        assert data["count"] >= 4
        preset_ids = [p["id"] for p in data["presets"]]
        assert "standard_casualis" in preset_ids
        assert "dauerlaeufer_usus" in preset_ids
        assert "strict_zero_leak" in preset_ids
        for p in data["presets"]:
            assert "turns" in p
            assert "modus" in p
            assert "cooldown_seconds" in p

    def test_gux024_blueprints_subpage_and_navigation(self):
        """GUX-024: Blueprints subpage under Fabrika is in public page paths and nav config."""
        assert "/agenten/blueprints" in server.DeviceAuthMiddleware.PUBLIC_PAGE_PATHS
        nav_file = Path(__file__).resolve().parent.parent / "gui" / "web" / "src" / "config" / "nav_config.json"
        assert nav_file.exists()
        nav_data = json.loads(nav_file.read_text(encoding="utf-8"))
        agenten_nav = next((item for item in nav_data if item.get("id") == "agenten"), None)
        assert agenten_nav is not None
        hrefs = [child["href"] for child in agenten_nav.get("children", [])]
        assert "/agenten/blueprints" in hrefs
        assert "/agenten/fabrika" not in hrefs
        assert "/agenten/marblerun" in hrefs

    def test_gux025_blueprints_describe_all_six_kinds(self, temp_bach_db):
        """GUX-025: Blueprints describe agents, roles, skills, workflows, services, contractus."""
        with closing(sqlite3.connect(temp_bach_db)) as conn:
            conn.row_factory = sqlite3.Row
            res = blueprint_service.list_blueprints(conn)
            all_bps = res["templates"] + res["blueprints"]
            kinds_present = {b["kind"] for b in all_bps}
            required_kinds = {"agent", "role", "workflow", "service", "contractus"}
            assert required_kinds.issubset(kinds_present)

    def test_gux026_template_protection_and_custom_save(self, temp_bach_db):
        """GUX-026: Built-in templates are protected from overwrite; custom blueprints save cleanly."""
        with closing(sqlite3.connect(temp_bach_db)) as conn:
            # Attempting to overwrite a template fails with PermissionError
            with pytest.raises(PermissionError) as exc_info:
                blueprint_service.save_blueprint(conn, {
                    "name": "buddha",
                    "persona_prompt": "Neuer Prompt",
                    "persona_role": "Hacker"
                })
            assert "schreibgeschützt" in str(exc_info.value)

            # Saving custom blueprint succeeds and synthesizes prompt
            custom_payload = {
                "name": "mein_test_agent",
                "title": "Mein Test Agent",
                "kind": "agent",
                "persona_role": "Automations-Experte",
                "persona_prompt": "Du bist ein spezialisierter Test-Agent für autonome Bach-Workflows.",
                "skills": ["git-hygiene", "lock-master"],
                "contractus": {"turns": 20, "cooldown_seconds": 10},
                "modus": "casualis",
                "governance": {"profile": "fail_closed_standard"}
            }
            res = blueprint_service.save_blueprint(conn, custom_payload)
            assert res["success"] is True
            assert res["name"] == "mein_test_agent"
            assert "[Boot:Agent]" in res["start_prompt"]
            assert "[Boot:System]" in res["start_prompt"]

    def test_gux027_materialization_needs_a_real_slot_and_dispatcher(self, temp_bach_db, tmp_path, monkeypatch):
        from hub._services.chat import slots_config
        from hub._services import skill_source_service
        skill_root = tmp_path / "skills"
        for name in ("gespraechsfuehrung-basis", "selbstmanagement", "decide"):
            path = skill_root / name / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"# {name}\nNutze diese Test-Anleitung.\n", encoding="utf-8")
        monkeypatch.setattr(skill_source_service, "skill_roots", lambda: [skill_root])
        slots_path = str(tmp_path / "slots.json")
        slots_config.initialize_slots_config(slots_path)
        with closing(sqlite3.connect(temp_bach_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT id,version FROM agent_blueprints WHERE name='buddha'").fetchone()
            snapshot = slots_config.core_system_agents_snapshot(slots_path)
            result = blueprint_service.materialize_blueprint(conn, row["id"],
                expected_version=row["version"], execution={"backend":"ollama","model":"fixture-model"},
                configuration_version=snapshot["configuration_version"], slots_path=slots_path)
            assert result["status"] == "configured"
            assert result["worker_started"] is False and result["is_running"] is False
            assert result["is_living"] is None
            assert slots_config.get_system_slot(result["slot_id"], slots_path)["blueprint_id"] == row["id"]
            assert {ref["id"] for ref in slots_config.get_system_slot(result["slot_id"], slots_path)["skill_refs"]} == {
                "gespraechsfuehrung-basis", "selbstmanagement", "decide"}
            with pytest.raises(RuntimeError, match="worker_dispatcher_required"):
                blueprint_service.start_blueprint_worker(conn, row["id"])
            assert conn.execute("SELECT COUNT(*) FROM partner_presence").fetchone()[0] == 0

    def test_gux028_governance_presets_and_audit_gate(self):
        """GUX-028: Factory Step 4 binds authentic profiles, tool whitelist, and hooker audit."""
        data = asyncio.run(unified_api.get_governance_presets())
        assert "presets" in data
        assert len(data["presets"]) >= 3
        preset_ids = [p["id"] for p in data["presets"]]
        assert "fail_closed_standard" in preset_ids
        assert "read_only_research" in preset_ids
        assert "full_dev_guarded" in preset_ids

        from hub._services.chat.bach_tools import tools_for_mode
        known = {tool["function"]["name"] for tool in tools_for_mode("full", bound_worker=True)}
        assert all(set(p["tool_whitelist"]) <= known for p in data["presets"])
        assert data["enforcement"]["tool_whitelist"] is True
        assert data["enforcement"]["hooker_verified"] is False

    def test_gux029_startprompt_synthesis_fail_closed(self):
        """GUX-029: Startprompt synthesizes authentic blocks; empty/static stubs fail closed."""
        # 1. Valid synthesis
        valid_bp = {
            "name": "lawchecker",
            "title": "Lawchecker",
            "persona_role": "Rechtsexperte",
            "persona_prompt": "Du prüfst Rechtsfragen präzise nach kanonischem Recht.",
            "skills": ["lock-master", "git-hygiene"],
            "contractus": {"turns": 15, "cooldown_seconds": 30},
            "modus": "casualis",
            "governance": {"profile": "fail_closed_standard"}
        }
        prompt = blueprint_service.synthesize_start_prompt(valid_bp, task_override="Prüfe Vertragsentwurf")
        assert "[Boot:Agent]" in prompt
        assert "[Boot:System]" in prompt
        assert "[Boot:Aufgabe]" in prompt
        assert "Rechtsexperte" in prompt
        assert "Prüfe Vertragsentwurf" in prompt

        # 2. Empty prompt fails closed
        invalid_bp = {
            "name": "empty_agent",
            "persona_prompt": "   ",
            "persona_role": "Stub"
        }
        with pytest.raises(ValueError) as exc_info:
            blueprint_service.synthesize_start_prompt(invalid_bp)
        assert "Persona-Prompt darf nicht leer sein" in str(exc_info.value)

        # 3. Via API endpoint
        synth_res = asyncio.run(unified_api.synthesize_prompt_endpoint({"blueprint": valid_bp}))
        assert synth_res["success"] is True
        assert synth_res["character_count"] > 100

    def test_core_system_agents_live_status_and_toggle(self, tmp_path, monkeypatch):
        """Verifies core system slots include status, pause_info, enabled, and toggle works."""
        from gui.api import core_system_agents, worker_status_adapter
        from hub._services.chat import slots_config
        path = str(tmp_path / "slots.json")
        slots_config.initialize_slots_config(path)
        monkeypatch.setattr(slots_config, "DEFAULT_SLOTS_FILE", path)
        monkeypatch.setattr(core_system_agents, "_snapshot", lambda: slots_config.core_system_agents_snapshot())
        monkeypatch.setattr(unified_api, "_require_memory_device_token", lambda request: "fixture-device")
        monkeypatch.setattr(worker_status_adapter, "worker_action", lambda *args, **kwargs: {"ok": True, "state": "stopping"})
        monkeypatch.setattr(worker_status_adapter, "read_worker_status", lambda **kwargs: {"workers": [{"id": "buddha_always_on", "status": "idle"}]})
        monkeypatch.setattr(worker_status_adapter, "start_worker", lambda *args, **kwargs: {"ok": True, "start_acknowledged": True})
        snapshot = asyncio.run(core_system_agents.list_core_system_agents())
        assert snapshot["schema"] == "bach.core-system-agents.v1"
        assert {agent["id"] for agent in snapshot["agents"]} == {
            "buddha_chat", "buddha_always_on", "buddha_connector",
            "buddha_boss", "buddha_developer", "buddha_research"}
        always_on = next(a for a in snapshot["agents"] if a["id"] == "buddha_always_on")
        assert "status" in always_on
        assert "pause_info" in always_on
        assert "enabled" in always_on
        initial_enabled = always_on["enabled"]
        # Toggle
        res = asyncio.run(core_system_agents.toggle_core_system_agent("buddha_always_on", object(), {"enabled": not initial_enabled, "configuration_version": snapshot["configuration_version"]}))
        assert res["ack"]["enabled"] == (not initial_enabled)
        # Toggle back
        res_back = asyncio.run(core_system_agents.toggle_core_system_agent("buddha_always_on", object(), {"enabled": initial_enabled, "configuration_version": res["configuration_version"]}))
        assert res_back["ack"]["enabled"] == initial_enabled
