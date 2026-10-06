"""Validated, public display metadata for a shared static GUI build."""
from __future__ import annotations

import json
from pathlib import Path
import re

DEFAULT_BRAND = Path.home() / ".bach" / "gui_brand.json"
SCHEMA = "ellmos-system-gui.brand.v1"
_LABEL = re.compile(r"^[^<>\x00-\x1f\x7f]{1,48}$")
_LOGO_TEXT = re.compile(r"^[^<>\x00-\x1f\x7f]{1,12}$")
_LOGO_PATH = re.compile(r"^/static/branding/[A-Za-z0-9][A-Za-z0-9._/-]{0,120}\.(?:png|webp)$")
_THEMES = {"dark", "light", "ocean", "warm"}


def read_gui_brand(config: Path = DEFAULT_BRAND) -> dict:
    """Return only validated labels and same-origin packaged logo references."""
    fallback = {
        "schema": SCHEMA,
        "label": "BACH",
        "product": "BACH/Ocean GUI",
        "logo_text": "🎵",
        "logo_path": None,
        "theme": "dark",
        "source": "backend_default",
    }
    try:
        if config.stat().st_size > 4096:
            return fallback
        data = json.loads(config.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            return fallback
        label = data.get("label")
        product = data.get("product")
        logo_text = data.get("logo_text")
        logo_path = data.get("logo_path")
        theme = data.get("theme")
        if (not isinstance(label, str) or not _LABEL.fullmatch(label)
                or not isinstance(product, str) or not _LABEL.fullmatch(product)
                or not isinstance(logo_text, str) or not _LOGO_TEXT.fullmatch(logo_text)
                or (logo_path is not None and
                    (not isinstance(logo_path, str) or not _LOGO_PATH.fullmatch(logo_path)
                     or ".." in logo_path))
                or theme not in _THEMES):
            return fallback
        return {
            "schema": SCHEMA,
            "label": label,
            "product": product,
            "logo_text": logo_text,
            "logo_path": logo_path,
            "theme": theme,
            "source": "validated_consumer_config",
        }
    except (OSError, ValueError, TypeError):
        return fallback
