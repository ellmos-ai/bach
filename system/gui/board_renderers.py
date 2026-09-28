# SPDX-License-Identifier: MIT
"""
Board Templates Renderer (Phase 2.3)
====================================

Neutrales Web-Modul zur Auslieferung modularisierter Board-Oberflächen:
  - Agents / Skills Board (agents-board.html & skills-board.html)
  - Tasks Management Board (tasks_board.html)

Ermöglicht geteilten Konsum durch:
  - BACH GUI (system/gui/server.py unter /agents-board, /skills-board, /tasks-board)
  - ellmos-unified-gui & OCEAN-Vollausprägung (als neutrale Module mit anpassbarem Branding)

Unterstützt konfigurierbare Parameter:
  - Titel, Markenname, Marken-Icon, Header-Titel
  - Theme-Storage-Key (Standard: 'bach-theme')
  - Token-Storage-Key (Standard: 'bach-token')
  - API-Basis-URL (für Remote-, Cross-Port- oder Gateway-Betrieb)
  - Statischer Ressourcen-Präfix (Standard: '/static')
  - Navigationslinks (Header-Aktionen)
  - CSS-Theme-Variablen (--accent, --bg-panel, etc.)
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
AGENTS_BOARD_TEMPLATE_PATH = TEMPLATE_DIR / "agents-board.html"
TASKS_BOARD_TEMPLATE_PATH = TEMPLATE_DIR / "tasks_board.html"

DEFAULT_AGENTS_BOARD_BRANDING: dict[str, Any] = {
    "title": "BACH - Agents Board",
    "brand_name": "BACH",
    "brand_icon": "🎯",
    "header_title": "Agents Board",
    "theme_storage_key": "bach-theme",
    "token_storage_key": "bach-token",
    "api_base": "",
    "static_base": "/static",
    "nav_links": None,
    "theme_colors": {},
}

DEFAULT_TASKS_BOARD_BRANDING: dict[str, Any] = {
    "title": "BACH - Tasks Board",
    "brand_name": "BACH",
    "brand_icon": "📋",
    "header_title": "Task Management Board",
    "theme_storage_key": "bach-theme",
    "token_storage_key": "bach-token",
    "api_base": "",
    "static_base": "/static",
    "nav_links": None,
    "theme_colors": {},
}


def get_agents_board_template() -> str:
    """Liest die rohe HTML-Template-Datei für das Agents Board ein."""
    if not AGENTS_BOARD_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Agents Board Template nicht gefunden: {AGENTS_BOARD_TEMPLATE_PATH}"
        )
    return AGENTS_BOARD_TEMPLATE_PATH.read_text(encoding="utf-8")


def get_tasks_board_template() -> str:
    """Liest die rohe HTML-Template-Datei für das Tasks Board ein."""
    if not TASKS_BOARD_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Tasks Board Template nicht gefunden: {TASKS_BOARD_TEMPLATE_PATH}"
        )
    return TASKS_BOARD_TEMPLATE_PATH.read_text(encoding="utf-8")


def _render_nav_links(links: list[dict[str, str]]) -> str:
    """Rendert eine Liste von Navigationslinks als HTML-Header."""
    items = []
    for link in links:
        href = html.escape(link.get("href", "#"), quote=True)
        label = html.escape(link.get("label", ""))
        target_attr = (
            f' target="{html.escape(link["target"], quote=True)}"'
            if link.get("target")
            else ""
        )
        css_class = html.escape(link.get("class", "btn btn-outline btn-sm"), quote=True)
        items.append(f'<a href="{href}"{target_attr} class="{css_class}">{label}</a>')
    rendered_links = "\n        ".join(items)
    return f"""<header class="main-header" style="display:flex;gap:0.75rem;align-items:center;padding:0.75rem 1.5rem;">
        {rendered_links}
    </header>"""


def _render_theme_css(theme_colors: dict[str, str]) -> str:
    """Rendert CSS-Custom-Properties zur Farbanpassung."""
    if not theme_colors:
        return ""
    lines = [":root {"]
    for key, val in theme_colors.items():
        var_name = key if key.startswith("--") else f"--{key}"
        clean_val = re.sub(r"[;}{]", "", str(val)).strip()
        lines.append(f"  {var_name}: {clean_val};")
    lines.append("}")
    return "\n".join(lines)


def _apply_common_replacements(
    raw_html: str,
    cfg: dict[str, Any],
    api_base: str = "",
) -> str:
    """Führt gemeinsame Ersetzungen für Board-Templates durch."""
    if api_base:
        cfg["api_base"] = api_base

    # Navigationslinks ersetzen (falls explizit übergeben)
    nav_links = cfg.get("nav_links")
    if isinstance(nav_links, list) and nav_links:
        nav_html = _render_nav_links(nav_links)
        nav_pattern = re.compile(
            r"<!--\s*NAV_LINKS_START\s*-->.*?<!--\s*NAV_LINKS_END\s*-->",
            re.DOTALL,
        )
        raw_html = nav_pattern.sub(nav_html, raw_html)

    # Theme Overrides einbetten
    theme_colors = cfg.get("theme_colors") or {}
    if isinstance(theme_colors, dict) and theme_colors:
        theme_css = _render_theme_css(theme_colors)
        raw_html = raw_html.replace(
            "/* THEME_OVERRIDES */",
            f"/* THEME_OVERRIDES */\n{theme_css}",
        )

    # Statische Ressourcen anpassen falls abweichend
    static_base = cfg.get("static_base", "/static")
    if static_base and static_base != "/static":
        clean_static = static_base.rstrip("/")
        raw_html = raw_html.replace("/static/", f"{clean_static}/")

    # Text- & Branding-Platzhalter ersetzen
    replacements = {
        "{{ title }}": html.escape(str(cfg.get("title", ""))),
        "{{ brand_name }}": html.escape(str(cfg.get("brand_name", ""))),
        "{{ brand_icon }}": str(cfg.get("brand_icon", "")),
        "{{ header_title }}": html.escape(str(cfg.get("header_title", ""))),
        "{{ theme_storage_key }}": str(
            cfg.get("theme_storage_key", "bach-theme")
        ).replace("'", "\\'"),
        "{{ token_storage_key }}": str(
            cfg.get("token_storage_key", "bach-token")
        ).replace("'", "\\'"),
        "{{ api_base }}": str(cfg.get("api_base", "")).replace("'", "\\'"),
    }

    for placeholder, value in replacements.items():
        raw_html = raw_html.replace(placeholder, value)

    return raw_html


def render_agents_board(
    branding: dict[str, Any] | None = None,
    api_base: str = "",
) -> str:
    """
    Rendert das Agents Board mit den übergebenen Branding-Optionen.

    :param branding: Optionales Dict zur Übersteuerung von DEFAULT_AGENTS_BOARD_BRANDING.
    :param api_base: Optionale API-Basis-URL (z. B. 'http://127.0.0.1:8000').
    :return: Vollständiges HTML-Dokument als String.
    """
    cfg = dict(DEFAULT_AGENTS_BOARD_BRANDING)
    if branding:
        cfg.update(branding)

    raw_html = get_agents_board_template()
    return _apply_common_replacements(raw_html, cfg, api_base=api_base)


def render_tasks_board(
    branding: dict[str, Any] | None = None,
    api_base: str = "",
) -> str:
    """
    Rendert das Tasks Board mit den übergebenen Branding-Optionen.

    :param branding: Optionales Dict zur Übersteuerung von DEFAULT_TASKS_BOARD_BRANDING.
    :param api_base: Optionale API-Basis-URL (z. B. 'http://127.0.0.1:8000').
    :return: Vollständiges HTML-Dokument als String.
    """
    cfg = dict(DEFAULT_TASKS_BOARD_BRANDING)
    if branding:
        cfg.update(branding)

    raw_html = get_tasks_board_template()
    return _apply_common_replacements(raw_html, cfg, api_base=api_base)


__all__ = [
    "AGENTS_BOARD_TEMPLATE_PATH",
    "DEFAULT_AGENTS_BOARD_BRANDING",
    "DEFAULT_TASKS_BOARD_BRANDING",
    "TASKS_BOARD_TEMPLATE_PATH",
    "get_agents_board_template",
    "get_tasks_board_template",
    "render_agents_board",
    "render_tasks_board",
]
