"""PB-13 (#3996): Homecontrol/Robotik-Routen gehorchen der Rechtematrix, E-Stop
ist persistent, HA-Connector validiert URL-Bausteine. Kein Netz, kein Provider."""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from gui import server

AUTH = {"Authorization": "Bearer pb13-fixture"}
READ_ROUTES = [
    "/api/homecontrol/devices",
    "/api/homecontrol/energy",
    "/api/robotics/capabilities",
    "/api/robotics/telemetry",
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    perms = tmp_path / "capability_permissions.json"
    perms.write_text(json.dumps({"smarthome_robotics": False}), encoding="utf-8")
    monkeypatch.setattr(server, "_CAPABILITY_PERMISSIONS_FILE", perms)
    monkeypatch.setattr(server, "_ROBOTICS_ESTOP_FILE", tmp_path / "robotics_estop.json")
    monkeypatch.setattr(server, "validate_token", lambda t: {"id": 1} if t == "pb13-fixture" else None)

    def grant(value: bool):
        perms.write_text(json.dumps({"smarthome_robotics": value}), encoding="utf-8")

    return grant


def _client():
    return TestClient(server.app)


PERMISSION_REQUIRED = {
    "error": "permission_required",
    "permission": "smarthome_robotics",
    "hint": "Freigabe unter /api/permissions bzw. Einstellungen → Rechte",
}


@pytest.mark.parametrize("granted", [False, True])
@pytest.mark.parametrize("path", READ_ROUTES)
def test_read_routes_work_without_grant_and_are_marked_demo(env, path, granted):
    env(granted)
    with _client() as c:
        r = c.get(path)
    assert r.status_code == 200
    body = r.json()
    assert body.get("demo") is True or all(d["demo"] is True for d in body["devices"])


def test_estop_needs_device_auth(env):
    with _client() as c:
        assert c.post("/api/robotics/estop", json={}).status_code == 401


def test_estop_works_without_grant_and_blocks_actuation_until_reset(env):
    from hub._services.ocean_stack_bridge import load_robotics_module

    robotics = load_robotics_module()

    def actuate():
        return robotics.RoboticsHub(state_path=server._ROBOTICS_ESTOP_FILE).robot_actuate("gripper", 0.1)

    assert actuate()["status"] == "actuated"  # before: free
    with _client() as c:
        r = c.post("/api/robotics/estop", headers=AUTH, json={"reason": "test"})  # no grant needed
        assert r.status_code == 200
        assert r.json()["status"] == "emergency_stopped"
        assert r.json()["persisted"] is True
        with pytest.raises(robotics.RoboticsSafetyViolationError, match="E-Stop active"):
            actuate()
        assert c.get("/api/robotics/telemetry").json()["emergency_stopped"] is True  # readable without grant
        env(False)
        denied = c.post("/api/robotics/estop/reset", headers=AUTH)  # reset needs grant
        assert denied.status_code == 403
        assert denied.json() == PERMISSION_REQUIRED
        with pytest.raises(robotics.RoboticsSafetyViolationError):
            actuate()
        env(True)
        assert c.post("/api/robotics/estop/reset", headers=AUTH).status_code == 200
    assert actuate()["status"] == "actuated"


def test_estop_reset_needs_device_auth(env):
    env(True)
    with _client() as c:
        assert c.post("/api/robotics/estop/reset").status_code == 401


# --- BACH-interne Kopie des HA-Connectors -----------------------------------

def _ha():
    from connectors.base import ConnectorConfig
    from connectors.homeassistant_connector import HomeAssistantConnector

    return HomeAssistantConnector(ConnectorConfig(
        name="ha", connector_type="homeassistant", endpoint="http://ha.local:8123",
        auth_type="token", auth_config={"access_token": "T"}))


@pytest.mark.parametrize("domain,service,data", [
    ("../config", "turn_on", None), ("light", "a/b", None), ("light", "turn_on?x=1", None),
    ("light", "turn_on#f", None), ("http://evil", "x", None), ("light", "turn on", None),
    ("shell_command", "run", None), ("hassio", "host_reboot", None),
    ("light", "turn_on", {"entity_id": "../../config"}),
    ("light", "turn_on", {"entity_id": ["light.a", "light/b"]}),
    ("light", "turn_on", {"entity_id": "light.a\n"}),
])
def test_ha_call_service_rejects_without_network(domain, service, data):
    with patch("urllib.request.urlopen") as m:
        assert _ha().call_service(domain, service, data) is False
        m.assert_not_called()


def test_ha_call_service_valid_still_goes_out():
    resp = MagicMock()
    resp.read.return_value = b"[]"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp) as m:
        assert _ha().call_service("light", "turn_on", {"entity_id": "light.wohnzimmer"}) is True
    assert m.call_args[0][0].full_url.endswith("/api/services/light/turn_on")


@pytest.mark.parametrize("entity_id", [
    "../../etc/passwd",
    "light",
    "light/wohnzimmer",
    "light.wohnzimmer?x=1",
    "light.wohnzimmer\n",
    "light.wohnzimmer#top",
    "http://evil.com/state",
])
def test_ha_get_state_rejects_without_network(entity_id):
    with patch("urllib.request.urlopen") as m:
        assert _ha().get_state(entity_id) is None
        m.assert_not_called()


def test_ha_get_state_valid_calls_api():
    resp = MagicMock()
    resp.read.return_value = b'{"state": "on", "entity_id": "light.wohnzimmer"}'
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp) as m:
        state = _ha().get_state("light.wohnzimmer")
    assert state == {"state": "on", "entity_id": "light.wohnzimmer"}
    assert m.call_args[0][0].full_url.endswith("/api/states/light.wohnzimmer")


@pytest.mark.parametrize("entity_id", [
    "../../etc/passwd",
    "sensor",
    "sensor/temperature",
    "sensor.temperature?hours=24",
    "sensor.temperature\n",
])
def test_ha_get_history_rejects_without_network(entity_id):
    with patch("urllib.request.urlopen") as m:
        assert _ha().get_history(entity_id) == []
        m.assert_not_called()


def test_ha_get_history_valid_calls_api():
    resp = MagicMock()
    resp.read.return_value = b'[{"entity_id": "sensor.temperature", "state": "21.5"}]'
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp) as m:
        history = _ha().get_history("sensor.temperature", hours=12)
    assert len(history) == 1
    assert history[0]["entity_id"] == "sensor.temperature"
    url = m.call_args[0][0].full_url
    assert "/api/history/period/" in url
    assert "filter_entity_id=sensor.temperature" in url


@pytest.mark.parametrize("event_type", [
    "../evil",
    "ha/event",
    "event\n",
    "event with space",
    "event?x=1",
    "event#frag",
    "*event*",
    "a" * 65,  # longer than 64 chars
    "",
])
def test_ha_fire_event_rejects_without_network(event_type):
    with patch("urllib.request.urlopen") as m:
        assert _ha().fire_event(event_type, {"key": "val"}) is False
        m.assert_not_called()


@pytest.mark.parametrize("event_type", [
    "custom_event",
    "ha.event",
    "device.button_1-pressed",
    "HOMEASSISTANT_START",
    "test_event.dot_and-dash.v1",
])
def test_ha_fire_event_valid_calls_api(event_type):
    resp = MagicMock()
    resp.read.return_value = b'{"message": "Event fired."}'
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=resp) as m:
        assert _ha().fire_event(event_type, {"button": 1}) is True
    assert m.call_args[0][0].full_url.endswith(f"/api/events/{event_type}")
