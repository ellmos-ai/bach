# SPDX-License-Identifier: MIT
import json
import sys
import threading
import time
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).parent.parent
if str(SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(SYSTEM_ROOT))

from hub.theme import CUSTOM_THEME_DEFAULTS, ThemeHandler
from hub._services.user_config_store import update_user_config


def test_theme_defaults_without_user_config(tmp_path):
    handler = ThemeHandler(tmp_path)

    result = handler.get_theme()

    assert result["theme"] == "dark"
    assert result["configured"] is False
    assert result["custom"] == CUSTOM_THEME_DEFAULTS
    assert result["available"] == ["dark", "light", "ocean", "warm", "custom"]


def test_set_theme_preserves_unrelated_user_config(tmp_path):
    config_path = tmp_path / "data" / "user_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"session_duration_minutes": 60, "gui": {"density": "compact"}}),
        encoding="utf-8",
    )
    handler = ThemeHandler(tmp_path)

    result = handler.set_theme("warm")
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert result["theme"] == "warm"
    assert result["configured"] is True
    assert saved["session_duration_minutes"] == 60
    assert saved["gui"]["density"] == "compact"
    assert saved["gui"]["theme"] == "warm"


def test_custom_theme_validates_and_merges_colors(tmp_path):
    handler = ThemeHandler(tmp_path)

    result = handler.set_theme("custom", {"accent": "#AABBCC"})

    assert result["custom"]["accent"] == "#aabbcc"
    assert result["custom"]["bg_dark"] == CUSTOM_THEME_DEFAULTS["bg_dark"]
    with pytest.raises(ValueError, match="Ungueltiger Farbwert"):
        handler.set_theme("custom", {"accent": "red; background:url(x)"})
    with pytest.raises(ValueError, match="Unbekannte Custom-Farben"):
        handler.set_theme("custom", {"unknown": "#000000"})


def test_theme_dry_run_does_not_write(tmp_path):
    handler = ThemeHandler(tmp_path)

    result = handler.set_theme("light", dry_run=True)

    assert result["dry_run"] is True
    assert not handler.config_path.exists()


def test_theme_refuses_to_overwrite_malformed_user_config(tmp_path):
    config_path = tmp_path / "data" / "user_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("not-json", encoding="utf-8")
    handler = ThemeHandler(tmp_path)

    with pytest.raises(ValueError, match="nicht lesbar"):
        handler.set_theme("warm")

    assert config_path.read_text(encoding="utf-8") == "not-json"


def test_theme_cli_contract(tmp_path):
    handler = ThemeHandler(tmp_path)

    ok, message = handler.handle("set", ["warm"])
    status_ok, status = handler.handle("status", [])

    assert ok is True
    assert message == "GUI-Theme: warm"
    assert status_ok is True
    assert json.loads(status)["theme"] == "warm"


def test_theme_cli_dry_run_flag_is_not_parsed_as_color(tmp_path):
    handler = ThemeHandler(tmp_path)

    ok, message = handler.handle("set", ["warm", "--dry-run"])

    assert ok is True
    assert message == "GUI-Theme: warm (Dry-Run)"
    assert not handler.config_path.exists()


def test_gui_theme_assets_share_the_same_contract():
    nav = (SYSTEM_ROOT / "gui" / "static" / "js" / "nav.js").read_text(encoding="utf-8")
    css = (SYSTEM_ROOT / "gui" / "static" / "css" / "main.css").read_text(encoding="utf-8")
    settings = (SYSTEM_ROOT / "gui" / "templates" / "settings.html").read_text(encoding="utf-8")

    for theme in ("dark", "light", "warm", "custom"):
        assert f'data-theme-option="{theme}"' in settings
        assert f"'{theme}'" in nav
    assert '[data-theme="warm"]' in css
    assert '[data-theme="custom"]' in css
    assert "/api/settings/theme" in nav
    assert "/api/settings/theme" in settings
    assert "persistedTheme" in settings
    assert "previewTheme(selectedTheme, customPalette)" in settings


def test_concurrent_user_config_updates_do_not_lose_fields(tmp_path):
    config_path = tmp_path / "data" / "user_config.json"
    first_entered = threading.Event()
    release_first = threading.Event()

    def slow_update(config):
        first_entered.set()
        assert release_first.wait(2)
        config["startup_mode"] = "silent"
        return config

    def fast_update(config):
        gui = dict(config.get("gui", {}))
        gui["theme"] = "warm"
        config["gui"] = gui
        return config

    first = threading.Thread(target=update_user_config, args=(config_path, slow_update))
    second = threading.Thread(target=update_user_config, args=(config_path, fast_update))
    first.start()
    assert first_entered.wait(1)
    second.start()
    time.sleep(0.05)
    assert second.is_alive()
    release_first.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["startup_mode"] == "silent"
    assert saved["gui"]["theme"] == "warm"


