"""Delivery preferences can live outside a clean public checkout."""

import json
from pathlib import Path

import pytest
from hub import bach_paths
from hub._services.delivery.delivery_engine import DeliveryEngine


def _preferences(path: Path, destination: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "default_delivery": {"mode": "only", "methods": ["user_folder"]},
            "delivery_methods": {
                "user_folder": {"enabled": True, "base_path": destination, "create_subdirs": False}
            },
        }),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def delivery_paths(tmp_path, monkeypatch):
    system = tmp_path / "system"
    private = tmp_path / "state"
    monkeypatch.setattr(bach_paths, "SYSTEM_ROOT", system)
    monkeypatch.setattr(bach_paths, "LOCAL_BACH_DIR", private)
    legacy = _preferences(system / "data/config/delivery_preferences.json", "bundled")
    return system, legacy, private / "config/delivery_preferences.json"


def test_default_engine_delivers_with_local_preferences(delivery_paths):
    system, legacy, local = delivery_paths
    _preferences(local, "custom")
    before = legacy.read_bytes()

    engine = DeliveryEngine()
    result = engine.deliver("Beleg", "Probe", format="txt")

    assert engine.config_file == local
    assert result["success"] is True
    assert result["delivered_to"] == ["user_folder"]
    assert (system / "custom" / Path(result["file"]).name).read_text(encoding="utf-8") == "Beleg"
    assert not (system / "bundled").exists()
    assert legacy.read_bytes() == before


def test_default_engine_keeps_bundled_configuration_when_local_file_is_missing(delivery_paths):
    _, legacy, local = delivery_paths
    assert DeliveryEngine().config_file == legacy
    assert not local.exists()


def test_explicit_base_keeps_its_own_configuration(delivery_paths):
    system, legacy, local = delivery_paths
    _preferences(local, "custom")
    assert DeliveryEngine(base_path=system).config_file == legacy


def test_broken_local_preferences_do_not_activate_bundled_destinations(delivery_paths, capsys):
    _, _, local = delivery_paths
    _preferences(local, "custom")
    local.write_text("private-marker", encoding="utf-8")

    engine = DeliveryEngine()

    assert engine.config_file == local
    assert engine.config == engine._get_default_config()
    assert "private-marker" not in capsys.readouterr().out
