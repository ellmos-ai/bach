# SPDX-License-Identifier: MIT
"""GUI theme preferences shared by CLI, API and the web dashboard."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .base import BaseHandler
from ._services.user_config_store import load_user_config, update_user_config


AVAILABLE_THEMES = ("dark", "light", "ocean", "warm", "custom")
CUSTOM_THEME_DEFAULTS = {
    "bg_dark": "#140e28",
    "bg_panel": "#1c1438",
    "bg_card": "#251d48",
    "bg_elevated": "#2e2555",
    "accent": "#ff6b8a",
    "accent_light": "#ff8fa8",
    "accent_blue": "#7c6cf0",
    "text": "#f0ecff",
    "text_muted": "#8a82b0",
    "border": "#342a5c",
    "success": "#4aedb0",
    "warning": "#ffd166",
    "error": "#ff5577",
}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

UI_PRESETS = ("compact", "standard", "spacious")
NAV_SCOPES = ("global", "section", "none")
ICON_STYLES = ("solid", "outline", "none")
DENSITIES = ("compact", "standard", "loose")
UI_DEFAULTS = {
    "preset": "standard",
    "nav_scope": "global",
    "icon_style": "solid",
    "density": "standard",
}
_UI_ENUMS = {
    "preset": UI_PRESETS,
    "nav_scope": NAV_SCOPES,
    "icon_style": ICON_STYLES,
    "density": DENSITIES,
}


class ThemeHandler(BaseHandler):
    """Persist dashboard theme preferences without owning unrelated config."""

    def __init__(self, base_path_or_app):
        super().__init__(base_path_or_app)
        import os

        configured_path = os.environ.get("BACH_USER_CONFIG")
        self.config_path = (
            Path(configured_path).expanduser()
            if configured_path
            else self.base_path / "data" / "user_config.json"
        )

    @property
    def profile_name(self) -> str:
        return "theme"

    @property
    def target_file(self) -> Path:
        return self.config_path

    def get_operations(self) -> dict:
        return {
            "status": "Aktuelles GUI-Theme anzeigen",
            "set": "GUI-Theme setzen: dark|light|ocean|warm|custom",
        }

    def _load_config(self) -> dict:
        return load_user_config(self.config_path, strict=True)

    @staticmethod
    def _validated_custom(custom: dict | None, *, partial: bool = False) -> dict:
        if custom is None:
            return {} if partial else dict(CUSTOM_THEME_DEFAULTS)
        if not isinstance(custom, dict):
            raise ValueError("custom muss ein Objekt mit Farbwerten sein")
        unknown = sorted(set(custom) - set(CUSTOM_THEME_DEFAULTS))
        if unknown:
            raise ValueError("Unbekannte Custom-Farben: " + ", ".join(unknown))
        result = {} if partial else dict(CUSTOM_THEME_DEFAULTS)
        for key, value in custom.items():
            if not isinstance(value, str) or not _HEX_COLOR_RE.fullmatch(value):
                raise ValueError(f"Ungueltiger Farbwert fuer {key}: erwartet #RRGGBB")
            result[key] = value.lower()
        return result

    def get_theme(self) -> dict:
        config = self._load_config()
        gui_config = config.get("gui") if isinstance(config.get("gui"), dict) else {}
        configured = "theme" in gui_config
        theme = str(gui_config.get("theme", "dark")).lower()
        if theme == "colorful":
            theme = "custom"
        if theme not in AVAILABLE_THEMES:
            theme = "dark"
        custom = self._validated_custom(gui_config.get("custom_theme"))
        return {
            "theme": theme,
            "custom": custom,
            "available": list(AVAILABLE_THEMES),
            "configured": configured,
        }

    def set_theme(
        self,
        theme: str,
        custom: dict | None = None,
        *,
        dry_run: bool = False,
    ) -> dict:
        normalized = str(theme or "").lower()
        if normalized == "colorful":
            normalized = "custom"
        if normalized not in AVAILABLE_THEMES:
            raise ValueError(
                "Unbekanntes Theme. Erlaubt: " + ", ".join(AVAILABLE_THEMES)
            )

        validated_update = self._validated_custom(custom, partial=True)

        def apply_update(config: dict) -> dict:
            gui_config = config.get("gui") if isinstance(config.get("gui"), dict) else {}
            gui_config = dict(gui_config)
            current_custom = self._validated_custom(gui_config.get("custom_theme"))
            current_custom.update(validated_update)
            gui_config["theme"] = normalized
            gui_config["custom_theme"] = current_custom
            config["gui"] = gui_config
            return config

        if dry_run:
            config = apply_update(self._load_config())
        else:
            config = update_user_config(self.config_path, apply_update)
        current_custom = config["gui"]["custom_theme"]
        return {
            "theme": normalized,
            "custom": current_custom,
            "available": list(AVAILABLE_THEMES),
            "configured": True,
            "dry_run": bool(dry_run),
        }

    def get_ui(self) -> dict:
        config = self._load_config()
        gui_config = config.get("gui") if isinstance(config.get("gui"), dict) else {}
        configured = any(key in gui_config for key in _UI_ENUMS)
        values = {}
        for key, allowed in _UI_ENUMS.items():
            value = str(gui_config.get(key, UI_DEFAULTS[key])).lower()
            if value not in allowed:
                value = UI_DEFAULTS[key]
            values[key] = value
        return {
            "preset": values["preset"],
            "nav_scope": values["nav_scope"],
            "icon_style": values["icon_style"],
            "density": values["density"],
            "available": {
                "preset": list(UI_PRESETS),
                "nav_scope": list(NAV_SCOPES),
                "icon_style": list(ICON_STYLES),
                "density": list(DENSITIES),
            },
            "configured": configured,
        }

    def set_ui(
        self,
        preset: str | None = None,
        nav_scope: str | None = None,
        icon_style: str | None = None,
        density: str | None = None,
        *,
        dry_run: bool = False,
    ) -> dict:
        provided = {
            "preset": preset,
            "nav_scope": nav_scope,
            "icon_style": icon_style,
            "density": density,
        }
        validated = {}
        for key, allowed in _UI_ENUMS.items():
            value = provided[key]
            if value is None:
                continue
            normalized = str(value).lower()
            if normalized not in allowed:
                raise ValueError(
                    "Ungueltiger "
                    + key
                    + "-Wert. Erlaubt: "
                    + ", ".join(allowed)
                )
            validated[key] = normalized

        def apply_update(config: dict) -> dict:
            gui_config = config.get("gui") if isinstance(config.get("gui"), dict) else {}
            gui_config = dict(gui_config)
            gui_config.update(validated)
            config["gui"] = gui_config
            return config

        if dry_run:
            config = apply_update(self._load_config())
        else:
            config = update_user_config(self.config_path, apply_update)
        gui_config = config.get("gui") if isinstance(config.get("gui"), dict) else {}
        return {
            "preset": gui_config.get("preset", UI_DEFAULTS["preset"]),
            "nav_scope": gui_config.get("nav_scope", UI_DEFAULTS["nav_scope"]),
            "icon_style": gui_config.get("icon_style", UI_DEFAULTS["icon_style"]),
            "density": gui_config.get("density", UI_DEFAULTS["density"]),
            "available": {
                "preset": list(UI_PRESETS),
                "nav_scope": list(NAV_SCOPES),
                "icon_style": list(ICON_STYLES),
                "density": list(DENSITIES),
            },
            "configured": True,
            "dry_run": bool(dry_run),
        }

    def handle(self, operation: str, args: list, dry_run: bool = False) -> tuple:
        try:
            if operation in ("", "status", "show"):
                return True, json.dumps(self.get_theme(), ensure_ascii=False, indent=2)
            if operation != "set":
                return False, "Unbekannte Operation. Nutze: bach theme status|set"
            if not args:
                return False, "Usage: bach theme set dark|light|ocean|warm|custom"

            theme = args[0]
            colors = {}
            effective_dry_run = dry_run
            for arg in args[1:]:
                if str(arg) in {"--dry-run", "-n"}:
                    effective_dry_run = True
                    continue
                if not str(arg).startswith("--") or "=" not in str(arg):
                    return False, "Custom-Farben als --bg_dark=#RRGGBB angeben"
                key, value = str(arg)[2:].split("=", 1)
                colors[key] = value
            result = self.set_theme(
                theme,
                colors or None,
                dry_run=effective_dry_run,
            )
            suffix = " (Dry-Run)" if effective_dry_run else ""
            return True, f"GUI-Theme: {result['theme']}{suffix}"
        except ValueError as exc:
            return False, str(exc)
