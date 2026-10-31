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

# Gemeinsamer GUI-Einstellungsvertrag (25.10.):
# - Navigationsstile (ui.preset): "standard" ("Standard bewährt"), "ocean-bach-classic" ("Ocean-BACH-Klassik")
# - Bereichsauswahl (ui.nav_scope): "compact" (kompakt), "all" (alle), "custom" (eigene Auswahl)
# - Symbole (ui.icon_style): "classic" (klassisch), "emoji" (Emoji)
# - Dichte (ui.density): "compact", "standard", "spacious"
# Legacy-Werte aus älteren Aufrufern werden verlustfrei auf den kanonischen Vertrag abgebildet.
UI_PRESETS = ("standard", "ocean-bach-classic", "compact", "spacious")
NAV_SCOPES = ("compact", "all", "custom", "global", "section", "none")
ICON_STYLES = ("classic", "emoji", "solid", "outline", "none")
DENSITIES = ("compact", "standard", "spacious", "loose")
UI_CANONICAL_OPTIONS = {
    "preset": ("standard", "ocean-bach-classic"),
    "nav_scope": ("compact", "all", "custom"),
    "icon_style": ("classic", "emoji"),
    "density": ("compact", "standard", "spacious"),
}
UI_ALIASES = {
    "preset": {
        "standard": "standard",
        "standard-bewaehrt": "standard",
        "ocean-bach-classic": "ocean-bach-classic",
        "ocean_bach_classic": "ocean-bach-classic",
        "classic": "ocean-bach-classic",
        "klassik": "ocean-bach-classic",
        "compact": "compact",
        "spacious": "spacious",
    },
    "nav_scope": {
        "compact": "compact",
        "kompakt": "compact",
        "section": "compact",
        "all": "all",
        "alle": "all",
        "global": "all",
        "custom": "custom",
        "eigene": "custom",
        "none": "custom",
    },
    "icon_style": {
        "classic": "classic",
        "klassisch": "classic",
        "solid": "classic",
        "outline": "classic",
        "emoji": "emoji",
        "none": "classic",
    },
    "density": {
        "compact": "compact",
        "standard": "standard",
        "spacious": "spacious",
        "loose": "spacious",
    },
}
UI_DEFAULTS = {
    "preset": "standard",
    "nav_scope": "compact",
    "icon_style": "classic",
    "density": "standard",
}
_UI_ENUMS = {
    "preset": tuple(UI_ALIASES["preset"].keys()),
    "nav_scope": tuple(UI_ALIASES["nav_scope"].keys()),
    "icon_style": tuple(UI_ALIASES["icon_style"].keys()),
    "density": tuple(UI_ALIASES["density"].keys()),
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

    @staticmethod
    def _normalize_ui_value(key: str, raw: object) -> str:
        normalized = str(raw or "").strip().lower()
        aliases = UI_ALIASES[key]
        if normalized in aliases:
            return aliases[normalized]
        raise ValueError(
            "Ungueltiger "
            + key
            + "-Wert. Erlaubt: "
            + ", ".join(UI_CANONICAL_OPTIONS[key])
        )

    def get_ui(self) -> dict:
        config = self._load_config()
        ui_config = config.get("ui") if isinstance(config.get("ui"), dict) else {}
        gui_config = config.get("gui") if isinstance(config.get("gui"), dict) else {}
        merged = {**gui_config, **ui_config}
        configured = any(key in merged for key in _UI_ENUMS)
        values = {}
        for key in _UI_ENUMS:
            raw_val = merged.get(key, UI_DEFAULTS[key])
            try:
                values[key] = self._normalize_ui_value(key, raw_val)
            except ValueError:
                values[key] = UI_DEFAULTS[key]
        return {
            "preset": values["preset"],
            "nav_scope": values["nav_scope"],
            "icon_style": values["icon_style"],
            "density": values["density"],
            "ui": dict(values),
            "available": {
                "preset": list(UI_CANONICAL_OPTIONS["preset"]),
                "nav_scope": list(UI_CANONICAL_OPTIONS["nav_scope"]),
                "icon_style": list(UI_CANONICAL_OPTIONS["icon_style"]),
                "density": list(UI_CANONICAL_OPTIONS["density"]),
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
        for key in _UI_ENUMS:
            value = provided[key]
            if value is None:
                continue
            validated[key] = self._normalize_ui_value(key, value)

        def apply_update(config: dict) -> dict:
            ui_config = config.get("ui") if isinstance(config.get("ui"), dict) else {}
            gui_config = config.get("gui") if isinstance(config.get("gui"), dict) else {}
            ui_config = dict(ui_config)
            gui_config = dict(gui_config)
            for k in _UI_ENUMS:
                if k not in ui_config and k in gui_config:
                    try:
                        ui_config[k] = self._normalize_ui_value(k, gui_config[k])
                    except ValueError:
                        pass
            ui_config.update(validated)
            gui_config.update(validated)
            config["ui"] = ui_config
            config["gui"] = gui_config
            return config

        if dry_run:
            config = apply_update(self._load_config())
        else:
            config = update_user_config(self.config_path, apply_update)
        ui_config = config.get("ui") if isinstance(config.get("ui"), dict) else {}
        result_vals = {
            k: ui_config.get(k, UI_DEFAULTS[k]) for k in _UI_ENUMS
        }
        return {
            **result_vals,
            "ui": dict(result_vals),
            "available": {
                "preset": list(UI_CANONICAL_OPTIONS["preset"]),
                "nav_scope": list(UI_CANONICAL_OPTIONS["nav_scope"]),
                "icon_style": list(UI_CANONICAL_OPTIONS["icon_style"]),
                "density": list(UI_CANONICAL_OPTIONS["density"]),
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
