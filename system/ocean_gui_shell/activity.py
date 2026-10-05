# SPDX-License-Identifier: MIT
"""Neutral Activity shell: rendering only, no backend imports or I/O."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

TEMPLATE_PATH = Path(__file__).parent / "templates" / "activity_dashboard.html"
DEFAULT_BRANDING = {
    "title": "OCEAN Aktivitäten & Worker", "brand_name": "OCEAN", "brand_icon": "🌊",
    "header_title": "Aktivitäten & Worker",
    "subtitle": "Modell-Zuweisung je Slot · Hintergrundworker · Parallele Ausführung · Live-Aktivitäten",
    "api_base": "", "nav_links": [], "token_storage_key": "ocean-control-api-token",
    "slot_chat_title": "Chat", "slot_always_on_title": "Always-On", "slot_connector_title": "Connector",
    "theme_colors": {}, "read_only": True,
}


def get_activity_dashboard_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def safe_url(value: str) -> str:
    """Allow explicit HTTP(S) URLs or local paths, never active URL schemes."""
    if not isinstance(value, str) or re.search(r"[\s\\<>\"']", value):
        raise ValueError("Ungültige Shell-URL")
    if value.startswith("//"):
        raise ValueError("Shell-URL benötigt einen eindeutigen Ursprung")
    parts = urlsplit(value)
    if parts.scheme:
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("Shell-URL muss HTTP(S) verwenden")
    elif value and not value.startswith(("/", "#")):
        raise ValueError("Shell-URL muss absolut oder hostrelativ sein")
    return value


def _nav(links: list[dict[str, str]]) -> str:
    items = []
    for link in links:
        href = html.escape(safe_url(link.get("href", "#")), quote=True)
        label = html.escape(link.get("label", ""))
        target = link.get("target", "")
        if target not in {"", "_blank", "_self"}:
            raise ValueError("Ungültiges Navigationsziel")
        extra = f' target="{target}"' if target else ""
        if target == "_blank":
            extra += ' rel="noopener noreferrer"'
        css = html.escape(link.get("class", "btn btn-outline btn-sm"), quote=True)
        items.append(f'<a href="{href}"{extra} class="{css}">{label}</a>')
    return "\n    ".join(items)


def _theme(colors: dict[str, str]) -> str:
    lines = []
    for key, value in colors.items():
        name = key if key.startswith("--") else "--" + key
        if not re.fullmatch(r"--[a-zA-Z][a-zA-Z0-9_-]*", name):
            raise ValueError("Ungültige CSS-Variable")
        if not re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]+", str(value)):
            raise ValueError("Theme-Farben müssen Hexwerte oder Farbnamen sein")
        lines.append(f"  {name}: {value};")
    return ":root {\n" + "\n".join(lines) + "\n}" if lines else ""


def render_activity_dashboard(branding: dict[str, Any] | None = None, api_base: str = "", *, template: str | None = None) -> str:
    cfg = {**DEFAULT_BRANDING, **(branding or {})}
    cfg["api_base"] = safe_url(api_base or cfg["api_base"])
    if not isinstance(cfg["read_only"], bool):
        raise TypeError("read_only muss ein boolescher Wert sein")
    client = {"apiBase": cfg["api_base"], "tokenStorageKey": str(cfg["token_storage_key"]),
              "alwaysOnTitle": str(cfg["slot_always_on_title"]), "readOnly": cfg["read_only"]}
    # JSON alone does not protect an HTML script context: escape tag delimiters.
    encoded = json.dumps(client, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    substitutions = {key: html.escape(str(cfg[key]), quote=True) for key in (
        "title", "brand_name", "brand_icon", "header_title", "subtitle",
        "slot_chat_title", "slot_always_on_title", "slot_connector_title",
    )}
    substitutions["shell_config_json"] = encoded
    raw = template if template is not None else get_activity_dashboard_template()
    # A single pass prevents user text containing placeholders being reinterpreted.
    raw = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda match: substitutions[match[1]], raw)
    nav = _nav(cfg["nav_links"] or [])
    raw = re.sub(r"<!--\s*NAV_LINKS_START\s*-->.*?<!--\s*NAV_LINKS_END\s*-->",
                 lambda _: "<!-- NAV_LINKS_START -->\n    " + nav + "\n    <!-- NAV_LINKS_END -->",
                 raw, flags=re.DOTALL)
    return raw.replace("/* THEME_OVERRIDES */", "/* THEME_OVERRIDES */\n" + _theme(cfg["theme_colors"] or {}))
