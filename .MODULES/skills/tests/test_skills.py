# -*- coding: utf-8 -*-
from pathlib import Path
import importlib.util
import sys
import pytest

src_file = Path(__file__).parent.parent / "src" / "skills.py"
spec = importlib.util.spec_from_file_location("standalone_skills_mod", src_file)
skills_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = skills_mod
spec.loader.exec_module(skills_mod)
SkillRegistry = skills_mod.SkillRegistry
SkillMetadata = skills_mod.SkillMetadata


def test_skill_registry_basic():
    reg = SkillRegistry()
    skill = SkillMetadata(
        name="test-skill",
        version="1.2.0",
        category="testing",
        tags=["pytest", "unit"],
        description="A test skill"
    )
    assert reg.register_skill(skill) is True
    assert reg.get_skill("test-skill") is not None
    assert reg.get_skill("test-skill").version == "1.2.0"


def test_skill_markdown_parsing(tmp_path):
    skill_file = tmp_path / "SKILL.md"
    content = """---
name: my-modular-skill
version: 2.0.0
category: dev
tags: [python, modular]
description: A modular skill
---
# Guide
This is the skill instructions.
"""
    skill_file.write_text(content, encoding="utf-8")
    reg = SkillRegistry()
    ok, meta = reg.parse_skill_markdown(skill_file)
    assert ok is True
    assert meta["name"] == "my-modular-skill"
    assert meta["version"] == "2.0.0"
    assert meta["category"] == "dev"
    assert "python" in meta["tags"]
    assert "This is the skill instructions." in meta["body"]


def test_skill_discovery_and_search(tmp_path):
    s1 = tmp_path / "sub1" / "SKILL.md"
    s1.parent.mkdir()
    s1.write_text("---\nname: alpha-skill\ncategory: tools\ntags: [fast]\n---\nBody", encoding="utf-8")

    s2 = tmp_path / "sub2" / "SKILL.md"
    s2.parent.mkdir()
    s2.write_text("---\nname: beta-skill\ncategory: core\ntags: [slow]\n---\nBody", encoding="utf-8")

    reg = SkillRegistry()
    discovered = reg.discover_skills(tmp_path)
    assert len(discovered) == 2

    res_tools = reg.list_skills(category="tools")
    assert len(res_tools) == 1
    assert res_tools[0].name == "alpha-skill"

    searched = reg.search_skills("alpha")
    assert len(searched) == 1
    assert searched[0].name == "alpha-skill"

    assert reg.disable_skill("alpha-skill") is True
    assert len(reg.list_skills(enabled_only=True)) == 1
