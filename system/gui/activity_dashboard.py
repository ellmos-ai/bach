# SPDX-License-Identifier: MIT
"""
Activity & Worker Dashboard Template Renderer (Phase 2.2)
=========================================================

Neutrales Web-Modul zur Auslieferung der Aktivitätsanzeige und des
Worker-Dashboards für die Control-API (:8081).

Ermöglicht geteilten Konsum durch:
  - BACH telegram_chat.py::ControlHandler (/activity)
  - ellmos-unified-gui (OCEAN-Vollausprägung & Standalone-Panels)

Unterstützt konfigurierbare Branding-Parameter:
  - Titel, Markenname, Marken-Icon, Untertitel
  - Navigationslinks (Header-Aktionen)
  - API-Basis-URL (für Remote-/Cross-Port-Betrieb)
  - Token-Storage-Key (für lokales Token-Caching im Browser)
  - Slot-Titel (z. B. Buddha Chat vs. Neutral Chat)
  - CSS-Theme-Variablen (--accent, --bg-body, etc.)
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_PATH = TEMPLATE_DIR / "activity_dashboard.html"

DEFAULT_BRANDING: dict[str, Any] = {
    "title": "BACH Aktivitätsanzeige & Worker Dashboard",
    "brand_name": "BACH",
    "brand_icon": "🤖",
    "header_title": "Aktivitätsanzeige & Worker Dashboard",
    "subtitle": "Modell-Zuweisung je Slot · Hintergrundworker · Parallele Ausführung · Live-Aktivitäten",
    "api_base": "",
    "nav_links": [
        {"label": "Chat-Control", "href": "/"},
        {"label": "GUI :8000", "href": "http://127.0.0.1:8000/", "target": "_blank"},
    ],
    "token_storage_key": "bach-control-api-token",
    "slot_chat_title": "Buddha Chat",
    "slot_always_on_title": "Buddha Always-On",
    "slot_connector_title": "Buddha Connector",
    "theme_colors": {},
}


def get_activity_dashboard_template() -> str:
    """Liest die rohe HTML-Template-Datei ein."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Activity Dashboard Template nicht gefunden: {TEMPLATE_PATH}")
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _render_nav_links(links: list[dict[str, str]]) -> str:
    """Rendert eine Liste von Navigationslinks als HTML."""
    items = []
    for link in links:
        href = html.escape(link.get("href", "#"), quote=True)
        label = html.escape(link.get("label", ""))
        target_attr = f' target="{html.escape(link["target"], quote=True)}"' if link.get("target") else ""
        css_class = html.escape(link.get("class", "btn btn-outline btn-sm"), quote=True)
        items.append(f'<a href="{href}"{target_attr} class="{css_class}">{label}</a>')
    return "\n    ".join(items)


def _render_theme_css(theme_colors: dict[str, str]) -> str:
    """Rendert CSS-Custom-Properties zur Farbanpassung."""
    if not theme_colors:
        return ""
    lines = [":root {"]
    for key, val in theme_colors.items():
        var_name = key if key.startswith("--") else f"--{key}"
        if not re.fullmatch(r"--[a-zA-Z_][a-zA-Z0-9_-]*", var_name):
            continue
        clean_val = str(val).strip()
        if any(char in clean_val for char in "<>;{}"):
            continue
        lines.append(f"  {var_name}: {clean_val};")
    lines.append("}")
    return "\n".join(lines)


def _script_json(value: Any) -> str:
    """Serializes a value for an inline script without allowing HTML termination."""
    return json.dumps(str(value)).replace("<", "\\u003c")


def render_activity_dashboard(
    branding: dict[str, Any] | None = None,
    api_base: str = "",
) -> str:
    """
    Rendert das Activity- & Worker-Dashboard mit den übergebenen Branding-Optionen.

    :param branding: Optionales Dict zur Übersteuerung von DEFAULT_BRANDING.
    :param api_base: Optionale API-Basis-URL (z. B. 'http://127.0.0.1:8081/api').
                     Wenn gesetzt, überschreibt sie branding['api_base'].
    :return: Vollständiges HTML-Dokument als String.
    """
    cfg = dict(DEFAULT_BRANDING)
    if branding:
        cfg.update(branding)

    if api_base:
        cfg["api_base"] = api_base

    raw_html = get_activity_dashboard_template()

    # Navigationslinks ersetzen
    nav_links = cfg.get("nav_links")
    if isinstance(nav_links, list):
        nav_html = _render_nav_links(nav_links)
        nav_pattern = re.compile(
            r"<!--\s*NAV_LINKS_START\s*-->.*?<!--\s*NAV_LINKS_END\s*-->",
            re.DOTALL,
        )
        raw_html = nav_pattern.sub(
            f"<!-- NAV_LINKS_START -->\n    {nav_html}\n    <!-- NAV_LINKS_END -->",
            raw_html,
        )

    # Theme Overrides einbetten
    theme_colors = cfg.get("theme_colors") or {}
    if isinstance(theme_colors, dict) and theme_colors:
        theme_css = _render_theme_css(theme_colors)
        raw_html = raw_html.replace(
            "/* THEME_OVERRIDES */",
            f"/* THEME_OVERRIDES */\n{theme_css}",
        )

    # Text- & Branding-Platzhalter ersetzen
    replacements = {
        "{{ title }}": html.escape(str(cfg.get("title", ""))),
        "{{ brand_icon }}": html.escape(str(cfg.get("brand_icon", ""))),
        "{{ brand_name }}": html.escape(str(cfg.get("brand_name", ""))),
        "{{ header_title }}": html.escape(str(cfg.get("header_title", ""))),
        "{{ subtitle }}": html.escape(str(cfg.get("subtitle", ""))),
        "{{ slot_chat_title }}": html.escape(str(cfg.get("slot_chat_title", ""))),
        "{{ slot_always_on_title }}": html.escape(str(cfg.get("slot_always_on_title", ""))),
        "{{ slot_connector_title }}": html.escape(str(cfg.get("slot_connector_title", ""))),
        "{{ api_base_json }}": _script_json(cfg.get("api_base", "")),
        "{{ token_storage_key_json }}": _script_json(
            cfg.get("token_storage_key", "bach-control-api-token")
        ),
        "{{ slot_always_on_title_json }}": _script_json(
            cfg.get("slot_always_on_title", "")
        ),
    }

    for placeholder, value in replacements.items():
        raw_html = raw_html.replace(placeholder, value)

    return raw_html


__all__ = [
    "DEFAULT_BRANDING",
    "TEMPLATE_PATH",
    "get_activity_dashboard_template",
    "render_activity_dashboard",
]
