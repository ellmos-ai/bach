"""Permission updates use isolated files and authenticated HTTP, never providers."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gui import server


AUTH = {"Authorization": "Bearer permission-fixture"}


@pytest.fixture
def permissions_file(tmp_path, monkeypatch):
    target = tmp_path / "capability_permissions.json"
    target.write_text(json.dumps({"camera": True}), encoding="utf-8")
    monkeypatch.setattr(server, "_CAPABILITY_PERMISSIONS_FILE", target)
    monkeypatch.setattr(server, "validate_token", lambda token: {"id": 1} if token == "permission-fixture" else None)
    return target


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_permission_mutations_require_device_auth(permissions_file, method):
    before = permissions_file.read_bytes()
    with TestClient(server.app) as client:
        response = client.request(method, "/api/permissions", json={"key": "camera", "enabled": False})
    assert response.status_code == 401
    assert permissions_file.read_bytes() == before


def test_authenticated_update_is_persisted_and_read_back(permissions_file):
    with TestClient(server.app) as client:
        response = client.post("/api/permissions", headers=AUTH, json={"key": "camera", "enabled": False})
        readback = client.get("/api/permissions")
    assert response.status_code == 200
    assert response.json()["permissions"]["camera"] is False
    assert readback.json()["permissions"]["camera"] is False
    assert json.loads(permissions_file.read_text())["camera"] is False


@pytest.mark.parametrize("headers,status", [
    ({"Authorization": "Bearer invalid-fixture"}, 401),
    ({**AUTH, "Origin": "https://other.invalid"}, 403),
])
def test_invalid_identity_and_cross_origin_do_not_write(permissions_file, headers, status):
    before = permissions_file.read_bytes()
    with TestClient(server.app) as client:
        response = client.post("/api/permissions", headers=headers, json={"key": "camera", "enabled": False})
    assert response.status_code == status
    assert permissions_file.read_bytes() == before


@pytest.mark.parametrize("payload", [
    {"key": "camera", "enabled": "false"},
    {"key": "camera", "enabled": 1},
    {"key": "camera", "enabled": None},
    {"permissions": {"camera": False, "microphone": "true"}},
    {"key": "unknown", "enabled": True}, {},
])
def test_invalid_updates_do_not_change_file(permissions_file, payload):
    before = permissions_file.read_bytes()
    with TestClient(server.app) as client:
        response = client.post("/api/permissions", headers=AUTH, json=payload)
    assert response.status_code == 400
    assert permissions_file.read_bytes() == before


def test_replace_failure_is_reported_and_original_is_intact(permissions_file, monkeypatch):
    before = permissions_file.read_bytes()

    def denied(*args):
        raise PermissionError("synthetic private write denial")

    monkeypatch.setattr(server.os, "replace", denied)
    with TestClient(server.app) as client:
        response = client.post("/api/permissions", headers=AUTH, json={"key": "camera", "enabled": False})
    assert response.status_code == 503
    assert permissions_file.read_bytes() == before
    assert list(permissions_file.parent.iterdir()) == [permissions_file]


@pytest.mark.parametrize("readback", ["{}", "{invalid"])
def test_unconfirmed_readback_never_reports_success(permissions_file, monkeypatch, readback):
    original_replace = server.os.replace
    original_read = Path.read_text
    replaced = []

    def replace(source, destination):
        original_replace(source, destination)
        replaced.append(True)

    def read(path, *args, **kwargs):
        if path == permissions_file and replaced:
            return readback
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(server.os, "replace", replace)
    monkeypatch.setattr(Path, "read_text", read)
    with TestClient(server.app) as client:
        response = client.post("/api/permissions", headers=AUTH, json={"key": "camera", "enabled": False})
    assert response.status_code == 503


@pytest.mark.parametrize("saved", ['{"camera":"false"}', '{"camera":1}', '[]', '{invalid'])
def test_malformed_permissions_never_grant_capabilities(permissions_file, saved):
    permissions_file.write_text(saved, encoding="utf-8")
    assert not any(server._load_capability_permissions().values())


def _toggle_method():
    source = Path(server.__file__).resolve().parent.parent / "hub" / "_services" / "chat" / "chat_tray.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_make_permission_toggle_action")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[method.name]


@pytest.mark.parametrize("answer", [None, {}, {"permissions": {"camera": True}}])
def test_tray_preserves_state_until_server_confirms(answer):
    errors = []
    tray = SimpleNamespace(permissions={"camera": True}, gui_url="http://fixture.invalid",
                           _api=lambda *a, **k: answer, _update_icon=lambda: None,
                           _notify_error=lambda message: errors.append(message))
    _toggle_method()(tray, "camera")()
    assert tray.permissions["camera"] is True
    assert errors


def test_tray_uses_confirmed_server_state():
    tray = SimpleNamespace(permissions={"camera": True}, gui_url="http://fixture.invalid",
                           _api=lambda *a, **k: {"permissions": {"camera": False}},
                           _update_icon=lambda: None, _notify_error=lambda message: pytest.fail(message))
    _toggle_method()(tray, "camera")()
    assert tray.permissions["camera"] is False
