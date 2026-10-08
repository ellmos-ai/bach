# SPDX-License-Identifier: MIT
"""
Tests for Modular Board Renderers (Phase 2.3)
=============================================

Validiert die modulare Auslieferung und das Branding der Board-Templates:
  - Agents Board (render_agents_board)
  - Tasks Board (render_tasks_board)
  - JavaScript-Vertrag (skills-board.js & api.js)
  - Server-Endpunkte (/agents-board, /skills-board, /tasks-board)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from gui.board_renderers import (
    DEFAULT_AGENTS_BOARD_BRANDING,
    DEFAULT_TASKS_BOARD_BRANDING,
    get_agents_board_template,
    get_tasks_board_template,
    render_agents_board,
    render_tasks_board,
)


def test_default_agents_board_rendering():
    """Testet das Agents-Board mit Standardwerten."""
    assert DEFAULT_AGENTS_BOARD_BRANDING["brand_name"] == "BACH"
    html_out = render_agents_board()
    assert "<!DOCTYPE html>" in html_out
    assert "<title>BACH - Agents Board</title>" in html_out
    assert 'localStorage.getItem("bach-theme")' in html_out
    assert "window.BOARD_CONFIG" in html_out
    assert 'brandName: "BACH"' in html_out
    assert 'tokenStorageKey: "bach-token"' in html_out
    assert "<h2>Agents Board</h2>" in html_out
    assert '<span class="icon">🎯</span>' in html_out
    assert 'src="/static/js/skills-board.js"' in html_out


def test_custom_agents_board_rendering():
    """Testet das Agents-Board mit benutzerdefiniertem Branding."""
    custom_branding = {
        "title": "OCEAN - Agents Hub",
        "brand_name": "OCEAN",
        "brand_icon": "🌊",
        "header_title": "OCEAN Global Agents",
        "theme_storage_key": "ocean-theme",
        "token_storage_key": "ocean-token",
        "theme_colors": {"accent": "#00e5ff", "bg-card": "#0d1b2a"},
        "nav_links": [
            {"label": "OCEAN Home", "href": "/ocean/home", "target": "_self"}
        ],
    }
    html_out = render_agents_board(branding=custom_branding, api_base="/gateway/control-api")
    assert "<title>OCEAN - Agents Hub</title>" in html_out
    assert 'localStorage.getItem("ocean-theme")' in html_out
    assert 'brandName: "OCEAN"' in html_out
    assert 'tokenStorageKey: "ocean-token"' in html_out
    assert 'apiBase: "/gateway/control-api"' in html_out
    assert "<h2>OCEAN Global Agents</h2>" in html_out
    assert '<span class="icon">🌊</span>' in html_out
    assert "--accent: #00e5ff;" in html_out
    assert "--bg-card: #0d1b2a;" in html_out
    assert 'href="/ocean/home"' in html_out
    assert "OCEAN Home" in html_out
    assert "const THEME_KEY = BOARD_CONFIG.themeStorageKey || 'bach-theme';" in (
        SYSTEM_ROOT / "gui" / "static" / "js" / "nav.js"
    ).read_text(encoding="utf-8")


def test_default_tasks_board_rendering():
    """Testet das Tasks-Board mit Standardwerten."""
    assert DEFAULT_TASKS_BOARD_BRANDING["brand_name"] == "BACH"
    html_out = render_tasks_board()
    assert "<!DOCTYPE html>" in html_out
    assert "<title>BACH - Tasks Board</title>" in html_out
    assert 'localStorage.getItem("bach-theme")' in html_out
    assert "window.BOARD_CONFIG" in html_out
    assert 'brandName: "BACH"' in html_out
    assert 'tokenStorageKey: "bach-token"' in html_out
    assert "<h1>Task Management Board</h1>" in html_out
    assert 'src="/static/js/api.js"' in html_out


def test_custom_tasks_board_rendering():
    """Testet das Tasks-Board mit benutzerdefiniertem Branding & statischem Pfad."""
    custom_branding = {
        "title": "Unified GUI - Tasks",
        "brand_name": "Unified",
        "header_title": "Agile Kanban Board",
        "theme_storage_key": "unified-theme",
        "token_storage_key": "unified-token",
        "static_base": "/custom_assets",
        "theme_colors": {"primary": "#3a86ff"},
        "nav_links": [
            {"label": "Back to Panels", "href": "/panels", "class": "btn btn-back"}
        ],
    }
    html_out = render_tasks_board(branding=custom_branding, api_base="/remote/api")
    assert "<title>Unified GUI - Tasks</title>" in html_out
    assert 'localStorage.getItem("unified-theme")' in html_out
    assert 'brandName: "Unified"' in html_out
    assert 'tokenStorageKey: "unified-token"' in html_out
    assert 'apiBase: "/remote/api"' in html_out
    assert "<h1>Agile Kanban Board</h1>" in html_out
    assert "--primary: #3a86ff;" in html_out
    assert 'src="/custom_assets/js/api.js"' in html_out
    assert 'href="/panels"' in html_out
    assert "Back to Panels" in html_out


def test_board_rendering_escapes_branding_and_script_values():
    html_out = render_agents_board(
        branding={
            "brand_icon": '<img src=x onerror="alert(1)">',
            "brand_name": "</script><script>window.__review_probe=1</script>",
            "api_base": "</script><script>window.__review_probe=1</script>",
            "theme_colors": {
                "valid-name": "#123456",
                "bad;name": "red",
                "probe": "</style><script>window.__review_probe=1</script>",
            },
        }
    )
    assert '<span class="icon">&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</span>' in html_out
    assert "</script><script>window.__review_probe" not in html_out
    assert "\\u003c/script>" in html_out
    assert "--valid-name: #123456;" in html_out


def test_empty_navigation_list_removes_board_header():
    html_out = render_agents_board(branding={"nav_links": []})
    assert '<header class="main-header" id="main-header"></header>' not in html_out
    assert "BACH v" not in html_out


def test_theme_helpers_use_board_configuration():
    nav_js = (SYSTEM_ROOT / "gui" / "static" / "js" / "nav.js").read_text(
        encoding="utf-8"
    )
    assert "const THEME_KEY = BOARD_CONFIG.themeStorageKey || 'bach-theme';" in nav_js
    assert "fetch(themeSettingsUrl()" in nav_js
    assert "`${apiBase}/settings/theme`" in nav_js


def test_template_missing_errors():
    """Prüft, dass FileNotFoundError geworfen wird, wenn Templates fehlen."""
    with (
        patch("gui.board_renderers.AGENTS_BOARD_TEMPLATE_PATH", Path("/tmp/nonexistent_agents.html")),
        pytest.raises(FileNotFoundError),
    ):
        get_agents_board_template()

    with (
        patch("gui.board_renderers.TASKS_BOARD_TEMPLATE_PATH", Path("/tmp/nonexistent_tasks.html")),
        pytest.raises(FileNotFoundError),
    ):
        get_tasks_board_template()


def test_skills_board_js_contract():
    """Prüft, dass skills-board.js API-Base und Auth-Header unterstützt."""
    js_path = SYSTEM_ROOT / "gui" / "static" / "js" / "skills-board.js"
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")
    assert "function getSkillsBoardApiUrl(" in content
    assert "function getSkillsBoardHeaders(" in content
    assert "getSkillsBoardApiUrl('/api/skills-board/hierarchy')" in content
    assert "getSkillsBoardApiUrl('/api/skills-board/item-file')" in content


def test_api_js_contract():
    """Prüft, dass api.js window.BOARD_CONFIG und Bearer-Auth unterstützt."""
    js_path = SYSTEM_ROOT / "gui" / "static" / "js" / "api.js"
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")
    assert "window.BOARD_CONFIG" in content
    assert "_headers(" in content
    assert "Authorization" in content
    assert "Bearer" in content


def test_fastapi_board_endpoints(tmp_path, monkeypatch):
    """Prüft die FastAPI-Routen /agents-board, /skills-board und /tasks-board."""
    from gui.server import app
    from starlette.testclient import TestClient

    from gui import server as server_module
    monkeypatch.setattr(server_module, "ASTRO_DIST_DIR", tmp_path / "absent-dist")
    client = TestClient(app)

    resp_agents = client.get("/agents-board", follow_redirects=False)
    assert resp_agents.status_code == 307
    assert resp_agents.headers["location"] == "/agenten/blueprints"

    resp_skills = client.get("/skills-board", follow_redirects=False)
    assert resp_skills.status_code == 307
    assert resp_skills.headers["location"] == "/skills"

    resp_tasks = client.get("/tasks-board")
    assert resp_tasks.status_code == 200
    assert "<title>BACH - Tasks Board</title>" in resp_tasks.text
    assert "window.BOARD_CONFIG" in resp_tasks.text


def test_deprecated_skills_board_never_renders_legacy_template(tmp_path, monkeypatch):
    from gui import board_renderers
    from gui import server as server_module
    from starlette.testclient import TestClient

    (tmp_path / "skills-board.html").write_text(
        get_agents_board_template(), encoding="utf-8"
    )
    monkeypatch.setattr(server_module, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(
        board_renderers,
        "render_agents_board",
        lambda: (_ for _ in ()).throw(RuntimeError("renderer unavailable")),
    )
    response = TestClient(server_module.app).get("/skills-board", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/skills"
    assert "window.BOARD_CONFIG" not in response.text


def test_board_rendering_failure_does_not_serve_unresolved_template(
    tmp_path, monkeypatch
):
    from gui import board_renderers
    from gui import server as server_module
    from starlette.testclient import TestClient

    (tmp_path / "tasks_board.html").write_text(
        get_tasks_board_template(), encoding="utf-8"
    )
    monkeypatch.setattr(server_module, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(server_module, "ASTRO_DIST_DIR", tmp_path / "absent-dist")
    monkeypatch.setattr(
        board_renderers,
        "render_tasks_board",
        lambda: (_ for _ in ()).throw(RuntimeError("renderer unavailable")),
    )
    monkeypatch.setattr(
        board_renderers,
        "_apply_common_replacements",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fallback failed")),
    )
    response = TestClient(server_module.app).get("/tasks-board")
    assert response.status_code == 500
