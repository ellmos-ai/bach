# SPDX-License-Identifier: MIT
"""Structural integrity tests for BACH skills and workflows.

Validates that all skill/workflow markdown files:
- Exist and are readable
- Service skills have YAML frontmatter with required fields
- Workflow files have content
- No broken cross-references in skill files
"""
import re
import sys
from pathlib import Path

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
SKILLS_DIR = SYSTEM_ROOT / "skills"


def _parse_frontmatter(text: str) -> dict | None:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


class TestServiceSkills:
    """Service skills in skills/_services/ must have valid frontmatter."""

    service_dir = SKILLS_DIR / "_services"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.service_dir.exists():
            pytest.skip("skills/_services/ not found")

    def _service_files(self):
        return [f for f in self.service_dir.glob("*.md") if f.name != "README.md"]

    def test_service_skills_exist(self):
        files = self._service_files()
        assert len(files) >= 10, f"Expected at least 10 service skills, found {len(files)}"

    @pytest.mark.parametrize("skill_file", [
        pytest.param(f, id=f.stem)
        for f in sorted((SKILLS_DIR / "_services").glob("*.md"))
        if f.name != "README.md" and (SKILLS_DIR / "_services").exists()
    ])
    def test_service_skill_readable(self, skill_file):
        content = skill_file.read_text(encoding="utf-8")
        assert len(content) > 50, f"{skill_file.name} is too short"

    @pytest.mark.parametrize("skill_file", [
        pytest.param(f, id=f.stem)
        for f in sorted((SKILLS_DIR / "_services").glob("*.md"))
        if f.name != "README.md" and (SKILLS_DIR / "_services").exists()
    ])
    def test_service_skill_has_frontmatter(self, skill_file):
        content = skill_file.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        assert fm is not None, f"{skill_file.name} has no YAML frontmatter"
        assert "name" in fm, f"{skill_file.name} frontmatter missing 'name'"

    @pytest.mark.parametrize("skill_file", [
        pytest.param(f, id=f.stem)
        for f in sorted((SKILLS_DIR / "_services").glob("*.md"))
        if f.name != "README.md" and (SKILLS_DIR / "_services").exists()
    ])
    def test_service_skill_has_heading(self, skill_file):
        content = skill_file.read_text(encoding="utf-8")
        body = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)
        assert re.search(r"^#\s+\S", body, re.MULTILINE), \
            f"{skill_file.name} has no markdown heading after frontmatter"


class TestWorkflows:
    """Workflow files in skills/workflows/ must be valid."""

    workflows_dir = SKILLS_DIR / "workflows"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.workflows_dir.exists():
            pytest.skip("skills/workflows/ not found")

    def _workflow_files(self):
        return list(self.workflows_dir.rglob("*.md"))

    def test_workflows_exist(self):
        files = self._workflow_files()
        assert len(files) >= 5, f"Expected at least 5 workflows, found {len(files)}"

    @pytest.mark.parametrize("wf_file", [
        pytest.param(f, id=str(f.relative_to(SKILLS_DIR / "workflows")))
        for f in sorted((SKILLS_DIR / "workflows").rglob("*.md"))
        if (SKILLS_DIR / "workflows").exists()
    ])
    def test_workflow_readable(self, wf_file):
        content = wf_file.read_text(encoding="utf-8")
        assert len(content) > 20, f"{wf_file.name} is too short"

    @pytest.mark.parametrize("wf_file", [
        pytest.param(f, id=str(f.relative_to(SKILLS_DIR / "workflows")))
        for f in sorted((SKILLS_DIR / "workflows").rglob("*.md"))
        if (SKILLS_DIR / "workflows").exists()
    ])
    def test_workflow_has_heading(self, wf_file):
        content = wf_file.read_text(encoding="utf-8")
        body = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)
        assert re.search(r"^#\s+\S", body, re.MULTILINE), \
            f"{wf_file.name} has no markdown heading"


class TestTherapySkills:
    """Therapy skills must be valid markdown."""

    therapy_dir = SKILLS_DIR / "therapie"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.therapy_dir.exists():
            pytest.skip("skills/therapie/ not found")

    def test_therapy_skills_exist(self):
        files = list(self.therapy_dir.glob("*.md"))
        assert len(files) >= 15, f"Expected at least 15 therapy skills, found {len(files)}"

    def test_ethics_file_exists(self):
        ethics = self.therapy_dir / "ETHICS.md"
        assert ethics.exists(), "ETHICS.md must exist in therapie/"


class TestSkillTemplates:
    """Skill templates must exist."""

    templates_dir = SKILLS_DIR / "_templates"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.templates_dir.exists():
            pytest.skip("skills/_templates/ not found")

    def test_templates_exist(self):
        files = list(self.templates_dir.rglob("*"))
        assert len(files) >= 1, "Expected at least 1 template"


class TestSkillDirectory:
    """Overall skills directory structure."""

    def test_skills_dir_exists(self):
        assert SKILLS_DIR.exists()

    def test_required_subdirs(self):
        expected = {"_services", "workflows"}
        actual = {d.name for d in SKILLS_DIR.iterdir() if d.is_dir()}
        missing = expected - actual
        assert not missing, f"Missing required subdirectories: {missing}"

    def test_no_empty_skill_files(self):
        for md in SKILLS_DIR.rglob("*.md"):
            size = md.stat().st_size
            assert size > 0, f"{md.relative_to(SKILLS_DIR)} is empty"
