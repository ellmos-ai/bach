# coding: utf-8
"""Dünner BACH-Adapter für .MODULES/.CONTROL/learning-loop (Skill-Gärtner / Skill Keeper, #2455)."""
from __future__ import annotations
import importlib.util
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[3] / ".MODULES/.CONTROL/learning-loop/skill_keeper.py"
_spec = importlib.util.spec_from_file_location("ocean_control_skill_keeper", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)

REQUIRED_HOUSE_FIELDS = _mod.REQUIRED_HOUSE_FIELDS
collect_skill_candidates_job = _mod.collect_skill_candidates_job
elaborate_candidate_with_skill_gaertner = _mod.elaborate_candidate_with_skill_gaertner
validate_skill_creator_house_format = _mod.validate_skill_creator_house_format

API_ROUTES = {
    "canonical": "/api/learning/skill-keeper/candidates",
    "legacy_alias": "/api/learning/hermes/candidates",
    "chat_backend_hermes_preserved": True,
    "ui_location": "Skills & Software › Skill Keeper",
}
