from hub._services.skill_keeper_service import (
    API_ROUTES,
    collect_skill_candidates_job,
    elaborate_candidate_with_skill_gaertner,
    validate_skill_creator_house_format,
)


def test_skill_keeper_job_and_gaertner_elaboration_follow_house_rules():
    raw = collect_skill_candidates_job([{"name": "PDF Prüfbericht", "description": "Prüft PDFs", "category": "dev"}])
    assert len(raw) == 1
    assert raw[0]["status"] == "collected_raw"

    doc = elaborate_candidate_with_skill_gaertner(raw[0], agent_role="skill-gaertner")
    assert validate_skill_creator_house_format(doc) == []
    assert doc["visibility"] == "private-only"
    assert doc["languages"] == ["de", "en"]
    assert API_ROUTES["ui_location"] == "Skills & Software › Skill Keeper"
    assert API_ROUTES["chat_backend_hermes_preserved"] is True
