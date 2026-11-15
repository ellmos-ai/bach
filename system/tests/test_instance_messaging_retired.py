"""BACH #4147: Das dateibasierte Inter-Instanz-Messaging ist stillgelegt und bleibt unverdrahtet."""
from pathlib import Path

from core.instance_messaging import InstanceMessaging
from core.instance_registry import InstanceRegistry

SYSTEM = Path(__file__).resolve().parents[1]


def test_instance_messaging_is_marked_as_legacy():
    for cls in (InstanceMessaging, InstanceRegistry):
        assert getattr(cls, "__ocean_deprecated__", False) is True
        assert "memoryhooker" in cls.__ocean_replacement__


def test_enable_messaging_has_no_caller():
    callers = [p for p in SYSTEM.rglob("*.py")
               if "tests" not in p.parts and ".enable_messaging(" in p.read_text(encoding="utf-8", errors="ignore")]
    assert callers == [], f"enable_messaging ist stillgelegt, neu verdrahtet in: {callers}"
