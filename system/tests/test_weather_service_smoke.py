"""Smoke-Tests fuer system/hub/_services/weather/weather_service.py.

Sichern die Regression aus Task #3719 ab:
- Modul muss importierbar sein (kein IndentationError/Syntaxfehler).
- Es darf nur EINE get_weather-Definition geben (kein toter Doppelblock).
- Der nicht existierende Helfer _fetch_json darf nicht referenziert werden.
"""

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "system"
    / "hub"
    / "_services"
    / "weather"
    / "weather_service.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "weather_service_smoke", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_importierbar():
    module = _load_module()
    assert callable(module.get_weather)


def test_get_weather_nur_einmal_definiert():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert source.count("def get_weather(") == 1
    assert "_fetch_json" not in source


def test_kernfunktionen_vorhanden():
    module = _load_module()
    assert callable(module._parse_daily_day)
    assert callable(module.get_forecast)
    assert callable(module.get_weather_text)
