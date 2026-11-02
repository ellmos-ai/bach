from hub._services.module_delivery_lifecycle import ModuleDeliveryCatalog, ORIGIN_REMOVED_BADGE
from gui.api.module_delivery_projection import project_module_library_and_routines


def test_gui_projection_for_roles_and_maintenance_classes_and_removed_origin():
    cat = ModuleDeliveryCatalog()
    cat.install_or_update_module({
        "id": "ellmos-skill-creator",
        "version": "1.0.0",
        "roles": [{"id": "skill-gaertner", "label": "Skill-Gärtner", "default_access": "cli"}],
        "maintenance": [
            {"id": "drift-job", "label": "Drift-Scan", "class": "job", "trigger": "@daily", "requires_model": False, "difficulty": "low", "requirements": ["python3"]},
            {"id": "dedup-rec", "label": "Dedup-Review", "class": "agent-recommended", "trigger": "@weekly", "requires_model": True, "difficulty": "medium", "requirements": ["git"]},
            {"id": "import-req", "label": "Skill-Übersetzung", "class": "agent-required", "trigger": "@weekly", "requires_model": True, "difficulty": "high", "requirements": ["llm"]},
        ],
    })
    cat.instantiate_agent("ellmos-skill-creator:skill-gaertner", "inst-1")
    cat.schedule_maintenance("ellmos-skill-creator:dedup-rec", execution_mode="job")

    vm = project_module_library_and_routines(cat)
    assert len(vm["agent_library"]) == 1
    assert vm["agent_library"][0]["actions"] == ["Agent anlegen", "In Werkstatt öffnen"]
    by_id = {r["id"]: r for r in vm["routines"]}
    assert by_id["drift-job"]["execution_options"] == ["job"]
    assert by_id["dedup-rec"]["execution_options"] == ["job", "agent"]
    assert by_id["dedup-rec"]["selected_execution_mode"] == "job"
    assert by_id["import-req"]["execution_options"] == ["agent"]

    cat.uninstall_module("ellmos-skill-creator")
    vm_after = project_module_library_and_routines(cat)
    assert vm_after["agent_library"] == []
    assert vm_after["agent_instances"][0]["origin_badge"] == ORIGIN_REMOVED_BADGE
    assert vm_after["routines"][0]["origin_badge"] == ORIGIN_REMOVED_BADGE
