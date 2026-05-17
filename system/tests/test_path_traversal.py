# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""Regression tests for path traversal security fixes.

Tests cover:
- prompt_generator: get_template / get_template_raw
- GUI server: workflow-tuev/content, skills-board/item-file, auto-sessions/launch
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))


# ===========================================================================
# prompt_generator path traversal tests
# ===========================================================================

class TestPromptGeneratorPathTraversal:
    """Tests for path traversal in prompt_generator get_template methods."""

    def _get_generator(self):
        from hub._services.prompt_generator.prompt_generator import PromptGenerator
        return PromptGenerator()

    def test_get_template_blocks_parent_traversal(self):
        gen = self._get_generator()
        result = gen.get_template("../../etc/passwd")
        assert result is None

    def test_get_template_blocks_dotdot_deep(self):
        gen = self._get_generator()
        result = gen.get_template("../../../../../../../etc/shadow")
        assert result is None

    def test_get_template_blocks_absolute_path(self):
        gen = self._get_generator()
        result = gen.get_template("/etc/passwd")
        assert result is None

    def test_get_template_raw_blocks_parent_traversal(self):
        gen = self._get_generator()
        result = gen.get_template_raw("../../etc/passwd")
        assert result is None

    def test_get_template_raw_blocks_dotdot_deep(self):
        gen = self._get_generator()
        result = gen.get_template_raw("../../../../windows/system32/config/sam")
        assert result is None

    def test_get_template_allows_valid_subpath(self):
        gen = self._get_generator()
        result = gen.get_template("system/default")
        # Returns None if file doesn't exist, but does NOT raise or block

    def test_get_template_raw_allows_valid_subpath(self):
        gen = self._get_generator()
        result = gen.get_template_raw("system/default")
        # Returns None if file doesn't exist, not a security block


# ===========================================================================
# GUI server path traversal tests (using httpx TestClient)
# ===========================================================================

@pytest.fixture
def client():
    """FastAPI TestClient for the GUI server (synchronous)."""
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("starlette not available")

    from gui.server import app
    return TestClient(app, raise_server_exceptions=False)


def test_workflow_tuev_blocks_traversal(client):
    """GET /api/workflow-tuev/content with path traversal returns 403."""
    response = client.get("/api/workflow-tuev/content", params={"path": "../../etc/passwd"})
    assert response.status_code == 403


def test_workflow_tuev_blocks_encoded_traversal(client):
    """GET /api/workflow-tuev/content with URL-encoded backslash traversal returns 403."""
    response = client.get("/api/workflow-tuev/content", params={"path": "..%5C..%5Cetc%5Cpasswd"})
    assert response.status_code == 403


def test_workflow_tuev_allows_valid_path(client):
    """GET /api/workflow-tuev/content with valid path doesn't return 403."""
    response = client.get("/api/workflow-tuev/content", params={"path": "skills/example.py"})
    assert response.status_code != 403


def test_auto_sessions_blocks_invalid_id(client):
    """POST /api/auto-sessions/launch with injection characters returns error."""
    response = client.post("/api/auto-sessions/launch", json={"session_id": "../../../etc/passwd"})
    data = response.json()
    assert data.get("status") == "error"
    assert "Ungueltige" in data.get("message", "")


def test_auto_sessions_blocks_semicolons(client):
    """POST /api/auto-sessions/launch with shell metacharacters returns error."""
    response = client.post("/api/auto-sessions/launch", json={"session_id": "valid; rm -rf /"})
    data = response.json()
    assert data.get("status") == "error"


def test_auto_sessions_allows_valid_id(client):
    """POST /api/auto-sessions/launch with valid session_id pattern doesn't fail on regex."""
    response = client.post("/api/auto-sessions/launch", json={"session_id": "test-session_123"})
    data = response.json()
    if data.get("status") == "error":
        assert "Ungueltige" not in data.get("message", "")


def test_skills_board_item_file_blocks_traversal(client):
    """PUT /api/skills-board/item-file with path traversal returns 403."""
    response = client.put(
        "/api/skills-board/item-file",
        json={"path": "../../etc/passwd", "content": "malicious"}
    )
    assert response.status_code == 403


def test_skills_board_item_file_blocks_absolute_path(client):
    """PUT /api/skills-board/item-file with absolute outside path returns 403."""
    response = client.put(
        "/api/skills-board/item-file",
        json={"path": "/etc/shadow", "content": "malicious"}
    )
    assert response.status_code == 403


# ===========================================================================
# Discriminator tests: sibling-directory false-positive
# These tests verify that relative_to() correctly blocks access to sibling
# directories that share a common prefix -- the exact bug that startswith
# would miss (e.g. /templates_other passes startswith("/templates")).
# ===========================================================================

class TestSiblingDirectoryDiscriminator:
    """Prove relative_to() blocks sibling dirs that startswith would allow."""

    def test_prompt_generator_blocks_sibling_prefix(self, tmp_path, monkeypatch):
        """A path like 'templates_other/secret' must NOT pass validation.

        With startswith: str('/x/templates_other').startswith(str('/x/templates')) == True (BUG)
        With relative_to: '/x/templates_other'.relative_to('/x/templates') raises ValueError (CORRECT)
        """
        from hub._services.prompt_generator import prompt_generator as pg_mod

        real_templates = tmp_path / "templates"
        real_templates.mkdir()
        (real_templates / "valid.txt").write_text("ok")

        sibling = tmp_path / "templates_other"
        sibling.mkdir()
        (sibling / "secret.txt").write_text("leaked")

        monkeypatch.setattr(pg_mod, "TEMPLATES_DIR", real_templates)

        from hub._services.prompt_generator.prompt_generator import PromptGenerator
        gen = PromptGenerator()

        result = gen.get_template("../templates_other/secret")
        assert result is None, "Sibling directory with shared prefix must be blocked"

    def test_prompt_generator_raw_blocks_sibling_prefix(self, tmp_path, monkeypatch):
        """get_template_raw must also block sibling-prefix paths."""
        from hub._services.prompt_generator import prompt_generator as pg_mod

        real_templates = tmp_path / "templates"
        real_templates.mkdir()

        sibling = tmp_path / "templates_other"
        sibling.mkdir()
        (sibling / "secret.txt").write_text("leaked")

        monkeypatch.setattr(pg_mod, "TEMPLATES_DIR", real_templates)

        from hub._services.prompt_generator.prompt_generator import PromptGenerator
        gen = PromptGenerator()

        result = gen.get_template_raw("../templates_other/secret")
        assert result is None, "Sibling directory with shared prefix must be blocked"

    def test_workflow_tuev_blocks_sibling_prefix(self, client):
        """Workflow-TÜV content endpoint must block sibling-prefix paths.

        A path that resolves outside base but shares a string prefix
        (e.g. 'skills_malicious/..') must return 403.
        """
        response = client.get(
            "/api/workflow-tuev/content",
            params={"path": "../system_other/secret.py"}
        )
        assert response.status_code == 403

    def test_skills_board_blocks_sibling_prefix(self, client):
        """Skills-board item-file must block sibling-prefix paths."""
        response = client.put(
            "/api/skills-board/item-file",
            json={"path": "../system_other/secret.py", "content": "x"}
        )
        assert response.status_code == 403
