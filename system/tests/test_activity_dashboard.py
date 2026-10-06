# SPDX-License-Identifier: MIT
"""
Tests für das Activity- & Worker-Dashboard (Phase 2.2)
======================================================
Prüft Modularisierung, Branding-Substitutionslogik,
HTML-Struktur und Inline-JavaScript-Validität.
"""

import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import pytest

SYSTEM_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SYSTEM_ROOT.parent
for p in (str(SYSTEM_ROOT), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from gui.activity_dashboard import (
        DEFAULT_BRANDING,
        TEMPLATE_PATH,
        get_activity_dashboard_template,
        render_activity_dashboard,
    )
except ImportError:
    from system.gui.activity_dashboard import (
        DEFAULT_BRANDING,
        TEMPLATE_PATH,
        get_activity_dashboard_template,
        render_activity_dashboard,
    )

try:
    import lxml.html
    LXML_AVAILABLE = True
except ImportError:
    LXML_AVAILABLE = False


def test_template_file_exists():
    """Das HTML-Template muss physisch im templates-Ordner existieren."""
    assert TEMPLATE_PATH.exists()
    assert TEMPLATE_PATH.is_file()
    raw = get_activity_dashboard_template()
    assert len(raw) > 1000
    assert "<!DOCTYPE html>" in raw
    assert "</html>" in raw


def test_default_rendering():
    """Standard-Rendering muss die BACH-Vorgaben und Buddhistische Slots einhalten."""
    assert DEFAULT_BRANDING["brand_name"] == "BACH"
    content = render_activity_dashboard()
    assert "<title>BACH Aktivitätsanzeige &amp; Worker Dashboard</title>" in content
    assert "<h1><span>🤖</span> BACH Aktivitätsanzeige &amp; Worker Dashboard</h1>" in content
    assert "Buddha Chat" in content
    assert "Buddha Always-On" in content
    assert "Buddha Connector" in content
    assert "Chat-Control" in content
    assert "GUI :8000" in content
    assert "bach-control-api-token" in content
    assert "location.origin + '/api'" in content


def test_custom_branding():
    """Benutzerdefiniertes Branding muss Platzhalter sauber ersetzen und escapen."""
    custom_branding = {
        "title": "ELLMOS Control Deck <v2>",
        "brand_name": "ELLMOS",
        "brand_icon": "🧭",
        "header_title": "Worker Cockpit",
        "subtitle": "Echtzeit-Steuerung & Modell-Orchestrierung",
        "slot_chat_title": "Core Assistant",
        "slot_always_on_title": "Daemon Watcher",
        "slot_connector_title": "Gateway Link",
    }
    content = render_activity_dashboard(branding=custom_branding)

    assert "<title>ELLMOS Control Deck &lt;v2&gt;</title>" in content
    assert "<span>🧭</span> ELLMOS Worker Cockpit" in content
    assert "Echtzeit-Steuerung &amp; Modell-Orchestrierung" in content
    assert "Core Assistant" in content
    assert "Daemon Watcher" in content
    assert "Gateway Link" in content
    # Die alten Buddhistischen Standard-Titel dürfen in den Slot-Headern nicht mehr auftauchen
    assert '<div class="card-title"><span>💬</span> Buddha Chat</div>' not in content


def test_custom_api_base():
    """API-Base URL muss im Client-JS gesetzt werden."""
    content = render_activity_dashboard(api_base="/custom/api/v2")
    assert "/custom/api/v2" in content

    # Auch über das branding-Dict
    content2 = render_activity_dashboard(branding={"api_base": "/gateway/control-api"})
    assert "/gateway/control-api" in content2
    assert "_rawApiBase.endsWith('/api')" in content2
    assert "_rawApiBase.replace(/\\/+$/, '') + '/api'" in content2


def test_script_values_are_json_encoded_and_brand_icon_is_escaped():
    payload = "</script><script>window.__review_probe=1</script>"
    content = render_activity_dashboard(
        branding={
            "token_storage_key": payload,
            "brand_icon": f'<img src=x onerror="alert(1)">{payload}',
            "slot_always_on_title": "A&B",
        }
    )
    assert payload not in content
    assert "\\u003c/script\\u003e" in content
    assert '<span>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in content
    assert '"alwaysOnTitle": "A\\u0026B"' in content
    with pytest.raises(ValueError):
        render_activity_dashboard(branding={"api_base": payload})


def test_custom_nav_links():
    """Navigationslinks müssen dynamisch konfigurierbar sein."""
    links = [
        {"label": "Zurück zum Hub", "href": "/hub"},
        {"label": "Dokumentation", "href": "https://docs.example.com", "target": "_blank"},
    ]
    content = render_activity_dashboard(branding={"nav_links": links})

    assert '<a href="/hub" class="btn btn-outline btn-sm">Zurück zum Hub</a>' in content
    assert '<a href="https://docs.example.com" target="_blank" rel="noopener noreferrer" class="btn btn-outline btn-sm">Dokumentation</a>' in content
    # Standard-Links sollten nicht mehr im Header enthalten sein
    assert '<a href="/" class="btn btn-outline btn-sm">Chat-Control</a>' not in content


def test_custom_theme_colors():
    """CSS-Theme-Variablen müssen als :root Block injiziert werden."""
    theme = {
        "accent": "#6366f1",
        "--bg-body": "#0b0f19",
        "btn-primary": "#4f46e5",
    }
    content = render_activity_dashboard(branding={"theme_colors": theme})

    assert ":root {" in content
    assert "--accent: #6366f1;" in content
    assert "--bg-body: #0b0f19;" in content
    assert "--btn-primary: #4f46e5;" in content
    assert ".card{background:var(--bg-card" in content
    assert "input,select,textarea{background:var(--bg-input" in content
    assert ".btn{background:var(--btn-primary" in content


def test_theme_css_rejects_invalid_names_and_values():
    with pytest.raises(ValueError):
        render_activity_dashboard(
            branding={
                "theme_colors": {
                    "accent": "#123456",
                    "bad}:name": "red",
                }
            }
        )
    with pytest.raises(ValueError):
        render_activity_dashboard(
            branding={"theme_colors": {"probe": "</style><script>bad</script>"}}
        )


def test_custom_token_storage_key():
    """LocalStorage-Schlüssel für Control-Token muss konfigurierbar sein."""
    content = render_activity_dashboard(branding={"token_storage_key": "ellmos-admin-token"})
    assert '"tokenStorageKey": "ellmos-admin-token"' in content


class _ScriptExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_script = False
        self.scripts: list[str] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() == "script":
            self._in_script = True
            self._buffer = []

    def handle_endtag(self, tag: str):
        if tag.lower() == "script":
            self._in_script = False
            self.scripts.append("".join(self._buffer))

    def handle_data(self, data: str):
        if self._in_script:
            self._buffer.append(data)


def test_html_and_js_syntax_validity():
    """Rendertes HTML und Inline-JS müssen syntaktisch valide sein."""
    rendered = render_activity_dashboard()

    if LXML_AVAILABLE:
        doc = lxml.html.fromstring(rendered)
        assert doc.tag == "html"

    parser = _ScriptExtractor()
    parser.feed(rendered)
    scripts = [s for s in parser.scripts if s.strip()]
    assert len(scripts) >= 1

    for script_code in scripts:
        res = subprocess.run(
            ["node", "--check", "-"],
            input=script_code,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        assert res.returncode == 0, f"JS Syntax Error: {res.stderr}"


def test_template_missing_raises():
    """Fehlende Template-Datei wirft FileNotFoundError."""
    import gui.activity_dashboard as ad_mod
    with patch.object(ad_mod, "TEMPLATE_PATH", Path("non_existent_file.html")), pytest.raises(FileNotFoundError):
        get_activity_dashboard_template()


def test_system_gui_package_imports_from_repository_root():
    result = subprocess.run(
        [sys.executable, "-c", "import system.gui; import system.gui.activity_dashboard"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
