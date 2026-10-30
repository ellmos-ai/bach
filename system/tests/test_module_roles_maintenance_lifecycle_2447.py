from hub._services.module_delivery_lifecycle import (
    ORIGIN_REMOVED_BADGE,
    ModuleDeliveryCatalog,
    validate_module_delivery_manifest,
)

def test_manifest_validation_and_uninstall_lifecycle():
    manifest = {
        "id": "ellmos-skill-creator",
        "version": "1.2.0",
        "roles": [
            {
                "id": "skill-gaertner",
                "label": "Skill-Gärtner",
                "default_access": "cli",
                "skills": ["skill-family-care"],
            }
        ],
        "maintenance": [
            {
                "id": "skill-index-refresh",
                "label": "Skill-Register prüfen",
                "class": "job",
                "trigger": "0 4 * * *",
                "role": None,
                "requires_model": False,
                "difficulty": "low",
                "requirements": ["python3"],
            },
            {
                "id": "skill-dedup-audit",
                "label": "Skill-Duplikate zusammenführen",
                "class": "agent-recommended",
                "trigger": "0 5 * * 0",
                "role": "skill-gaertner",
                "requires_model": True,
                "difficulty": "medium",
                "requirements": ["git", "llm"],
            },
        ],
    }
    assert validate_module_delivery_manifest(manifest) == []

    cat = ModuleDeliveryCatalog()
    cat.install_or_update_module(manifest)
    assert "ellmos-skill-creator:skill-gaertner" in cat.role_templates
    assert cat.role_templates["ellmos-skill-creator:skill-gaertner"]["active"] is False

    inst = cat.instantiate_agent("ellmos-skill-creator:skill-gaertner", "my-gardener")
    sched = cat.schedule_maintenance("ellmos-skill-creator:skill-dedup-audit")
    assert inst["origin_removed"] is False
    assert sched["active"] is True

    res = cat.uninstall_module("ellmos-skill-creator")
    assert "ellmos-skill-creator:skill-gaertner" not in cat.role_templates
    assert res["marked_instances"] == ["my-gardener"]
    assert cat.agent_instances["my-gardener"]["origin_removed"] is True
    assert cat.agent_instances["my-gardener"]["origin_badge"] == ORIGIN_REMOVED_BADGE
    assert cat.scheduled_maintenance["ellmos-skill-creator:skill-dedup-audit"]["origin_badge"] == ORIGIN_REMOVED_BADGE

def test_job_cannot_require_model():
    bad = {
        "id": "mod-a",
        "roles": [],
        "maintenance": [
            {
                "id": "bad-job",
                "label": "Fehlkonfigurierter Job",
                "class": "job",
                "trigger": "@daily",
                "requires_model": True,
                "difficulty": "low",
                "requirements": [],
            }
        ],
    }
    errs = validate_module_delivery_manifest(bad)
    assert any("class=job" in e for e in errs)
