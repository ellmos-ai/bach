from hub._services.persona_routing import (
    list_persona_catalog,
    resolve_persona_route,
)

def test_only_two_default_active_system_agents_and_legacy_in_library():
    cat = list_persona_catalog()
    active_ids = [a["id"] for a in cat["active_system_agents"]]
    assert active_ids == ["coordinator", "expert"]
    assert all(a["active_by_default"] is True for a in cat["active_system_agents"])
    assert all(t["is_template"] is True and t["active_by_default"] is False for t in cat["library_templates"])

def test_persona_routing_falls_back_to_system_expert_unless_template_enabled():
    r1 = resolve_persona_route("Bitte prüfe meinen Förderplan nach ICF")
    assert r1["selected_agent"] == "expert"
    assert r1["recommended_template"] == "paedagogik"

    r2 = resolve_persona_route("Bitte prüfe meinen Förderplan nach ICF", enabled_templates={"paedagogik"})
    assert r2["selected_agent"] == "paedagogik"

    r3 = resolve_persona_route("Wie ist der Gesamtstatus heute?")
    assert r3["selected_agent"] == "coordinator"
