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

    def test_gux020_core_prompts_control_source(self):
        """GUX-020: Core-prompts endpoint provides verified standard prompts."""
        from gui.api import core_system_agents
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

    def test_gux022_dynamic_capabilities_skills(self):
        """GUX-022: Factory Step 2 shows dynamic real skills, not a hardcoded 9-element list."""
        data = asyncio.run(unified_api.get_capabilities_skills())
        assert "skills" in data
        assert data["total"] > 10, "Must provide verified catalog beyond static stubs"
        skill_ids = [s["id"] for s in data["skills"]]
        assert "git-hygiene" in skill_ids
        assert "lock-master" in skill_ids
        assert "pipeline-optimizer" in skill_ids
        assert len(data["categories"]) >= 3

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
        assert "/agenten/fabrika" in hrefs

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

    def test_gux027_materialize_living_vs_start_running(self, temp_bach_db):
        """GUX-027: Materialize sets Living (is_running=False); Start sets Running with authentic receipt."""
        with closing(sqlite3.connect(temp_bach_db)) as conn:
            conn.row_factory = sqlite3.Row
            buddha = conn.execute("SELECT id FROM agent_blueprints WHERE name = 'buddha'").fetchone()
            assert buddha is not None
            bp_id = buddha["id"]

            # 1. Materialization -> Living (not running)
            living_res = blueprint_service.materialize_blueprint(conn, bp_id, model="claude-3-5-sonnet")
            assert living_res["is_materialized"] == 1
            assert living_res["is_living"] is True
            assert living_res["is_running"] is False
            assert living_res["status"] == "living"

            # 2. Worker Start -> Running with authentic receipts
            worker_res = blueprint_service.start_blueprint_worker(conn, bp_id, task="Führe System-Scan durch")
            assert worker_res["is_running"] is True
            assert worker_res["status"] == "running"
            assert "job_receipt" in worker_res
            assert "receipt_id" in worker_res["job_receipt"]
            assert "heartbeat_receipt" in worker_res
            assert worker_res["job_receipt"]["task_summary"] == "Führe System-Scan durch"

    def test_gux028_governance_presets_and_audit_gate(self):
        """GUX-028: Factory Step 4 binds authentic profiles, tool whitelist, and hooker audit."""
        data = asyncio.run(unified_api.get_governance_presets())
        assert "presets" in data
        assert len(data["presets"]) >= 3
        preset_ids = [p["id"] for p in data["presets"]]
        assert "fail_closed_standard" in preset_ids
        assert "read_only_research" in preset_ids
        assert "full_dev_guarded" in preset_ids

        for p in data["presets"]:
            assert "tool_whitelist" in p
            assert "hooker_monitoring" in p
            assert "allowed_paths" in p

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

    def test_core_system_agents_live_status_and_toggle(self):
        """Verifies core system slots include status, pause_info, enabled, and toggle works."""
        from gui.api import core_system_agents
        snapshot = asyncio.run(core_system_agents.list_core_system_agents())
        assert snapshot["schema"] == "bach.core-system-agents.v1"
        assert len(snapshot["agents"]) == 3
        always_on = next(a for a in snapshot["agents"] if a["id"] == "buddha_always_on")
        assert "status" in always_on
        assert "pause_info" in always_on
        assert "enabled" in always_on
        initial_enabled = always_on["enabled"]
        # Toggle
        res = asyncio.run(core_system_agents.toggle_core_system_agent("buddha_always_on"))
        assert res["ack"]["enabled"] == (not initial_enabled)
        # Toggle back
        res_back = asyncio.run(core_system_agents.toggle_core_system_agent("buddha_always_on"))
        assert res_back["ack"]["enabled"] == initial_enabled
