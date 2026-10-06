# SPDX-License-Identifier: MIT
"""BACH branding consumer of the neutral, independently importable shell."""
from __future__ import annotations

from typing import Any

try:
    from ocean_gui_shell import TEMPLATE_PATH
    from ocean_gui_shell import render_activity_dashboard as _render
except ModuleNotFoundError:
    from system.ocean_gui_shell import TEMPLATE_PATH
    from system.ocean_gui_shell import render_activity_dashboard as _render

TEMPLATE_DIR = TEMPLATE_PATH.parent
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
    "read_only": False,
}


def get_activity_dashboard_template() -> str:
    """Compatibility API, retaining the overridable template path."""
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def render_activity_dashboard(
    branding: dict[str, Any] | None = None, api_base: str = ""
) -> str:
    return _render(
        {**DEFAULT_BRANDING, **(branding or {})},
        api_base,
        template=get_activity_dashboard_template(),
    )


__all__ = [
    "DEFAULT_BRANDING",
    "TEMPLATE_PATH",
    "get_activity_dashboard_template",
    "render_activity_dashboard",
]