def test_typed_bach_api_theme_accepts_structured_custom_palette(tmp_path, monkeypatch):
    monkeypatch.setenv("BACH_USER_CONFIG", str(tmp_path / "user_config.json"))
    import bach_api

    monkeypatch.setattr(bach_api, "_app", None)
    result = bach_api.theme.set("custom", {"accent": "#AABBCC"})

    assert result["theme"] == "custom"
    assert result["custom"]["accent"] == "#aabbcc"
    assert bach_api.theme.status()["configured"] is True

def test_ocean_theme_roundtrip_preserves_unrelated_config(tmp_path):
    handler = ThemeHandler(tmp_path)
    config = tmp_path / "data" / "user_config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"startup_mode": "silent", "gui": {"density": "compact"}}), encoding="utf-8")
    assert handler.set_theme("ocean")["theme"] == "ocean"
    assert handler.get_theme()["theme"] == "ocean"
    assert json.loads(config.read_text(encoding="utf-8"))["startup_mode"] == "silent"
    assert json.loads(config.read_text(encoding="utf-8"))["gui"]["density"] == "compact"
    assert handler.handle("set", ["ocean"])[0] is True


def test_ocean_theme_legacy_assets_share_native_contract():
    nav = (SYSTEM_ROOT / "gui/static/js/nav.js").read_text(encoding="utf-8")
    css = (SYSTEM_ROOT / "gui/static/css/main.css").read_text(encoding="utf-8")
    settings = (SYSTEM_ROOT / "gui/templates/settings.html").read_text(encoding="utf-8")
    assert "'ocean'" in nav
    assert 'data-theme="ocean"' in nav
    assert '[data-theme="ocean"]' in css
    assert 'data-theme-option="ocean"' in settings

def test_navigation_and_finance_tabs_wrap_without_hiding_content():
    css = (SYSTEM_ROOT / "gui/static/css/main.css").read_text(encoding="utf-8")
    finance = (SYSTEM_ROOT / "gui/templates/financial.html").read_text(encoding="utf-8")
    nav_rules = css[css.index(".main-nav {"):css.index(".nav-item {")]
    assert "flex-wrap: wrap" in nav_rules
    tabs = finance[finance.index(".tabs {"):finance.index(".tab {")]
    assert "flex-wrap: wrap" in tabs


@pytest.mark.parametrize("theme", ["dark", "light", "ocean", "warm"])
def test_default_theme_text_and_actions_contrast(theme):
    import re

    css = (SYSTEM_ROOT / "gui/static/css/main.css").read_text(encoding="utf-8")

    def variables(selector):
        start = css.index(selector + " {") + len(selector) + 2
        block = css[start:].split("}", 1)[0]
        return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,6});", block))

    values = variables(":root")
    if theme != "dark":
        values.update(variables(f'[data-theme="{theme}"]'))

    def luminance(color):
        color = color.lstrip("#")
        if len(color) == 3:
            color = "".join(char * 2 for char in color)
        rgb = [int(color[offset:offset + 2], 16) / 255 for offset in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    def contrast(first, second):
        low, high = sorted((luminance(values[first]), luminance(values[second])))
        return (high + 0.05) / (low + 0.05)

    for foreground in ("--text", "--text-muted", "--text-dim"):
        for background in ("--bg-dark", "--bg-panel", "--bg-card", "--bg-elevated"):
            assert contrast(foreground, background) >= 4.5, (theme, foreground, background)
    for background in ("--accent", "--accent-light"):
        assert contrast("--on-accent", background) >= 4.5, (theme, background)


def test_mobile_navigation_has_full_row_without_recoloring_underlined_tabs():
    css = (SYSTEM_ROOT / "gui/static/css/main.css").read_text(encoding="utf-8")
    assert ".header-left { flex-wrap: wrap; }" in css
    assert ".main-nav { flex: 1 1 100%; width: 100%; overflow-x: auto; }" in css
    assert ".nav-item.active { color: var(--on-accent); }" in css
    assert ".nav-item.active, .tab-btn.active { color: var(--on-accent); }" not in css
